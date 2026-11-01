#!/usr/bin/env python3
"""verify-dream-journal.py -- deterministic grammar validator for the /qdream
crash-recovery journal (memory/.dream-journal.jsonl).

Validates each non-empty line against the JSONL record grammar (canonical
spec: shared/skills/qdream/memory-rules.md § Crash-recovery journal):
  - Exactly one key in {rename, remove}
  - Value is a 2-element array of non-empty strings
  - rename: BOTH elements must be fully-qualified targets
    (prefix: "user memory § " or "project memory (")
  - remove: first element (target) must be fq-prefixed;
    second element (class) checked against the canonical 8-class
    vocabulary (§ The rename/removal working map). Off-list -> WARN.

Torn-suffix tolerance: a JSON parse error on the LAST non-empty line
is WARNed (torn flush), not FAILed. A parse error on any interior
line, or a grammar-invalid line (parses but wrong structure) anywhere,
FAILs. A line nested too deeply to decode (RecursionError, e.g. 100000
"[") is that line's parse error, under the same rule. Missing/empty
file -> SKIP (exit 0): "SKIP: journal file not found (no active sweep)" or
"SKIP: journal file is empty". A path that exists but is not a regular file
(a directory, a dangling link) -> "SKIP: not a regular file: <path>" (exit 0).
dream-write.py's run_validator reads any SKIP over a path that exists as "did
not run", never as a pass.

A non-empty journal whose only non-empty line does not parse is a torn
suffix too: one WARN, "ok=0 fail=0 warn=1", exit 0. That line is also the
last one, and a sweep that crashed during its first journal flush leaves
exactly that file; FAILing it would halt recovery on the very crash the
journal exists to survive. The WARN keeps it visible.

Usage:
  verify-dream-journal.py [--help] [<journal-file>]
  verify-dream-journal.py --selftest

  <journal-file>  Path to the journal file. Default:
                  memory/.dream-journal.jsonl relative to repo root.

Output: "ok:" / "FAIL:" / "WARN:" lines + summary line
"verify-dream-journal: ok=N fail=M warn=W" on stdout (UTF-8, LF line
endings). Exit 0 when fail=0, else 1. A file that is not UTF-8 prints nothing on
stdout, a one-line reason on stderr, and exits 1 (a defect of the file). Exit
2, the guard did not run: a file that cannot be read (an OSError such as a
permission error; one-line reason on stderr), not run in the playbook venv
(the venv guard below), or any other unexpected exception, which prints nothing on stdout and
"verify-dream-journal.py: guard did not run: <reason>" on stderr.

Encoding: read as utf-8-sig, so a leading BOM never changes a verdict (the .sh
twin's Python did the same; the .ps1 twin's .NET UTF-8 reader strips it too).
Lines split on LF, CRLF or a lone CR (Python universal newlines, as .NET's
ReadAllLines); each line is stripped before parsing. JSON follows Python's
json module: a duplicate key keeps the last value, keys are case-sensitive, a
one-element top-level array is not an object, ISO-timestamp strings stay
strings, and lenient syntax (trailing commas, single quotes, comments) is a
parse error. The .ps1 twin (ConvertFrom-Json) differed on each of those; this
script keeps the Python behaviour.

--selftest runs the cases in fixtures/verify-dream-journal/ (expected.tsv
lists each case, its input journal or - for a missing path, and its exit
code; <case>.out holds the exact expected stdout). Every case runs in process;
the valid, signal (a FAIL), missing-file and deep-nesting cases also run as a
subprocess the way dream-write.py's run_validator launches it
([sys.executable, "-I", this file, <path>]), checking the CLI, LF stdout and
exit code. The fixtures directory as the path (the not-a-regular-file SKIP)
runs both ways. An injected read failure (exit 2, stderr reason) and an injected
unexpected exception (exit 2, did-not-run line) run in process. Prints
"verify-dream-journal selftest: N failure(s), M check(s), 0 skipped" and
exits 1 on any failure.

Python 3.8+, stdlib only. The Python successor of verify-dream-journal.{sh,ps1}
(plan 261016 Phase 13); dream-write.py's run_validator launches this script.
"""
import contextlib
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "verify-dream-journal")


# --- venv guard stub: identical in every qdream script (venv-selfcheck.py --selftest compares them) ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "venv-selfcheck.py")
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


