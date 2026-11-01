"""Copy an edited document over the user's file, only if that is still safe.

Refuses when the target is open in Word (a ~$ owner file exists) or no longer
matches the base copy your edit started from (the user saved in between; their
changes would be lost). In that case, copy the target again, diff it against
the base, re-apply your edit on top of it, and retry.

Usage:
    python safe_replace.py <edited.docx> <target.docx> --base <base_copy.docx> [--word]

--word checks, after copying, that Word opens the target without repair.

Exit codes: 0 = replaced, 1 = refused or post-copy check failed, 2 = usage error
"""
import hashlib
import os
import shutil
import sys

from word_com import lock_file


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Hash-guarded replacement of the user's .docx")
    parser.add_argument("edited")
    parser.add_argument("target")
    parser.add_argument("--base", required=True, help="the copy of target your edit started from")
    parser.add_argument("--word", action="store_true", help="check that Word opens the result")
    args = parser.parse_args()
    for p in (args.edited, args.target, args.base):
        if not os.path.isfile(p):
            print("missing file: %s" % p)
            sys.exit(2)

    lock = lock_file(args.target)
    if lock:
        print("REFUSED: target is open in Word (%s). Ask the user to close it." % lock)
        sys.exit(1)
    if sha256(args.target) != sha256(args.base):
        print("REFUSED: target changed since the base copy was taken. Rebase your edit on it.")
        sys.exit(1)
    tmp = args.target + ".replace-tmp"
    try:
        shutil.copyfile(args.edited, tmp)
        os.replace(tmp, args.target)  # atomic: the target is either old or new, never partial
    except OSError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print("REFUSED: replace failed (%s). The file may be open or syncing; target unchanged." % e)
        sys.exit(1)
    if sha256(args.target) != sha256(args.edited):
        print("FAILED: target does not match the edited file after copying")
        sys.exit(1)
    print("replaced %s" % args.target)
    if args.word:
        from verify_docx import word_opens
        if not word_opens(args.target):
            print("FAILED: Word does not open the replaced file without repair")
            sys.exit(1)
        print("Word opens it")
    sys.exit(0)


if __name__ == "__main__":
    main()
