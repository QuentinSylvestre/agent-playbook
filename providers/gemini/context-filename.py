#!/usr/bin/env python3
"""context-filename.py -- add or remove one name in Gemini CLI's `context.fileName` setting.

Both setup twins call this when a file of the user's own sits at ~/.gemini/GEMINI.md. The user's file stays,
setup links ~/.gemini/AGENT-PLAYBOOK.md to shared/AGENTS.md, and this script adds "AGENT-PLAYBOOK.md" to
`context.fileName` in ~/.gemini/settings.json so Gemini CLI loads both files.

The mechanism is source-read, not runtime-verified: in Gemini CLI 0.28.2, config.js:312 passes
`settings.context.fileName` to the core, and memoryDiscovery.js:93-100 reads ~/.gemini/<name> as global memory
for every name in that list (read 2026-11-12; a non-interactive run could not authenticate).

Usage:
  context-filename.py add --settings PATH --name NAME [--dry-run]
  context-filename.py remove --settings PATH --name NAME [--prior VALUE] [--dry-run]
  context-filename.py --selftest

The settings path is always given explicitly, so a sandboxed setup can never reach the real home. The
setup twins pass the prior value in the environment variable CONTEXT_FILENAME_PRIOR instead of --prior, as
Windows PowerShell 5.1 strips the quotes inside a native argument.

add: a string value becomes a list that keeps the existing name first; an absent value means Gemini's default
"GEMINI.md", so the list becomes ["GEMINI.md", NAME]; an absent file is created. An explicit empty list
(`"fileName": []`, "load no context file") becomes [NAME]: the playbook is still loaded, which is what setup
is there for. Prints one line:
  present            NAME is already listed; nothing is written
  added <prior>      written; <prior> is the earlier value as compact JSON, - when the file held no value,
                     or + when there was no file at all (setup created it)
remove: takes NAME out again. When the rest equals <prior> (the value `add` printed), the prior shape comes
back: the string, or no key at all (and no `context` object, if that leaves it empty); with prior + a file
left holding `{}` is deleted. With prior - or +, a list left empty loses the key too. Prints:
  removed | absent
Either command prints `unreadable <reason>` and exits 3, writing nothing, when the file cannot be edited: it
does not parse as plain JSON (Gemini CLI also accepts comments, JSONC, which this script cannot keep, so it
leaves such a file alone), `context` or `context.fileName` has another type, it is a link to a missing
file, it is read-only, or the write fails. Every other key is kept; the file is re-serialized with its own
indentation (a one-line file stays on one line), line endings, byte-order mark and final newline. It is
written atomically, beside the real file when settings.json is a link (the link stays), with the file's
own permission bits, and not at all when it changed while being read. Exit 0 on success, 2 on a usage
error; any other exit is a crash, which setup treats as unreadable.

Only `context.fileName` values are printed, never another key: settings.json can hold credentials. Output
is UTF-8 whatever the console's code page.

Stdlib only, Python 3.8+.
"""
import argparse
import json
import os
import re
import stat
import sys

DEFAULT_NAME = "GEMINI.md"
CREATED = "+"
NO_VALUE = "-"


class Unreadable(Exception):
    pass


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def target_of(path):
    """-> the file to read and write: settings.json itself, or the file a link there points to."""
    if not os.path.islink(path):
        return path
    real = os.path.realpath(path)
    if not os.path.exists(real):
        raise Unreadable("it is a link to a missing file (%s)" % real)
    return real


