"""Diff helpers shared by build-explanation.py and measure-change.py.

Captures one or several git diffs, leaves out files that may hold secrets, scans what
remains for credential-shaped text, and classifies files the way the page's Diff review
part does. Reports name a path and a line, never the matched value.

The filter fails closed: a block whose path cannot be read, a combined diff and a binary
patch all stay off the page and are listed as left out.

Standard library only.
"""

import fnmatch
import html
import json
import os
import re
import shlex
import shutil
import subprocess

# Always left out, matched against the file name, ignoring case.
SECRET_FILES = [
    ".env", ".env.*", "*.env", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "*.ppk",
    "*.tfvars", "*.tfstate", "*.tfstate.*", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".npmrc", ".netrc", ".pgpass", ".htpasswd", ".pypirc", ".dockerconfigjson", "kubeconfig",
    "service-account*.json", "token.json", "auth.json", ".s3cfg", ".my.cnf", "wp-config.php",
]
# Key material and login files: even a line's first word can be the secret, so no setting names.
NO_SETTING_NAMES = ["*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks", "*.ppk", "id_rsa*", "id_dsa*",
                    "id_ecdsa*", "id_ed25519*", ".netrc", ".pgpass", ".htpasswd", ".npmrc", ".pypirc"]
# Left out unless the file is code or prose: the credential scan covers those, and a file
# such as password_reset.py is what the reader came to see.
SECRET_WORDS = ["*secret*", "*credential*", "*password*"]
SECRET_DIRS = {"secrets", "credentials", ".ssh", ".aws", ".gnupg", ".kube", ".docker"}
WORD_SAFE_PATH = re.compile(r"\.(go|py|js|jsx|ts|tsx|mjs|cjs|java|kt|kts|rs|c|cc|cpp|h|hpp|cs|rb|php|swift|scala|lua|dart|md|mdx|rst|adoc)$", re.I)

# Keep these in step with fileType() in assets/template.html.
GENERATED_PATH = re.compile(r"(^|/)(vendor|node_modules|dist|third_party)/|\.min\.(js|css)$|\.generated\.|_generated\.|\.pb\.go$|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock|poetry\.lock|composer\.lock|Gemfile\.lock|uv\.lock)$", re.I)
TEST_PATH = re.compile(r"(^|/)(tests?|testing|__tests__|spec|testdata|test_data|fixtures?|__fixtures__|__snapshots__)/|[._-](test|spec)\.[^/]+$|_test\.go$|(^|/)test_[^/]+$|(^|/)conftest\.py$|\.snap$", re.I)
TEST_CLASS = re.compile(r"[a-z]Tests?\.(java|kt|cs|scala|swift|php)$")
DOC_PATH = re.compile(r"\.(md|mdx|rst|adoc|txt)$|(^|/)(README|CHANGELOG|LICENSE)[^/]*$", re.I)
CONFIG_PATH = re.compile(r"\.(json|jsonc|ya?ml|toml|ini|cfg|conf|env|xml|lock|properties|gradle)$|(^|/)(\.[^/]+|Dockerfile|Makefile|Procfile)$", re.I)
SOURCE_PATH = re.compile(r"\.(go|py|js|jsx|ts|tsx|mjs|cjs|java|kt|kts|rs|c|cc|cpp|h|hpp|cs|rb|php|swift|scala|sh|bash|ps1|psm1|sql|html|css|scss|vue|svelte|lua|dart)$", re.I)
SHELL_PATH = re.compile(r"\.(sh|bash|ps1|psm1)$|(^|/)Dockerfile[^/]*$", re.I)

