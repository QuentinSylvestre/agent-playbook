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

The settings path is always given explicitly, so a sandboxed setup can never reach the real home. The
setup twins pass the prior value in the environment variable CONTEXT_FILENAME_PRIOR instead of --prior, as
Windows PowerShell 5.1 strips the quotes inside a native argument.

add: a string value becomes a list that keeps the existing name first; an absent value means Gemini's default
"GEMINI.md", so the list becomes ["GEMINI.md", NAME]; an absent file is created. Prints one line:
  present            NAME is already listed; nothing is written
  added <prior>      written; <prior> is the earlier value as compact JSON, or - when there was none
remove: takes NAME out again. When the rest equals <prior> (the value `add` printed), the prior shape comes
back: the string, or no key at all (and no `context` object, if that leaves it empty). Prints:
  removed | absent
Either command prints `unreadable <reason>` and exits 3, writing nothing, when the file does not parse as a
JSON object, or `context` or `context.fileName` has another type. Every other key is kept; the file is
re-serialized with its own indentation, line endings, byte-order mark and final newline. It is written
atomically, and not at all when it changed while being read. Exit 0 on success, 2 on a usage error.

Only `context.fileName` values are printed, never another key: settings.json can hold credentials.

Stdlib only, Python 3.8+.
"""
import argparse
import json
import os
import re
import sys

DEFAULT_NAME = "GEMINI.md"


class Unreadable(Exception):
    pass


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load(path):
    """-> (raw bytes or None when absent, settings dict, format)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, {}, {"indent": "  ", "eol": "\n", "bom": False, "final": True}
    except OSError as exc:
        raise Unreadable("cannot read %s (%s)" % (path, type(exc).__name__))
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
    fmt = {"indent": m.group(1) if m else "  ", "eol": "\r\n" if "\r\n" in text else "\n", "bom": bom,
           "final": text.endswith("\n") or not text.strip()}
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


def save(path, raw, data, fmt, dry_run):
    if dry_run:
        return
    text = json.dumps(data, ensure_ascii=False, indent=fmt["indent"])
    if fmt["final"]:
        text += "\n"
    text = text.replace("\n", fmt["eol"])
    out = (b"\xef\xbb\xbf" if fmt["bom"] else b"") + text.encode("utf-8")
    try:
        with open(path, "rb") as fh:
            now = fh.read()
    except FileNotFoundError:
        now = None
    if now != raw:
        raise Unreadable("it changed while setup was reading it")
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".%s.tmp-%d" % (os.path.basename(path), os.getpid()))
    with open(tmp, "wb") as fh:
        fh.write(out)
    os.replace(tmp, path)


def add(path, name, dry_run):
    raw, data, fmt = load(path)
    ctx, value = file_names(data)
    names = as_list(value)
    if name in names:
        return "present"
    if ctx is None:
        ctx = data["context"] = {}
    ctx["fileName"] = names + [name]
    save(path, raw, data, fmt, dry_run)
    return "added " + ("-" if value is None else compact(value))


def remove(path, name, prior, dry_run):
    raw, data, fmt = load(path)
    if raw is None:
        return "absent"
    ctx, value = file_names(data)
    if value is None or name not in as_list(value):
        return "absent"
    rest = [n for n in as_list(value) if n != name]
    if prior == "-":
        if rest == [DEFAULT_NAME]:
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
    save(path, raw, data, fmt, dry_run)
    return "removed"


def main(argv=None):
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
    try:
        if args.action == "add":
            print(add(args.settings, args.name, args.dry_run))
        else:
            print(remove(args.settings, args.name, args.prior, args.dry_run))
    except Unreadable as exc:
        print("unreadable " + str(exc))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
