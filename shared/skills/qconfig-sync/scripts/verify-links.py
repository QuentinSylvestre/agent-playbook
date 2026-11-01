#!/usr/bin/env python3
"""verify-links.py -- validate the repo's self-citations: every backticked repo-relative path citation
must resolve, and every section anchor must still occur in the file it points at.

Run with the playbook venv (<repo>/.venv-agent-playbook); any other interpreter exits 2 ("guard did not
run: venv missing"). Stdlib only, Python 3.8+. It reads files, writes nothing, runs no git and touches no
network.

This is the DERIVED counterpart to verify-citations. That script walks a hand-maintained CHECKS list (a
ratchet: a citation that disappears must FAIL, so the list is deliberately not derived). This one derives
its whole workload from the prose, so a citation nobody remembered to register is still checked.

Scope: shared/ and providers/ markdown. plans/ is excluded (archived project files deliberately record
citations that were valid when written, and plans/.handoff-*.md / plans/tests/HARNESS.md are created at
runtime). memory/ is excluded as a SOURCE (its provenance staleness is owned by the /qdream sweep, where
confirmed-absent is an expected state) but allowed as a citation TARGET. User memory lives in the store
repo behind the config repo's `memory` link: the link is followed when indexing targets, and where there is
no memory/ at all (a fresh clone, CI) every memory/ citation is counted on one SKIPPED line, not as missing.
Every fixtures/ folder (qdream's, qconfig-sync's, the Claude hook's, ...) is excluded: it is deliberately
fictional test data. A memory/topics/ citation whose file this user's memory does not hold is SKIPPED, not
missing: topic files are each user's own, and verify-memory checks the topic index itself.

What counts as a citation:
  - Anchored: a backticked span holding a path and a section sign, e.g.
    `shared/AGENTS.md § Commit Conventions`. The path is resolved and the anchor must occur literally in
    the target.
  - Bare: a backticked path with NO section sign. Only checked when it contains a slash AND its first
    segment is shared/, providers/, memory/ or workspaces/. No workspaces/ directory exists any more
    (stores live in the store repo, outside this repo), so a bare workspaces/ citation reports
    MISSING_PATH: stale prose naming the old layout is caught, not skipped. A path holding an angle
    bracket (a format placeholder) is skipped upstream. A bare filename is nearly always a concept ("the
    project's CLAUDE.md"), a filename-grammar template (YYMMDD_UPPER_CASE.md) or a worked example, not a
    pointer -- checking all of them yields 41% false failures.

Path resolution tries four locations, in order: repo-relative, the citing file's own directory, its
scripts/ subdir, its references/ subdir. A trailing :NNN line-number suffix is stripped. Globs,
brace-twin notation (setup.{sh,ps1}) and {{TEMPLATE}} tokens are skipped. The file index is
every regular file under the repo root except the top-level .git (a filesystem walk, not a git listing:
a file added in the same commit as its first citation is untracked at check time).

Anchor matching is ANY-LITERAL-OCCURRENCE, the same rule verify-citations uses (grep -c -F). A stricter
heading-only matcher was measured at 75 failures over 321 citations of which 1 was real --
numbered-heading prefixes (## 1) Personas table), bold labels, and trailing punctuation all defeat it. A
compound anchor is reduced before matching: a backticked segment inside the anchor wins, else the anchor
is split on the section sign, an arrow or a greater-than and the last segment is tried, then the first.
A trailing parenthetical is dropped from the candidate.

Case: the path gates (extension, plans/, first segment, .md target) are case-INSENSITIVE (ASCII), so
`Plans/` and `plans/` are treated alike, as on the Windows filesystem. Path resolution itself is exact.

Escape hatch, for text that is not a real citation (format placeholders, deliberately fictional example
paths):
  <!-- verify-links: skip <path> -->   exempts that target on this line
  <!-- verify-links: skip -->          exempts the whole line
A marker inside a code span is being quoted, not applied, and is ignored.

Usage:
  verify-links.py [--help] [<repo-root>]
  verify-links.py --selftest
The optional <repo-root> defaults to the repo this script sits in (four directories up), never the
ambient cwd. Any convention change must update qconfig-sync/SKILL.md's documented invocations in the same
commit.

Output: one tab-separated line per citation:
  <STATUS>\\t<citation>\\t<citing-site>\\t<hit-count>
STATUS in {OK, MISSING_PATH, MISSING_ANCHOR}. Trailing SUMMARY line; a REMEDIATION line follows it when a
citation is broken. Sources are scanned in byte order of their repo-relative path, lines in file order.

Exit codes:
  0   every citation resolves.
  1   one or more citations are broken.
  2   precondition failure (venv missing, repo path invalid, not an agent-playbook repo, or the tree could
      not be enumerated or read): the guard did not run.
"""
import os
import re
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.realpath(__file__))
DEFAULT_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))  # scripts -> repo
NAME = "verify-links.py"
SECT = "§"
ARROW = "→"
# Files the /qdream sweep creates at runtime (the crash-recovery journal, the state file of the first full
# run). A citation names them as places, so their absence is no stale pointer.
RUNTIME_FILES = ("memory/.dream-journal.jsonl", "memory/.dream-state.json")


