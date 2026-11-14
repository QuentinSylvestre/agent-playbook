#!/usr/bin/env python3
"""verify-skills.py -- check every skill's SKILL.md frontmatter, name and `requires` line.

Run with the playbook venv (<repo>/.venv-agent-playbook); any other interpreter exits 2 ("guard did not
run: venv missing"). Stdlib only, Python 3.8+. It reads files, writes nothing, runs no git and touches no
network.

Checked files: every shared/skills/*/SKILL.md, and every providers/kiro/skills/*/SKILL.md whose folder has
no OVERLAY.md (a standalone Kiro skill; an overlay folder is merged into the shared skill at deploy time).
A folder without a SKILL.md (for example an untracked shared/skills/synced/) is skipped and counted on the
SUMMARY line.

Usage:
  verify-skills.py [--help] <repo-root>
  verify-skills.py --selftest

The repo-root argument is MANDATORY -- exit 2 when absent. Repo context is never derived from the ambient
cwd, a recorded footgun (memory/topics/playbook-authoring.md, the ambient-cwd lesson).

Frontmatter grammar (strict and flat). The file opens with a line `---` and the frontmatter ends at the next
line `---`. Between the fences every line is `key: value`: the key matches [A-Za-z][A-Za-z0-9_-]*, the
value is a single line, optionally wrapped in matching single or double quotes. Rejected: a blank line, a
comment line, indentation, a list item (`- x`), an empty value (which would continue on the next line), a
duplicate key, a quote with no matching close or with an unescaped interior quote (double quotes escape
with a backslash, single quotes by doubling), a leading byte-order mark. An UNQUOTED value must not
contain `: ` or ` #`, end with `:`, or start with a YAML indicator character ([ { * & ! | > % @ # or a
backtick). Quote the value to use any of them.

Rules, per skill:
  - `name` and `description` are present.
  - `argument-hint`, when present, is quoted (shared/AGENTS.md's SKILL.md Authoring rule).
  - `name` equals the folder name and starts with `q`; no two checked skills share a name.
  - `requires`, when present, is a QUOTED, comma-separated list of skill names (`requires: "qreview,
    qvalidate"`): no empty, duplicate or self entry, and every entry names a checked skill.
  - Every skill the body CALLS (below) is listed in `requires`.
  - Every skill listed in `requires` appears in the body as a whole word (`qreview`, `/qreview`,
    `shared/skills/qreview/SKILL.md` all count), so a stale entry fails. The body is the text below the
    closing fence.

Call versus mention. A skill's body names other skills in two ways. A MENTION cites a skill's file or
section to read, names a caller, gives advice to the user, or says what NOT to do. A CALL runs the other
skill as a step of this one. A fully mechanical call detector proved unreliable (bodies name callers,
advise the user to run a skill, and cite "per `/qreview`'s Verdict rubrics" more often than they call), so
the body-to-`requires` direction checks only EXPLICIT invocation phrasing. The rule:

  A call is the active verb `invoke`, `invokes` or `invoking` (also `auto-invoke`), or the phrase
  `dispatch to`, `hand off to` or `delegate to` (any inflection of the verb), followed by an optional
  article or adverb (the, a, an, it, then, inline, directly, also, again, once) and then `/<skill>`,
  with or without backticks, optionally followed by arguments inside the code span. The match ignores case.
  A match is NOT a call when the same line holds `not`, `never`, `no` or a `n't` contraction in the 40
  characters before the verb, and a skill naming itself is ignored.

Calls (each skill must be listed in `requires`):
  "invoke `/qdream lightweight` scoped to the plan"          "the orchestrator invokes `/qqa` inline"
  "auto-invoke `/qqa` without a user prompt"                   "Delegate to `/qbrowser-test` with the URL"
Mentions (never need listing, and a listed skill still needs one whole-word appearance):
  "follow `/qreview`'s Sub-agent unavailability gate"         "see `/qreview`"
  "`shared/skills/qreview/SKILL.md § Verdict rubrics`"        "suggest the user run `/qconfig-sync`"
  "Do NOT invoke `/qplan`"                                    "invoked by `/qdev`" (passive: a caller)
A dependency the phrasing does not catch (for example a skill that loads `/qreview` for its rules) is
declared in `requires` by hand; the guard then only checks that the skill exists and the body names it.

Output: one tab-separated line per checked file, in path order:
  OK\\t<repo-relative file>\\t<name>
  FAIL\\t<repo-relative file>\\t<what is wrong>        (one line per violation)
then SUMMARY\\tok=<files>\\tfail=<files>\\tskipped=<folders>.

Exit codes:
  0   every checked skill passes.
  1   one or more FAIL lines.
  2   precondition failure (repo-root argument missing, repo path invalid or not a playbook, no skill
      found), or the venv guard did not pass, or an unexpected error: "verify-skills.py: guard did not run:
      <reason>" on stderr, after any rows already printed.

Selftest: `verify-skills.py --selftest` builds synthetic repos in a temp folder and checks a passing tree
(shared, Kiro standalone, Kiro overlay and a folder with no SKILL.md), each frontmatter rule broken once,
the name rules, the `requires` rules, the call and mention cases above, and each exit-2 precondition.
"""
import os
import re
import sys