# Every repeat is bounded: a fixture line can be megabytes long.
KEYWORD = r"(?:password|passwd|passphrase|pwd|secret|token|bearer|credentials?|api[_-]?key|access[_-]?key|account[_-]?key|private[_-]?key|auth[_-]?key)"
# The value needs only its opening quote, so a value longer than the bound still counts.
ASSIGNED = re.compile(KEYWORD + r"""[\w-]{0,64}\\?["']?\]?(?:(?:\s{0,2}:\s{0,2}|\s{1,2})[A-Za-z_]\w{0,32})?\s{0,4}(?::=|=>|[:=])\s{0,4}\\?["']([^"'\\\s]{6,256})""", re.I)
BARE_ASSIGNED = re.compile(r"""^\s{0,64}(?:[-{]\s{1,4})?(?:export\s{1,4}|ENV\s{1,4})?[\w.-]{0,64}""" + KEYWORD + r"""[\w.-]{0,64}\s{0,4}[:=]\s{0,4}([^\s"'#,}]{6,256})[\s,}]{0,8}(?:#.{0,256})?$""", re.I)
# Text the agent wrote: an assignment can sit anywhere on a line, for example in a <pre>.
WRITTEN_ASSIGNED = re.compile(r"""[\w.-]{0,64}""" + KEYWORD + r"""[\w.-]{0,64}\s{0,4}=\s{0,4}([^\s"'#<,;]{6,256})""", re.I)
FLAG_VALUE = re.compile(r"""--[\w-]{0,32}""" + KEYWORD + r"""[\w-]{0,32}=([^\s"']{6,256})""", re.I)
SETTER = re.compile(r"""\bset[\w]{0,16}""" + KEYWORD + r"""\w{0,16}\(\s{0,2}["']([^"'\s]{6,256})""", re.I)
CONNECTION = re.compile(KEYWORD + r"""\s{0,2}=\s{0,2}([^;"'\s]{6,256});""", re.I)
TAGGED = re.compile(r"<" + KEYWORD + r"[\w-]{0,32}>([^<\s]{6,256})</", re.I)
URL_LOGIN = re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://[^/\s:@]{0,256}:([^\s@]{6,1024})@", re.I)
ALWAYS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY(?: BLOCK)?-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{20,255})")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,255}")),
    ("API key", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,255}|[sr]k_live_[A-Za-z0-9]{16,255}|AIza[0-9A-Za-z_-]{35})")),
    ("signed token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,2048}\.eyJ[A-Za-z0-9_-]{10,2048}\.[A-Za-z0-9_-]{5,2048}")),
    ("bearer token", re.compile(r"\bbearer\s{1,4}[A-Za-z0-9._~+/-]{20,512}", re.I)),
]
MASK = "<hidden-by-qexplain-change>"  # placeholder-shaped, so a masked line is not flagged again
PLACEHOLDER_WORDS = {"changeme", "change_me", "password", "placeholder", "example", "redacted", "none", "null", "undefined"}
PLACEHOLDER_FORMS = re.compile(r"\$\{[^}]*\}|\$\([^)]*\)|\$[A-Za-z_]\w*|%[A-Za-z_]\w*%|<[^<>]*>|\{\{.*\}\}|[A-Z][A-Z0-9_]*|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|[A-Za-z_][\w.]*\(.*\)")
MADE_UP = re.compile(r"test|fake|dummy|mock|sample|wrong|invalid|foo|bar|baz|example", re.I)

# Every other option is refused: some run code or write files, and others reshape the diff past the scan.
ALLOWED_OPTION = re.compile(r"--cached|--staged|--merge-base|-U\d{1,4}|--unified=\d{1,4}")
PLAN_SCOPE = re.compile(r"^\w+\(([0-9]{6}(?:-[0-9]{4})?_[A-Za-z0-9_-]+)\)")


def file_type(path):
    if GENERATED_PATH.search(path):
        return "generated"
    if TEST_PATH.search(path) or TEST_CLASS.search(path):
        return "test"
    if DOC_PATH.search(path):
        return "doc"
    if CONFIG_PATH.search(path):
        return "config"
    if SOURCE_PATH.search(path):
        return "src"
    return "other"


def parse_target(text):
    """Turn '<label>=<repo>::<diff args>' into its three parts."""
    head, sep, diff_args = text.partition("::")
    label, eq, repo = head.partition("=")
    if not (sep and eq and label and repo and diff_args):
        raise ValueError(f"--target must read <label>=<repo>::<diff args>, got {text!r}")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", label):
        raise ValueError(f"--target label {label!r} may hold only letters, digits, dot, dash and underscore")
    if file_type(label + "/x.go") != "src":
        raise ValueError(f"--target label {label!r} would change how the repo's files are classified; pick another")
    return label, repo, diff_args