def is_fixture(rel):
    """Any file under a fixtures/ folder: deliberately fictional test data, never a source."""
    return "/fixtures/" in "/" + rel
REMEDIATION = ("Repoint the citation at where the target actually lives, or fix the anchor to text that "
               "occurs in the target. If the span is not a real citation -- a format placeholder, a "
               "deliberately fictional example, a path belonging to another repo -- annotate the line with "
               "<!-- verify-links: skip <path> --> rather than deleting the check. Never weaken the resolver "
               "to make a broken pointer pass: the guard exists because a stale pointer reads as "
               "authoritative.")

GATE_RE = re.compile("[a-z0-9_.@/-][a-z0-9_.@/{}*-]*\\.(?:md|sh|ps1|json|jsonl|tsv|py)(?:[ \\t]|\\Z|"
                     + SECT + "|:)")
SKIP_RE = re.compile(r"<!--[ \t]*verify-links:[ \t]*skip[^>]*-->")
SKIP_HEAD_RE = re.compile(r"\A<!--[ \t]*verify-links:[ \t]*skip[ \t]*")
SKIP_TAIL_RE = re.compile(r"[ \t]*-->\Z")
SPAN_RE = re.compile(r"`[^`]+`")
TRAIL_PUNCT_RE = re.compile(r"[.,;:)]+\Z")
LINE_SUFFIX_RE = re.compile(r":[0-9]+\Z")
DEPAREN_RE = re.compile(r"[ \t]*\([^()]*\)[ \t]*\Z")
WS_TAIL_RE = re.compile(r"[ \t].*\Z", re.DOTALL)
ASCII_LOWER = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}


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
    """The guard cannot give a verdict (exit 2); the args are the stderr lines."""


def trim(s):
    """Space and tab only, never other whitespace."""
    return s.strip(" \t")


def lower(s):
    """ASCII-only lowercasing, for the case-insensitive gates."""
    return s.translate(ASCII_LOWER)


def byte_key(s):
    return s.encode("utf-8", "surrogateescape")


def read_text(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return data.decode("utf-8-sig", "surrogateescape")


def split_lines(text):
    """Records split on LF only; a final line without a newline is kept, a trailing newline adds none;
    one trailing CR is dropped from every line."""
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [p[:-1] if p.endswith("\r") else p for p in parts]


def walk_files(repo, top, prune_git, label):
    """Every regular file under repo/top (symlinks neither listed nor followed), as '/'-joined paths
    relative to repo with `top` spelled as given. Any listing error is CouldNotRun."""
    out = []

    def rec(abs_dir, rel_dir):
        try:
            with os.scandir(abs_dir) as it:
                entries = list(it)
        except OSError as exc:
            raise CouldNotRun("%s: could not enumerate %s; guard did not run" % (NAME, label), "  %s" % exc)
        for e in entries:
            rel = e.name if rel_dir == "" else rel_dir + "/" + e.name
            if prune_git and rel_dir == "" and e.name == ".git":
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    rec(e.path, rel)
                elif e.is_file(follow_symlinks=False):
                    out.append(rel)
            except OSError as exc:
                raise CouldNotRun("%s: could not enumerate %s; guard did not run" % (NAME, label), "  %s" % exc)

    rec(os.path.join(repo, top) if top else repo, top)
    return out


def codemask(s):
    """Same-length mask of s with every code-span character replaced by \\x01. A run of N backticks opens
    a span that only a run of exactly N closes; an unmatched run opens nothing. Offsets into the mask line
    up with offsets into s, so a skip marker is located in the raw line (keeping a backticked argument)
    and rejected when it starts inside a code span."""
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] != "`":
            out.append(s[i])
            i += 1
            continue
        runlen = 0
        while i + runlen < n and s[i + runlen] == "`":
            runlen += 1
        j, close = i + runlen, -1
        while j < n:
            if s[j] == "`":
                k = 0
                while j + k < n and s[j + k] == "`":
                    k += 1
                if k == runlen:
                    close = j
                    break
                j += k
            else:
                j += 1
        if close < 0:
            out.append("`" * runlen)
            i += runlen
            continue
        out.append("\x01" * (close + runlen - i))
        i = close + runlen
    return "".join(out)


