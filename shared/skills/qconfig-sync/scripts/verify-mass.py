#!/usr/bin/env python3
"""verify-mass.py -- enforce the governance-mass brake.

Every session-loaded governance file in the BUDGETS table below must stay at or under its absolute word
ceiling, so governance word-mass cannot ratchet upward through small commits unnoticed. Run with the
playbook venv (<repo>/.venv-agent-playbook); any other interpreter exits 2 ("guard did not run: venv
missing"). Stdlib only, Python 3.8+. It reads the measured files, writes nothing, runs no git and touches
no network.

Word-count algorithm (pinned): split the file content on runs of ASCII whitespace ([ \\t\\r\\n]+) and count
the non-empty tokens. The algorithm is pinned rather than native: native word counters (wc -w,
str.split()) classify Unicode whitespace (e.g. NBSP) and \\v/\\f as separators, and the count must not move
with them. Files are read as UTF-8 with a leading byte-order mark dropped, so a BOM never changes a count.

Override path: first route the growth to the skill that owns the behaviour, or cut restatement. Raise a
budget row in BUDGETS only on an EXPLICIT USER DECISION recorded in the commit body (ratchet rule 2
below), in the same commit as the growth, with the justification in the commit body. Never satisfy the
budget by cutting load-bearing rules; the conditional Proportionality/Leanness review standard judges WHAT
was cut.

Usage:
  verify-mass.py [--help] <repo-root>
  verify-mass.py --selftest

The repo-root argument is MANDATORY -- exit 2 when absent. Repo context is never derived from the ambient
cwd, a recorded footgun (memory/topics/playbook-authoring.md, the ambient-cwd lesson).

Output: one tab-separated line per measured file:
  <STATUS>\\t<file>\\t<words>\\t<budget>
STATUS in {OK, OVER}. A trailing SUMMARY line records totals; a REMEDIATION line follows when any file
is OVER.

Fixed cost per client (report-only, no ceiling, never changes the exit code). After those lines, one line per
client:
  TOTAL\\t<client>\\t<N> words\\t(<file>=<words>, ...; skill descriptions=<words> over <K> skills)
N is the words in the governance files the client loads at every session start plus the words in the
`description:` frontmatter value of every skill deployed to that client (the skill-description catalogue).
Words are the pinned whitespace split above (a description with its outer quotes dropped). The files, from
the repo sources and inventory.tsv, never the live home, so the numbers are the same in CI:
  claude  the ~/.claude/CLAUDE.md target, and every ~/.claude/rules/*.md row once the inventory deploys one
          (agent-playbook.md, and the links to memory/MEMORY.md and memory/HIGHER_ORDER.md).
  codex   the ~/.codex/AGENTS.md target.
  gemini  the ~/.gemini/GEMINI.md target, or ~/.gemini/AGENT-PLAYBOOK.md when the inventory deploys it.
  kiro    every ~/.kiro/steering/*.md row, the agent definition providers/kiro/agents/kiro_default.md, and the
          `file://{{PLAYBOOK_ROOT}}/...` resources of that definition expanded under the repo (the two
          memory/*.md tiers). Workspace-relative resources (`file://AGENTS.md`, `file://memory/*.md`) are not
          counted: the workspace is unknown here.
A file named by the inventory but absent from the repo (memory/ is a link that CI does not have) prints as
`<file>=missing` and adds 0. Skills: shared/skills/* with a SKILL.md (not `synced`), plus for Kiro the
providers/kiro/skills/* folders with a SKILL.md and no OVERLAY.md. A failure computing them prints a WARN
line, never an error.

Exit codes:
  0   all measured files at or under their word budget.
  1   one or more measured files over budget (raise the ceiling in-diff if the growth is deliberate).
  2   precondition failure (repo-root argument missing, repo path invalid, or a measured file missing),
      or the venv guard did not pass, or an unexpected error (for example a measured file unreadable):
      "verify-mass.py: guard did not run: <reason>" on stderr, after any rows already printed.

BUDGETS format: one `("<repo-relative-file>", <max-words>),` row per line, inside the module-level
`BUDGETS = (` ... `)` tuple; a trailing `# comment` is allowed. dream-sweep.py (mass_rows) parses that
text and reports any row it cannot parse, so keep the shape.

RATCHET RULE. A ceiling re-derived from the current value and raised whenever it binds is not a
constraint -- it measures growth while constraining nothing. Two obligations follow:
  1. After any DELIBERATE REDUCTION of a measured file, re-derive the ceiling DOWN as
     min(current ceiling, new actual x 1.10). Reclaimed headroom is not silently spendable.
  2. Raising a ceiling requires an EXPLICIT USER DECISION recorded in the commit message -- an in-diff
     comment is not approval.
Evidence (2026-08-05 /qdream sweep): the 2026-07-30 leanness pass cut shared/AGENTS.md 7,176 -> 5,659
words while the ceiling stayed at 7,200, leaving ~1,000 words of silent regrowth room; the file was back
to 6,179 (+9.2% in five days) with this script reporting OK throughout. Measured growth slope was
unchanged across the brake's introduction (49.4 words/day before, 52.8 after).

Ceiling derivation for shared/AGENTS.md: 7100 (2026-07-16, 6,442 x 1.10) -> 7200 (2026-07-24,
lifecycle-table enumeration) -> 6300 (2026-08-05, ratcheted down under rule 1 after the 2026-07-30
reduction; user-approved in the /qdream sweep with "bind immediately" chosen over a softer 6,800) -> 6500
(2026-08-14, raised by EXPLICIT USER DECISION under rule 2, recorded in the commit message. Two known
demands, not speculative headroom: a new AI-provenance-trailer ban in Commit Conventions adds ~95 words,
and the workspace-store project reserves 75 more across four phases, projecting ~6,466. 6500 was chosen
over a looser 6,600 to keep ~34 words of reserve rather than ~134 -- the brake should still bite. Note
this raise does not self-reverse: rule 1 only ratchets DOWN to actual x 1.10, which at 6,391 actual is
7,030, so 6500 stands until a deliberate cut takes the file under 5,909.)
-> 6392 (2026-09-20, ratcheted down under rule 1 after the bloat-review reduction 6,494 -> 5,811:
min(6500, 5,811 x 1.10 = 6,392). Rule 1 next applies below 5,811; raising again needs rule 2.)
-> 6440 (2026-10-09, raised by EXPLICIT USER DECISION under rule 2 in the /qdream sweep, option (a)
chosen over cutting ~40 words elsewhere or a Claude-only steering line: one known demand, the 41-word
user-mandated branch-approval rule in Commit Safety, which takes the file to 6,426.)

Selftest: `verify-mass.py --selftest` builds synthetic repos in a temp folder and checks an all-OK run,
an OVER run, a missing measured file, each exit-2 precondition, an unreadable measured file, a BOM file,
the ASCII-only separator set, and that dream-sweep.py's mass_rows parses this file's BUDGETS tuple
(including a row with a trailing comment) and reports an unparseable row. The existing cases run with the
TOTAL lines off; separate cases check the TOTAL lines (per-client files and catalogue, a missing file, a CRLF
inventory, an OVER run, a failure to compute) and that the real repo yields four.
"""
import os
import re
import sys

