"""Rewrite every path-keyed agent store from OLD to NEW. DRY RUN unless --apply.

  <python> apply.py --old <path> --new <path> [--config-repo <checkout>] [--also <file> ...] [--apply]

--config-repo  the agent-playbook checkout that will be live AFTER the move (the copy under NEW
               when the config repo itself moves). Its machine state is rewritten.
--also         an extra file to rewrite whole (project config that names OLD, found by
               `verify.py residue`). Repeatable.
--ignore-procs relaxes the live-process refusal for CLAUDE processes only (agent-run mode: the
               agent driving this script is itself a claude process). It still refuses when any
               codex, kiro/kiro-cli, Code (VS Code), PowerAtlas or gemini process is alive; Gemini
               CLI runs as node.exe, so a node.exe whose command line names gemini counts as gemini.
               It also refuses while a live claude session (~/.claude/sessions/<pid>.json with a
               running pid) has its cwd inside OLD or NEW. Claude Code keeps appending to
               ~/.claude/history.jsonl and ~/.claude.json, so those two files are rewritten with a
               re-check (see _rewrite_live) and looked at again a few seconds after the run, because a
               live session can write its own copy back.

Guarantees: raw byte replacement (no JSON round trip, no BOM), mtimes preserved (Claude Code
and Codex order sessions by mtime) except on re-keyed store-repo STORE files, every changed file backed up first, every rename recorded
in manifest.json for restore.py, and a changed .json/.jsonl/.toml must still parse if it
parsed before. Only sessions that BELONG to OLD are rewritten; other transcripts that merely
mention OLD stay byte-identical. --apply first re-runs itself as a dry run and refuses on any
blocker, and refuses while agent or editor processes are alive (the stores are shared by
every session, not only by sessions in OLD). A run that stops on a blocker after it began is
partly applied: fix the cause and re-run the same command (idempotent); restore only to undo it all.

OLD may be absent (already moved by OneDrive or by hand): this script only matches OLD's path text
and lists OLD's parent folder; it reads no file under OLD. A Claude project folder named from OLD
that holds NO transcript (no *.jsonl at any depth) is handled by what else it holds:
  - nothing but sessions-index.json: parked in the backup folder (manifest.json records it,
    restore.py moves it back);
  - other content (memory/MEMORY.md and the like) in the folder with OLD's exact slug: rewritten
    and renamed to NEW's slug, unless a sibling folder's name also matches OLD (then a blocker);
  - other content in a folder that only starts with OLD's slug: a blocker (the slug is lossy).
A folder that holds a transcript but none whose cwd is inside OLD stays a blocker.
"""
import argparse
import atexit
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathmap import (PathMap, ambiguous_siblings, kiro_workspace_hash, load_store_resolver, slug,  # noqa: E402
                     store_rewrites, work_dir)

H = os.path.expanduser("~")
ap = argparse.ArgumentParser()
ap.add_argument("--old", required=True)
ap.add_argument("--new", required=True)
ap.add_argument("--config-repo")
ap.add_argument("--also", action="append", default=[])
ap.add_argument("--work", help="default: a per-migration folder under ~/.agent-playbook/qmigrate-workspace")
ap.add_argument("--apply", action="store_true")
ap.add_argument("--ignore-procs", action="store_true")
ap.add_argument("--no-predry", action="store_true")
A = ap.parse_args()
APPLY = A.apply
pm = PathMap(A.old, A.new)
A.work = A.work or work_dir(A.old, A.new)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUP = os.path.join(A.work, "backup-" + STAMP)
# started_ns (UTC epoch, nanoseconds) orders runs for restore.py; the folder stamp is local time and can go backwards
manifest = {"stamp": STAMP, "started_ns": time.time_ns(), "old": A.old, "new": A.new, "renames": [], "backups": [], "sqlite": []}
blockers, stats, lines = [], {}, []
JOURNAL = None  # manifest.jsonl, appended and flushed per change so a crash mid-run stays restorable


def record(kind, entry):
    manifest[kind].append(entry)
    if JOURNAL:
        JOURNAL.write(json.dumps({"kind": kind, **(entry if isinstance(entry, dict) else {"path": entry})}) + "\n")
        JOURNAL.flush()


def log(s=""):
    lines.append(s)
    print(s, flush=True)


def stat(k, n=1):
    stats[k] = stats.get(k, 0) + n


