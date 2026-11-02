#!/usr/bin/env python3
"""verify-stores.py -- deterministic guard for the workspace store layout.

The store repo's guard since plan 261016 (it took over from the old in-repo workspaces/ check). Python
only, no sh/ps1 twin, so it is outside test-parity.sh's tally. Run with the playbook venv
(<repo>/.venv-agent-playbook); any other interpreter exits 2 ("guard did not run: venv missing"). Stdlib
only, Python 3.8+. It reads the store repo, .dream-state.json and the session stores' cwd metadata; it
writes nothing, runs only read-only git (status, log, rev-parse) and touches no network.

Usage:
  verify-stores.py [<repo>] [--stores DIR] [--state FILE] [--claude-projects DIR]
                   [--kiro-sessions DIR]
  verify-stores.py --selftest

  <repo>   The config repo (default: the current directory); it must hold shared/AGENTS.md.
  --stores DIR     The store repo (default: AGENT_PLAYBOOK_STORES, else stores= in
                   ~/.agent-playbook/config, else ~/.agent-playbook/stores).
  --state FILE     The sweep state (default: <repo>/memory/.dream-state.json).
  --claude-projects DIR / --kiro-sessions DIR
                   Where session cwds are read (default: ~/.claude/projects, ~/.kiro/sessions).

Store-repo FAIL checks (exit 1):
  1. Every non-dot directory of the store repo but the reserved user/ (user-tier memory) holds a valid
     STORE file (scan_stores' verdict); user/ itself holds none.
  2. No two STORE files share one identity (compared with the resolver's same_identity, so case-folded;
     the same remote with a different `path` line is a different identity).
  3. Reserved folder names exist only as SC-2 lists them. The reserved names are memory, plans,
     explanations, artifacts, visualizations (a store's top level) and done, tests (inside plans/ only).
     A FAIL is: a reserved name as a directory at the store repo root; a reserved name inside a store that
     is a file, or is not spelled in lower case; done/ or tests/ directly in a store (they belong in
     plans/); plans/done or plans/tests that is a file.
  4. A STORE value is in the resolver's normalized form: a `local` path as norm_path writes it (forward
     slashes; case does not matter), a `remote` value lower-case with no scheme, credentials or `.git`
     suffix. A hand-edited `local` line with backslashes is valid STORE syntax that the resolver never
     matches.
  5. No tracked file of the config repo, archived plans included, holds a term listed in the store repo's
     BLOCKLIST file (one term per line, `#` comments; matched case-insensitively). The FAIL names the file
     and the BLOCKLIST line number, never the term, so the output can be pasted anywhere. No BLOCKLIST file
     means no check.
Store-repo WARN checks (never change the exit code):
  - a store-repo path uncommitted for over a day (the path's mtime; a deleted path uses its nearest
    existing parent's mtime); commits not pushed for over a day (the oldest unpushed commit; no upstream
    means a skip line); a leftover STORE.tmp-* file;
  - an orphaned store: no .dream-state.json project path and no session cwd (Claude Code, Kiro) modified in
    the last 90 days resolves to it through the resolver's find (which walks from the folder up to the
    repo toplevel, so a session in a subfolder of the store's repo counts); for a `local` store, also when
    its path no longer exists. A `store:<identity>` state key counts as a reference;
  - a git rebase, merge or cherry-pick stopped in the store repo (its memory files may hold conflict markers);
  - the store repo's origin is not the `stores_url=` of the pointer file (~/.agent-playbook/config, which
    setup writes; client content would be pushed somewhere else); no stores_url, or no origin, is a SKIP line;
  - a Kiro .kiro/steering/__store_memory__.md that is not a symlink, or whose target is not the memory
    file of the store serving that folder (resolve_artifact's store); and the reverse, a wired workspace (a
    .kiro/steering/__store__.md pointer naming a store) whose store already holds memory/MEMORY.md but has no
    __store_memory__.md link, so Kiro sessions do not auto-load that memory;
  - an unwired workspace: a Kiro session cwd modified in the last 90 days resolves to a store, but the folder
    that store serves (a `local` path, or the repo toplevel joined with its `path` subpath) has no
    .kiro/steering/__store__.md, so /qwire-governance never ran there and Kiro sessions get no project memory.
    The home directory is exempt (/qwire-governance refuses to wire it);
  - memory/ or plans/ left in a workspace .dream-state.json names (its content belongs in the workspace's
    store), and in the argument repo. Exempt: a config repo's memory/ (by its markers; the user tier, behind
    its link) but never its plans/, which live in its store; and a no-create folder (the resolver's
    would_create_path is none), which keeps its memory in place.

Output: "ok:", "FAIL:", "WARN:", "SKIP:" lines; the last line is "verify-stores: ok=N fail=M warn=K"
(an orphaned store is a WARN line). Exit 0 (no FAIL), 1 (a FAIL), 2 (the guard could not run: venv missing,
repo or store repo unusable, the scan failed).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(os.path.realpath(__file__)).parent
SKILLS = HERE.parents[1]  # scripts -> qconfig-sync -> skills
QDREAM_SCRIPTS = SKILLS / "qdream" / "scripts"
DAY = 86400.0
ORPHAN_DAYS = 90
RESERVED_STORE_DIRS = ("memory", "plans", "explanations", "artifacts", "visualizations")
RESERVED_PLAN_DIRS = ("done", "tests")
ASCII_WS = " \t\r\n\v\f"


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
    """The guard cannot give a verdict (exit 2); the text names the next action."""


# Selftest only: copied into each loaded resolver's _TEST overrides (its temp roots, for the no-create cases).
RESOLVER_TEST: dict = {}


def load_resolver():
    path = QDREAM_SCRIPTS / "store-resolver.py"
    try:
        spec = importlib.util.spec_from_file_location("store_resolver", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise CouldNotRun("cannot load %s (%s: %s)" % (path, type(exc).__name__, exc))
    mod._TEST.update(RESOLVER_TEST)
    return mod


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.lines = []
        self.ok = self.fail = self.warn = 0

    def add(self, text):
        self.lines.append(text)

    def good(self, text):
        self.ok += 1
        self.add("ok: " + text)

    def bad(self, text):
        self.fail += 1
        self.add("FAIL: " + text)

    def warning(self, text):
        self.warn += 1
        self.add("WARN: " + text)


def _norm(p):
    return os.path.normcase(os.path.realpath(str(p)))


def _git(cwd, args):
    """(returncode, stdout bytes) of a read-only git call, or (None, b'') when git cannot run."""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        r = subprocess.run(["git", "-C", str(cwd)] + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=120, env=env)
    except (OSError, subprocess.SubprocessError):
        return None, b""
    return r.returncode, r.stdout


def _human(seconds):
    if seconds >= DAY:
        return "%.1f days" % (seconds / DAY)
    return "%.1f hours" % (seconds / 3600.0)


def ident_text(i):
    return "%s %s" % (i.kind, i.value) + ((" path " + i.subpath) if i.subpath else "")


# ---------------------------------------------------------------------------
# Store repo checks
# ---------------------------------------------------------------------------

def layout_problems(sdir, name):
    """(fails, warns) for one store-repo child directory's folder names."""
    fails, warns = [], []
    if name.casefold() in RESERVED_STORE_DIRS + RESERVED_PLAN_DIRS:
        fails.append("reserved folder name at the store repo root -- move it into a store directory "
                     "(stores are flat <name>-<hex> folders) or delete it")
    try:
        children = sorted(os.listdir(str(sdir)))
    except OSError as exc:
        return fails + ["cannot list the directory: %s" % exc], warns
    for c in children:
        p = sdir / c
        low = c.casefold()
        if c.startswith("STORE.tmp-"):
            warns.append("leftover %s -- delete it (a creation's temp file; the resolver never reads it)" % c)
            continue
        if low in RESERVED_STORE_DIRS:
            if c != low:
                fails.append("%s must be spelled %s -- rename it" % (c, low))
            if not p.is_dir():
                fails.append("%s is a file, not a folder -- rename or remove it" % c)
        elif low in RESERVED_PLAN_DIRS and p.is_dir():
            fails.append("%s/ sits directly in the store; it belongs in plans/%s -- move it" % (c, low))
    plans = sdir / "plans"
    if plans.is_dir():
        for sub in RESERVED_PLAN_DIRS:
            q = plans / sub
            if os.path.lexists(str(q)) and not q.is_dir():
                fails.append("plans/%s is a file, not a folder -- rename or remove it" % sub)
    return fails, warns


def git_operation(root):
    """The git operation stopped in `root` ("rebase", "merge", "cherry-pick"), or '' (from .git's marker files)."""
    g = Path(root) / ".git"
    for marker, name in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"),
                         ("CHERRY_PICK_HEAD", "cherry-pick")):
        if os.path.lexists(str(g / marker)):
            return name
    return ""




def origin_check(R, root, repo, rep):
    """WARN when the store repo's origin is not the `stores_url=` setup recorded in the pointer file
    (shared/AGENTS.md § Config Repo Locations): the URL the store repo was cloned from or made for."""
    cfg, _problems = R.read_config()
    want = cfg.get("stores_url", "")
    if not want:
        rep.add("SKIP: stores-repo origin  no stores_url= in %s" % R.config_path())
        return
    rc, out = _git(root, ["remote", "get-url", "--push", "origin"])
    if rc is None:
        rep.add("SKIP: stores-repo origin  git cannot run")
        return
    if rc != 0:
        rep.add("SKIP: stores-repo origin  no origin remote")
        return
    got = out.decode("utf-8", "replace").strip()
    want_n, got_n = R.normalize_remote(want), R.normalize_remote(got)
    if got_n is None or got_n != want_n:
        rep.warning("stores-repo  origin's push URL is %s, not the pointer file's stores_url %s -- check where /qconfig-sync pushes the "
                    "store repo (it holds client content) before the next push"
                    % ("not a recognisable remote URL" if got_n is None else got_n, want_n))


