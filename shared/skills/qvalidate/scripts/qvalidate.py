#!/usr/bin/env python3
"""qvalidate.py -- deterministic validator for the agent-playbook plan-file
format. Runs the full applicable suite of named checks against one project file
and reports each as a tab-separated CHECK line, followed by a SUMMARY line.

The checks (names are the cross-file citation vocabulary -- never
numbered): filename-grammar, status-grammar, completeness, phase-count,
parallel-symmetry, sc-coverage, harness-section, acceptance-evidence,
commit-pairing, doc-updates. Semantics are single-sourced
in shared/skills/qvalidate/SKILL.md. On FAIL, callers halt and present the
violation verbatim (SKILL.md "## Failure semantics" owns that rule).

Port of qvalidate.sh (plan 261016 Phase 14): same CLI, checks, TSV bytes (LF),
SUMMARY line and exit codes, except two decided changes (user, 2026-10-26).
A [P:N] tag carrying extra text (### Phase 1: X [P:3 note]) makes
parallel-symmetry FAIL with a detail naming the malformed annotation and its
phase, and every other check still runs. doc-updates runs git with
-c core.quotepath=off, so a non-ASCII file name in the diff is matched.
Review fixes of the same phase: a failing git command whose output a check
needs, a bad --doc-updates-since ref and a missing git binary exit 2 (the .sh
read them as "no commits" or "not inside a git repository"); a shallow history
makes commit-pairing WARN that it could not run; one trailing CR is dropped
from each plan line, so a CRLF plan reads as an LF one. Runs
only under the playbook venv (<config repo>/.venv-agent-playbook); any other
interpreter exits 2 ("guard did not run: venv missing"). Stdlib only, Python
3.8+.

Usage:
  qvalidate.py [--project-root <dir>] [--plan-root <dir>]
               [--phase N --expect-ticked K]
               [--check-commits] [--base <ref>] [--help] <plan-path>
  qvalidate.py --selftest

Flags:
  --project-root <dir>   CODE root: run git operations relative to <dir>,
                         making the script cwd-independent. It no longer
                         resolves <plan-path> -- see --plan-root. (The same
                         flag name in close-plan.py means something
                         different, "where plans/ lives"; that divergence is
                         pre-existing and deliberate.)
  --plan-root <dir>      PLAN root: resolve a relative <plan-path> against
                         <dir>. Defaults to the directory holding the
                         resolved plan, so the plan root is derived AFTER
                         <plan-path> resolution, never before it. When
                         --project-root is absent the code root IS the plan
                         root (the standalone /qvalidate <plan-path> case).
  --phase N              Enable the phase-count check for Phase N (N may carry
                         a single trailing letter for a split sub-phase, e.g.
                         8b). Requires --expect-ticked.
  --expect-ticked K      Expected count of ticked (- [x]) boxes in Phase N's
                         block, or the literal 'auto' to report the count
                         without comparing (no mismatch possible). Requires
                         --phase.
  --check-commits        Enable the git-history scans: BOTH commit-pairing
                         and doc-updates. Neither fires without it.
  --base <ref>           Base ref for commit-pairing, used only when neither
                         origin/HEAD nor a local main/master can be derived.
                         It serves the CODE root ONLY: in the cross-repo
                         (workspace store) case the plan root derives its own
                         base and this flag does not reach it.
  --doc-updates-since <ref>  Optional. Scopes doc-updates' change-detection to
                         <ref>..HEAD instead of the full <base>..HEAD range --
                         use when the plan shares a long-lived branch with a
                         predecessor's own commits (pass the commit before
                         this plan's own first commit). Absent, doc-updates
                         behavior is unchanged.
  --help, -h             Print this header and exit 0.
  --selftest             Run the fixture selftest (fixtures/ next to this
                         script) and exit 1 on any failure.

Output (stdout):
  CHECK<TAB><name><TAB><PASS|WARN|FAIL><TAB><detail>   (one per fired check)
  SUMMARY<TAB>pass=N warn=N fail=N                     (final line)

Exit codes:
  0   No FAIL among the fired checks.
  1   One or more checks FAILed.
  2   Precondition failure: bad/missing path, non-project file (basename does not
      match ^[0-9]{6}_[A-Z0-9_]+\\.md$), a plans/done/ file, or a malformed
      flag combination. Also "guard did not run": the venv is missing, git is
      not found (with --check-commits), a git command whose output a check
      needs failed ("git <subcommand> failed: <stderr tail>"), the
      --doc-updates-since ref names no commit, or an unexpected error stopped
      the run (CHECK lines already printed are kept, and no SUMMARY line
      follows).

Applicability guard: a file whose basename does not match
^[0-9]{6}_[A-Z0-9_]+\\.md$, or that lives under plans/done/, is rejected with
exit 2 (not a validatable active plan).

Cross-repo note: when the plan lives in a workspace store inside the config
repo (shared/skills/qdream/memory-rules.md "Workspace Store") the plan root
and the code root are DIFFERENT repositories. commit-pairing then reads code
commits from the code root and docs commits from the plan root. Sameness is
decided by `git rev-parse --path-format=absolute --git-common-dir` equality,
which needs git >= 2.31; on older git the script falls back to
--show-toplevel and prints one WARN line on stderr. doc-updates deliberately
stays on the CODE root, so a Documentation Updates row naming a store-side
file will not be seen -- a documented, tested limitation.

Commit-convention note: commit-pairing's subject tests are anchored on the
playbook's <type>(<slug>) grammar, which shared/AGENTS.md "Commit Conventions"
(Scope and priority) makes a DEFAULT that a project's own stated convention
outranks. The check therefore reads the plan file's own history first: when
commits touch the plan file and none use that grammar, it WARNs and skips
instead of reporting a vacuous PASS or a spurious FAIL. Full rationale and the
one residual gap: the block comment at the check itself.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

NAME = "qvalidate.py"
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

# --- status-grammar severity default (single knob) ------------------------
# Severity emitted for a status-grammar violation. Phase 1 shipped WARN so a new
# validator never hard-halted legitimate work on legacy plans; Phase 2 normalized
# the active plans and flipped this default to FAIL (SC-3). The severity lives
# here as a single knob -- do not scatter it elsewhere.
STATUS_GRAMMAR_SEVERITY = "FAIL"

# grep/awk's [[:space:]] in the C locale. Every pattern is compiled with re.ASCII so \b and the
# classes below never take Python's Unicode meaning, which grep does not have. One exception:
# RE_AE_NEGATION (acceptance-evidence) uses Unicode \s and \b, so a no-break space cannot hide a negation.
WS = r"[ \t\n\r\f\v]"
A = re.ASCII
RE_PLAN_NAME = re.compile(r"[0-9]{6}_[A-Z0-9_]+\.md", A)
RE_DONE = re.compile(r"[\\/]plans[\\/]done[\\/]", A)
RE_STATUS_PREFIX = re.compile(r"> \*\*Status\*\*:", A)
RE_STATUS = re.compile("^> \\*\\*Status\\*\\*: (Exploring|Draft|In Progress|Complete)( — .+)?( *<!--.*-->)? *$")
RE_UNTICKED = re.compile("^" + WS + r"*- \[ \]", A)
RE_TICKED = re.compile("^" + WS + r"*- \[x\]", A)
RE_PHASE_HEADING = re.compile(r"^### Phase ([0-9]+):", A)
RE_P_ANY = re.compile(r"\[P:[0-9]", A)
RE_P_WELL = re.compile(r"\[P:([0-9,]+)\]", A)
RE_P_SHOWN = re.compile(r"\[P:[0-9][^\]]*\]?", A)
RE_SC_HEADING_END = re.compile(r"^#{2,3} ", A)
RE_SC = re.compile(r"SC-[0-9]+", A)
RE_SC_UNHYPHENATED = re.compile(r"\bSC[0-9]+\b", A)
RE_COVERS = re.compile(r"^\*\*Covers\*\*:", A)
RE_PHASE_WORD = re.compile(r"phase ([0-9]+)", A | re.I)
RE_DOC_HEADING = re.compile(r"^## .*Documentation Updates", A)
RE_DOC_END = re.compile(r"^### (Out of scope|Zero-hit)", A)
RE_SEPARATOR_ROW = re.compile("^\\|" + "[ \t\n\r\f\v-]*" + "\\|", A)
RE_HEADER_ROW = re.compile("^\\|" + WS + "*Document" + WS + "*\\|", A | re.I)
RE_BACKTICK = re.compile(r"`([^`]+)`", A)
RE_BARE_PATH = re.compile(r"[A-Za-z0-9._/-]+\.[A-Za-z0-9]+", A)
RE_WS_TAIL = re.compile(WS + ".*$", A | re.S)
RE_LINE_ANCHOR = re.compile(r":[0-9]+(-[0-9]+)?(,[0-9]+(-[0-9]+)?)*$", A)
RE_ABS_ARG = re.compile(r"(/|[A-Za-z]:/|[A-Za-z]:\\)", A)
RE_REPO_ID_SHAPE = re.compile(r"(/|[A-Za-z]:)", A)
WINDOW_DESC = "plan-scoped window (git log -n 400 --grep=<slug>)"
CODE_TYPES = ("feat", "fix", "refactor", "test", "chore", "ci")


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


class Usage(Exception):
    """A precondition failure: exit 2 after printing each message line as `qvalidate.py: <line>`."""


def _cap(text):
    """bash $(...): the output with every trailing newline removed."""
    return text.rstrip("\n")


class GuardStop(Exception):
    """The run cannot produce a trustworthy verdict: exit 2 with `guard did not run: <message>`, keeping
    the CHECK lines already printed and printing no SUMMARY."""


def _git(root, *args, **kw):
    """-> (exit code, stdout text, stderr text). A probe reads the exit code; a call whose output a check
    needs goes through _git_must. A missing git binary stops the run (GuardStop): no call site can
    stand in for it, and reading it as "not inside a git repository" would hide it."""
    pre = list(kw.get("pre", ()))
    try:
        r = subprocess.run(["git"] + pre + ["-C", root] + list(args), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise GuardStop("git not found")
    except OSError as exc:
        raise GuardStop("git could not start: %s" % exc)
    return r.returncode, r.stdout.decode("utf-8", "surrogateescape"), r.stderr.decode("utf-8", "surrogateescape")


def _git_fail(args, err):
    tail = [l.strip() for l in err.replace("\r", "\n").split("\n") if l.strip()]
    return GuardStop("git %s failed: %s" % (args[0], tail[-1][:300] if tail else "no message"))


def _git_must(root, *args, **kw):
    """-> stdout text of a git call whose output a check needs; a non-zero exit stops the run (GuardStop),
    where the .sh's `|| true` read a failing `git log` as "no commits"."""
    rc, out, err = _git(root, *args, **kw)
    if rc != 0:
        raise _git_fail(args, err)
    return out


def _lines(text):
    """Lines as grep/awk read them: split on LF only, a final LF ends the last line. One trailing CR is
    dropped from each line, so a CRLF plan matches as an LF one and no CHECK detail carries a CR."""
    out = text.split("\n")
    if out and out[-1] == "":
        out.pop()
    return [l[:-1] if l.endswith("\r") else l for l in out]


def _grep_f(needle, hay):
    """`printf '%s' "$hay" | grep -qF "$needle"`: a fixed-string match on any line; empty input never matches."""
    return hay != "" and needle in hay


