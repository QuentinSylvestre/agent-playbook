#!/usr/bin/env python3
"""deploy_model.py -- the agent-playbook deploy model, in one place.

Setup (setup/setup.py) writes from it and verify-deployment.py checks a deployed tree against it;
verify-mass.py reads the manifest through it. It owns:

  - inventory.tsv parsing (read_manifest) and destination expansion (expand_dest, kiro_ide_user_dir)
  - the Kiro overlay merge (merge_overlay_bytes, overlay_is_blank, aux_overlay_targets,
    has_any_overlay) and template rendering (render_template_bytes)
  - the generated-copy expected list (files_no_follow, generated_expected)
  - the deploy-lock grammar (LOCK_HEADER, is_lock_row, read_lock_lines, parse_lock, lock_bytes)

Stdlib only, Python 3.8+. Callers run under `-I`, which keeps this folder off sys.path, so they load
this file by path (importlib), never by `import deploy_model`.

Byte contract (merge and render; it was setup.ps1's, Q5 of plan 261114):
  - a source is read as [IO.File]::ReadAllText reads it: a BOM is detected and dropped, the rest is
    decoded as UTF-8 (invalid bytes become U+FFFD);
  - trailing CR and LF characters are stripped, interior line endings are kept;
  - an overlay is blank when only .NET Char.IsWhiteSpace characters remain (U+001C-U+001F are not
    white space there, unlike Python's str.isspace);
  - merged = shared + "\\n\\n" + overlay + "\\n" (blank overlay: shared + "\\n"); render = body with
    {{USER_HOME}} and {{PLAYBOOK_ROOT}} replaced by forward-slash roots, + "\\n"; written as UTF-8
    without a BOM.

The golden files under fixtures/deploy-model/ were produced by the retired setup twins, never by this
module; `--selftest` checks the module against them. Changing this module's bytes and a golden file in
the same commit needs a `Golden-reviewed:` line in the commit message (`--check-golden-history`).

Usage:
  python -I deploy_model.py --selftest
  python -I deploy_model.py --check-golden-history [--repo <path>] [--since <rev>]
"""

import hashlib
import os
import re
import stat
import sys

# --- manifest -----------------------------------------------------------------

KIND_SYMLINK_FILE = "symlink-file"
KIND_SYMLINK_DIR = "symlink-dir"
KIND_COPY_FILE = "copy-file"
KIND_COPY_DIR_RECURSIVE = "copy-dir-recursive"
KIND_MERGE_FILE = "merge-file"
KIND_TEMPLATE_FILE = "template-file"
KIND_SEED_FILE = "seed-file"
VALID_KINDS = (KIND_SYMLINK_FILE, KIND_SYMLINK_DIR, KIND_COPY_FILE, KIND_COPY_DIR_RECURSIVE,
               KIND_MERGE_FILE, KIND_TEMPLATE_FILE, KIND_SEED_FILE)
MODES = ("claude", "codex", "gemini", "kiro-always", "kiro")
KIRO_IDE_TOKEN = "<KIRO_IDE_USER>"


class ManifestError(Exception):
    """inventory.tsv is missing or malformed; the message is the line setup and the verifier print."""


class Entry(tuple):
    """One manifest row: (kind, dest, source, mode)."""
    __slots__ = ()

    def __new__(cls, kind, dest, source, mode):
        return tuple.__new__(cls, (kind, dest, source, mode))

    kind = property(lambda self: self[0])
    dest = property(lambda self: self[1])
    source = property(lambda self: self[2])
    mode = property(lambda self: self[3])


_COMMENT_RE = re.compile(r"^\s*#")
_BLANK_RE = re.compile(r"^\s*$")


def read_manifest(path):
    """-> [Entry]; ManifestError for a missing file, a row without 4 columns or an unknown kind.
    Lines split on CRLF, LF or CR; a last line without a newline counts; a UTF-8 BOM is dropped."""
    if not os.path.isfile(path):
        raise ManifestError("ERROR: manifest not found: %s" % path)
    with open(path, "rb") as fh:
        text = decode_net(fh.read())
    lines = re.split(r"\r\n|\n|\r", text)
    if lines and lines[-1] == "":
        lines.pop()
    entries = []
    for num, line in enumerate(lines, 1):
        if _COMMENT_RE.match(line) or _BLANK_RE.match(line):
            continue
        cols = line.split("\t")
        if len(cols) != 4:
            raise ManifestError("ERROR: manifest line %d has %d columns (expected 4): %s" % (num, len(cols), line))
        if cols[0] not in VALID_KINDS:
            raise ManifestError("ERROR: manifest line %d has unknown kind '%s': %s" % (num, cols[0], line))
        entries.append(Entry(*cols))
    return entries