def capture(repo, diff_args, label=None):
    """Return the unified diff as text. With a label, every path starts with <label>/."""
    tokens = shlex.split(diff_args)
    for tok in tokens:
        if tok == "--":
            break
        if tok.startswith("-") and not ALLOWED_OPTION.fullmatch(tok):
            raise ValueError(f"diff option {tok} is not allowed here; pass only revisions, --cached, --merge-base, -U<n> and paths")
    prefix = f"{label}/" if label else ""
    # -M -C keep a rename's two names in one block, so the filter sees where the content came from.
    forced = ["--no-color", "--no-ext-diff", "--no-textconv", "-M", "-C", f"--src-prefix=a/{prefix}", f"--dst-prefix=b/{prefix}"]
    cmd = ["git", "-C", repo, "-c", "core.quotepath=off", "diff", "--unified=3"] + forced + tokens
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("git diff failed: " + proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace")


def unquote(text):
    """Decode a path git printed in C style. A plain path passes through unchanged."""
    if not (len(text) >= 2 and text[0] == '"' and text[-1] == '"'):
        return text
    out, i, body = bytearray(), 0, text[1:-1]
    simple = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
        elif body[i + 1:i + 2] in simple:
            out.append(simple[body[i + 1]])
            i += 2
        else:
            out.append(int(body[i + 1:i + 4], 8) & 255)
            i += 4
    return out.decode("utf-8", "replace")


def strip_prefix(name):
    return name[2:] if name[:2] in ("a/", "b/") else name


def header_name(rest):
    """Read the one name in 'a/X b/X'. Returns None when the two sides differ or cannot be read."""
    quoted = re.fullmatch(r'("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*")', rest)
    if quoted:
        left, right = unquote(quoted.group(1)), unquote(quoted.group(2))
    else:
        if len(rest) % 2 == 0:
            return None
        mid = len(rest) // 2
        if rest[mid] != " ":
            return None
        left, right = rest[:mid], rest[mid + 1:]
    if left == right:
        return left
    if left[1:2] == "/" and right[1:2] == "/" and left[2:] == right[2:]:
        return right[2:]
    return None


def split_files(raw):
    """Split a unified diff into [(path, block text)], one per file. A path of None means unreadable."""
    files, start = [], None
    lines = raw.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(("diff --git ", "diff --cc ", "diff --combined ")):
            if start is not None:
                block = "\n".join(lines[start:i])
                files.append((block_names(block)[0], block))
            start = i
    if start is not None:
        block = "\n".join(lines[start:]).rstrip("\n")
        files.append((block_names(block)[0], block))
    return files


def block_names(block):
    """Return (main path or None, every name the block mentions). None fails closed: the block is left out."""
    try:
        return read_block_names(block)
    except (ValueError, IndexError):
        return None, []


def read_block_names(block):
    lines = block.split("\n")
    first = lines[0]
    if first.startswith(("diff --cc ", "diff --combined ")):
        name = unquote(first.split(" ", 2)[2])
        return name, [name]
    names, new_path, old_path, moved_to = [], None, None, None
    for line in lines[1:]:
        if line.startswith("@@") or line.startswith("GIT binary patch"):
            break
        if line.startswith("+++ ") and line[4:].rstrip("\t") != "/dev/null":
            new_path = strip_prefix(unquote(line[4:].rstrip("\t")))
            names.append(new_path)
        elif line.startswith("--- ") and line[4:].rstrip("\t") != "/dev/null":
            old_path = strip_prefix(unquote(line[4:].rstrip("\t")))
            names.append(old_path)
        elif line.startswith(("rename from ", "copy from ")):
            names.append(unquote(line.split(" ", 2)[2]))
        elif line.startswith(("rename to ", "copy to ")):
            moved_to = unquote(line.split(" ", 2)[2])
            names.append(moved_to)
    from_header = header_name(first[len("diff --git "):])
    if from_header is None and moved_to is None:
        return None, names  # two different names and no rename line: the block contradicts itself
    path = new_path or old_path or moved_to or from_header
    if path:
        names.append(path)
    return path, names


def counts(block):
    """Count changed lines inside hunks only: a removed SQL comment can look like a --- header."""
    add = rem = 0
    in_hunk = False
    for line in block.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            add += 1
        elif in_hunk and line.startswith("-"):
            rem += 1
    return add, rem


def normalise(pattern):
    return pattern.replace("\\", "/").lower()


def pattern_matches(path, pattern):
    path, pat = path.lower(), normalise(pattern)
    pat = pat[2:] if pat.startswith("./") else pat
    pat = pat.strip("/")
    return (path == pat or path.endswith("/" + pat) or path.startswith(pat + "/") or ("/" + pat + "/") in path
            or fnmatch.fnmatchcase(path, pat) or fnmatch.fnmatchcase(path, "*/" + pat))


def secret_named(path):
    base = os.path.basename(path).lower()
    if any(fnmatch.fnmatchcase(base, p) for p in SECRET_FILES):
        return True
    if any(part.lower() in SECRET_DIRS for part in path.split("/")[:-1]):
        return True
    return not WORD_SAFE_PATH.search(base) and any(fnmatch.fnmatchcase(base, p) for p in SECRET_WORDS)


def filter_files(files, patterns):
    """Return (kept files, [{path, add, del, reason}] for those left out, patterns that matched nothing)."""
    kept, left_out, used = [], [], set()
    for path, block in files:
        names = block_names(block)[1]
        add, rem = counts(block)
        first = block.split("\n", 1)[0]
        reason = None
        if path is None:
            reason, path = "path could not be read", first
        elif first.startswith(("diff --cc ", "diff --combined ")):
            reason = "combined diff of a conflict"
        elif "\nGIT binary patch\n" in block:
            reason = "binary patch"
        for name in names:
            if secret_named(name):
                reason = reason or "file name suggests secrets"
            for pat in patterns:
                if pattern_matches(name, pat):
                    used.add(pat)
                    reason = reason or "excluded by --exclude"
        if reason:
            left_out.append({"path": path, "add": add, "del": rem, "reason": reason})
        else:
            kept.append((path, block))
    return kept, left_out, [p for p in patterns if p not in used]


def made_up_value(value):
    """A short value that reads as a test word. A long one may be a real token whose name says 'test'."""
    return len(value) < 20 and bool(MADE_UP.search(value))


def is_placeholder(value):
    low = value.lower()
    if PLACEHOLDER_FORMS.fullmatch(value):
        return True
    return low in PLACEHOLDER_WORDS or low.startswith(("your_", "your-")) or set(low) <= set("x*")


def line_hits(text, config_like, written=False):
    """Return [(kind, looks made up)] for one line. The value itself never leaves this function."""
    hits = []
    for kind, rx in ALWAYS:
        if rx.search(text):
            hits.append((kind, False))
    shapes = [("assigned secret", rx) for rx in (ASSIGNED, CONNECTION, TAGGED, FLAG_VALUE, SETTER)]
    if config_like:
        shapes.append(("assigned secret", BARE_ASSIGNED))
    if written:
        shapes.append(("assigned secret", WRITTEN_ASSIGNED))
    for kind, rx in shapes:
        for m in rx.finditer(text):
            if not is_placeholder(m.group(1)):
                hits.append((kind, made_up_value(m.group(1))))
    for m in URL_LOGIN.finditer(text):
        value = m.group(1)
        if not is_placeholder(value) and not re.match(r"\d+(/|$)", value):
            hits.append(("login in a URL", made_up_value(value)))
    return hits


def scan_files(files):
    """Scan every content line, context included: context is copied into the page too."""
    found = []
    for path, block in files:
        kind = file_type(path)
        config_like = kind in ("config", "other", "generated") or bool(SHELL_PATH.search(path))
        new_line = old_line = 0
        in_hunk = False
        for line in block.split("\n"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                old_line, new_line, in_hunk = int(m.group(1)), int(m.group(2)), True
                continue
            if not in_hunk:
                # Lines before the first hunk are copied into the page too.
                if not line.startswith(("diff --git ", "index ", "--- ", "+++ ")):
                    for shape, _ in line_hits(line, True):
                        found.append({"path": path, "side": "header", "line": 0, "kind": shape, "made_up": False, "test_file": False})
                continue
            if line.startswith("\\"):
                continue
            sign = line[:1]
            side, where = ("old", old_line) if sign == "-" else ("new", new_line)
            for shape, made_up in line_hits(line[1:], config_like):
                found.append({"path": path, "side": side, "line": where, "kind": shape,
                              "made_up": made_up, "test_file": kind == "test"})
            if sign == "-":
                old_line += 1
            elif sign == "+":
                new_line += 1
            else:
                old_line += 1
                new_line += 1
    return found


def mask_line(text, config_like):
    """Replace each credential-shaped value on a line. The rest of the line stays readable."""
    spans = [m.span(0) for _, rx in ALWAYS for m in rx.finditer(text)]
    shapes = [ASSIGNED, CONNECTION, TAGGED, FLAG_VALUE, SETTER, URL_LOGIN] + ([BARE_ASSIGNED] if config_like else [])
    for rx in shapes:
        spans += [m.span(1) for m in rx.finditer(text) if not is_placeholder(m.group(1))]
    for start, end in sorted(set(spans), reverse=True):
        text = text[:start] + MASK + text[end:]
    return text


def mask_files(files, keys):
    """Mask the values on the lines named <path>:<side>:<line>. Returns (files, keys that matched nothing)."""
    wanted, used, out = set(keys), set(), []
    for path, block in files:
        config_like = file_type(path) in ("config", "other", "generated") or bool(SHELL_PATH.search(path))
        lines = block.split("\n")
        new_line = old_line = 0
        in_hunk = False
        for i, line in enumerate(lines):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                old_line, new_line, in_hunk = int(m.group(1)), int(m.group(2)), True
                continue
            if not in_hunk or line.startswith("\\"):
                continue
            sign = line[:1]
            key = f"{path}:{'old' if sign == '-' else 'new'}:{old_line if sign == '-' else new_line}"
            if key in wanted:
                lines[i] = sign + mask_line(line[1:], config_like)
                used.add(key)
            if sign != "+":
                old_line += 1
            if sign != "-":
                new_line += 1
        out.append((path, "\n".join(lines)))
    return out, sorted(wanted - used)


def hit_key(hit):
    return f"{hit['path']}:{hit['side']}:{hit['line']}"


def safe_path(path):
    """Escape control characters, so a file name cannot forge a report line."""
    return re.sub(r"[\x00-\x1f\x7f]", lambda m: f"\\x{ord(m.group(0)):02x}", path)


def looks_made_up(hit):
    return bool(hit["made_up"] and hit["test_file"])


def hit_line(hit):
    made_up = "yes" if looks_made_up(hit) else "no"
    return f"CREDENTIAL\t{safe_path(hit['path'])}\t{hit['side']} {hit['line']}\t{hit['kind']}\tmade-up-test-value={made_up}"


def scan_text(name, text):
    """Scan text the agent wrote, as written, with entities decoded, and with tags removed."""
    found = []
    decoded = html.unescape(text)
    plain = re.sub(r"<[^<>\n]{0,512}>", " ", decoded)
    # The last variant joins the lines, for an assignment split across two lines of a <pre>.
    for variant in (text, decoded, plain, " ".join(plain.split())):
        for i, line in enumerate(variant.split("\n"), 1):
            for shape, _ in line_hits(line, True, written=True):
                found.append({"path": name, "side": "file", "line": i, "kind": shape, "made_up": False, "test_file": False})
    unique = {hit_key(h) + h["kind"]: h for h in found}
    return list(unique.values())


def scan_json(name, data):
    """Scan the decoded strings of a JSON file, where quotes are no longer escaped."""
    found = []

    def walk(node, where):
        if isinstance(node, str):
            for hit in scan_text(f"{name} {where}".strip(), node):
                found.append(hit)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{where}[{i}]")
        elif isinstance(node, dict):
            for key, item in node.items():
                walk(key, f"{where}.key")
                walk(item, f"{where}.{key}")

    walk(data, "")
    return found


def scan_content_file(name, text):
    """Scan one content file. Valid JSON is scanned through its decoded strings."""
    if name.endswith(".json"):
        try:
            return scan_json(name, json.loads(text))
        except ValueError:
            pass
    return scan_text(name, text)


def log_range(diff_args):
    """Work out which commits a diff covers. Returns (git log arguments, or None, and the reason)."""
    tokens = shlex.split(diff_args)
    cut = tokens.index("--") if "--" in tokens else len(tokens)
    revs = [t for t in tokens[:cut] if not t.startswith("-")]
    paths = tokens[cut:]
    if "--cached" in tokens[:cut] or "--staged" in tokens[:cut]:
        return None, "staged changes have no commits"
    if not revs:
        return None, "no revision given"
    if len(revs) == 1:
        rev = revs[0]
        if "..." in rev:
            return [rev.replace("...", "..", 1)] + paths, ""
        if ".." in rev or rev.endswith(("^!", "^-")):
            return [rev] + paths, ""
        return [rev + "..HEAD"] + paths, ""
    if len(revs) == 2:
        return [revs[0] + ".." + revs[1]] + paths, ""
    return None, "more than two revisions"


def plans_in_range(repo, diff_args):
    """Return (plan slugs named by commit scopes, why the search was skipped, or '')."""
    args, why = log_range(diff_args)
    if args is None:
        return [], why
    proc = subprocess.run(["git", "-C", repo, "log", "--format=%s"] + args, capture_output=True)
    if proc.returncode != 0:
        return [], "git log failed on that range"
    found = []
    for subject in proc.stdout.decode("utf-8", "replace").split("\n"):
        m = PLAN_SCOPE.match(subject)
        if m and m.group(1) not in found:
            found.append(m.group(1))
    return found, ""


def setting_names(path, block):
    """Name the settings a left-out file's change touches. Values are never returned.

    A name must look like one: short, starting with a letter, and not token-like. A file
    of key material or logins gets no names at all, because a line's first word can be the secret.
    """
    allow_names = not any(fnmatch.fnmatchcase(os.path.basename(path).lower(), p) for p in NO_SETTING_NAMES)
    names = []
    in_hunk = False
    for line in block.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk or not line or line[0] not in "+-":
            continue
        m = re.match(r"\s{0,64}(?:-\s{1,4})?(?:export\s{1,4})?([A-Za-z_][\w.-]{0,63})\s{0,4}(:|=)(.*)$", line[1:]) if allow_names else None
        name = m.group(1) if m else None
        if name and m.group(2) == "=" and not m.group(3).strip():
            name = None  # 'abc=' is base64 padding as often as an empty setting
        if name and (line_hits(name, True) or (len(name) >= 16 and re.search(r"\d", name) and re.search(r"[a-z]", name) and re.search(r"[A-Z]", name))):
            name = None
        names.append(line[0] + (name or "(line without a setting name)"))
    return names


# ---- Subsystems, D2 lookup and D2 source refusals (shared by measure-change.py and build-explanation.py) ----

PRODUCTION_KINDS = ("src", "config", "other")  # tests, docs and generated files belong to no subsystem
SUBSYSTEM_DEPTH = 2
D2_REFUSALS = [
    (re.compile(r"""\bicon["']?\s*:""", re.I), "refused construct icon:, which pulls an image from outside the page. Remove it and use a class instead"),
    (re.compile(r"@import", re.I), "refused construct @import, which reads another file. Inline what you need"),
    (re.compile(r"\.\.\.\s*@"), "refused construct ...@ import, which reads another file. Inline what you need"),
    # Any @ that starts a token imports a file, quoted or not, so refuse whatever follows it.
    (re.compile(r"""(?:^|[\s:{;\[,(])@\S""", re.M), "refused construct @ import (quoted or not), which reads another file. Inline what you need"),
    (re.compile(r"""(?:^|[\s{;,])["']?link["']?\s*:""", re.I | re.M), "refused construct link:, which writes a clickable href into the page. Remove it"),
    (re.compile(r"""(?:^|[\s{;,])["']?(?:layers|scenarios|steps)["']?\s*:""", re.M), "refused construct layers:, scenarios: or steps:, which make d2 write extra files. Draw one diagram per file"),
    (re.compile(r"\bd2-config\b"), "refused construct d2-config, which would override the layout, theme and sketch settings the build owns. Remove it"),
]


def subsystem_of(path, labelled=False):
    """Name the area a file belongs to: the repo label (labelled targets only) plus the first two directories."""
    parts = path.split("/")
    label = parts.pop(0) if labelled and len(parts) > 1 else None
    segs = ([label] if label else []) + parts[:-1][:SUBSYSTEM_DEPTH]
    return "/".join(segs) if segs else "(repo root)"


def production_subsystems(paths, labelled=False):
    """Distinct subsystems of the production files among paths, in first-seen order."""
    return list(dict.fromkeys(subsystem_of(p, labelled) for p in paths if file_type(p) in PRODUCTION_KINDS))


def find_d2():
    """Path of the d2 executable, or None. QEXPLAIN_D2 wins; when it is set but names no file, d2 counts as not found."""
    env = os.environ.get("QEXPLAIN_D2")
    if env:
        return env if os.path.isfile(env) else None
    return shutil.which("d2")


def d2_version(exe):
    """The d2 version text (for example v0.9.0), or None when it cannot be read."""
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    text = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    return text[0].strip() if proc.returncode == 0 and text else None


def d2_refusals(text):
    """Reasons a D2 source may not be rendered. An empty list means it may."""
    return [why for rx, why in D2_REFUSALS if rx.search(text)]