def blocklist_terms(root):
    """[(line number, term)] of the store repo's BLOCKLIST, or [] when there is none or it cannot be read."""
    try:
        lines = (Path(root) / "BLOCKLIST").read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    return [(n, x.strip()) for n, x in enumerate(lines, 1) if x.strip() and not x.strip().startswith("#")]


def mask_terms(line, root, _cache={}):
    """`line` with each BLOCKLIST term replaced by `<BLOCKLIST n>`, case-insensitively."""
    key = str(root)
    if key not in _cache:
        _cache.clear()
        _cache[key] = [(n, re.compile(re.escape(t), re.I)) for n, t in blocklist_terms(root)]
    for n, rx in _cache[key]:
        line = rx.sub("<BLOCKLIST %d>" % n, line)
    return line


def blocklist_check(root, repo, rep):
    """FAIL for each tracked config-repo file holding a BLOCKLIST term (named by BLOCKLIST line, never by term).
    Archived plans are checked too: they are as readable as any other file, and this plan's own archive lands
    there."""
    bl = Path(root) / "BLOCKLIST"
    if not bl.is_file():
        return
    try:
        lines = bl.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotRun("cannot read %s: %s" % (bl, exc))
    terms = [(n, x.strip()) for n, x in enumerate(lines, 1) if x.strip() and not x.strip().startswith("#")]
    for n, term in terms:
        rc, out = _git(repo, ["-c", "core.quotepath=off", "grep", "-l", "-I", "-i", "-F", "-e", term, "--", "."])
        if rc is None:
            raise CouldNotRun("git cannot run for the BLOCKLIST check")
        if rc not in (0, 1):
            raise CouldNotRun("git grep failed in %s for the BLOCKLIST check" % repo)
        mask = re.compile(re.escape(term), re.I)
        named = set()
        for path in out.decode("utf-8", "replace").splitlines():
            if path.strip():
                named.add(path.strip())
                rep.bad("config-repo %s  holds the term on line %d of the store repo's BLOCKLIST -- replace it "
                        "with a neutral placeholder" % (mask.sub("<BLOCKLIST %d>" % n, path.strip()), n))
        rc, names = _git(repo, ["-c", "core.quotepath=off", "ls-files", "-z"])
        if rc != 0:
            raise CouldNotRun("git ls-files failed in %s for the BLOCKLIST check" % repo)
        for path in names.decode("utf-8", "replace").split("\0"):
            if path and path not in named and mask.search(path):
                rep.bad("config-repo %s  is a file name holding the term on line %d of the store repo's BLOCKLIST "
                        "-- rename it" % (mask.sub("<BLOCKLIST %d>" % n, path), n))


def store_value_problem(R, ident):
    """Why a valid STORE value is not in the resolver's normalized form, or ''."""
    v = ident.value
    if ident.kind == "local":
        if v.casefold() != R.norm_path(v).casefold():
            return ("`local` value is not in normalized form (%s) -- the resolver never matches it; rewrite the "
                    "line as `local %s`" % (v, R.norm_path(v)))
    elif ident.kind == "remote":
        norm = R.normalize_remote("https://" + v) if "://" not in v and "@" not in v and "\\" not in v else None
        if norm != v:
            return ("`remote` value is not in normalized form (%s) -- the resolver never matches it; write it as "
                    "the resolver's identity prints it%s" % (v, (" (%s)" % norm) if norm else ""))
    return ""


def uncommitted_and_unpushed(root, rep, now):
    rc, out = _git(root, ["status", "--porcelain", "-z", "-uall"])
    if rc is None:
        rep.add("SKIP: stores-repo commit state  git cannot run")
        return
    if rc != 0:
        rep.add("SKIP: stores-repo commit state  git status failed in %s" % root)
        return
    toks = out.split(b"\0")
    old = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, rel = tok[:2].decode("ascii", "replace"), tok[3:].decode("utf-8", "replace")
        if "R" in xy or "C" in xy:
            i += 1  # the original path follows
        p = Path(root) / rel
        age = None
        while True:
            try:
                age = now - os.lstat(str(p)).st_mtime
                break
            except OSError:
                if p == Path(root) or p.parent == p:
                    break
                p = p.parent
        if age is not None and age > DAY:
            old.append((rel, age))
    shown = 20
    for rel, age in old[:shown]:
        rep.warning("stores-repo  uncommitted for over a day (%s): %s -- run /qconfig-sync Step 2b to commit it" % (_human(age), rel))
    if len(old) > shown:
        rep.warning("stores-repo  %d more paths uncommitted for over a day (%d in all; the first %d are listed)"
                    % (len(old) - shown, len(old), shown))
    op = git_operation(root)
    if op:
        rep.warning("stores-repo  a git %s is in progress -- finish it (/qconfig-sync Step 2b) before any sweep or "
                    "memory write; until then the push state cannot be read" % op)
        return
    rc, branch = _git(root, ["symbolic-ref", "-q", "HEAD"])
    if rc is None:
        rep.add("SKIP: stores-repo push state  git cannot run")
        return
    if rc != 0:
        rep.add("SKIP: stores-repo push state  HEAD is detached (no branch) -- check it out again in Step 2b")
        return
    rc, up = _git(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if rc != 0:
        rep.add("SKIP: stores-repo push state  no upstream branch")
        return
    rc, out = _git(root, ["log", "@{u}..HEAD", "--format=%ct"])
    if rc != 0:
        rep.add("SKIP: stores-repo push state  git log failed")
        return
    times = [int(x) for x in out.decode("ascii", "replace").split() if x.isdigit()]
    if times:
        age = now - min(times)
        if age > DAY:
            rep.warning("stores-repo  %d commit(s) not pushed, the oldest %s old -- run /qconfig-sync to push" % (len(times), _human(age)))


TOKEN_RE = re.compile(r'(?P<s>"(?:[^"\\]|\\.)*")|(?P<q>")|(?P<p>[{}\[\]:,])')
LINE_PREFIX = 4096  # bytes of one session line that are looked at; the cwd key sits among its first fields
SCAN_BUDGET = 16 << 20  # bytes read from one session file in all, the skipped rest of long lines included


def _top_level_cwd(text):
    """The string value of the TOP-LEVEL `cwd` key in the prefix of one JSON line, else None. Not a JSON parse:
    a small scanner walks the strings and the brackets of the prefix and tracks the nesting depth, so a `cwd`
    inside a nested object or array (message text, tool input) is never taken. String contents are skipped
    undecoded; only the value of the cwd key is decoded. A string cut by the end of the prefix ends the scan."""
    depth = 0
    want_key = False  # at depth 1, a string token is a key
    key = None  # the top-level key just read, waiting for its colon
    cwd_next = False  # the colon after "cwd" was read; the next token is its value
    for m in TOKEN_RE.finditer(text):
        if m.group("q"):
            return None
        if m.group("s"):
            raw = m.group("s")
            if depth == 1 and want_key:
                key, want_key = raw, False
            elif depth == 1 and cwd_next:
                try:
                    value = json.loads(raw)
                except ValueError:
                    value = ""
                if value:
                    return value
                cwd_next = False
            continue
        p = m.group("p")
        cwd_next = False
        if p == ":":
            if depth == 1 and key is not None:
                cwd_next = key == '"cwd"'
            key = None
        elif p == ",":
            key = None
            want_key = depth == 1
        elif p in "{[":
            depth += 1
            key = None
            want_key = p == "{" and depth == 1
        else:
            depth -= 1
            key = None
            want_key = False
            if depth < 1:
                return None
    return None


def _first_cwd(path, limit=100, budget=SCAN_BUDGET):
    """The cwd of a Claude Code session file: the first top-level `cwd` string among the first `limit` lines.
    A line is never parsed as JSON and is looked at for its first LINE_PREFIX bytes only (_top_level_cwd);
    the rest of a long line is skipped in bounded reads, so a long line costs its prefix in the lookup and only
    the skipped bytes in I/O, at most `budget` bytes per file. Only the cwd value is decoded, never message text."""
    seen = 0
    try:
        with open(path, "rb") as fh:
            for _n in range(limit):
                if seen > budget:
                    return None
                head = fh.readline(LINE_PREFIX)
                if not head:
                    return None
                seen += len(head)
                value = _top_level_cwd(head.decode("utf-8", "replace"))
                if value:
                    return value
                rest = head
                while not rest.endswith(b"\n"):
                    if seen > budget:
                        return None
                    rest = fh.readline(1 << 16)
                    if not rest:
                        return None
                    seen += len(rest)
    except OSError:
        pass
    return None


def _listdir(path):
    """Sorted names in `path`; an unreadable directory yields none."""
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def session_cwds(claude_dir, kiro_dir, now, days):
    """Folders of sessions modified in the last `days` days: Claude Code (the cwd of the first records of each
    top-level <slug>/*.jsonl, read by _first_cwd without parsing message lines) and Kiro v3 (session.json
    workspacePaths). A directory that cannot be listed is left out."""
    out = []
    cutoff = now - days * DAY
    if claude_dir and os.path.isdir(claude_dir):
        for slug in _listdir(claude_dir):
            sd = os.path.join(claude_dir, slug)
            if not os.path.isdir(sd):
                continue
            for f in _listdir(sd):
                fp = os.path.join(sd, f)
                if not f.endswith(".jsonl"):
                    continue
                try:
                    if os.path.getmtime(fp) < cutoff:
                        continue
                except OSError:
                    continue
                c = _first_cwd(fp)
                if c:
                    out.append(c)
    out.extend(kiro_session_cwds(kiro_dir, now, days))
    return out


def kiro_session_cwds(kiro_dir, now, days):
    """Folders of Kiro v3 sessions (session.json workspacePaths) modified in the last `days` days."""
    out = []
    cutoff = now - days * DAY
    if kiro_dir and os.path.isdir(kiro_dir):
        for h in _listdir(kiro_dir):
            hd = os.path.join(kiro_dir, h)
            if not os.path.isdir(hd):
                continue
            for s in _listdir(hd):
                sj = os.path.join(hd, s, "session.json")
                try:
                    if not os.path.isfile(sj) or os.path.getmtime(sj) < cutoff:
                        continue
                    with open(sj, "rb") as fh:
                        obj = json.loads(fh.read().decode("utf-8-sig", "replace"))
                except (OSError, ValueError):
                    continue
                paths = obj.get("workspacePaths") if isinstance(obj, dict) else None
                if isinstance(paths, list):
                    out.extend(p for p in paths if isinstance(p, str) and p)
    return out


def load_state(path):
    """(project keys, reason). reason is non-empty when the state could not be read (the orphan check is skipped)."""
    if not path or not os.path.isfile(path):
        return [], "no .dream-state.json at %s" % path
    try:
        with open(path, "rb") as fh:
            obj = json.loads(fh.read().decode("utf-8-sig"))
        projects = obj["projects"]
        if not isinstance(projects, dict):
            raise ValueError("projects is not an object")
    except (OSError, ValueError, KeyError) as exc:
        return [], "cannot read %s (%s: %s)" % (path, type(exc).__name__, exc)
    return [k for k in projects if isinstance(k, str)], ""


def orphan_check(R, valid, rep, state_keys, state_reason, cwds, now):
    if state_reason:
        rep.add("SKIP: orphaned-store check  %s" % state_reason)
        return None
    served, referenced, unresolved = set(), set(), 0
    folders = {}
    for k in state_keys:
        if k.startswith("store:"):
            # looked up by its text: a remote holding " path " makes the key ambiguous to parse
            d = R.store_for_key(k[len("store:"):], valid)
            if d is not None:
                referenced.add(_norm(d))
        else:
            folders.setdefault(os.path.normcase(os.path.abspath(k)), k)
    for c in cwds:
        folders.setdefault(os.path.normcase(os.path.abspath(c)), c)
    for f in folders.values():
        res = R.find(f)
        if res.status == "found":
            served.add(_norm(res.path))
        elif res.status == "failed":
            unresolved += 1
    for d, ident in valid:
        reasons = []
        if _norm(d) not in served and _norm(d) not in referenced:
            reasons.append("no .dream-state.json project path and no session in the last %d days resolves to it -- "
                           "if the work is gone, delete the store directory in the store repo and commit" % ORPHAN_DAYS)
        if ident.kind == "local" and not os.path.exists(ident.value):
            reasons.append("its local path no longer exists (%s) -- move the store with /qmigrate-workspace or delete it"
                           % ident.value)
        if reasons:
            rep.warning("stores/%s  orphaned: %s" % (os.path.basename(str(d)), "; ".join(reasons)))
    if unresolved:
        rep.add("SKIP: %d folder(s) could not be resolved to a store and were left out of the orphan check" % unresolved)


def pointer_store_text(text):
    """The store directory a Kiro `__store__.md` pointer names: the first line that is only one backticked
    path (the template's `<store-path>` line), `~` expanded. None when there is none."""
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip(ASCII_WS)
        if len(line) > 2 and line.startswith("`") and line.endswith("`") and "`" not in line[1:-1]:
            return os.path.expanduser(line[1:-1])
    return None


def pointer_store(path):
    """pointer_store_text of the file at `path`; None when it cannot be read."""
    try:
        with open(path, "rb") as fh:
            return pointer_store_text(fh.read(65536).decode("utf-8-sig", "replace"))
    except OSError:
        return None


def symlink_check(R, folders, rep):
    """A Kiro __store_memory__.md must be a symlink to its store's memory/MEMORY.md. Reverse: a wired workspace
    (a __store__.md pointer naming a store) whose store already holds memory/MEMORY.md but has no link."""
    for f in folders:
        link = os.path.join(f, ".kiro", "steering", "__store_memory__.md")
        if not os.path.lexists(link):
            pointer = os.path.join(f, ".kiro", "steering", "__store__.md")
            named = pointer_store(pointer) if os.path.isfile(pointer) else None
            if named and os.path.isfile(os.path.join(named, "memory", "MEMORY.md")):
                rep.warning("%s  is missing: %s names a store whose memory/MEMORY.md exists, so Kiro sessions do not auto-load "
                            "that memory -- re-run /qwire-governance in %s" % (link, pointer, f))
            continue
        store = R.resolve_artifact(f, "memory").store
        if not os.path.islink(link):
            rep.warning("%s  is not a symlink (a copy does not follow store edits) -- delete it and re-run /qwire-governance" % link)
            continue
        try:
            target = os.readlink(link)
        except OSError as exc:
            rep.warning("%s  cannot be read (%s)" % (link, exc))
            continue
        if target.startswith("\\\\?\\") and not target.upper().startswith("\\\\?\\UNC\\"):
            target = target[4:]
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(link), target)
        if store is None:
            rep.warning("%s  points at %s but no store serves this workspace -- delete the link or re-run /qwire-governance" % (link, target))
            continue
        want = os.path.join(str(store), "memory", "MEMORY.md")
        if _norm(target) != _norm(want):
            rep.warning("%s  points at %s, not at its store's memory %s -- delete it and re-run /qwire-governance" % (link, target, want))