def load(path):
    """-> (raw bytes or None when absent, settings dict, format)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, {}, {"indent": "  ", "eol": "\n", "bom": False, "final": True, "flat": False}
    except OSError as exc:
        raise Unreadable("cannot read it (%s)" % type(exc).__name__)
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Unreadable("not UTF-8")
    if not text.strip():
        data = {}
    else:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise Unreadable("not plain JSON (%s)" % str(exc).split(":")[0])
    if not isinstance(data, dict):
        raise Unreadable("the top level is not a JSON object")
    m = re.search(r"\n([ \t]+)\S", text)
    flat = bool(text.strip()) and "\n" not in text.strip()
    fmt = {"indent": m.group(1) if m else "  ", "eol": "\r\n" if "\r\n" in text else "\n", "bom": bom,
           "final": text.endswith("\n") or not text.strip(), "flat": flat,
           "tight": flat and re.search(r"[,:][ \t]", text) is None}
    return raw, data, fmt


def file_names(data):
    """-> (context dict or None, the current value or None when absent)."""
    ctx = data.get("context")
    if ctx is None:
        return None, None
    if not isinstance(ctx, dict):
        raise Unreadable("context is not a JSON object")
    if "fileName" not in ctx:
        return ctx, None
    value = ctx["fileName"]
    if isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value)):
        return ctx, value
    raise Unreadable("context.fileName is not a string or a list of strings")


def as_list(value):
    if value is None:
        return [DEFAULT_NAME]
    return [value] if isinstance(value, str) else list(value)


def render(data, fmt):
    if fmt.get("flat"):
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":") if fmt.get("tight") else None)
    else:
        text = json.dumps(data, ensure_ascii=False, indent=fmt["indent"])
    if fmt["final"]:
        text += "\n"
    text = text.replace("\n", fmt["eol"])
    return (b"\xef\xbb\xbf" if fmt["bom"] else b"") + text.encode("utf-8")


def unchanged_since(path, raw):
    try:
        with open(path, "rb") as fh:
            now = fh.read()
    except FileNotFoundError:
        now = None
    except OSError as exc:
        raise Unreadable("cannot read it (%s)" % type(exc).__name__)
    if now != raw:
        raise Unreadable("it changed while setup was reading it")


def save(path, raw, out, dry_run):
    """Write `out` to path atomically (a temp file beside it, then a replace); None deletes the file."""
    if dry_run:
        return
    unchanged_since(path, raw)
    if raw is not None and not os.access(path, os.W_OK):
        raise Unreadable("it is read-only")
    if out is None:
        try:
            os.remove(path)
        except OSError as exc:
            raise Unreadable("cannot delete it (%s)" % type(exc).__name__)
        return
    folder = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(folder, ".%s.tmp-%d" % (os.path.basename(path), os.getpid()))
    try:
        os.makedirs(folder, exist_ok=True)
        with open(tmp, "wb") as fh:
            fh.write(out)
        if raw is not None:
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        os.replace(tmp, path)
    except OSError as exc:
        raise Unreadable("cannot write it (%s)" % type(exc).__name__)
    finally:
        if os.path.lexists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def add(settings, name, dry_run):
    path = target_of(settings)
    raw, data, fmt = load(path)
    ctx, value = file_names(data)
    names = as_list(value)
    if name in names:
        return "present", None
    if ctx is None:
        ctx = data["context"] = {}
    # an explicit [] means "load no context file": the playbook's name alone is listed then
    ctx["fileName"] = names + [name]
    line = "added " + (CREATED if raw is None else NO_VALUE if value is None else compact(value))
    return line, (path, raw, render(data, fmt))


def remove(settings, name, prior, dry_run):
    path = target_of(settings)
    raw, data, fmt = load(path)
    if raw is None:
        return "absent", None
    ctx, value = file_names(data)
    if value is None or name not in as_list(value):
        return "absent", None
    rest = [n for n in as_list(value) if n != name]
    if prior in (NO_VALUE, CREATED):
        if rest in ([DEFAULT_NAME], []):
            del ctx["fileName"]
            if not ctx:
                del data["context"]
        else:
            ctx["fileName"] = rest
    else:
        try:
            before = json.loads(prior)
        except ValueError:
            before = None
        ctx["fileName"] = before if before is not None and as_list(before) == rest else rest
    out = None if prior == CREATED and data == {} else render(data, fmt)
    return "removed", (path, raw, out)


def run(action, settings, name, prior, dry_run):
    """-> (line, exit code). The line is computed before anything is written, so a failure to print it
    can never leave a written file unreported."""
    try:
        if action == "add":
            line, write = add(settings, name, dry_run)
        else:
            line, write = remove(settings, name, prior, dry_run)
        if write is not None:
            save(write[0], write[1], write[2], dry_run)
    except Unreadable as exc:
        return "unreadable " + str(exc), 3
    return line, 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if s is not None and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(description="Add or remove one name in Gemini CLI's context.fileName.")
    ap.add_argument("action", choices=("add", "remove"))
    ap.add_argument("--settings", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--prior")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    args.prior = args.prior or os.environ.get("CONTEXT_FILENAME_PRIOR", "")
    if args.action == "remove" and not args.prior:
        ap.error("remove needs --prior or CONTEXT_FILENAME_PRIOR")
    line, code = run(args.action, args.settings, args.name, args.prior, args.dry_run)
    print(line)
    return code


# --- selftest -----------------------------------------------------------------

def selftest():
    import shutil
    import subprocess
    import tempfile
    fails, n = [], [0]
    skipped = []
    name = "AGENT-PLAYBOOK.md"

    def check(cond, label, detail=""):
        n[0] += 1
        if not cond:
            fails.append(label + (": " + detail if detail else ""))

    tmp = tempfile.mkdtemp(prefix="context-filename-selftest ")
    try:
        def fresh(sub, data=None):
            d = os.path.join(tmp, sub)
            os.makedirs(d)
            p = os.path.join(d, "settings.json")
            if data is not None:
                with open(p, "wb") as fh:
                    fh.write(data)
            return p

        def read(p):
            with open(p, "rb") as fh:
                return fh.read()

        # add / remove: a string value, other keys and the indentation kept, the string restored
        p = fresh("string", b'{\n    "context": {"fileName": "GEMINI.md"},\n    "keep": 1\n}\n')
        line, code = run("add", p, name, "", False)
        check((line, code) == ('added "GEMINI.md"', 0), "add to a string value", repr(line))
        check(json.loads(read(p))["context"]["fileName"] == ["GEMINI.md", name] and json.loads(read(p))["keep"] == 1,
              "add makes a list and keeps every other key", repr(read(p)))
        check(b'\n    "keep": 1' in read(p), "add keeps the file's own indentation", repr(read(p)))
        check(run("add", p, name, "", False) == ("present", 0), "a second add is present")
        line, code = run("remove", p, name, '"GEMINI.md"', False)
        check((line, code) == ("removed", 0) and json.loads(read(p)) == {"context": {"fileName": "GEMINI.md"}, "keep": 1},
              "remove restores the prior string", repr(read(p)))
        check(run("remove", p, name, '"GEMINI.md"', False) == ("absent", 0), "a second remove is absent")
        check(not [f for f in os.listdir(os.path.dirname(p)) if f != "settings.json"], "no temp file is left behind")

        # present: a list that already holds the name is never written
        p = fresh("present", b'{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}')
        before = read(p)
        check(run("add", p, name, "", False) == ("present", 0) and read(p) == before, "a listed name is present, unwritten")

        # no file: created, then deleted again by remove with prior +
        p = os.path.join(tmp, "created", "settings.json")
        check(run("add", p, name, "", True) == ("added +", 0) and not os.path.exists(p), "a dry-run add writes nothing")
        check(run("add", p, name, "", False) == ("added +", 0), "add with no file prints +")
        check(json.loads(read(p)) == {"context": {"fileName": ["GEMINI.md", name]}}, "add creates the file", repr(read(p)))
        check(run("remove", p, name, "+", False) == ("removed", 0) and not os.path.exists(p),
              "remove with prior + deletes the {} file setup created")

        # no value in an existing file: the key and the context object go again; prior - keeps the file
        p = fresh("novalue", b'{"theme": "dark"}')
        check(run("add", p, name, "", False) == ("added -", 0), "add with no value prints -")
        check(run("remove", p, name, "-", False) == ("removed", 0) and json.loads(read(p)) == {"theme": "dark"},
              "remove with prior - deletes the key and the context object", repr(read(p)))
        check(read(p) == b'{"theme": "dark"}', "a one-line file stays on one line", repr(read(p)))
        p = fresh("tight", b'{"theme":"dark"}\n')
        run("add", p, name, "", False)
        check(read(p) == b'{"theme":"dark","context":{"fileName":["GEMINI.md","AGENT-PLAYBOOK.md"]}}\n',
              "a minified file stays minified", repr(read(p)))

        # an explicit empty list: becomes [NAME]; a remove leaves no empty list behind
        p = fresh("empty", b'{"context": {"fileName": []}}')
        check(run("add", p, name, "", False) == ("added []", 0), "add to an empty list")
        check(json.loads(read(p))["context"]["fileName"] == [name], "an empty list becomes [NAME]", repr(read(p)))
        check(run("remove", p, name, "[]", False) == ("removed", 0)
              and json.loads(read(p)) == {"context": {"fileName": []}}, "remove restores the empty list", repr(read(p)))
        p = fresh("empty-rest", b'{"context": {"fileName": ["AGENT-PLAYBOOK.md"], "x": 1}}')
        check(run("remove", p, name, "-", False) == ("removed", 0) and json.loads(read(p)) == {"context": {"x": 1}},
              "remove with prior - never leaves fileName: []", repr(read(p)))

        # unreadable: JSONC, another type, not UTF-8 -- nothing written
        for sub, data, why in (("jsonc", b'{\n  // mine\n  "theme": "dark"\n}\n', "not plain JSON"),
                               ("list", b'[1]', "the top level"),
                               ("ctx", b'{"context": 3}', "context is not"),
                               ("names", b'{"context": {"fileName": [1]}}', "context.fileName is not"),
                               ("bytes", b'{"a": "\xff"}', "not UTF-8")):
            p = fresh(sub, data)
            line, code = run("add", p, name, "", False)
            check(code == 3 and line.startswith("unreadable ") and why in line and read(p) == data,
                  "unreadable (%s) writes nothing" % sub, repr(line))

        # a symlinked settings.json: written through the link, the link kept; a dangling link is unreadable
        d = os.path.join(tmp, "link")
        os.makedirs(os.path.join(d, "dotfiles"))
        real = os.path.join(d, "dotfiles", "gemini.json")
        with open(real, "wb") as fh:
            fh.write(b'{"theme": "dark"}\n')
        p = os.path.join(d, "settings.json")
        try:
            os.symlink(real, p)
            linked = True
        except (OSError, NotImplementedError):
            linked = False
            skipped.append("SKIP symlink cases: no symlink could be made")
        if linked:
            check(run("add", p, name, "", False) == ("added -", 0), "add through a link")
            check(os.path.islink(p) and json.loads(read(real))["context"]["fileName"] == ["GEMINI.md", name],
                  "the link stays and its target is written", repr(read(real)))
            check(not [f for f in os.listdir(os.path.dirname(real)) if f != "gemini.json"],
                  "no temp file is left beside the target")
            dangling = os.path.join(d, "dangling.json")
            os.symlink(os.path.join(d, "no-such.json"), dangling)
            line, code = run("add", dangling, name, "", False)
            check(code == 3 and "link to a missing file" in line and not os.path.exists(os.path.join(d, "no-such.json"))
                  and os.path.islink(dangling), "a dangling link is unreadable and stays", repr(line))

        # read-only: unreadable, nothing written; the mode bits of a writable file are kept
        p = fresh("readonly", b'{"theme": "dark"}')
        os.chmod(p, stat.S_IREAD)
        line, code = run("add", p, name, "", False)
        check(code == 3 and "read-only" in line and read(p) == b'{"theme": "dark"}', "a read-only file is unreadable",
              repr(line))
        os.chmod(p, stat.S_IREAD | stat.S_IWRITE)
        if os.name != "nt":
            p = fresh("mode", b'{"theme": "dark"}')
            os.chmod(p, 0o600)
            run("add", p, name, "", False)
            check(stat.S_IMODE(os.stat(p).st_mode) == 0o600, "the file keeps mode 0600",
                  oct(stat.S_IMODE(os.stat(p).st_mode)))

        # a failed write: unreadable, the file and the folder as they were (no temp left)
        p = fresh("writefail", b'{"theme": "dark"}')
        real_replace = os.replace

        def boom(a, b):
            raise PermissionError("held")
        os.replace = boom
        try:
            line, code = run("add", p, name, "", False)
        finally:
            os.replace = real_replace
        check(code == 3 and "cannot write" in line and read(p) == b'{"theme": "dark"}'
              and os.listdir(os.path.dirname(p)) == ["settings.json"], "a failed write leaves no temp", repr(line))

        # non-ASCII: printed as UTF-8 through a pipe whatever the code page, after the write
        p = fresh("utf8", '{"context": {"fileName": "名前.md"}}'.encode("utf-8"))
        env = dict(os.environ)
        env.pop("PYTHONIOENCODING", None)
        env.pop("PYTHONUTF8", None)
        r = subprocess.run([sys.executable, "-I", os.path.realpath(__file__), "add", "--settings", p, "--name", name],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        check(r.returncode == 0 and r.stdout.decode("utf-8").strip() == 'added "名前.md"' and not r.stderr,
              "a non-ASCII prior prints as UTF-8", repr((r.returncode, r.stdout, r.stderr[-200:])))
        check(json.loads(read(p))["context"]["fileName"] == ["名前.md", name], "the non-ASCII name is kept", repr(read(p)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for s in skipped:
        print(s)
    for f in fails:
        print("FAIL: " + f)
    print("context-filename selftest: %d failure(s), %d check(s), %d skipped" % (len(fails), n[0], len(skipped)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
