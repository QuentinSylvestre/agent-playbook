"""READ-ONLY checks for a workspace move.

  <python> verify.py pointers  --old <path>              session records that still LOCATE a session under OLD
  <python> verify.py residue   --old <path> --new <path> files under NEW that still name OLD (caches and logs skipped)
  <python> verify.py copy      --old <path> --new <path> [--exclude <rel> ...]   SHA-256 of every file, OLD vs NEW
  <python> verify.py predelete --old <path> --new <path> [--exclude <rel> ...]   files only in OLD, or newer there

`pointers` reads session-location fields only (first cwd, workspacePaths, slug folders,
catalogue rows), not prose: a transcript of another workspace that mentions OLD is history,
not a pointer. All four exit 1 when they find something.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathmap import PathMap  # noqa: E402

H = os.path.expanduser("~")
ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["pointers", "residue", "copy", "predelete"])
ap.add_argument("--old", required=True)
ap.add_argument("--new", default=r"C:\placeholder")
ap.add_argument("--exclude", action="append", default=[], help="path relative to OLD/NEW, e.g. a rebuilt venv")
A = ap.parse_args()
pm = PathMap(A.old, A.new)
LP = "\\\\?\\"
CWD = re.compile(rb'"cwd"\s*:\s*"([^"]*)"')
SKIP_DIRS = {".git", "node_modules", ".mypy_cache", "__pycache__", ".pytest_cache", ".ruff_cache", ".hypothesis",
             ".playwright-mcp", "build", "dist", "obj", "out", "target", ".tmp"}


def first_cwd(p):
    try:
        with open(p, "rb") as f:
            m = CWD.search(f.read(262144))
        return m.group(1) if m else None
    except OSError:
        return None


def pointers():
    found = 0

    def report(label, n, total, ex=()):
        nonlocal found
        found += n
        print("%-48s %d of %d" % (label, n, total))
        for e in list(ex)[:3]:
            print("    e.g.", e)
    tr = glob.glob(os.path.join(H, ".claude", "projects", "*", "*.jsonl"))
    bad = [p for p in tr if (c := first_cwd(p)) and pm.search(c)]
    report("Claude transcripts, first cwd under OLD", len(bad), len(tr), bad)
    o = pm.old_slug.lower()
    sl = [d for d in os.listdir(os.path.join(H, ".claude", "projects")) if d.lower() == o or d.lower().startswith(o + "-")]
    report("Claude project folders named from OLD", len(sl), len(sl), sl)
    # Files a live claude session keeps rewriting from its own copy: they can bring OLD back after the run.
    cj = os.path.join(H, ".claude.json")
    try:
        keys = list(json.loads(open(cj, "rb").read().decode("utf-8-sig")).get("projects", {})) if os.path.isfile(cj) else []
    except (OSError, ValueError):
        keys = []
    bad = [k for k in keys if pm.search(k.encode("utf-8"))]
    report("~/.claude.json project keys under OLD", len(bad), len(keys), bad)
    hp = os.path.join(H, ".claude", "history.jsonl")
    hist = [c for ln in (open(hp, "rb").read().split(b"\n") if os.path.isfile(hp) else [])
            if (m := re.search(rb'"project"\s*:\s*"([^"]*)"', ln)) and (c := m.group(1))]
    bad = [c for c in hist if pm.search(c)]
    report("history.jsonl \"project\" fields under OLD", len(bad), len(hist), [b.decode("utf-8", "replace") for b in bad])
    cx = os.environ.get("CODEX_HOME") or os.path.join(H, ".codex")
    ro = [os.path.join(dp, f) for s in ("sessions", "archived_sessions") for dp, _, fs in os.walk(os.path.join(cx, s)) for f in fs if f.endswith(".jsonl")]
    bad = [p for p in ro if (c := first_cwd(p)) and pm.search(c)]
    report("Codex rollouts, first cwd under OLD", len(bad), len(ro), bad)
    for db, tbl in (("state_5.sqlite", "threads"), (os.path.join("sqlite", "state_5.sqlite"), "threads"), (os.path.join("sqlite", "codex-dev.db"), "local_thread_catalog")):
        src = os.path.join(cx, db)
        if not os.path.isfile(src):
            continue
        t = tempfile.mkdtemp()
        try:
            for e in ("", "-wal", "-shm"):
                if os.path.exists(src + e):
                    shutil.copy2(src + e, os.path.join(t, "c.db" + e))
            con = sqlite3.connect(os.path.join(t, "c.db"))
            rows = [r[0] for r in con.execute('select cwd from "%s"' % tbl)]
            con.close()
        except sqlite3.Error as e:
            print("  unreadable %s: %s" % (db, e))
            continue
        finally:
            shutil.rmtree(t, ignore_errors=True)
        report("Codex %s %s.cwd under OLD" % (db, tbl), sum(1 for r in rows if r and pm.search(r.encode())), len(rows))
    kb = os.path.join(H, ".kiro", "sessions")
    sj = glob.glob(os.path.join(kb, "*", "sess_*", "session.json"))
    bad = []
    for p in sj:
        try:
            if any(pm.search(x.encode()) for x in json.loads(open(p, "rb").read()).get("workspacePaths") or []):
                bad.append(p)
        except Exception:
            pass
    report("Kiro v3 sessions, workspacePaths under OLD", len(bad), len(sj), bad)
    v2 = glob.glob(os.path.join(kb, "cli", "*.json"))
    bad = []
    for p in v2:
        try:
            c = json.loads(open(p, "rb").read()).get("cwd", "")
            if c and pm.search(c.encode()):
                bad.append(p)
        except Exception:
            pass
    report("Kiro v2 sessions, cwd under OLD", len(bad), len(v2), bad)
    return found


def residue():
    rows = []
    for dp, dns, fns in os.walk(A.new):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".venv")]
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, A.new).replace("\\", "/")
            if rel.endswith((".log", "coverage.xml")) or "/plans/done/" in "/" + rel or "/artifacts/" in "/" + rel:
                continue  # generated output and archived history, not configuration
            try:
                if os.path.getsize(p) > 20 * 1024 * 1024:
                    continue
                d = open(p, "rb").read()
            except OSError:
                continue
            n = len(pm.regex.findall(d)) + (len(pm.tilde[0].findall(d)) if pm.tilde else 0)
            if n:
                rows.append((rel, n))
    print("files under NEW that still name OLD (caches, logs, coverage, plans/done, artifacts skipped): %d" % len(rows))
    for r, n in sorted(rows):
        print("  %3d  %s" % (n, r))
    return len(rows)


def tree(root):
    out = {}
    base = LP + root
    for dp, dns, fns in os.walk(base):
        rel_dp = os.path.relpath(dp, base)
        dns[:] = [d for d in dns if os.path.normpath(os.path.join(rel_dp, d)) not in {os.path.normpath(x) for x in A.exclude}]
        for f in fns:
            p = os.path.join(dp, f)
            if os.path.islink(p):
                continue
            st = os.stat(p)
            out[os.path.normpath(os.path.join(rel_dp, f))] = (st.st_size, st.st_mtime)
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def copy():
    a = tree(A.old)

    def cmp(rel):
        b = LP + os.path.join(A.new, rel)
        if not os.path.exists(b):
            return rel, "MISSING"
        return rel, "ok" if sha(LP + os.path.join(A.old, rel)) == sha(b) else "DIFFERENT"
    bad = 0
    with ThreadPoolExecutor(8) as ex:
        for rel, st in ex.map(cmp, sorted(a)):
            if st != "ok":
                bad += 1
                print(st, rel)
    print("compared %d files: %s" % (len(a), "ALL IDENTICAL" if not bad else "%d PROBLEMS" % bad))
    return bad


def predelete():
    a, b = tree(A.old), tree(A.new)
    only = [r for r in a if r not in b]
    newer = [r for r in a if r in b and a[r][1] > b[r][1] + 2]
    print("files only in OLD: %d    newer in OLD than in NEW: %d" % (len(only), len(newer)))
    for r in (only + newer)[:50]:
        print("  ", r)
    return len(only) + len(newer)


sys.exit(1 if {"pointers": pointers, "residue": residue, "copy": copy, "predelete": predelete}[A.cmd]() else 0)
