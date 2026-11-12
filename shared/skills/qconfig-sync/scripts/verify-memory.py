#!/usr/bin/env python3
"""verify-memory.py -- deterministic guard for the structure of every memory file.

Plan 261016 Phase 12 (SC-11). Python only, no sh/ps1 twin, so it is outside test-parity.sh's tally. It
absorbs verify-topics.{sh,ps1}: the topic-citation check below is a port of it. Run with the playbook venv
(<repo>/.venv-agent-playbook); any other interpreter exits 2 ("guard did not run: venv missing"). Stdlib
only, Python 3.8+. It reads memory files and inventory.tsv, writes nothing, runs no git and touches no
network. Entries are read with the one memory-entry parser, shared/skills/qdream/scripts/memory-entries.py;
the store repo is listed with the store resolver's scan_stores.

Usage:
  verify-memory.py <repo> [--stores DIR] [--topics]
  verify-memory.py --selftest | --help

  <repo>        The config repo. MANDATORY (exit 2 when absent): repo context is never derived from the
                ambient cwd (the verify-mass precedent).
  --stores DIR  The store repo (default: AGENT_PLAYBOOK_STORES, else stores= in ~/.agent-playbook/config,
                else ~/.agent-playbook/stores).
  --topics      Run only the topic-citation check (the former verify-topics guard), on <repo> alone.

Scope: <repo>/memory/MEMORY.md (required), <repo>/memory/HIGHER_ORDER.md and <repo>/memory/topics/*.md (each
skipped when absent), and memory/MEMORY.md of every store scan_stores returns as valid (a store with an
invalid STORE file is verify-stores' finding and is skipped here). A store repo that is missing (no
directory or no .git) is a SKIP line, as in verify-stores; any other scan failure exits 2.

Terms. A "type section" is a `## ` section named exactly Feedback, Decision or Pattern (memory-rules.md
§ Memory File Format). An "entry" is a `### ` heading in a section, as memory-entries.py defines it (fenced
lines are never headings). The "user tier" is memory/MEMORY.md plus memory/topics/*.md (shared/AGENTS.md
§ Memory locations: topic memory is "user memory that loads on demand"; same tier).

FAIL rules (exit 1):
  dup-type-heading     `## Feedback`, `## Decision` or `## Pattern` appears twice in one file
                       (memory-rules.md § Memory File Format: "A second ## Feedback ... heading breaks the
                       type partition").
  declined-missing     <repo>/memory/MEMORY.md has no `## Declined`. Only that file: memory-rules.md
                       § Declined records says "Never remove the ## Declined heading" of the file
                       verify-citations guards, and "An absent ## Declined section means 'no declinations',
                       not an error -- project memory files created before this section predate it", so a
                       store file may lack it. HIGHER_ORDER.md and topic files never carry one (§ Higher-Order
                       Tier's format has none; the Declined paragraph names memory/MEMORY.md).
  declined-duplicate   `## Declined` appears twice in any file.
  heading-outside-type a `### ` line outside a type section: under any other `## ` section, or under no `## `
                       section at all (a preamble after a `# ` title). No exception is needed: Declined rows
                       are `- ` bullets, Topics rows are table rows, and HIGHER_ORDER.md's preamble holds no
                       `###` (§ Higher-Order Tier: "the same type-section layout"). memory-entries.py drops a
                       `###` with no enclosing `##`, so that one case is found by a fence-aware line walk on
                       the parser's own normalize() and FENCE_RE; it is not a second entry parser.
  verified-invalid     an unfenced `**Verified**:` field in an entry whose value does not start with a real
                       calendar YYYY-MM-DD date (§ Memory File Format; § Date References). A field opens a
                       line (after list, numbered-list or quote markers) or follows a ` | `; the name inside a
                       backtick code span or a quoted span, mid-sentence, or on an Evidence-quote /
                       Governance-conflict-quote line is prose, not a field.
  source-pipe          an unfenced Source line (the parser's SOURCE_RE) holds two or more ` | `
                       (§ Memory File Format, the Verified annotation: "the grammar keeps one per line").
                       The line is cut at its first ` | **Verified**:` tail outside every span (else its
                       first one) and each side is counted without
                       its backtick code spans and quoted spans ("..." or \u201c...\u201d), which are anchor
                       text. So an Outcome after the Verified value is a FAIL (it belongs on its own line,
                       § Cross-type optional metadata), and a quote cannot hide a pipe across the tail.
  heading-too-long     an entry heading over 200 characters (SC-16: "within today's length").
  conflict-marker      an unfenced git conflict marker line: `<<<<<<< `, `>>>>>>> ` (or the bare marker), and
                       `=======` after an opening marker (alone it is a Markdown heading underline). A rebase
                       or merge resolved without removing them leaves both sides as entries.
  heading-duplicate    one entry heading (compared exactly, ASCII whitespace stripped) twice in one file, or
                       in two user-tier files. HIGHER_ORDER.md is a separate tier (shared/AGENTS.md § Memory
                       locations) and is compared only within itself; a node sharing a base entry's heading
                       is not flagged, though § Higher-Order Tier says "do not duplicate a single base entry
                       up a level". Store files are project tier and are compared only within themselves.
  topic-citation       a `## Topics` row of <repo>/memory/MEMORY.md with no always-loaded citer (the port of
                       verify-topics, below). The detail keeps verify-topics' MISSING token and wording:
                       "MISSING <topic> <detail>".
  unreadable           an in-scope file other than <repo>/memory/MEMORY.md that is not UTF-8 text (invalid
                       UTF-8, a UTF-16 byte-order mark, or a NUL byte): the guard ran and the file is
                       defective. <repo>/memory/MEMORY.md and inventory.tsv instead exit 2, as in
                       verify-topics.

WARN rules (never change the exit code):
  missing-field        an entry in a type section lacks **Why**, **How to apply** or **Source**
                       (§ Memory File Format: all three types carry all three; HIGHER_ORDER nodes too).
                       An [improvement_signal] entry is checked by signal-incomplete instead.
  signal-incomplete    an entry whose heading starts with `[improvement_signal]` lacks **Target**, **Why**,
                       **Frequency**, **Sessions** or **Last observed** (§ `[improvement_signal]` sub-form;
                       Evidence-quote is optional, "entries persisted before this field was introduced
                       remain valid", and Source is optional).
  signal-verified      an `[improvement_signal]` entry carries a **Verified** field, read as verified-invalid
                       reads one (§ `[improvement_signal]`
                       sub-form: "a signal never carries a `**Verified**` field").
  relative-date        the heading or an unfenced body line, outside backtick code spans and outside the
                       verbatim **Evidence-quote** / **Governance-conflict-quote** lines, matches
                       \\b(today|yesterday|tomorrow|(last|this|next)\\s+(week|month|year|session))\\b,
                       case-insensitive (§ Date References: "Never use relative references").
  A field is present when an unfenced body line holds `**<Field>**:` (or `**<Field>:**`) anywhere on it.

Topic-citation check (the verify-topics port; its rules are kept exactly). For each row of the `## Topics`
table in memory/MEMORY.md: every row must have exactly three cells; the first is one backticked topic path;
every backticked span of the last cell is a candidate citer (a " § <anchor>" suffix dropped, a bare
`AGENTS.md` naming the repo root's AGENTS.md). A row is OK when one candidate (a) matches the citer-path
allowlist ([A-Za-z0-9._-] segments joined by single `/`, no segment ending in `.`), (b) exists as a file,
(c) is UTF-8 text, (d) contains the topic path, and (e) is accepted: an inventory.tsv destination of
~/.claude/CLAUDE.md, ~/.codex/AGENTS.md, ~/.gemini/GEMINI.md, a co-existence link beside one
(~/.claude/rules/agent-playbook.md, ~/.gemini/AGENT-PLAYBOOK.md) or under ~/.kiro/steering/ (four-field rows,
`#` comments skipped), shared/skills/<name>/SKILL.md, providers/<p>/skills/<name>/SKILL.md with no sibling
OVERLAY.md, or the root AGENTS.md. A row with no passing citer is still OK when its last cell holds the
waiver "(no always-loaded home — index only)". Otherwise the detail is "none-cited", or
"<citer>:<reason>" per candidate joined by ";", reason the first failing test of bad-path, not-found,
not-utf8, no-reference, not-always-loaded. A UTF-8 BOM and one trailing CR per line are ignored. The
section is located with the parser's sections() (so a fenced `## Topics` no longer starts it, the one
change from verify-topics); the rows are walked here, not with topic_rows(), because the parser skips a
malformed row where this check must stop. OK and waived rows are not printed. Exit 2, nothing on stdout:
memory/MEMORY.md or inventory.tsv missing, unreadable or not UTF-8 text; no `## Topics` heading; a row
without exactly three cells; a data row whose first cell is not one backticked path; no table (a
header row with no data rows is a fresh memory with no topic yet, and passes).

Output: one tab-separated line per finding, in file then line order:
  FAIL\\t<file>\\t<line>\\t<rule>\\t<detail>      WARN\\t<file>\\t<line>\\t<rule>\\t<detail>
then SUMMARY\\tfail=N\\twarn=N\\tfiles=N. <file> is repo-relative for repo files and absolute for store files;
<line> is 1-based (0 for a whole-file finding). A missing store repo adds a SKIP\\t<path>\\t0\\tstores\\t...
line. No detail echoes entry text beyond the heading (a long heading is cut to 60 characters).

Exit codes: 0 no FAIL (clean, or WARN only); 1 a FAIL; 2 the guard could not run (bad arguments, repo not
found, venv missing, memory/MEMORY.md or inventory.tsv unusable, the store scan failed).
"""
import argparse
import datetime
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(os.path.realpath(__file__)).parent
SKILLS = HERE.parents[1]  # scripts -> qconfig-sync -> skills
QDREAM_SCRIPTS = SKILLS / "qdream" / "scripts"
FIXTURES = HERE / "fixtures"
ASCII_WS = " \t\r\n\v\f"
TYPE_SECTIONS = ("Feedback", "Decision", "Pattern")
HEADING_MAX = 200
SIGNAL_PREFIX = "[improvement_signal]"
SIGNAL_FIELDS = ("Target", "Why", "Frequency", "Sessions", "Last observed")
ENTRY_FIELDS = ("Why", "How to apply", "Source")
RELATIVE_RE = re.compile(r"\b(today|yesterday|tomorrow|(last|this|next)\s+(week|month|year|session))\b",
                         re.IGNORECASE)
