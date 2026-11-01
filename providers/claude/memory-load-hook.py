#!/usr/bin/env python3
"""Claude Code SessionStart hook: a guaranteed memory floor for every session.

Reads the hook's stdin JSON (`cwd`, `hook_event_name`, `source`, ...) and
prints one JSON object whose `hookSpecificOutput.additionalContext` holds,
under a character cap (default 9,500; Claude Code saves anything over about
10,000 to a file instead of injecting it):

  1. a 2-line header;
  2. the heading index of the config repo's user `memory/MEMORY.md`, by section;
  3. the heading index of `memory/HIGHER_ORDER.md`;
  4. the `## Topics` rows of user memory (path and trigger), one line each;
  5. each tier's absolute file path;
  6. then the project tier in full when the remaining budget holds it,
     otherwise its heading index.

The fixed index (1-5) is reserved first. When it alone is over the cap, whole
lines are dropped from the end of the user index and a `(+N more -- see
<path>)` line replaces them; a line is never cut in half.

An entry is marked with a warning sign when a file cited on its `Source`
line (its anchor, not a path named in prose) changed in git after its
`Verified` date (the cheap `cited_path_changed` check only: one
batched `git log` per repository, the whole hook capped at 3 seconds; over
the cap the marks are omitted and the header says so). A cited path resolves
against the config repo (user and higher-order tiers) or the project root
(project tier) only, so the hook can under-mark relative to the sweep's
manifest but never over-mark.

Where the project tier comes from (shared/skills/qdream/memory-rules.md
§ Resolution contract): the store resolver, `resolve_artifact` in
`shared/skills/qdream/scripts/store-resolver.py`. It walks up from `cwd` to the
git toplevel and, at each level, reads the store-repo store that holds memory.
The nearest level that holds memory wins, so a nested project keeps its own
memory over its toplevel's (the resolver's walk-up rule). When no store holds
memory, the in-workspace `memory/MEMORY.md` is read only where the resolver's
`folder_fallback` names it: a folder where the resolver creates no store (such
as the system temp directory), no store at any level of its walk, and a
readable store repo; the nearest level up to the git toplevel, outside git the
folder itself only. In any other folder an in-workspace copy is a leftover and
is not read, and a missing or unreadable store repo reads nothing. Inside the
config repo its own `memory/` is the user tier (step 0) and is never read as
project memory.

When the project tier is delivered in full, its marked headings are listed
on one line before the text (`<mark> in project tier: <heading>; ...`).

Every tier is parsed by `shared/skills/qdream/scripts/memory-entries.py`
(entries, sections and the Topics rows). The hook loads it and the store
resolver directly from the config repo; `dream-manifest.py` supplies only the
Source-anchor rules the marks use, so a broken `dream-manifest.py` drops the
marks (the header says so) and a broken resolver drops the project tier (a
note says so), never the user and higher-order index.

An in-workspace memory/MEMORY.md read by folder_fallback (a no-create folder
such as Downloads, where untrusted trees land) is shown as a labelled heading
index, never in full. A store-repo project tier names the store's identity, so
a session can see which workspace's memory it was given. When the store repo
has a rebase, merge or cherry-pick in progress, or the project file holds git
conflict markers, the project tier is shown as an index with a note.

The store repo (`AGENT_PLAYBOOK_STORES`, else the pointer file's `stores=`, else `~/.agent-playbook/stores`) gets a
one-line notice when it is missing, or when it holds paths uncommitted or
commits unpushed for over a day (plan 261016 Phase 10; the same tests as
`shared/skills/qconfig-sync/scripts/verify-stores.py`). The two git calls share
the time cap with the marks; a timeout or git failure emits no notice.

Fails open (shared/AGENTS.md § Read-time behavior, "Memory loading fails
open"): on any error it exits 0 with a one-line notice as the context. It
writes nothing: no files, no bytecode, and git runs with
--no-optional-locks. Stdlib only, Python 3.8+.

Usage:
  memory-load-hook.py [--cap N] < hook-input.json
  memory-load-hook.py --selftest     # runs fixtures/memory-load-hook/*/case.json
Deployment and the settings.json snippet: providers/claude/README.md
§ SessionStart memory hook.
"""

import sys

# Before any import: no __pycache__ beside this script or the qdream scripts
# it loads (a stray .pyc makes a deployed copy look drifted).
sys.dont_write_bytecode = True

import argparse
import datetime  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

START = time.monotonic()
DEFAULT_CAP = 9500
TIME_CAP = 3.0
MARK = "⚠"
HEADER = ("Playbook memory index — a snapshot taken at session start; current files and the "
          "user's latest instructions win over it. Open an entry's file when its heading applies; "
          "%s = Source file changed since verified, re-check before relying" % MARK)
IS_WINDOWS = os.name == "nt"
SKIP_SECTIONS = {"topics", "declined"}