NAME = "verify-mass.py"

BUDGETS = (
    ("shared/AGENTS.md", 6440),
)

SEPARATORS = re.compile(r"[ \t\r\n]+")
REMEDIATION = ("REMEDIATION\tMove content to an on-demand file and cite it from here, or raise the budget "
               "row in BUDGETS in the same commit as the growth with a user-approved justification in "
               "the commit body. Never satisfy the budget by cutting load-bearing rules -- the "
               "Proportionality/Leanness review standard judges WHAT was cut.")


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


def _read(path):
    """A measured file's text, UTF-8 with a leading BOM dropped. Invalid UTF-8 is replaced, which never
    moves a token boundary because every separator is ASCII."""
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return fh.read()


def count_words(path):
    """The pinned count: tokens between runs of ASCII whitespace."""
    return len([w for w in SEPARATORS.split(_read(path)) if w])


def run(argv, budgets=BUDGETS, totals=True):
    """-> (exit code, stdout lines, stderr lines). No side effects. Any unexpected error is exit 2, "guard
    did not run", with the rows already produced kept: exit 1 means only a real OVER finding. `totals`
    adds the report-only TOTAL lines."""
    out, err = [], []
    try:
        return _run(argv, budgets, totals, out, err)
    except Exception as exc:
        err.append("%s: guard did not run: %s: %s" % (NAME, type(exc).__name__, exc))
        return 2, out, err