def store_root(ident, folder):
    """The folder a store serves, where /qwire-governance writes its .kiro/steering/ wiring: a `local` store's
    path, or a `remote` store's repo toplevel (taken from `folder`, a folder the store serves) joined with its
    `path` subpath. None when it cannot be told."""
    if ident.kind == "local":
        return ident.value
    rc, top = _git(folder, ["rev-parse", "--show-toplevel"])
    if rc != 0:
        return None
    top = top.decode("utf-8", "replace").strip()
    return os.path.join(top, *ident.subpath.split("/")) if ident.subpath else top


def unwired_check(R, valid, kiro_cwds, rep):
    """A store-backed workspace a recent Kiro session ran in whose root has no .kiro/steering/__store__.md:
    /qwire-governance never wired it, so Kiro sessions there get no project memory and nothing says a store
    exists (the symlink check above only sees workspaces that already hold the pointer). The home directory is
    skipped: /qwire-governance refuses to wire it (its .kiro/steering/ is the global one)."""
    idents = {_norm(d): i for d, i in valid}
    home = _norm(os.path.expanduser("~"))
    seen = set()
    for c in kiro_cwds:
        if not os.path.isdir(c):
            continue
        res = R.find(c)
        if res.status != "found" or _norm(res.path) not in idents:
            continue
        root = store_root(idents[_norm(res.path)], c)
        if not root or not os.path.isdir(root) or _norm(root) == home or _norm(root) in seen:
            continue
        seen.add(_norm(root))
        pointer = os.path.join(root, ".kiro", "steering", "__store__.md")
        if not os.path.lexists(pointer):
            rep.warning("%s  is missing: a Kiro session in the last %d days ran in this store-backed workspace "
                        "(stores/%s), but it was never wired, so Kiro sessions there get no project memory -- "
                        "re-run /qwire-governance in %s" % (pointer, ORPHAN_DAYS, os.path.basename(str(res.path)), root))


CONFIG_REPO_MARKERS = (("shared", "AGENTS.md"), ("shared", "skills", "qdream", "scripts", "store-resolver.py"))


def is_config_repo(folder):
    """True when `folder` is a git toplevel holding the config repo's markers (the resolver's
    _is_config_repo test; the resolver exposes no public form, so it is repeated here)."""
    if not all(os.path.isfile(os.path.join(str(folder), *rel)) for rel in CONFIG_REPO_MARKERS):
        return False
    rc, top = _git(folder, ["rev-parse", "--show-toplevel"])
    return rc == 0 and _norm(top.decode("utf-8", "replace").strip()) == _norm(folder)


def in_workspace_check(R, state_keys, rep, repo):
    """memory/ or plans/ left in a workspace the state names, or in the argument repo. Exempt: a config
    repo's memory/ (the user tier, behind its link) -- never its plans/, which live in its store like any
    workspace's -- and a no-create folder, which keeps its memory in place (memory-rules.md § Resolution
    contract step 3)."""
    cfg = _norm(repo)
    keys = list(state_keys)
    if repo and not any(_norm(k) == cfg for k in keys if not k.startswith("store:")):
        keys.append(str(repo))
    for k in keys:
        if k.startswith("store:") or not os.path.isdir(k):
            continue
        cfg_like = _norm(k) == cfg or is_config_repo(k)
        if not cfg_like and R.would_create_path(k).status == "none":
            continue
        for kind in (("plans",) if cfg_like else ("memory", "plans")):
            d = os.path.join(k, kind)
            if os.path.isdir(d) and R.populated(d):
                rep.warning("%s  holds an in-workspace %s/ after migration -- move it into the workspace's store, then delete it" % (k, kind))