def _segments(a):
    return a.replace(SECT, "\x01").replace(ARROW, "\x01").replace(">", "\x01").split("\x01")


def leafof(a):
    """A backticked segment inside the anchor wins outright; else the last segment."""
    m = SPAN_RE.search(a)
    if m:
        return trim(m.group()[1:-1])
    return trim(_segments(a)[-1])


def firstof(a):
    return trim(_segments(a)[0])


def deparen(s):
    """Drop a trailing parenthetical, e.g. "Memory Management (Dream autonomy ...)"."""
    return trim(DEPAREN_RE.sub("", s, count=1))


class Checker:
    def __init__(self, repo, have):
        self.repo = repo
        self.have = have
        self.cache = {}
        self.ok = 0
        self.bad = 0
        self.out = []
        self.memory_present = True
        self.memory_skipped = 0

    def resolves(self, p, d):
        p = LINE_SUFFIX_RE.sub("", p, count=1)
        if p == "":
            return ""
        for c in (p, d + "/" + p, d + "/scripts/" + p, d + "/references/" + p):
            if c in self.have:
                return c
        return ""

    def content(self, path):
        """The target read once and cached; one trailing CR and one leading BOM dropped from every line.
        A read failure is not an empty target: it is CouldNotRun."""
        if path in self.cache:
            return self.cache[path]
        try:
            text = read_text(os.path.join(self.repo, path))
        except OSError as exc:
            raise CouldNotRun("%s: cannot read cited target %s; guard did not run" % (NAME, path), "  %s" % exc)
        buf = "".join((l[1:] if l.startswith("﻿") else l) + "\n" for l in split_lines(text))
        self.cache[path] = buf
        return buf

    def emit(self, status, citation, site, lineno, hits):
        self.out.append("%s\t%s\t%s:%d\t%d" % (status, citation, site, lineno, hits))
        if status == "OK":
            self.ok += 1
        else:
            self.bad += 1

    def check(self, span, site, d, lineno, skip):
        span = trim(span)
        if not GATE_RE.match(lower(span)):
            return
        si = span.find(SECT)
        if si >= 0:
            p = trim(span[:si])
            anchor = trim(span[si + 1:])
        else:
            p = WS_TAIL_RE.sub("", span, count=1)
            anchor = ""
        p = TRAIL_PUNCT_RE.sub("", p, count=1)
        if "*" in p or "{" in p:                     # glob / brace-twin / template token
            return
        if lower(p).startswith("plans/"):            # transient project files + runtime artifacts
            return
        if lower(p) in RUNTIME_FILES:                # exists only while a /qdream sweep runs, or after its first
            return                                   # full run: absent is the normal state, never a stale pointer
        if lower(p).startswith("memory/") and not self.memory_present:
            self.memory_skipped += 1                 # no user memory here (fresh clone, CI): not checkable
            return
        if p in skip or "" in skip:                  # <!-- verify-links: skip ... -->
            return
        if anchor == "":
            if "/" not in p:                         # a bare filename is a concept, not a pointer
                return
            if lower(p).split("/", 1)[0] not in ("shared", "providers", "memory", "workspaces"):
                return
        tgt = self.resolves(p, d)
        if tgt == "" and lower(p).startswith("memory/topics/"):
            # A topic file is the user's own (their memory, in their store repo): another user's memory
            # need not hold it. verify-memory owns the topic index (rows, files and citers agree).
            self.memory_skipped += 1
            return
        if tgt == "":
            self.emit("MISSING_PATH", span, site, lineno, 0)
            return
        if anchor == "" or not lower(tgt).endswith(".md"):
            self.emit("OK", span, site, lineno, 1)
            return
        body = self.content(tgt)
        cand = deparen(leafof(anchor))
        if cand != "" and cand in body:
            self.emit("OK", span, site, lineno, 1)
            return
        cand = deparen(firstof(anchor))
        if cand != "" and cand in body:
            self.emit("OK", span, site, lineno, 1)
            return
        self.emit("MISSING_ANCHOR", span, site, lineno, 0)

    def scan_line(self, line, site, d, lineno):
        skip = set()
        masked = codemask(line)
        for m in SKIP_RE.finditer(line):
            if masked[m.start()] == "\x01":          # quoted, not applied
                continue
            marker = SKIP_HEAD_RE.sub("", m.group(), count=1)
            marker = SKIP_TAIL_RE.sub("", marker, count=1)
            skip.add(trim(marker.replace("`", "")))  # a backticked argument is still an argument
        # Double-backtick spans are delimited first: a ``A `B` C`` span holds inner single backticks.
        for idx, chunk in enumerate(line.split("``")):
            if idx % 2 == 1:
                self.check(chunk, site, d, lineno, skip)
            else:
                for m in SPAN_RE.finditer(chunk):
                    self.check(m.group()[1:-1], site, d, lineno, skip)