# ------------------------------------------------------------------ primitives
def _copy_backup(path):
    """Copy path into the backup folder under a name no earlier backup uses: a file rewritten twice in one run
    (the live-writer re-check) keeps its FIRST, pre-run copy, which restore.py puts back."""
    base = os.path.join(BACKUP, os.path.splitdrive(os.path.abspath(path))[1].lstrip("\\/"))
    os.makedirs(os.path.dirname(base), exist_ok=True)
    dst, i = base, 0
    while os.path.exists(dst):
        i += 1
        dst = "%s.qmw%d" % (base, i)
    shutil.copy2(path, dst)
    return dst


def backup_file(path):
    dst = _copy_backup(path)
    record("backups", {"orig": os.path.abspath(path), "backup": dst})
    stat("bytes_backed_up", os.path.getsize(path))


def parses(path, data):
    low = path.lower()
    try:
        if low.endswith(".json"):
            json.loads(data.decode("utf-8-sig"))
        elif low.endswith(".jsonl"):
            for ln in data.split(b"\n"):
                if ln.strip():
                    json.loads(ln)
        elif low.endswith(".toml"):
            tomllib.loads(data.decode("utf-8"))
    except RecursionError:
        return True
    except Exception:
        return False
    return True


LIVE_TRIES = 5
LIVE_DONE = set()  # live files this run rewrote; the post-run re-check looks at these
LIVE_FAILED = set()  # live files that exhausted their retries: already a blocker, not retried or reported again


def _rewrite_live(path, fn):
    """Rewrite a file a running Claude Code session keeps appending to (history.jsonl, .claude.json).

    Read, recompute, write a temp copy, back up, then re-check (backup bytes == bytes read, size and
    mtime unchanged) immediately before os.replace. Any change since the read means a writer got in:
    discard the temp copy and backup and start again from a fresh read. After LIVE_TRIES the file is
    left untouched and reported as a blocker, so there is never a partial write. The few
    microseconds between the final check and os.replace are not closed (no cross-process lock exists)."""
    tmp = path + ".qmw-tmp"
    last_err = None
    for attempt in range(LIVE_TRIES):
        try:
            st = os.stat(path)
            data = open(path, "rb").read()
            st_read = os.stat(path)
            if (st.st_size, st.st_mtime_ns) != (st_read.st_size, st_read.st_mtime_ns):
                time.sleep(0.2)  # a writer got in during the read: the bytes may be torn
                continue
        except OSError as e:
            blockers.append("cannot read %s: %s" % (path, e))
            return 0
        new, n = pm.rewrite(data) if fn is None else fn(data)
        if n == 0:
            return 0
        if parses(path, data) and not parses(path, new):
            blockers.append("rewrite would break parsing of %s" % path)
            return 0
        bk, replaced = None, False
        try:
            with open(tmp, "wb") as f:
                f.write(new)
            bk = _copy_backup(path)
            st2 = os.stat(path)
            if open(bk, "rb").read() == data and (st2.st_size, st2.st_mtime_ns) == (st.st_size, st.st_mtime_ns):
                os.replace(tmp, path)
                replaced = True
        except OSError as e:
            last_err = e  # e.g. replace refused because a writer holds the file open: retried like a change
        if replaced:
            record("backups", {"orig": os.path.abspath(path), "backup": bk})
            stat("bytes_backed_up", len(data))
            stat("files_rewritten")
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
            LIVE_DONE.add(os.path.abspath(path))
            return n
        for junk in (tmp, bk):
            if junk and os.path.exists(junk):
                os.remove(junk)
        time.sleep(0.2)
    LIVE_FAILED.add(os.path.abspath(path))
    blockers.append("%s kept changing while it was rewritten (%d attempts%s); left unchanged. "
                    "Re-run the same command when no claude session is writing it (apply.py is idempotent; do not restore)."
                    % (path, LIVE_TRIES, "; last OS error: %s" % last_err if last_err else ""))
    return 0


def rewrite_file(path, fn=None, live=False, keep_mtime=True):
    """Whole-file replace (or fn(data)->(new, n)). Absent file = nothing to do. Returns hits.
    live=True: the file may be appended to while we work; see _rewrite_live (APPLY only).
    keep_mtime=False: the file takes the time of the rewrite (a store-repo STORE file, which the hook and
    verify-stores age by mtime: an old mtime would read as a change left uncommitted for days)."""
    if not os.path.isfile(path):
        return 0
    if live and APPLY:
        return _rewrite_live(path, fn)
    try:
        data = open(path, "rb").read()
    except OSError as e:
        blockers.append("cannot read %s: %s" % (path, e))
        return 0
    new, n = (fn or pm.rewrite)(data)
    if n == 0:
        return 0
    if parses(path, data) and not parses(path, new):
        blockers.append("rewrite would break parsing of %s" % path)
        return 0
    stat("files_rewritten")
    if APPLY:
        st = os.stat(path)
        backup_file(path)
        tmp = path + ".qmw-tmp"
        with open(tmp, "wb") as f:
            f.write(new)
        os.replace(tmp, path)
        if keep_mtime:
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    return n