def native_join(base, rel, windows):
    """base + rel with the platform's separator (Windows: Join-Path's form, every / turned to \\)."""
    if windows:
        base, rel = base.replace("/", "\\"), rel.replace("/", "\\")
        if not base:
            return rel
        return base.rstrip("\\") + "\\" + rel.lstrip("\\")
    return base.rstrip("/") + "/" + rel.lstrip("/")


def kiro_ide_user_dir(environ, home, windows):
    """The Kiro IDE per-user config folder: %APPDATA%\\Kiro\\User on Windows,
    ${XDG_CONFIG_HOME:-~/.config}/Kiro/User elsewhere."""
    if windows:
        appdata = environ.get("APPDATA") or ""
        return native_join(appdata, "Kiro/User", True)
    base = environ.get("XDG_CONFIG_HOME") or (home.rstrip("/") + "/.config")
    return base.rstrip("/") + "/Kiro/User"


def expand_dest(dest, home, kiro_ide, windows):
    """A manifest destination as a path: ~ is home, <KIRO_IDE_USER> the Kiro IDE folder."""
    if dest.startswith(KIRO_IDE_TOKEN + "/") or (windows and dest.startswith(KIRO_IDE_TOKEN + "\\")):
        return native_join(kiro_ide, dest[len(KIRO_IDE_TOKEN) + 1:], windows)
    if dest.startswith("~/") or (windows and dest.startswith("~\\")):
        return native_join(home, dest[2:], windows)
    return dest


# --- text, merge and render -----------------------------------------------------

# .NET Char.IsWhiteSpace: what String.Trim() strips.
NET_WS = ("\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
          "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000")


def decode_net(data):
    """Bytes decoded as [IO.File]::ReadAllText does: BOM detected and dropped, else UTF-8."""
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    if data[:4] == b"\xff\xfe\x00\x00":
        return data[4:].decode("utf-32-le", "replace")
    if data[:2] == b"\xff\xfe":
        return data[2:].decode("utf-16-le", "replace")
    if data[:2] == b"\xfe\xff":
        return data[2:].decode("utf-16-be", "replace")
    if data[:4] == b"\x00\x00\xfe\xff":
        return data[4:].decode("utf-32-be", "replace")
    return data.decode("utf-8", "replace")


def read_text(path):
    with open(path, "rb") as fh:
        return decode_net(fh.read())


def overlay_is_blank(path):
    """True when the overlay holds nothing but .NET white space (setup prints SKIPPED EMPTY OVERLAY)."""
    return not read_text(path).strip(NET_WS)


def merge_text(shared, overlay):
    """The merge of two decoded bodies (the byte contract in the module docstring)."""
    body = shared.rstrip("\r\n")
    if overlay.strip(NET_WS):
        return body + "\n\n" + overlay.rstrip("\r\n") + "\n"
    return body + "\n"


def merge_overlay_bytes(shared_file, overlay_file):
    """The bytes setup writes for a merged Kiro target: the shared file with the overlay appended."""
    return merge_text(read_text(shared_file), read_text(overlay_file)).encode("utf-8")


def forward_root(path):
    """A root in the form templates take: forward slashes, no trailing one."""
    p = path.replace("\\", "/")
    return p.rstrip("/") if len(p) > 1 else p


def render_text(body, user_home, playbook_root):
    body = body.rstrip("\r\n")
    body = body.replace("{{USER_HOME}}", forward_root(user_home))
    body = body.replace("{{PLAYBOOK_ROOT}}", forward_root(playbook_root))
    return body + "\n"


def render_template_bytes(source, user_home, playbook_root):
    """The bytes setup writes for a template-file or seed-file row. playbook_root must be the long
    form (no 8.3 short names) on Windows."""
    return render_text(read_text(source), user_home, playbook_root).encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --- overlays and generated copies ----------------------------------------------

