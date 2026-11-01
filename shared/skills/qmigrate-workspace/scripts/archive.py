"""Archive the OLD tree to one zip before it is deleted, and prove the zip is complete.

  <python> archive.py build  --old <path> --zip <file.zip>
  <python> archive.py verify --old <path> --zip <file.zip>

build walks OLD through a \\\\?\\ prefix (paths over 260 characters were present on
2026-10-02), keeps empty directories, does not follow symlinks (they are listed in
<top>/SYMLINKS.txt inside the zip), and writes <zip>.manifest.json.
verify CRC-tests every member AND re-walks OLD now, so it fails if any file was added,
removed, resized or re-timestamped since the build. Delete OLD only after verify prints PASS.
Put the zip outside OneDrive and outside OLD. 7.75 GB of source took 11 minutes.
"""
import argparse
import json
import os
import sys
import time
import zipfile

ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["build", "verify"])
ap.add_argument("--old", required=True)
ap.add_argument("--zip", required=True)
A = ap.parse_args()
OLD, ZIP, MAN = A.old.rstrip("\\"), A.zip, A.zip + ".manifest.json"
TOP = os.path.basename(OLD) or "root"
LP = "\\\\?\\"


def walk():
    files, links, errs = {}, [], []
    stack, root_len = [LP + OLD], len(LP + OLD) + 1
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    rel = e.path[root_len:].replace("\\", "/")
                    try:
                        if e.is_symlink():
                            links.append((rel, os.readlink(e.path)))
                        elif e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                            if not os.listdir(e.path):
                                files[rel + "/"] = [0, 0]
                        else:
                            st = e.stat(follow_symlinks=False)
                            files[rel] = [st.st_size, st.st_mtime_ns]  # mtime catches a same-size edit
                    except OSError as ex:
                        errs.append((rel, str(ex)))
        except OSError as ex:
            errs.append((d, str(ex)))
    return files, links, errs


def build():
    if os.path.abspath(ZIP).lower().startswith(OLD.lower() + "\\"):
        sys.exit("the zip must not live inside OLD")
    t0 = time.time()
    files, links, errs = walk()
    print("source: %d entries, %d symlinks, %.2f GB" % (len(files), len(links), sum(v[0] for v in files.values()) / 2 ** 30), flush=True)
    if errs:
        sys.exit("walk errors: %s" % errs[:5])
    n = 0
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for rel in sorted(files):
            arc = TOP + "/" + rel
            if rel.endswith("/"):
                z.writestr(zipfile.ZipInfo(arc), b"")
                continue
            src = LP + OLD + "\\" + rel.replace("/", "\\")
            zi = zipfile.ZipInfo.from_file(src, arc, strict_timestamps=False)  # pre-1980 mtimes exist
            zi.compress_type = zipfile.ZIP_DEFLATED
            with open(src, "rb") as f, z.open(zi, "w", force_zip64=True) as w:
                for b in iter(lambda: f.read(1 << 20), b""):
                    w.write(b)
            n += 1
            if n % 20000 == 0:
                print("  %d files, %.0fs" % (n, time.time() - t0), flush=True)
        z.writestr(TOP + "/SYMLINKS.txt", "\n".join("%s -> %s" % x for x in links))
    json.dump({"files": files, "symlinks": links}, open(MAN, "w"))
    print("BUILT %s  %.2f GB  %d files  %.0fs" % (ZIP, os.path.getsize(ZIP) / 2 ** 30, n, time.time() - t0))


def verify():
    files = json.load(open(MAN))["files"]
    now, links, errs = walk()
    ok = not errs
    if now != files:
        ok = False
        print("OLD CHANGED since the build: +%d -%d" % (len(set(now) - set(files)), len(set(files) - set(now))))
    with zipfile.ZipFile(ZIP) as z:
        bad = z.testzip()
        names = {i.filename: i.file_size for i in z.infolist() if i.filename != TOP + "/SYMLINKS.txt"}
    exp = {TOP + "/" + k: v[0] for k, v in now.items()}
    miss, extra = set(exp) - set(names), set(names) - set(exp)
    wrong = [k for k in set(exp) & set(names) if exp[k] != names[k]]
    print("CRC: %s   members %d / expected %d   missing %d  extra %d  size mismatches %d" % (
        "all OK" if bad is None else "BAD " + bad, len(names), len(exp), len(miss), len(extra), len(wrong)))
    ok = ok and bad is None and not (miss or extra or wrong)
    print("VERIFY:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


{"build": build, "verify": verify}[A.cmd]()