def store_checks(R, root, rep, opts, repo, now):
    st, valid, invalid, why = R.scan_stores(root)
    if st == "failed":
        raise CouldNotRun("the store repo scan failed: %s" % why)
    problems = {}  # directory name -> [fail text]
    udir = Path(root) / R.USER_DIR
    if udir.is_dir():
        # the reserved user/ holds user-tier memory (the config repo's `memory` link points into it)
        if os.path.lexists(str(udir / R.STORE_FILE)):
            rep.bad("stores/%s  holds a STORE file, but %s/ is reserved for user-tier memory and is never a "
                    "store -- move the store to its own <name>-<hex> directory" % (R.USER_DIR, R.USER_DIR))
        else:
            rep.good("stores/%s  user-tier memory (reserved; not a store)" % R.USER_DIR)
    for name in sorted(os.listdir(str(root))):
        d = Path(root) / name
        if name.startswith(".") or not d.is_dir() or name == R.USER_DIR:
            continue
        fails, warns = layout_problems(d, name)
        problems.setdefault(name, []).extend(fails)
        for w in warns:
            rep.warning("stores/%s  %s" % (name, w))
    for d, reason in invalid:
        problems.setdefault(os.path.basename(str(d)), []).append(
            "invalid STORE: %s -- fix or recreate the STORE file (or delete the directory if nothing lives there)" % reason)
    groups = {}
    for d, ident in valid:
        groups.setdefault(R.id_key(ident), []).append(os.path.basename(str(d)))
    for names in groups.values():
        if len(names) > 1:
            for n in names:
                others = ", ".join("stores/" + o for o in names if o != n)
                problems.setdefault(n, []).append(
                    "same identity as %s -- merge the two directories into one and delete the other" % others)
    idents = {os.path.basename(str(d)): i for d, i in valid}
    for name, ident in idents.items():
        why = store_value_problem(R, ident)
        if why:
            problems.setdefault(name, []).append(why)
    for name in sorted(os.listdir(str(root))):
        d = Path(root) / name
        if name.startswith(".") or not d.is_dir() or name == R.USER_DIR:
            continue
        if problems.get(name):
            for p in problems[name]:
                rep.bad("stores/%s  %s" % (name, p))
        else:
            rep.good("stores/%s  %s" % (name, ident_text(idents[name])))
    uncommitted_and_unpushed(root, rep, now)
    origin_check(R, root, repo, rep)
    blocklist_check(root, repo, rep)
    state_keys, state_reason = load_state(opts.state)
    cwds = session_cwds(opts.claude_projects, opts.kiro_sessions, now, ORPHAN_DAYS)
    orphan_check(R, valid, rep, state_keys, state_reason, cwds, now)
    candidates = list(state_keys) if not state_reason else []
    candidates = [k for k in candidates if not k.startswith("store:")] + list(cwds)
    seen, uniq = set(), []
    for c in candidates:
        n = os.path.normcase(os.path.abspath(c))
        if n not in seen:
            seen.add(n)
            uniq.append(c)
    symlink_check(R, uniq, rep)
    unwired_check(R, valid, kiro_session_cwds(opts.kiro_sessions, now, ORPHAN_DAYS), rep)
    in_workspace_check(R, state_keys, rep, repo)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description="Guard for the workspace store layout.", add_help=False)
    ap.add_argument("repo", nargs="?", default=None)
    ap.add_argument("--stores", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--claude-projects", default=None)
    ap.add_argument("--kiro-sessions", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--help", "-h", action="store_true")
    return ap


def run(argv, now=None):
    """-> (exit code, stdout lines, stderr lines). Never prints; the selftest calls it in process."""
    opts = build_parser().parse_args(argv)
    if opts.help:
        return 0, __doc__.rstrip().split("\n"), []
    now = time.time() if now is None else now
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    try:
        repo = os.path.abspath(opts.repo or os.getcwd())
        if not os.path.isdir(repo):
            raise CouldNotRun("repo path not found: %s" % repo)
        if not os.path.isfile(os.path.join(repo, "shared", "AGENTS.md")):
            raise CouldNotRun("%s does not look like an agent-playbook repo" % repo)
        home = os.path.expanduser("~")
        opts.state = opts.state or os.path.join(repo, "memory", ".dream-state.json")
        opts.claude_projects = opts.claude_projects or os.path.join(home, ".claude", "projects")
        opts.kiro_sessions = opts.kiro_sessions or os.path.join(home, ".kiro", "sessions")
        if opts.stores:
            os.environ["AGENT_PLAYBOOK_STORES"] = opts.stores
        rep = Report()
        R = load_resolver()
        root = R.store_repo_root()
        if not os.path.isdir(str(root)) or not os.path.lexists(os.path.join(str(root), ".git")):
            # /qconfig-sync Step 2b treats a missing store repo as a skip, not a failure.
            rep.add("SKIP: no store repo at %s -- store-repo checks not run; clone it "
                    "(providers/claude/README.md § Store repo on a new machine)" % root)
        else:
            rc, _out = _git(str(root), ["rev-parse", "--git-dir"])
            if os.path.isfile(os.path.join(str(root), ".git")) and rc not in (None, 0):
                raise CouldNotRun("the store repo at %s is unusable: git cannot open it (a broken .git?)" % root)
            store_checks(R, root, rep, opts, repo, now)
        rep.add("verify-stores: ok=%d fail=%d warn=%d" % (rep.ok, rep.fail, rep.warn))
        # Every line, not only the BLOCKLIST check's: an ok: line prints a store's live identity, which can
        # name a listed host, so no line of this guard ever carries a BLOCKLIST term.
        rep.lines = [mask_terms(l, root) for l in rep.lines]
        return (1 if rep.fail else 0), rep.lines, []
    except CouldNotRun as exc:
        return 2, [], ["verify-stores.py: guard did not run: %s" % exc]
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
        print("verify-stores.py: guard did not run: unexpected error: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    return rc


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

GIT_ENV_KEYS = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def fixture_git(cwd, *args, **env_extra):
    env = dict(os.environ)
    env.update(GIT_ENV_KEYS)
    env.update(env_extra)
    r = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=", "-c", "core.autocrlf=false",
                        "-C", str(cwd)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                       timeout=120)
    if r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace")[:200]))
    return r.stdout.decode("utf-8", "replace")


def selftest():
    fails, checks, skips = [], [0], []

    def chk(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (name, (": " + detail) if detail else ""))

    try:
        fixture_git(".", "--version")
    except Exception as exc:
        print("verify-stores selftest: SKIP: git cannot run (%s)" % exc)
        return 0
    # realpath: on macOS the temp dir is a symlink (/var -> /private/var), and the guard reports real paths
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="verify-stores-"))
    # The fixtures live under the system temp directory, a no-create root; only <tmp>/nocreate counts as one.
    RESOLVER_TEST["temp"] = [os.path.join(tmp, "nocreate")]
    # Never the machine's own pointer file: a case that wants one writes it (the stores_url cases).
    saved_config_env = os.environ.get("AGENT_PLAYBOOK_CONFIG")
    os.environ["AGENT_PLAYBOOK_CONFIG"] = os.path.join(tmp, "no-pointer-file")
    R = load_resolver()
    try:
        _selftest_cwd(tmp, chk)
        _selftest_stores(R, tmp, chk, skips)
    finally:
        RESOLVER_TEST.clear()
        if saved_config_env is None:
            os.environ.pop("AGENT_PLAYBOOK_CONFIG", None)
        else:
            os.environ["AGENT_PLAYBOOK_CONFIG"] = saved_config_env
        shutil.rmtree(tmp, ignore_errors=True)
    for s in skips:
        print("SKIP: %s" % s)
    for f in fails:
        print("FAIL: %s" % f)
    print("verify-stores selftest: %d failure(s), %d check(s), %d skipped" % (len(fails), checks[0], len(skips)))
    return 1 if fails else 0


def pointer_template():
    """The `__store__.md` text that /qwire-governance Step 3b.1 writes, `<store-path>` still in it, taken from
    that SKILL.md (the first fenced block after the Step 3b.1 heading); None when it cannot be found."""
    path = HERE.parents[3] / "providers" / "kiro" / "skills" / "qwire-governance" / "SKILL.md"
    try:
        text = path.read_text(encoding="utf-8")  # universal newlines: CRLF reads as LF
    except OSError:
        return None
    fence = "\n" + "`" * 3 + "\n"
    start = text.find("#### Step 3b.1")
    opened = text.find(fence, start) if start >= 0 else -1
    closed = text.find(fence, opened + len(fence)) if opened >= 0 else -1
    return text[opened + len(fence):closed + 1] if closed >= 0 else None