for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def config_repo_of_script():
    """The config repo: the parent of providers/claude/ under the real path
    of this file (the deployed file is a symlink into the repo)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def load_module(path, name):
    if not os.path.isfile(path):
        raise RuntimeError("%s not found (is the hook deployed as a symlink into the config repo?)"
                           % path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_helpers(config_repo):
    """-> (store resolver, memory-entries parser, dream-manifest). The parser is required (every tier
    needs it); the resolver or dream-manifest is the exception that stopped its load instead, which costs
    only the project tier or the marks."""
    scripts = os.path.join(config_repo, "shared", "skills", "qdream", "scripts")
    me = load_module(os.path.join(scripts, "memory-entries.py"), "memory_entries")
    got = []
    for name, mod in (("store-resolver.py", "store_resolver"), ("dream-manifest.py", "dream_manifest")):
        try:
            got.append(load_module(os.path.join(scripts, name), mod))
        except Exception as e:  # noqa: BLE001 -- reported in the output, never raised
            got.append(e)
    return got[0], me, got[1]


# --------------------------------------------------------------------------
# Locating the project tier
# --------------------------------------------------------------------------

def git_toplevel(folder):
    """The nearest folder at or above `folder` holding a `.git` entry, found
    on disk (no git call); None when there is none."""
    cur = os.path.abspath(folder)
    while True:
        if os.path.lexists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def store_identity(store):
    """The STORE lines of a store directory joined by "; " (how the hook names the store it read), or ''."""
    try:
        with open(os.path.join(str(store), "STORE"), encoding="utf-8") as fh:
            return "; ".join(x.strip() for x in fh.read().splitlines() if x.strip())[:200]
    except (OSError, UnicodeDecodeError):
        return ""


def store_operation(sr):
    """The git operation the store repo is stopped in ("rebase", "merge", "cherry-pick"), or ''.
    Read from the files git leaves in .git (no git call), as dream-write.py's in_progress does."""
    try:
        g = os.path.join(str(sr.store_repo_root()), ".git")
        for marker, name in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"),
                             ("CHERRY_PICK_HEAD", "cherry-pick")):
            if os.path.exists(os.path.join(g, marker)):
                return name
    except Exception:  # noqa: BLE001 -- advisory
        return ""
    return ""