def rename(src, dst, note=None):
    stat("renames")
    if os.path.exists(dst):
        blockers.append("rename target exists: %s" % dst)
        return False
    if APPLY:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)  # os.rename when on one volume; copy and delete across drives (the backup folder can be on another)
        record("renames", {"from": src, "to": dst, **({"note": note} if note else {})})
    return True


def rewrite_tree(root, skip=()):
    files = hits = 0
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip]
        for fn in fns:
            n = rewrite_file(os.path.join(dp, fn))
            files += bool(n)
            hits += n
    return files, hits


def field_only(name):
    """Rewrite only the value of one JSON string field (history.jsonl `project`)."""
    pat = re.compile(rb'("' + name.encode() + rb'"\s*:\s*")([^"]*)(")')

    def fn(data):
        count = [0]

        def sub(m):
            v, n = pm.rewrite(m.group(2))
            count[0] += n
            return m.group(1) + v + m.group(3)
        return pat.sub(sub, data), count[0]
    return fn


def first_cwd(path, limit=262144):
    try:
        with open(path, "rb") as f:
            m = re.search(rb'"cwd"\s*:\s*"([^"]*)"', f.read(limit))
        return m.group(1) if m else None
    except OSError:
        return None


def sqlite_rewrite(path, specs, label):
    """specs: [(table, [columns])]. Dry run counts on a scratch copy."""
    if not os.path.isfile(path):
        return
    work, tmp = path, None
    if APPLY:
        for e in ("", "-wal", "-shm"):
            if os.path.exists(path + e):
                backup_file(path + e)
    else:
        tmp = tempfile.mkdtemp(prefix="qmw_")
        work = os.path.join(tmp, "c.db")
        for e in ("", "-wal", "-shm"):
            if os.path.exists(path + e):
                shutil.copy2(path + e, work + e)
    total = 0
    try:
        con = sqlite3.connect(work, timeout=10)
        for table, cols in specs:
            have = {r[1] for r in con.execute('pragma table_info("%s")' % table)}
            for col in [c for c in cols if c in have]:
                # no SQL prefilter: a LIKE on the raw segment misses URL-encoded rows (`%20`); tables are small
                rows = con.execute('select rowid, "%s" from "%s"' % (col, table)).fetchall()
                for rowid, v in rows:
                    if v is None or not isinstance(v, (str, bytes)):
                        continue
                    raw = v if isinstance(v, bytes) else v.encode("utf-8")
                    new, n = pm.rewrite(raw)
                    if n:
                        total += 1
                        if APPLY:
                            nv = new if isinstance(v, bytes) else new.decode("utf-8")
                            con.execute('update "%s" set "%s"=? where rowid=?' % (table, col), (nv, rowid))
        if APPLY:
            con.commit()
            ok = con.execute("pragma integrity_check").fetchone()[0]
            con.execute("pragma wal_checkpoint(truncate)")
            if ok != "ok":
                blockers.append("integrity_check after update: %s -> %s" % (path, ok))
            record("sqlite", path)
        con.close()
    except sqlite3.Error as e:
        blockers.append("sqlite error on %s: %s" % (path, e))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    stat("sqlite_cells", total)
    log("  [sqlite] %-52s %d cell(s)" % (label, total))


def task_list():
    """[(image name, pid)] from tasklist, lower-cased. An unreadable listing is an error, never 'nothing running'."""
    r = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True)
    rows = []
    for ln in r.stdout.lower().splitlines():
        parts = ln.strip().strip('"').split('","')
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    if APPLY and (r.returncode != 0 or not rows):
        log("ABORT: cannot read the process list (tasklist exit %s), so running agents cannot be excluded." % r.returncode)
        sys.exit(2)
    return rows


def live_processes(tasks):
    pat = re.compile(r"^(claude|codex|kiro|kiro-cli|poweratlas|power-atlas|code|gemini)[^,]*\.exe$")
    return sorted({name for name, _ in tasks if pat.match(name)})


def gemini_nodes():
    """Gemini CLI runs as node.exe, so its image name says nothing: report node.exe processes whose command
    line names gemini. Read-only. -> (command lines, whether the query worked)."""
    ps = "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'node.exe' } | ForEach-Object { $_.CommandLine }"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True)
    except OSError:
        return [], False
    return [ln.strip() for ln in r.stdout.splitlines() if re.search("gemini", ln, re.I)], r.returncode == 0