def _selftest_cwd(tmp, chk):
    d = Path(tmp) / "cwdfiles"
    d.mkdir()
    counter = [0]

    def jsonl(lines):
        counter[0] += 1
        p = d / ("s%d.jsonl" % counter[0])
        p.write_bytes(b"".join((l if isinstance(l, bytes) else l.encode("utf-8")) + b"\n" for l in lines))
        return str(p)

    def rec(cwd, **extra):
        r = {"type": "user", "cwd": cwd, "message": {"content": "hello"}}
        r.update(extra)
        return json.dumps(r)

    path_a = "C:\\Users\\a b\u00e9\\proj"
    chk("cwd: backslashes and a non-ASCII letter decode", _first_cwd(jsonl([rec(path_a)])) == path_a, repr(_first_cwd(jsonl([rec(path_a)]))))
    chk("cwd: records without one are passed over",
        _first_cwd(jsonl(['{"type":"summary"}', rec("/b")])) == "/b", "")
    # The first-100-lines limit: the 100th line counts, the 101st does not.
    filler = ['{"type":"summary"}'] * 99
    chk("cwd: found on line 100", _first_cwd(jsonl(filler + [rec("/line100")])) == "/line100", "")
    chk("cwd: not read on line 101", _first_cwd(jsonl(filler + ['{"type":"summary"}', rec("/line101")])) is None, "")
    # Message text is never read for a cwd.
    leak1 = json.dumps({"type": "user", "message": {"content": '{"cwd": "/leak"}'}})
    leak2 = json.dumps({"type": "assistant", "message": {"input": {"cwd": "/leak2"}}})
    chk("cwd: a cwd inside message text is not taken", _first_cwd(jsonl([leak1, leak2])) is None, "")
    chk("cwd: ...and the real record after it is", _first_cwd(jsonl([leak1, leak2, rec("/real")])) == "/real", "")
    # Current Claude Code records put cwd AFTER content/message keys (a hook_success attachment, a user turn).
    attach = '{"type":"attachment","attachment":{"type":"hook_success","content":"","exitCode":0},"cwd":"/after-content","sessionId":"s"}'
    chk("cwd: top-level cwd after a nested content key", _first_cwd(jsonl([attach])) == "/after-content", "")
    after_msg = json.dumps({"type": "user", "message": {"role": "user", "content": 'hi {"cwd": "/nope"}'}, "cwd": "/after-message"})
    chk("cwd: top-level cwd after a message object", _first_cwd(jsonl([after_msg])) == "/after-message", "")
    chk("cwd: the top-level one wins over a nested one before it",
        _first_cwd(jsonl(['{"message":{"input":{"cwd":"/nested"}},"cwd":"/top"}'])) == "/top", "")
    chk("cwd: a nested cwd alone is not taken", _first_cwd(jsonl(['{"message":{"input":{"cwd":"/nested"}}}'])) is None, "")
    chk("cwd: a cwd in an array element is not taken", _first_cwd(jsonl(['{"arr":[{"cwd":"/inarr"}],"x":1}'])) is None, "")
    chk("cwd: brackets and quotes inside strings do not move the depth",
        _first_cwd(jsonl([json.dumps({"a": "}}}]]", "b": 'x},{"cwd":"/f"}', "cwd": "/real-after-strings"})])) == "/real-after-strings", "")
    chk("cwd: the string 'cwd' as a value is not a key", _first_cwd(jsonl(['{"a":"cwd","b":"/zzz"}'])) is None, "")
    chk("cwd: a non-string cwd value is passed over, the next line is read",
        _first_cwd(jsonl(['{"cwd":null,"x":"/zzz"}', rec("/after-null")])) == "/after-null", "")
    chk("cwd: an empty cwd is passed over", _first_cwd(jsonl(['{"cwd":""}', rec("/after-empty")])) == "/after-empty", "")
    chk("cwd: whitespace around the colon", _first_cwd(jsonl(['{ "cwd" :  "/ws" }'])) == "/ws", "")
    # A line is read for at most LINE_PREFIX bytes: a cwd placed after that much text is not seen.
    pad = json.dumps({"type": "user", "pad": "x" * (LINE_PREFIX + 1904), "cwd": "/too-late"})
    chk("cwd: a cwd past the line prefix is skipped, the next line is read",
        _first_cwd(jsonl([pad, rec("/next")])) == "/next", "")
    near = json.dumps({"type": "user", "pad": "x" * (LINE_PREFIX - 200), "cwd": "/in-time"})
    chk("cwd: a cwd inside the line prefix is found", _first_cwd(jsonl([near])) == "/in-time", "")
    front, tail = '{"pad":"', '","cwd":"/abc'
    cut = front + "x" * (LINE_PREFIX - len(front) - len(tail)) + tail
    chk("fixture: the cwd value starts inside the prefix and is cut by its end", len(cut) == LINE_PREFIX, str(len(cut)))
    chk("cwd: a value cut by the end of the prefix is not returned as a partial path",
        _first_cwd(jsonl([cut + 'defghijklmnop"}', rec("/after-cut")])) == "/after-cut", "")
    # Long early lines cost their prefix in the lookup, not their length: twelve 90 KB lines are skipped
    # and the record after them is found (the old 1 MiB total budget gave up here).
    longs = [json.dumps({"type": "attachment", "pad": "p" * 90000, "cwd": "/past-the-prefix"}) for _i in range(12)]
    chk("cwd: twelve 90 KB lines before the real record", _first_cwd(jsonl(longs + [rec("/after-long")])) == "/after-long", "")
    # A huge line is never loaded whole: the cwd at its front is found.
    huge = rec("/front").replace('"hello"', '"' + "y" * (3 << 20) + '"')
    chk("cwd: a 3 MB line with the cwd in front", _first_cwd(jsonl([huge])) == "/front", "")
    # The byte budget bounds the skipped rest of long lines: both sides of it.
    chk("cwd: a 150 KB line is inside a 200 KB budget",
        _first_cwd(jsonl([json.dumps({"pad": "z" * 150000}), rec("/in-budget")]), budget=200000) == "/in-budget", "")
    chk("cwd: a 250 KB line is beyond a 200 KB budget",
        _first_cwd(jsonl([json.dumps({"pad": "z" * 250000}), rec("/past-budget")]), budget=200000) is None, "")
    chk("cwd: a 2 MB line is inside the default budget",
        _first_cwd(jsonl([json.dumps({"type": "user", "pad": "z" * (2 << 20)}), rec("/after-2mb")])) == "/after-2mb", "")
    chk("cwd: an unreadable file yields none", _first_cwd(str(d / "no-such.jsonl")) is None, "")
    # session_cwds: a directory that cannot be listed is left out, the others still count.
    cdir = Path(tmp) / "claude-listing"
    for slug, cwd in (("slug-ok", "/ok"), ("slug-denied", "/denied")):
        (cdir / slug).mkdir(parents=True)
        (cdir / slug / "s.jsonl").write_text(rec(cwd) + "\n", encoding="utf-8")
    denied = os.path.join(str(cdir), "slug-denied")
    real_listdir = os.listdir

    def listdir(p="."):
        if os.path.normcase(os.path.abspath(str(p))) == os.path.normcase(denied):
            raise PermissionError("planted")
        return real_listdir(p)

    os.listdir = listdir
    try:
        got = session_cwds(str(cdir), None, time.time(), 90)
    except Exception as exc:
        got = "raised %s" % exc
    finally:
        os.listdir = real_listdir
    chk("cwd: an unlistable directory is skipped", got == ["/ok"], repr(got))


def _store_text(d, text):
    d.mkdir(parents=True, exist_ok=True)
    (d / "STORE").write_bytes(text.encode("utf-8"))


def _mk_store_repo(root, with_remote=None):
    root.mkdir(parents=True, exist_ok=True)
    fixture_git(root, "init", "-q")
    fixture_git(root, "symbolic-ref", "HEAD", "refs/heads/main")


