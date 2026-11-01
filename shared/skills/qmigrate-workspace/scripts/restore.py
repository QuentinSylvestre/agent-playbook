"""Undo apply.py runs from a backup directory's manifest.json, or from a whole per-migration work folder.

  <python> restore.py <backup-dir | work-dir>            # dry run: prints what it would do
  <python> restore.py <backup-dir | work-dir> --apply    # does it (agents and editors closed)

A backup dir is <work>\\backup-<stamp>[-<n>]. Given the work dir itself (it holds backup-* folders), every
run is undone, newest first, so the oldest run's copies are put back last and the files end as they
were before the FIRST run. A re-run of apply.py (after a blocker, say) makes a second backup folder:
restoring the work dir covers it, restoring one backup dir covers only that run. Runs are ordered by the
UTC start time each manifest records (the folder stamp is local time and can go backwards), the folder
stamp being the fallback for older manifests.

Per run: reverse every rename (newest first), then copy every backed-up file back to its original
path. A file backed up more than once in one run (the live-writer re-check) is restored from its
FIRST copy, the pre-run bytes. SQLite databases come back together with their -wal/-shm companions.

A damaged manifest never stops the restore: manifest.json that does not parse falls back to the
manifest.jsonl journal (one torn last line, from a crash, is skipped), an entry that fails is counted as a
problem and the rest still run, and a run that cannot be read at all is counted and the OLDER runs are still
restored. Problems are always counted; the exit code is 1 if there is any (a dry run counts a missing backup
copy too). If the config repo's deployment symlinks were repointed, re-run its setup.ps1 from the OLD
checkout afterwards.
"""
import glob
import json
import os
import re
import shutil
import sys
import time

target = sys.argv[1]
APPLY = "--apply" in sys.argv


def has_manifest(d):
    return os.path.exists(os.path.join(d, "manifest.json")) or os.path.exists(os.path.join(d, "manifest.jsonl"))


def read_journal(jf):
    """Rebuild a manifest from the journal. Returns (manifest, problems). A torn LAST line is skipped; a bad
    line elsewhere is skipped and counted."""
    m, problems = {"renames": [], "backups": [], "sqlite": []}, 0
    raw = open(jf, encoding="utf-8", errors="replace").read().splitlines()
    for i, ln in enumerate(raw):
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
            kind = e.pop("kind")
        except (ValueError, KeyError, AttributeError):
            if i == len(raw) - 1 and not re.match(r'\s*\{\s*"kind"\s*:\s*"renames"', ln):
                print("  journal: the last line is torn (a crash mid-write); skipped")
            elif i == len(raw) - 1:
                # A torn rename record means a folder may have been moved with nothing written down to move it back.
                print("  PROBLEM: the last journal line is a torn RENAME record: a move may be unrecorded; check by hand")
                problems += 1
            else:
                print("  PROBLEM: journal line %d does not parse; skipped" % (i + 1))
                problems += 1
            continue
        if kind == "run":
            m.update({k: v for k, v in e.items() if k in ("stamp", "started_ns")})
        elif kind in m:
            m[kind].append(e)
        else:
            print("  PROBLEM: journal line %d has an unknown kind %r; skipped" % (i + 1, kind))
            problems += 1
    return m, problems


def load_run(bdir):
    """-> (manifest or None, problems)"""
    mf, jf = os.path.join(bdir, "manifest.json"), os.path.join(bdir, "manifest.jsonl")
    problems = 0
    if os.path.exists(mf):
        try:
            m = json.load(open(mf, encoding="utf-8"))
            if not isinstance(m, dict):
                raise ValueError("not a JSON object")
            return m, 0
        except (OSError, ValueError) as e:
            print("  PROBLEM: manifest.json does not parse (%s)" % e)
            problems += 1
    if not os.path.exists(jf):
        print("  PROBLEM: no usable manifest.json and no manifest.jsonl in", bdir)
        return None, problems + 1
    m, p = read_journal(jf)
    print("  rebuilt from manifest.jsonl (%d renames, %d backups)" % (len(m["renames"]), len(m["backups"])))
    return m, problems + p