OVERLAY_NAME = "OVERLAY.md"
RESERVED_OVERLAY = "SKILL.OVERLAY.md"
AUX_SUFFIX = ".OVERLAY.md"
COPY_SKIP_DIRS = ("__pycache__",)   # skipped in any letter case on Windows, as setup.ps1 -ne does
COPY_SKIP_DIR_EXACT = "fixtures"   # selftest data, read only from the repo (case-sensitive)


def is_reparse(path):
    """A symlink or a junction (any reparse point on Windows), never followed."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & 0x400)


def _scandir_sorted(path):
    with os.scandir(path) as it:
        return list(it)


def _entry_is_reparse(e):
    if e.is_symlink():
        return True
    try:
        attrs = getattr(e.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & 0x400)


def files_no_follow(root, windows):
    """The regular files under root, recursively, never entering a link, a __pycache__ folder or a
    fixtures folder. Paths are built from root as given (an 8.3 short name stays short)."""
    out = []
    stack = [root]
    while stack:
        d = stack.pop()
        for e in _scandir_sorted(d):
            if _entry_is_reparse(e):
                continue
            full = native_join(d, e.name, windows) if windows else d.rstrip("/") + "/" + e.name
            if e.is_dir(follow_symlinks=False):
                low = e.name.lower() if windows else e.name
                if low not in COPY_SKIP_DIRS and e.name != COPY_SKIP_DIR_EXACT:
                    stack.append(full)
            else:
                out.append(full)
    return out


def has_any_overlay(overlay_dir):
    """Does a providers/kiro/skills/<name> folder carry an overlay (OVERLAY.md or an aux
    <stem>.OVERLAY.md)? Such a skill deploys as a generated copy. SKILL.OVERLAY.md does not count."""
    if not os.path.isdir(overlay_dir):
        return False
    if os.path.exists(os.path.join(overlay_dir, OVERLAY_NAME)):
        return True
    for e in _scandir_sorted(overlay_dir):
        if (e.is_file() and e.name.lower().endswith(AUX_SUFFIX.lower())
                and e.name.lower() not in (OVERLAY_NAME.lower(), RESERVED_OVERLAY.lower())):
            return True
    return False


def aux_overlay_targets(overlay_dir, source_dir, warn=None):
    """[(target_name, overlay_path)] for every <stem>.OVERLAY.md except OVERLAY.md and the reserved
    SKILL.OVERLAY.md, whose shared target <stem>.md exists. warn(line) reports a skipped overlay."""
    out = []
    if not os.path.isdir(overlay_dir):
        return out
    for e in sorted(_scandir_sorted(overlay_dir), key=lambda x: x.name.lower()):
        if not e.is_file() or not e.name.lower().endswith(AUX_SUFFIX.lower()):
            continue
        if e.name.lower() == OVERLAY_NAME.lower():
            continue
        full = os.path.join(overlay_dir, e.name)
        if e.name.lower() == RESERVED_OVERLAY.lower():
            if warn:
                warn("  SKIPPED RESERVED: %s (SKILL.md uses bare OVERLAY.md; SKILL.OVERLAY.md is forbidden)" % full)
            continue
        target = e.name[:-len(AUX_SUFFIX)] + ".md"
        if not os.path.exists(os.path.join(source_dir, target)):
            if warn:
                warn("  SKIPPED AUX OVERLAY: %s (no shared target '%s')" % (full, target))
            continue
        out.append((target, full))
    return out


class Expected(object):
    """One file of a generated copy: kind copy-dir-recursive (src set) or merge-file (data set)."""
    __slots__ = ("kind", "src", "data", "hash")

    def __init__(self, kind, src, data, digest):
        self.kind, self.src, self.data, self.hash = kind, src, data, digest


def generated_expected(source_dir, overlay_dir, windows, warn=None, note=None):
    """The files a generated Kiro copy holds: {rel (/ separated): Expected}, in deploy order.
    note(line) reports a blank SKILL.md overlay; warn(line) a skipped aux overlay."""
    exp = {}
    sep = "\\" if windows else "/"
    for f in files_no_follow(source_dir, windows):
        rel = f[len(source_dir.rstrip(sep)) + 1:].replace("\\", "/")
        exp[rel] = Expected(KIND_COPY_DIR_RECURSIVE, f, None, "")
    skill_overlay = os.path.join(overlay_dir, OVERLAY_NAME)
    if os.path.exists(skill_overlay):
        if overlay_is_blank(skill_overlay) and note:
            note("  SKIPPED EMPTY OVERLAY: %s" % os.path.basename(source_dir.rstrip("\\/")))
        data = merge_overlay_bytes(os.path.join(source_dir, "SKILL.md"), skill_overlay)
        exp["SKILL.md"] = Expected(KIND_MERGE_FILE, None, data, sha256_bytes(data))
    for target, ov in aux_overlay_targets(overlay_dir, source_dir, warn):
        data = merge_overlay_bytes(os.path.join(source_dir, target), ov)
        exp[target] = Expected(KIND_MERGE_FILE, None, data, sha256_bytes(data))
    for e in exp.values():
        if e.src:
            e.hash = sha256_file(e.src)
    return exp


SKILL_CACHE_NAMES = (".trash", "synced")   # the Claude Code app's skill-sync cache, never a skill


def is_skill_cache(name):
    low = name.lower()
    return low in SKILL_CACHE_NAMES or low.startswith(".bucket-")


# --- deploy lock ------------------------------------------------------------------

LOCK_HEADER = "# agent-playbook deploy lock v1 (written by setup; kind<TAB>path<TAB>sha256)"
LOCK_FILE_KINDS = (KIND_COPY_DIR_RECURSIVE, KIND_MERGE_FILE, KIND_COPY_FILE, KIND_TEMPLATE_FILE)
LOCK_SETTING_KEY = "kiro-cli/chat.defaultAgent"
LOCK_GEMINI_KEY = "gemini/context.fileName"
_SHA_RE = re.compile(r"^[0-9a-f]{64}\Z")


def is_lock_row(c):
    """One row of the lock format: kind, ~/ path (no .., \\ or :) and sha256 (backup of a folder: -);
    setting rows name one of the two setting keys and a non-empty value."""
    if len(c) != 3:
        return False
    kind, key, val = c
    if kind == "setting":
        return key in (LOCK_SETTING_KEY, LOCK_GEMINI_KEY) and val != ""
    if kind not in LOCK_FILE_KINDS + ("backup",):
        return False
    if not key.startswith("~/") or "/../" in "/" + key + "/" or "\\" in key or ":" in key:
        return False
    if kind == "backup" and val == "-":
        return True
    return bool(_SHA_RE.match(val))


def read_lock_lines(path):
    """A lock-format file's lines (UTF-8, LF), without the empty last one. UnicodeDecodeError on
    bytes that are not UTF-8 (the caller treats it as an unreadable lock)."""
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    if not text:
        return []
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def parse_lock(lines):
    """-> [[kind, key, value]] or None when the header or any row is not the lock format."""
    if not lines or lines[0] != LOCK_HEADER:
        return None
    rows = []
    for line in lines[1:]:
        c = line.split("\t")
        if not is_lock_row(c):
            return None
        rows.append(c)
    return rows


def read_lock_rows(path):
    """The rows of a lock file, or None when it is missing, unreadable or not the lock format."""
    try:
        return parse_lock(read_lock_lines(path))
    except (OSError, UnicodeDecodeError):
        return None


def lock_class(kind):
    return kind if kind in ("backup", "setting") else "file"


def lock_bytes(lines):
    """The lock file's bytes for these rows ("kind\\tkey\\tvalue" strings): one row per path and kind
    class, the first one winning; sorted by code point (= UTF-8 byte order); LF; no BOM."""
    seen = set()
    rows = []
    for line in lines:
        if not line:
            continue
        c = line.split("\t")
        k = (lock_class(c[0]), c[1])
        if k in seen:
            continue
        seen.add(k)
        rows.append(line)
    rows.sort()
    return rows, (LOCK_HEADER + "\n" + "".join(r + "\n" for r in rows)).encode("utf-8")


# --- selftest -----------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_DIR = os.path.join(HERE, "fixtures", "deploy-model")
GOLDEN_HOME = "C:\\Users\\Golden"
GOLDEN_ROOT = "C:\\Users\\Golden\\agent-playbook"
GOLDEN_MARKER = "Golden-reviewed:"


def _golden_cases():
    """[(name, kind, inputs, expected_path)] from fixtures/deploy-model/cases.tsv."""
    cases = []
    with open(os.path.join(GOLDEN_DIR, "cases.tsv"), "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            c = line.split("\t")
            cases.append((c[0], c[1], [os.path.join(GOLDEN_DIR, p) for p in c[2].split(",")],
                          os.path.join(GOLDEN_DIR, c[3])))
    return cases


def _golden_real_pairs():
    """[(label, kind, input paths (repo-relative), input sha256s, expected sha256)] from real.tsv."""
    rows = []
    with open(os.path.join(GOLDEN_DIR, "real.tsv"), "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            c = line.split("\t")
            rows.append((c[0], c[1], c[2].split(","), c[3].split(","), c[4]))
    return rows


def _compute(kind, inputs, root=None):
    if kind == "merge":
        return merge_overlay_bytes(inputs[0], inputs[1])
    if kind == "render":
        return render_template_bytes(inputs[0], GOLDEN_HOME, GOLDEN_ROOT)
    raise ValueError(kind)


def golden_failures(repo):
    """-> (failures, real_checked, real_total): every golden case and every real pair whose inputs
    are still the ones the goldens were made from must reproduce the twins' bytes."""
    fails = []
    for name, kind, inputs, expected in _golden_cases():
        with open(expected, "rb") as fh:
            want = fh.read()
        got = _compute(kind, inputs)
        if got != want:
            fails.append("golden %s: module bytes differ from the twins' (%d vs %d bytes)" % (name, len(got), len(want)))
    checked = 0
    real = _golden_real_pairs()
    for label, kind, rels, in_shas, out_sha in real:
        paths = [os.path.join(repo, r) for r in rels]
        if not all(os.path.isfile(p) for p in paths) or [sha256_file(p) for p in paths] != in_shas:
            continue
        checked += 1
        got = sha256_bytes(_compute(kind, paths))
        if got != out_sha:
            fails.append("real pair %s: module bytes differ from the twins'" % label)
    return fails, checked, len(real)