VALID_KEYS = ("rename", "remove")
FQ_PREFIXES = ("user memory § ", "project memory (")
# Canonical 8 classes from memory-rules.md § The rename/removal working map
CLASSES = {
    "demoted",
    "pruned",
    "stale-entry deletion",
    "promotion-removal",
    "[improvement_signal] promotion-removal",
    "subsumption removal",
    "Delete entry",
    "expired_signal",
}

SKIP_MISSING = "SKIP: journal file not found (no active sweep)"
SKIP_EMPTY = "SKIP: journal file is empty"
SKIP_NOT_REGULAR = "SKIP: not a regular file: %s"


def default_path():
    return os.path.join(HERE, "..", "..", "..", "..", "memory", ".dream-journal.jsonl")


def _record(obj, lineno, out, counts):
    """Validate one parsed line; append its output lines and bump counts."""
    def ok(msg):
        counts[0] += 1
        out.append("ok: " + msg)

    def fail(msg):
        counts[1] += 1
        out.append("FAIL: " + msg)

    def warn(msg):
        counts[2] += 1
        out.append("WARN: " + msg)

    if not isinstance(obj, dict):
        return fail("line %d: not a JSON object" % lineno)
    if len(obj) != 1 or not set(obj).issubset(VALID_KEYS):
        return fail("line %d: must have exactly one key in {rename, remove}, got [%s]"
                    % (lineno, ", ".join(obj.keys())))
    key = next(iter(obj))
    val = obj[key]
    if not isinstance(val, list) or len(val) != 2:
        return fail("line %d: value must be a 2-element array" % lineno)
    if not all(isinstance(s, str) and s for s in val):
        return fail("line %d: array elements must be non-empty strings" % lineno)
    if key == "rename":
        for idx_e, elem in enumerate(val):
            if not elem.startswith(FQ_PREFIXES):
                return fail("line %d: rename element %d not fq-prefixed" % (lineno, idx_e))
    else:
        target, cls = val
        if not target.startswith(FQ_PREFIXES):
            return fail("line %d: remove target not fq-prefixed" % lineno)
        if cls not in CLASSES:
            warn("line %d: unknown removal class '%s'" % (lineno, cls))
    ok("line %d: valid %s record" % (lineno, key))