def _commit_all(root, msg="c", when=None):
    fixture_git(root, "add", "-A")
    extra = {}
    if when is not None:
        stamp = "%d +0000" % int(when)
        extra = {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    fixture_git(root, "commit", "-q", "-m", msg, **extra)


def _backdate(path, seconds):
    t = time.time() - seconds
    os.utime(str(path), (t, t))


def _selftest_stores(R, tmp, chk, skips):
    T = Path(tmp)
    now = time.time()
    # --- a config repo, a checkout whose origin is the store's remote, and a clean pushed store repo ---
    repo = T / "repo"
    (repo / "shared").mkdir(parents=True)
    (repo / "shared" / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
    (repo / "memory").mkdir()
    work = T / "work"
    proj = R.fixture_repo(work / "proj", "https://example.com/org/proj.git")
    (proj / "sub").mkdir()
    claude, kiro = T / "claude", T / "kiro"
    claude.mkdir()
    kiro.mkdir()
    state_file = repo / "memory" / ".dream-state.json"

    def write_state(paths):
        state_file.write_text(json.dumps({"schema_version": 3, "projects": {p: {"last_analyzed": "2026-10-01T00:00:00Z"} for p in paths}}),
                              encoding="utf-8")

    write_state([str(proj)])
    base = T / "base-stores"
    _mk_store_repo(base)
    _store_text(base / "proj-abcdef", "remote example.com/org/proj\n")
    (base / "proj-abcdef" / "memory").mkdir()
    (base / "proj-abcdef" / "memory" / "MEMORY.md").write_text("# Project Memory\n", encoding="utf-8")
    (base / ".gitignore").write_text("STORE.tmp-*\nvisualizations/\n", encoding="utf-8")
    _commit_all(base)
    origin = T / "origin.git"
    fixture_git(T, "init", "-q", "--bare", str(origin))
    fixture_git(base, "remote", "add", "origin", str(origin))
    fixture_git(base, "push", "-q", "-u", "origin", "main")

    counter = [0]

    def clone():
        counter[0] += 1
        dest = T / ("stores-%d" % counter[0])
        shutil.copytree(str(base), str(dest))
        return dest

    def go(root, extra=(), state=None, rp=None):
        if state is not None:
            write_state(state)
        argv = [str(rp or repo), "--stores", str(root), "--claude-projects", str(claude),
                "--kiro-sessions", str(kiro)] + list(extra)
        return run(argv)

    def has(out, prefix, *frag):
        return any(l.startswith(prefix) and all(f in l for f in frag) for l in out)

    def count(out, prefix):
        return sum(1 for l in out if l.startswith(prefix))

    # --- baseline: clean, pushed, served by the state path ---
    root = clone()
    rc, out, err = go(root)
    chk("baseline exit 0", rc == 0, "%s %r %r" % (rc, out, err))
    chk("baseline ok line", "ok: stores/proj-abcdef  remote example.com/org/proj" in out, repr(out))
    chk("baseline no FAIL/WARN", count(out, "FAIL:") == 0 and count(out, "WARN:") == 0, repr(out))
    chk("baseline summary", "verify-stores: ok=1 fail=0 warn=0" in out, repr(out))

    # --- a STORE value not in the resolver's normalized form: valid syntax the resolver never matches ---
    root = clone()
    _store_text(root / "loc-111111", "local C:\\Users\\x\\proj\n")
    rc, out, _e = go(root)
    chk("un-normalized local value fails", rc == 1 and has(out, "FAIL: stores/loc-111111", "not in normalized form", "c:/users/x/proj"), repr(out))
    root = clone()
    _store_text(root / "dotgit-111111", "remote example.com/org/other.git\n")
    rc, out, _e = go(root)
    chk("un-normalized remote value fails", rc == 1 and has(out, "FAIL: stores/dotgit-111111", "not in normalized form"), repr(out))
    for nm, val in (("slash-111111", "remote example.com/org/tslash/"), ("port-111111", "remote example.com:443/org/p"),
                    ("query-111111", "remote example.com/org/q?x=1")):
        root = clone()
        _store_text(root / nm, val + "\n")
        rc, out, _e = go(root)
        chk("remote value the resolver never matches fails: %s" % nm, rc == 1 and has(out, "FAIL: stores/" + nm, "not in normalized form"), repr(out))
    root = clone()
    os.rename(str(root / ".git"), str(root / "git-moved-aside"))
    (root / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
    rc, out, err = go(root)
    chk("a store repo whose .git file points nowhere did not run (exit 2)", rc == 2 and any("unusable" in e for e in err), repr((rc, out, err)))

    # --- a rebase stopped in the store repo is a WARN naming it, not a misleading "no upstream" ---
    root = clone()
    (root / ".git" / "rebase-merge").mkdir()
    rc, out, _e = go(root)
    chk("rebase in progress warns", rc == 0 and has(out, "WARN: stores-repo", "rebase is in progress"), repr(out))
    chk("rebase in progress: no push-state line", not has(out, "SKIP: stores-repo push state"), repr(out))

    # --- the origin URL against the pointer file's stores_url= ---
    saved_cfg = os.environ.get("AGENT_PLAYBOOK_CONFIG")
    cfgf = T / "playbook-config"
    cfgf.write_text("stores_url=https://github.com/Owner/agent-playbook-stores.git\n", encoding="utf-8")
    os.environ["AGENT_PLAYBOOK_CONFIG"] = str(cfgf)
    try:
        root = clone()
        rc, out, _e = go(root)
        chk("origin elsewhere warns", rc == 0 and has(out, "WARN: stores-repo", "push URL is", "github.com/owner/agent-playbook-stores"), repr(out))
        fixture_git(root, "remote", "set-url", "origin", "https://x:" + "y@github.com/owner/Agent-Playbook-Stores")  # split: no credential-shaped literal
        rc, out, _e = go(root)
        chk("origin matching stores_url is quiet", not has(out, "WARN: stores-repo", "push URL is"), repr(out))
        cfgf.write_text("# no stores_url\n", encoding="utf-8")
        rc, out, _e = go(clone())
        chk("no stores_url is a SKIP line", has(out, "SKIP: stores-repo origin", "no stores_url="), repr(out))
    finally:
        if saved_cfg is None:
            os.environ.pop("AGENT_PLAYBOOK_CONFIG", None)
        else:
            os.environ["AGENT_PLAYBOOK_CONFIG"] = saved_cfg

    # --- BLOCKLIST: a tracked config-repo file holding a listed term fails, named by line, never by term ---
    br = T / "repo-blocklist"
    (br / "shared").mkdir(parents=True)
    (br / "shared" / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
    (br / "memory").mkdir()
    (br / "notes.md").write_text("see the Zebra-Host-77 server\n", encoding="utf-8")
    (br / "plans" / "done").mkdir(parents=True)
    (br / "plans" / "done" / "old.md").write_text("zebra-host-77 again\n", encoding="utf-8")
    (br / "clean.md").write_text("nothing here\n", encoding="utf-8")
    fixture_git(br, "init", "-q")
    _commit_all(br)
    root = clone()
    (root / "BLOCKLIST").write_text("# terms that must never enter the config repo\nzebra-host-77\n", encoding="utf-8")
    rc, out, err = go(root, rp=br)
    chk("blocklist: a tracked file with the term fails", rc == 1 and has(out, "FAIL: config-repo notes.md", "line 2 of the store repo's BLOCKLIST"), repr((out, err)))
    chk("blocklist: an archived plan is checked too", has(out, "FAIL: config-repo plans/done/old.md", "line 2"), repr(out))
    chk("blocklist: a clean file passes", not has(out, "FAIL: config-repo clean.md"), repr(out))
    chk("blocklist: the term itself is never printed", not any("zebra" in l.lower() for l in out + err), repr(out))
    (br / "zebra-host-77-notes.md").write_text("clean text\n", encoding="utf-8")
    (br / "docs").mkdir()
    (br / "docs" / "Zebra-Host-77.md").write_text("zebra-host-77 inside\n", encoding="utf-8")
    fixture_git(br, "add", "-A")
    fixture_git(br, "commit", "-q", "-m", "names")
    rc, out, err = go(root, rp=br)
    chk("blocklist: a file name holding the term fails", has(out, "FAIL: config-repo <BLOCKLIST 2>-notes.md", "file name"), repr(out))
    chk("blocklist: a path holding the term is masked", has(out, "FAIL: config-repo docs/<BLOCKLIST 2>.md", "holds the term"), repr(out))
    chk("blocklist: the term never printed, paths included", not any("zebra" in l.lower() for l in out + err), repr(out))
    _store_text(root / "zeb-222222", "remote zebra-host-77/org/proj\n")
    rc, out, err = go(root, rp=br)
    chk("blocklist: a store identity holding the term is masked in its ok: line",
        has(out, "ok: stores/zeb-222222", "<BLOCKLIST 2>") and not any("zebra" in l.lower() for l in out + err), repr(out))
    (root / "BLOCKLIST").write_text("# only a comment\n", encoding="utf-8")
    rc, out, _e = go(root, rp=br)
    chk("blocklist: comments only, nothing fails", not has(out, "FAIL: config-repo"), repr(out))

    # --- the plan's mutation: a deleted STORE file turns OK into FAIL ---
    root = clone()
    os.remove(str(root / "proj-abcdef" / "STORE"))
    rc, out, err = go(root)
    chk("mutation: deleted STORE exits 1", rc == 1, "%s %r" % (rc, out))
    chk("mutation: FAIL names the directory and the cause", has(out, "FAIL: stores/proj-abcdef", "no STORE file"), repr(out))
    chk("mutation: no ok line for it", not has(out, "ok: stores/proj-abcdef"), repr(out))

    # --- invalid STORE texts ---
    root = clone()
    _store_text(root / "proj-abcdef", "banana\n")
    rc, out, _e = go(root)
    chk("malformed STORE fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "invalid STORE", "line 1"), repr(out))
    root = clone()
    _store_text(root / "proj-abcdef", "")
    _backdate(root / "proj-abcdef" / "STORE", 60)
    rc, out, _e = go(root)
    chk("old empty STORE fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "empty STORE"), repr(out))
    root = clone()
    _store_text(root / "proj-abcdef", "local C:/x\npath sub\n")
    rc, out, _e = go(root)
    chk("path line after a local line fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "invalid STORE"), repr(out))

    # --- duplicate identities: case-only difference is a duplicate; a different path line is not ---
    root = clone()
    _store_text(root / "twin-123456", "remote Example.com/Org/Proj\n")
    rc, out, _e = go(root)
    chk("case-folded duplicate fails both", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "same identity as stores/twin-123456")
        and has(out, "FAIL: stores/twin-123456", "same identity as stores/proj-abcdef"), repr(out))
    root = clone()
    _store_text(root / "mono-654321", "remote example.com/org/proj\npath tools/a\n")
    rc, out, _e = go(root)
    chk("same remote, different path line is no duplicate", count(out, "FAIL:") == 0, repr(out))

    # --- reserved folder names ---
    root = clone()
    (root / "plans").mkdir()
    (root / "plans" / "x.md").write_text("x\n", encoding="utf-8")
    rc, out, _e = go(root)
    chk("reserved name at the repo root fails", rc == 1 and has(out, "FAIL: stores/plans", "reserved folder name at the store repo root"), repr(out))
    root = clone()
    shutil.rmtree(str(root / "proj-abcdef" / "memory"))
    (root / "proj-abcdef" / "memory").write_text("a file\n", encoding="utf-8")
    rc, out, _e = go(root)
    chk("reserved name as a file fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "memory is a file"), repr(out))
    root = clone()
    (root / "proj-abcdef" / "done").mkdir()
    rc, out, _e = go(root)
    chk("done/ directly in a store fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "done/ sits directly in the store"), repr(out))
    root = clone()
    (root / "proj-abcdef" / "plans").mkdir()
    (root / "proj-abcdef" / "plans" / "tests").write_text("file\n", encoding="utf-8")
    rc, out, _e = go(root)
    chk("plans/tests as a file fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "plans/tests is a file"), repr(out))
    root = clone()
    (root / "proj-abcdef" / "plans").mkdir()
    (root / "proj-abcdef" / "plans" / "done").mkdir()
    (root / "proj-abcdef" / "plans" / "tests").mkdir()
    (root / "proj-abcdef" / "explanations").mkdir()
    (root / "proj-abcdef" / "artifacts").mkdir()
    (root / "proj-abcdef" / "visualizations").mkdir()
    (root / "proj-abcdef" / "notes").mkdir()
    rc, out, _e = go(root)
    chk("the SC-2 layout (and an unlisted folder) passes", rc == 0 and count(out, "FAIL:") == 0, repr(out))
    root = clone()
    os.rename(str(root / "proj-abcdef" / "memory"), str(root / "proj-abcdef" / "tmp-name"))
    os.rename(str(root / "proj-abcdef" / "tmp-name"), str(root / "proj-abcdef" / "Memory"))
    names = os.listdir(str(root / "proj-abcdef"))
    if "Memory" in names:
        rc, out, _e = go(root)
        chk("upper-case reserved name fails", rc == 1 and has(out, "FAIL: stores/proj-abcdef", "must be spelled memory"), repr(out))
    else:
        skips.append("upper-case reserved name: the file system folds the case of a rename")
    root = clone()
    (root / "proj-abcdef" / "STORE.tmp-9z").write_text("x\n", encoding="utf-8")
    rc, out, _e = go(root)
    chk("leftover STORE.tmp-* warns, exit 0", rc == 0 and has(out, "WARN: stores/proj-abcdef", "STORE.tmp-9z"), repr(out))

    # --- uncommitted for over a day: both sides of the boundary ---
    for hours, expect in ((23, False), (25, True)):
        root = clone()
        f = root / "proj-abcdef" / "memory" / "new.md"
        f.write_text("n\n", encoding="utf-8")
        _backdate(f, hours * 3600)
        rc, out, _e = go(root)
        chk("uncommitted %dh: warn=%s" % (hours, expect), has(out, "WARN: stores-repo", "uncommitted for over a day") == expect, repr(out))
        chk("uncommitted %dh: exit 0" % hours, rc == 0, str(rc))
    root = clone()
    f = root / "proj-abcdef" / "memory" / "MEMORY.md"
    f.write_text("# Project Memory\nedited\n", encoding="utf-8")
    _backdate(f, 49 * 3600)
    rc, out, _e = go(root)
    chk("a modified tracked file warns", has(out, "WARN: stores-repo", "memory/MEMORY.md"), repr(out))
    root = clone()
    os.remove(str(root / "proj-abcdef" / "memory" / "MEMORY.md"))
    _backdate(root / "proj-abcdef" / "memory", 49 * 3600)
    rc, out, _e = go(root)
    chk("a deleted tracked path uses its parent's mtime", has(out, "WARN: stores-repo", "memory/MEMORY.md"), repr(out))

    # --- unpushed for over a day ---
    for hours, expect in ((23, False), (25, True)):
        root = clone()
        (root / "proj-abcdef" / "memory" / "more.md").write_text("m\n", encoding="utf-8")
        _commit_all(root, "local", when=now - hours * 3600)
        rc, out, _e = go(root)
        chk("unpushed %dh: warn=%s" % (hours, expect), has(out, "WARN: stores-repo", "not pushed") == expect, repr(out))
        chk("unpushed %dh: exit 0" % hours, rc == 0, str(rc))
    root = T / "no-upstream"
    _mk_store_repo(root)
    _store_text(root / "proj-abcdef", "remote example.com/org/proj\n")
    _commit_all(root)
    rc, out, _e = go(root)
    chk("no upstream is a skip line", rc == 0 and has(out, "SKIP: stores-repo push state", "no upstream") and count(out, "WARN:") == 0, repr(out))

    # --- orphaned stores ---
    root = clone()
    rc, out, _e = go(root, state=[])
    chk("no state path, no session: orphan warn, exit 0", rc == 0 and has(out, "WARN: stores/proj-abcdef", "orphaned"), repr(out))
    sess = claude / "slug-a"
    sess.mkdir()
    jl = sess / "s1.jsonl"
    jl.write_text(json.dumps({"type": "summary"}) + "\n" + json.dumps({"type": "user", "cwd": str(proj), "message": {"content": "SECRET"}}) + "\n", encoding="utf-8")
    for days, expect in ((89, False), (91, True)):
        _backdate(jl, days * DAY)
        rc, out, _e = go(root, state=[])
        chk("claude session %dd old: orphan=%s" % (days, expect), has(out, "WARN: stores/proj-abcdef", "orphaned") == expect, repr(out))
    _backdate(jl, 1 * DAY)
    jl.write_text(json.dumps({"type": "user", "cwd": str(proj / "sub")}) + "\n", encoding="utf-8")
    rc, out, _e = go(root, state=[])
    chk("a session in a subfolder serves the repo's store", count(out, "WARN:") == 0, repr(out))
    jl.unlink()
    ks = kiro / "hash1" / "sess_x"
    ks.mkdir(parents=True)
    (ks / "session.json").write_text(json.dumps({"id": "sess_x", "workspacePaths": [str(proj)]}), encoding="utf-8")
    rc, out, _e = go(root, state=[])
    chk("a Kiro session serves the store", not has(out, "WARN:", "orphaned"), repr(out))
    _backdate(ks / "session.json", 95 * DAY)
    rc, out, _e = go(root, state=[])
    chk("an old Kiro session does not", has(out, "WARN: stores/proj-abcdef", "orphaned"), repr(out))
    shutil.rmtree(str(kiro / "hash1"))
    rc, out, _e = go(root, state=["store:remote example.com/org/proj"])
    chk("a store: state key references the store", count(out, "WARN:") == 0, repr(out))
    other = R.fixture_repo(work / "other", "https://example.com/org/other.git")
    rc, out, _e = go(root, state=[str(other)])
    chk("a state path of another repo does not serve it", has(out, "WARN: stores/proj-abcdef", "orphaned"), repr(out))
    root = clone()
    _store_text(root / "mono-654321", "remote example.com/org/proj\npath sub\n")
    _commit_all(root)
    rc, out, _e = go(root, state=[str(proj)])
    chk("a subpath store is not served by the repo root", has(out, "WARN: stores/mono-654321", "orphaned")
        and not has(out, "WARN: stores/proj-abcdef"), repr(out))
    rc, out, _e = go(root, state=[str(proj / "sub")])
    chk("a subpath store is served by a folder at that subpath", not has(out, "WARN: stores/mono-654321", "orphaned"), repr(out))
    # local stores: a path that is gone is an orphan even when the state names it
    loc = work / "plain"
    loc.mkdir()
    lid = R.identity(str(loc))
    chk("fixture: plain folder has a local identity", lid.status == "found" and lid.path.kind == "local", repr(lid))
    if lid.status == "found":
        root = clone()
        _store_text(root / "plain-111111", "local %s\n" % lid.path.value)
        _commit_all(root)
        rc, out, _e = go(root, state=[str(proj), str(loc)])
        chk("a local store with its folder is quiet", count(out, "WARN:") == 0, repr(out))
        gone = work / "gone"
        gone.mkdir()
        gid = R.identity(str(gone))
        _store_text(root / "gone-222222", "local %s\n" % gid.path.value)
        _commit_all(root)
        gone.rmdir()
        rc, out, _e = go(root, state=[str(proj), str(loc), str(gone)])
        chk("a local store whose path is gone warns, though the state names it",
            has(out, "WARN: stores/gone-222222", "no longer exists") and not has(out, "WARN: stores/gone-222222", "no .dream-state.json"), repr(out))
        chk("...and only that store", count(out, "WARN:") == 1, repr(out))
    root = clone()
    write_state([str(proj)])
    state_file.write_text("{not json", encoding="utf-8")
    rc, out, _e = go(root)
    chk("an unreadable state skips the orphan check, no false warning", rc == 0 and has(out, "SKIP: orphaned-store check") and count(out, "WARN:") == 0, repr(out))
    write_state([str(proj)])

    # --- the reserved user/ (user-tier memory behind the config repo's `memory` link) is never a store ---
    root = clone()
    (root / "user" / "memory").mkdir(parents=True)
    (root / "user" / "memory" / "MEMORY.md").write_text("# user tier\n", encoding="utf-8")
    rc, out, _e = go(root)
    chk("user/: reported as user-tier memory, no invalid-STORE fail", rc == 0 and has(out, "ok: stores/user", "user-tier memory")
        and not has(out, "FAIL: stores/user"), repr(out))
    (root / "user" / "STORE").write_text("local c:/somewhere\n", encoding="utf-8")
    rc, out, _e = go(root)
    chk("user/: a STORE file in it fails", rc == 1 and has(out, "FAIL: stores/user", "reserved for user-tier memory"), repr(out))

    # --- in-workspace memory/plans: always checked; a config repo's memory/ (the user tier) is exempt ---
    wsroot = work / "withmem"
    (wsroot / "memory").mkdir(parents=True)
    (wsroot / "memory" / "MEMORY.md").write_text("# m\n", encoding="utf-8")
    (repo / "plans").mkdir(exist_ok=True)
    (repo / "plans" / "p.md").write_text("# p\n", encoding="utf-8")
    (repo / "memory" / "MEMORY.md").write_text("# user tier\n", encoding="utf-8")
    root = clone()
    rc, out, _e = go(root, state=[str(proj), str(wsroot), str(repo)])
    chk("in-workspace warn: names the workspace's memory/", has(out, "WARN:", str(wsroot), "in-workspace memory/"), repr(out))
    chk("in-workspace warn: the config repo's plans/ warns (they live in its store)", has(out, "WARN:", str(repo) + " ", "in-workspace plans/"), repr(out))
    chk("in-workspace warn: the config repo's memory/ (user tier) is exempt", not has(out, "WARN:", str(repo) + " ", "in-workspace memory/"), repr(out))
    chk("in-workspace warn: exit 0", rc == 0, str(rc))
    shutil.rmtree(str(repo / "plans"))
    (wsroot / "plans").mkdir()
    (wsroot / "plans" / "q.md").write_text("# q\n", encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj), str(wsroot)])
    chk("in-workspace warn: a workspace's plans/ warns too", has(out, "WARN:", str(wsroot), "in-workspace plans/"), repr(out))
    shutil.rmtree(str(wsroot / "memory"))
    shutil.rmtree(str(wsroot / "plans"))
    rc, out, _e = go(root, state=[str(proj), str(wsroot)])
    chk("in-workspace warn: a workspace without memory/ or plans/ is quiet", not has(out, "WARN:", "in-workspace"), repr(out))
    # a no-create folder keeps its memory in place (memory-rules.md § Resolution contract step 3)
    nc = T / "nocreate" / "scratch"
    (nc / "memory").mkdir(parents=True)
    (nc / "memory" / "MEMORY.md").write_text("# m\n", encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj), str(nc)])
    chk("in-workspace warn: a no-create folder's memory/ is exempt", not has(out, "WARN:", str(nc)), repr(out))
    # another config repo (identified by its markers, not by the argument path): memory/ exempt, plans/ warn
    other = T / "other-cfg"
    for rel in (("shared", "AGENTS.md"), ("shared", "skills", "qdream", "scripts", "store-resolver.py")):
        f = other.joinpath(*rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# fixture\n", encoding="utf-8")
    fixture_git(other, "init", "-q")
    for kind, name in (("memory", "MEMORY.md"), ("plans", "p.md")):
        (other / kind).mkdir()
        (other / kind / name).write_text("# x\n", encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj), str(other)])
    chk("in-workspace warn: a second config repo's memory/ is exempt, its plans/ warn",
        has(out, "WARN:", str(other), "in-workspace plans/") and not has(out, "WARN:", str(other), "in-workspace memory/"), repr(out))
    shutil.rmtree(str(other / "plans"))
    os.remove(str(repo / "memory" / "MEMORY.md"))

    # --- a wired workspace (a __store__.md pointer) whose store has memory but no __store_memory__.md link ---
    psteer = proj / ".kiro" / "steering"
    psteer.mkdir(parents=True, exist_ok=True)
    pointer = psteer / "__store__.md"
    template = pointer_template()

    def write_pointer(store_dir, text=None, crlf=False, bom=False):
        body = (template if text is None else text).replace("<store-path>", str(store_dir))
        if crlf:
            body = body.replace("\n", "\r\n")
        pointer.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))

    root = clone()
    sdir = root / "proj-abcdef"
    if template is None:
        skips.append("missing-link warning: the pointer template was not found in qwire-governance/SKILL.md")
    else:
        write_pointer(sdir)
        rc, out, _e = go(root, state=[str(proj)])
        chk("pointer + store memory + no link: warns", has(out, "WARN:", "__store_memory__.md", "is missing", "re-run /qwire-governance"), repr(out))
        chk("...exit stays 0", rc == 0, str(rc))
        chk("pointer_store reads the template's path", pointer_store(str(pointer)) == str(sdir), repr(pointer_store(str(pointer))))
        write_pointer(sdir, crlf=True, bom=True)
        rc, out, _e = go(root, state=[str(proj)])
        chk("a CRLF + BOM pointer is read the same", has(out, "WARN:", "is missing"), repr(out))
        os.remove(str(sdir / "memory" / "MEMORY.md"))
        rc, out, _e = go(root, state=[str(proj)])
        chk("pointer but the store has no MEMORY.md yet: quiet", not has(out, "WARN:", "is missing"), repr(out))
        write_pointer(root / "no-such-store-dir")
        (sdir / "memory" / "MEMORY.md").write_text("# Project Memory\n", encoding="utf-8")
        rc, out, _e = go(root, state=[str(proj)])
        chk("pointer naming a store directory that does not exist: quiet", not has(out, "WARN:", "is missing"), repr(out))
    if pointer.exists():
        pointer.unlink()
    rc, out, _e = go(root, state=[str(proj)])
    chk("no pointer, no link: quiet", not has(out, "WARN:", "is missing"), repr(out))
    chk("pointer_store: ~ is expanded", pointer_store_text("x\n`~/a/b`\ny\n") == os.path.expanduser("~/a/b"), "")
    chk("pointer_store: a line with two backticked spans is not the path line",
        pointer_store_text("1. Read `/s/memory/MEMORY.md` or `/t`\n") is None, "")
    shutil.rmtree(str(psteer.parent), ignore_errors=True)

    # --- an unwired workspace: a recent Kiro session in a store-backed folder with no __store__.md ---
    root = clone()
    ku = kiro / "hash-unwired" / "sess_u"
    ku.mkdir(parents=True)
    kjson = ku / "session.json"
    kjson.write_text(json.dumps({"id": "sess_u", "workspacePaths": [str(proj)]}), encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj)])
    chk("unwired: a Kiro session in a store-backed root with no pointer warns",
        has(out, "WARN:", "__store__.md", "never wired", "stores/proj-abcdef", "re-run /qwire-governance in %s" % str(proj).replace("\\", "/")), repr(out))
    chk("unwired: ...exit stays 0", rc == 0, str(rc))
    kjson.write_text(json.dumps({"id": "sess_u", "workspacePaths": [str(proj / "sub")]}), encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj)])
    chk("unwired: a subfolder session names the repo root, once",
        sum(1 for l in out if l.startswith("WARN:") and "never wired" in l and "in %s" % str(proj).replace("\\", "/") in l) == 1,
        repr(out))
    psteer.mkdir(parents=True, exist_ok=True)
    pointer.write_text("# pointer\n", encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj)])
    chk("unwired: a root with __store__.md is quiet", not has(out, "WARN:", "never wired"), repr(out))
    shutil.rmtree(str(psteer.parent), ignore_errors=True)
    _backdate(kjson, 95 * DAY)
    rc, out, _e = go(root, state=[str(proj)])
    chk("unwired: a Kiro session older than 90 days is quiet", not has(out, "WARN:", "never wired"), repr(out))
    kjson.write_text(json.dumps({"id": "sess_u", "workspacePaths": [str(other)]}), encoding="utf-8")
    rc, out, _e = go(root, state=[str(proj)])
    chk("unwired: a Kiro session in a folder no store serves is quiet", not has(out, "WARN:", "never wired"), repr(out))
    if jl.exists():
        jl.unlink()
    sess.mkdir(exist_ok=True)
    cj = sess / "s-unwired.jsonl"
    cj.write_text(json.dumps({"type": "user", "cwd": str(proj)}) + "\n", encoding="utf-8")
    kjson.unlink()
    rc, out, _e = go(root, state=[str(proj)])
    chk("unwired: a Claude Code session alone does not warn (only Kiro needs the wiring)",
        not has(out, "WARN:", "never wired"), repr(out))
    cj.unlink()
    shutil.rmtree(str(kiro / "hash-unwired"))

    # --- Kiro __store_memory__.md links ---
    probe = T / "linkprobe"
    try:
        os.symlink(str(base / ".gitignore"), str(probe))
        can_link = True
        os.remove(str(probe))
    except (OSError, NotImplementedError):
        can_link = False
    if not can_link:
        skips.append("__store_memory__.md symlink cases: this process cannot create symbolic links")
    else:
        root = clone()
        steer = proj / ".kiro" / "steering"
        steer.mkdir(parents=True, exist_ok=True)
        link = steer / "__store_memory__.md"
        right = root / "proj-abcdef" / "memory" / "MEMORY.md"
        os.symlink(str(right), str(link))
        if template is not None:
            write_pointer(root / "proj-abcdef")
        rc, out, _e = go(root, state=[str(proj)])
        chk("a link to its store's memory is quiet (pointer present too)", count(out, "WARN:") == 0, repr(out))
        link.unlink()
        wrong = T / "elsewhere.md"
        wrong.write_text("# x\n", encoding="utf-8")
        os.symlink(str(wrong), str(link))
        rc, out, _e = go(root, state=[str(proj)])
        chk("a link to another file warns", has(out, "WARN:", "__store_memory__.md", "not at its store's memory"), repr(out))
        chk("...and the exit stays 0", rc == 0, str(rc))
        link.unlink()
        shutil.copyfile(str(right), str(link))
        rc, out, _e = go(root, state=[str(proj)])
        chk("a copy warns", has(out, "WARN:", "is not a symlink"), repr(out))
        link.unlink()
        os.symlink(str(root / "proj-abcdef" / "memory" / "gone.md"), str(link))
        rc, out, _e = go(root, state=[str(proj)])
        chk("a dangling link to the wrong file warns", has(out, "WARN:", "not at its store's memory"), repr(out))
        link.unlink()
        os.symlink("~/memory/MEMORY.md", str(link))
        rc, out, _e = go(root, state=[str(proj)])
        chk("a literal ~ target warns", has(out, "WARN:", "__store_memory__.md"), repr(out))
        link.unlink()
        # a workspace no store serves: its link warns whatever it points at
        lone = work / "lonely"
        R.fixture_repo(lone, "https://example.com/org/lonely.git")
        lsteer = lone / ".kiro" / "steering"
        lsteer.mkdir(parents=True)
        os.symlink(str(right), str(lsteer / "__store_memory__.md"))
        rc, out, _e = go(root, state=[str(proj), str(lone)])
        chk("a link in a workspace no store serves warns", has(out, "WARN:", "__store_memory__.md", "no store serves this workspace"), repr(out))
        shutil.rmtree(str(lsteer.parent))
        shutil.rmtree(str(steer.parent))

    # --- could not run: exit 2 ---
    rc, out, err = go(T / "no-such-stores")
    chk("a missing store repo is a SKIP line (Step 2b)", rc == 0 and has(out, "SKIP: no store repo at", "clone it")
        and "verify-stores: ok=0 fail=0 warn=0" in out, "%s %r %r" % (rc, out, err))
    plain = T / "plain-dir"
    plain.mkdir()
    rc, out, err = go(plain)
    chk("a store root without .git is the same SKIP", rc == 0 and has(out, "SKIP: no store repo at"), "%s %r" % (rc, out))
    filesonly = T / "files-only"
    filesonly.mkdir()
    (filesonly / ".git").mkdir()
    (filesonly / "stray-file").write_text("a file, not a directory\n", encoding="utf-8")
    rc, out, err = go(filesonly)
    chk("a store repo holding only a file (no store directory) is clean", rc == 0, "%s %r" % (rc, out))
    rc, out, err = run([str(T / "not-a-repo"), "--stores", str(base)])
    chk("a missing repo exits 2", rc == 2, "%s %r" % (rc, err))
    rc, out, err = run([str(plain), "--stores", str(base)])
    chk("a folder that is not the playbook exits 2", rc == 2 and any("agent-playbook repo" in e for e in err), "%s %r" % (rc, err))

    # --- the venv guard: another interpreter exits 2 before anything runs ---
    other_py = getattr(sys, "_base_executable", None)
    if other_py and _norm(other_py) != _norm(sys.executable):
        r = subprocess.run([other_py, "-I", "-B", os.path.realpath(__file__), str(repo), "--stores", str(base)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        chk("another interpreter exits 2 with the venv message", r.returncode == 2
            and b"guard did not run: venv missing" in r.stderr, "%s %r" % (r.returncode, r.stderr[:200]))
    else:
        skips.append("venv guard: no interpreter outside the venv to try")


if __name__ == "__main__":
    sys.exit(main())