QUOTE_LINE_RE = re.compile(r"^\W*\*\*(Evidence-quote|Governance-conflict-quote)(?:\*\*:|:\*\*)")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
QUOTED_SPAN_RE = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d')
# A Verified field opens a line (after list or quote markers) or follows a ` | `; anywhere else it is prose.
VERIFIED_FIELD_RE = re.compile(r"(?:^[ \t>*+_-]*(?:\d+[.)][ \t]+)?_*|\|[ \t]*)\*\*Verified(?:\*\*:|:\*\*)[ \t]*(\S*)")
# The Source line's Verified tail: the one ` | ` the grammar allows (memory-rules.md § Memory File Format).
VERIFIED_TAIL_RE = re.compile(r"[ \t]\|[ \t]*\*\*Verified(?:\*\*:|:\*\*)")
DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?!\d)")
CONFLICT_EDGE_RE = re.compile(r"^(<{7}|>{7})(?: |$)")
CONFLICT_MID_RE = re.compile(r"^={7}$")
# The spelling memory-entries.py's verified() does not read (it reads **Verified**: only).
VERIFIED_OFF_SPELLING_RE = re.compile(r"\*\*Verified:\*\*")
WAIVER = "(no always-loaded home — index only)"
CITER_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", re.ASCII)
SKILL_RE = re.compile(r"shared/skills/[^/]+/SKILL\.md")
PROVIDER_SKILL_RE = re.compile(r"providers/[^/]+/skills/[^/]+/SKILL\.md")
SEPARATOR_RE = re.compile(r":?-+:?")
FIRST_CELL_RE = re.compile(r"`([^`]+)`")
SPAN_RE = re.compile(r"`([^`]*)`")
# The instruction files, and the co-existence links setup makes beside a user's own CLAUDE.md or GEMINI.md
# (setup.sh "Co-existence"): those load in every session too.
ACCEPTED_DESTS = ("~/.claude/CLAUDE.md", "~/.codex/AGENTS.md", "~/.gemini/GEMINI.md",
                  "~/.claude/rules/agent-playbook.md", "~/.gemini/AGENT-PLAYBOOK.md")
KIRO_STEERING = "~/.kiro/steering/"


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


class CouldNotRun(Exception):
    """The guard cannot give a verdict (exit 2); the text is the stderr reason."""


def _load(name, filename):
    path = QDREAM_SCRIPTS / filename
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise CouldNotRun("cannot load %s (%s: %s)" % (path, type(exc).__name__, exc))
    return mod


def trim(s):
    return s.strip(ASCII_WS)


def short(heading):
    return heading if len(heading) <= 60 else heading[:60] + "..."