def non_claude(procs):
    """--ignore-procs tolerates claude processes only: every other agent or editor still blocks."""
    return [p for p in procs if not p.startswith("claude")]


def live_sessions_in_trees(tasks):
    """Live claude sessions (~/.claude/sessions/<pid>.json whose pid is alive) with a cwd inside OLD or NEW.
    A pid can be reused by an unrelated process; that only causes a refusal, never a miss."""
    pids = {pid for _, pid in tasks}
    pm_new = PathMap(A.new, A.old)
    found = []
    for p in glob.glob(os.path.join(H, ".claude", "sessions", "*.json")):
        name_pid = os.path.splitext(os.path.basename(p))[0]
        try:
            d = json.loads(open(p, "rb").read())
            if not isinstance(d, dict):
                raise ValueError("not a JSON object")
        except Exception:
            if name_pid in pids:  # alive pid, unreadable record: its cwd cannot be shown to be outside the trees
                found.append("pid %s: %s is unreadable, so its cwd is unknown" % (name_pid, p))
            continue
        pid = str(d.get("pid") or name_pid)
        cwd = d.get("cwd") if isinstance(d.get("cwd"), str) else ""
        if pid in pids and (pm.search(cwd.encode("utf-8")) or pm_new.search(cwd.encode("utf-8"))):
            found.append("pid %s cwd %s" % (pid, cwd))
    return found


# ================================================================== main
log("MODE: %s   backup: %s" % ("APPLY" if APPLY else "DRY RUN (nothing changes)", BACKUP))
if APPLY and not A.no_predry:
    cmd = [sys.executable, os.path.abspath(__file__), "--old", A.old, "--new", A.new, "--work", A.work]
    if A.config_repo:
        cmd += ["--config-repo", A.config_repo]
    for x in A.also:
        cmd += ["--also", x]
    pre = subprocess.run(cmd, capture_output=True, text=True)
    if pre.returncode == 1:
        log("ABORT: the pre-flight dry run found blockers:\n" + pre.stdout[-3000:])
        sys.exit(1)
    log("pre-flight dry run: no blockers")
tasks = task_list()
live = live_processes(tasks)
gem, gem_ok = gemini_nodes()
if gem:
    live = sorted(live + ["node.exe running Gemini CLI (%s)" % gem[0][:120]])
if APPLY and not gem_ok:
    log("ABORT: cannot list node.exe command lines (the powershell query failed), so a running Gemini CLI cannot be "
        "excluded. Fix PowerShell on this machine, or ask the user to run the cutover after closing Gemini CLI.")
    sys.exit(2)
if live:
    if APPLY and not A.ignore_procs:
        log("ABORT: close these first (the stores are shared by every session): " + ", ".join(live))
        sys.exit(2)
    if APPLY and non_claude(live):
        log("ABORT: --ignore-procs tolerates claude processes only. Close these first (the stores are shared "
            "by every session): " + ", ".join(non_claude(live)))
        sys.exit(2)
    if APPLY:
        log("NOTE: --ignore-procs: claude process(es) stay alive (%s); history.jsonl and .claude.json are "
            "rewritten with a re-check" % ", ".join(live))
    else:
        log("NOTE (blocks --apply, unless only claude runs and --ignore-procs is set): running: " + ", ".join(live))
if A.ignore_procs and live:
    in_trees = live_sessions_in_trees(tasks)
    if in_trees and APPLY:
        log("ABORT: a live claude session has its cwd inside OLD or NEW (its transcripts would be rewritten under it). "
            "Close it first: " + "; ".join(in_trees))
        sys.exit(2)
    for s in in_trees:
        log("NOTE (blocks --apply): live claude session inside OLD or NEW: " + s)
sib = ambiguous_siblings(A.old)
# Folders beside OLD whose own path slugs to the same text (`a b` and `a-b`): Claude Code stores both under one name.
_parent, _base = os.path.split(A.old.rstrip("\\/"))
same_slug = []
try:
    same_slug = [n for n in os.listdir(_parent) if os.path.isdir(os.path.join(_parent, n)) and n.lower() != _base.lower() and slug(os.path.join(_parent, n)).lower() == pm.old_slug.lower()]
except OSError:
    pass
if sib:
    blockers.append("folders beside OLD whose paths would also match: %s. Rename them or move them in the same run." % sib)
if APPLY and blockers:
    log("ABORT before any change:\n  - " + "\n  - ".join(blockers))
    sys.exit(1)