def _selftest_lock(check):
    sha = "a" * 64
    rows = ["copy-file\t~/.kiro/a\t" + sha, "backup\t~/.kiro/a\t-", "copy-file\t~/.kiro/a\t" + "b" * 64,
            "setting\t" + LOCK_SETTING_KEY + "\t-", "merge-file\t~/.kiro/A\t" + sha]
    kept, data = lock_bytes(rows)
    check(kept == sorted([rows[0], rows[1], rows[3], rows[4]]), "lock: one row per path and class, first wins")
    check(data.startswith((LOCK_HEADER + "\n").encode()) and data.endswith(b"\n") and b"\r" not in data,
          "lock: header, LF, trailing newline")
    check(parse_lock(data.decode().split("\n")[:-1]) == [r.split("\t") for r in kept], "lock: round trip")
    for bad in (["copy-file", "~/../x", sha], ["copy-file", "~/a\\b", sha], ["copy-file", "/abs", sha],
                ["copy-file", "~/a", "XYZ"], ["setting", "other", "v"], ["setting", LOCK_GEMINI_KEY, ""],
                ["symlink-file", "~/a", sha], ["copy-file", "~/a:b", sha]):
        check(not is_lock_row(bad), "lock: rejects %r" % (bad,))
    check(is_lock_row(["backup", "~/a", "-"]) and not is_lock_row(["copy-file", "~/a", "-"]),
          "lock: - only for a backup")
    check(parse_lock(["# other header"]) is None and parse_lock([]) is None, "lock: wrong header -> None")
    srt, _ = lock_bytes(["copy-file\t~/\u00e9\t" + sha, "copy-file\t~/z\t" + sha, "copy-file\t~/Z\t" + sha])
    check([r.split("\t")[1] for r in srt] == ["~/Z", "~/z", "~/\u00e9"], "lock: sorted by code point")