def run(repo):
    """-> (exit code, stdout lines, stderr lines). Never prints; the selftest calls it in process."""
    if not os.path.isdir(repo):
        return 2, [], ["%s: repo path not found: %s" % (NAME, repo)]
    if not os.path.isfile(os.path.join(repo, "shared", "AGENTS.md")):
        return 2, [], ["%s: %s does not look like an agent-playbook repo" % (NAME, repo)]
    chk = None
    try:
        have = set(walk_files(repo, "", True, "repo files"))
        mem = os.path.join(repo, "memory")
        memory_present = os.path.isdir(mem)
        if memory_present and os.path.islink(mem):
            # user memory lives in the store repo behind the `memory` link: index it like a repo folder
            have.update(walk_files(repo, "memory", False, "user memory"))
        sources = []
        for root in ("shared", "providers"):
            if os.path.isdir(os.path.join(repo, root)):
                for rel in walk_files(repo, root, False, "source markdown"):
                    if lower(rel).endswith(".md") and not is_fixture(rel):
                        sources.append(rel)
        sources.sort(key=byte_key)
        if not sources:
            return 0, ["SUMMARY\tok=0\tmissing=0"], []
        chk = Checker(repo, have)
        chk.memory_present = memory_present
        for site in sources:
            slash = site.rfind("/")
            d = site[:slash] if slash >= 0 else "."
            try:
                text = read_text(os.path.join(repo, site))
            except OSError as exc:
                raise CouldNotRun("%s: cannot read %s; guard did not run" % (NAME, site), "  %s" % exc)
            for lineno, line in enumerate(split_lines(text), 1):
                chk.scan_line(line, site, d, lineno)
    except CouldNotRun as exc:
        return 2, (chk.out if chk else []), list(exc.args)
    out = list(chk.out)
    if chk.memory_skipped:
        why = ("no user memory at %s (run setup to link it)" % os.path.join(repo, "memory")
               if not chk.memory_present else "topic files this user memory does not hold (verify-memory checks the index)")
        out.append("SKIPPED\t%d memory/ citation(s): %s" % (chk.memory_skipped, why))
    out.append("SUMMARY\tok=%d\tmissing=%d" % (chk.ok, chk.bad))
    if chk.bad > 0:
        out.append("REMEDIATION\t" + REMEDIATION)
        return 1, out, []
    return 0, out, []


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

BASE_AGENTS = "# Agents\n\n## Commit Conventions\n\nText.\n\n## Memory Management\n\nMore (Dream autonomy) here.\n"


def _tree(base, name, files):
    root = os.path.join(base, name)
    files = dict(files)
    files.setdefault("shared/AGENTS.md", BASE_AGENTS)
    for rel, body in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(body if isinstance(body, bytes) else body.encode("utf-8"))
    return root