if APPLY:
    # One folder per run, created exclusively: a second run in the same second must not share (and then
    # overwrite the manifest of) the first run's folder. A taken name gets -2, -3, ... after the stamp.
    os.makedirs(A.work, exist_ok=True)
    _base, _n = BACKUP, 1
    while True:
        try:
            os.mkdir(BACKUP)
            break
        except FileExistsError:
            _n += 1
            BACKUP = "%s-%d" % (_base, _n)
    if _n > 1:
        log("backup folder name was taken; using " + BACKUP)
    JOURNAL = open(os.path.join(BACKUP, "manifest.jsonl"), "a", encoding="utf-8")
    JOURNAL.write(json.dumps({"kind": "run", "stamp": STAMP, "started_ns": manifest["started_ns"]}) + "\n")
    JOURNAL.flush()

    def _dump_manifest():  # runs on every exit, including an uncaught exception mid-run
        json.dump(manifest, open(os.path.join(BACKUP, "manifest.json"), "w", encoding="utf-8"), indent=1)
    atexit.register(_dump_manifest)

# ---- Claude Code ------------------------------------------------------------
log("\n[Claude Code]")
proj = os.path.join(H, ".claude", "projects")
o = pm.old_slug.lower()


def _slug_taken(new_name, old_name):
    """The NEW slug folder already exists (e.g. a session started in NEW after the move): name the case."""
    if not os.path.exists(os.path.join(proj, new_name)):
        return False
    blockers.append("projects\\%s already exists (Claude Code made it for NEW), so projects\\%s cannot be renamed onto it. "
                    "Close the Claude sessions in NEW and move projects\\%s out of ~/.claude/projects (keep it, outside that "
                    "folder); re-run, so OLD's folder is rewritten and renamed to the NEW slug; then merge what you moved aside "
                    "back into the new projects\\%s (for the auto-memory folder: memory\\MEMORY.md and its topic files; keep the "
                    "newer file when both exist). Copying OLD's files into the NEW-slug folder by hand would keep OLD's paths." %
                    (new_name, old_name, new_name, new_name))
    return True


for d in sorted(os.listdir(proj)) if os.path.isdir(proj) else []:
    if d.lower() == o or d.lower().startswith(o + "-"):
        src = os.path.join(proj, d)
        # Slugs are lossy: a sibling `Repo-old` or `Repo old` slugs to `<old slug>-old` too. Rename a
        # folder only when one of its transcripts shows it belongs to OLD.
        owned = [p for p in glob.glob(os.path.join(src, "*.jsonl")) if (c := first_cwd(p)) and pm.search(c)]
        if not owned:
            # "No transcripts" = no *.jsonl file at any depth (session folders keep subagent transcripts below).
            if not any(fn.lower().endswith(".jsonl") for _, _, fns in os.walk(src) for fn in fns):
                kept = sorted(x for x in os.listdir(src) if x != "sessions-index.json")
                if not kept:
                    # Only (or not even) the session index: no session and no content to lose. Park it whole in
                    # the backup folder; restore.py moves it back.
                    rename(src, os.path.join(BACKUP, "claude-projects-parked", d), note="project folder without transcripts")
                    log("  projects\\%s holds only a session index: parked in the backup folder" % d)
                    continue
                if d.lower() == o and not sib and not same_slug:
                    # The exact slug of OLD with real content (auto-memory\\MEMORY.md and the like): that content
                    # belongs to OLD's workspace, so it follows it to the NEW slug instead of disappearing.
                    if _slug_taken(pm.new_slug, d):
                        continue
                    f, n = rewrite_tree(src)
                    rename(src, os.path.join(proj, pm.new_slug))
                    log("  projects\\%s holds no transcript but %s: -> %s  (%d files, %d hits)" %
                        (d, ", ".join(kept), pm.new_slug, f, n))
                    continue
                blockers.append("projects\\%s holds no transcript but %s, and cannot be confirmed as OLD's (%s); "
                                "not renamed. Move it aside by hand if it is not OLD's." %
                                (d, ", ".join(kept), "a sibling folder's name also matches (%s)" % ", ".join(list(sib) + same_slug) if d.lower() == o else "its name only starts with OLD's"))
                continue
            blockers.append("cannot confirm that projects\\%s belongs to OLD (no transcript cwd inside OLD); not renamed" % d)
            continue
        dst = pm.new_slug + d[len(pm.old_slug):]
        if _slug_taken(dst, d):
            continue
        f, n = rewrite_tree(src)
        rename(src, os.path.join(proj, dst))
        log("  projects\\%s -> %s  (%d files, %d hits)" % (d, dst, f, n))