def _selftest_manifest(check, tmp):
    p = os.path.join(tmp, "inv.tsv")
    with open(p, "wb") as fh:
        fh.write(b"\xef\xbb\xbf# c\r\n\r\ncopy-file\t~/a\tsrc/a\tclaude\r\n  # indented\nseed-file\t~/b\tsrc/b\tkiro")
    e = read_manifest(p)
    check(e == [("copy-file", "~/a", "src/a", "claude"), ("seed-file", "~/b", "src/b", "kiro")]
          and e[0].dest == "~/a", "manifest: BOM, CRLF, comments, last line without newline")
    for body, frag in ((b"copy-file\t~/a\tsrc\n", "has 3 columns"), (b"weird\t~/a\ts\tclaude\n", "unknown kind 'weird'")):
        with open(p, "wb") as fh:
            fh.write(body)
        try:
            read_manifest(p)
            check(False, "manifest: %s raises" % frag)
        except ManifestError as exc:
            check(frag in str(exc) and str(exc).startswith("ERROR: manifest line 1 "), "manifest: %s" % frag)
    try:
        read_manifest(os.path.join(tmp, "absent.tsv"))
        check(False, "manifest: missing raises")
    except ManifestError as exc:
        check("manifest not found" in str(exc), "manifest: missing file")
    check(expand_dest("~/.kiro/x", "C:\\H", "C:\\A\\Kiro\\User", True) == "C:\\H\\.kiro\\x", "expand ~ (Windows)")
    check(expand_dest("<KIRO_IDE_USER>/mcp.json", "C:\\H", "C:\\A\\Kiro\\User", True) == "C:\\A\\Kiro\\User\\mcp.json",
          "expand <KIRO_IDE_USER> (Windows)")
    check(expand_dest("~/.kiro/x", "/h", "/h/.config/Kiro/User", False) == "/h/.kiro/x", "expand ~ (POSIX)")
    check(kiro_ide_user_dir({}, "/h", False) == "/h/.config/Kiro/User"
          and kiro_ide_user_dir({"XDG_CONFIG_HOME": "/x/"}, "/h", False) == "/x/Kiro/User"
          and kiro_ide_user_dir({"APPDATA": "C:\\A"}, "C:\\H", True) == "C:\\A\\Kiro\\User", "Kiro IDE folder")