def _run(argv, budgets, totals, out, err):
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
    ok = over = 0
    for rel, budget in budgets:
        path = os.path.join(repo, *rel.split("/"))
        if not os.path.isfile(path):
            err.append("%s: measured file missing: %s" % (NAME, rel))
            return 2, out, err
        words = count_words(path)
        if words <= budget:
            out.append("OK\t%s\t%d\t%d" % (rel, words, budget))
            ok += 1
        else:
            out.append("OVER\t%s\t%d\t%d" % (rel, words, budget))
            over += 1
    out.append("SUMMARY\tok=%d\tover=%d" % (ok, over))
    if over:
        out.append(REMEDIATION)
    if totals:
        out.extend(total_lines(repo))
    return (1 if over else 0), out, err


# --- report-only fixed cost per client ---
CLIENT_MODES = {"claude": ("claude",), "codex": ("codex",), "gemini": ("gemini",), "kiro": ("kiro", "kiro-always")}
CLIENT_DIR = {"claude": "~/.claude/", "codex": "~/.codex/", "gemini": "~/.gemini/", "kiro": "~/.kiro/"}
AGENT_TEMPLATE_DEST = "~/.kiro/agents/kiro_default.md"
PLAYBOOK_ROOT_PREFIX = "file://{{PLAYBOOK_ROOT}}/"


def _always_loaded(client, dest):
    """True when the client reads the file at `dest` (an inventory destination) at every session start."""
    if client == "claude":
        return dest == "~/.claude/CLAUDE.md" or (dest.startswith("~/.claude/rules/") and dest.endswith(".md"))
    if client == "codex":
        return dest == "~/.codex/AGENTS.md"
    if client == "gemini":
        return dest in ("~/.gemini/GEMINI.md", "~/.gemini/AGENT-PLAYBOOK.md")
    return (dest.startswith("~/.kiro/steering/") and dest.endswith(".md")) or dest == AGENT_TEMPLATE_DEST


def _manifest(repo):
    """-> [(dest, source, mode)] from inventory.tsv: four tab-separated columns, no comment or blank line."""
    rows = []
    for line in _read(os.path.join(repo, "inventory.tsv")).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) == 4:
            rows.append((cols[1], cols[2], cols[3]))
    return rows


def _skill_folders(repo, root_rel, standalone_only):
    root = os.path.join(repo, *root_rel.split("/"))
    found = []
    if not os.path.isdir(root):
        return found
    for folder in sorted(os.listdir(root)):
        if folder.startswith(".") or folder == "synced" or folder.startswith(".bucket-"):
            continue
        d = os.path.join(root, folder)
        if not os.path.isfile(os.path.join(d, "SKILL.md")):
            continue
        if standalone_only and os.path.exists(os.path.join(d, "OVERLAY.md")):
            continue
        found.append(os.path.join(d, "SKILL.md"))
    return found


def description_words(skill_md):
    """Words in the `description:` frontmatter value of a SKILL.md (matching outer quotes dropped); 0 when
    the file has no frontmatter or no description."""
    lines = _read(skill_md).splitlines()
    if not lines or lines[0].strip() != "---":
        return 0
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            value = line[len("description:"):].strip()
            if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]
            return len([w for w in SEPARATORS.split(value) if w])
    return 0