log("  history.jsonl \"project\" fields: %d" % rewrite_file(os.path.join(H, ".claude", "history.jsonl"), field_only("project"), live=True))
for p in [os.path.join(H, ".claude.json"), os.path.join(H, ".claude", "settings.local.json"),
          os.path.join(H, ".claude", "daemon", "roster.json")] + \
        glob.glob(os.path.join(H, ".claude", "jobs", "*", "state.json")) + glob.glob(os.path.join(H, ".claude", "sessions", "*.json")):
    n = rewrite_file(p, live=os.path.basename(p) == ".claude.json")
    if n:
        log("  %-56s %d" % (os.path.relpath(p, H), n))

# ---- Codex ------------------------------------------------------------------
log("\n[Codex]")
cx = os.environ.get("CODEX_HOME") or os.path.join(H, ".codex")
for p in [os.path.join(cx, "config.toml"), os.path.join(cx, ".codex-global-state.json"),
          os.path.join(cx, "process_manager", "chat_processes.json"), os.path.join(cx, "rules", "default.rules")]:
    n = rewrite_file(p)
    if n:
        log("  %-56s %d" % (os.path.relpath(p, H), n))
roll = 0
for sub in ("sessions", "archived_sessions"):
    for dp, _, fns in os.walk(os.path.join(cx, sub)):
        for fn in fns:
            p = os.path.join(dp, fn)
            c = first_cwd(p) if fn.endswith(".jsonl") else None
            if c and pm.search(c) and rewrite_file(p):
                roll += 1
log("  rollouts whose session cwd is under OLD: %d" % roll)
for db, specs in [("state_5.sqlite", [("threads", ["cwd", "sandbox_policy"])]),
                  (os.path.join("sqlite", "state_5.sqlite"), [("threads", ["cwd", "sandbox_policy"])]),
                  (os.path.join("sqlite", "codex-dev.db"), [("local_thread_catalog", ["cwd"])])]:
    sqlite_rewrite(os.path.join(cx, db), specs, db + " " + specs[0][0])

# ---- Kiro CLI v3 ------------------------------------------------------------
log("\n[Kiro CLI v3]")
kb = os.path.join(H, ".kiro", "sessions")
hash_map = {}
for d in sorted(os.listdir(kb)) if os.path.isdir(kb) else []:
    dp = os.path.join(kb, d)
    if not re.fullmatch(r"[0-9a-f]{16}", d) or not os.path.isdir(dp):
        continue
    sess = [s for s in sorted(os.listdir(dp)) if s.startswith("sess_")]
    paths_of = {}
    for s in sess:
        try:
            paths_of[s] = json.loads(open(os.path.join(dp, s, "session.json"), "rb").read()).get("workspacePaths") or []
        except Exception:
            pass
    mine = [s for s, ps in paths_of.items() if any(pm.search(p.encode("utf-8")) for p in ps)]
    if not mine:
        continue
    ps0 = paths_of[mine[0]]
    if kiro_workspace_hash(ps0) != d:
        blockers.append("kiro hash formula does not reproduce %s from %r: re-verify it before moving anything" % (d, ps0))
        continue
    if len(mine) != len(sess):
        blockers.append("kiro dir %s mixes sessions inside and outside OLD" % d)
        continue
    new_h = kiro_workspace_hash([pm.rewrite_str(p) for p in ps0])
    hash_map[d] = new_h
    f = n = 0
    for s in mine:
        ff, nn = rewrite_tree(os.path.join(dp, s), skip=("snapshots",))  # snapshots are captured file content
        f, n = f + ff, n + nn
        rename(os.path.join(dp, s), os.path.join(kb, new_h, s))
    log("  %s -> %s  %d sessions, %d files (%d hits)" % (d, new_h, len(mine), f, n))
    # `.index/` is per-workspace shared state (its .lock and a session-list cache). Only once the
    # hash dir holds no sessions is it orphaned; kiro-cli rebuilds one in the new dir. Park it.
    rest = [x for x in os.listdir(dp) if not x.startswith("sess_")] if os.path.isdir(dp) else []
    if rest and set(rest) <= {".index"}:
        rename(dp, os.path.join(BACKUP, "kiro-v3-emptied-hash-dirs", d), note="orphaned .index cache")
    elif APPLY and os.path.isdir(dp) and not os.listdir(dp):
        os.rmdir(dp)
sidx = os.path.join(H, ".kiro", "session-index")
for old_h, new_h in hash_map.items():
    src = os.path.join(sidx, old_h + ".jsonl")
    if os.path.isfile(src):
        dst = os.path.join(sidx, new_h + ".jsonl")
        if os.path.exists(dst):
            blockers.append("session-index target exists: " + dst)
            continue
        stat("session_index_files")
        if APPLY:
            backup_file(src)
            open(dst, "wb").write(open(src, "rb").read().replace(old_h.encode(), new_h.encode()))
            os.remove(src)
            record("renames", {"from": src, "to": dst, "content_changed": True})