def _lines(rows, remediation):
    ok = sum(1 for r in rows if r.startswith("OK\t"))
    skipped = sum(1 for r in rows if r.startswith("SKIPPED\t"))
    out = list(rows) + ["SUMMARY\tok=%d\tmissing=%d" % (ok, len(rows) - ok - skipped)]
    if remediation:
        out.append("REMEDIATION\t" + REMEDIATION)
    return out


def selftest():
    fails = []
    checks = [0]
    base = tempfile.mkdtemp(prefix="verify-links-selftest-")

    def expect(name, root, rc, rows=None, reason=None):
        """rows: the citation rows; SUMMARY (and REMEDIATION) are appended, except on exit 2, where rows
        are the whole stdout (the rows emitted before the guard stopped, no SUMMARY)."""
        checks[0] += 1
        got_rc, out, err = run(root)
        if got_rc != rc:
            fails.append("%s: exit %d, want %d (stderr: %s)" % (name, got_rc, rc, " | ".join(err)))
            return
        if reason is not None and ((out and rows is None) or not any(reason in e for e in err)):
            fails.append("%s: want a stderr line naming %r, got %r / %r" % (name, reason, out, err))
        if rows is not None:
            want = list(rows) if rc == 2 else _lines(rows, rc == 1)
            if out != want:
                fails.append("%s: output differs\n    got:  %r\n    want: %r" % (name, out, want))

    def unreadable(name, root, rel, rows, reason):
        """Run with the module's reader failing for one repo-relative path, as an unreadable file would."""
        global read_text
        real, bad = read_text, os.path.normcase(os.path.normpath(os.path.join(root, rel)))

        def failing(path):
            if os.path.normcase(os.path.normpath(path)) == bad:
                raise PermissionError(13, "Permission denied (selftest)", path)
            return real(path)

        read_text = failing
        try:
            expect(name, root, 2, rows, reason)
        finally:
            read_text = real

    try:
        a = "shared/AGENTS.md"
        ok_src = (
            "See `shared/AGENTS.md § Commit Conventions` and `shared/AGENTS.md`.\n"
            "Paren: `shared/AGENTS.md § Memory Management (Dream autonomy exception)`.\n"
            "Leaf: `shared/AGENTS.md § Nope → Commit Conventions`; first: `shared/AGENTS.md § Commit Conventions > Nope`.\n"
            "Line suffix: `shared/AGENTS.md:12`, trailing punct `shared/AGENTS.md: see`.\n"
            "Double: ``shared/AGENTS.md § `Commit Conventions` `` ok.\n"
            "Upper ext: `shared/UP.MD § Hello`.\n"
        )
        skill_src = "Local: `tool.sh § anything` and `ref.md § Hello` and `SKILL.md § Local`.\n"
        root = _tree(base, "ok", {
            "shared/a.md": ok_src,
            "shared/UP.MD": "Hello\n",
            "shared/skills/x/SKILL.md": skill_src,
            "shared/skills/x/scripts/tool.sh": "#!/bin/sh\n",
            "shared/skills/x/references/ref.md": "Hello there\n",
        })
        s = "shared/a.md"
        k = "shared/skills/x/SKILL.md"
        expect("all-OK tree", root, 0, [
            "OK\t%s § Commit Conventions\t%s:1\t1" % (a, s),
            "OK\t%s\t%s:1\t1" % (a, s),
            "OK\t%s § Memory Management (Dream autonomy exception)\t%s:2\t1" % (a, s),
            "OK\t%s § Nope → Commit Conventions\t%s:3\t1" % (a, s),
            "OK\t%s § Commit Conventions > Nope\t%s:3\t1" % (a, s),
            "OK\t%s:12\t%s:4\t1" % (a, s),
            "OK\t%s: see\t%s:4\t1" % (a, s),
            "OK\t%s § `Commit Conventions`\t%s:5\t1" % (a, s),
            "OK\tshared/UP.MD § Hello\t%s:6\t1" % s,
            "OK\ttool.sh § anything\t%s:1\t1" % k,
            "OK\tref.md § Hello\t%s:1\t1" % k,
            "OK\tSKILL.md § Local\t%s:1\t1" % k,
        ])

        root = _tree(base, "bomcrlf", {
            "shared/a.md": b"\xef\xbb\xbf" + ok_src.replace("\n", "\r\n").encode("utf-8"),
            "shared/AGENTS.md": b"\xef\xbb\xbf" + BASE_AGENTS.replace("\n", "\r\n").encode("utf-8"),
            "shared/UP.MD": b"\xef\xbb\xbfHello\r\n",
            "shared/skills/x/SKILL.md": skill_src,
            "shared/skills/x/scripts/tool.sh": "#!/bin/sh\n",
            "shared/skills/x/references/ref.md": "Hello there\n",
        })
        checks[0] += 1
        if run(root) != run(os.path.join(base, "ok")):
            fails.append("BOM/CRLF tree: output differs from the LF tree")

        root = _tree(base, "missing-path", {"shared/a.md": "x\nBroken `shared/nope.md` here.\n"})
        expect("MISSING_PATH", root, 1, ["MISSING_PATH\tshared/nope.md\tshared/a.md:2\t0"])

        root = _tree(base, "missing-anchor", {"shared/a.md": "`shared/AGENTS.md § No Such Heading`\n"})
        expect("MISSING_ANCHOR", root, 1, ["MISSING_ANCHOR\tshared/AGENTS.md § No Such Heading\tshared/a.md:1\t0"])

        root = _tree(base, "anchor-case", {"shared/a.md": "`shared/AGENTS.md § commit conventions`\n"})
        expect("anchor match is case-sensitive", root, 1,
               ["MISSING_ANCHOR\tshared/AGENTS.md § commit conventions\tshared/a.md:1\t0"])

        root = _tree(base, "unreadable", {
            "shared/a.md": "`shared/AGENTS.md § Commit Conventions`\n`shared/t.md § Hello` `shared/AGENTS.md`\n",
            "shared/t.md": "Hello\n",
            "shared/z.md": "`shared/AGENTS.md`\n",
        })
        unreadable("exit 2: unreadable cited target keeps the rows so far, no SUMMARY", root, "shared/t.md",
                   ["OK\tshared/AGENTS.md § Commit Conventions\tshared/a.md:1\t1"],
                   "cannot read cited target shared/t.md; guard did not run")
        unreadable("exit 2: unreadable source keeps the rows so far, no SUMMARY", root, "shared/z.md", [
            "OK\tshared/AGENTS.md § Commit Conventions\tshared/a.md:1\t1",
            "OK\tshared/t.md § Hello\tshared/a.md:2\t1",
            "OK\tshared/AGENTS.md\tshared/a.md:2\t1",
        ], "cannot read shared/z.md; guard did not run")

        root = _tree(base, "skip-target", {"shared/a.md":
                     "`shared/nope.md` <!-- verify-links: skip shared/nope.md --> `shared/gone.md`\n"})
        expect("skip <path>", root, 1, ["MISSING_PATH\tshared/gone.md\tshared/a.md:1\t0"])

        root = _tree(base, "skip-backticked", {"shared/a.md":
                     "`shared/nope.md` <!-- verify-links: skip `shared/nope.md` -->\n"})
        expect("skip `<path>`", root, 0, [])

        root = _tree(base, "skip-line", {"shared/a.md":
                     "`shared/nope.md` <!--verify-links:skip--> `shared/AGENTS.md § Nope`\n"})
        expect("skip whole line", root, 0, [])

        root = _tree(base, "skip-quoted", {"shared/a.md":
                     "Quoted ``<!-- verify-links: skip -->`` and `<!-- verify-links: skip -->` then `shared/nope.md`\n"
                     "Next line `shared/nope.md` <!-- verify-links: skip -->\n"})
        expect("quoted marker is not applied, and is line-scoped", root, 1,
               ["MISSING_PATH\tshared/nope.md\tshared/a.md:1\t0"])

        root = _tree(base, "bare", {"shared/a.md":
                     "`foo.md` `docs/x.md` `memory/x.md` `workspaces/x.md` `providers/x.md` `Shared/x.md` "
                     "`other/y.md § A` `<placeholder>/x.md` `shared/*.md` `shared/{a,b}.md`\n",
                     "memory/MEMORY.md": "# user memory present, so memory/ citations are checked\n"})
        expect("bare-path rule", root, 1, [
            "MISSING_PATH\tmemory/x.md\tshared/a.md:1\t0",
            "MISSING_PATH\tworkspaces/x.md\tshared/a.md:1\t0",
            "MISSING_PATH\tproviders/x.md\tshared/a.md:1\t0",
            "MISSING_PATH\tShared/x.md\tshared/a.md:1\t0",
            "MISSING_PATH\tother/y.md § A\tshared/a.md:1\t0",
        ])

        # user memory absent (fresh clone, CI): memory/ citations are counted as SKIPPED, never MISSING
        root = _tree(base, "no-memory", {"shared/a.md": "`memory/MEMORY.md § Topics` `memory/topics/x.md`\n"})
        expect("no memory/: memory citations skipped, not missing", root, 0, [
            "SKIPPED\t2 memory/ citation(s): no user memory at %s (run setup to link it)"
            % os.path.join(root, "memory"),
        ])

        # the sweep's runtime files (journal, first-run state) are places, not pointers: absent is not missing
        root = _tree(base, "runtime", {"shared/a.md": "`memory/.dream-journal.jsonl` `memory/.dream-state.json` `memory/gone.md`"
                                                      " `memory/topics/not-mine.md`\n",
                                       "memory/MEMORY.md": "# m\n"})
        expect("runtime files never missing; a topic file the user lacks is skipped; another memory/ path is missing",
               root, 1, [
                   "MISSING_PATH\tmemory/gone.md\tshared/a.md:1\t0",
                   "SKIPPED\t1 memory/ citation(s): topic files this user memory does not hold (verify-memory checks the index)",
               ])

        # user memory behind the `memory` link (it lives in the store repo): followed and checked
        store = _tree(base, "linked-store", {"shared/AGENTS.md": BASE_AGENTS,
                                             "user/memory/MEMORY.md": "## Topics\n"})
        root = _tree(base, "linked", {"shared/a.md": "`memory/MEMORY.md § Topics` `memory/MEMORY.md § Gone`\n"})
        try:
            os.symlink(os.path.join(store, "user", "memory"), os.path.join(root, "memory"), target_is_directory=True)
            linked = True
        except (OSError, NotImplementedError):
            linked = False
        if linked:
            expect("memory/ link: followed, anchors checked in the linked file", root, 1, [
                "OK\tmemory/MEMORY.md § Topics\tshared/a.md:1\t1",
                "MISSING_ANCHOR\tmemory/MEMORY.md § Gone\tshared/a.md:1\t0",
            ])
        else:
            print("SKIP memory/ link: no symlink could be made")

        root = _tree(base, "plans-memory", {
            "shared/a.md": "`plans/x.md § Foo` `PLANS/y.md` `memory/MEMORY.md § Topics`\n",
            "providers/p/b.md": "`memory/MEMORY.md`\n",
            "memory/MEMORY.md": "## Topics\n`shared/nope-from-memory.md`\n",
            "plans/p.md": "`shared/nope-from-plans.md`\n",
            "shared/skills/qdream/scripts/fixtures/f.md": "`shared/nope-from-fixtures.md`\n",
            "shared/skills/qconfig-sync/scripts/fixtures/g.md": "`shared/nope-from-other-fixtures.md`\n",
        })
        expect("plans/ excluded, memory/ a target only, fixtures excluded, byte-order sources", root, 0, [
            "OK\tmemory/MEMORY.md\tproviders/p/b.md:1\t1",
            "OK\tmemory/MEMORY.md § Topics\tshared/a.md:1\t1",
        ])

        expect("exit 2: repo path not found", os.path.join(base, "no-such-dir"), 2,
               reason="repo path not found")
        root = os.path.join(base, "not-a-repo")
        os.makedirs(os.path.join(root, "shared"))
        expect("exit 2: not an agent-playbook repo", root, 2, reason="does not look like an agent-playbook repo")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    for f in fails:
        print("FAIL " + f)
    print("verify-links selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
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
    first = argv[0] if argv else ""
    if first == "--help":
        sys.stdout.flush()
        sys.stdout.buffer.write((__doc__.strip() + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    if first == "--selftest":
        return selftest()
    repo = first or DEFAULT_REPO
    try:
        rc, out, err = run(repo)
    except Exception as exc:
        print("%s: guard did not run: unexpected error: %s: %s" % (NAME, type(exc).__name__, exc), file=sys.stderr)
        return 2
    sys.stdout.flush()
    sys.stdout.buffer.write("".join(l + "\n" for l in out).encode("utf-8", "surrogateescape"))
    sys.stdout.buffer.flush()
    for line in err:
        print(line, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