def _read_lines(path):
    """The journal's lines (the one read; the selftest replaces it to inject a failing read)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.readlines()


def check(path):
    """-> (exit code, stdout lines, stderr lines). Never prints."""
    if not os.path.isfile(path):
        if os.path.lexists(path):
            return 0, [SKIP_NOT_REGULAR % path], []
        return 0, [SKIP_MISSING], []
    try:
        raw_lines = _read_lines(path)
    except UnicodeDecodeError as exc:
        return 1, [], ["verify-dream-journal: %s is not UTF-8 (%s)" % (path, exc)]
    except OSError as exc:
        return 2, [], ["verify-dream-journal: cannot read %s (%s: %s)" % (path, type(exc).__name__, exc)]
    non_empty = [(i, line) for i, line in enumerate(raw_lines, 1) if line.strip()]
    if not non_empty:
        return 0, [SKIP_EMPTY], []
    last = non_empty[-1][0]
    out, counts = [], [0, 0, 0]
    for lineno, line in non_empty:
        try:
            obj = json.loads(line.strip())
        except (ValueError, RecursionError):  # RecursionError: nesting too deep to decode
            if lineno == last:
                counts[2] += 1
                out.append("WARN: line %d: parse error on last non-empty line (torn suffix)" % lineno)
            else:
                counts[1] += 1
                out.append("FAIL: line %d: JSON parse error on interior line" % lineno)
            continue
        _record(obj, lineno, out, counts)
    out.append("verify-dream-journal: ok=%d fail=%d warn=%d" % tuple(counts))
    return (0 if counts[1] == 0 else 1), out, []


def run_check(path):
    """check(), with any unexpected exception turned into exit 2 ("guard did not run") instead of a
    traceback that would exit 1 and read as a finding. -> (exit code, stdout lines, stderr lines)."""
    try:
        return check(path)
    except Exception as exc:
        return 2, [], ["verify-dream-journal.py: guard did not run: %s: %s" % (type(exc).__name__, exc)]


def _read_rows():
    rows = []
    with open(os.path.join(FIXTURES, "expected.tsv"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("case\t"):
                continue
            name, inp, code = line.split("\t")[:3]
            rows.append((name, inp, int(code)))
    return rows


def _fixture_path(inp):
    return os.path.join(FIXTURES, "does-not-exist.jsonl" if inp == "-" else inp)


def _expected(name):
    with open(os.path.join(FIXTURES, name + ".out"), "rb") as f:
        return f.read().decode("utf-8")


def selftest():
    fails, checks = [], [0]

    def chk(label, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (label, (": " + detail) if detail else ""))

    rows = _read_rows()
    chk("expected.tsv lists cases", len(rows) > 0)
    by_name = {}
    for name, inp, code in rows:
        by_name[name] = (inp, code)
        if inp != "-":
            chk("%s: input exists" % name, os.path.isfile(_fixture_path(inp)))
        try:
            rc, out, err = check(_fixture_path(inp))
        except Exception as exc:  # a crash of the code under test fails the case, not the run
            chk("%s: runs" % name, False, "%s: %s" % (type(exc).__name__, exc))
            continue
        got = "".join(l + "\n" for l in out)
        want = _expected(name)
        chk("%s: exit" % name, rc == code, "got %d, expected %d" % (rc, code))
        chk("%s: stdout" % name, got == want, "got %r, expected %r" % (got, want))
        if code == 1 and not out:
            chk("%s: stderr names the reason" % name, len(err) == 1, repr(err))
    # A path that exists but is not a regular file (the fixtures directory): its own SKIP, exit 0,
    # in process and as a subprocess; a missing path keeps the not-found SKIP (the missing-file row).
    rc, out, err = check(FIXTURES)
    chk("a directory: not-a-regular-file SKIP, exit 0",
        (rc, out, err) == (0, ["SKIP: not a regular file: " + FIXTURES], []), repr((rc, out, err)))
    r = subprocess.run([sys.executable, "-I", os.path.realpath(__file__), FIXTURES],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    chk("a directory (subprocess): exit 0, the SKIP line (LF)",
        r.returncode == 0 and r.stdout == ("SKIP: not a regular file: %s\n" % FIXTURES).encode("utf-8"),
        "got %d, %r" % (r.returncode, r.stdout[:300]))
    # Injected failures of the read and of the check itself (the reader is replaced, then restored).
    real_read = globals()["_read_lines"]
    vpath = _fixture_path("valid.jsonl")

    def deny(path):
        raise PermissionError(13, "Permission denied", path)

    def boom(path):
        raise RuntimeError("injected")
    try:
        globals()["_read_lines"] = deny
        rc, out, err = run_check(vpath)
        chk("cannot-read: exit 2, the guard did not run (not a pass)", rc == 2, "got %d" % rc)
        chk("cannot-read: no stdout", out == [], repr(out))
        chk("cannot-read: one stderr line naming the reason",
            len(err) == 1 and err[0].startswith("verify-dream-journal: cannot read ")
            and "PermissionError" in err[0], repr(err))
        globals()["_read_lines"] = boom
        rc, out, err = run_check(vpath)
        chk("unexpected exception: exit 2", rc == 2, "got %d" % rc)
        chk("unexpected exception: no stdout", out == [], repr(out))
        chk("unexpected exception: did-not-run line",
            err == ["verify-dream-journal.py: guard did not run: RuntimeError: injected"], repr(err))
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            rc = main([vpath])
        chk("unexpected exception via main: exit 2, did-not-run on stderr",
            rc == 2 and so.getvalue() == ""
            and se.getvalue() == "verify-dream-journal.py: guard did not run: RuntimeError: injected\n",
            "rc %r, stdout %r, stderr %r" % (rc, so.getvalue(), se.getvalue()))
    finally:
        globals()["_read_lines"] = real_read
    for name in ("valid", "signal", "missing-file", "deep-nesting"):
        if name not in by_name:
            chk("%s: row present for the subprocess check" % name, False)
            continue
        inp, code = by_name[name]
        r = subprocess.run([sys.executable, "-I", os.path.realpath(__file__), _fixture_path(inp)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        want = _expected(name).encode("utf-8")
        chk("%s (subprocess): exit" % name, r.returncode == code,
            "got %d, expected %d; stderr %r" % (r.returncode, code, r.stderr[:300]))
        chk("%s (subprocess): stdout bytes (LF)" % name, r.stdout == want,
            "got %r, expected %r" % (r.stdout[:300], want[:300]))
    for f in fails:
        print("FAIL: " + f)
    print("verify-dream-journal selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
    return 1 if fails else 0


def main(argv=None):
    _require_venv(__file__)
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--help":
        sys.stdout.write(__doc__)
        return 0
    if argv and argv[0] == "--selftest":
        return selftest()
    path = argv[0] if argv else default_path()
    rc, out, err = run_check(path)
    for line in out:
        sys.stdout.write(line + "\n")
    for line in err:
        sys.stderr.write(line + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