def _selftest_generated(check, tmp):
    win = os.name == "nt"
    src = os.path.join(tmp, "shared", "beta")
    ov = os.path.join(tmp, "kiro", "beta")
    for d in (os.path.join(src, "scripts", "__pycache__"), os.path.join(src, "fixtures"), ov):
        os.makedirs(d)
    files = {os.path.join(src, "SKILL.md"): b"# Beta\r\n\r\n", os.path.join(src, "aux.md"): b"aux\n",
             os.path.join(src, "scripts", "x.py"): b"x\n", os.path.join(src, "scripts", "__pycache__", "x.pyc"): b"c",
             os.path.join(src, "fixtures", "f.txt"): b"f", os.path.join(ov, "OVERLAY.md"): b"\xef\xbb\xbfdelta\n\n",
             os.path.join(ov, "aux.OVERLAY.md"): b"ax\n", os.path.join(ov, "SKILL.OVERLAY.md"): b"no\n",
             os.path.join(ov, "gone.OVERLAY.md"): b"no target\n"}
    for p, data in files.items():
        with open(p, "wb") as fh:
            fh.write(data)
    warns = []
    exp = generated_expected(src, ov, win, warn=warns.append)
    check(sorted(exp) == ["SKILL.md", "aux.md", "scripts/x.py"], "generated: __pycache__ and fixtures skipped")
    check(exp["SKILL.md"].kind == KIND_MERGE_FILE and exp["SKILL.md"].data == b"# Beta\n\ndelta\n",
          "generated: SKILL.md merged (BOM dropped, CRLF stripped)")
    check(exp["aux.md"].data == b"aux\n\nax\n" and exp["scripts/x.py"].hash == sha256_bytes(b"x\n"),
          "generated: aux merge and copy hash")
    check(len(warns) == 2 and "SKIPPED RESERVED" in warns[0] + warns[1] and "SKIPPED AUX OVERLAY" in warns[0] + warns[1],
          "generated: reserved and target-less aux overlays warned")
    check(has_any_overlay(ov) and not has_any_overlay(os.path.join(tmp, "absent")), "has_any_overlay")
    only_reserved = os.path.join(tmp, "kiro", "gamma")
    os.makedirs(only_reserved)
    with open(os.path.join(only_reserved, "SKILL.OVERLAY.md"), "wb") as fh:
        fh.write(b"x")
    check(not has_any_overlay(only_reserved), "has_any_overlay: SKILL.OVERLAY.md alone does not count")