NAME = "verify-skills.py"

INDICATORS = "[{*&!|>%@#`"
KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?: +(.*))?$")
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CALL_VERB = (r"(?:invoke|invokes|invoking|dispatch(?:es|ed|ing)?\s+to|hand(?:s|ed|ing)?\s+off\s+to"
             r"|delegate[sd]?\s+to|delegating\s+to)")
FILLER = r"(?:\s+(?:the|a|an|it|then|inline|directly|also|again|once))*"
NEGATION = re.compile(r"\b(?:not|never|no)\b|n't", re.I)


# --- venv guard stub: same text as the qdream scripts', except the one line naming where venv-selfcheck.py is ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "qdream", "scripts", "venv-selfcheck.py")
    name = os.path.basename(script or __file__)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("venv_selfcheck", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        sys.stderr.write("%s: guard did not run: venv self-check unavailable (%s: %s)\n"
                         % (name, type(exc).__name__, exc))
        sys.exit(2)
    finally:
        sys.dont_write_bytecode = saved
    mod.require(script or __file__)
# --- end venv guard stub ---


def parse_value(raw):
    """-> (value, quoted, error or None) for one non-empty, stripped value."""
    if raw[0] in "\"'":
        q = raw[0]
        if len(raw) < 2 or raw[-1] != q:
            return None, True, "quoted value has no matching closing quote"
        inner = raw[1:-1]
        i = 0
        while i < len(inner):
            c = inner[i]
            if q == '"' and c == "\\":
                if i + 1 >= len(inner):
                    return None, True, "closing quote is escaped by a backslash"
                i += 2
                continue
            if c == q:
                if q == "'" and inner[i + 1:i + 2] == "'":
                    i += 2
                    continue
                return None, True, "unescaped %s quote inside a quoted value" % q
            i += 1
        value = re.sub(r"\\(.)", r"\1", inner) if q == '"' else inner.replace("''", "'")
        return value, True, None
    if raw[0] in INDICATORS:
        return None, False, "unquoted value starts with the indicator character %r (quote it)" % raw[0]
    if ": " in raw:
        return None, False, "unquoted value contains ': ' (quote it)"
    if raw.endswith(":"):
        return None, False, "unquoted value ends with ':' (quote it)"
    if " #" in raw:
        return None, False, "unquoted value contains ' #' (quote it)"
    return raw, False, None


def parse_skill(text):
    """-> (fields {key: (value, quoted)}, errors [str], body str). Strict flat frontmatter grammar."""
    if text.startswith("﻿"):
        return {}, ["file starts with a byte-order mark; it must open with the '---' fence"], ""
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    if not lines or lines[0] != "---":
        return {}, ["file does not open with a '---' fence"], ""
    close = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            close = i
            break
    if close is None:
        return {}, ["frontmatter has no closing '---' fence"], ""
    fields, errors = {}, []
    for n in range(1, close):
        line = lines[n].rstrip()
        where = "line %d" % (n + 1)
        if not line:
            errors.append("%s: blank line inside the frontmatter" % where)
            continue
        if line[0] in " \t":
            errors.append("%s: indentation (nested or continued value)" % where)
            continue
        if line.startswith("- ") or line == "-":
            errors.append("%s: list item" % where)
            continue
        m = KEY_RE.match(line)
        if not m:
            errors.append("%s: not a 'key: value' line" % where)
            continue
        key, raw = m.group(1), (m.group(2) or "").strip()
        if not raw:
            errors.append("%s: empty or multi-line value for '%s'" % (where, key))
            continue
        value, quoted, err = parse_value(raw)
        if err:
            errors.append("%s: '%s': %s" % (where, key, err))
            continue
        if key in fields:
            errors.append("%s: duplicate key '%s'" % (where, key))
            continue
        fields[key] = (value, quoted)
    return fields, errors, "\n".join(lines[close + 1:])


def invoked_skills(body, names, own):
    """The skills the body CALLS under the explicit-phrasing rule in the module docstring."""
    if not names:
        return set()
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    rx = re.compile(r"\b" + CALL_VERB + FILLER + r"\s+`?/(" + alt + r")(?![\w-])", re.I)
    found = set()
    for m in rx.finditer(body):
        if m.group(1) == own:
            continue
        line_start = body.rfind("\n", 0, m.start()) + 1
        if NEGATION.search(body[max(line_start, m.start() - 40):m.start()]):
            continue
        found.add(m.group(1))
    return found


def mentions(body, name):
    return re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", body) is not None


def discover(repo):
    """-> (skills [(rel, folder, abs path)] in path order, skipped folder count)."""
    skills, skipped = [], 0
    for root_rel, standalone_only in (("shared/skills", False), ("providers/kiro/skills", True)):
        root = os.path.join(repo, *root_rel.split("/"))
        if not os.path.isdir(root):
            continue
        for folder in sorted(os.listdir(root)):
            d = os.path.join(root, folder)
            if not os.path.isdir(d):
                continue
            skill = os.path.join(d, "SKILL.md")
            if not os.path.isfile(skill) or (standalone_only and os.path.exists(os.path.join(d, "OVERLAY.md"))):
                skipped += 1
                continue
            skills.append(("%s/%s/SKILL.md" % (root_rel, folder), folder, skill))
    skills.sort()
    return skills, skipped


def run(argv):
    """-> (exit code, stdout lines, stderr lines). No side effects. Any unexpected error is exit 2, "guard
    did not run", with the rows already produced kept: exit 1 means only a real FAIL finding."""
    out, err = [], []
    try:
        return _run(argv, out, err)
    except Exception as exc:
        err.append("%s: guard did not run: %s: %s" % (NAME, type(exc).__name__, exc))
        return 2, out, err


def _run(argv, out, err):
    if not argv:
        err.append("%s: repo-root argument is required (deliberately never derived from cwd)" % NAME)
        return 2, out, err
    repo = argv[0]
    if not repo or not os.path.isdir(repo):
        err.append("%s: repo path not found: %s" % (NAME, repo))
        return 2, out, err
    if not os.path.isfile(os.path.join(repo, "shared", "AGENTS.md")):
        err.append("%s: %s does not look like an agent-playbook repo" % (NAME, repo))
        return 2, out, err
    skills, skipped = discover(repo)
    if not skills:
        err.append("%s: guard did not run: no SKILL.md found under shared/skills or providers/kiro/skills" % NAME)
        return 2, out, err

    parsed = {}  # rel -> (fields, body, problems)
    for rel, folder, path in skills:
        with open(path, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            parsed[rel] = ({}, "", ["file is not valid UTF-8"])
            continue
        fields, errors, body = parse_skill(text)
        parsed[rel] = (fields, body, list(errors))

    name_of = {}  # rel -> declared name, for files that declare one
    by_name = {}
    for rel, folder, _p in skills:
        fields, _b, problems = parsed[rel]
        for key in ("name", "description"):
            if key not in fields and not any("'%s'" % key in p for p in problems):
                problems.append("missing required key '%s'" % key)
        if "name" in fields:
            name = fields["name"][0]
            name_of[rel] = name
            by_name.setdefault(name, []).append(rel)
            if name != folder:
                problems.append("name '%s' does not equal the folder name '%s'" % (name, folder))
            if not name.startswith("q"):
                problems.append("name '%s' does not start with 'q'" % name)
        if "argument-hint" in fields and not fields["argument-hint"][1]:
            problems.append("argument-hint must be quoted")
    for name, rels in by_name.items():
        if len(rels) > 1:
            for rel in rels:
                others = ", ".join(r for r in rels if r != rel)
                parsed[rel][2].append("name '%s' is also used by %s" % (name, others))

    known = set(by_name)
    for rel, folder, _p in skills:
        fields, body, problems = parsed[rel]
        own = name_of.get(rel, folder)
        requires = None
        if "requires" in fields:
            value, quoted = fields["requires"]
            if not quoted:
                problems.append("requires must be a quoted, comma-separated list")
            else:
                requires = []
                for item in [x.strip() for x in value.split(",")]:
                    if not SKILL_NAME_RE.match(item):
                        problems.append("requires has an empty or malformed entry %r" % item)
                    elif item == own:
                        problems.append("requires lists the skill itself ('%s')" % item)
                    elif item in requires:
                        problems.append("requires lists '%s' twice" % item)
                    elif item not in known:
                        problems.append("requires names '%s', which is not a checked skill" % item)
                    else:
                        requires.append(item)
                for item in requires:
                    if not mentions(body, item):
                        problems.append("requires lists '%s' but the body never names it" % item)
        if not [p for p in problems if p.startswith("line ") or "fence" in p or "UTF-8" in p
                or "byte-order" in p]:
            for called in sorted(invoked_skills(body, known, own)):
                if requires is None or called not in requires:
                    problems.append("the body calls '%s' but requires does not list it" % called)

    ok = failed = 0
    for rel, folder, _p in skills:
        problems = parsed[rel][2]
        if problems:
            failed += 1
            for p in problems:
                out.append("FAIL\t%s\t%s" % (rel, p))
        else:
            ok += 1
            out.append("OK\t%s\t%s" % (rel, name_of.get(rel, folder)))
    out.append("SUMMARY\tok=%d\tfail=%d\tskipped=%d" % (ok, failed, skipped))
    return (1 if failed else 0), out, err


def selftest():
    import shutil
    import tempfile
    fails, checks = [], [0]

    def chk(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (name, (": " + detail) if detail else ""))

    def write(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    counter = [0]

    def repo(files):
        counter[0] += 1
        root = os.path.join(tmp, "r%d" % counter[0])
        write(os.path.join(root, "shared", "AGENTS.md"), b"x\n")
        for rel, data in files.items():
            write(os.path.join(root, *rel.split("/")), data if isinstance(data, bytes) else data.encode("utf-8"))
        return root

    def skill(name, extra="", body="Body.\n", desc="A test skill."):
        return "---\nname: %s\ndescription: %s\n%s---\n%s" % (name, desc, extra, body)

    def good():
        return {
            "shared/skills/qalpha/SKILL.md": skill("qalpha", 'argument-hint: "<x>"\nrequires: "qbeta"\n',
                                                   "Run the work, then invoke `/qbeta` inline.\n"),
            "shared/skills/qbeta/SKILL.md": skill("qbeta", body="Called by `/qalpha`; invoked by `/qalpha`.\n"),
            "providers/kiro/skills/qgamma/SKILL.md": skill("qgamma"),
            "providers/kiro/skills/qalpha/OVERLAY.md": "overlay\n",
            "providers/kiro/skills/qbeta/OVERLAY.md": "overlay\n",
            "providers/kiro/skills/qbeta/SKILL.md": "not frontmatter at all\n",
            "shared/skills/synced/notes.md": "no SKILL.md here\n",
        }

    def result(files):
        r = repo(files)
        rc, out, err = run([r])
        return rc, out, err

    def fails_with(label, files, needle):
        rc, out, err = result(files)
        hit = [ln for ln in out if ln.startswith("FAIL\t") and needle in ln]
        chk(label, rc == 1 and bool(hit) and not err, "%s %r %r" % (rc, out, err))

    tmp = tempfile.mkdtemp(prefix="verify-skills-")
    try:
        rc, out, err = result(good())
        chk("a passing tree exits 0 with OK rows, skipped folders counted",
            rc == 0 and out == ["OK\tproviders/kiro/skills/qgamma/SKILL.md\tqgamma",
                                "OK\tshared/skills/qalpha/SKILL.md\tqalpha", "OK\tshared/skills/qbeta/SKILL.md\tqbeta",
                                "SUMMARY\tok=3\tfail=0\tskipped=3"] and not err, "%s %r %r" % (rc, out, err))

        def with_alpha(text):
            f = good()
            f["shared/skills/qalpha/SKILL.md"] = text
            return f

        # frontmatter grammar
        fails_with("no opening fence", with_alpha("name: qalpha\ndescription: d\n---\nx\n"), "does not open")
        fails_with("no closing fence", with_alpha("---\nname: qalpha\ndescription: d\nbody\n"), "no closing")
        fails_with("byte-order mark", with_alpha("﻿" + skill("qalpha")), "byte-order mark")
        fails_with("missing description", with_alpha("---\nname: qalpha\n---\nx\n"), "missing required key 'description'")
        fails_with("missing name", with_alpha("---\ndescription: d\n---\nx\n"), "missing required key 'name'")
        fails_with("unquoted ': '", with_alpha(skill("qalpha", desc="Use it: always")), "contains ': '")
        fails_with("unquoted ' #'", with_alpha(skill("qalpha", desc="Use it # now")), "contains ' #'")
        fails_with("unquoted trailing colon", with_alpha(skill("qalpha", desc="Use it:")), "ends with ':'")
        for ch in "[{*&!|>%@#`":
            fails_with("unquoted indicator %s" % ch, with_alpha(skill("qalpha", desc=ch + "x")), "indicator character")
        fails_with("indentation", with_alpha(skill("qalpha", extra="  more: x\n")), "indentation")
        fails_with("list item", with_alpha(skill("qalpha", extra="- item\n")), "list item")
        fails_with("empty value", with_alpha(skill("qalpha", extra="other:\n")), "empty or multi-line")
        fails_with("duplicate key", with_alpha(skill("qalpha", extra="description: again\n")), "duplicate key 'description'")
        fails_with("blank line", with_alpha("---\nname: qalpha\n\ndescription: d\n---\nx\n"), "blank line")
        fails_with("comment line", with_alpha(skill("qalpha", extra="# c\n")), "not a 'key: value'")
        fails_with("no space after colon", with_alpha(skill("qalpha", extra="k:v\n")), "not a 'key: value'")
        fails_with("unclosed quote", with_alpha(skill("qalpha", desc='"abc')), "no matching closing quote")
        fails_with("mismatched quotes", with_alpha(skill("qalpha", desc="\"abc'")), "no matching closing quote")
        fails_with("interior double quote", with_alpha(skill("qalpha", desc='"a "b" c"')), "unescaped")
        fails_with("interior single quote", with_alpha(skill("qalpha", desc="'it's'")), "unescaped")
        fails_with("escaped closing quote", with_alpha(skill("qalpha", desc='"abc\\"')), "escaped")
        fails_with("unquoted argument-hint", with_alpha(skill("qalpha", extra='argument-hint: <x>\n', body="")),
                   "argument-hint must be quoted")

        # accepted forms
        f = good()
        f["shared/skills/qbeta/SKILL.md"] = skill("qbeta", extra="note: 'it''s ok'\nmore: \"a: b # c \\\" d\"\n"
                                                              "plain: has no colon-space\n")
        rc, out, err = result(f)
        chk("quoted values may hold ': ', ' #', escaped and doubled quotes", rc == 0 and not err, "%s %r" % (rc, out))
        f = good()
        f["shared/skills/qbeta/SKILL.md"] = skill("qbeta").replace("\n", "\r\n")
        rc, out, err = result(f)
        chk("CRLF line endings pass", rc == 0 and not err, "%s %r" % (rc, out))

        # name rules
        fails_with("name differs from folder", with_alpha(skill("qother")), "does not equal the folder name")
        f = good()
        f["shared/skills/plain/SKILL.md"] = skill("plain")
        fails_with("name without q prefix", f, "does not start with 'q'")
        f = good()
        f["providers/kiro/skills/qalpha/SKILL.md"] = skill("qalpha")
        f.pop("providers/kiro/skills/qalpha/OVERLAY.md")
        fails_with("name shared by two skills", f, "is also used by")

        # requires rules
        fails_with("requires unquoted", with_alpha(skill("qalpha", extra="requires: qbeta\n",
                                                         body="invoke `/qbeta`\n")), "requires must be a quoted")
        fails_with("requires names an unknown skill",
                   with_alpha(skill("qalpha", extra='requires: "qbeta, qnone"\n', body="`/qbeta` `/qnone`\n")),
                   "not a checked skill")
        fails_with("requires empty entry", with_alpha(skill("qalpha", extra='requires: "qbeta,"\n', body="qbeta\n")),
                   "empty or malformed entry")
        fails_with("requires duplicate", with_alpha(skill("qalpha", extra='requires: "qbeta, qbeta"\n', body="qbeta\n")),
                   "twice")
        fails_with("requires lists itself", with_alpha(skill("qalpha", extra='requires: "qalpha"\n', body="qalpha\n")),
                   "the skill itself")
        fails_with("requires entry never named in the body",
                   with_alpha(skill("qalpha", extra='requires: "qbeta"\n', body="Nothing here.\n")), "never names it")
        fails_with("body calls a skill requires omits", with_alpha(skill("qalpha", body="First invoke `/qbeta`.\n")),
                   "calls 'qbeta'")
        fails_with("a hand-off is a call", with_alpha(skill("qalpha", body="Then hand off to `/qbeta`.\n")), "calls 'qbeta'")
        fails_with("a delegation is a call", with_alpha(skill("qalpha", body="Delegate to `/qbeta` for it.\n")),
                   "calls 'qbeta'")
        fails_with("a call with arguments in the span", with_alpha(skill("qalpha", body="invokes `/qbeta lightweight`\n")),
                   "calls 'qbeta'")
        fails_with("a call without backticks, upper case", with_alpha(skill("qalpha", body="Invoke the /qbeta now\n")),
                   "calls 'qbeta'")
        for label, body in (("a negated invoke", "Do NOT invoke `/qbeta`.\n"),
                            ("a never-invoke", "It must never invoke `/qbeta`.\n"),
                            ("a see-reference", "See `/qbeta` for details.\n"),
                            ("a section citation", "Read `shared/skills/qbeta/SKILL.md § Rules`.\n"),
                            ("advice to the user", "Suggest the user run `/qbeta`.\n"),
                            ("a passive caller", "This skill is invoked by `/qbeta`.\n"),
                            ("a sibling-skill name with a suffix", "invoke `/qbeta-extra`\n"),
                            ("self-invocation", "Re-invoke `/qalpha` to continue.\n"),
                            ("a path-prefixed name", "invoke shared/skills/qbeta/x\n")):
            rc, out, err = result(with_alpha(skill("qalpha", body=body)))
            chk("mention, not a call: " + label, rc == 0 and not err, "%s %r" % (rc, out))
        rc, out, err = result(with_alpha(skill("qalpha", extra='requires: "qbeta"\n', body="Per `/qbeta`'s rubrics.\n")))
        chk("a hand-listed dependency passes when the body names it", rc == 0 and not err, "%s %r" % (rc, out))

        # exit-2 preconditions and the other exit paths
        rc, out, err = run([])
        chk("no repo argument exits 2",
            rc == 2 and not out and err == ["%s: repo-root argument is required (deliberately never derived "
                                            "from cwd)" % NAME], "%s %r" % (rc, err))
        gone = os.path.join(tmp, "no-such-dir")
        rc, out, err = run([gone])
        chk("a nonexistent repo exits 2", rc == 2 and err == ["%s: repo path not found: %s" % (NAME, gone)],
            "%s %r" % (rc, err))
        rc, out, err = run([""])
        chk("an empty repo argument exits 2 as not found", rc == 2 and err == ["%s: repo path not found: " % NAME],
            "%s %r" % (rc, err))
        root = os.path.join(tmp, "notplaybook")
        write(os.path.join(root, "README.md"), b"x\n")
        rc, out, err = run([root])
        chk("a folder without shared/AGENTS.md exits 2",
            rc == 2 and err == ["%s: %s does not look like an agent-playbook repo" % (NAME, root)], "%s %r" % (rc, err))
        r = repo({"shared/skills/synced/notes.md": "x\n"})
        rc, out, err = run([r])
        chk("a repo with no SKILL.md exits 2", rc == 2 and not out and "guard did not run" in err[0], "%s %r" % (rc, err))
        r = repo({"shared/skills/qalpha/SKILL.md": b"---\nname: qalpha\ndescription: \xff\n---\n"})
        rc, out, err = run([r])
        chk("invalid UTF-8 is a FAIL line, not a crash",
            rc == 1 and out[:1] == ["FAIL\tshared/skills/qalpha/SKILL.md\tfile is not valid UTF-8"], "%s %r" % (rc, out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f in fails:
        print("FAIL: %s" % f)
    print("verify-skills selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
    return 1 if fails else 0


def main(argv=None):
    _require_venv(__file__)
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
            except Exception:
                pass
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["--help"]:
            sys.stdout.write(__doc__.strip("\n") + "\n")
            return 0
        if argv[:1] == ["--selftest"]:
            return selftest()
        rc, out, err = run(argv)
        for line in out:
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
        for line in err:
            sys.stderr.write(line + "\n")
        return rc
    except Exception as exc:
        sys.stderr.write("%s: guard did not run: %s: %s\n" % (NAME, type(exc).__name__, exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