def not_utf8(data):
    """True when the bytes start with a UTF-16 byte-order mark, hold a NUL, or are not valid UTF-8."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def read_lines(data):
    """verify-topics' read_lines: a BOM dropped from the first line, one trailing CR from every line, a
    final line without a newline kept."""
    text = data.decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [p[:-1] if p.endswith("\r") else p for p in parts]


def read_bytes(path, label):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise CouldNotRun("could not read %s (%s)" % (label, exc))


# ---------------------------------------------------------------------------
# One memory file, read once
# ---------------------------------------------------------------------------

class MemFile:
    def __init__(self, ME, label, text, kind):
        self.label = label
        self.kind = kind  # root | higher | topic | store
        self.text = text
        self.sections = ME.sections(text)
        self.entries = []
        for section, heading, body, line_no in ME.entries(text):
            unfenced = []  # (line_no, line) outside a fence
            fence = None
            for i, line in enumerate(body):
                fm = ME.FENCE_RE.match(line)
                if fence:
                    if fm and fm.group(1) == fence:
                        fence = None
                    continue
                if fm:
                    fence = fm.group(1)
                    continue
                unfenced.append((line_no + 1 + i, line))
            self.entries.append((section, heading, body, line_no, unfenced))
        self.orphan_headings = self._orphan_headings(ME)

    def _orphan_headings(self, ME):
        """`### ` lines under no `## ` section (memory-entries.py drops them): [(line_no, heading)]."""
        out, section, fence = [], None, None
        for no, line in enumerate(ME.normalize(self.text).split("\n"), 1):
            fm = ME.FENCE_RE.match(line)
            if fence:
                if fm and fm.group(1) == fence:
                    fence = None
                continue
            if fm:
                fence = fm.group(1)
                continue
            if line.startswith("### "):
                if section is None:
                    out.append((no, line[4:].strip()))
            elif line.startswith("## "):
                section = line.strip()[3:]
            elif line.startswith("# "):
                section = None
        return out


def has_field(unfenced, field):
    pat = re.compile(r"\*\*" + re.escape(field) + r"(?:\*\*:|:\*\*)")
    return any(pat.search(line) for _no, line in unfenced)


# ---------------------------------------------------------------------------
# Rules. Each takes (mf, ctx) and returns [(severity, line, detail)].
# ---------------------------------------------------------------------------

def rule_dup_type_heading(mf, ctx):
    """FAIL: a type heading twice in one file."""
    out, first = [], {}
    for name, no in mf.sections:
        if name in TYPE_SECTIONS:
            if name in first:
                out.append(("FAIL", no, "second '## %s' (first at line %d)" % (name, first[name])))
            else:
                first[name] = no
    return out


def rule_declined_missing(mf, ctx):
    """FAIL: the repo's memory/MEMORY.md has no ## Declined."""
    if mf.kind != "root":
        return []
    if any(name == "Declined" for name, _no in mf.sections):
        return []
    return [("FAIL", 0, "no '## Declined' heading (memory-rules.md § Declined records: never drop it)")]


def rule_declined_duplicate(mf, ctx):
    """FAIL: ## Declined twice in one file."""
    out, first = [], None
    for name, no in mf.sections:
        if name == "Declined":
            if first is None:
                first = no
            else:
                out.append(("FAIL", no, "second '## Declined' (first at line %d)" % first))
    return out


def rule_heading_outside_type(mf, ctx):
    """FAIL: a ### outside a type section."""
    out = []
    for section, heading, _body, no, _u in mf.entries:
        if section not in TYPE_SECTIONS:
            out.append(("FAIL", no, "'### %s' under '## %s', not a type section" % (short(heading), section)))
    for no, heading in mf.orphan_headings:
        out.append(("FAIL", no, "'### %s' under no '## ' section" % short(heading)))
    return out


def blank_spans(line):
    """The line with its backtick code spans and quoted spans blanked to spaces (offsets kept)."""
    line = CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)
    return QUOTED_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)


def verified_values(line):
    """The values of the Verified fields on a body line: never on a quote line, never inside a span."""
    if QUOTE_LINE_RE.match(line):
        return []
    return [m.group(1) for m in VERIFIED_FIELD_RE.finditer(blank_spans(line))]


def rule_verified_invalid(mf, ctx):
    """FAIL: a Verified value that is not a real calendar date."""
    out = []
    for section, heading, _body, _no, unfenced in mf.entries:
        for line_no, line in unfenced:
            for value in verified_values(line):
                d = DATE_PREFIX_RE.match(value)
                ok = False
                if d:
                    try:
                        datetime.date(int(d.group(1)), int(d.group(2)), int(d.group(3)))
                        ok = True
                    except ValueError:
                        ok = False
                if not ok:
                    out.append(("FAIL", line_no, "%s: Verified is not a real YYYY-MM-DD date" % short(heading)))
    return out


def rule_source_pipe(mf, ctx):
    """FAIL: a second ' | ' on a Source line. The line is cut at its Verified tail first; a pipe inside a
    code span or a quoted span ("..." or \u201c...\u201d) on either side is anchor text, not a separator."""
    out = []
    ME = ctx["ME"]

    def pipes(s):
        return QUOTED_SPAN_RE.sub(" ", CODE_SPAN_RE.sub(" ", s)).count(" | ")
    for _section, heading, _body, _no, unfenced in mf.entries:
        for line_no, line in unfenced:
            if ME.SOURCE_RE.match(line):
                m = VERIFIED_TAIL_RE.search(blank_spans(line)) or VERIFIED_TAIL_RE.search(line)
                n = pipes(line) if m is None else pipes(line[:m.start()]) + 1 + pipes(line[m.end():])
                if n > 1:
                    out.append(("FAIL", line_no, "%s: Source line has %d ' | ' separators (at most 1)"
                                % (short(heading), n)))
    return out


def rule_heading_too_long(mf, ctx):
    """FAIL: an entry heading over 200 characters."""
    return [("FAIL", no, "'%s': %d characters (over %d)" % (short(h), len(h), HEADING_MAX))
            for _s, h, _b, no, _u in mf.entries if len(h) > HEADING_MAX]


def rule_heading_duplicate(mf, ctx):
    """FAIL: one heading twice in a file, or in two user-tier files."""
    out = []
    seen = ctx["user_headings"] if mf.kind in ("root", "topic") else {}
    for _s, heading, _b, no, _u in mf.entries:
        key = trim(heading)
        if key in seen:
            f, l = seen[key]
            where = ("line %d" % l) if f == mf.label else ("%s:%d" % (f, l))
            out.append(("FAIL", no, "'%s' duplicates the heading at %s" % (short(heading), where)))
        else:
            seen[key] = (mf.label, no)
    return out


def rule_topic_citation(mf, ctx):
    """FAIL: a Topics row with no always-loaded citer (verify-topics port)."""
    if mf.kind != "root":
        return []
    return [("FAIL", no, "MISSING %s %s" % (topic, detail)) for no, topic, detail in ctx["topic_missing"]]


def rule_unreadable(mf, ctx):
    """FAIL: an in-scope file that is not UTF-8 text (reported by the loader)."""
    return []  # emitted by run() while it reads the files; this entry keeps the rule name in the registry


def rule_missing_field(mf, ctx):
    """WARN: an entry without Why, How to apply or Source."""
    out = []
    ME = ctx["ME"]
    for section, heading, body, no, unfenced in mf.entries:
        if section not in TYPE_SECTIONS or heading.startswith(SIGNAL_PREFIX):
            continue
        missing = [f for f in ENTRY_FIELDS if f != "Source" and not has_field(unfenced, f)]
        if ME.source([l for _n, l in unfenced]) is None:
            missing.append("Source")
        if missing:
            out.append(("WARN", no, "%s: no %s" % (short(heading), ", ".join("**%s**" % f for f in missing))))
    return out