def _mutation_check(check, repo):
    """The golden check must fail on a broken merge and on a broken render."""
    global merge_text, render_text
    real_merge, real_render = merge_text, render_text
    try:
        merge_text = lambda s, o: real_merge(s, o).replace("\n\n", "\n", 1)
        check(any(f.startswith("golden merge") for f in golden_failures(repo)[0]),
              "mutation: a merge without the blank line fails the golden check")
        merge_text = lambda s, o: s.rstrip("\r\n") + "\n" + (o.rstrip("\r\n") + "\n" if o.strip() else "")
        check(any(f.startswith("golden merge") for f in golden_failures(repo)[0]),
              "mutation: a merge with Python's isspace blank test fails the golden check")
        merge_text = real_merge
        render_text = lambda b, h, r: real_render(b, h, r).replace(forward_root(r), r)
        check(any(f.startswith("golden render") for f in golden_failures(repo)[0]),
              "mutation: a render with backslash roots fails the golden check")
    finally:
        merge_text, render_text = real_merge, real_render


def selftest():
    import tempfile
    import shutil
    results = []

    def check(cond, label):
        results.append((bool(cond), label))

    repo = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
    tmp = tempfile.mkdtemp(prefix="deploy-model-")
    try:
        _selftest_lock(check)
        _selftest_manifest(check, tmp)
        _selftest_generated(check, tmp)
        check(merge_text("a\r\n\n", "\x1c\n") == "a\n\n\x1c\n" and merge_text("a", " \u00a0\n") == "a\n",
              "merge: U+001C is content, NBSP is blank (.NET IsWhiteSpace)")
        check(render_text("{{USER_HOME}}|{{PLAYBOOK_ROOT}}\n\n", "C:\\U\\x\\", "/r") == "C:/U/x|/r\n", "render: tokens")
        fails, checked, total = golden_failures(repo)
        check(not fails, "golden: module reproduces the twins' bytes%s" % ("" if not fails else ": " + "; ".join(fails)))
        check(len(_golden_cases()) >= 10, "golden: edge cases present")
        _mutation_check(check, repo)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [l for ok, l in results if not ok]
    for ok, label in results:
        print("%s: %s" % ("PASS" if ok else "FAIL", label))
    print("real overlay pairs still at their golden inputs: %d of %d" % (checked, total))
    print("deploy_model selftest: %d checks, %d failed" % (len(results), len(bad)))
    return 1 if bad else 0


# --- golden history guard -------------------------------------------------------------

def check_golden_history(repo, since):
    """Every commit (since `since`, or all) that changes both this module and a golden file names
    the review in a `Golden-reviewed:` line. -> exit code."""
    import subprocess
    rel_mod = "shared/skills/qconfig-sync/scripts/deploy_model.py"
    rel_gold = "shared/skills/qconfig-sync/scripts/fixtures/deploy-model/"
    rng = ["%s..HEAD" % since] if since else ["HEAD"]
    try:
        out = subprocess.run(["git", "-C", repo, "log", "--format=%x00%H%x00%B%x00", "--name-only"] + rng
                             + ["--", rel_mod, rel_gold], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError) as exc:
        print("deploy_model: could not read git history (%s)" % exc, file=sys.stderr)
        return 2
    # one commit: \0 sha \0 body \0 \n names; split -> ["", sha, body, names, sha, body, names, ...]
    parts = out.split("\x00")
    bad = []
    for i in range(1, len(parts) - 1, 3):
        sha, body = parts[i], parts[i + 1]
        names = parts[i + 2] if i + 2 < len(parts) else ""
        files = [n for n in names.split("\n") if n]
        if rel_mod in files and any(f.startswith(rel_gold) for f in files) and GOLDEN_MARKER not in body:
            bad.append(sha[:12])
    for sha in bad:
        print("FAIL: commit %s changes deploy_model.py and a golden file without a '%s' line" % (sha, GOLDEN_MARKER))
    print("deploy_model golden history: %d commit(s) without a review marker" % len(bad))
    return 1 if bad else 0


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["--check-golden-history"]:
        repo = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
        since = None
        rest = argv[1:]
        while rest:
            if rest[0] == "--repo" and len(rest) > 1:
                repo, rest = rest[1], rest[2:]
            elif rest[0] == "--since" and len(rest) > 1:
                since, rest = rest[1], rest[2:]
            else:
                print("usage: deploy_model.py --check-golden-history [--repo PATH] [--since REV]", file=sys.stderr)
                return 2
        return check_golden_history(repo, since)
    print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