def _doc_target_hit(target, changed):
    """True when the Documentation Updates path `target` names a file in `changed` (the commits' paths): the
    path, without a trailing annotation or a line anchor, equals a changed path or its trailing path segments
    (`qclose/SKILL.md` matches `shared/skills/qclose/SKILL.md`, never `shared/skills/qdev/SKILL.md`, and
    `done.md` never matches `notdone.md`). A brace set matches on any of its expansions."""
    clean = RE_WS_TAIL.sub("", target, count=1)
    clean = RE_LINE_ANCHOR.sub("", clean, count=1)
    if clean.startswith("./"):
        clean = clean[2:]
    alts = [clean]
    lb = clean.find("{")
    if lb >= 0 and clean.find("}", lb + 1) >= 0:
        head, rest = clean.split("{", 1)
        mid, tail = rest.split("}", 1)
        alts = [head + alt + tail for alt in _ifs_comma_words(mid)]
    paths = [c for c in changed.split("\n") if c]
    return any(c == a or c.endswith("/" + a) for a in alts for c in paths)


def _strip_one_space(s):
    """bash ${X% }: drop one trailing space."""
    return s[:-1] if s.endswith(" ") else s


def _ifs_comma_words(s):
    """bash `IFS=','; for ALT in $s`: comma fields, a trailing comma adds no empty field, '' gives none."""
    if s == "":
        return []
    parts = s.split(",")
    if parts[-1] == "":
        parts.pop()
    return parts