log("  session-index files remapped: %d" % stats.get("session_index_files", 0))
wr = os.path.join(H, ".kiro", "workspace-roots")
for d in sorted(os.listdir(wr)) if os.path.isdir(wr) else []:
    tm = os.path.join(wr, d, ".trust-migration.json")
    try:
        root = json.loads(open(tm, "rb").read()).get("root", "")
    except Exception:
        continue
    if pm.search(root.encode("utf-8")):
        if kiro_workspace_hash([root]) != d:
            blockers.append("workspace-roots/%s does not hash from its own root" % d)
            continue
        nh = kiro_workspace_hash([pm.rewrite_str(root)])
        rewrite_file(tm)
        rename(os.path.join(wr, d), os.path.join(wr, nh))
        log("  workspace-roots/%s -> %s" % (d, nh))
for p in glob.glob(os.path.join(H, ".kiro", "hooks", "*.json")):
    n = rewrite_file(p)
    if n:
        log("  hooks\\%s  %d" % (os.path.basename(p), n))

# ---- Kiro CLI v2 (retired, still on disk) -------------------------------------
log("\n[Kiro CLI v2]")
v2 = 0
for p in glob.glob(os.path.join(kb, "cli", "*.json")):
    try:
        cwd = json.loads(open(p, "rb").read()).get("cwd", "")
    except Exception:
        continue
    if cwd and pm.search(cwd.encode("utf-8")):  # the cwd field is JSON-escaped on disk; parse, then match
        v2 += 1
        rewrite_file(p)
        rewrite_file(p[:-5] + ".jsonl")
log("  sessions whose cwd is under OLD: %d" % v2)
sqlite_rewrite(os.path.join(H, "AppData", "Local", "Kiro-Cli", "data.sqlite3"),
               [("conversations_v2", ["key", "value"])], "Kiro-Cli data.sqlite3 conversations_v2")

# ---- editor recents (Kiro IDE, VS Code), Gemini, PowerAtlas -------------------
log("\n[editors, Gemini, PowerAtlas]")
for base, tag in ((os.path.join(H, "AppData", "Roaming", "Kiro", "User", "globalStorage"), "Kiro IDE"),
                  (os.path.join(H, "AppData", "Roaming", "Code", "User", "globalStorage"), "VS Code")):
    n = rewrite_file(os.path.join(base, "storage.json"))
    if n:
        log("  %s storage.json  %d" % (tag, n))
    for f in ("state.vscdb", "state.vscdb.backup"):
        sqlite_rewrite(os.path.join(base, f), [("ItemTable", ["value"])], "%s %s" % (tag, f))
gem = os.path.join(H, ".gemini")
g = sum(bool(rewrite_file(p)) for p in [os.path.join(gem, "projects.json")] +
        glob.glob(os.path.join(gem, "tmp", "*", ".project_root")) + glob.glob(os.path.join(gem, "history", "*", ".project_root")))
log("  Gemini projects.json + .project_root files: %d" % g)
log("  PowerAtlas config.toml: %d" % rewrite_file(os.path.join(H, "AppData", "Local", "power-atlas", "config.toml")))

# ---- agent-playbook machine state --------------------------------------------
if A.config_repo:
    log("\n[agent-playbook machine state in %s]" % A.config_repo)
    for rel in (os.path.join("memory", ".dream-state.json"), os.path.join(".kiro", "steering", "__store__.md")):
        n = rewrite_file(os.path.join(A.config_repo, rel))
        if n:
            log("  %-44s %d" % (rel, n))
# The pointer file (shared/AGENTS.md § Config Repo Locations) records root= and stores=: machine state, not
# governance text, so it follows the move like the files above.
n = rewrite_file(os.path.join(H, ".agent-playbook", "config"))
if n:
    log("  %-44s %d" % ("~/.agent-playbook/config", n))

# ---- agent-playbook store repo ------------------------------------------------
# A `local <path>` STORE line names its folder, so a store for a folder in OLD is re-keyed to NEW. A `remote` store
# keeps its identity when the checkout moves; a changed remote is the user's re-key step (SKILL.md). Directory names
# never change: resolution reads STORE content only.
sr = load_store_resolver()
log("\n[agent-playbook store repo %s]" % sr.store_repo_root())
st_, rws, inv, why = store_rewrites(sr, A.old, A.new)
if st_ == "missing":
    log("  no store repo: nothing to rewrite")