def run_started(bdir):
    """UTC start time (ns) a run recorded, or None."""
    for name in ("manifest.json", "manifest.jsonl"):  # each source is tried even if the one before it is unreadable
        p = os.path.join(bdir, name)
        try:
            if name == "manifest.json":
                ns = json.load(open(p, encoding="utf-8")).get("started_ns")
            else:
                e = json.loads(open(p, encoding="utf-8", errors="replace").readline())
                ns = e.get("started_ns") if e.get("kind") == "run" else None
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(ns, int):
            return ns
    return None


def age_key(d):
    """One comparable (ns, suffix) for every run. A recorded UTC start is used as is; a run without one gets
    the time of its folder stamp (backup-<YYYYMMDD-HHMMSS>[-<n>], local time), so old and new runs mix correctly.
    The numeric suffix only breaks ties between runs of the same second."""
    m = re.fullmatch(r"backup-(\d{8}-\d{6})(?:-(\d+))?", os.path.basename(d))
    suffix = int(m.group(2) or 1) if m else 0
    ns = run_started(d)
    if not isinstance(ns, int):
        try:
            ns = int(time.mktime(time.strptime(m.group(1), "%Y%m%d-%H%M%S")) * 1_000_000_000)
        except (AttributeError, ValueError, OverflowError):
            ns = 0
    return (ns, suffix)


def restore_run(bdir):
    """Undo one apply.py run. Returns the number of problems."""
    print("restore from", bdir, "(APPLY)" if APPLY else "(dry run)")
    m, problems = load_run(bdir)
    if m is None:
        return problems
    for r in reversed(m.get("renames", [])):
        try:
            src, dst = r["to"], r["from"]
            ok = os.path.exists(src) and not os.path.exists(dst)
            print("  rename back  %s -> %s   %s" % (src, dst, "ok" if ok else "SKIP (source missing or target exists)"))
            if APPLY and ok:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)  # parked folders may sit on another drive than the store they came from
            elif not ok and not r.get("content_changed"):
                problems += 1
        except (OSError, KeyError, TypeError) as e:
            print("  PROBLEM: rename entry failed (%s): %r" % (e, r))
            problems += 1
    seen = set()
    for b in m.get("backups", []):
        try:
            if b["orig"] in seen:  # a later copy of the same file holds bytes written after the run began
                continue
            seen.add(b["orig"])
            print("  restore file %s" % b["orig"])
            if not os.path.exists(b["backup"]):  # checked in a dry run too, so a lost copy shows before --apply
                print("    PROBLEM: backup copy missing: %s" % b["backup"])
                problems += 1
                continue
            if APPLY:
                os.makedirs(os.path.dirname(b["orig"]), exist_ok=True)
                shutil.copy2(b["backup"], b["orig"])
        except (OSError, KeyError, TypeError) as e:
            print("  PROBLEM: backup entry failed (%s): %r" % (e, b))
            problems += 1
    return problems


if has_manifest(target):
    runs = [target]
else:
    runs = sorted((d for d in glob.glob(os.path.join(target, "backup-*")) if os.path.isdir(d) and has_manifest(d)), key=age_key, reverse=True)
    if not runs:
        print("no manifest.json or backup-* folder with a manifest under", target)
        sys.exit(1)
    print("work folder: %d run(s), newest first" % len(runs))
total = 0
for r in runs:
    try:
        total += restore_run(r)
    except Exception as e:  # one unreadable run must not stop the older ones
        print("  PROBLEM: run %s could not be restored (%s: %s); continuing with the older runs" % (r, type(e).__name__, e))
        total += 1
print("done; problems: %d" % total)
sys.exit(1 if total else 0)