def _agent_resources(repo, template):
    """-> [repo-relative file] the agent template's `resources:` list loads from the playbook checkout: each
    `file://{{PLAYBOOK_ROOT}}/<glob>` entry, expanded under the repo (a glob without `**` matches one level).
    Entries relative to the workspace or the home folder are not counted: the workspace is unknown here, and
    the steering ones are already counted through the inventory."""
    import glob
    found = []
    inside = False
    for line in _read(template).splitlines():
        if line.strip() == "---" and inside:
            break
        if line.startswith("resources:"):
            inside = True
            continue
        if inside and not line.startswith(" "):
            break
        item = line.strip()
        if inside and item.startswith("- "):
            item = item[2:].strip().strip("\"'")
            if item.startswith(PLAYBOOK_ROOT_PREFIX):
                pattern = os.path.join(repo, *item[len(PLAYBOOK_ROOT_PREFIX):].split("/"))
                for path in sorted(glob.glob(pattern)):
                    if os.path.isfile(path):
                        found.append(os.path.relpath(path, repo).replace(os.sep, "/"))
    return found


def total_lines(repo):
    """-> one `TOTAL\\t<client>\\t<N> words\\t(<detail>)` line per client, never an error: the words the
    client's always-loaded governance files hold plus the skill-description catalogue. Measured from the
    repo sources and inventory.tsv, not from the live home. Report-only: no ceiling, never changes the exit
    code. A computation error becomes a WARN line."""
    try:
        manifest = _manifest(repo)
        shared = _skill_folders(repo, "shared/skills", False)
        standalone = _skill_folders(repo, "providers/kiro/skills", True)
        lines = []
        for client in ("claude", "codex", "gemini", "kiro"):
            parts, total = [], 0

            def add(label, rel):
                path = os.path.join(repo, *rel.split("/"))
                if os.path.isfile(path):
                    n = count_words(path)
                    parts.append("%s=%d" % (label, n))
                    return n
                parts.append("%s=missing" % label)
                return 0
            for dest, source, mode in manifest:
                if mode in CLIENT_MODES[client] and _always_loaded(client, dest):
                    total += add(dest[len(CLIENT_DIR[client]):], source)
                    if dest == AGENT_TEMPLATE_DEST:
                        for rel in _agent_resources(repo, os.path.join(repo, *source.split("/"))):
                            total += add(rel, rel)
            skills = shared + (standalone if client == "kiro" else [])
            catalogue = sum(description_words(p) for p in skills)
            total += catalogue
            lines.append("TOTAL\t%s\t%d words\t(%s; skill descriptions=%d over %d skills)"
                         % (client, total, ", ".join(parts) if parts else "no governance file", catalogue, len(skills)))
        return lines
    except Exception as exc:
        return ["WARN\tTOTAL not computed (%s: %s)" % (type(exc).__name__, exc)]