def rule_signal_incomplete(mf, ctx):
    """WARN: an [improvement_signal] without its required fields."""
    out = []
    for _section, heading, _body, no, unfenced in mf.entries:
        if not heading.startswith(SIGNAL_PREFIX):
            continue
        missing = [f for f in SIGNAL_FIELDS if not has_field(unfenced, f)]
        if missing:
            out.append(("WARN", no, "%s: missing %s" % (short(heading), ", ".join("**%s**" % f for f in missing))))
    return out


def rule_relative_date(mf, ctx):
    """WARN: a relative date word in an entry."""
    out = []
    for _section, heading, _body, no, unfenced in mf.entries:
        for line_no, line in [(no, heading)] + unfenced:
            if line_no != no and QUOTE_LINE_RE.match(line):
                continue
            m = RELATIVE_RE.search(CODE_SPAN_RE.sub(" ", line))
            if m:
                out.append(("WARN", line_no, "%s: relative date '%s' (memory-rules.md § Date References)"
                            % (short(heading), m.group(0))))
    return out


def rule_conflict_marker(mf, ctx):
    """FAIL: an unfenced git conflict marker line."""
    ME = ctx["ME"]
    out, fence, opened = [], None, False
    for no, line in enumerate(ME.normalize(mf.text).split("\n"), 1):
        fm = ME.FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        if CONFLICT_EDGE_RE.match(line):
            opened = line.startswith("<")
            out.append(("FAIL", no, "git conflict marker %r -- resolve the conflict and delete the marker "
                        "lines (both sides now read as entries)" % line[:7]))
        elif opened and CONFLICT_MID_RE.match(line):
            out.append(("FAIL", no, "git conflict marker '=======' -- resolve the conflict and delete the "
                        "marker lines"))
    return out


def rule_verified_spelling(mf, ctx):
    """WARN: a `**Verified:**` field, which the guard accepts but the parser's verified() never reads."""
    out = []
    for _section, heading, _body, _no, unfenced in mf.entries:
        for line_no, line in unfenced:
            if not QUOTE_LINE_RE.match(line) and VERIFIED_OFF_SPELLING_RE.search(blank_spans(line)):
                out.append(("WARN", line_no, "%s: write **Verified**: (the colon after the bold); readers "
                            "(memory-entries.py verified()) skip **Verified:**" % short(heading)))
    return out


def rule_signal_verified(mf, ctx):
    """WARN: an [improvement_signal] entry carrying a Verified field."""
    out = []
    for _section, heading, _body, no, unfenced in mf.entries:
        if heading.startswith(SIGNAL_PREFIX) and any(verified_values(line) for _n, line in unfenced):
            out.append(("WARN", no, "%s: a signal never carries **Verified** (memory-rules.md "
                        "§ [improvement_signal] sub-form)" % short(heading)))
    return out


RULES = (
    ("dup-type-heading", rule_dup_type_heading),
    ("declined-missing", rule_declined_missing),
    ("declined-duplicate", rule_declined_duplicate),
    ("heading-outside-type", rule_heading_outside_type),
    ("verified-invalid", rule_verified_invalid),
    ("source-pipe", rule_source_pipe),
    ("heading-too-long", rule_heading_too_long),
    ("conflict-marker", rule_conflict_marker),
    ("heading-duplicate", rule_heading_duplicate),
    ("topic-citation", rule_topic_citation),
    ("unreadable", rule_unreadable),
    ("missing-field", rule_missing_field),
    ("signal-incomplete", rule_signal_incomplete),
    ("relative-date", rule_relative_date),
    ("signal-verified", rule_signal_verified),
    ("verified-spelling", rule_verified_spelling),
)


# ---------------------------------------------------------------------------
# The topic-citation check (verify-topics port)
# ---------------------------------------------------------------------------

def bad_path(p):
    if not CITER_RE.fullmatch(p):
        return True
    return any(seg.endswith(".") for seg in p.split("/"))


def accepted_sources(inv_lines):
    out = []
    for l in inv_lines:
        t = trim(l)
        if not t or t.startswith("#"):
            continue
        parts = l.split("\t")
        if len(parts) != 4:
            continue
        dest, src = trim(parts[1]), trim(parts[2])
        if not src:
            continue
        if dest in ACCEPTED_DESTS or (dest.startswith(KIRO_STEERING) and len(dest) > len(KIRO_STEERING)):
            out.append(src)
    return out


def topic_check(ME, repo, mem_data, inv_data):
    """-> [(line_no, topic, detail)] for every MISSING row, in table order. Raises CouldNotRun."""
    inv = accepted_sources(read_lines(inv_data))
    mem_lines = read_lines(mem_data)
    secs = ME.sections(mem_data.decode("utf-8"))
    start = next((no for name, no in secs if name == "Topics"), None)
    if start is None:
        raise CouldNotRun("no '## Topics' heading in memory/MEMORY.md")
    end = next((no for _name, no in secs if no > start), len(mem_lines) + 1)
    rows = []
    for no in range(start + 1, min(end, len(mem_lines) + 1)):
        t = trim(mem_lines[no - 1])
        if t.startswith("|"):
            rows.append((no, t))

    def is_accepted(p):
        if p == "AGENTS.md" or SKILL_RE.fullmatch(p):
            return True
        if PROVIDER_SKILL_RE.fullmatch(p):
            return not os.path.isfile(os.path.join(repo, p[:-len("SKILL.md")] + "OVERLAY.md"))
        return p in inv

    missing, datarows, header = [], 0, False
    for no, row in rows:
        body = row[1:]
        if body.endswith("|"):
            body = body[:-1]
        cells = body.split("|")
        if len(cells) != 3:
            raise CouldNotRun("malformed Topics row (expected 3 cells, found %d): %s" % (len(cells), row))
        first = trim(cells[0])
        if first == "Topic file" or SEPARATOR_RE.fullmatch(first):
            header = header or first == "Topic file"
            continue
        m = FIRST_CELL_RE.fullmatch(first)
        if not m:
            raise CouldNotRun("malformed Topics row (first cell is not one backticked path): %s" % row)
        topic = trim(m.group(1))
        last = cells[2]
        datarows += 1
        passed, details = None, []
        for sp in SPAN_RE.findall(last):
            path = trim(sp.split("§", 1)[0])
            if not path:
                continue
            if bad_path(path):
                details.append(path + ":bad-path")
                continue
            full = os.path.join(repo, path)
            if not os.path.isfile(full):
                details.append(path + ":not-found")
                continue
            data = read_bytes(full, path)
            if not_utf8(data):
                details.append(path + ":not-utf8")
                continue
            if topic.encode("utf-8") not in data:
                details.append(path + ":no-reference")
                continue
            if not is_accepted(path):
                details.append(path + ":not-always-loaded")
                continue
            passed = path
            break
        if passed is None and WAIVER not in last:
            missing.append((no, topic, ";".join(details) if details else "none-cited"))
    # A table with its header and no rows is a fresh memory with no topic yet (setup's template); with
    # neither, the parser found no table, which must not pass as "every topic cited".
    if datarows == 0 and not header:
        raise CouldNotRun("the '## Topics' table has no data rows")
    return missing


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)


