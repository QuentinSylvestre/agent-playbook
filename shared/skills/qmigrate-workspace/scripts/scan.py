"""READ-ONLY inventory: where does OLD appear in the agent stores, and in what role?

  <python> scan.py --old <path> [--new <path>] [--report <file>]

Writes nothing except the optional report. SQLite databases are read from a
scratch copy (with -wal/-shm), never in place. Slow on large stores (about
10 minutes for 28 GB on 2026-10-02): run it in the background.
"""
import argparse
import collections
import os
import re
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathmap import PathMap  # noqa: E402

H = os.path.expanduser("~")
ap = argparse.ArgumentParser()
ap.add_argument("--old", required=True)
ap.add_argument("--new", default=r"C:\placeholder")
ap.add_argument("--report")
a = ap.parse_args()
pm = PathMap(a.old, a.new)

# (label, root, directory names to skip). Only stores an agent or editor keys by path.
STORES = [
    ("claude.json", os.path.join(H, ".claude.json"), set()),
    ("claude", os.path.join(H, ".claude"), {"file-history", "shell-snapshots", "debug", "cache", "plugins",
                                            "paste-cache", "downloads", "chrome", "skills", "skills.bak", "backups"}),
    ("codex", os.path.join(H, ".codex"), {"cache", ".tmp", "tmp", "plugins", "vendor_imports", "packages",
                                          "node_repl", "computer-use", ".sandbox", ".sandbox-bin", "generated_images", "skills"}),
    ("kiro", os.path.join(H, ".kiro"), {"skills", "extensions", "logs"}),
    ("gemini", os.path.join(H, ".gemini"), {"skills"}),
    ("kiro-cli appdata", os.path.join(H, "AppData", "Local", "Kiro-Cli"), set()),
    ("kiro-ide globalStorage", os.path.join(H, "AppData", "Roaming", "Kiro", "User", "globalStorage"), set()),
    ("kiro-ide workspaceStorage", os.path.join(H, "AppData", "Roaming", "Kiro", "User", "workspaceStorage"), set()),
    ("vscode User", os.path.join(H, "AppData", "Roaming", "Code", "User"), {"Cache", "CachedData", "logs", "History"}),
    ("power-atlas", os.path.join(H, "AppData", "Local", "power-atlas"), set()),
]
KEY = re.compile(rb'"([A-Za-z_][A-Za-z0-9_]{0,40})"\s*:\s*"?\[?\s*"?$')
out = []


def log(s=""):
    out.append(s)
    print(s, flush=True)


def is_sqlite(p):
    try:
        with open(p, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def scan_sqlite(p):
    res, tmp = [], tempfile.mkdtemp(prefix="qmw_")
    try:
        cp = os.path.join(tmp, "c.db")
        shutil.copy2(p, cp)
        for e in ("-wal", "-shm"):
            if os.path.exists(p + e):
                shutil.copy2(p + e, cp + e)
        con = sqlite3.connect("file:%s?mode=ro" % cp.replace("\\", "/"), uri=True)
        con.text_factory = bytes
        for (t,) in con.execute("select name from sqlite_master where type='table'"):
            t = t.decode()
            for c in [r[1].decode() for r in con.execute('pragma table_info("%s")' % t)]:
                try:
                    n = sum(1 for (v,) in con.execute('select "%s" from "%s"' % (c, t))
                            if isinstance(v, bytes) and pm.search(v))
                except sqlite3.Error:
                    continue
                if n:
                    res.append("    table %s.%s: %d rows" % (t, c, n))
        con.close()
    except (OSError, sqlite3.Error) as e:
        res.append("    unreadable: %s" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


def walk(root, skip):
    if os.path.isfile(root):
        yield root
        return
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip]
        for fn in fns:
            yield os.path.join(dp, fn)


for label, root, skip in STORES:
    if not os.path.exists(root):
        log("[%s] absent" % label)
        continue
    hit = occ = scanned = 0
    by_top, by_key, sample, sql = collections.Counter(), collections.Counter(), {}, {}
    for p in walk(root, skip):
        rel = os.path.relpath(p, root) if os.path.isdir(root) else os.path.basename(p)
        top = rel.split(os.sep)[0] if os.sep in rel else "(root)"
        if is_sqlite(p):
            r = scan_sqlite(p)
            if r:
                sql[rel] = r
            continue
        try:
            if os.path.getsize(p) > 400 * 1024 * 1024:
                continue
            data = open(p, "rb").read()
        except OSError:
            continue
        scanned += 1
        ms = list(pm.regex.finditer(data))
        if ms:
            hit += 1
            occ += len(ms)
            by_top[top] += 1
            sample.setdefault(top, rel)
            for m in ms[:40]:
                k = KEY.search(data[max(0, m.start() - 80):m.start()])
                by_key[k.group(1).decode("ascii", "replace") if k else "(not a json value)"] += 1
    log("[%s] %s\n  %d files scanned, %d mention OLD (%d occurrences)" % (label, root, scanned, hit, occ))
    for t, n in by_top.most_common(10):
        log("    %-34s %5d  e.g. %s" % (t, n, sample[t]))
    if by_key:
        log("  JSON keys holding OLD: " + ", ".join("%s=%d" % kv for kv in by_key.most_common(12)))
    for rel, lines in sql.items():
        log("  SQLITE " + rel)
        for ln in lines:
            log(ln)
    log()

proj = os.path.join(H, ".claude", "projects")
if os.path.isdir(proj):
    log("[claude project folders named from OLD]")
    for d in sorted(os.listdir(proj)):
        o = pm.old_slug.lower()
        if d.lower() == o or d.lower().startswith(o + "-"):  # boundary: '...-Perso' must not match '...-Personal'
            log("  " + d)
if a.report:
    open(a.report, "w", encoding="utf-8").write("\n".join(out))