FALLBACK_LINE_MAX = 120
CONFLICT_RE = re.compile(r"^(<{7}|>{7})( |$)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def has_conflict_markers(text):
    """True when a git conflict marker line (`<<<<<<< ` or `>>>>>>> `) sits outside a code fence, as
    verify-memory's conflict-marker rule reads it: a fenced example is not a conflict."""
    fence = None
    for line in text.replace("\r\n", "\n").split("\n"):
        fm = FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        if CONFLICT_RE.match(line):
            return True
    return False


def locate_project(config_repo, cwd, sr):
    """-> (project root or None, memory file or None, [note lines], store repo state, info).
    info: {"fallback": True for an in-workspace copy, "store": the store directory or None}.

    One call to the store resolver decides the project tier: the store-repo store that holds
    memory, else (source none) the resolver's folder_fallback, which names an in-workspace memory/
    only in a no-create folder no store serves, with the store repo readable. A store repo that is
    missing or cannot be read leaves nothing to show (a reader fails open), and the note lines say
    so for an unreadable one (a missing one gets store_notice's line). The state is the resolver's
    `store_repo` ("ok", "missing", "unreadable").
    """
    start = os.path.abspath(cwd)
    art = sr.resolve_artifact(start, "memory")
    notes = []
    if art.store_repo == "unreadable":
        why = " ".join(str(art.reason).replace("store repo skipped: ", "", 1).split())
        notes.append("Note: store repo unreadable: %s; project memory kept there cannot be shown "
                     "(resolve it with /qconfig-sync)." % why)
    if art.source == "none" and str(art.reason).startswith("untrusted root"):
        notes.append("Note: %s; a store this folder's git remote names is not shown here." % art.reason)
    if art.source == "none":
        # memory-rules.md § Resolution contract and the no-store read rule: folder_fallback alone
        # decides whether an in-workspace copy may be read; None means there is nothing to read.
        found = sr.folder_fallback(start, "memory")
        if found is None:
            return None, None, notes, art.store_repo, {}
        mem = os.path.join(str(found), "MEMORY.md")
        if not os.path.exists(mem):
            return None, None, notes, art.store_repo, {}
        return str(found.parent), mem, notes, art.store_repo, {"fallback": True}
    if art.source == "failed" or art.path is None:
        return None, None, notes, art.store_repo, {}
    mem = os.path.join(str(art.path), "MEMORY.md")
    if not os.path.exists(mem):
        return None, None, notes, art.store_repo, {}
    return str(art.folder), mem, notes, art.store_repo, {"store": art.store}


# --------------------------------------------------------------------------
# Store repo health: missing, or uncommitted / unpushed for over a day
# --------------------------------------------------------------------------

DAY = 86400.0


def _store_git(root, args, deadline):
    """stdout of one git call in the store repo, or None on a failure or past the deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        r = subprocess.run(["git", "--no-optional-locks", "--git-dir", os.path.join(root, ".git"),
                            "--work-tree", root] + args, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=remaining)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _old_uncommitted(root, out, now):
    """True when a `git status --porcelain -z` path (or, deleted, its nearest existing parent)
    was last modified over a day ago."""
    toks = out.split(b"\0")
    i = 0
    while i < len(toks):
        tok = toks[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, rel = tok[:2].decode("ascii", "replace"), tok[3:].decode("utf-8", "replace")
        if "R" in xy or "C" in xy:
            i += 1  # the original path follows
        p = os.path.join(root, *[x for x in rel.split("/") if x])
        while True:
            try:
                if now - os.lstat(p).st_mtime > DAY:
                    return True
                break
            except OSError:
                parent = os.path.dirname(p)
                if os.path.normcase(p) == os.path.normcase(root) or parent == p:
                    break
                p = parent
    return False


def store_notice(sr, repo_state, deadline):
    """-> [one note line] or []. A missing store repo says how to get it; one with paths
    uncommitted or commits unpushed for over a day points at /qconfig-sync. Any git failure or
    timeout says nothing: the notice is advisory and never blocks session start. An unreadable
    store repo already has its own note (locate_project), so no git runs against it; nor does any
    git run unless the scan was "ok". Any unexpected error gives no notice."""
    try:
        return _store_notice(sr, repo_state, deadline)
    except Exception:
        return []


def _store_notice(sr, repo_state, deadline):
    root = str(sr.store_repo_root())
    if repo_state == "missing":
        return ["Note: the store repo is missing at %s; clone it (see providers/claude/README.md "
                "§ Store repo on a new machine), then run /qconfig-sync." % root]
    if repo_state != "ok":
        return []
    op = store_operation(sr)
    if op:
        return ["Note: the store repo (%s) has a %s in progress; its memory files may hold conflict markers. "
                "Finish it (/qconfig-sync Step 2b) before writing memory." % (root, op)]
    skipped = ["Note: store repo check skipped (the hook's time cap was spent)."]
    if deadline - time.monotonic() <= 0:
        return skipped
    now = time.time()
    found = []
    out = _store_git(root, ["status", "--porcelain", "-z", "-uall"], deadline)
    if out is None:
        return skipped if deadline - time.monotonic() <= 0 else []
    if _old_uncommitted(root, out, now):
        found.append("paths uncommitted")
    out = _store_git(root, ["log", "@{u}..HEAD", "--format=%ct"], deadline)
    if out is None and deadline - time.monotonic() <= 0:
        return skipped
    times = [int(x) for x in out.decode("ascii", "replace").split() if x.isdigit()] if out else []
    if times and now - min(times) > DAY:
        found.append("commits not pushed")
    if not found:
        return []
    return ["Note: the store repo (%s) holds %s for over a day; run /qconfig-sync."
            % (root, " and ".join(found))]


# --------------------------------------------------------------------------
# Parsing a memory file
# --------------------------------------------------------------------------

def read_file(path):
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    return text[1:] if text.startswith("﻿") else text


def parse_memory(text, me):
    """-> (entries, topics). entries: [(section, heading, body)] for ###
    entries under every ## section except Topics and Declined, plus a
    (section, None, "") placeholder for a section with no entries; topics:
    [(path, trigger)] from the ## Topics table. Parsed by `me`, the
    memory-entries.py module (fence-aware; a "# " line ends the section, so
    a ### after it and before the next ## is not an entry; Topics rows by its
    three-cell rule)."""

    def shown(section):
        name = section.strip()
        return name and name.casefold() not in SKIP_SECTIONS

    entries = [(s.strip(), h, "\n".join(b)) for s, h, b, _n in me.entries(text) if shown(s)]
    if not entries:
        # A section label without entries is listed only for a file that has
        # no ### entries at all (one organized by ## sections alone).
        entries = [(s.strip(), None, "") for s, _n in me.sections(text) if shown(s)]
    return entries, me.topic_rows(text)


# --------------------------------------------------------------------------
# Suspect marks: cited_path_changed, one batched git log per repository
# --------------------------------------------------------------------------

class Marks:
    def __init__(self, dm, deadline):
        self.dm = dm
        self.deadline = deadline
        self.wanted = {}     # git top -> earliest Verified day
        self.checks = []     # (key, top, rel, verified)
        self.status = None   # None | "timeout" | "partial"

    def collect(self, key, body, root):
        if self.dm is None:
            return
        vday = self.dm.verified_day(body)
        if not vday:
            return
        for cited in self.dm.source_paths(body):
            target = os.path.join(root, *[x for x in re.split(r"[\\/]+", cited) if x])
            if not os.path.isfile(target):
                continue
            real = os.path.realpath(target)
            # A cited path that escapes its tier's root (`../x`, a link out)
            # gets no mark: marks resolve against that root only.
            base = os.path.realpath(root)
            try:
                inside = os.path.normcase(os.path.commonpath([real, base])) == \
                    os.path.normcase(base)
            except ValueError:  # different drives
                inside = False
            if not inside:
                continue
            top = git_toplevel(os.path.dirname(real))
            if top is None:
                continue
            rel = os.path.relpath(real, os.path.realpath(top)).replace("\\", "/")
            if rel.startswith("../"):
                continue
            if top not in self.wanted or vday < self.wanted[top]:
                self.wanted[top] = vday
            self.checks.append((key, top, rel.casefold() if IS_WINDOWS else rel, vday))

    def _start(self, top, since):
        """Start one batched `git log` over `top` (one day of slack before
        `since`). A NUL marker opens each commit's date line, so a tracked
        file named like a date is never read as a commit header."""
        start = datetime.date.fromisoformat(since) - datetime.timedelta(days=1)
        return subprocess.Popen(["git", "--no-optional-locks", "-C", top, "-c",
                                 "core.quotePath=false", "log", "--name-only",
                                 "--format=%x00%cs", "--since=%s" % start.isoformat()],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)

    def _no_commits(self, top):
        """True when `top` has no commits yet: `git rev-parse -q --verify HEAD`
        exits 1. Decided by exit code, never by git's (translated) stderr.
        Raises TimeoutExpired past the deadline."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("git", 0)
        r = subprocess.run(["git", "--no-optional-locks", "-C", top, "rev-parse", "-q",
                            "--verify", "HEAD"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=remaining)
        return r.returncode == 1

    def _finish(self, proc, top):
        """-> {path key: newest commit date}, or None when git failed.
        A repository with no commits yet has nothing to mark: {}. That is
        checked only after `git log` fails, so a healthy repository pays
        nothing for it. Raises TimeoutExpired past the deadline."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("git", 0)
        out, _err = proc.communicate(timeout=remaining)
        if proc.returncode != 0:
            try:
                return {} if self._no_commits(top) else None
            except OSError:
                return None
        dates, cur = {}, None
        for line in out.decode("utf-8", errors="replace").split("\n"):
            line = line.rstrip("\r")
            if line.startswith("\x00"):
                cur = line[1:]
            elif line and cur:
                k = line.casefold() if IS_WINDOWS else line
                if k not in dates or dates[k] < cur:
                    dates[k] = cur
        return dates

    def resolve(self):
        """-> the set of keys to mark; sets self.status."""
        logs, procs = {}, {}
        if self.deadline <= time.monotonic():
            self.status = "timeout"
            return set()
        # The repositories' logs run side by side: the slowest, not the sum,
        # counts against the time cap.
        for top in sorted(self.wanted):
            try:
                procs[top] = self._start(top, self.wanted[top])
            except OSError:
                logs[top] = None
        results = {}

        def drain(top, proc):
            try:
                results[top] = self._finish(proc, top)
            except subprocess.TimeoutExpired:
                results[top] = "timeout"

        threads = [threading.Thread(target=drain, args=(t, p), daemon=True)
                   for t, p in procs.items()]
        for th in threads:
            th.start()
        for th in threads:
            th.join(max(0.0, self.deadline - time.monotonic()) + 0.5)
        try:
            for top in procs:
                got = results.get(top, "timeout")
                if got == "timeout":
                    raise subprocess.TimeoutExpired("git", TIME_CAP)
                logs[top] = got
        except subprocess.TimeoutExpired:
            for proc in procs.values():
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
            self.status = "timeout"
            return set()
        if any(v is None for v in logs.values()):
            self.status = "partial"
        marked = set()
        for key, top, rel, vday in self.checks:
            last = (logs.get(top) or {}).get(rel)
            if last and last > vday:
                marked.add(key)
        return marked


# --------------------------------------------------------------------------
# Building the context string
# --------------------------------------------------------------------------

def index_lines(entries, tier, marked):
    out, section = [], None
    for i, (sec, heading, _body) in enumerate(entries):
        if sec != section:
            out.append((False, "%s:" % sec))
            section = sec
        if heading is not None:
            out.append((True, "- %s%s" % (heading, " " + MARK if (tier, i) in marked else "")))
    return out


def _len(lines):
    return len("\n".join(lines))


def trim(fixed_before, block, fixed_after, cap, path):
    """Drop whole droppable lines from the end of `block` until everything
    fits under `cap`, then add one `(+N more -- see <path>)` line."""
    lines = list(block)
    dropped = 0
    while True:
        tail = ["(+%d more — see %s)" % (dropped, path)] if dropped else []
        body = [t for _, t in lines] + tail
        if _len(fixed_before + body + fixed_after) < cap:
            return body
        idx = max((i for i, (d, _) in enumerate(lines) if d), default=None)
        if idx is None:
            return body
        del lines[idx]
        # A section label left with no entry under it says nothing.
        if idx > 0 and idx == len(lines) and not lines[idx - 1][0]:
            del lines[idx - 1]
        dropped += 1


def read_tier(path):
    """-> (text or None, problem or None)."""
    if not os.path.exists(path):
        return None, "not present"
    try:
        return read_file(path), None
    except OSError as e:
        return None, "could not be read (%s); read it yourself" % type(e).__name__


def build(cwd, config_repo, cap=DEFAULT_CAP, deadline=None, helpers=None):
    sr, me, dm = helpers if helpers is not None else load_helpers(config_repo)
    deadline = deadline if deadline is not None else START + TIME_CAP
    marks = Marks(None if isinstance(dm, Exception) else dm, deadline)
    user_path = os.path.join(config_repo, "memory", "MEMORY.md")
    ho_path = os.path.join(config_repo, "memory", "HIGHER_ORDER.md")

    tiers = {}
    for tier, path in (("user", user_path), ("higher-order", ho_path)):
        text, problem = read_tier(path)
        entries, topics = parse_memory(text, me) if text is not None else ([], [])
        tiers[tier] = (path, problem, entries, topics)
        for i, (_s, heading, body) in enumerate(entries):
            if heading is not None:
                marks.collect((tier, i), body, config_repo)

    try:
        if isinstance(sr, Exception):
            raise sr
        root, proj_path, notes, repo_state, info = locate_project(config_repo, cwd, sr)
    except Exception as e:  # noqa: BLE001 -- the user and higher-order index still go out
        root, proj_path, repo_state, info = None, None, "unknown", {}
        notes = ["Note: the project tier could not be located (%s: %s); read it yourself per "
                 "shared/skills/qdream/memory-rules.md § Resolution contract."
                 % (type(e).__name__, " ".join(str(e).split())[:200])]
    proj_text, proj_problem, proj_entries = None, None, []
    index_only = bool(info.get("fallback"))
    if proj_path is not None:
        proj_text, proj_problem = read_tier(proj_path)
        if proj_text is not None and info.get("store") is not None:
            op = store_operation(sr)
            if op or has_conflict_markers(proj_text):
                index_only = True
                if not op:
                    notes.append("Note: %s holds git conflict markers; only its heading index is shown. "
                                 "Resolve them before relying on it." % proj_path)
        if proj_text is not None:
            proj_entries = parse_memory(proj_text, me)[0]
            for i, (_s, heading, body) in enumerate(proj_entries):
                if heading is not None:
                    marks.collect(("project", i), body, root)

    # User memory lives in the store repo's user/memory/, behind the config repo's `memory` link (shared/AGENTS.md
    # § Config Repo Locations): say so loudly when the link is missing, and give it the store-repo guard.
    mem_dir = os.path.join(config_repo, "memory")
    if not os.path.isdir(mem_dir):
        notes.append("Note: no user memory at %s: run the playbook setup to link it to the store repo's "
                     "user/memory/ (shared/AGENTS.md § Config Repo Locations)." % mem_dir)
    elif os.path.islink(mem_dir) and not isinstance(sr, Exception):
        op = store_operation(sr)
        conflicted = [tiers[t][0] for t in ("user", "higher-order")
                      if tiers[t][1] is None and has_conflict_markers(read_tier(tiers[t][0])[0] or "")]
        if op:
            notes.append("Note: user memory sits in the store repo, which has a %s in progress; its files may "
                         "hold conflict markers. Finish it (/qconfig-sync Step 2b) before writing memory." % op)
        for path in conflicted:
            notes.append("Note: %s holds git conflict markers. Resolve them before relying on it." % path)

    marked = marks.resolve() if marks.checks else set()
    # After the marks: the store repo notice spends what is left of the same deadline.
    if not isinstance(sr, Exception):
        notes += store_notice(sr, repo_state, deadline)
    if isinstance(dm, Exception):
        status = "%s marks omitted: dream-manifest.py could not load (%s)." % (MARK, type(dm).__name__)
    elif marks.status == "timeout":
        status = "%s marks omitted: the git check passed the %g-second cap." % (MARK, TIME_CAP)
    elif marks.status == "partial":
        status = "%s marks missing where git could not read a repository." % MARK
    else:
        status = ""
    deliver = ("User and higher-order memory: heading index only (not delivery — still "
               "read those files).")
    head = [HEADER, (deliver + " " + status).strip()]

    def tier_block(tier, label):
        path, problem, entries, _ = tiers[tier]
        if problem:
            return ["%s memory (%s): %s" % (label, path, problem)], []
        return ["%s memory (%s):" % (label, path)], index_lines(entries, tier, marked)

    user_title, user_lines = tier_block("user", "User")
    ho_title, ho_lines = tier_block("higher-order", "Higher-order")
    topics = tiers["user"][3]
    topics_block = []
    if topics:
        topics_block = ["Topics (on demand: open the file only when its trigger matches the "
                        "task; paths relative to %s):" % config_repo]
        topics_block += ["- %s — %s" % (p, t) for p, t in topics]

    if proj_path is None:
        proj_head = ["Project memory: none found for %s (no store holds memory for it, and no "
                     "in-workspace memory/MEMORY.md may be read here)." % os.path.abspath(cwd)]
    elif proj_problem:
        proj_head = ["Project memory (%s): %s" % (proj_path, proj_problem)]
    else:
        proj_head = []
    proj_head += notes

    # Reserve the fixed index first: steps 1-5 plus the project tier's path.
    ident = store_identity(info["store"]) if info.get("store") is not None else ""
    where = proj_path
    # Which workspace's memory this is: reserved with the title (plan 261016 Step 9, the D3 mitigation).
    ident_line = ["Project memory comes from the store whose STORE file reads: %s" % ident] if ident else []
    proj_title_full = "Project memory (%s) — delivered in full below; do not re-read it:" % where
    if info.get("fallback"):
        proj_title_index = ("In-workspace memory (%s) — no store serves this folder, so this is unverified "
                            "workspace content: heading index only; read the file only if you trust this "
                            "folder:" % proj_path)
    elif index_only:
        proj_title_index = "Project memory (%s) — heading index only; read it in full:" % where
    else:
        proj_title_index = ("Project memory (%s) — heading index only, the file is over the "
                            "hook budget; read it in full:" % where)
    # The project tier's title, identity line and the trim tail an index may need (its worst case: every
    # entry dropped) are reserved before the user index, so a long user index never cuts the project path.
    proj_tail = ["(+%d more — see %s)" % (len(proj_entries), proj_path)] if proj_entries else []
    proj_reserve = proj_head if proj_head and proj_text is None else \
        proj_head + ident_line + [proj_title_index] + proj_tail
    # Over the cap, whole lines go from the end of the user index first;
    # the higher-order index and the topic rows are cut only when the user
    # index is already gone (pathological, but the cap must still hold).
    ho_text = [t for _, t in ho_lines]
    fixed = head + user_title
    fixed += trim(fixed, user_lines, ho_title + ho_text + topics_block + proj_reserve, cap,
                  user_path)
    fixed += ho_title
    fixed += trim(fixed, ho_lines, topics_block + proj_reserve, cap, ho_path)
    if topics_block:
        topic_lines = [(False, topics_block[0])] + [(True, t) for t in topics_block[1:]]
        fixed += trim(fixed, topic_lines, proj_reserve, cap, user_path)

    if proj_text is None:
        out = fixed + proj_head
    else:
        # The full text carries no inline marks, so list the marked headings
        # once before it; the line counts against the same budget.
        flagged = [h for i, (_s, h, _b) in enumerate(proj_entries)
                   if h is not None and ("project", i) in marked]
        mark_line = ["%s in project tier: %s" % (MARK, "; ".join(flagged))] if flagged else []
        body = [proj_title_full] + mark_line + [proj_text.rstrip("\n"), "(end of project memory)"]
        full = fixed + proj_head + ident_line + body
        if _len(full) >= cap:
            full = fixed + proj_head + body  # the identity line only when the budget allows
        if _len(full) < cap and not index_only:
            out = full
        else:
            pidx = index_lines(proj_entries, "project", marked)
            if info.get("fallback"):
                # unverified workspace content: each line bounded, so one file cannot fill the context
                pidx = [(d, x if len(x) <= FALLBACK_LINE_MAX else x[:FALLBACK_LINE_MAX] + "…") for d, x in pidx]
            lead = fixed + proj_head + ident_line + [proj_title_index]
            out = lead + trim(lead, pidx, [], cap, proj_path)
    # Last resort: whole lines go from the end of the indexes above the project tier first (its title, path
    # and identity must survive), then from the very end.
    proj_start, cut = len(fixed), False
    while _len(out) >= cap and proj_start > 2:
        del out[proj_start - 1]
        proj_start -= 1
        if not cut:
            out.insert(proj_start, "(index cut at the %d-character cap)" % cap)
            cut = True
    while _len(out) >= cap and len(out) > 2:
        out = out[:-2] + ["(output cut at the %d-character cap)" % cap]
    return "\n".join(out)


def emit(text):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                        "additionalContext": text}}))
    sys.stdout.write("\n")
    sys.stdout.flush()


def notice(err):
    msg = str(err).replace("\n", " ").strip()[:300]
    return ("Playbook memory hook failed open (%s: %s); read the memory tiers yourself per "
            "shared/AGENTS.md § Read-time behavior." % (type(err).__name__, msg))


# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------

def _rmtree(path):
    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def _subst(value, root):
    if isinstance(value, str):
        return value.replace("{{ROOT}}", root)
    if isinstance(value, list):
        return [_subst(v, root) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, root) for k, v in value.items()}
    return value


def _git_init(folder, date, commit=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    cmds = [["init", "-q"]] + ([["add", "-A"], ["commit", "-q", "-m", "fixture"]] if commit else [])
    for cmd in cmds:
        r = subprocess.run(["git", "-C", folder] + cmd, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            return False
    return True


def _store_git_fixture(store_root, scratch, mode):
    """Make `store_root` a git repository committed two days ago and pushed to a bare upstream, then
    put it in `mode`: clean, old-uncommitted (a new file modified two days ago), fresh-uncommitted
    (a new file modified now), old-unpushed (a second commit two days ago, not pushed) or
    fresh-unpushed (a second commit made now, not pushed)."""
    old = time.time() - 2 * DAY
    date = "%d +0000" % int(old)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    bare = os.path.join(scratch, "upstream.git")

    def git(*args, cwd=store_root):
        return subprocess.run(["git", "-C", cwd] + list(args), env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0

    ok = (git("init", "-q", "--bare", bare, cwd=scratch) and git("init", "-q") and git("add", "-A")
          and git("commit", "-q", "-m", "fixture") and git("remote", "add", "origin", bare)
          and git("push", "-q", "-u", "origin", "HEAD"))
    if not ok:
        return False
    if mode in ("old-uncommitted", "fresh-uncommitted"):
        extra = os.path.join(store_root, "proj-jjjjjj", "memory", "new.md")
        with open(extra, "w", encoding="utf-8") as fh:
            fh.write("# New\n")
        if mode == "old-uncommitted":
            os.utime(extra, (old, old))
    elif mode in ("old-unpushed", "fresh-unpushed"):
        with open(os.path.join(store_root, "proj-jjjjjj", "memory", "new.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# New\n")
        if mode == "fresh-unpushed":
            # Committed now: the notice reads the committer time (%ct), so both dates are now.
            now = "%d +0000" % int(time.time())
            env.update(GIT_AUTHOR_DATE=now, GIT_COMMITTER_DATE=now)
        return git("add", "-A") and git("commit", "-q", "-m", "unpushed")
    return True


def _known_lines(tree, me):
    """Every whole index line the fixture tree can produce."""
    known = set()
    for dirpath, _dirs, files in os.walk(tree):
        for f in files:
            if not f.endswith(".md"):
                continue
            try:
                text = read_file(os.path.join(dirpath, f))
            except OSError:
                continue
            entries, topics = parse_memory(text, me)
            for sec, heading, _ in entries:
                known.add("%s:" % sec)
                if heading is not None:
                    known.add("- %s" % heading)
                    known.add("- %s %s" % (heading, MARK))
            for p, t in topics:
                known.add("- %s — %s" % (p, t))
    return known


def _run_case(case_dir, helpers):
    with open(os.path.join(case_dir, "case.json"), encoding="utf-8") as fh:
        case = json.load(fh)
    fails = []
    saved_stores = os.environ.get("AGENT_PLAYBOOK_STORES", "")
    scratch = tempfile.mkdtemp(prefix="memory load hook ")
    try:
        root = os.path.join(scratch, "fixture root")
        shutil.copytree(os.path.join(case_dir, "tree"), root)
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f == "STORE":
                    # A store-repo store; its `local <path>` line is written with forward slashes,
                    # as the resolver normalizes a STORE identity.
                    p = os.path.join(dirpath, f)
                    with open(p, encoding="utf-8") as fh:
                        data = fh.read()
                    with open(p, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(_subst(data, os.path.realpath(root).replace("\\", "/")))
        for ln in case.get("link", []):
            # a directory symlink, as setup links the config repo's `memory` to the store repo's user/memory
            try:
                os.symlink(os.path.join(root, ln["src"]), os.path.join(root, ln["dst"]), target_is_directory=True)
            except (OSError, NotImplementedError):
                return ["SKIP: no symlink could be made"]
        if case.get("store_repo"):
            # The case's store repo root (a directory of the tree holding STORE directories) becomes a
            # store repo by a `.git` folder made here (a fixture tree cannot commit a nested `.git`).
            store_root = os.path.join(root, case["store_repo"])
            if case.get("store_git"):
                # A real git store repo with an upstream, in the state the case names.
                if not _store_git_fixture(store_root, scratch, case["store_git"]):
                    return ["SKIP: git could not create the fixture store repo"]
            else:
                os.makedirs(os.path.join(store_root, ".git"), exist_ok=True)
            os.environ["AGENT_PLAYBOOK_STORES"] = store_root
            if case.get("store_op"):
                # git's in-progress marker (rebase-merge, MERGE_HEAD, ...) in the store repo's .git
                marker = os.path.join(store_root, ".git", case["store_op"])
                if case["store_op"].endswith("_HEAD"):
                    open(marker, "w").close()
                else:
                    os.makedirs(marker, exist_ok=True)
            for rel in case.get("unreadable_store", []):
                # A STORE that is a directory cannot be read as a file: the whole scan is `failed`
                # (a fixture tree cannot hold an empty directory, so it is made here).
                os.makedirs(os.path.join(store_root, rel, "STORE"), exist_ok=True)
        if case.get("store_repo_missing"):
            os.environ["AGENT_PLAYBOOK_STORES"] = os.path.join(root, "no-store-repo")
        for rel in case.get("git", []):
            if not _git_init(os.path.join(root, rel), case.get("git_date", "2026-09-15T12:00:00")):
                return ["SKIP: git could not create the fixture repository"]
        for rel in case.get("git_no_commits", []):
            if not _git_init(os.path.join(root, rel), "", commit=False):
                return ["SKIP: git could not create the fixture repository"]
        case = _subst(case, root)
        cap = case.get("cap", DEFAULT_CAP)
        if "stdin" in case:
            # The real entry point, as Claude Code runs it: a subprocess fed
            # the case's stdin. The hook finds its config repo from its own
            # real path, so a copy of this file (and the qdream helper
            # scripts it loads, the store resolver included) is placed in the fixture's config repo: the
            # copy reads the fixture's memory, never this repo's. No seam in
            # the production code path.
            live_repo = config_repo_of_script()
            cfg = case["config_repo"]
            hook_dir = os.path.join(cfg, "providers", "claude")
            helper_dir = os.path.join(cfg, "shared", "skills", "qdream", "scripts")
            os.makedirs(hook_dir)
            os.makedirs(helper_dir)
            hook_copy = os.path.join(hook_dir, "memory-load-hook.py")
            shutil.copyfile(os.path.realpath(__file__), hook_copy)
            for helper in ("qmemory-eval.py", "dream-manifest.py", "store-resolver.py",
                           "memory-entries.py"):
                shutil.copyfile(os.path.join(live_repo, "shared", "skills", "qdream", "scripts",
                                             helper), os.path.join(helper_dir, helper))
            r = subprocess.run([sys.executable, hook_copy],
                               input=case["stdin"].encode("utf-8"), cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if r.returncode != 0:
                fails.append("exit code %d, not 0" % r.returncode)
            try:
                out = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"][
                    "additionalContext"]
            except (ValueError, KeyError, TypeError) as e:
                return fails + ["stdout is not the hook JSON (%s): %r" % (e, r.stdout[:300])]
            # Isolation: the output must name the fixture's memory file (unless
            # the hook failed open before reading it) and never the live repo.
            seen = out.replace("\\", "/").casefold()
            if live_repo.replace("\\", "/").casefold() in seen:
                fails.append("output names the live config repo %s" % live_repo)
            fixture_memory = os.path.realpath(
                os.path.join(cfg, "memory", "MEMORY.md")).replace("\\", "/")
            if not out.startswith("Playbook memory hook failed open") and \
                    fixture_memory.casefold() not in seen:
                fails.append("output does not name the fixture memory file %s" % fixture_memory)
        else:
            deadline = time.monotonic() + case.get("time_cap", TIME_CAP)
            fake = case.get("fake_git_log")
            real_start = Marks._start
            if fake:
                # Stand in for `git log` with a process that fails with the
                # case's stderr and exit code (a localized git, say).
                code = ("import sys; sys.stderr.write(%r); sys.exit(%d)"
                        % (fake["stderr"], fake["code"]))
                Marks._start = lambda self, top, since: subprocess.Popen(
                    [sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # The resolver's own test seam: the fixture's cfg is the config repo (the real one is
            # known by its shared/ files, which a fixture tree does not carry), and `would_create`
            # makes the scratch folder a normal one by naming no system temp directory.
            sr = helpers[0]
            saved_test = dict(sr._TEST)
            sr._TEST["config_repo"] = case["config_repo"]
            if case.get("would_create"):
                sr._TEST["temp"] = []
            use = list(helpers)
            if "broken_helper" in case:
                use[case["broken_helper"]] = RuntimeError("fixture: this helper could not load")
            try:
                out = build(os.path.normpath(case["cwd"]), os.path.normpath(case["config_repo"]),
                            cap, deadline, tuple(use))
            except Exception as e:  # the hook's main() would fail open; a case must not
                return ["build raised %s: %s" % (type(e).__name__, e)]
            finally:
                Marks._start = real_start
                sr._TEST.clear()
                sr._TEST.update(saved_test)
        flat = out.replace("\\", "/")
        if len(out) >= cap:
            fails.append("output is %d characters, not under the %d cap" % (len(out), cap))
        for s in case.get("contains", []):
            if s.replace("\\", "/") not in flat:
                fails.append("missing: %r" % s)
        for s in case.get("absent", []):
            if s.replace("\\", "/") in flat:
                fails.append("unexpected: %r" % s)
        for pat in case.get("regex", []):
            if not re.search(pat, flat, re.M):
                fails.append("no match for /%s/" % pat)
        if case.get("whole_lines"):
            known = _known_lines(root, helpers[1])
            body = out.split("(end of project memory)")[-1] if "delivered in full" in out \
                else out
            for line in body.split("\n"):
                if (line.startswith("- ") or line.endswith(":") and not line.startswith(
                        ("User", "Higher", "Topics", "Project"))) and line not in known:
                    fails.append("index line is not a whole heading: %r" % line)
        if fails:
            fails.append("output was:\n" + out)
    finally:
        _rmtree(scratch)
        os.environ["AGENT_PLAYBOOK_STORES"] = saved_stores
    return fails


def selftest():
    fixdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "fixtures",
                          "memory-load-hook")
    names = sorted(d for d in os.listdir(fixdir)
                   if os.path.isfile(os.path.join(fixdir, d, "case.json"))) \
        if os.path.isdir(fixdir) else []
    if not names:
        print("FAIL: no fixtures under %s" % fixdir)
        return 1
    # Fixtures never see the live store repo: the default is an empty store repo whose `.git` is
    # an empty folder, so the resolver finds no store and the store notice's git calls fail (no
    # notice); the stdin-mode cases inherit this through the environment.
    iso = tempfile.mkdtemp(prefix="memory load hook iso ")
    os.makedirs(os.path.join(iso, "stores", ".git"))
    os.environ["AGENT_PLAYBOOK_STORES"] = os.path.join(iso, "stores")
    try:
        return _selftest_cases(fixdir, names)
    finally:
        _rmtree(iso)


def _selftest_cases(fixdir, names):
    helpers = load_helpers(config_repo_of_script())
    failed = 0
    for name in names:
        try:
            fails = _run_case(os.path.join(fixdir, name), helpers)
        except Exception as e:  # one broken case never stops the run
            fails = ["case raised %s: %s" % (type(e).__name__, e)]
        if fails and all(f.startswith("SKIP:") for f in fails):
            print("SKIP %s: %s" % (name, fails[0][5:].strip()))
        elif fails:
            failed += 1
            print("FAIL %s" % name)
            for f in fails:
                print("  - %s" % f)
        else:
            print("PASS %s" % name)
    print("selftest: %d case(s), %d failed" % (len(names), failed))
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Claude Code SessionStart memory hook.")
    ap.add_argument("--selftest", action="store_true", help="run the fixtures and exit")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP,
                    help="character cap of the injected context (default %d)" % DEFAULT_CAP)
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace") \
            if sys.stdin is not None else ""
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:  # unreadable input: still emit the index, for os.getcwd()
            data = {}
        cwd = data.get("cwd") if isinstance(data, dict) else None
        text = build(cwd or os.getcwd(), config_repo_of_script(), args.cap)
    except Exception as e:  # fail open: never block or break session start
        text = notice(e)
    emit(text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: B902 -- last-resort fail open
        try:
            emit(notice(e))
        finally:
            sys.exit(0)