elif st_ != "ok":
    blockers.append("cannot scan the store repo: %s" % why)
for d, reason in inv:
    log("  invalid store left as is: %s (%s)" % (d, reason))
rekeyed = 0
for p, nb, note, blk in rws:
    if blk:
        blockers.append("store re-key collision: %s: %s" % (p, note))
        continue
    if rewrite_file(p, lambda data, nb=nb: (nb, int(data != nb)), keep_mtime=False):
        rekeyed += 1
        log("  %s -> %s" % (p, nb.decode("utf-8").strip()))
    if note:
        log("  WARNING %s" % note)
if rekeyed:
    log("  %s %d STORE file(s) in the store repo: commit that change in %s, or leave it for /qconfig-sync" %
        ("re-keyed" if APPLY else "would re-key", rekeyed, sr.store_repo_root()))

# ---- machine-local config inside the moved tree --------------------------------
log("\n[machine-local config under NEW]")
cands = set(A.also)
for pat in ("*/.vscode/settings.json", "*/.claude/settings.json", "*/.claude/settings.local.json",
            ".vscode/settings.json", ".claude/settings.json", ".claude/settings.local.json"):
    cands.update(glob.glob(os.path.join(A.new, pat)))
for p in sorted(cands):
    n = rewrite_file(p)
    if n:
        log("  %-56s %d" % (p, n))

# ---- live writers: confirm the rewrite held --------------------------------------
# A running claude session keeps its own copy of ~/.claude.json and history.jsonl and may write that copy
# back later, which would bring OLD's path back. Look again after a pause and rewrite again if it did.
if APPLY and A.ignore_procs and live:
    log("\n[live-writer re-check]")
    live_files = [(p, fn) for p, fn in ((os.path.join(H, ".claude", "history.jsonl"), field_only("project")),
                                        (os.path.join(H, ".claude.json"), None)) if os.path.abspath(p) in LIVE_DONE]

    def _stale():
        out = []
        for p, fn in live_files:
            if os.path.abspath(p) in LIVE_FAILED:
                continue
            try:
                if os.path.isfile(p) and (fn or pm.rewrite)(open(p, "rb").read())[1]:
                    out.append((p, fn))
            except OSError:
                pass
        return out
    stale = []
    for attempt in range(4 if live_files else 0):  # three rewrites at most; the last pass only confirms nothing came back
        time.sleep(3)
        stale = _stale()
        if not stale:
            break
        if attempt < 3:
            for p, fn in stale:
                log("  %s names OLD again: a live session wrote its own copy back; rewriting again" % p)
                rewrite_file(p, fn, live=True)
    for p, _fn in stale:
        blockers.append("%s names OLD again after the rewrite: a live claude session keeps writing its own copy. "
                        "Re-run the same command (idempotent) once that session is idle or closed; do not restore." % p)
    log("  re-check done")

# ---- summary -------------------------------------------------------------------
log("\n==== SUMMARY ====")
for k, v in sorted(stats.items()):
    log("  %-20s %s" % (k, "%.1f MB" % (v / 1048576) if k == "bytes_backed_up" else v))
if blockers:
    log("\nBLOCKERS (%d) - %s:" % (len(blockers), "the run is partly applied: fix the cause and re-run the same command (apply.py is "
                                  "idempotent); restore.py only undoes the whole migration" if APPLY else "--apply refuses until resolved"))
    for b in blockers:
        log("  - " + b)
else:
    log("\nNo blockers.")
os.makedirs(A.work, exist_ok=True)
if APPLY:
    os.makedirs(BACKUP, exist_ok=True)
    json.dump(manifest, open(os.path.join(BACKUP, "manifest.json"), "w", encoding="utf-8"), indent=1)
    log("manifest: " + os.path.join(BACKUP, "manifest.json"))
# One log per run, never overwritten: an apply log is named after its (exclusive) backup folder; a dry run
# takes the stamp and, if that log exists, -2, -3, ...
_tag = os.path.basename(BACKUP)[len("backup-"):] if APPLY else STAMP
_log, _k = os.path.join(A.work, ("apply-" if APPLY else "dryrun-") + _tag + ".log"), 1
while True:
    try:
        _fh = open(_log, "x", encoding="utf-8")
        break
    except FileExistsError:
        _k += 1
        _log = os.path.join(A.work, ("apply-" if APPLY else "dryrun-") + "%s-%d.log" % (_tag, _k))
with _fh:
    _fh.write("\n".join(lines))
sys.exit(1 if blockers else 0)