def _load_dream_sweep():
    """dream-sweep.py loaded by path as a module (its main guard does not run), for mass_rows."""
    import importlib.util
    here = os.path.dirname(os.path.realpath(__file__))
    path = os.path.join(os.path.dirname(os.path.dirname(here)), "qdream", "scripts", "dream-sweep.py")
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("dream_sweep_for_verify_mass", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


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

    def repo(tag, files):
        root = os.path.join(tmp, tag)
        for rel, data in files.items():
            write(os.path.join(root, *rel.split("/")), data)
        return root

    two = (("shared/AGENTS.md", 5), ("shared/other.md", 3))

    def run0(argv, budgets=BUDGETS):
        return run(argv, budgets, totals=False)
    tmp = tempfile.mkdtemp(prefix="verify-mass-")
    try:
        # report-only TOTAL lines: governance files from the inventory plus the skill-description catalogue
        inv = ("# comment\n\nsymlink-file\t~/.claude/CLAUDE.md\tshared/AGENTS.md\tclaude\n"
               "symlink-file\t~/.claude/rules/playbook-user-memory.md\tmemory/MEMORY.md\tclaude\n"
               "symlink-file\t~/.claude/AUTHORING.md\tshared/AUTHORING.md\tclaude\n"
               "symlink-file\t~/.codex/AGENTS.md\tshared/AGENTS.md\tcodex\n"
               "symlink-file\t~/.gemini/GEMINI.md\tshared/AGENTS.md\tgemini\n"
               "template-file\t~/.kiro/agents/kiro_default.md\tproviders/kiro/agents/kiro_default.md\tkiro-always\n"
               "symlink-file\t~/.kiro/steering/agents.md\tshared/AGENTS.md\tkiro\n"
               "symlink-file\t~/.kiro/steering/kg.md\tproviders/kiro/steering/kg.md\tkiro\n").encode("utf-8")
        agent = (b"---\nresources:\n  - file://AGENTS.md\n  - file://memory/*.md\n"
                 b"  - \"file://{{PLAYBOOK_ROOT}}/memory/*.md\"\nwelcomeMessage: x\n---\nBody words here now\n")
        r = repo("totals", {
            "shared/AGENTS.md": b"a b c", "inventory.tsv": inv, "memory/MEMORY.md": b"m1 m2",
            "memory/topics/t.md": b"not counted by the one-level glob", "providers/kiro/agents/kiro_default.md": agent,
            "shared/skills/qa/SKILL.md": b"---\nname: qa\ndescription: one two three\n---\nbody body body\n",
            "shared/skills/qb/SKILL.md": b"---\nname: qb\ndescription: \"four five\"\n---\nx\n",
            "shared/skills/synced/SKILL.md": b"---\ndescription: ignored ignored\n---\n",
            "providers/kiro/skills/qk/SKILL.md": b"---\nname: qk\ndescription: 'six'\n---\n",
            "providers/kiro/skills/qa/OVERLAY.md": b"overlay words\n",
            "providers/kiro/skills/qa/SKILL.md": b"---\ndescription: ignored ignored ignored\n---\n"})
        agent_words = len([w for w in SEPARATORS.split(agent.decode("utf-8")) if w])
        t = total_lines(r)
        chk("TOTAL: claude counts CLAUDE.md and a rules row, plus the catalogue (description words only)",
            t[0] == "TOTAL\tclaude\t10 words\t(CLAUDE.md=3, rules/playbook-user-memory.md=2; "
                    "skill descriptions=5 over 2 skills)", repr(t[:1]))
        chk("TOTAL: codex and gemini count their one file", t[1] == "TOTAL\tcodex\t8 words\t(AGENTS.md=3; skill descriptions=5 over 2 skills)"
            and t[2] == "TOTAL\tgemini\t8 words\t(GEMINI.md=3; skill descriptions=5 over 2 skills)", repr(t[1:3]))
        chk("TOTAL: kiro counts the agent definition, its PLAYBOOK_ROOT resources, steering (a missing file adds 0) and "
            "the standalone Kiro skill, not an overlay folder",
            t[3] == "TOTAL\tkiro\t%d words\t(agents/kiro_default.md=%d, memory/MEMORY.md=2, steering/agents.md=3, "
                    "steering/kg.md=missing; skill descriptions=6 over 3 skills)" % (agent_words + 2 + 3 + 6, agent_words)
            and len(t) == 4, repr(t[3:]))
        rc, out, err = run([r], (("shared/AGENTS.md", 2),))
        chk("TOTAL lines follow an OVER run's REMEDIATION and do not change its exit code",
            rc == 1 and out[0].startswith("OVER") and out[2] == REMEDIATION and out[3:] == t and not err, "%s %r" % (rc, out))
        rc, out, err = run([r], (("shared/AGENTS.md", 99),))
        chk("TOTAL lines follow SUMMARY on a passing run, exit 0", rc == 0 and out[1].startswith("SUMMARY") and out[2:] == t,
            "%s %r" % (rc, out))
        r2 = repo("totals-noinv", {"shared/AGENTS.md": b"a b c"})
        rc, out, err = run([r2], (("shared/AGENTS.md", 99),))
        chk("a failure computing TOTAL is a WARN line, never an error",
            rc == 0 and not err and len(out) == 3 and out[2].startswith("WARN\tTOTAL not computed (FileNotFoundError"), repr(out))
        r3 = repo("totals-crlf", {"shared/AGENTS.md": b"a b c", "inventory.tsv": b"symlink-file\t~/.codex/AGENTS.md\tshared/AGENTS.md\tcodex\r\n",
                                  "shared/skills/qa/SKILL.md": b"---\r\ndescription: one two\r\n---\r\n"})
        t3 = total_lines(r3)
        chk("TOTAL: CRLF inventory and SKILL.md count the same, a client with no row says so",
            t3[1] == "TOTAL\tcodex\t5 words\t(AGENTS.md=3; skill descriptions=2 over 1 skills)"
            and t3[0].startswith("TOTAL\tclaude\t2 words\t(no governance file;"), repr(t3))
        real_repo = os.path.realpath(__file__)
        for _ in range(5):  # verify-mass.py -> scripts -> qconfig-sync -> skills -> shared -> repo
            real_repo = os.path.dirname(real_repo)
        real = total_lines(real_repo)
        chk("TOTAL: the real repo gives four TOTAL lines with a positive word count",
            len(real) == 4 and all(re.match(r"^TOTAL\t(claude|codex|gemini|kiro)\t[1-9]\d* words\t", l) for l in real), repr(real))

        # all OK, including a file exactly at its ceiling (OK is <=, not <)
        r = repo("ok", {"shared/AGENTS.md": b"one two\n\nthree  four\tfive\n", "shared/other.md": b"a b"})
        rc, out, err = run0([r], two)
        chk("all-OK run exits 0 with OK rows and SUMMARY",
            rc == 0 and out == ["OK\tshared/AGENTS.md\t5\t5", "OK\tshared/other.md\t2\t3",
                                "SUMMARY\tok=2\tover=0"] and not err, "%s %r %r" % (rc, out, err))

        # one word over its ceiling
        r = repo("over", {"shared/AGENTS.md": b"one two three four five six\n", "shared/other.md": b"a"})
        rc, out, err = run0([r], two)
        chk("OVER run exits 1 with an OVER row, SUMMARY and REMEDIATION",
            rc == 1 and out == ["OVER\tshared/AGENTS.md\t6\t5", "OK\tshared/other.md\t1\t3",
                                "SUMMARY\tok=1\tover=1", REMEDIATION] and not err, "%s %r %r" % (rc, out, err))

        # pinned separators: CRLF, tabs and runs split; NBSP, \v and \f do not
        r = repo("sep", {"shared/AGENTS.md": b"a\r\nb\t\tc  \r\n\r\nd\xc2\xa0e f\x0bg h\x0ci\n"})
        rc, out, _e = run0([r], (("shared/AGENTS.md", 99),))
        chk("only ASCII space, tab, CR and LF separate words", rc == 0 and out[:1] == ["OK\tshared/AGENTS.md\t6\t99"],
            repr(out))

        # a leading BOM does not change the count, even when whitespace follows it
        r = repo("bom", {"shared/AGENTS.md": b"\xef\xbb\xbf\none two\r\nthree\r\n"})
        rc, out, _e = run0([r], (("shared/AGENTS.md", 3),))
        chk("a leading BOM is not a word", rc == 0 and out[:1] == ["OK\tshared/AGENTS.md\t3\t3"], repr(out))

        # an empty measured file counts 0
        r = repo("empty", {"shared/AGENTS.md": b""})
        rc, out, _e = run0([r], (("shared/AGENTS.md", 0),))
        chk("an empty file is 0 words", rc == 0 and out[:1] == ["OK\tshared/AGENTS.md\t0\t0"], repr(out))

        # a measured file missing: rows before it are printed, then exit 2
        r = repo("missing", {"shared/AGENTS.md": b"x\n"})
        rc, out, err = run0([r], two)
        chk("a missing measured file exits 2 with its reason",
            rc == 2 and out == ["OK\tshared/AGENTS.md\t1\t5"]
            and err == ["%s: measured file missing: shared/other.md" % NAME], "%s %r %r" % (rc, out, err))

        # an unreadable measured file (injected OSError on one path): rows before it kept, exit 2, not 1
        r = repo("unreadable", {"shared/AGENTS.md": b"x\n", "shared/other.md": b"a b c d e\n"})
        real_read = globals()["_read"]
        bad = os.path.join(r, "shared", "other.md")

        def failing_read(path):
            if os.path.normcase(path) == os.path.normcase(bad):
                raise PermissionError("injected: %s" % path)
            return real_read(path)
        globals()["_read"] = failing_read
        try:
            rc, out, err = run0([r], two)
        except Exception as exc:
            rc, out, err = "raised", [], ["%s: %s" % (type(exc).__name__, exc)]
        finally:
            globals()["_read"] = real_read
        chk("an unreadable measured file exits 2 'guard did not run', keeping earlier rows",
            rc == 2 and out == ["OK\tshared/AGENTS.md\t1\t5"]
            and err == ["%s: guard did not run: PermissionError: injected: %s" % (NAME, bad)],
            "%s %r %r" % (rc, out, err))

        # exit-2 preconditions
        rc, out, err = run0([])
        chk("no repo argument exits 2",
            rc == 2 and not out and err == ["%s: repo-root argument is required (deliberately never derived "
                                            "from cwd)" % NAME], "%s %r" % (rc, err))
        gone = os.path.join(tmp, "no-such-dir")
        rc, out, err = run0([gone])
        chk("a nonexistent repo exits 2",
            rc == 2 and not out and err == ["%s: repo path not found: %s" % (NAME, gone)], "%s %r" % (rc, err))
        rc, out, err = run0([""])
        chk("an empty repo argument exits 2 as not found",
            rc == 2 and err == ["%s: repo path not found: " % NAME], "%s %r" % (rc, err))
        r = repo("notplaybook", {"README.md": b"x\n"})
        rc, out, err = run0([r])
        chk("a folder without shared/AGENTS.md exits 2",
            rc == 2 and not out and err == ["%s: %s does not look like an agent-playbook repo" % (NAME, r)],
            "%s %r" % (rc, err))

        # the BUDGETS tuple parses with dream-sweep.py's mass_rows, from this file and from a fixture copy
        here = os.path.realpath(__file__)
        real_repo = here
        for _ in range(5):  # verify-mass.py -> scripts -> qconfig-sync -> skills -> shared -> repo
            real_repo = os.path.dirname(real_repo)
        try:
            ds = _load_dream_sweep()
        except Exception as exc:
            ds = None
            chk("dream-sweep.py loads", False, "%s: %s" % (type(exc).__name__, exc))
        if ds is not None:
            rows, note = ds.mass_rows(real_repo)
            chk("dream-sweep mass_rows reads this BUDGETS tuple", rows == list(BUDGETS) and note is None,
                "%r %r" % (rows, note))
            with open(here, "rb") as fh:
                me = fh.read()
            r = repo("parse", {"shared/skills/qconfig-sync/scripts/verify-mass.py": me.replace(
                b'    ("shared/AGENTS.md", 6440),\n',
                b'    ("shared/AGENTS.md", 6440),\n    ("shared/other.md", 12),\n', 1)})
            rows, note = ds.mass_rows(r)
            chk("dream-sweep mass_rows reads a second row", rows[-1:] == [("shared/other.md", 12)]
                and len(rows) == len(BUDGETS) + 1 and note is None, "%r %r" % (rows, note))

            def budgets_repo(tag, body):
                head, sep, tail = me.partition(b"\nBUDGETS = (\n")
                body_end = tail.index(b"\n)\n")
                return repo(tag, {"shared/skills/qconfig-sync/scripts/verify-mass.py":
                                  head + sep + body + tail[body_end:]})
            r = budgets_repo("comment-row", b'    # pins\n    ( "shared/AGENTS.md" , 6440 ),  # rule 2, 2026-10-09\n'
                                            b'\n    ("shared/other.md", 7)')
            rows, note = ds.mass_rows(r)
            chk("dream-sweep mass_rows parses a trailing-comment row and skips comment and blank lines",
                rows == [("shared/AGENTS.md", 6440), ("shared/other.md", 7)] and note is None,
                "%r %r" % (rows, note))
            r = budgets_repo("bad-row", b'    ("shared/AGENTS.md", 6440),\n    ("shared/other.md", 6_440),')
            rows, note = ds.mass_rows(r)
            chk("dream-sweep mass_rows reports an unparseable row instead of dropping its pin",
                rows == [] and note is not None and "unparsed" in note, "%r %r" % (rows, note))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f in fails:
        print("FAIL: %s" % f)
    print("verify-mass selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
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