def parse_args(argv):
    """-> options dict, or 'help' / 'selftest'. Raises Usage. Mirrors the .sh loop exactly: a value flag
    consumes the next argument whatever it is, and a flag is reported where it occurs."""
    o = {"project_root": "", "plan_root": "", "phase": "", "expect": "", "check_commits": False,
         "base": "", "since": "", "plan": ""}
    keys = {"--project-root": "project_root", "--plan-root": "plan_root", "--phase": "phase",
            "--expect-ticked": "expect", "--base": "base", "--doc-updates-since": "since"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            return "help"
        if a == "--selftest":
            return "selftest"
        if a in keys:
            if i + 1 >= len(argv):
                raise Usage("%s requires an argument" % a)
            o[keys[a]] = argv[i + 1]
            i += 2
            continue
        if a == "--check-commits":
            o["check_commits"] = True
        elif a.startswith("--"):
            raise Usage("unknown flag: %s" % a)
        else:
            if o["plan"] != "":
                raise Usage("unexpected positional argument: %s (plan already set to %s)" % (a, o["plan"]))
            o["plan"] = a
        i += 1
    if o["plan"] == "":
        raise Usage("a plan path is required",
                    "usage: qvalidate.py [--project-root <dir>] [--plan-root <dir>] [--phase N --expect-ticked K|auto] [--check-commits] [--base <ref>] [--doc-updates-since <ref>] <plan-path>")
    if (o["phase"] != "") != (o["expect"] != ""):
        raise Usage("--phase and --expect-ticked must be given together")
    if o["phase"] != "" and not re.fullmatch(r"[0-9]+[A-Za-z]?", o["phase"], A):
        raise Usage("--phase must be a positive integer, optionally with a single trailing letter for a split sub-phase (e.g. 8 or 8b): %s" % o["phase"])
    if o["expect"] not in ("", "auto") and not re.fullmatch(r"[0-9]+", o["expect"], A):
        raise Usage("--expect-ticked must be a non-negative integer, or the literal 'auto' to report the count without comparing: %s" % o["expect"])
    return o


def resolve_paths(o):
    """-> (plan_abs, plan_basename, plan_root, code_root). Raises Usage. The .sh's resolution ORDER: join a
    relative <plan-path> onto --plan-root when given, else leave it relative to the cwd; only then derive
    the --plan-root default from the resolved plan path."""
    project_root = o["project_root"]
    if project_root != "":
        if not os.path.isdir(project_root):
            raise Usage("--project-root directory does not exist: %s" % project_root)
        project_root = os.path.abspath(project_root)
    plan_root_arg = o["plan_root"]
    if plan_root_arg != "":
        if not os.path.isdir(plan_root_arg):
            raise Usage("--plan-root directory does not exist: %s" % plan_root_arg)
        plan_root_arg = os.path.abspath(plan_root_arg)
        plan_abs = o["plan"] if RE_ABS_ARG.match(o["plan"]) else os.path.join(plan_root_arg, o["plan"])
    else:
        plan_abs = o["plan"]
    if not os.path.isfile(plan_abs):
        raise Usage("project file not found: %s" % o["plan"],
                    "(a relative plan path resolves against $PWD; --project-root is the CODE root and no longer resolves it -- pass --plan-root <dir> or an absolute plan path)")
    plan_abs = os.path.abspath(plan_abs)
    base = os.path.basename(plan_abs)
    if not RE_PLAN_NAME.fullmatch(base):
        raise Usage("not a project file (basename must match ^[0-9]{6}_[A-Z0-9_]+\\.md$): %s" % base)
    if RE_DONE.search(plan_abs):
        raise Usage("archived plans under plans/done/ are not validated: %s" % plan_abs)
    plan_root = plan_root_arg if plan_root_arg != "" else os.path.dirname(plan_abs)
    code_root = project_root if project_root != "" else plan_root
    return plan_abs, base, plan_root, code_root


def read_plan(path):
    """-> the plan's lines. utf-8-sig (a leading BOM is dropped); undecodable bytes pass through unchanged."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return _lines(data.decode("utf-8", "surrogateescape"))


class Run(object):
    """One validation: the counters, the output streams and the once-only repo-id warning."""

    def __init__(self, out, err):
        self.out, self.err = out, err
        self.n = {"PASS": 0, "WARN": 0, "FAIL": 0}
        self.repo_id_warned = False

    def emit(self, name, status, detail):
        # Written and flushed at once: an unexpected error later keeps every line printed so far.
        self.out.write(("CHECK\t%s\t%s\t%s\n" % (name, status, detail)).encode("utf-8", "surrogateescape"))
        self.out.flush()
        if status in self.n:
            self.n[status] += 1

    def warn_stderr(self, text):
        self.err.write((text + "\n").encode("utf-8", "surrogateescape"))
        self.err.flush()


# --- Status line (shared by status-grammar and completeness) --------------

def status_line_and_state(lines):
    line = ""
    for l in lines:
        if RE_STATUS_PREFIX.match(l):
            line = l
            break
    state = ""
    if line != "":
        content = re.sub(r"^> \*\*Status\*\*: ", "", line, count=1, flags=A)
        # awk '{print $1}': blanks are space and tab; leading blanks are skipped
        words = [w for w in re.split(r"[ \t]+", content) if w != ""]
        state = words[0] if words else ""
    return line, state


def check_status_grammar(r, status_line):
    # Anchored full-form grammar; tolerates an optional trailing HTML comment (the template lifecycle
    # comment every current plan carries). The separator is U+2014.
    if status_line == "":
        r.emit("status-grammar", STATUS_GRAMMAR_SEVERITY, "no '> **Status**:' line found (nonconforming)")
    elif RE_STATUS.search(status_line):
        r.emit("status-grammar", "PASS", "conforms: %s" % status_line)
    else:
        r.emit("status-grammar", STATUS_GRAMMAR_SEVERITY, "nonconforming status line: %s" % status_line)


def check_completeness(r, lines, state):
    # Fires only when parsed State is Complete. Then every '- [ ]' (including '(deferred from Phase N)'
    # entries) must be ticked. Checkbox lines inside a fenced code block (``` or ~~~) are skipped.
    if state == "Complete":
        fence, unticked = False, 0
        for l in lines:
            if l.startswith("```") or l.startswith("~~~"):
                fence = not fence
                continue
            if not fence and RE_UNTICKED.match(l):
                unticked += 1
        if unticked > 0:
            r.emit("completeness", "FAIL", "State is Complete but %d unticked checkbox(es) remain (deferrals included)" % unticked)
        else:
            r.emit("completeness", "PASS", "State is Complete and all checkboxes are ticked")
    else:
        # ASCII hyphen, deliberately: keep machine-compared output ASCII-only.
        r.emit("completeness", "PASS", "not applicable - State not Complete")


def check_phase_count(r, lines, phase, expect):
    # Counts '- [x]' in Phase N's block. The block ends at the FIRST of the next '### Phase ' heading OR
    # the next '## ' heading that is NOT inside a fenced code block; the fence toggle is evaluated before
    # the boundary test. Every matching heading (re)starts a block, as the .sh's awk does.
    head = "### Phase %s:" % phase
    found, inblock, fence, ticked = False, False, False, 0
    for l in lines:
        if l.startswith(head):
            found, inblock, fence = True, True, False
            continue
        if inblock:
            if l.startswith("```") or l.startswith("~~~"):
                fence = not fence
                continue
            if not fence and (l.startswith("### Phase ") or l.startswith("## ")):
                inblock = False
                continue
            if not fence and RE_TICKED.match(l):
                ticked += 1
    if not found:
        r.emit("phase-count", "FAIL", "Phase %s heading (### Phase %s:) not found" % (phase, phase))
    elif expect == "auto":
        r.emit("phase-count", "PASS", "Phase %s has %d ticked box(es) (auto -- reported, not compared)" % (phase, ticked))
    elif ticked == int(expect):
        r.emit("phase-count", "PASS", "Phase %s has %d ticked box(es), expected %s" % (phase, ticked, expect))
    else:
        r.emit("phase-count", "FAIL", "Phase %s has %d ticked box(es), expected %s" % (phase, ticked, expect))


def check_parallel_symmetry(r, lines):
    # Every [P:N] group member must annotate all partners symmetrically. Only phase headings carry the
    # annotation. Decided change 5: a heading whose only [P: tag is not [P:<digits and commas>] is a
    # malformed annotation and FAILs here (the .sh aborted with no SUMMARY line).
    partners, exists, malformed, has_parallel = {}, {}, [], False
    for hl in lines:
        m = RE_PHASE_HEADING.match(hl)
        if not m:
            continue
        pn = m.group(1)
        exists[pn] = True
        if RE_P_ANY.search(hl):
            has_parallel = True
            w = RE_P_WELL.search(hl)
            if w:
                partners[pn] = w.group(1)
            else:
                malformed.append((pn, RE_P_SHOWN.search(hl).group(0)))
    if not has_parallel:
        r.emit("parallel-symmetry", "PASS", "no [P:N] parallel-group annotations declared")
        return
    asym = ""
    for pn in sorted(partners, key=lambda k: (int(k), k)):
        for mm in partners[pn].split(","):
            if mm == "":
                continue
            if mm not in exists:
                asym += "Phase %s declares [P:%s] but Phase %s does not exist; " % (pn, mm, mm)
                continue
            if ",%s," % pn not in ",%s," % partners.get(mm, ""):
                asym += "Phase %s lists %s but Phase %s does not list %s; " % (pn, mm, mm, pn)
    parts = []
    if malformed:
        parts.append("malformed [P:N] annotation (expected [P:N] or [P:N,M]): " + "; ".join(
            "Phase %s has '%s'" % pm for pm in malformed))
    if asym:
        parts.append("asymmetric parallel annotation: " + _strip_one_space(asym))
    if parts:
        r.emit("parallel-symmetry", "FAIL", " -- ".join(parts))
    else:
        r.emit("parallel-symmetry", "PASS", "all [P:N] parallel groups are symmetric")


def check_sc_coverage(r, lines):
    # Fires only when the Intent's Success criteria carry SC-n IDs. Every SC-n must be referenced by >=1
    # phase '**Covers**:' line. IDs present but zero Covers lines anywhere -> WARN. An orphan -> FAIL.
    block, inblock = [], False
    for l in lines:
        if l.startswith("### Success criteria"):
            inblock = True
            continue
        if inblock and RE_SC_HEADING_END.match(l):
            inblock = False
        if inblock:
            block.append(l)
    defined = sorted(set(m for l in block for m in RE_SC.findall(l)))
    # Unhyphenated SC<n> tokens (e.g. "SC1") are a silent no-op against the SC-[0-9]+ matcher.
    unhyphenated = sorted(set(m for l in block for m in RE_SC_UNHYPHENATED.findall(l)))
    if unhyphenated:
        r.emit("sc-coverage", "WARN", "unhyphenated SC<n> token(s) found (e.g. SC1, not SC-1) -- sc-coverage's SC-[0-9]+ matcher will silently ignore them: %s" % " ".join(unhyphenated))
    if not defined:
        return
    covers = [l for l in lines if RE_COVERS.match(l)]
    if not covers:
        r.emit("sc-coverage", "WARN", "SC-n IDs present but no '**Covers**:' lines found (adoption nudge)")
        return
    referenced = set(m for l in covers for m in RE_SC.findall(l))
    orphans = [sc for sc in defined if sc not in referenced]
    if not orphans:
        r.emit("sc-coverage", "PASS", "all %d SC ID(s) referenced by a phase '**Covers**:' line" % len(defined))
    else:
        r.emit("sc-coverage", "FAIL", "SC ID(s) not covered by any phase '**Covers**:' line: %s" % " ".join(orphans))


AE_TOKEN = "User: accepted"
RE_AE_DECISION_COL = re.compile(r"\buser\s+(decision|answer|reply|turn|quote)", re.I)
RE_AE_ROW = re.compile(r"^[ \t]*\|", A)
# A backtick code span, applied to one cell at a time (the row is split first, as GFM tables do, so a span
# never crosses a cell boundary): a run of N backticks closed by a run of exactly N.
RE_AE_CODE = re.compile(r"(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)", A)
RE_AE_CELL_SPLIT = re.compile(r"(?<!\\)\|", A)
RE_AE_QUOTE = re.compile("\"[^\"]+\"|“[^”]+”", A)
RE_AE_QUOTE_FIRST = re.compile("^" + WS + "*(\"[^\"]+\"|“[^”]+”)", A)
RE_AE_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b", A)
RE_AE_REF = re.compile(r"\buser (turn|answer|decision)\b|\bsame (user )?turn\b|\bdecision [A-Za-z]*-?\d+[A-Za-z]?\b",
                       A | re.I)
# A reference right after one of these words is a negation, not evidence ("pending user decision"). The
# gap is Unicode whitespace (no re.ASCII), so a no-break space does not hide the negation.
RE_AE_NEGATION = re.compile(r"\b(pending|awaiting|no|without)\s+$", re.I)
# A ticked user-acceptance exit criterion is a hit too: the agent must not tick it without the user's turn.
RE_AE_BOX = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[[xX]\][ \t]+User acceptance:", A | re.I)


def _ae_has_marker(segment):
    if RE_AE_QUOTE.search(segment) or RE_AE_DATE.search(segment):
        return True
    return any(not RE_AE_NEGATION.search(segment[:m.start()]) for m in RE_AE_REF.finditer(segment))


def check_acceptance_evidence(r, lines):
    # Every `User: accepted` in a table row must carry evidence of the user turn it records: a marker in
    # its own segment (the text up to the next hit in the cell, or the cell's end), or another cell of the
    # row that begins with a quote (a decisions table's user-decision column). A ticked `User acceptance:`
    # list item is a hit too, its segment the rest of the line. Fenced lines (``` or ~~~ at column 0; an
    # indented fence is a known limit) and backtick code spans are skipped; other prose is never read.
    # No line when the plan has no hit. Severity is always FAIL.
    # A quote-first cell counts only in a column whose header (the first row of the table) names the
    # user, as a decisions table's "User decision" column does: a Finding cell, or a design table's
    # "Decision" column, that happens to open with a quoted phrase is never evidence.
    fence, hits, bare, missing = False, 0, 0, []
    header, prev_row = [], False
    for i, l in enumerate(lines):
        if l.startswith("```") or l.startswith("~~~"):
            fence = not fence
            prev_row = False
            continue
        box = None if fence else RE_AE_BOX.match(l)
        if box:
            prev_row = False
            hits += 1
            if not _ae_has_marker(RE_AE_CODE.sub(" ", l[box.end():])):
                bare += 1
                missing.append(i + 1)
            continue
        if fence or not RE_AE_ROW.match(l):
            prev_row = False
            continue
        cells = [RE_AE_CODE.sub(" ", c) for c in RE_AE_CELL_SPLIT.split(l)]
        if not prev_row:
            header = [c.casefold() for c in cells]
        prev_row = True
        for ci, cell in enumerate(cells):
            if AE_TOKEN not in cell:
                continue
            quote_cell = any(RE_AE_QUOTE_FIRST.match(c) for cj, c in enumerate(cells)
                             if cj != ci and cj < len(header) and RE_AE_DECISION_COL.search(header[cj]))
            for segment in cell.split(AE_TOKEN)[1:]:
                hits += 1
                if not quote_cell and not _ae_has_marker(segment):
                    bare += 1
                    if not missing or missing[-1] != i + 1:
                        missing.append(i + 1)
    if hits == 0:
        return
    if bare == 0:
        r.emit("acceptance-evidence", "PASS", "%d acceptance hit(s) carry evidence" % hits)
    else:
        r.emit("acceptance-evidence", "FAIL", "%d of %d acceptance hit(s) without evidence at line(s) %s"
               % (bare, hits, ", ".join(str(n) for n in missing)))


def check_harness(r, lines):
    # WARN, never FAIL: an absent section is not a defect, an UNREPORTED absent section is.
    # Case-sensitive, as the .sh (decided change 4 keeps it).
    if any(l.startswith("## Harness Improvement Opportunities") for l in lines):
        r.emit("harness-section", "PASS", "'## Harness Improvement Opportunities' present")
    else:
        r.emit("harness-section", "WARN", "no '## Harness Improvement Opportunities' section -- /qclose Pass 2 and /qdream GAT-PLANS will harvest nothing; absent is not the same as no-friction")


# --- Git root resolution (shared by commit-pairing and doc-updates) -------

def repo_id(r, d):
    """An identity for the repository containing d, '' outside one. --path-format=absolute --git-common-dir
    is right for both a repo-vs-subdirectory pair and two linked worktrees; it needs git >= 2.31, and older
    git echoes the unknown flag and exits 0, so the gate is the SHAPE of the result, never emptiness."""
    # Both calls are probes: a failure means "no identity" (d is outside a repository), as in the .sh.
    out = _git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")[1]
    rid = _cap(out)
    if RE_REPO_ID_SHAPE.match(rid):
        return rid
    out = _git(d, "rev-parse", "--show-toplevel")[1]
    rid = _cap(out)
    if rid != "" and not r.repo_id_warned:
        r.repo_id_warned = True
        r.warn_stderr("qvalidate: WARN: git lacks 'rev-parse --path-format' (needs git >= 2.31); fell back to --show-toplevel for the same-repo test, which cannot tell two linked worktrees of one repository apart")
    return rid


def derive_base(root, fallback):
    """-> (base, use_window): origin/HEAD -> local main -> master -> fallback; the window when no base is
    derived, it does not resolve, it is HEAD, or HEAD is on the base branch itself (a plan committed straight
    onto main: origin/main..HEAD would hold only the commits not pushed yet, so every pushed one would read as
    absent). Every call here is a probe whose failure is an answer."""
    base = ""
    rc, out, _err = _git(root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if rc == 0:
        base = _cap(out)
        if base.startswith("refs/remotes/"):
            base = base[len("refs/remotes/"):]
    elif _git(root, "show-ref", "--verify", "--quiet", "refs/heads/main")[0] == 0:
        base = "main"
    elif _git(root, "show-ref", "--verify", "--quiet", "refs/heads/master")[0] == 0:
        base = "master"
    elif fallback != "":
        base = fallback
    if base == "":
        return base, True
    base_sha = _cap(_git(root, "rev-parse", "--verify", base)[1])
    head_sha = _cap(_git(root, "rev-parse", "--verify", "HEAD")[1])
    branch = _cap(_git(root, "symbolic-ref", "--short", "-q", "HEAD")[1])
    # A detached HEAD (no branch) reads the window too: base..HEAD would miss what was already pushed.
    on_base = branch == "" or branch in (base, base.split("/", 1)[-1])
    return base, (base_sha == "" or base_sha == head_sha or on_base)


def _probe_true(root, *args):
    """A yes/no probe: true only when git prints exactly 'true' (an older git echoes an unknown flag)."""
    return _cap(_git(root, *args)[1]) == "true"


class GitContext(object):
    def __init__(self, r, code_root, plan_root, base_ref):
        # Probes: a failing `rev-parse --git-dir` IS the answer "not inside a git repository".
        self.code_in = _git(code_root, "rev-parse", "--git-dir")[0] == 0
        if code_root == plan_root:
            self.plan_in = self.code_in
        else:
            self.plan_in = _git(plan_root, "rev-parse", "--git-dir")[0] == 0
        # An unborn HEAD (no commit yet) has no history to read: the logs below are skipped, so it still
        # reads as "no commits" as in the .sh, while a repository whose HEAD resolves but whose `git log`
        # fails (a corrupt object store) stops the run.
        self.unborn = {}
        self.shallow = []
        if code_root == plan_root:
            roots = [("repository", code_root, self.code_in)]
        else:
            roots = [("code root", code_root, self.code_in), ("plan root", plan_root, self.plan_in)]
        for name, root, inside in roots:
            if inside:
                self.unborn[root] = _git(root, "rev-parse", "-q", "--verify", "HEAD")[0] != 0
                if _probe_true(root, "rev-parse", "--is-shallow-repository"):
                    self.shallow.append("%s (%s)" % (name, root))
        # Sameness is decided on repository IDENTITY, not path equality.
        self.split = False
        self.id_code = self.id_plan = ""
        if self.code_in and self.plan_in and code_root != plan_root:
            self.id_code = repo_id(r, code_root)
            self.id_plan = repo_id(r, plan_root)
            self.split = self.id_code != self.id_plan
        self.base_code, self.window_code, self.desc_code = "", True, ""
        if self.code_in:
            self.base_code, self.window_code = derive_base(code_root, base_ref)
            self.desc_code = WINDOW_DESC if self.window_code else "%s..HEAD" % self.base_code
        if self.split:
            self.base_plan, self.window_plan = derive_base(plan_root, "")
            self.desc_plan = WINDOW_DESC if self.window_plan else "%s..HEAD" % self.base_plan
        else:
            self.base_plan, self.window_plan, self.desc_plan = self.base_code, self.window_code, self.desc_code


def _log(g, root, *args, **kw):
    """`git log ...` whose output a check needs: '' on an unborn HEAD, else _git_must."""
    if g.unborn.get(root, False):
        return ""
    return _git_must(root, "log", *args, **kw)


def _subjects(g, root, window, base, slug):
    if window:
        return _cap(_log(g, root, "-n", "400", "-F", "--grep=" + slug, "--format=%s"))
    return _cap(_log(g, root, "%s..HEAD" % base, "--format=%s"))


def _phase_of(subj):
    m = RE_PHASE_WORD.search(subj)
    return m.group(1) if m else ""


def check_commit_pairing(r, g, slug, plan_abs, plan_root, code_root):
    # A code commit -- <type>(<slug>): ...phase N, <type> one of feat|fix|refactor|test|chore|ci -- with no
    # paired docs(<slug>): ...phase N commit is a FAIL. Cross-repo: code commits from the CODE root, docs
    # commits from the PLAN root and from the plan's earlier homes (the code root and the config repo).
    # Convention discriminator: the plan file's own history decides whether this repository writes
    # plan-bookkeeping commits in the <type>(<slug>) grammar; commits that certify nothing -> WARN, skip.
    # Residual, deliberately NOT covered: foreign code commits paired with playbook-grammar plan commits.
    # A shallow history cannot be scanned: the plan file's commits and the pairing window are both cut
    # off, so the grammar test and the pairing verdict would read a truncated log (a misleading grammar
    # WARN, a spurious FAIL or a vacuous PASS). Could-not-run, so WARN and skip (a CI shallow clone is a
    # known environment; the other checks still run).
    plan_file_n, grammar_seen = 0, False
    if g.code_in and g.plan_in and not g.shallow:
        # The .sh treats a failure here as "no evidence" by design, for a plan file outside the plan
        # root's repository; only that case is still tolerated, any other git failure stops the run.
        if g.unborn.get(plan_root, False):
            subjects = ""
        else:
            rc, subjects, err = _git(plan_root, "log", "-n", "400", "--format=%s", "--", plan_abs)
            if rc != 0:
                if repo_id(r, os.path.dirname(plan_abs)) == repo_id(r, plan_root):
                    raise _git_fail(("log",), err)
                subjects = ""
            subjects = _cap(subjects)
        for subj in subjects.split("\n"):
            if subj == "":
                continue
            plan_file_n += 1
            if any(subj.startswith("%s(%s):" % (t, slug)) for t in ("docs",) + CODE_TYPES):
                grammar_seen = True
    if not g.code_in and not g.plan_in:
        r.emit("commit-pairing", "WARN", "not inside a git repository -- commit-pairing skipped")
        return
    if not g.code_in:
        r.emit("commit-pairing", "WARN", "code root is not inside a git repository (%s) -- commit-pairing skipped" % code_root)
        return
    if not g.plan_in:
        r.emit("commit-pairing", "WARN", "plan root is not inside a git repository (%s) -- commit-pairing skipped" % plan_root)
        return
    if g.shallow:
        r.emit("commit-pairing", "WARN", "git history is shallow in the %s -- commits are missing, so commit-pairing could not run; skipped (fetch the full history, e.g. git fetch --unshallow)" % " and the ".join(g.shallow))
        return
    if plan_file_n > 0 and not grammar_seen:
        r.emit("commit-pairing", "WARN", "none of the %d commits touching the plan file use the <type>(%s) grammar -- project commit convention differs; commit-pairing skipped" % (plan_file_n, slug))
        return
    commits_code = _subjects(g, code_root, g.window_code, g.base_code, slug)
    if g.split:
        commits_plan = _subjects(g, plan_root, g.window_plan, g.base_plan, slug)
        desc = "code=%s plan=%s" % (g.desc_code, g.desc_plan)
        homes = "code-root"
        earlier = _cap(_log(g, code_root, "-n", "400", "-F", "--grep=" + slug, "--format=%s"))
        if "QVALIDATE_CONFIG_REPO" in os.environ:
            cfg = os.environ["QVALIDATE_CONFIG_REPO"]
        else:
            # A probe: a deployed copy outside any repository has no config-repo home.
            cfg = _cap(_git(HERE, "rev-parse", "--show-toplevel")[1])
        if cfg != "" and os.path.isfile(cfg + "/shared/AGENTS.md") and os.path.isfile(cfg + "/shared/skills/qvalidate/SKILL.md"):
            id_cfg = repo_id(r, cfg)
            if id_cfg != "" and id_cfg != g.id_code and id_cfg != g.id_plan:
                homes += ",config-repo"
                g.unborn.setdefault(cfg, _git(cfg, "rev-parse", "-q", "--verify", "HEAD")[0] != 0)
                earlier += "\n" + _cap(_log(g, cfg, "-n", "400", "-F", "--grep=" + slug, "--format=%s"))
        desc += " earlier=%s" % homes
    else:
        commits_plan, earlier, desc = commits_code, "", g.desc_code
    code_phases = []
    for subj in commits_code.split("\n"):
        if subj and any(subj.startswith("%s(%s):" % (t, slug)) for t in CODE_TYPES):
            ph = _phase_of(subj)
            if ph:
                code_phases.append(ph)
    docs_phases = set()
    for subj in (commits_plan + "\n" + earlier).split("\n"):
        if subj and subj.startswith("docs(%s):" % slug):
            ph = _phase_of(subj)
            if ph:
                docs_phases.add(ph)
    unpaired = []
    for ph in code_phases:
        if ph not in docs_phases and ph not in unpaired:
            unpaired.append(ph)
    if not code_phases:
        r.emit("commit-pairing", "PASS", "no code phase commits for %s in %s" % (slug, desc))
    elif unpaired:
        r.emit("commit-pairing", "FAIL", "code phase(s) %s for %s lack a paired docs(%s) commit in %s" % (" ".join(unpaired), slug, slug, desc))
    else:
        r.emit("commit-pairing", "PASS", "every code phase commit for %s has a paired docs commit in %s" % (slug, desc))


def check_doc_updates(r, g, lines, state, slug, code_root, since):
    # Every row of the "## Documentation Updates" table must name a target file the plan's own commits
    # touched. doc-table-only rows are skipped. Stays on the CODE root (a store-side row is not seen).
    # The section ends at the next '## ' heading or at '### Out of scope' / '### Zero-hit'. Decided
    # change 6: git runs with -c core.quotepath=off, so a non-ASCII path prints raw and is matched.
    if not g.code_in:
        r.emit("doc-updates", "WARN", "not inside a git repository -- doc-updates skipped")
        return
    section, f = [], False
    for l in lines:
        if RE_DOC_HEADING.match(l):
            f = True
            continue
        if l.startswith("## "):
            f = False
        if RE_DOC_END.match(l):
            f = False
        if f:
            section.append(l)
    while section and section[-1] == "":
        section.pop()
    if re.sub(WS, "", "".join(section), flags=A) == "":
        r.emit("doc-updates", "PASS", "no Documentation Updates section (or section empty)")
        return
    pre = ("-c", "core.quotepath=off")
    if since != "":
        # A ref that names no commit stops the run, naming the ref, instead of an empty range read as
        # "no file touched" (a misleading FAIL or WARN).
        if _git(code_root, "rev-parse", "-q", "--verify", since + "^{commit}")[0] != 0:
            raise GuardStop("--doc-updates-since ref does not name a commit: %s" % since)
        changed = _log(g, code_root, "%s..HEAD" % since, "--name-only", "--format=", pre=pre)
    elif g.window_code:
        changed = _log(g, code_root, "-n", "400", "-F", "--grep=(" + slug + ")", "--name-only", "--format=", pre=pre)
    else:
        changed = _log(g, code_root, "%s..HEAD" % g.base_code, "--name-only", "--format=", pre=pre)
    changed = _cap(changed)
    # Severity follows the parsed State: mid-plan an unimplemented phase's rows are legitimately absent.
    if state == "Complete" and g.shallow:
        # A shallow history lacks the commits a row may sit in, so an absent row is not evidence.
        severity, note = "WARN", "; git history is shallow - absent rows may sit in commits the clone lacks"
    elif state == "Complete":
        severity, note = "FAIL", ""
    else:
        severity, note = "WARN", "; State not Complete - absent rows may belong to unimplemented phases"
    missing, checked, skipped = [], 0, 0
    for row in section:
        if not row.startswith("|"):
            continue
        if RE_SEPARATOR_ROW.match(row) or RE_HEADER_ROW.match(row):
            continue
        if "doc-table-only" in row:
            skipped += 1
            continue
        cells = row.split("|")
        cell = cells[1] if len(cells) > 1 else ""
        # Every backticked path of the cell is a target (a row may name several files); a span that is
        # no path (no "." and no "/") is not one. Without a backticked path, the first bare path is.
        targets = [x for x in RE_BACKTICK.findall(cell) if "." in x or "/" in x]
        if not targets:
            m = RE_BARE_PATH.search(cell)
            targets = [m.group(0)] if m else []
        if not targets:
            skipped += 1
            continue
        for target in targets:
            checked += 1
            if not _doc_target_hit(target, changed):
                missing.append(target)

    if checked == 0:
        r.emit("doc-updates", "WARN", "Documentation Updates section present but no file-path targets parsed (%d row(s) skipped)" % skipped)
    elif missing:
        r.emit("doc-updates", severity, "Documentation Updates row target(s) absent from the plan's commits: %s (%d checked, %d skipped)%s" % (" ".join(missing), checked, skipped, note))
    else:
        r.emit("doc-updates", "PASS", "all %d Documentation Updates target(s) appear in the plan's commits (%d skipped)" % (checked, skipped))


def validate(argv, out, err):
    """-> exit code. `out`/`err` are binary streams; CHECK lines are flushed as they are emitted."""
    def usage(lines):
        for l in lines:
            err.write(("%s: %s\n" % (NAME, l)).encode("utf-8", "surrogateescape"))
        err.flush()
        return 2
    try:
        o = parse_args(argv)
        if o == "help":
            out.write((__doc__.strip("\n") + "\n").encode("utf-8"))
            out.flush()
            return 0
        if o == "selftest":
            return selftest()
        plan_abs, basename, plan_root, code_root = resolve_paths(o)
    except Usage as exc:
        return usage(exc.args)
    r = Run(out, err)
    try:
        lines = read_plan(plan_abs)
        status_line, state = status_line_and_state(lines)
        # (The applicability guard already proved the match; emit it as a suite member.)
        r.emit("filename-grammar", "PASS", "basename '%s' matches ^[0-9]{6}_[A-Z0-9_]+\\.md$" % basename)
        check_status_grammar(r, status_line)
        check_completeness(r, lines, state)
        if o["phase"] != "":
            check_phase_count(r, lines, o["phase"], o["expect"])
        check_parallel_symmetry(r, lines)
        check_sc_coverage(r, lines)
        check_harness(r, lines)
        check_acceptance_evidence(r, lines)
        if o["check_commits"]:
            g = GitContext(r, code_root, plan_root, o["base"])
            slug = basename[:-3]
            check_commit_pairing(r, g, slug, plan_abs, plan_root, code_root)
            check_doc_updates(r, g, lines, state, slug, code_root, o["since"])
        out.write(("SUMMARY\tpass=%d warn=%d fail=%d\n" % (r.n["PASS"], r.n["WARN"], r.n["FAIL"])).encode("ascii"))
        out.flush()
    except GuardStop as exc:
        return usage(["guard did not run: %s" % exc])
    except Exception as exc:
        return usage(["guard did not run: unexpected error: %s: %s" % (type(exc).__name__, exc)])
    return 1 if r.n["FAIL"] > 0 else 0


def main(argv=None):
    _require_venv(__file__)
    argv = sys.argv[1:] if argv is None else argv
    return validate(argv, sys.stdout.buffer, sys.stderr.buffer)


# ---------------------------------------------------------------------------
# Selftest. The fixture plans live in fixtures/<case>/ as *.md.in (so verify-links and verify-citations
# never scan them); a run copies a case to a scratch folder and drops the .in. Git layouts are built in
# the scratch folder at run time. The equivalence harness of plan 261016 Phase 14 builds the same cases
# through build_case() and CASES, so both read one table.
# ---------------------------------------------------------------------------

GIT_ID = ["-c", "user.name=qvalidate-selftest", "-c", "user.email=selftest@example.invalid",
          "-c", "commit.gpgsign=false", "-c", "core.hooksPath=.qv-no-hooks", "-c", "core.autocrlf=false"]


def _copy_fixture(case, dst):
    """Copy fixtures/<case> to dst, dropping a trailing .in from every file name. -> the plan file path."""
    shutil.copytree(os.path.join(FIXTURES, case), dst)
    found = []
    for dirpath, _dirs, names in os.walk(dst):
        for n in names:
            if n.endswith(".in"):
                os.replace(os.path.join(dirpath, n), os.path.join(dirpath, n[:-3]))
                found.append(os.path.join(dirpath, n[:-3]))
    return found[0]


def _sg(d, *args):
    r = subprocess.run(["git"] + GIT_ID + ["-C", d] + list(args), stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("git %s in %s: %s" % (" ".join(args), d, r.stderr.decode("utf-8", "replace")))
    return r.stdout.decode("utf-8", "replace").strip()


def _init(d):
    os.makedirs(d, exist_ok=True)
    _sg(d, "init", "-q", "-b", "main")


def _commit(d, subject, files=()):
    """Write each file (content 'x'), stage it, commit; with no files, an empty commit."""
    for rel in files:
        p = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("x\n")
    if files:
        _sg(d, "add", "--", *files)
    _sg(d, "commit", "-q", "--allow-empty", "-m", subject)
    return _sg(d, "rev-parse", "--short", "HEAD")


def _repo_with_plan(root, case):
    """root/repo, a git repo holding fixtures/<case> under plans/. -> (repo, plan path, slug)."""
    repo = os.path.join(root, "repo")
    _init(repo)
    plan = _copy_fixture(case, os.path.join(repo, "plans"))
    slug = os.path.basename(plan)[:-3]
    return repo, plan, slug


def _rel(repo, path):
    return os.path.relpath(path, repo).replace("\\", "/")


def build_case(case, root):
    """Materialise case['layout'] under root. -> (argv, env overrides, cwd)."""
    lay = case["layout"]
    os.makedirs(root, exist_ok=True)
    env = {"GIT_CEILING_DIRECTORIES": os.path.abspath(root)}
    ph = {"root": os.path.abspath(root)}
    if lay.startswith("plain:") or lay.startswith("crlf:"):
        plan = _copy_fixture(lay.split(":", 1)[1], os.path.join(root, "fx"))
        if lay.startswith("crlf:"):
            with open(plan, "rb") as fh:
                data = fh.read()
            with open(plan, "wb") as fh:
                fh.write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        ph.update(plan=plan, dir=os.path.dirname(plan), name=os.path.basename(plan))
        cwd = os.path.dirname(plan)
    elif lay.startswith("git:"):
        kind, fixture = lay[4:].split(":", 1)
        repo, plan, slug = _repo_with_plan(root, fixture)
        rp = _rel(repo, plan)
        if kind == "pair-window":
            _commit(repo, "docs(%s): add plan" % slug, [rp])
            _commit(repo, "feat(%s): phase 1 — alpha" % slug, ["done.md"])
            _commit(repo, "docs(%s): phase 1 progress" % slug)
        elif kind == "pair-main-ahead":
            # On main, with origin/main one commit behind HEAD: the window, not origin/main..HEAD.
            _commit(repo, "docs(%s): add plan" % slug, [rp])
            _commit(repo, "feat(%s): phase 1 — alpha" % slug, ["done.md"])
            _sg(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
            _sg(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            _commit(repo, "docs(%s): phase 1 progress" % slug)
        elif kind == "pair-branch":
            _commit(repo, "chore: initial commit", ["base.txt"])
            _sg(repo, "checkout", "-q", "-b", "topic")
            _commit(repo, "docs(%s): add plan" % slug, [rp])
            _commit(repo, "feat(%s): phase 1 alpha" % slug, ["done.md"])
            _commit(repo, "docs(%s): Phase 1 done" % slug)
            _commit(repo, "fix(%s): phase 2 beta" % slug, ["beta.txt"])
        elif kind == "no-code":
            _commit(repo, "docs(%s): add plan" % slug, [rp])
        elif kind == "foreign":
            _commit(repo, "Add the plan file", [rp])
        elif kind == "docs":
            _commit(repo, "docs(%s): add plan" % slug, [rp])
            _commit(repo, "feat(%s): phase 1 docs" % slug, ["done.md", "docs/plain.txt", "api.md",
                    "kiro_default.json", "shared/AGENTS.md", "Readme.md", "guide-été.md", "extra/first.md",
                    "other/SKILL.md"])
            _commit(repo, "docs(%s): phase 1 done" % slug)
        elif kind == "corrupt":
            # HEAD resolves, but its parent's object is gone: `git log` fails with exit 128.
            _commit(repo, "docs(%s): add plan" % slug, [rp])
            _commit(repo, "feat(%s): phase 1 — alpha" % slug, ["done.md"])
            parent = _sg(repo, "rev-parse", "HEAD~1")
            _commit(repo, "docs(%s): phase 1 progress" % slug)
            obj = os.path.join(repo, ".git", "objects", parent[:2], parent[2:])
            os.chmod(obj, 0o666)  # git writes objects read-only
            os.remove(obj)
        elif kind == "shallow":
            # A --depth 1 clone whose one commit is not in the <type>(<slug>) grammar.
            _commit(repo, "docs(%s): add plan" % slug, [rp])
            _commit(repo, "feat(%s): phase 1 — alpha" % slug, ["done.md"])
            _commit(repo, "docs(%s): phase 1 progress" % slug)
            _commit(repo, "Bump the version", ["version.txt"])
            clone = os.path.join(root, "clone")
            _sg(root, "clone", "-q", "--depth", "1", "file:///" + repo.replace("\\", "/"), clone)
            repo, plan = clone, os.path.join(clone, *rp.split("/"))
        elif kind == "unborn":
            pass  # a fresh repository: the plan is never committed and HEAD is unborn
        else:
            raise ValueError("unknown git layout %s" % kind)
        ph.update(plan=plan, dir=os.path.dirname(plan), name=os.path.basename(plan), repo=repo)
        cwd = repo
    elif lay.startswith("split:"):
        kind = lay[6:]
        code, stores = os.path.join(root, "code"), os.path.join(root, "stores")
        plans = os.path.join(stores, "wk-000000", "plans")
        _init(code)
        _init(stores)
        plan = _copy_fixture("store-plan", plans)
        slug = os.path.basename(plan)[:-3]
        sha = _commit(code, "feat(%s): phase 1" % slug, ["f.txt"])
        if kind != "plan-norepo":
            _commit(stores, "docs(%s): phase 1 progress (code: %s)" % (slug, sha), [_rel(stores, plan)])
        env["QVALIDATE_CONFIG_REPO"] = code
        if kind in ("cfg", "no-cfg"):
            _commit(code, "feat(%s): phase 2" % slug, ["g.txt"])
            cfg = os.path.join(root, "cfg")
            _init(cfg)
            _commit(cfg, "chore: config repo markers", ["shared/AGENTS.md", "shared/skills/qvalidate/SKILL.md"])
            _commit(cfg, "docs(%s): phase 2 progress, before the move" % slug)
            if kind == "cfg":
                env["QVALIDATE_CONFIG_REPO"] = cfg
        if kind == "plan-norepo":
            plans = os.path.join(root, "loose", "plans")
            os.makedirs(plans)
            shutil.copy(plan, plans)
        ph.update(plan=plan, code=code, plans=plans, name=os.path.basename(plan))
        cwd = code
    elif lay == "none":
        cwd = root
    else:
        raise ValueError("unknown layout %s" % lay)
    if case.get("cwd") == "root":
        cwd = os.path.abspath(root)

    def fill(s):
        for k, v in ph.items():
            s = s.replace("{%s}" % k, v)
        return s
    for k, v in (case.get("env") or {}).items():
        if k == "PATH":
            # A PATH with no git on it: one empty folder (the venv's python is run by its full path).
            v = fill(v)
            os.makedirs(v, exist_ok=True)
        env[k] = fill(v)
    return [fill(a) for a in case["argv"]], env, cwd, [fill(l) for l in case.get("expect", [])]


def _c(name, layout, argv, rc, expect=(), summary=None, note="", cwd=None, env=None, stderr=None, absent=()):
    """`stderr`: the exact stderr (a str ending in '...' is a prefix); `absent`: CHECK names that must not
    print. A case with `stderr` and rc 2 is a guard stop: it keeps the CHECK lines and prints no SUMMARY."""
    return {"name": name, "layout": layout, "argv": list(argv), "rc": rc, "expect": list(expect),
            "summary": summary, "note": note, "cwd": cwd, "env": env, "stderr": stderr, "absent": list(absent)}


P1 = "260101_PARITY_FIXTURE"
P2 = "260102_PARITY_FIXTURE_COMPLETE"
WIN = WINDOW_DESC
NA = "CHECK\tcompleteness\tPASS\tnot applicable - State not Complete"
HP = "CHECK\tharness-section\tPASS\t'## Harness Improvement Opportunities' present"
HW = "CHECK\tharness-section\tWARN\tno '## Harness Improvement Opportunities' section -- /qclose Pass 2 and /qdream GAT-PLANS will harvest nothing; absent is not the same as no-friction"
PS_SYM = "CHECK\tparallel-symmetry\tPASS\tall [P:N] parallel groups are symmetric"
PS_NONE = "CHECK\tparallel-symmetry\tPASS\tno [P:N] parallel-group annotations declared"
SC_ALL2 = "CHECK\tsc-coverage\tPASS\tall 2 SC ID(s) referenced by a phase '**Covers**:' line"
IP_LINE = "> **Status**: In Progress — phase 1 under way <!-- lifecycle: Exploring -> Draft -> In Progress -> Complete -->"


def _fg(slug):
    return "CHECK\tfilename-grammar\tPASS\tbasename '%s.md' matches ^[0-9]{6}_[A-Z0-9_]+\\.md$" % slug


CASES = [
    # --- the two test-parity fixtures and their five argsets (moved here from parity_sec_qvalidate) ---
    _c("parity1", "plain:parity-in-progress", ["--plan-root", "{dir}", "{name}"], 0, [
        _fg(P1), "CHECK\tstatus-grammar\tPASS\tconforms: > **Status**: In Progress", NA, PS_SYM, SC_ALL2, HW],
       "pass=5 warn=1 fail=0"),
    _c("parity1-phase1", "plain:parity-in-progress", ["--phase", "1", "--expect-ticked", "1", "--plan-root", "{dir}", "{name}"], 0, [
        "CHECK\tphase-count\tPASS\tPhase 1 has 1 ticked box(es), expected 1"], "pass=6 warn=1 fail=0"),
    _c("parity2", "plain:parity-complete", ["--plan-root", "{dir}", "{name}"], 1, [
        _fg(P2), "CHECK\tstatus-grammar\tPASS\tconforms: > **Status**: Complete — shipped and verified",
        "CHECK\tcompleteness\tFAIL\tState is Complete but 1 unticked checkbox(es) remain (deferrals included)",
        PS_NONE, "CHECK\tsc-coverage\tPASS\tall 1 SC ID(s) referenced by a phase '**Covers**:' line", HW],
       "pass=4 warn=1 fail=1"),
    _c("parity2-phase1", "plain:parity-complete", ["--phase", "1", "--expect-ticked", "1", "--plan-root", "{dir}", "{name}"], 1, [
        "CHECK\tphase-count\tPASS\tPhase 1 has 1 ticked box(es), expected 1"], "pass=5 warn=1 fail=1"),
    _c("parity2-phase2", "plain:parity-complete", ["--phase", "2", "--expect-ticked", "0", "--plan-root", "{dir}", "{name}"], 1, [
        "CHECK\tphase-count\tPASS\tPhase 2 has 0 ticked box(es), expected 0"], "pass=5 warn=1 fail=1"),
    # --- each check's PASS and FAIL/WARN path, without git ---
    _c("clean", "plain:clean", ["{plan}"], 0, [
        _fg("260201_QV_CLEAN"), "CHECK\tstatus-grammar\tPASS\tconforms: " + IP_LINE, NA, PS_SYM, SC_ALL2, HP],
       "pass=6 warn=0 fail=0"),
    _c("status-missing", "plain:no-status", ["{plan}"], 1, [
        "CHECK\tstatus-grammar\tFAIL\tno '> **Status**:' line found (nonconforming)", NA], "pass=5 warn=0 fail=1"),
    _c("status-nonconforming", "plain:bad-status", ["{plan}"], 1, [
        "CHECK\tstatus-grammar\tFAIL\tnonconforming status line: > **Status**: Complete (implementation + review) — shipped",
        "CHECK\tcompleteness\tFAIL\tState is Complete but 1 unticked checkbox(es) remain (deferrals included)"],
       "pass=4 warn=0 fail=2"),
    _c("completeness-pass", "plain:complete", ["{plan}"], 0, [
        "CHECK\tstatus-grammar\tPASS\tconforms: > **Status**: Complete — shipped",
        "CHECK\tcompleteness\tPASS\tState is Complete and all checkboxes are ticked", PS_NONE, SC_ALL2], "pass=6 warn=0 fail=0"),
    _c("phase-count-fail", "plain:clean", ["--phase", "1", "--expect-ticked", "2", "{plan}"], 1, [
        "CHECK\tphase-count\tFAIL\tPhase 1 has 1 ticked box(es), expected 2"], "pass=6 warn=0 fail=1"),
    _c("phase-count-auto", "plain:clean", ["--phase", "2", "--expect-ticked", "auto", "{plan}"], 0, [
        "CHECK\tphase-count\tPASS\tPhase 2 has 1 ticked box(es) (auto -- reported, not compared)"], "pass=7 warn=0 fail=0"),
    _c("phase-count-missing", "plain:clean", ["--phase", "7", "--expect-ticked", "0", "{plan}"], 1, [
        "CHECK\tphase-count\tFAIL\tPhase 7 heading (### Phase 7:) not found"], "pass=6 warn=0 fail=1"),
    _c("parallel-asym", "plain:parallel-asym", ["{plan}"], 1, [
        "CHECK\tparallel-symmetry\tFAIL\tasymmetric parallel annotation: Phase 1 lists 2 but Phase 2 does not list 1; Phase 3 declares [P:9] but Phase 9 does not exist;"],
       "pass=5 warn=0 fail=1"),
    _c("sc-orphan", "plain:sc-orphan", ["{plan}"], 1, [
        "CHECK\tsc-coverage\tFAIL\tSC ID(s) not covered by any phase '**Covers**:' line: SC-2"], "pass=5 warn=0 fail=1"),
    _c("sc-nocovers", "plain:sc-nocovers", ["{plan}"], 0, [
        "CHECK\tsc-coverage\tWARN\tSC-n IDs present but no '**Covers**:' lines found (adoption nudge)"], "pass=5 warn=1 fail=0"),
    # --- decided behaviours 1, 2, 4, 5 ---
    _c("d1-sc-unhyphenated", "plain:sc-unhyphenated", ["{plan}"], 0, [
        "CHECK\tsc-coverage\tWARN\tunhyphenated SC<n> token(s) found (e.g. SC1, not SC-1) -- sc-coverage's SC-[0-9]+ matcher will silently ignore them: SC2 SC3",
        "CHECK\tsc-coverage\tPASS\tall 1 SC ID(s) referenced by a phase '**Covers**:' line"], "pass=6 warn=1 fail=0",
       "decision 1 (the .ps1 has no unhyphenated WARN)"),
    _c("d2-phase-subletter", "plain:phase-subletter", ["--phase", "8b", "--expect-ticked", "2", "{plan}"], 0, [
        "CHECK\tphase-count\tPASS\tPhase 8b has 2 ticked box(es), expected 2"], "pass=7 warn=0 fail=0",
       "decision 2 (the .ps1 rejects 8b with exit 2)"),
    _c("d2-phase-plain-8", "plain:phase-subletter", ["--phase", "8", "--expect-ticked", "1", "{plan}"], 0, [
        "CHECK\tphase-count\tPASS\tPhase 8 has 1 ticked box(es), expected 1"], "pass=7 warn=0 fail=0"),
    _c("d4-harness-case", "plain:harness-case", ["{plan}"], 0, [HW], "pass=5 warn=1 fail=0",
       "decision 4 (the .ps1 matches the heading case-insensitively)"),
    _c("d5-parallel-note", "plain:parallel-note", ["{plan}"], 1, [
        "CHECK\tparallel-symmetry\tFAIL\tmalformed [P:N] annotation (expected [P:N] or [P:N,M]): Phase 1 has '[P:3 note]'; Phase 2 has '[P:3 note]'",
        SC_ALL2, HP], "pass=5 warn=0 fail=1",
       "decision 5 (the .sh aborts with no SUMMARY; the .ps1 reads [P:3])"),
    # --- git: commit-pairing and doc-updates ---
    _c("git-pair-window", "git:pair-window:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tevery code phase commit for 260201_QV_CLEAN has a paired docs commit in " + WIN,
        "CHECK\tdoc-updates\tPASS\tall 1 Documentation Updates target(s) appear in the plan's commits (0 skipped)"],
       "pass=8 warn=0 fail=0"),
    _c("git-pair-main-ahead", "git:pair-main-ahead:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tevery code phase commit for 260201_QV_CLEAN has a paired docs commit in " + WIN,
        "CHECK\tdoc-updates\tPASS\tall 1 Documentation Updates target(s) appear in the plan's commits (0 skipped)"],
       "pass=8 warn=0 fail=0", "on main with unpushed commits: the window, not origin/main..HEAD"),
    _c("git-pair-branch-fail", "git:pair-branch:clean", ["--check-commits", "--project-root", "{repo}", "{plan}"], 1, [
        "CHECK\tcommit-pairing\tFAIL\tcode phase(s) 2 for 260201_QV_CLEAN lack a paired docs(260201_QV_CLEAN) commit in main..HEAD",
        "CHECK\tdoc-updates\tPASS\tall 1 Documentation Updates target(s) appear in the plan's commits (0 skipped)"],
       "pass=7 warn=0 fail=1"),
    _c("git-no-code", "git:no-code:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tno code phase commits for 260201_QV_CLEAN in " + WIN,
        "CHECK\tdoc-updates\tWARN\tDocumentation Updates row target(s) absent from the plan's commits: done.md (1 checked, 0 skipped); State not Complete - absent rows may belong to unimplemented phases"],
       "pass=7 warn=1 fail=0"),
    _c("git-foreign", "git:foreign:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tWARN\tnone of the 1 commits touching the plan file use the <type>(260201_QV_CLEAN) grammar -- project commit convention differs; commit-pairing skipped"],
       "pass=6 warn=2 fail=0"),
    _c("no-repo", "plain:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tWARN\tnot inside a git repository -- commit-pairing skipped",
        "CHECK\tdoc-updates\tWARN\tnot inside a git repository -- doc-updates skipped"], "pass=6 warn=2 fail=0"),
    _c("d3-d6-doc-updates", "git:docs:docs", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tevery code phase commit for 260212_QV_DOCS has a paired docs commit in " + WIN,
        "CHECK\tdoc-updates\tWARN\tDocumentation Updates row target(s) absent from the plan's commits: README.md extra/second.md sub/SKILL.md (10 checked, 2 skipped); State not Complete - absent rows may belong to unimplemented phases"],
       "pass=7 warn=1 fail=0",
       "decisions 3 and 6 (the .sh also misses guide-été.md; the .ps1 also reads past ### Out of scope and matches README.md case-insensitively)"),
    _c("doc-updates-since", "git:docs:docs", ["--check-commits", "--doc-updates-since", "HEAD", "{plan}"], 0, [
        "CHECK\tdoc-updates\tWARN\tDocumentation Updates row target(s) absent from the plan's commits: done.md docs/plain.txt api.md:102,148 kiro_default.{json,md} shared/AGENTS.md § Memory locations README.md guide-été.md extra/first.md extra/second.md sub/SKILL.md (10 checked, 2 skipped); State not Complete - absent rows may belong to unimplemented phases"],
       "pass=7 warn=1 fail=0"),
    _c("doc-updates-fail-complete", "git:pair-window:complete", ["--check-commits", "{plan}"], 1, [
        "CHECK\tdoc-updates\tFAIL\tDocumentation Updates row target(s) absent from the plan's commits: missing.md (2 checked, 0 skipped)"],
       "pass=7 warn=0 fail=1"),
    _c("doc-updates-notarget", "git:no-code:docs-notarget", ["--check-commits", "{plan}"], 0, [
        "CHECK\tdoc-updates\tWARN\tDocumentation Updates section present but no file-path targets parsed (1 row(s) skipped)"],
       "pass=7 warn=1 fail=0"),
    _c("doc-updates-none", "git:no-code:parity-in-progress", ["--check-commits", "{plan}"], 0, [
        "CHECK\tdoc-updates\tPASS\tno Documentation Updates section (or section empty)"], "pass=7 warn=1 fail=0"),
    # --- review fixes R2-R5, R11 (plan 261016 Phase 14) ---
    _c("crlf-bare-status", "crlf:crlf-complete", ["{plan}"], 1, [
        "CHECK\tstatus-grammar\tPASS\tconforms: > **Status**: Complete",
        "CHECK\tcompleteness\tFAIL\tState is Complete but 1 unticked checkbox(es) remain (deferrals included)", HP],
       "pass=4 warn=0 fail=1", "R5/R11: a CRLF plan reads as an LF one (both twins agree; the first port kept the CR)"),
    _c("x2-git-corrupt", "git:corrupt:clean", ["--check-commits", "{plan}"], 2, [_fg("260201_QV_CLEAN"), HP],
       stderr="qvalidate.py: guard did not run: git log failed: ...", absent=["commit-pairing", "doc-updates"],
       note="R2: a failing git log stops the run (both twins read it as no commits and PASS)"),
    _c("x2-doc-updates-since-bad", "git:docs:docs", ["--check-commits", "--doc-updates-since", "nosuchref", "{plan}"], 2, [
        "CHECK\tcommit-pairing\tPASS\tevery code phase commit for 260212_QV_DOCS has a paired docs commit in " + WIN],
       stderr="qvalidate.py: guard did not run: --doc-updates-since ref does not name a commit: nosuchref\n",
       absent=["doc-updates"], note="R2: a bad --doc-updates-since ref exits 2 naming it (both twins report every row absent)"),
    _c("x2-git-missing", "git:pair-window:clean", ["--check-commits", "{plan}"], 2, [_fg("260201_QV_CLEAN"), HP],
       env={"PATH": "{root}/nogit"}, stderr="qvalidate.py: guard did not run: git not found\n",
       absent=["commit-pairing", "doc-updates"], note="R3: no git on PATH exits 2 (the twins said not inside a git repository)"),
    _c("git-shallow", "git:shallow:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tWARN\tgit history is shallow in the repository ({dir}) -- commits are missing, so commit-pairing could not run; skipped (fetch the full history, e.g. git fetch --unshallow)"],
       note="R4: a shallow clone names the shallow history (the twins print the grammar WARN)"),
    _c("git-shallow-complete", "git:shallow:complete", ["--check-commits", "{plan}"], 0, [
        "CHECK\tdoc-updates\tWARN\tDocumentation Updates row target(s) absent from the plan's commits: done.md missing.md (2 checked, 0 skipped); git history is shallow - absent rows may sit in commits the clone lacks"],
       note="re-review: a shallow clone downgrades a Complete plan's doc-updates FAIL to WARN"),
    _c("git-unborn", "git:unborn:clean", ["--check-commits", "{plan}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tno code phase commits for 260201_QV_CLEAN in " + WIN],
       note="an unborn HEAD still reads as no commits, as in both twins"),
    # --- the two-repo layout: a store-repo plan and a code repo ---
    _c("split-pair", "split:pair", ["--check-commits", "--project-root", "{code}", "--plan-root", "{plans}", "{name}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tevery code phase commit for 260214_QV_STORE_PLAN has a paired docs commit in code=%s plan=%s earlier=code-root" % (WIN, WIN),
        "CHECK\tdoc-updates\tPASS\tno Documentation Updates section (or section empty)"], "pass=8 warn=0 fail=0"),
    _c("split-earlier-config-repo", "split:cfg", ["--check-commits", "--project-root", "{code}", "--plan-root", "{plans}", "{name}"], 0, [
        "CHECK\tcommit-pairing\tPASS\tevery code phase commit for 260214_QV_STORE_PLAN has a paired docs commit in code=%s plan=%s earlier=code-root,config-repo" % (WIN, WIN)],
       "pass=8 warn=0 fail=0"),
    _c("split-unpaired", "split:no-cfg", ["--check-commits", "--project-root", "{code}", "--plan-root", "{plans}", "{name}"], 1, [
        "CHECK\tcommit-pairing\tFAIL\tcode phase(s) 2 for 260214_QV_STORE_PLAN lack a paired docs(260214_QV_STORE_PLAN) commit in code=%s plan=%s earlier=code-root" % (WIN, WIN)],
       "pass=7 warn=0 fail=1"),
    _c("split-plan-norepo", "split:plan-norepo", ["--check-commits", "--project-root", "{code}", "--plan-root", "{plans}", "{name}"], 0, [
        "CHECK\tcommit-pairing\tWARN\tplan root is not inside a git repository ({plans}) -- commit-pairing skipped"],
       "pass=7 warn=1 fail=0", "the path is printed in the host's form (the .sh prints /c/...)"),
    # --- acceptance-evidence (plan 261016 Phase 16): the golden rows, copied from real plans ---
    _c("ae-golden", "plain:ae-golden", ["{plan}"], 1, [
        "CHECK\tacceptance-evidence\tFAIL\t2 of 4 acceptance hit(s) without evidence at line(s) 10, 11"],
       "pass=5 warn=0 fail=1", "two real FAIL rows, one own-segment row, one quote-first decisions row"),
    _c("ae-golden-crlf", "crlf:ae-golden", ["{plan}"], 1, [
        "CHECK\tacceptance-evidence\tFAIL\t2 of 4 acceptance hit(s) without evidence at line(s) 10, 11"],
       "pass=5 warn=0 fail=1"),
    _c("ae-none", "plain:clean", ["{plan}"], 0, summary="pass=6 warn=0 fail=0", absent=["acceptance-evidence"],
       note="no User: accepted hit, no line"),
    # --- exit 2: precondition failures ---
    _c("x2-no-plan", "none", [], 2),
    _c("x2-unknown-flag", "plain:clean", ["--bogus", "{plan}"], 2),
    _c("x2-second-positional", "plain:clean", ["{plan}", "{plan}"], 2),
    _c("x2-missing-value", "plain:clean", ["{plan}", "--base"], 2),
    _c("x2-phase-alone", "plain:clean", ["--phase", "1", "{plan}"], 2),
    _c("x2-expect-alone", "plain:clean", ["--expect-ticked", "1", "{plan}"], 2),
    _c("x2-phase-shape", "plain:clean", ["--phase", "8bb", "--expect-ticked", "1", "{plan}"], 2),
    _c("x2-expect-shape", "plain:clean", ["--phase", "1", "--expect-ticked", "x", "{plan}"], 2),
    _c("x2-project-root-missing", "plain:clean", ["--project-root", "{root}/nope", "{plan}"], 2),
    _c("x2-plan-root-missing", "plain:clean", ["--plan-root", "{root}/nope", "{name}"], 2),
    _c("x2-plan-missing", "plain:clean", ["{dir}/260299_QV_ABSENT.md"], 2),
    _c("x2-relative-against-project-root", "plain:clean", ["--project-root", "{dir}", "{name}"], 2, cwd="root",
       note="a relative plan path resolves against the cwd, never against --project-root"),
    _c("relative-against-plan-root", "plain:clean", ["--plan-root", "{dir}", "{name}"], 0, cwd="root",
       summary="pass=6 warn=0 fail=0"),
    _c("x2-not-a-plan", "plain:not-a-plan", ["{plan}"], 2),
    _c("x2-time-suffix", "plain:time-suffix", ["{plan}"], 2),
    _c("x2-plans-done", "plain:archived", ["{plan}"], 2),
    _c("help", "none", ["--help"], 0, note="the header names qvalidate.py and adds --selftest"),
]


# acceptance-evidence fixtures, run in process: (name, the plan's body lines, the expected CHECK line or None
# for no line, the encoding: "lf" | "crlf" | "bom"). The plan is "> **Status**: Draft", a blank line, then the
# body, so a body's first line is line 3. _ae_row puts one row under a table header: the row is line 5.
AE_PASS1 = "CHECK\tacceptance-evidence\tPASS\t1 acceptance hit(s) carry evidence"
AE_FAIL5 = "CHECK\tacceptance-evidence\tFAIL\t1 of 1 acceptance hit(s) without evidence at line(s) 5"


def _ae_row(resolution, finding="A finding."):
    return ["| # | Severity | Finding | Resolution |", "|---|---|---|---|",
            "| 1 | Low | %s | %s |" % (finding, resolution)]


AE_CASES = [("ae-straight-quote", _ae_row('User: accepted — "ok with recos".'), AE_PASS1, "lf"),
            ("ae-curly-quote", _ae_row("User: accepted — “ok”."), AE_PASS1, "lf"),
            ("ae-short-quote", _ae_row('User: accepted — "ok".'), AE_PASS1, "lf"),
            ("ae-date-only", _ae_row("User: accepted — 2026-10-23."), AE_PASS1, "lf")]
for _ref in ("user turn", "user answer", "user decision", "same turn", "same user turn", "decision 5a"):
    for _form in (_ref, _ref.upper()):
        AE_CASES.append(("ae-ref %s" % _form, _ae_row("User: accepted — deferred (%s)." % _form), AE_PASS1, "lf"))
AE_CASES += [
    ("ae-ref Decision 1", _ae_row("User: accepted — Decision 1."), AE_PASS1, "lf"),
    ("ae-ref decision D-14", _ae_row("User: accepted — per decision D-14."), AE_PASS1, "lf"),
    ("ae-bare", _ae_row("User: accepted — deferred."), AE_FAIL5, "lf"),
    ("ae-empty-quote", _ae_row('User: accepted — "" deferred.'), AE_FAIL5, "lf"),
    ("ae-lone-quote", _ae_row('User: accepted — a 6" screen.'), AE_FAIL5, "lf"),
    ("ae-single-quote", _ae_row("User: accepted — 'fine by me'."), AE_FAIL5, "lf"),
    ("ae-decision-to-defer", _ae_row("User: accepted — decision to defer."), AE_FAIL5, "lf"),
    ("ae-follow-up", _ae_row("User: accepted — Follow-up 12."), AE_FAIL5, "lf"),
    ("ae-decisions-table", ["| Item | User decision | Effect |", "|---|---|---|",
                            '| U-1 | "ok" | #4: User: accepted — documented limitation |'], AE_PASS1, "lf"),
    ("ae-decisions-empty-quote", ["| Item | User decision | Effect |", "|---|---|---|",
                                  '| U-1 | "" | #4: User: accepted — documented limitation |'], AE_FAIL5, "lf"),
    ("ae-finding-quotes", _ae_row("User: accepted — deferred.", 'The doc says "retry later".'), AE_FAIL5, "lf"),
    ("ae-finding-starts-with-a-quote", _ae_row("User: accepted — deferred.", '"retry later" is wrong.'), AE_FAIL5, "lf"),
    ("ae-quote-first-user-facing-column", ["| # | Finding | User-facing impact | Resolution |", "|---|---|---|---|",
                                           '| 1 | x | "none" | User: accepted — deferred. |'], AE_FAIL5, "lf"),
    ("ae-quote-first-design-decision-column", ["| Item | Decision | Effect |", "|---|---|---|",
                                                '| U-1 | "keep it" | #4: User: accepted — documented limitation |'], AE_FAIL5, "lf"),
    ("ae-quote-first-column-not-a-decision", ["| Item | Note | Effect |", "|---|---|---|",
                                              '| U-1 | "ok" | #4: User: accepted — documented limitation |'], AE_FAIL5, "lf"),
    ("ae-two-hits", _ae_row('User: accepted — "ok" (2026-10-23); later User: accepted — deferred.'),
     "CHECK\tacceptance-evidence\tFAIL\t1 of 2 acceptance hit(s) without evidence at line(s) 5", "lf"),
    ("ae-two-rows", _ae_row("User: accepted — deferred.") + ["| 2 | Low | B. | User: accepted — later. |"],
     "CHECK\tacceptance-evidence\tFAIL\t2 of 2 acceptance hit(s) without evidence at line(s) 5, 6", "lf"),
    ("ae-escaped-pipe", ["| # | Resolution |", "|---|---|", '| 1 | "ok" \\| User: accepted — deferred. |'],
     AE_FAIL5, "lf"),
    ("ae-prose", ["User: accepted — deferred, in prose."], None, "lf"),
    ("ae-code-span", _ae_row("`User: accepted — <reason>` is the template."), None, "lf"),
    ("ae-code-span-evidence", _ae_row('User: accepted — `"ok"` in code.'), AE_FAIL5, "lf"),
    ("ae-unbalanced-backtick", _ae_row("User: accepted — deferred `x`.", "The `--dest flag is unchecked."),
     AE_FAIL5, "lf"),
    ("ae-two-bare-hits", _ae_row("User: accepted — a; User: accepted — b."),
     "CHECK\tacceptance-evidence\tFAIL\t2 of 2 acceptance hit(s) without evidence at line(s) 5", "lf"),
    ("ae-negated-pending", _ae_row("User: accepted — pending user decision."), AE_FAIL5, "lf"),
    ("ae-negated-no", _ae_row("User: accepted — no user turn recorded."), AE_FAIL5, "lf"),
    ("ae-negated-awaiting", _ae_row("User: accepted — AWAITING decision 5a."), AE_FAIL5, "lf"),
    ("ae-negated-without", _ae_row("User: accepted — without user answer."), AE_FAIL5, "lf"),
    ("ae-negated-nbsp", _ae_row("User: accepted — pending user decision."), AE_FAIL5, "lf"),
    ("ae-negated-plus-date", _ae_row("User: accepted — no user turn quoted, 2026-10-23."), AE_PASS1, "lf"),
    ("ae-negated-plus-ref", _ae_row("User: accepted — without user answer; same user turn as C2-5."), AE_PASS1, "lf"),
    ("ae-fenced", ["```", "| 1 | Low | A finding. | User: accepted — deferred. |", "```"], None, "lf"),
    ("ae-tilde-fenced", ["~~~", "| 1 | Low | A finding. | User: accepted — deferred. |", "~~~"], None, "lf"),
    ("ae-box-bare", ["", "", "- [x] User acceptance: the chart reads as steady"], AE_FAIL5, "lf"),
    ("ae-box-evidence", ["", "", '- [x] User acceptance: the chart reads as steady — "looks steady now" (2026-10-28)'], AE_PASS1, "lf"),
    ("ae-box-unticked", ["", "", "- [ ] User acceptance: the chart reads as steady"], None, "lf"),
    ("ae-box-fenced", ["```", "- [x] User acceptance: x", "```"], None, "lf"),
    ("ae-box-numbered-lower", ["", "", "1. [X] user acceptance: the chart reads as steady"], AE_FAIL5, "lf"),
    ("ae-indented-row", ["| # | Resolution |", "|---|---|", "  | 1 | User: accepted — deferred. |"], AE_FAIL5, "lf"),
    ("ae-crlf", _ae_row("User: accepted — deferred."), AE_FAIL5, "crlf"),
    ("ae-bom", _ae_row("User: accepted — deferred."), AE_FAIL5, "bom"),
    ("ae-no-hit", _ae_row("Fixed — done."), None, "lf"),
]


def _ae_plan(path, body, enc, state="Draft"):
    text = "\n".join(["> **Status**: %s" % state, ""] + body + ["", "## Harness Improvement Opportunities", ""])
    data = text.encode("utf-8")
    if enc == "crlf":
        data = data.replace(b"\n", b"\r\n")
    elif enc == "bom":
        data = b"\xef\xbb\xbf" + data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _run_py(argv, env, cwd):
    full = dict(os.environ)
    full.update(env)
    r = subprocess.run([sys.executable, "-I", "-B", os.path.abspath(__file__)] + argv, cwd=cwd, env=full,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    return r.returncode, r.stdout, r.stderr


def selftest():
    fails, checks, skips = [], [0], []

    def chk(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (name, (": " + detail) if detail else ""))

    tmp = tempfile.mkdtemp(prefix="qvalidate-selftest-")
    try:
        for i, case in enumerate(CASES):
            root = os.path.join(tmp, "c%02d" % i)
            try:
                argv, env, cwd, expect = build_case(case, root)
            except Exception as exc:
                chk("%s: layout builds" % case["name"], False, "%s: %s" % (type(exc).__name__, exc))
                continue
            rc, out, err = _run_py(argv, env, cwd)
            text = out.decode("utf-8", "replace")
            lines = text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")
            chk("%s: exit %d" % (case["name"], case["rc"]), rc == case["rc"],
                "exit %s, stdout %r, stderr %r" % (rc, text[-400:], err[-300:]))
            chk("%s: LF-only stdout" % case["name"], b"\r" not in out)
            for want in expect:
                chk("%s: line %r" % (case["name"], want[:70]), want in lines, repr(lines))
            errt = err.decode("utf-8", "replace").replace("\r\n", "\n")
            if case["stderr"] is not None:
                want = case["stderr"]
                ok = errt.startswith(want[:-3]) if want.endswith("...") else errt == want
                chk("%s: stderr %r" % (case["name"], want[:70]), ok, repr(errt))
            for absent in case["absent"]:
                chk("%s: no %s line" % (case["name"], absent),
                    not any(l.startswith("CHECK\t%s\t" % absent) for l in lines), repr(lines))
            if case["rc"] == 2 and case["stderr"] is not None:
                chk("%s: a guard stop prints no SUMMARY" % case["name"],
                    not any(l.startswith("SUMMARY") for l in lines), repr(lines))
            elif case["rc"] == 2 and case["name"] != "help":
                chk("%s: no stdout, a stderr reason" % case["name"], out == b"" and err.startswith(b"qvalidate.py: "),
                    "%r %r" % (out, err))
            if case["summary"] is not None:
                chk("%s: SUMMARY" % case["name"], lines[-1:] == ["SUMMARY\t" + case["summary"]], repr(lines[-1:]))
                n = {"PASS": 0, "WARN": 0, "FAIL": 0}
                for l in lines[:-1]:
                    f = l.split("\t")
                    if f[0] == "CHECK" and len(f) >= 4:
                        n[f[2]] = n.get(f[2], 0) + 1
                chk("%s: SUMMARY counts the CHECK lines" % case["name"],
                    lines[-1:] == ["SUMMARY\tpass=%d warn=%d fail=%d" % (n["PASS"], n["WARN"], n["FAIL"])], repr(lines))
            if case["name"] == "help":
                chk("help: prints the header", text.startswith("qvalidate.py -- deterministic validator") and "--selftest" in text)

        # --- exit 2 on an unexpected error, keeping the lines already printed (in process) ---
        plan = _copy_fixture("clean", os.path.join(tmp, "boom"))
        saved = globals()["check_harness"]

        def boom(r, lines):
            raise RuntimeError("injected")
        globals()["check_harness"] = boom
        out, err = io.BytesIO(), io.BytesIO()
        try:
            rc = validate([plan], out, err)
        finally:
            globals()["check_harness"] = saved
        got = out.getvalue().decode("utf-8").split("\n")
        chk("an unexpected error exits 2", rc == 2, str(rc))
        chk("an unexpected error keeps the CHECK lines printed before it, and prints no SUMMARY",
            len(got) == 6 and got[0].startswith("CHECK\tfilename-grammar\t") and got[4].startswith("CHECK\tsc-coverage\t")
            and not any(l.startswith("SUMMARY") for l in got), repr(got))
        chk("an unexpected error names itself on stderr",
            err.getvalue() == b"qvalidate.py: guard did not run: unexpected error: RuntimeError: injected\n", repr(err.getvalue()))

        # --- R2: an injected failing `git log` stops the run at each must-succeed site (in process) ---
        real_git = globals()["_git"]
        for label, hit in (("the pairing window", lambda a: a[0] == "log" and any(x.startswith("--grep=") for x in a)),
                           ("the plan file's history", lambda a: a[0] == "log" and "--" in a),
                           ("doc-updates' file list", lambda a: a[0] == "log" and "--name-only" in a)):
            argv, env, _cwd, _e = build_case(_c("inj", "git:pair-window:clean", ["--check-commits", "{plan}"], 0),
                                             os.path.join(tmp, "inj-%d" % len(label)))

            def fake(root, *args, **kw):
                if hit(args):
                    return 128, "", "error: x\nfatal: injected\n"
                return real_git(root, *args, **kw)
            globals()["_git"] = fake
            out, err = io.BytesIO(), io.BytesIO()
            try:
                rc = validate(argv, out, err)
            finally:
                globals()["_git"] = real_git
            got = out.getvalue().decode("utf-8")
            chk("an injected failing git log in %s exits 2" % label, rc == 2, "%s %r" % (rc, got))
            chk("an injected failing git log in %s names git and its stderr tail" % label,
                err.getvalue() == b"qvalidate.py: guard did not run: git log failed: fatal: injected\n", repr(err.getvalue()))
            chk("an injected failing git log in %s keeps the lines printed and prints no SUMMARY" % label,
                got.startswith("CHECK\tfilename-grammar\t") and "SUMMARY" not in got, repr(got))

        # --- a leading BOM is not part of the first line (utf-8-sig) ---
        bom = os.path.join(tmp, "bom", "260301_QV_BOM.md")
        os.makedirs(os.path.dirname(bom))
        with open(bom, "wb") as fh:
            fh.write(b"\xef\xbb\xbf> **Status**: Draft\n\n## Harness Improvement Opportunities\n")
        out, err = io.BytesIO(), io.BytesIO()
        rc = validate([bom], out, err)
        chk("a BOM before the Status line is dropped", rc == 0 and b"CHECK\tstatus-grammar\tPASS\tconforms: > **Status**: Draft\n"
            in out.getvalue(), repr(out.getvalue()))

        # --- acceptance-evidence: each case asserts its one CHECK line, or no line ---
        # The check applies in every State: one case runs on a Complete plan.
        for i, case in enumerate(AE_CASES + [
                ("ae-state-complete", _ae_row("User: accepted — deferred."), AE_FAIL5, "lf", "Complete")]):
            name, body, want, enc = case[:4]
            p = os.path.join(tmp, "ae%02d" % i, "260401_QV_AE.md")
            _ae_plan(p, body, enc, case[4] if len(case) > 4 else "Draft")
            out, err = io.BytesIO(), io.BytesIO()
            rc = validate([p], out, err)
            got = [l for l in out.getvalue().decode("utf-8").split("\n") if l.startswith("CHECK\tacceptance-evidence\t")]
            chk("%s: acceptance-evidence line" % name, got == ([want] if want else []), repr(got))
            want_rc = 1 if want is not None and "\tFAIL\t" in want else 0
            chk("%s: exit %d" % (name, want_rc), rc == want_rc, "%s %r" % (rc, err.getvalue()))

        # --- acceptance-evidence: an error inside the check is could-not-run (exit 2), never a FAIL ---
        p = os.path.join(tmp, "ae-boom", "260401_QV_AE.md")
        _ae_plan(p, _ae_row("User: accepted — deferred."), "lf")
        saved = globals()["_ae_has_marker"]

        def ae_boom(segment):
            raise re.error("injected")
        globals()["_ae_has_marker"] = ae_boom
        out, err = io.BytesIO(), io.BytesIO()
        try:
            rc = validate([p], out, err)
        finally:
            globals()["_ae_has_marker"] = saved
        got = out.getvalue().decode("utf-8")
        chk("an acceptance-evidence error exits 2 with no acceptance-evidence line and no SUMMARY",
            rc == 2 and "acceptance-evidence" not in got and "SUMMARY" not in got, "%s %r" % (rc, got))
        chk("an acceptance-evidence error prints the unexpected-error guard line on stderr",
            err.getvalue() == ("qvalidate.py: guard did not run: unexpected error: %s: injected\n"
                               % type(re.error("x")).__name__).encode("ascii"), repr(err.getvalue()))

        # --- the venv guard: another interpreter exits 2 before anything runs ---
        other_py = getattr(sys, "_base_executable", None)
        if other_py and os.path.normcase(os.path.realpath(other_py)) != os.path.normcase(os.path.realpath(sys.executable)):
            r = subprocess.run([other_py, "-I", "-B", os.path.realpath(__file__), plan],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            chk("another interpreter exits 2 with the venv message", r.returncode == 2 and r.stdout == b""
                and b"guard did not run: venv missing" in r.stderr, "%s %r" % (r.returncode, r.stderr[:200]))
        else:
            skips.append("venv guard: no interpreter outside the venv to try")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for s in skips:
        print("SKIP: %s" % s)
    for f in fails:
        print("FAIL: %s" % f)
    print("qvalidate selftest: %d failure(s), %d check(s), %d skipped" % (len(fails), checks[0], len(skips)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