def parse(argv):
    ap = _Parser(add_help=False)
    ap.add_argument("repo", nargs="?", default=None)
    ap.add_argument("--stores", default=None)
    ap.add_argument("--topics", action="store_true")
    ap.add_argument("--help", "-h", action="store_true")
    return ap.parse_args(argv)


def run(argv, disabled=()):
    """-> (exit code, stdout lines, stderr lines). Never prints; the selftest calls it in process.
    `disabled`: rule names skipped (selftest only)."""
    try:
        opts = parse(argv)
    except _ArgError as exc:
        return 2, [], ["verify-memory.py: guard did not run: %s" % exc]
    if opts.help:
        return 0, __doc__.rstrip().split("\n"), []
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    try:
        if not opts.repo:
            raise CouldNotRun("repo-root argument is required (deliberately never derived from cwd)")
        repo = os.path.abspath(opts.repo)
        if not os.path.isdir(repo):
            raise CouldNotRun("repo path not found: %s" % repo)
        memp = os.path.join(repo, "memory", "MEMORY.md")
        invp = os.path.join(repo, "inventory.tsv")
        if not os.path.isfile(memp):
            raise CouldNotRun("memory/MEMORY.md not found under %s" % repo)
        if not os.path.isfile(invp):
            raise CouldNotRun("inventory.tsv not found under %s" % repo)
        mem_data = read_bytes(memp, "memory/MEMORY.md")
        inv_data = read_bytes(invp, "inventory.tsv")
        if not_utf8(mem_data):
            raise CouldNotRun("memory/MEMORY.md is not UTF-8 text (invalid UTF-8, UTF-16 byte-order mark or NUL byte)")
        if not_utf8(inv_data):
            raise CouldNotRun("inventory.tsv is not UTF-8 text (invalid UTF-8, UTF-16 byte-order mark or NUL byte)")
        ME = _load("memory_entries", "memory-entries.py")
        ctx = {"ME": ME, "user_headings": {}, "topic_missing": topic_check(ME, repo, mem_data, inv_data)}
        out, skips = [], []
        files = [MemFile(ME, "memory/MEMORY.md", mem_data.decode("utf-8"), "root")]
        scan_order = ["memory/MEMORY.md"]
        if not opts.topics:
            extra = []
            hop = os.path.join(repo, "memory", "HIGHER_ORDER.md")
            if os.path.isfile(hop):
                extra.append(("memory/HIGHER_ORDER.md", hop, "higher"))
            tdir = os.path.join(repo, "memory", "topics")
            if os.path.isdir(tdir):
                for name in sorted(os.listdir(tdir)):
                    p = os.path.join(tdir, name)
                    if name.endswith(".md") and os.path.isfile(p):
                        extra.append(("memory/topics/" + name, p, "topic"))
            if opts.stores:
                os.environ["AGENT_PLAYBOOK_STORES"] = opts.stores
            R = _load("store_resolver", "store-resolver.py")
            root = R.store_repo_root()
            if not os.path.isdir(str(root)) or not os.path.lexists(os.path.join(str(root), ".git")):
                skips.append("SKIP\t%s\t0\tstores\tno store repo -- store memory not checked" % root)
            else:
                status, valid, _invalid, why = R.scan_stores(root)
                if status != "ok":
                    raise CouldNotRun("store scan failed: %s" % why)
                for d, _ident in valid:
                    p = os.path.join(str(d), "memory", "MEMORY.md")
                    if os.path.isfile(p):
                        extra.append((os.path.abspath(p).replace("\\", "/"), p, "store"))
            scan_order.extend(label for label, _p, _k in extra)
            for label, path, kind in extra:
                data = read_bytes(path, label)
                if not_utf8(data):
                    if "unreadable" not in disabled:
                        out.append(("FAIL", label, 0, "unreadable",
                                    "not UTF-8 text (invalid UTF-8, UTF-16 byte-order mark or NUL byte)"))
                    continue
                files.append(MemFile(ME, label, data.decode("utf-8"), kind))
        rules = [r for r in RULES if r[0] not in disabled]
        if opts.topics:
            rules = [r for r in rules if r[0] == "topic-citation"]
        # user-tier files first so a cross-file duplicate is reported on the later file, in scan order
        for mf in files:
            for name, fn in rules:
                for sev, line, detail in fn(mf, ctx):
                    out.append((sev, mf.label, line, name, detail))
        order = {label: i for i, label in enumerate(scan_order)}
        out.sort(key=lambda f: (order[f[1]], f[2]))
        lines = ["%s\t%s\t%d\t%s\t%s" % f for f in out] + skips
        nfail = sum(1 for f in out if f[0] == "FAIL")
        nwarn = sum(1 for f in out if f[0] == "WARN")
        lines.append("SUMMARY\tfail=%d\twarn=%d\tfiles=%d" % (nfail, nwarn, len(files) + sum(
            1 for f in out if f[3] == "unreadable")))
        return (1 if nfail else 0), lines, []
    except CouldNotRun as exc:
        return 2, [], ["verify-memory.py: %s" % exc]
    finally:
        if saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    _require_venv(__file__)
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    try:
        rc, out, err = run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print("verify-memory.py: guard did not run: unexpected error: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        return 2
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    return rc


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _copy_fixture(src, dst):
    """Copy a fixture tree, dropping a trailing .in from every file name (test-parity's rule)."""
    shutil.copytree(str(src), str(dst))
    for dirpath, _dirs, names in os.walk(str(dst)):
        for n in names:
            if n.endswith(".in"):
                os.replace(os.path.join(dirpath, n), os.path.join(dirpath, n[:-3]))


def _bom_crlf(src_case, dst_case):
    for rel in ("memory/MEMORY.md", "inventory.tsv"):
        with open(os.path.join(str(src_case), rel), "rb") as fh:
            data = fh.read()
        # test-parity's `printf BOM; sed 's/\r$//; s/$/\r/'`: one CR per line, a missing final newline kept
        lines = data.split(b"\n")
        tail = lines[-1] == b""
        if tail:
            lines.pop()
        body = b"\n".join((l[:-1] if l.endswith(b"\r") else l) + b"\r" for l in lines)
        out = b"\xef\xbb\xbf" + body + (b"\n" if tail else b"")
        with open(os.path.join(str(dst_case), rel), "wb") as fh:
            fh.write(out)


def topic_fixture_cases():
    """-> [(case, exit, transform, stderr-substring or None)] from fixtures/verify-memory/topics/expected.tsv."""
    rows = []
    with open(str(FIXTURES / "verify-memory" / "topics" / "expected.tsv"), "r", encoding="utf-8") as fh:
        for line in fh.read().replace("\r", "").split("\n"):
            if not line.strip() or line.startswith("#") or line.startswith("case\t"):
                continue
            case, code, transform, errsub = line.split("\t")
            rows.append((case, int(code), transform, None if errsub == "-" else errsub))
    return rows


def expected_missing(case):
    """The MISSING (topic, detail) pairs and the exit code verify-topics' expected.out records."""
    with open(str(FIXTURES / "verify-memory" / "topics" / case / "expected.out"), "r", encoding="utf-8") as fh:
        text = fh.read().replace("\r", "")
    return [tuple(l.split("\t")[1:3]) for l in text.split("\n") if l.startswith("MISSING\t")]


def prepare_topic_case(tmp, case, transform):
    dst = Path(tmp) / ("vt-" + case)
    _copy_fixture(FIXTURES / "verify-memory" / "topics" / case, dst)
    if transform == "bom-crlf":
        _bom_crlf(FIXTURES / "verify-memory" / "topics" / case, dst)
    return dst


def run_topics(repo):
    """-> (exit, [(topic, detail)], stderr text) from `--topics`."""
    rc, out, err = run([str(repo), "--topics"])
    pairs = []
    for l in out:
        f = l.split("\t")
        if f[0] == "FAIL" and f[3] == "topic-citation":
            _m, topic, detail = f[4].split(" ", 2)
            pairs.append((topic, detail))
    return rc, pairs, "\n".join(err)


# The clean fixture's mutations: (name, file, old, new, rule, severity or None for "rule absent").
# Every old string must occur exactly once in its file. Severity None: the mutated twin stays clean.
# Rules a mutation also trips by design, disabled in both of its runs (the bold-colon spelling is both a bad
# date for verified-invalid and the spelling verified-spelling warns on).
MUTATION_ALSO = {"verified in the bold-colon spelling": ("verified-spelling",)}

MUTATIONS = (
    ("dup type heading", "memory/MEMORY.md", "## Declined\n", "## Feedback\n\n## Declined\n", "dup-type-heading", "FAIL"),
    ("dup type heading in a store", "STORE", "## Declined\n", "## Pattern\n\n## Declined\n", "dup-type-heading", "FAIL"),
    ("declined missing", "memory/MEMORY.md", "## Declined\n\n", "", "declined-missing", "FAIL"),
    ("store without declined is clean", "STORE", "## Declined\n", "", "declined-missing", None),
    ("declined duplicate", "memory/MEMORY.md", "## Declined\n", "## Declined\n\n## Declined\n", "declined-duplicate", "FAIL"),
    ("### under Topics", "memory/MEMORY.md", "## Feedback\n", "### Stray heading\n\n## Feedback\n", "heading-outside-type", "FAIL"),
    ("### in a preamble", "memory/topics/alpha.md", "> Not loaded", "### Preamble heading\n\n> Not loaded", "heading-outside-type", "FAIL"),
    ("### under Declined", "memory/MEMORY.md", "- \"Fixture declined", "### Stray\n\n- \"Fixture declined", "heading-outside-type", "FAIL"),
    ("a fenced ### under Topics is clean", "memory/MEMORY.md", "## Feedback\n", "```\n### Fenced under Topics\n```\n\n## Feedback\n", "heading-outside-type", None),
    ("verified not a calendar day", "memory/MEMORY.md", "2026-02-28", "2026-02-30", "verified-invalid", "FAIL"),
    ("verified not a date", "memory/HIGHER_ORDER.md", "**Verified**: 2026-10-02", "**Verified**: soon", "verified-invalid", "FAIL"),
    ("verified in a fence is ignored", "memory/MEMORY.md", "### fenced heading is not an entry\n", "### fenced heading is not an entry\n**Verified**: 2026-99-99\n", "verified-invalid", None),
    ("second pipe on Source", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", "fixture-plan § Section | extra | **Verified**", "source-pipe", "FAIL"),
    ("a pipe inside a quoted Source span is clean", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", 'fixture-plan § Section "a | b" | **Verified**', "source-pipe", None),
    ("a pipe outside the quoted span still counts", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", 'fixture-plan "a | b" § Section | extra | **Verified**', "source-pipe", "FAIL"),
    ("heading over 200", "memory/MEMORY.md", "### Fixture feedback entry one\n", "### " + "x" * 201 + "\n", "heading-too-long", "FAIL"),
    ("conflict markers", "memory/MEMORY.md", "**Why**: the feedback reason.\n", "<<<<<<< HEAD\n**Why**: the feedback reason.\n=======\n**Why**: theirs.\n>>>>>>> 0801c3d (mine)\n", "conflict-marker", "FAIL"),
    ("conflict markers in a store", "STORE", "### Store entry two\n", "<<<<<<< HEAD\n### Store entry two\n", "conflict-marker", "FAIL"),
    ("conflict markers in a fence are clean", "memory/MEMORY.md", "**Why**: the feedback reason.\n", "**Why**: the feedback reason.\n```\n<<<<<<< HEAD\n=======\n>>>>>>> x\n```\n", "conflict-marker", None),
    ("a lone ======= heading underline is clean", "memory/MEMORY.md", "**Why**: the feedback reason.\n", "**Why**: the feedback reason.\n\nTitle\n=======\n", "conflict-marker", None),
    ("Verified spelled with the colon inside the bold", "memory/HIGHER_ORDER.md", "**Verified**: 2026-10-02", "**Verified:** 2026-10-02", "verified-spelling", "WARN"),
    ("heading of exactly 200 is clean", "memory/MEMORY.md", "### Fixture feedback entry one\n", "### " + "y" * 200 + "\n", "heading-too-long", None),
    ("heading duplicated across user-tier files", "memory/topics/alpha.md", "### Alpha entry\n", "### Fixture feedback entry one\n", "heading-duplicate", "FAIL"),
    ("heading duplicated within a store", "STORE", "### Store entry two\n", "### Store entry one\n", "heading-duplicate", "FAIL"),
    ("higher-order node sharing a base heading is clean", "memory/HIGHER_ORDER.md", "### Fixture node\n", "### Fixture feedback entry one\n", "heading-duplicate", None),
    ("topic citer loses its reference", "AGENTS.md", "memory/topics/alpha.md", "memory/topics/other.md", "topic-citation", "FAIL"),
    ("topic file not UTF-8", "memory/topics/alpha.md", "Alpha entry", "Alpha \udcff entry", "unreadable", "FAIL"),
    ("missing Why", "memory/MEMORY.md", "**Why**: the feedback reason.\n", "", "missing-field", "WARN"),
    ("missing How to apply", "memory/topics/alpha.md", "**How to apply**: the alpha action.\n", "", "missing-field", "WARN"),
    ("missing Source", "memory/HIGHER_ORDER.md", "**Source**: fixture-plan § Node | ", "", "missing-field", "WARN"),
    ("signal missing Target", "memory/topics/improvement-signals.md", "**Target**: `shared/AGENTS.md`\n", "", "signal-incomplete", "WARN"),
    ("signal missing Last observed", "memory/topics/improvement-signals.md", " | **Last observed**: 2026-10-01", "", "signal-incomplete", "WARN"),
    ("relative date in prose", "memory/MEMORY.md", "**Why**: the feedback reason.", "**Why**: the feedback reason from last week.", "relative-date", "WARN"),
    ("relative date in a heading", "memory/topics/alpha.md", "### Alpha entry\n", "### Alpha entry seen yesterday\n", "relative-date", "WARN"),
    ("relative date in a code span is clean", "memory/MEMORY.md", "**Why**: the feedback reason.", "**Why**: the feedback reason `today`.", "relative-date", None),
    # review cycle 1 (2026-10-25): sub-behaviours each rule documents
    ("verified with an actor first, on its own line", "memory/MEMORY.md", "fixture-plan § Other | **Verified**: 2026-02-28", "fixture-plan § Other\n**Verified**: human: 2026-02-28", "verified-invalid", "FAIL"),
    ("verified date runs into a digit", "memory/MEMORY.md", "2026-02-28", "2026-02-280", "verified-invalid", "FAIL"),
    ("verified in the bold-colon spelling", "memory/topics/alpha.md", "| **Verified**: 2026-10-03", "| **Verified:** 2026-13-03", "verified-invalid", "FAIL"),
    ("verified quoted in a code span is clean", "memory/MEMORY.md", "**Why**: the feedback reason.", "**Why**: write `**Source**: x | **Verified**: <YYYY-MM-DD>` after How to apply.", "verified-invalid", None),
    ("verified named mid-sentence is clean", "memory/MEMORY.md", "**How to apply**: the feedback action.", "**How to apply**: re-date **Verified**: only after a check.", "verified-invalid", None),
    ("verified inside a governance quote line is clean", "memory/MEMORY.md", "**How to apply**: the feedback action.\n", "**How to apply**: the feedback action.\n**Governance-conflict-quote**: \"a | **Verified**: <YYYY-MM-DD>\"\n", "verified-invalid", None),
    ("outcome after the Verified tail", "memory/MEMORY.md", "2026-10-01 (human:test, grep)", "2026-10-01 (human:test, grep) | **Outcome**: recurred 2026-10-02", "source-pipe", "FAIL"),
    ("outcome on its own line is clean", "memory/MEMORY.md", "2026-10-01 (human:test, grep)\n", "2026-10-01 (human:test, grep)\n**Usage**: 3 | **Outcome**: recurred 2026-10-02\n", "source-pipe", None),
    ("a pipe in a code span is clean", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", "fixture-plan § Section `a | b` | **Verified**", "source-pipe", None),
    ("a pipe in curly quotes is clean", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", "fixture-plan § Section \u201ca | b\u201d | **Verified**", "source-pipe", None),
    ("a quote cannot hide a pipe across the tail", "memory/MEMORY.md", "fixture-plan § Section | **Verified**: 2026-10-01 (human:test, grep)", "fixture-plan \"§ Section | **Verified**: 2026-10-01 | x\"", "source-pipe", "FAIL"),
    ("a second Source line is checked too", "memory/MEMORY.md", "**Source**: fixture-plan § Other | **Verified**: 2026-02-28", "**Source**: fixture-plan § Other | **Verified**: 2026-02-28\n**Source**: a | b | c", "source-pipe", "FAIL"),
    ("a lowercase type heading is not a type section", "STORE", "## Decision\n", "## decision\n", "heading-outside-type", "FAIL"),
    ("a ### after a # title is outside every section", "memory/topics/alpha.md", "**Source**: fixture-plan § Alpha | **Verified**: 2026-10-03\n", "**Source**: fixture-plan § Alpha | **Verified**: 2026-10-03\n\n# Appendix\n\n### After a title\n", "heading-outside-type", "FAIL"),
    ("heading duplicated within one user-tier file", "memory/MEMORY.md", "### Fixture pattern entry\n", "### Fixture feedback entry one\n", "heading-duplicate", "FAIL"),
    ("declined duplicated in a store", "STORE", "## Declined\n", "## Declined\n\n## Declined\n", "declined-duplicate", "FAIL"),
    ("two stores sharing a heading is clean", "STORE2", "### Store b entry\n", "### Store entry one\n", "heading-duplicate", None),
    ("a store sharing a user heading is clean", "STORE", "### Store entry two\n", "### Fixture feedback entry one\n", "heading-duplicate", None),
    ("Why in the bold-colon spelling counts", "memory/MEMORY.md", "**Why**: the feedback reason.", "**Why:** the feedback reason.", "missing-field", None),
    ("a quoted anchor holding a Verified tail is clean", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", 'fixture-plan "§ A | **Verified**: x" | **Verified**', "source-pipe", None),
    ("a quoted anchor holding a Verified tail is not a field", "memory/MEMORY.md", "fixture-plan § Section | **Verified**", 'fixture-plan "§ A | **Verified**: x" | **Verified**', "verified-invalid", None),
    ("verified in a numbered list item", "memory/MEMORY.md", "**How to apply**: the feedback action.\n", "**How to apply**: the feedback action.\n1. **Verified**: bad\n", "verified-invalid", "FAIL"),
    ("a signal naming Verified in prose is clean", "memory/topics/improvement-signals.md", " | **Last observed**: 2026-10-01", " | **Last observed**: 2026-10-01; it never carries `**Verified**:`", "signal-verified", None),
    ("signal carrying Verified", "memory/topics/improvement-signals.md", " | **Last observed**: 2026-10-01", " | **Last observed**: 2026-10-01 | **Verified**: 2026-10-01", "signal-verified", "WARN"),
)


def build_clean(tmp, name):
    """-> (repo, stores) scratch copies of fixtures/verify-memory/clean."""
    base = Path(tmp) / name
    _copy_fixture(FIXTURES / "verify-memory" / "clean", base)
    repo, stores = base / "repo", base / "stores"
    (stores / ".git").mkdir()
    return repo, stores


def store_memory(stores, name="proj-aaaaaa"):
    return stores / name / "memory" / "MEMORY.md"


def apply_mutation(repo, stores, rel, old, new):
    path = {"STORE": store_memory(stores), "STORE2": store_memory(stores, "proj-bbbbbb")}.get(rel) or repo / rel
    with open(str(path), "r", encoding="utf-8") as fh:
        text = fh.read()
    if text.count(old) != 1:
        return "old string occurs %d times in %s" % (text.count(old), rel)
    data = text.replace(old, new).encode("utf-8", "surrogateescape")
    with open(str(path), "wb") as fh:
        fh.write(data)
    return None


def findings(out):
    return [l.split("\t") for l in out if l.startswith("FAIL\t") or l.startswith("WARN\t")]


def selftest():
    fails, checks, skips = [], [0], []

    def chk(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (name, (": " + detail) if detail else ""))

    tmp = tempfile.mkdtemp(prefix="verify-memory-")
    try:
        # --- the clean fixture ---
        repo, stores = build_clean(tmp, "clean")
        rc, out, err = run([str(repo), "--stores", str(stores)])
        chk("the clean fixture is clean", rc == 0 and not findings(out)
            and out[-1] == "SUMMARY\tfail=0\twarn=0\tfiles=6", "%s %r %r" % (rc, out, err))

        # --- each rule: the mutated twin flips the verdict; the same twin with the rule disabled does not ---
        covered = set()
        for i, (name, rel, old, new, rule, sev) in enumerate(MUTATIONS):
            repo, stores = build_clean(tmp, "m%02d" % i)
            why = apply_mutation(repo, stores, rel, old, new)
            if why:
                chk("mutation '%s' applies" % name, False, why)
                continue
            argv = [str(repo), "--stores", str(stores)]
            also = MUTATION_ALSO.get(name, ())
            rc, out, err = run(argv, disabled=also)
            hits = [f for f in findings(out) if f[3] == rule]
            if sev is None:
                chk("%s: no %s finding" % (name, rule), not hits and rc == 0, "%s %r" % (rc, out))
                continue
            covered.add(rule)
            want_rc = 1 if sev == "FAIL" else 0
            chk("%s: a %s %s finding, exit %d" % (name, sev, rule, want_rc),
                len(hits) >= 1 and all(h[0] == sev for h in hits) and rc == want_rc
                and len(findings(out)) == len(hits), "%s %r %r" % (rc, out, err))
            rc2, out2, _e = run(argv, disabled=(rule,) + tuple(also))
            chk("%s: with %s disabled the twin is clean" % (name, rule),
                rc2 == 0 and not findings(out2), "%s %r" % (rc2, out2))
        for rule, _fn in RULES:
            chk("rule %s has a flipping mutation" % rule, rule in covered)

        # --- never echo entry text beyond the heading ---
        repo, stores = build_clean(tmp, "echo")
        apply_mutation(repo, stores, "memory/MEMORY.md", "**Why**: the feedback reason.",
                       "**Why**: the feedback reason SECRETWORD last week.")
        apply_mutation(repo, stores, "memory/MEMORY.md", "fixture-plan § Section | **Verified**",
                       "SECRETWORD | x | **Verified**")
        rc, out, _e = run([str(repo), "--stores", str(stores)])
        chk("no finding echoes body text", findings(out) and not any("SECRETWORD" in l for l in out), repr(out))

        # --- the 13 former verify-topics fixture cases ---
        cases = topic_fixture_cases()
        chk("expected.tsv lists 14 cases", len(cases) == 14, str(len(cases)))
        for case, want, transform, errsub in cases:
            d = prepare_topic_case(tmp, case, transform)
            rc, pairs, err = run_topics(d)
            ok = rc == want and pairs == expected_missing(case) and (errsub is None or errsub in err)
            chk("verify-topics case %s: exit %d and its MISSING rows" % (case, want), ok,
                "exit %s, %r, stderr %r" % (rc, pairs, err))

        # --- could not run: exit 2 ---
        rc, out, err = run([])
        chk("no repo argument exits 2", rc == 2 and not out and "required" in err[0], repr(err))
        rc, out, err = run([str(Path(tmp) / "no-such-repo")])
        chk("a missing repo exits 2", rc == 2 and not out, repr(err))
        rc, out, err = run(["--bogus"])
        chk("an unknown option exits 2", rc == 2, repr(err))
        repo, stores = build_clean(tmp, "nostore")
        rc, out, err = run([str(repo), "--stores", str(Path(tmp) / "no-stores")])
        chk("a missing store repo is a SKIP line, exit 0", rc == 0 and any(l.startswith("SKIP\t") for l in out)
            and out[-1] == "SUMMARY\tfail=0\twarn=0\tfiles=4", repr(out))
        repo, stores = build_clean(tmp, "store-invalid")
        (stores / "proj-cccccc").mkdir()
        with open(str(stores / "proj-cccccc" / "STORE"), "w", encoding="utf-8") as fh:
            fh.write("garbage line\n")
        os.makedirs(str(stores / "proj-cccccc" / "memory"))
        with open(str(stores / "proj-cccccc" / "memory" / "MEMORY.md"), "w", encoding="utf-8") as fh:
            fh.write("## Feedback\n\n## Feedback\n")
        rc, out, err = run([str(repo), "--stores", str(stores)])
        chk("a store with an invalid STORE file is skipped (verify-stores' finding)", rc == 0
            and not findings(out), repr(out))
        repo, stores = build_clean(tmp, "store-nogit")
        (stores / ".git").rmdir()
        rc, out, err = run([str(repo), "--stores", str(stores)])
        chk("a store repo without .git is a SKIP line, exit 0", rc == 0 and any(l.startswith("SKIP\t") for l in out)
            and out[-1] == "SUMMARY\tfail=0\twarn=0\tfiles=4", repr(out))

        # --- output order: an unreadable file keeps its scan position ---
        repo, stores = build_clean(tmp, "order")
        apply_mutation(repo, stores, "memory/topics/alpha.md", "Alpha entry", "Alpha \udcff entry")
        apply_mutation(repo, stores, "memory/MEMORY.md", "## Declined\n", "## Declined\n\n## Declined\n")
        rc, out, _e = run([str(repo), "--stores", str(stores)])
        got = [f[1] for f in findings(out)]
        chk("findings print in scan order, an unreadable file included",
            got == ["memory/MEMORY.md", "memory/topics/alpha.md"], repr(out))

        # --- accepted destinations: the instruction files and their co-existence links, never the memory rules ---
        inv_lines = ["symlink-file	~/.claude/rules/agent-playbook.md	shared/A.md	claude",
                     "symlink-file	~/.gemini/AGENT-PLAYBOOK.md	shared/B.md	gemini",
                     "symlink-file	~/.claude/rules/playbook-user-memory.md	memory/MEMORY.md	claude"]
        chk("a co-existence link is an accepted destination; a memory rules link is not",
            accepted_sources(inv_lines) == ["shared/A.md", "shared/B.md"], repr(accepted_sources(inv_lines)))

        # --- the venv guard: another interpreter exits 2 before anything runs ---
        other_py = getattr(sys, "_base_executable", None)
        if other_py and os.path.normcase(os.path.realpath(other_py)) != os.path.normcase(os.path.realpath(sys.executable)):
            r = subprocess.run([other_py, "-I", "-B", os.path.realpath(__file__), str(repo)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            chk("another interpreter exits 2 with the venv message", r.returncode == 2
                and b"guard did not run: venv missing" in r.stderr, "%s %r" % (r.returncode, r.stderr[:200]))
        else:
            skips.append("venv guard: no interpreter outside the venv to try")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for s in skips:
        print("SKIP: %s" % s)
    for f in fails:
        print("FAIL: %s" % f)
    print("verify-memory selftest: %d failure(s), %d check(s), %d skipped" % (len(fails), checks[0], len(skips)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
