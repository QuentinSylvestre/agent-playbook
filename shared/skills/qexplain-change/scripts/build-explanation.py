#!/usr/bin/env python3
"""Build a /qexplain-change artifact from the shared template and the agent's content files.

The agent writes the parts that need judgement (brief, walkthrough, maps, diagram sources,
per-file rationales and roles). This script does the mechanical rest: captures the diff as
UTF-8, renders D2 diagrams, works out the provenance from git, builds the change summary,
inlines every piece of data safely, wires the tabs, drops the parts that were not selected,
then runs the validator on the result.

Standard library only; nothing to install. <python> is the interpreter the SKILL.md names, run with -I.

Usage:
    <python> build-explanation.py --out <path.html> --title <text> \
        (--diff-args "<git diff arguments>" [--repo <dir>] | --diff-file <unified.diff> --base <text> --head <text> \
         | --target "<label>=<repo>::<git diff arguments>" ...) \
        --brief <brief.html> --rationales <rationales.json> \
        [--parts brief,walkthrough,maps,summary,diff] [--walkthrough <walkthrough.html>] [--maps <maps.json>] \
        [--roles <roles.json>] [--notes <notes.json>] [--diagrams <dir>] [--id <text>] [--ticket <text>]... [--link <label>=<url>]... \
        [--base <text>] [--head <text>] [--exclude <glob>]... \
        [--allow-credential <path>:<side>:<line>]... [--mask-credential ...]... [--user-confirmed-credential ...]...
    <python> build-explanation.py --selftest
    <python> build-explanation.py --comments-only --out <page.html> --replies <dir>/replies.json [--comments-from <page copy>]

--parts lists the parts to emit. Brief is always emitted. Walkthrough needs --walkthrough, Maps needs
--maps, Change summary needs --rationales (always given), Diff review needs nothing more. The default is
"brief,diff". A part that is not listed has neither its button nor its panel in the page.

--target may repeat, one per repo. Each repo's paths then start with <label>/, and rationales.json and
roles.json use those labelled paths. --base and --head are optional with --diff-args and --target: the
build reads the base and head from git. They are required with --diff-file, which has no git to read.

--exclude leaves a file out of the page, on top of a built-in list of secret-bearing file
names. The page names each file left out, with its line counts and never its content.

Any remaining credential-shaped text stops the build, with its path and line and never its
value. Exclude the file, or pass --allow-credential with the match's path, side and line as
measure-change.py prints them (for example a_test.go:new:12), which the build accepts only for
a match marked made-up-test-value=yes. --mask-credential takes the same form for any match: it
replaces the value on the page and keeps the rest of the file, so prefer it for a test file.
--user-confirmed-credential is for a match the user has personally said is not a live credential.
Text in the content files, diagram sources, --ticket, --link, title and refs cannot be allowed; reword it.

--shots is a folder of screenshots (png, jpg, jpeg, gif, webp). In brief.html or walkthrough.html, write
<figure data-shot="orders.png">caption</figure> where the picture belongs, and add data-before="orders-old.png" when
you also have the screen as it was. One picture may weigh 2 MiB at most; the page has no limit on their number.
A figure without data-shot is left as you wrote it.

--lang is the language code of the prose you wrote (default en). It sets the page's lang attribute and nothing
else: the page's own labels stay in English.

Comments live in the page file, in blocks of data placed before the page's script. The page writes one block when
a reader saves; this script adds one when you reply. Only the page merges them, each time it opens. A rebuild
keeps the blocks of the page it replaces (the file at --out), and those of --comments-from <page> when the reader
gives you the page under another name.

--replies is replies.json, your answers to comments: {"by": "<name of the person you work for>", "replies":
[{"to": "<comment id>", "text": "Addressed: ..."}, ...]}. "by" is optional. The id of a comment is in the feedback
text. A reply already in the page is not added twice: a reply is known by its comment, its author and its words, so
the same words to the same comment in a later round are not added again, and a WARN says so. Reword it.

--comments-only adds the replies to the page at --out and changes nothing else in it. Use it when you answer
comments without changing the page, or when you were given a page and not its content files. It needs only --out
and --replies. It scans the replies for credential-shaped text; it has no diff, so it cannot tell that a reply
quotes a value the diff holds behind a CREDENTIAL flag, as a full build does. Never quote such a value.

Content files:
    brief.html          HTML fragment, placed in the Brief panel. Heading ids are fixed and checked by the
                        validator: intent, context, change-<name> (one or more), then optional decisions,
                        precedent, deploy, surface, then verified and open-items, in that order.
    walkthrough.html    HTML fragment. To get one sub-tab per subsystem, wrap each subsystem in
                        <section data-subsystem="Name"> ... </section>. Text outside the sections stays above or below the tabs.
    maps.json           {"views": [view, ...]}. A view has "key" (system, dataflow, deps, actions, sequence),
                        "label", "diagram" (a diagram name, below), optional "note", optional "subsystem" (views
                        with the same subsystem share a sub-tab) and optional "tour": [{"caption": text,
                        "highlight": [ids]}]. D2 ids are D2 object ids, such as site.mistap for a node and
                        (site.bl -> gw.http)[0] for a connection; the build resolves them against the rendered
                        diagram and fails on an unknown id, listing the valid ones. Mermaid flowchart ids are node
                        ids. Mermaid sequence "highlight" entries are text fragments of a participant, message or note.
    rationales.json     {"path/in/diff": "One sentence on why it changed.", ...}
    notes.json          optional: [{"path": "path/in/diff", "line": 12, "note": "..."}, ...] with "side": "old" and "end": 14 when needed
    roles.json          {"path/in/diff": "One sentence on what the file does.", ...} (optional; feeds Change summary)
    diagrams/           with --diagrams <dir>: <name>.d2 (D2) or <name>.mmd (Mermaid), never both for one name.

Diagram placeholder: in brief.html and walkthrough.html write <div data-diagram="name"></div> where a
diagram goes. The build replaces it with the diagram named <name> from the --diagrams folder. In maps.json
the view's "diagram" field names it. D2 sources are rendered with the ELK layout (dagre for sequence diagrams)
in four variants (sketch or classic, light or dark) and inlined. The build prepends a class set, so write
"class: new" and not a colour: new, changed, existing, removed, decision, step, question, container, and for
connections new-edge, changed-edge, removed-edge. A Mermaid source is drawn by the page. An icon:, @import or
...@ import in a D2 source is refused. d2 is found on PATH, or from the QEXPLAIN_D2 environment variable.

Exit codes:
    0  built, and every validator check passed (or the selftest passed)
    1  built, but a validator check FAILed (or the selftest failed)
    2  bad input; nothing written
"""

import argparse
import base64
import hashlib
import datetime
import html
import html.entities
import io
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I leaves the script's folder off the path
import qexplain_change_diff as qd  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "assets", "template.html")
VALIDATOR = os.path.join(HERE, "validate-explanation.py")
VIEW_ORDER = ["system", "dataflow", "deps", "actions", "sequence"]
PART_ORDER = ["brief", "walkthrough", "maps", "summary", "diff"]
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
# The page's content security policy (assets/template.html) allows scripts from the host of these two addresses and
# from no other. A script from another host needs that policy changed too; the self-test checks the two agree.
# Syntax colours for the Diff review part: the common build (36 languages). Loaded with async, so a page with no
# network is not held back and shows its diff uncoloured.
HLJS_URL = "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.11.1/highlight.min.js"
# The hash of each file, as the browser checks it (subresource integrity): a file the host changed does not run.
# A new version needs its new hash: base64 of the SHA-384 of the file, after "sha384-".
MERMAID_SRI = "sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2"
HLJS_SRI = "sha384-RH2xi4eIQ/gjtbs9fUXM68sLSi99C7ZWBRX1vDrVv6GQXRibxXLbwO2NGZB74MbU"
D2_TIMEOUT = 60
PLACEHOLDER = re.compile(r"""<div\s+data-diagram=["']([A-Za-z0-9._-]+)["']\s*>\s*</div>""")
SECTION = re.compile(r"""<section\s+data-subsystem=["']([^"']+)["']\s*>(.*?)</section>""", re.S)
SEQ_D2 = re.compile(r"^\s*shape\s*:\s*sequence_diagram", re.M)
SEQ_MMD = re.compile(r"\A(?:\s*(?:%%[^\n]*|---.*?---)\s*)*sequenceDiagram\b", re.S)
LANG_CODE = re.compile(r"\A[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}\Z")
MMD_ENTITY = re.compile(r"#(?:\d+|[A-Za-z][A-Za-z0-9]*);")
MMD_NAMED = re.compile(r"#([A-Za-z_][A-Za-z0-9_]*);")
MMD_STYLE_LINE = re.compile(r"\s*(?:%%|style\b|classDef\b|linkStyle\b)")
EDGE_ID = re.compile(r"^(?:(?P<pre>.+)\.)?\((?P<a>.+?) (?:->|<->|<-|--) (?P<b>.+?)\)\[\d+\]$")

# D2 class palette, written out per theme. The agent writes "class: new", never a colour.
# Each entry is fill, stroke, font colour and extra style lines.
PALETTE = {
    "light": {
        "new": ("#e2f1ef", "#0f766e", "#10302d", {}),
        "changed": ("#fde3a7", "#b45309", "#3a2405", {"stroke-width": "3"}),
        "existing": ("#eef1f4", "#9aa5b2", "#1d2530", {}),
        "removed": ("#fbe9e7", "#b3261e", "#5a1410", {"stroke-dash": "4"}),
        "decision": ("#fbf0e1", "#a45d07", "#3a2405", {}),
        "question": ("#fbf0e1", "#a45d07", "#3a2405", {}),
        "step": ("#e8eef7", "#5b7bb5", "#14243d", {}),
        "container": ("#f7f8f9", "#c3cad2", "#1d2530", {}),
    },
    "dark": {
        "new": ("#15302e", "#4fc4b6", "#d7f3ef", {}),
        "changed": ("#4a3a12", "#e7a64c", "#f6e2c2", {"stroke-width": "3"}),
        "existing": ("#222a33", "#5a6573", "#e3e8ee", {}),
        "removed": ("#3a1a18", "#f08a82", "#f7d3d0", {"stroke-dash": "4"}),
        "decision": ("#33280f", "#e7a64c", "#f6e2c2", {}),
        "question": ("#33280f", "#e7a64c", "#f6e2c2", {}),
        "step": ("#1c2638", "#7ea0d8", "#d4e2f7", {}),
        "container": ("#13171c", "#3a424c", "#e3e8ee", {}),
    },
}
EDGE_PALETTE = {
    "light": {"new-edge": ("#0f766e", {"stroke-width": "3"}), "changed-edge": ("#b45309", {"stroke-width": "3"}),
              "removed-edge": ("#b3261e", {"stroke-dash": "4"})},
    "dark": {"new-edge": ("#4fc4b6", {"stroke-width": "3"}), "changed-edge": ("#e7a64c", {"stroke-width": "3"}),
             "removed-edge": ("#f08a82", {"stroke-dash": "4"})},
}


def fail(msg):
    """Stop with nothing written. Every message says what is wrong and what to do next."""
    print(f"ERROR\t{msg}", file=sys.stderr)
    sys.exit(2)


def step(msg):
    """One line per stage, so a reader of the output knows what the build is doing while it works."""
    print(f"STEP\t{msg}", flush=True)


def read(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read {path} as UTF-8: {exc}. Check the path, and save the file as UTF-8")


# The comments of a page live in the page file, in blocks of data between two markers placed before the page's script.
# The page writes one block when a reader saves, and this script adds one when an agent replies. Only the page merges
# them: here a block is copied as it is written, or added, and never read for more than its ids.
CM_OPEN, CM_SHUT = "<!--qx-comments-->", "<!--/qx-comments-->"
CM_BLOCK = re.compile(r'<script type="application/json" class="qx-comments">([^<]*)</script>')
REPLY_MAX = 4000
REPLY_TO = re.compile(r"^[\w.:+-]{1,80}$", re.ASCII)       # the shape of a comment id, as the page accepts it


def comments_region(text):
    """Where the blocks stand in a page text: between the last pair of markers. None when the page has no such place."""
    a = text.rfind(CM_OPEN)
    b = text.find(CM_SHUT, a) if a >= 0 else -1
    return None if a < 0 or b < 0 else (a + len(CM_OPEN), b)


def page_blocks(path, page_id):
    """The comments blocks of the page at path, as written, with their data. A block that cannot be read, or that
    belongs to another explanation, is left out and said."""
    if not path or not os.path.isfile(path):
        return []
    text = read(path)
    region = comments_region(text)
    kept = []
    for m in CM_BLOCK.finditer(text[region[0]:region[1]] if region else ""):
        try:
            data = json.loads(m.group(1))
        except (ValueError, RecursionError):
            data = None
        if isinstance(data, dict) and data.get("id") == page_id and isinstance(data.get("items"), list):
            kept.append((m.group(0), data))
        else:
            print(f"WARN\ta comments block of {path} cannot be read or belongs to another explanation; it is not in the page this build writes")
    return kept


def known_ids(blocks):
    """Every comment id the blocks hold or record as deleted: a reply with one of these ids is in the page already."""
    ids = set()
    for _, data in blocks:
        ids.update(c["id"] for c in data["items"] if isinstance(c, dict) and isinstance(c.get("id"), str))
        ids.update(k for k in (data["gone"] if isinstance(data.get("gone"), dict) else {}) if isinstance(k, str))
    return ids


NOT_A_PERSON = re.compile(r"(?:(?:the|my|your|an?) )?(?:ai )?(?:agent|assistant)", re.I)


def reply_author(by):
    """The name shown beside an agent's reply. "by" is the person the agent works for; an agent that names itself
    there (a Kiro run wrote "Agent") gives no name, so the reply is not signed "Agent's agent"."""
    by = " ".join(by.split())[:60]
    return "Agent" if not by or NOT_A_PERSON.fullmatch(by) else f"{by}'s agent"


def reply_block(path, page_id, known):
    """replies.json as one comments block. The id of a reply comes from what it says and to which comment, so the same
    reply given twice is one reply, and one the reader deleted does not come back."""
    data = read_json(path)
    by = ""
    if isinstance(data, dict):
        by, data = data.get("by", ""), data.get("replies")
    shape = ('Write {"by": "<name of the person you work for>", "replies": [{"to": "<comment id>", "text": "..."}]}; '
             '"by" is optional, and the id of a comment is in the feedback text')
    if not isinstance(by, str) or not isinstance(data, list) or not data:
        fail(f"{path} holds no list of replies. {shape}")
    author = reply_author(by)
    now, items = int(time.time() * 1000), []
    for i, r in enumerate(data):
        if not (isinstance(r, dict) and isinstance(r.get("to"), str) and r["to"].strip() and isinstance(r.get("text"), str) and r["text"].strip()):
            fail(f'{path}: reply {i + 1} needs "to" (a comment id) and "text", both non-empty text. {shape}')
        to, text = r["to"].strip(), r["text"].strip()
        if not REPLY_TO.match(to):
            fail(f'{path}: reply {i + 1} has a "to" that is not a comment id. Copy the id from the line "Id: ..." under the comment in the feedback text')
        if len(text) > REPLY_MAX:
            fail(f"{path}: reply {i + 1} is {len(text)} characters long; the limit is {REPLY_MAX}. Say it shorter, and put the detail in the page itself")
        rid = "r" + hashlib.sha1("\n".join((to, author, text)).encode("utf-8")).hexdigest()[:12]
        if rid in known or any(x["id"] == rid for x in items):
            print(f"WARN\treply {i + 1} to {qd.safe_path(to)} is in the page already, or was deleted there by a reader; not added again. "
                  "To say it again, say it in other words")
            continue
        items.append({"id": rid, "re": to, "by": author, "agent": True, "text": text, "t": now + i, "kind": "reply", "part": "page", "quote": "", "state": "open"})
    if not items:
        return "", 0
    block = {"v": 1, "id": page_id, "saved": now, "items": items, "gone": {}, "edits": {}}
    return '<script type="application/json" class="qx-comments">' + script_json(block) + "</script>", len(items)


def replies_said(path):
    """What replies.json says, decoded: the text a check for a quoted value must look at."""
    try:
        data = json.loads(read(path))
    except (ValueError, RecursionError):
        return ""
    items = data.get("replies") if isinstance(data, dict) else data
    said = [str(data.get("by", ""))] if isinstance(data, dict) else []
    for r in (items if isinstance(items, list) else []):
        said += [str(v) for v in r.values()] if isinstance(r, dict) else []
    return "\n".join(said)


def scan_replies(path):
    """An agent's replies go into the page: they are scanned like every other text the agent writes."""
    hits = qd.scan_content_file("replies.json", read(path))
    if hits:
        for hit in hits:
            print(qd.hit_line(hit), file=sys.stderr)
        fail("credential-shaped text found in replies.json; nothing written. Reword the reply: say what kind of value it is, never quote it")


def comments_only(args):
    """Adds replies to an existing page and changes nothing else in it."""
    if not args.out or not args.replies:
        fail("--comments-only needs --out <the page> and --replies <replies.json>")
    try:
        with open(args.out, "r", encoding="utf-8", newline="") as fh:       # line ends as they are: nothing else in the page may change
            text = fh.read()
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read {args.out} as UTF-8: {exc}. Check the path")
    region = comments_region(text)
    at = text.find("const QX = ", region[1]) if region else -1             # the page's own data follows the place of the blocks
    try:
        page_id = json.JSONDecoder().raw_decode(text, at + len("const QX = "))[0]["id"] if at >= 0 else None
    except (ValueError, KeyError, TypeError, RecursionError):
        page_id = None
    if not isinstance(page_id, str):
        fail(f"{args.out} has no place for comments: it was built before comments were kept in the file, or it is not a page "
             "of this skill. Rebuild it in full, without --comments-only")
    scan_replies(args.replies)
    here = page_blocks(args.out, page_id)
    extra = [b for b in page_blocks(args.comments_from, page_id) if b[0] not in {x[0] for x in here}]
    new, count = reply_block(args.replies, page_id, known_ids(here + extra))
    add = "".join(b for b, _ in extra) + new
    if not add:
        print(f"NOTE\tnothing to add: {args.out} is unchanged")
        return 0
    handle, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(args.out)), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as fh:
            fh.write(text[:region[1]] + add + text[region[1]:])
        shutil.copymode(args.out, tmp)          # the page keeps who may read it
        os.replace(tmp, args.out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f"WROTE\t{args.out}\t{count} repl{'y' if count == 1 else 'ies'} added, {len(extra)} comments block(s) taken from --comments-from; nothing else changed")
    step("checking the page with the validator")
    return subprocess.run([sys.executable, "-I", VALIDATOR, args.out]).returncode


def read_json(path):
    try:
        return json.loads(read(path))
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}. Fix the file at that line and column; a trailing comma and a single quote are the usual causes")


def capture_diff(args):
    if args.diff_file:
        return read(args.diff_file)
    try:
        if args.target:
            parts = [qd.capture(repo, diff_args, label)
                     for label, repo, diff_args in (qd.parse_target(t) for t in args.target)]
            return "\n".join(p.rstrip("\n") for p in parts if p.strip()) + "\n"
        return qd.capture(args.repo, args.diff_args)
    except ValueError as exc:
        fail(str(exc))
    except RuntimeError as exc:
        fail(f"{exc}. Check that --repo is a git repository and that each revision exists there (git rev-parse <revision>)")


def changed_functions(kept, args, selected, uncalled=None):
    """Per file: the label of each hunk, the declarations it changes, and for each function its callers by name.
    Callers need a repo, so a page built from a diff file has none; the page says so.
    uncalled, when given, receives (path, name) for each function the change adds whose name stands nowhere but on
    its declaration, in tests and in documents. It is a second search, apart from the callers the page lists: a path
    the page leaves out counts as a use, and so does a name passed as a value.
    The page data is for the Diff review part only; the new functions are searched whatever the parts."""
    show = "diff" in selected
    if not show and uncalled is None:
        return {}, False
    targets = [qd.parse_target(t) for t in args.target] if args.target else ([(None, args.repo, args.diff_args)] if args.diff_args else [])
    heads = {label: (repo, range_ends(repo, diff_args)[1]) for label, repo, diff_args in targets}
    out, searched = {}, 0
    for path, block in kept:
        info = qd.hunk_functions(path, block)
        if not info["list"] and not any(info["hunks"]):
            continue
        label, inner = (path.split("/", 1) + [""])[:2] if args.target else (None, path)
        fresh = qd.new_functions(inner, block) if uncalled is not None else set()
        for fn in info["list"]:
            if label not in heads or not fn["call"]:
                continue
            # A use in any repo of the page is a use, and a search that failed anywhere settles nothing.
            if fn["name"] in fresh and len(uncalled) < 40 and all(qd.used_outside_tests(r, h, fn["call"]) is False for r, h in heads.values()):
                uncalled.append((path, fn["name"]))
            repo, head = heads[label]
            if not show or searched >= 80 or len(fn["call"]) < 3:
                continue
            searched += 1
            hits, total = qd.find_callers(repo, head, fn["call"], skip=args.exclude)
            if total is None:
                continue  # the search failed: the page shows no callers for it, rather than "no caller found"
            fn["callers"] = [[f"{label}/{p}" if label else p, line] for p, line in hits]
            fn["more"] = total - len(hits)
        out[path] = info
    return (out, bool(heads)) if show else ({}, False)


def uncalled_line(uncalled):
    """What the build prints about the new functions that only their declaration, tests and documents name.
    It is for the writer of the content; the page does not show it."""
    names = ", ".join(f"{name} ({qd.safe_path(path)})" for path, name in uncalled[:12]) + (f" and {len(uncalled) - 12} more" if len(uncalled) > 12 else "")
    count = f"at least {len(uncalled)}" if len(uncalled) >= 40 else str(len(uncalled))  # changed_functions stops looking at 40
    return (f"WARN\tno use found outside tests for {count} new function{'' if len(uncalled) == 1 else 's'}: {names}. "
            "The search is by name across the repo: a method that only an interface or a framework reaches, or a name built at run time, is not found. "
            "For each one, name in the Brief the code that calls it, or say there that only tests call it so far. "
            "Do not write or draw as working a path that runs through it")


# Pictures the page can show before and after. A picture is embedded as a data: address and shown through an image
# element only, never as markup, so an SVG cannot run a script. Raster pictures cannot be scanned for credentials;
# the limits below are their only guard. SVG is text and is scanned like any text the page carries.
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}
IMAGE_CAP = 256 * 1024        # one picture
IMAGE_BUDGET = 2 * 1024 * 1024  # every picture of one page together


def looks_like(ext, data):
    """Whether the bytes are the kind of picture their file name says."""
    if ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if ext == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return ext == "svg" and b"<svg" in data[:4096].lower()


def image_versions(kept, args, selected):
    """Per changed picture: {"before": version, "after": version}. A version is {"uri", "bytes"}, or {"note"} when
    the picture is not shown, or None when the file does not exist on that side. Both versions are read from git by
    the ids on the file's index line, so a page built from a diff file has none."""
    if "diff" not in selected or args.diff_file:
        return {}
    targets = [qd.parse_target(t) for t in args.target] if args.target else [(None, args.repo, args.diff_args)]
    repos = {label: (repo, range_ends(repo, diff_args)[1]) for label, repo, diff_args in targets}
    out, spent = {}, 0
    for path, block in kept:
        ext = qd.ext_of(path)
        ids = re.search(r"^index ([0-9a-f]{4,64})\.\.([0-9a-f]{4,64})", block, re.M)
        label, inner = (path.split("/", 1) + [""])[:2] if args.target else (None, path)
        if ext not in IMAGE_TYPES or not ids or label not in repos:
            continue
        repo, head = repos[label]
        sides = {}
        for side, blob in (("before", ids.group(1)), ("after", ids.group(2))):
            if not blob.strip("0"):
                sides[side] = None
                continue
            proc = subprocess.run(["git", "-C", repo, "cat-file", "blob", blob], capture_output=True)
            data = proc.stdout if proc.returncode == 0 else None
            if data is None and side == "after" and head is None:  # an uncommitted version is only in the working tree
                try:
                    # Only a file that really stands inside the repo: a link that points out of it is not followed.
                    target = os.path.join(repo, inner)
                    if os.path.islink(target) or os.path.commonpath([os.path.realpath(target), os.path.realpath(repo)]) != os.path.realpath(repo):
                        raise OSError("outside the repo")
                    with open(target, "rb") as fh:
                        data = fh.read()
                except (OSError, ValueError):  # ValueError: a path on another drive
                    data = None
            if data is None:
                sides[side] = {"note": "This version could not be read from the repo."}
            elif len(data) > IMAGE_CAP:
                sides[side] = {"note": f"Not shown: {len(data) // 1024} KiB, over the {IMAGE_CAP // 1024} KiB limit for a picture on this page."}
            elif spent + len(data) > IMAGE_BUDGET:
                sides[side] = {"note": f"Not shown: the pictures of this page together would pass {IMAGE_BUDGET // (1024 * 1024)} MiB."}
            elif not looks_like(ext, data):
                sides[side] = {"note": f"Not shown: the file is not a readable .{ext} picture."}
            elif ext != "svg" and any(rx.search(data.decode("latin-1")) for _, rx in qd.ALWAYS):
                # Pixels cannot be scanned, but a token of a known form written in a picture's metadata is plain bytes.
                sides[side] = {"note": "Not shown: this picture's data holds credential-shaped text."}
            elif ext == "svg" and qd.scan_content_file(path, data.decode("utf-8", "replace")):
                sides[side] = {"note": "Not shown: this SVG holds credential-shaped text."}
            else:
                spent += len(data)
                sides[side] = {"uri": f"data:{IMAGE_TYPES[ext]};base64,{base64.b64encode(data).decode('ascii')}", "bytes": len(data)}
        out[path] = sides
    return out


# Screenshots the agent took for this page. brief.html and walkthrough.html name them in a figure:
#   <figure data-shot="orders-after.png" data-before="orders-before.png">The caption.</figure>
# The build reads each named file from the --shots folder and puts it in the page. A figure without data-shot is
# not touched. One picture has a limit, because the agent can take it again smaller; the page as a whole has none,
# so a change with many screens is shown whole.
SHOT_TYPES = ("png", "jpg", "jpeg", "gif", "webp")
SHOT_CAP = 2 * 1024 * 1024
SHOT_HEAVY = 20 * 1024 * 1024
SHOT_FIGURE = re.compile(r"<figure\b([^<>]*?\sdata-shot\s*=[^<>]*)>(.*?)</figure\s*>", re.S | re.I)
SHOT_ATTR = re.compile(r"""\s(data-shot|data-before|class)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)


class Shots:
    """The folder of screenshots, the checks every named picture passes, and the figure the page shows."""

    def __init__(self, folder):
        self.folder, self.files, self.used, self.captions = folder, {}, set(), []
        self.figures = self.pictures = self.bytes = 0
        if folder:
            if not os.path.isdir(folder):
                fail(f"--shots {folder} is not a folder. Pass the folder that holds the screenshots your figures name")
            self.files = {fn: os.path.join(folder, fn) for fn in sorted(os.listdir(folder)) if fn.rsplit(".", 1)[-1].lower() in SHOT_TYPES}

    def picture(self, name, where):
        """The data: address of one named screenshot, after its checks."""
        if not self.folder:
            fail(f"{where} names the screenshot {name!r}, but no --shots folder was given. Pass --shots with the folder that holds it")
        if name not in self.files:
            fail(f"{where} names the screenshot {name!r}, but --shots has no such picture (found: {', '.join(self.files) or 'none'}). "
                 f"A name is a file name in that folder, with its ending: {', '.join(sorted(set(SHOT_TYPES)))}")
        path, ext = self.files[name], name.rsplit(".", 1)[-1].lower()
        if os.path.islink(path):
            fail(f"screenshot {name} is a link to another file. Put the picture itself in the --shots folder")
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            fail(f"screenshot {name} could not be read: {exc.strerror or exc}")
        if len(data) > SHOT_CAP:
            fail(f"screenshot {name} is {len(data) // 1024} KiB, over the {SHOT_CAP // 1024} KiB limit for one picture. Take it again smaller: "
                 "crop to the changed area, use a smaller window, or save it as JPEG or WebP. Do not leave the screen out: the page has no limit on the number of pictures")
        if not looks_like(ext, data):
            fail(f"screenshot {name} is not a readable .{ext} picture. Save it again in the format its name says")
        if any(rx.search(data.decode("latin-1")) for _, rx in qd.ALWAYS):
            fail(f"screenshot {name} holds credential-shaped text in its data; nothing written. Take the picture again")
        self.used.add(name)
        self.pictures += 1
        self.bytes += len(data)
        return f"data:{IMAGE_TYPES[ext]};base64,{base64.b64encode(data).decode('ascii')}"

    def rewrite(self, text, where):
        """The fragment with every data-shot figure turned into the page's screenshot figure."""
        def side(which, label, uri, alt, on):
            return (f'<div class="shot-side shot-{which}{" on" if on else ""}"><span class="shot-lab">{label}</span>'
                    f'<img loading="lazy" decoding="async" alt="{alt}" src="{uri}"></div>')

        def figure(m):
            attrs, caption = m.group(1), m.group(2).strip()
            found = {k.lower(): a or b for k, a, b in SHOT_ATTR.findall(" " + attrs)}
            after, before = found.get("data-shot", "").strip(), found.get("data-before", "").strip()
            plain = " ".join(html.unescape(re.sub(r"<[^<>]*>", " ", caption)).split())
            if not after:
                fail(f"{where}: a figure has an empty data-shot. Give it the file name of the screenshot")
            if not plain or re.search(r"<(?:img|figcaption|figure)\b", caption, re.I):
                fail(f"{where}: the figure for {after!r} needs a caption and nothing else between its tags: one or two sentences saying "
                     "what the screen shows and what changed on it. The build adds the picture")
            self.captions.append(plain)
            self.figures += 1
            alt = html.escape(plain[:300], quote=True)
            rest = SHOT_ATTR.sub("", " " + attrs).strip()
            classes = "shot" + (" shot-pair" if before else "") + (" " + html.escape(found["class"], quote=True) if found.get("class") else "")
            bar = '<button type="button" class="shot-big" title="Show in the full window">Enlarge</button>'
            sides = side("after", "After", self.picture(after, where), ("After: " if before else "") + alt, True)
            if before:
                bar = ('<span class="shot-seg" role="group" aria-label="Version shown">'
                       '<button type="button" class="shot-v" data-v="before" aria-pressed="false">Before</button>'
                       '<button type="button" class="shot-v on" data-v="after" aria-pressed="true">After</button></span>'
                       '<button type="button" class="shot-sbs" aria-pressed="false" title="Show both versions next to each other">Side by side</button>' + bar)
                sides = side("before", "Before", self.picture(before, where), "Before: " + alt, False) + sides
            return (f'<figure class="{classes}"{" " + rest if rest else ""}><div class="shot-bar">{bar}</div>'
                    f'<div class="shot-frame">{sides}</div><figcaption>{caption}</figcaption></figure>')

        return SHOT_FIGURE.sub(figure, text)

    def report(self):
        for name in self.files:
            if name not in self.used:
                print(f"WARN\tscreenshot {name} is in --shots and no figure names it. Name it in the section it belongs to, or remove the file")
        twice = sorted({c for c in self.captions if self.captions.count(c) > 1})
        if twice:
            print(f"WARN\t{len(twice)} screenshot caption(s) are used more than once, so a reader's comment on one cannot be told from the other: "
                  + "; ".join(c[:60] for c in twice[:3]))
        if self.figures:
            print(f"NOTE\t{self.figures} screenshot figure(s), {self.pictures} picture(s), {self.bytes // 1024} KiB")
        if self.bytes > SHOT_HEAVY:
            print(f"NOTE\tthe screenshots are {self.bytes // (1024 * 1024)} MiB together: the page may be slow to attach or to open. "
                  "This is not a limit. To make it lighter, save the pictures as JPEG or WebP; do not leave a screen out")


NOTE_MAX = 600


def line_notes(data, kept):
    """Check the agent's notes on diff lines and return them per file: {path: [{"s": side, "a": first line,
    "b": last line, "t": text}]}, with the problems found. A note must name a file of the page, a side (new by
    default, or old), and lines the diff shows on that side: a note on a line the page does not show would vanish."""
    out, bad, shown = {}, [], {path: qd.hunk_line_numbers(block) for path, block in kept}
    if not isinstance(data, list):
        return {}, ["notes.json must be a list of notes"]
    for i, item in enumerate(data, 1):
        where = f"note {i}"
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("note"), str):
            bad.append(f"{where}: needs \"path\" and \"note\" as text, and \"line\" as a number")
            continue
        path, side, text = item["path"], item.get("side", "new"), item["note"].strip()
        first, last = item.get("line"), item.get("end", item.get("line"))
        where = f"{where} ({qd.safe_path(path)})"
        if path not in shown:
            bad.append(f"{where}: this file is not on the page")
        elif side not in ("new", "old"):
            bad.append(f"{where}: \"side\" is \"new\" or \"old\"")
        elif not all(isinstance(n, int) and not isinstance(n, bool) for n in (first, last)) or last < first:
            bad.append(f"{where}: \"line\" and \"end\" are line numbers, the end not before the line")
        elif not text or len(text) > NOTE_MAX:
            bad.append(f"{where}: the note is empty or longer than {NOTE_MAX} characters")
        else:
            missing = [n for n in range(first, last + 1) if n not in shown[path][0 if side == "old" else 1]]
            if missing:
                bad.append(f"{where}: line {missing[0]} is not shown on the {side} side of the diff")
            else:
                out.setdefault(path, []).append({"s": side, "a": first, "b": last, "t": text})
    return out, bad


CHANGE_HEAD = re.compile(r"""<h2\b(?=[^>]*\bid=["']change-[^"']+["'])([^>]*)>.*?</h2>""", re.S | re.I)
ANY_H2 = re.compile(r"<h2\b[^>]*>", re.I)


def brief_files(brief, paths, diff_selected):
    """Turn the files a Brief change section names into a line of links to their diff cards.

    A section names its files on its heading: <h2 id="change-x" data-files="a/b.go, c/d.py">. The build writes the
    line under the heading, so it cannot drift from the diff: a path that is not on the page stops the build. Files
    that no section names are listed once, after the last change section. Nothing is added when no section names a
    file. Returns (the brief, the files no section names)."""
    known, named, out, last, any_named = set(paths), [], [], 0, False
    short = lambda p: "/".join(p.split("/")[-2:])
    link = lambda p: (f'<a href="#part-diff" data-file="{html.escape(p, quote=True)}" title="{html.escape(p, quote=True)}">{html.escape(short(p))}</a>' if diff_selected
                      else f'<code title="{html.escape(p, quote=True)}">{html.escape(short(p))}</code>')
    end_of_changes = 0
    for m in CHANGE_HEAD.finditer(brief):
        attr = re.search(r"""\bdata-files=("([^"]*)"|'([^']*)')""", m.group(1))
        out.append(brief[last:m.end()])
        last = end_of_changes = m.end()
        if attr is None:
            continue
        any_named = True
        files = [html.unescape(p).strip() for p in (attr.group(2) if attr.group(2) is not None else attr.group(3)).split(",") if p.strip()]
        unknown = [p for p in files if p not in known]
        if unknown:
            fail(f"brief.html: a change section names {', '.join(qd.safe_path(p) for p in unknown)}, which is not a file of this page. "
                 "Write each path as the diff shows it, separated by commas. The files of this page: " + ", ".join(qd.safe_path(p) for p in paths))
        named += files
        if files:
            out.append('<p class="sec-files"><span>Files:</span> ' + ", ".join(link(p) for p in dict.fromkeys(files)) + "</p>")
    stray = len(re.findall(r"<[a-zA-Z][^<>]*\sdata-files=", brief)) - sum(1 for m in CHANGE_HEAD.finditer(brief) if "data-files=" in m.group(1))  # in a tag, not in prose
    if stray:
        print(f"WARN\tdata-files stands {stray} time(s) outside the h2 heading of a change section; it is read only on <h2 id=\"change-...\">")
    rest = [p for p in paths if p not in set(named)] if any_named else []
    tail = brief[last:]
    if rest:
        # The catch-all stands where the change sections end: before the next section, or at the end of the brief.
        nxt = ANY_H2.search(tail)
        cut = nxt.start() if nxt else len(tail)
        tail = (tail[:cut] + '<p class="sec-files sec-rest"><span>Changed files that no section above names:</span> '
                + ", ".join(link(p) for p in rest) + "</p>" + tail[cut:])
    return "".join(out) + tail, rest


CHANGED_MARK = re.compile(r"""<[a-zA-Z][^<>]*\sdata-changed(?:=("[^"]*"|'[^']*'))?(?=[\s>/])[^<>]*>""")


def changed_marks(parts):
    """Count the blocks the agent marked as changed in this rebuild (data-changed, with an optional reason) and
    return (count, problems). A reason is at most 300 characters. The page turns the marks into a legend and a way to step through them."""
    count, bad = 0, []
    for name, text in parts:
        for m in CHANGED_MARK.finditer(text or ""):
            count += 1
            reason = html.unescape((m.group(1) or '""')[1:-1])
            if len(reason) > 300:
                bad.append(f"{name}: a data-changed reason is {len(reason)} characters long; keep it under 300, a sentence or two")
    return count, bad


def script_json(data):
    # "<" never appears raw, so no "</script>" or "<!--" inside the data can end the script early.
    text = json.dumps(data, ensure_ascii=False, indent=1)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def slug(text, taken=()):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


# ---------------------------------------------------------------------------------------------
# Provenance: computed from git, so it cannot drift from the diff on the page.

def git_out(repo, *args):
    try:
        proc = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8", "replace").strip() if proc.returncode == 0 else None


def range_ends(repo, diff_args):
    """Return (base revision, head revision or None for the working tree or index), as git reads the diff arguments."""
    tokens = shlex.split(diff_args)
    cut = tokens.index("--") if "--" in tokens else len(tokens)
    flags = [t for t in tokens[:cut] if t.startswith("-")]
    revs = [t for t in tokens[:cut] if not t.startswith("-")]
    if "--cached" in flags or "--staged" in flags:
        return (revs[0] if revs else "HEAD"), None
    if "--merge-base" in flags:  # git diff --merge-base A [B] compares merge-base(A, B or HEAD) with B or the working tree
        a, b = (revs[0] if revs else "HEAD"), (revs[1] if len(revs) > 1 else None)
        return (git_out(repo, "merge-base", a, b or "HEAD") or a), b
    if not revs:
        return "HEAD", None
    if len(revs) == 1:
        rev = revs[0]
        if rev.endswith(("^!", "^-")):  # X^! is X against its first parent
            return rev[:-2] + "^", rev[:-2]
        if "..." in rev:
            a, b = rev.split("...", 1)
            a, b = a or "HEAD", b or "HEAD"
            return (git_out(repo, "merge-base", a, b) or a), b
        if ".." in rev:
            a, b = rev.split("..", 1)
            return (a or "HEAD"), (b or "HEAD")
        return rev, None  # one revision: that commit against the working tree
    return revs[0], revs[1]


def branch_at(repo, head):
    """The branch the range head sits on: the checked-out one when the head is HEAD, else one branch pointing at it."""
    if head in (None, "HEAD"):
        current = git_out(repo, "symbolic-ref", "--short", "-q", "HEAD")
        if current:
            return current
    pointing = git_out(repo, "for-each-ref", "--points-at", head or "HEAD", "--format=%(refname:short)", "refs/heads")
    names = sorted(pointing.split()) if pointing else []
    return head if head in names else (names[0] if names else None)


def repo_provenance(label, repo, diff_args):
    base, head = range_ends(repo, diff_args)
    short = lambda rev: git_out(repo, "rev-parse", "--short=8", rev + "^{commit}") if rev else None
    base_sha, head_sha = short(base), short(head or "HEAD")
    branch = branch_at(repo, head) if head_sha else None
    log_args, _ = qd.log_range(diff_args)
    count = git_out(repo, "rev-list", "--count", *log_args) if log_args else None
    head_text = head_sha or "not recorded"
    if head is None and head_sha:
        head_text += " plus uncommitted changes"
    return {
        "label": label or os.path.basename(os.path.abspath(repo)),
        "branch": branch or "not recorded",
        "base": base_sha or "not recorded",
        "head": head_text,
        "commits": count if count is not None else "not recorded",
    }


def explanation_id(out, repo_names, override=None):
    """The identity of one explanation across rebuilds: the reader's comments and review state are stored under it.

    Local pages share one storage area in the browser, so the id names the repo as well as the explanation. The
    date prefix and a _vN suffix are dropped from the file name, so a rebuild on another day or as _v2 keeps the id.
    """
    if override and override.strip():
        return slug(override)
    stem = re.sub(r"\.html?$", "", os.path.basename(out), flags=re.I)
    stem = re.sub(r"^\d{6}(?:-\d{4})?[_-]+", "", stem)
    stem = re.sub(r"[_-]+v\d+$", "", stem, flags=re.I)
    return slug("+".join(repo_names)) + "--" + slug(stem)


def repo_name(repo):
    top = git_out(repo, "rev-parse", "--show-toplevel")
    return os.path.basename(os.path.normpath(top or os.path.abspath(repo)))


def provenance_html(repos, plans, d2_version, tickets, links, left_out, show_left_out):
    esc = html.escape
    rows = []
    for r in repos:
        rows.append(f'<span class="prov-row"><b>{esc(r["label"])}</b> branch {esc(r["branch"])}, base {esc(r["base"])}, '
                    f'head {esc(r["head"])}, {esc(str(r["commits"]))} commits</span>')
    link_html = ", ".join(f'<a href="{esc(url, quote=True)}">{esc(label)}</a>' for label, url in links) or "not recorded"
    rows.append(f'<span class="prov-row">Built {datetime.date.today().isoformat()}. '
                f'Plans: {esc(", ".join(plans)) if plans else "not recorded"}. D2: {esc(d2_version)}.</span>')
    rows.append(f'<span class="prov-row">Tickets: {esc(", ".join(tickets)) if tickets else "not recorded"}. Links: {link_html}.</span>')
    if show_left_out and left_out:
        rows.append('<span class="prov-row">Left out of this page: '
                    + esc(", ".join(f'{qd.safe_path(x["path"])} ({x["reason"]})' for x in left_out)) + ".</span>")
    rows.append('<span class="prov-row pagepath" hidden>File: <span class="pp-text"></span> '
                '<button type="button" class="pp-copy" title="Copy this page\'s path">copy path</button></span>')
    return '<div class="prov">' + "".join(rows) + "</div>"


# ---------------------------------------------------------------------------------------------
# Diagrams

def class_prelude(theme):
    lines = ["classes: {"]
    for name, (fill, stroke, font, extra) in PALETTE[theme].items():
        style = [f'fill: "{fill}"', f'stroke: "{stroke}"', f'font-color: "{font}"'] + [f"{k}: {v}" for k, v in extra.items()]
        lines.append(f"  {name}: {{ style: {{ " + "; ".join(style) + " } }")
    for name, (stroke, extra) in EDGE_PALETTE[theme].items():
        style = [f'stroke: "{stroke}"'] + [f"{k}: {v}" for k, v in extra.items()]
        lines.append(f"  {name}: {{ style: {{ " + "; ".join(style) + " } }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_d2(exe, name, source):
    """Render one D2 source in four variants. Returns {(theme, style): svg text}."""
    # D2 draws sequence diagrams with its own sequence layout whatever engine is named, so dagre is only a placeholder here.
    layout = "dagre" if SEQ_D2.search(source) else "elk"
    out = {}
    # An empty temp dir holds only our copies of the source, so a relative path in it reaches nothing else.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for theme in ("light", "dark"):
            src = f"{theme}.d2"
            with open(os.path.join(tmp, src), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(class_prelude(theme) + source)
            for style in ("sketch", "classic"):
                svg = f"{theme}-{style}.svg"
                cmd = [exe, "--layout", layout, "--theme", "0" if theme == "light" else "200", "--pad", "16"]
                cmd += ["--sketch"] if style == "sketch" else []
                cmd += [src, svg]
                try:
                    proc = subprocess.run(cmd, cwd=tmp, capture_output=True, timeout=D2_TIMEOUT)
                except subprocess.TimeoutExpired:
                    fail(f"d2 took more than {D2_TIMEOUT} seconds on diagram {name!r}. Simplify the diagram")
                except OSError as exc:
                    fail(f"cannot run d2 ({exc}). Check that d2 starts from a terminal (d2 --version), or set QEXPLAIN_D2 to its full path")
                if proc.returncode != 0:
                    tail = proc.stderr.decode("utf-8", "replace").strip()[-600:]
                    fail(f"d2 could not render diagram {name!r} ({theme}, {style}). The build adds a {class_prelude(theme).count(chr(10))}-line class block first, so subtract "
                         f"that from a reported line number. Output tail: {tail}")
                try:
                    with open(os.path.join(tmp, svg), "r", encoding="utf-8") as fh:
                        out[(theme, style)] = prepare_svg(fh.read())
                except OSError:
                    fail(f"d2 wrote no SVG for diagram {name!r} ({theme}, {style}). Draw one plain diagram per file: "
                         "layers, scenarios and steps are not supported")
    return out


def prepare_svg(svg):
    svg = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", svg)
    m = re.search(r'<svg\b[^>]*\bviewBox="[-\d.]+ [-\d.]+ ([\d.]+) [\d.]+"', svg)
    if m:  # the outer svg has a viewBox and no width, so it would stretch to the column
        svg = svg.replace("<svg ", f'<svg width="{int(float(m.group(1)))}" ', 1)
    return svg


def uniquify_ids(svg, prefix):
    """Give every id in one SVG a prefix, and every reference to it, so a diagram used twice has no duplicate ids."""
    ids = set(re.findall(r'\sid="([^"]+)"', svg))
    if not ids:
        return svg
    pick = lambda m: m.group(1) + prefix + m.group(2) if m.group(2) in ids else m.group(0)
    svg = re.sub(r'(\sid=")([^"]+)', pick, svg)
    svg = re.sub(r"""(url\(['"]?#)([^)'"]+)""", pick, svg)
    return re.sub(r'(href="#)([^"]+)', pick, svg)


def d2_ids(svg):
    """Map each D2 object id to the base64 class token its group carries."""
    ids = {}
    for m in re.finditer(r'<g class="([^"]*)"', svg):
        token = m.group(1).split(" ")[0]
        try:
            raw = base64.b64decode(token, validate=True)
            text = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if base64.b64encode(raw).decode("ascii") == token and text.isprintable():
            ids[html.unescape(text)] = token
    return ids


def normalise_edge_id(text):
    """A connection without an index means the first one: (a -> b) is (a -> b)[0]."""
    return text + "[0]" if re.fullmatch(r"(?:.+\.)?\(.+ (?:->|<->|<-|--) .+\)", text) else text


def resolve_tour_step(ids, wanted, view_key, step_no):
    """Return (mark tokens, lit tokens) for one D2 tour step, or fail naming the valid ids."""
    chosen = [normalise_edge_id(w) for w in wanted]
    unknown = [w for w in chosen if w not in ids]
    if unknown:
        valid = ", ".join(sorted(ids)[:40]) + (" ..." if len(ids) > 40 else "")
        fail(f"map view {view_key!r}, tour step {step_no}: unknown D2 id {unknown[0]!r}. Valid ids: {valid}")
    nodes = {w for w in chosen if not EDGE_ID.match(w)}
    mark = set(chosen)
    for eid, tok in ids.items():
        m = EDGE_ID.match(eid)
        if m:
            pre = (m.group("pre") + ".") if m.group("pre") else ""
            if (pre + m.group("a")) in nodes and (pre + m.group("b")) in nodes:
                mark.add(eid)  # a connection between two highlighted nodes stays lit
    containers = {i for i in ids if any(o != i and o.startswith(i + ".") for o in ids)}
    return sorted(ids[i] for i in mark), sorted(ids[i] for i in mark | containers)


def mermaid_hash_problems(text):
    """Lines of a Mermaid source that Mermaid parses without an error and draws with other text than they say.

    Seen on Mermaid 11.17.2: in a sequence diagram the text after a # is not drawn (a message, a note, a participant
    name); in the other diagrams #word; is drawn as &word;. #35; is drawn as # everywhere. The page applies the same
    two rules to a source the reader edits (mmHashBad in the template)."""
    seq, out = bool(SEQ_MMD.search(text)), []
    for n, line in enumerate(text.split("\n"), 1):
        if MMD_STYLE_LINE.match(line):
            continue
        if seq:
            if "#" in MMD_ENTITY.sub("", line):
                out.append(f"line {n}: in a sequence diagram the text after # is not drawn")
        else:
            for name in MMD_NAMED.findall(line):
                if name + ";" not in html.entities.html5:
                    out.append(f"line {n}: #{name}; is drawn as &{name};")
    return out


class Diagrams:
    """The folder of diagram sources, with rendering and the checks every source passes before it is used."""

    def __init__(self, folder):
        self.folder = folder
        self.sources = {}   # name -> (kind, text)
        self.rendered = {}  # name -> {"kind", "html", "ids", "tokens", "seq"}
        self.used = []
        self.counter = 0
        self.instances = 0
        self.mermaid = {}   # mid -> source
        self.d2_exe, self.d2_version = None, None
        if folder:
            if not os.path.isdir(folder):
                fail(f"--diagrams {folder} is not a folder. Pass the folder that holds your .d2 and .mmd files")
            for fn in sorted(os.listdir(folder)):
                stem, ext = os.path.splitext(fn)
                if ext in (".d2", ".mmd"):
                    if stem in self.sources:
                        fail(f"diagram {stem!r} exists as both .d2 and .mmd. A diagram is written once, in D2 or in Mermaid: delete one")
                    self.sources[stem] = ("d2" if ext == ".d2" else "mermaid", read(os.path.join(folder, fn)))

    def source_texts(self, names):
        return [(f"diagram {n}", self.sources[n][1]) for n in names if n in self.sources]

    def need(self, name, where):
        if name not in self.sources:
            have = ", ".join(sorted(self.sources)) or "none"
            fail(f"{where} names diagram {name!r}, but --diagrams has no {name}.d2 or {name}.mmd (found: {have})")
        if name not in self.used:
            self.used.append(name)

    def check_sources(self):
        """Refusals first (they need no d2), then the d2 lookup."""
        for name in self.used:
            kind, text = self.sources[name]
            if kind == "mermaid":
                bad = mermaid_hash_problems(text)
                if bad:
                    fail(f"diagram {name}.mmd refused: Mermaid would draw other text than the source says, with no error ("
                         + "; ".join(bad[:6]) + "). Write #35; where you mean the # sign, for example User#35;save")
            if kind == "d2":
                for why in qd.d2_refusals(text):
                    fail(f"diagram {name}.d2 refused: {why}. Remove it from the source and build again")
                # Credential-shaped text is a refusal too: it must stop the build whether or not d2 is installed.
                hits = qd.scan_content_file(f"diagram {name}.d2", text)
                if hits:
                    for hit in hits:
                        print(qd.hit_line(hit), file=sys.stderr)
                    fail(f"diagram {name}.d2 refused: credential-shaped text found; nothing written. In a D2 source an id "
                         "such as token_store: Label reads like an assignment: rename the id (for example auth_cache) "
                         "and keep the wording in the label")
        if any(self.sources[n][0] == "d2" for n in self.used):
            self.d2_exe = qd.find_d2()
            if not self.d2_exe:
                fail("D2 sources were supplied but d2 was not found. Install d2 (winget install Terrastruct.D2, brew install d2, "
                     "or https://d2lang.com), set QEXPLAIN_D2 to its path, or write these diagrams as Mermaid (.mmd) instead")
            self.d2_version = qd.d2_version(self.d2_exe) or "unknown version"

    def render(self, name):
        """Return the rendered record for a diagram, rendering it on first use."""
        if name in self.rendered:
            return self.rendered[name]
        kind, text = self.sources[name]
        self.counter += 1
        if kind == "d2":
            variants = render_d2(self.d2_exe, name, text)
            ids = d2_ids(variants[("light", "classic")])
            rec = {"kind": "d2", "name": name, "variants": variants, "ids": ids, "tokens": sorted(ids.values()), "seq": False}
        else:
            mid = f"m{self.counter}"
            self.mermaid[mid] = text
            rec = {"kind": "mermaid", "name": name, "mid": mid, "html": f'<div class="mermaid mmd" data-mid="{mid}" title="Click to enlarge"></div>',
                   "ids": {}, "tokens": [], "seq": bool(SEQ_MMD.search(text))}
        self.rendered[name] = rec
        return rec

    def unit(self, name):
        """Return (html, wrapper id) for one use of a diagram. Each use gets its own wrapper id.

        The wrapper id is a counter and changes when a diagram is added earlier in the page, so the wrapper also
        carries the diagram's own name: a reader's comment finds its diagram by that name after a rebuild.
        """
        rec = self.render(name)
        self.instances += 1
        dg = f"dg-{self.instances}"
        who = f'data-name="{html.escape(name, quote=True)}" data-kind="{rec["kind"]}"'
        if rec["kind"] == "d2":
            inner = "".join(f'<div class="dgv v-{theme} v-{style}" title="Click to enlarge">{uniquify_ids(rec["variants"][(theme, style)], f"u{self.instances}-{theme[0]}{style[0]}-")}</div>'
                            for theme in ("light", "dark") for style in ("sketch", "classic"))
            return f'<div class="dg" id="{dg}" {who}>{inner}</div>', dg
        return f'<div class="dg" id="{dg}" {who}>{rec["html"]}</div>', dg


def fill_placeholders(text, diagrams, where):
    def repl(m):
        return diagrams.unit(m.group(1))[0]
    # Names first, so a missing diagram fails before any render
    for m in PLACEHOLDER.finditer(text):
        diagrams.need(m.group(1), where)
    return PLACEHOLDER.sub(repl, text)


# ---------------------------------------------------------------------------------------------
# Parts

def walkthrough_html(text):
    """Turn <section data-subsystem> blocks into sub-tabs. Without any, the text is used as written."""
    found = list(SECTION.finditer(text))
    if not found:
        return text
    taken, ids = set(), []
    for m in found:
        ids.append(slug("wt-" + m.group(1), taken))
        taken.add(ids[-1])
    bar = "".join(f'<button class="sub-btn{" active" if i == 0 else ""}" data-group="wt" data-sub="{sid}" '
                  f'onclick="switchSub(\'wt\',\'{sid}\')">{html.escape(m.group(1))}</button>'
                  for i, (m, sid) in enumerate(zip(found, ids)))
    panels = "".join(f'<div id="sub-{sid}" class="sub-panel{" active" if i == 0 else ""}" data-group="wt">{m.group(2)}</div>\n'
                     for i, (m, sid) in enumerate(zip(found, ids)))
    return text[:found[0].start()] + f'<div class="sub-bar">{bar}</div>\n{panels}' + text[found[-1].end():]


def check_views(maps, diagrams):
    views = maps.get("views") if isinstance(maps, dict) else None
    if not isinstance(views, list) or not views:
        fail('maps.json must be an object with a non-empty "views" list')
    seen, out, taken = set(), [], set()
    for v in views:
        if not isinstance(v, dict):
            fail(f"maps.json: view {len(seen) + 1} is not an object. Each view is {{\"key\": ..., \"label\": ..., \"diagram\": ...}}")
        key = v.get("key")
        if key not in VIEW_ORDER:
            fail(f"map view key {key!r} is not one of {', '.join(VIEW_ORDER)}")
        sub = v.get("subsystem") or None
        if (key, sub) in seen:
            fail(f"map view {key!r} appears twice" + (f" in subsystem {sub!r}" if sub else "")
                 + ". Keep one, or give each its own \"subsystem\" so they stand under different sub-tabs")
        seen.add((key, sub))
        if not v.get("label"):
            fail(f"map view {key!r} needs a label")
        if not v.get("diagram"):
            fail(f"map view {key!r} needs a \"diagram\": the name of a diagram in --diagrams")
        diagrams.need(v["diagram"], f"map view {key!r}")
        vid = slug(key + ("-" + sub if sub else ""), taken)
        taken.add(vid)
        tour = v.get("tour") or []
        for i, step in enumerate(tour, 1):
            if not isinstance(step, dict) or not step.get("caption"):
                fail(f"map view {key!r}, tour step {i} needs a caption")
        out.append({**v, "vid": vid, "subsystem": sub})
    return sorted(out, key=lambda v: (v["subsystem"] or "", VIEW_ORDER.index(v["key"])))


def maps_html(views, diagrams):
    """Return (panel html, data for the page) for the Maps part."""
    data, panels_by_group = [], {}
    for v in views:
        rec = diagrams.render(v["diagram"])
        steps = []
        for i, step in enumerate(v.get("tour") or [], 1):
            entry = {"caption": step["caption"], "highlight": list(step.get("highlight") or [])}
            if rec["kind"] == "d2":
                entry["mark"], entry["lit"] = resolve_tour_step(rec["ids"], entry["highlight"], v["key"], i)
            steps.append(entry)
        data.append({"vid": v["vid"], "key": v["key"], "kind": rec["kind"], "seq": rec["seq"], "tokens": rec["tokens"], "tour": steps})
        note = f'<p class="map-note">{html.escape(v["note"])}</p>' if v.get("note") else ""
        unit, dg = diagrams.unit(v["diagram"])
        toggle = ""
        if v["key"] == "system":
            toggle = (f'<label class="chg"><input type="checkbox" checked data-target="{dg}" onchange="toggleChanges(this)"> '
                      "Show changes</label>")
        tour = ""
        if steps:
            tour = (f'<div class="tour-box"><button onclick="tourMove(\'{v["vid"]}\',-1)">&larr;</button>'
                    '<span class="tour-caption"></span><span class="tour-step-label"></span>'
                    f'<button onclick="tourMove(\'{v["vid"]}\',1)">&rarr;</button></div>')
        panels_by_group.setdefault(v["subsystem"], []).append((v, f"{note}{toggle}{unit}{tour}"))

    def group_html(group_views, first_active):
        bar = "".join(f'<button class="map-btn{" active" if i == 0 and first_active else ""}" data-view="{v["vid"]}" '
                      f'onclick="switchMap(\'{v["vid"]}\')">{html.escape(v["label"])}</button>' for i, (v, _) in enumerate(group_views))
        panels = "".join(f'<div id="view-{v["vid"]}" class="map-panel{" active" if i == 0 and first_active else ""}">{body}</div>\n'
                         for i, (v, body) in enumerate(group_views))
        return f'<div class="map-bar">{bar}</div>\n{panels}'

    if list(panels_by_group) == [None]:
        return group_html(panels_by_group[None], True), data
    names = list(panels_by_group)
    taken, sids = set(), {}
    for n in names:
        sids[n] = slug("maps-" + (n or "overview"), taken)
        taken.add(sids[n])
    bar = "".join(f'<button class="sub-btn{" active" if i == 0 else ""}" data-group="maps" data-sub="{sids[n]}" '
                  f'onclick="switchSub(\'maps\',\'{sids[n]}\')">{html.escape(n or "Overview")}</button>' for i, n in enumerate(names))
    subs = "".join(f'<div id="sub-{sids[n]}" class="sub-panel{" active" if i == 0 else ""}" data-group="maps">'
                   f'{group_html(panels_by_group[n], True)}</div>\n' for i, n in enumerate(names))
    return f'<div class="sub-bar">{bar}</div>\n{subs}', data


def summary_html(kept, rationales, roles, labelled, diff_selected):
    groups = {}
    for path, block in kept:
        groups.setdefault(qd.subsystem_of(path, labelled), []).append((path, block))
    esc = html.escape
    out = [f"<p>{len(kept)} files in {len(groups)} subsystems.</p>"]
    for name, files in groups.items():
        rows = []
        for path, block in files:
            add, rem = qd.counts(block)
            label = esc(qd.safe_path(path))
            cell = f'<a href="#part-diff" data-file="{esc(path, quote=True)}">{label}</a>' if diff_selected else label
            rows.append(f'<tr><td class="fcol">{cell}</td><td>{esc(roles.get(path, "not recorded"))}</td>'
                        f'<td>{esc(rationales.get(path, "not recorded"))}</td><td>+{add} -{rem}</td></tr>')
        out.append(f"<h3>{esc(name)}</h3><div class=\"table-wrap\"><table><thead><tr><th>File</th><th>What it does</th>"
                   f"<th>Why it changed</th><th>Lines</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
    return "\n".join(out)


def strip_parts(page, selected):
    return re.sub(r"<!--@PART:(\w+)-->(.*?)<!--@/PART:\1-->", lambda m: m.group(2) if m.group(1) in selected else "", page, flags=re.S)


SECRET_QUERY_KEY = re.compile(r"sig|signature|token|key|secret|password|credential|auth|x-amz-", re.I)


def parse_links(raw):
    from urllib.parse import parse_qsl, urlsplit
    out = []
    for item in raw:
        label, eq, url = item.partition("=")
        if not (eq and label.strip() and re.fullmatch(r"https?://[^\s\"'<>]+", url.strip())):
            fail(f"--link must read label=https://..., got {label!r}=...")
        parts = urlsplit(url.strip())
        if parts.username or parts.password:
            fail(f"--link {label.strip()!r} carries a login in the URL. Link the page without it")
        bad = [k for k, _ in parse_qsl(parts.query, keep_blank_values=True) if SECRET_QUERY_KEY.search(k)]
        if bad:
            fail(f"--link {label.strip()!r} has a query key that may be a signature or secret ({bad[0]}). Link the page without the signed query")
        out.append((label.strip(), url.strip()))
    return out


def main(argv=None):
    # -I ignores PYTHONIOENCODING, and a piped Windows console cannot print every file name.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true", help="run the built-in fixtures and exit")
    ap.add_argument("--out")
    ap.add_argument("--title")
    ap.add_argument("--base", help="base text for the page; read from git when omitted, required with --diff-file")
    ap.add_argument("--head", help="head text for the page; read from git when omitted, required with --diff-file")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--diff-args", help='arguments for git diff, e.g. "abc123..def456" or "main...HEAD -- src/"')
    src.add_argument("--diff-file", help="a unified diff already captured as UTF-8 (e.g. from a PR)")
    src.add_argument("--target", action="append", help='one per repo: "<label>=<repo>::<git diff arguments>"')
    ap.add_argument("--exclude", action="append", default=[], help="glob of a path to leave out of the page")
    ap.add_argument("--allow-credential", action="append", default=[],
                    help="<path>:<side>:<line> of one match marked made-up-test-value=yes")
    ap.add_argument("--mask-credential", action="append", default=[],
                    help="<path>:<side>:<line> of one match whose value is hidden on the page")
    ap.add_argument("--user-confirmed-credential", action="append", default=[],
                    help="<path>:<side>:<line> of one match the user has said is not a live credential")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--id", help="explanation id that keeps the reader's comments and review state across rebuilds; "
                                 "default: the repo name plus the --out file name without its date and _vN")
    ap.add_argument("--parts", default="brief,diff", help="comma list of brief, walkthrough, maps, summary, diff (brief is always emitted)")
    ap.add_argument("--brief")
    ap.add_argument("--walkthrough")
    ap.add_argument("--maps")
    ap.add_argument("--rationales")
    ap.add_argument("--roles")
    ap.add_argument("--notes", help="notes.json: notes on lines of the diff, shown read-only on the page")
    ap.add_argument("--diagrams")
    ap.add_argument("--ticket", action="append", default=[], help="a ticket reference to show in the Info menu")
    ap.add_argument("--link", action="append", default=[], help="label=https://url to show in the Info menu")
    ap.add_argument("--shots", help="folder of screenshots that figures in brief.html and walkthrough.html name with data-shot")
    ap.add_argument("--replies", help="replies.json: your answers to comments, added to the page as one comments block")
    ap.add_argument("--comments-from", help="a copy of the page whose comments blocks are also kept, when the reader gives you the page under another name")
    ap.add_argument("--comments-only", action="store_true", help="add --replies to the page at --out and change nothing else in it")
    ap.add_argument("--lang", default="en", help="language code of the prose you wrote, for the page's lang attribute (en, fr, pt-BR)")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.comments_only:
        return comments_only(args)
    if not LANG_CODE.match(args.lang):
        fail(f"--lang {args.lang!r} is not a language code. Pass the code of the language the prose is written in, such as en, fr or pt-BR")
    for need in ("out", "title", "brief", "rationales"):
        if not getattr(args, need):
            ap.error(f"--{need} is required")
    if not (args.diff_args or args.diff_file or args.target):
        ap.error("one of --diff-args, --diff-file or --target is required")
    if args.diff_file and not (args.base and args.head):
        fail("--diff-file carries no git history, so --base and --head are required with it")
    if (args.base or args.head) and not args.diff_file:
        fail("--base and --head are only for --diff-file. With --diff-args or --target the build reads them from git")

    selected = {p.strip() for p in args.parts.split(",") if p.strip()} | {"brief"}
    unknown = selected - set(PART_ORDER)
    if unknown:
        fail(f"unknown part {', '.join(sorted(unknown))}; the parts are {', '.join(PART_ORDER)}")
    for part, flag in (("walkthrough", args.walkthrough), ("maps", args.maps)):
        if part in selected and not flag:
            fail(f"the {part} part is selected but --{part} was not given. Pass --{part} <file>, or take {part} out of --parts")
        if part not in selected and flag:
            print(f"WARN\t--{part} was given but the {part} part is not in --parts; it is ignored")
    tickets, links = [t.strip() for t in args.ticket if t.strip()], parse_links(args.link)

    step("reading the diff")
    raw = capture_diff(args)
    if not raw.strip():
        fail("the diff is empty: nothing differs between the two ends of the range. Check the revisions with git rev-parse, "
             "and the path filter if you gave one. If the range is right, tell the user there is nothing to explain")
    kept, left_out, unused = qd.filter_files(qd.split_files(raw), args.exclude)
    if not kept:
        fail("no file can be shown: every file was left out, or the input holds no diff. "
             "Check the LEFT-OUT lines from measure-change.py and tell the user this change has no page")
    secret_values = qd.flagged_values(kept)  # read before the masking; compared below, never printed
    kept, unmatched = qd.mask_files(kept, args.mask_credential)
    if unmatched:
        fail("--mask-credential matched nothing: " + ", ".join(qd.safe_path(k) for k in unmatched)
             + ". Copy each <path>:<side>:<line> exactly as measure-change.py printed it")
    for key in args.mask_credential:
        print(f"MASKED\t{qd.safe_path(key)}")
    raw = "\n".join(block for _, block in kept) + "\n"
    if unused:
        fail("--exclude matched nothing, so a file meant to stay out may be on the page: " + ", ".join(unused)
             + ". Write the glob against the path as the diff shows it, or drop the flag if the file is no longer in the change")
    step(f"reading your content files ({len(kept)} files on the page, {len(left_out)} left out)")
    rationales = read_json(args.rationales)
    if not isinstance(rationales, dict):
        fail('rationales.json must map file paths to sentences. Write it as {"path/as/in/the/diff": "One sentence on why it changed."}')
    roles = read_json(args.roles) if args.roles else {}
    if not isinstance(roles, dict):
        fail('roles.json must map file paths to sentences. Write it as {"path/as/in/the/diff": "One sentence on what the file does."}')
    if args.notes and "diff" not in selected:
        print("WARN\t--notes was given but the diff part is not in --parts; it is ignored")
    notes_text = read(args.notes) if args.notes and "diff" in selected else ""
    notes, bad_notes = line_notes(read_json(args.notes), kept) if notes_text else ({}, [])
    if bad_notes:
        fail("notes.json: " + "; ".join(bad_notes[:6]) + (f"; and {len(bad_notes) - 6} more" if len(bad_notes) > 6 else "")
             + ". Correct each note against the diff as the page shows it (path, side, line), or remove it")
    brief = read(args.brief)
    walkthrough = read(args.walkthrough) if args.walkthrough and "walkthrough" in selected else ""
    maps_text = read(args.maps) if args.maps and "maps" in selected else ""
    maps = read_json(args.maps) if maps_text else None

    # Diagrams: names, refusals, the d2 lookup, then rendering.
    step("checking and drawing the diagrams (a D2 diagram is drawn four times, which can take a while)")
    diagrams = Diagrams(args.diagrams)
    for m in PLACEHOLDER.finditer(brief):
        diagrams.need(m.group(1), "brief.html")
    for m in PLACEHOLDER.finditer(walkthrough):
        diagrams.need(m.group(1), "walkthrough.html")
    views = check_views(maps, diagrams) if maps is not None else []
    tier_name = qd.tier(qd.reading_lines(kept))
    short = [f"{v['key']} ({len(v.get('tour') or [])})" for v in views if len(v.get("tour") or []) < qd.TOUR_MIN[tier_name]]
    if short and "maps" in selected:
        fail(f"a map view has fewer tour steps than this change's tier asks ({tier_name}: at least {qd.TOUR_MIN[tier_name]}): "
             + ", ".join(short) + ". Add steps that each show one thing the reader must see, or leave the view out "
               "if it has nothing more to show")
    for name in diagrams.sources:
        if name not in diagrams.used:
            print(f"WARN\tdiagram {name} is not used by the brief, the walkthrough or a map view")
    diagrams.check_sources()

    # Provenance
    if args.diff_file:
        repos, plans = [{"label": "diff file", "branch": "not recorded", "base": args.base, "head": args.head, "commits": "not recorded"}], []
        base_text, head_text = args.base, args.head
        repo_names = ["diff-file"]
    else:
        targets = [qd.parse_target(t) for t in args.target] if args.target else [(None, args.repo, args.diff_args)]
        repos, plans = [], []
        repo_names = [label or repo_name(repo) for label, repo, _ in targets]
        for label, repo, diff_args in targets:
            repos.append(repo_provenance(label, repo, diff_args))
            plans += [s for s in qd.plans_in_range(repo, diff_args)[0] if s not in plans]
        base_text = "; ".join((f"{r['label']}: " if len(repos) > 1 else "") + r["base"] for r in repos)
        head_text = "; ".join((f"{r['label']}: " if len(repos) > 1 else "") + r["head"] for r in repos)
    prov = provenance_html(repos, plans, diagrams.d2_version or "not used", tickets, links, left_out, "diff" not in selected)

    # Credential scan: the diff, then everything the agent wrote.
    step("scanning the diff and your files for credential-shaped text")
    diff_hits = qd.scan_files(kept)
    for key in args.allow_credential:
        matched = [h for h in diff_hits if qd.hit_key(h) == key]
        if any(not qd.looks_made_up(h) for h in matched):
            fail(f"--allow-credential {qd.safe_path(key)} is not marked made-up-test-value=yes. Exclude the file, or ask the user")
    allowed = set(args.allow_credential) | set(args.user_confirmed_credential)
    for key in sorted(allowed):
        n = sum(1 for h in diff_hits if qd.hit_key(h) == key)
        print(f"ALLOWED\t{qd.safe_path(key)}\t{n} match(es)" if n else f"WARN\tallowed match {qd.safe_path(key)} is not in the diff")
    hits = [h for h in diff_hits if qd.hit_key(h) not in allowed]
    written = [("brief", brief), ("walkthrough", walkthrough), ("maps.json", maps_text), ("rationales.json", read(args.rationales)),
               ("roles.json", read(args.roles) if args.roles else ""), ("notes.json", notes_text), ("title and refs", f"{args.title}\n{args.base}\n{args.head}"),
               ("tickets and links", "\n".join(tickets + [f"{a} {b}" for a, b in links])),
               ("provenance", "\n".join(f"{r['label']} {r['branch']} {r['base']} {r['head']}" for r in repos))]
    written += diagrams.source_texts(diagrams.used)
    if args.replies:        # the file as written, for the scan, and what it says, for a value quoted from the diff
        written += [("replies.json", read(args.replies)), ("replies.json (its texts)", replies_said(args.replies))]
    for name, text in written:
        hits += qd.scan_content_file(name, text)
    # A value the diff holds behind a CREDENTIAL flag must not come back in the agent's own text, masked or not.
    quoted = sorted({(name, key) for name, text in written for key, value in secret_values
                     if key not in allowed and len(value) >= 8 and value in text})
    if quoted:
        fail("; ".join(f"{name} holds the value of the credential-shaped match {qd.safe_path(key)}" for name, key in quoted[:6])
             + (f"; and {len(quoted) - 6} more" if len(quoted) > 6 else "")
             + ". Nothing written. Remove the value from your text: say what kind of value it is and where it stands, "
               "never quote it, and leave to the user whether it is a live credential")
    if hits:
        for hit in hits:
            print(qd.hit_line(hit), file=sys.stderr)
        hint = ""
        if any(h["path"].startswith("diagram ") for h in hits):
            hint = (". In a D2 source an id such as token_store: Label reads like an assignment: rename the id "
                    "(for example auth_cache) and keep the wording in the label")
        fail("credential-shaped text found; nothing written. Exclude the file, allow a made-up test value by its "
             "path:side:line, or reword your own text" + hint)

    # Fragments
    step("filling the page")
    marks, bad_marks = changed_marks([("brief.html", brief), ("walkthrough.html", walkthrough)])
    if bad_marks:
        fail("; ".join(bad_marks[:4]) + (f"; and {len(bad_marks) - 4} more" if len(bad_marks) > 4 else ""))
    if marks:
        print(f"NOTE\t{marks} {'block is' if marks == 1 else 'blocks are'} marked as changed; the page shows a legend and steps through them")
    brief, unnamed = brief_files(brief, [path for path, _ in kept], "diff" in selected)
    if unnamed:
        print(f"NOTE\t{len(unnamed)} changed {'file is' if len(unnamed) == 1 else 'files are'} named by no Brief section and listed after the change sections: "
              + ", ".join(qd.safe_path(p) for p in unnamed))
    # The pictures come in here, after the credential scan of the written text: a picture's own data is checked as
    # bytes when it is read, and is never read as prose.
    shots = Shots(args.shots)
    brief, walkthrough = shots.rewrite(brief, "brief.html"), shots.rewrite(walkthrough, "walkthrough.html")
    shots.report()
    brief_out = fill_placeholders(brief, diagrams, "brief.html")
    walk_out = walkthrough_html(fill_placeholders(walkthrough, diagrams, "walkthrough.html")) if "walkthrough" in selected else ""
    maps_out, view_data = ("", [])
    if "maps" in selected:
        maps_out, view_data = maps_html(views, diagrams)
    labelled = bool(args.target)
    summary_out = summary_html(kept, rationales, roles, labelled, "diff" in selected) if "summary" in selected else ""

    mermaid_used = bool(diagrams.mermaid)
    uncalled = []
    fns, callers_searched = changed_functions(kept, args, selected, uncalled)
    if uncalled:
        print(uncalled_line(uncalled))
    page = strip_parts(read(TEMPLATE), selected)
    # Comments: the blocks of the page this build replaces are kept as written, then the agent's replies are added.
    page_id = explanation_id(args.out, repo_names, args.id)
    carried = page_blocks(args.out, page_id)
    carried += [b for b in page_blocks(args.comments_from, page_id) if b[0] not in {x[0] for x in carried}]
    if not os.path.isfile(args.out) and not args.comments_from:
        print(f"NOTE\tno page at {args.out} yet, so no comments to keep. If this explanation was built before under another name "
              "(a date, _v2), pass that page as --comments-from: the comments its file holds are not found by name")
    reply_text, reply_count = reply_block(args.replies, page_id, known_ids(carried)) if args.replies else ("", 0)
    if carried or reply_count:
        print(f"NOTE\t{len(carried)} comments block(s) kept from the page this build replaces, {reply_count} repl{'y' if reply_count == 1 else 'ies'} added")
    slots = {
        "<!--@COMMENTS-->": "".join(b for b, _ in carried) + reply_text,
        "{{TITLE}}": html.escape(args.title),
        "{{LANG}}": args.lang,
        "{{BASE_REF}}": html.escape(base_text),
        "{{HEAD_REF}}": html.escape(head_text),
        "<!--@PROVENANCE-->": prov,
        "<!--@MERMAID-->": f'<script src="{MERMAID_URL}" integrity="{MERMAID_SRI}" crossorigin="anonymous"></script>' if mermaid_used else "",
        "<!--@HLJS-->": f'<script async src="{HLJS_URL}" integrity="{HLJS_SRI}" crossorigin="anonymous"></script>' if "diff" in selected else "",
        "<!--@BRIEF-->": brief_out,
        "<!--@WALKTHROUGH-->": walk_out,
        "<!--@MAPS-->": maps_out,
        "<!--@SUMMARY-->": summary_out,
        "/*@DATA*/": "const QX = " + script_json({
            "id": page_id, "base": base_text, "head": head_text, "views": view_data, "mermaid": diagrams.mermaid,
            "hasD2": any(r["kind"] == "d2" for r in diagrams.rendered.values()),
            # Per diagram name: its kind, and for D2 the id of every object with its class token, and the source.
            "dg": {n: ({"kind": "d2", "ids": r["ids"], "src": diagrams.sources[n][1]} if r["kind"] == "d2" else {"kind": "mermaid", "mid": r["mid"]})
                   for n, r in diagrams.rendered.items()},
            "rationales": rationales, "rawDiff": raw if "diff" in selected else "", "excluded": left_out,
            "paths": [path for path, _ in kept],
            # Per file, a hash of its hunk lines: a reviewed mark holds only while the patch it was made on is the same.
            "patch": {path: qd.patch_hash(block) for path, block in kept} if "diff" in selected else {},
            # Per file: a label per hunk and the functions it changes, with callers found by name. See changed_functions.
            "fns": fns, "callers": callers_searched,
            # Per file and hunk: a hunk that is only a move, only spacing or one word replaced. See qd.hunk_kinds.
            "hk": qd.hunk_kinds(kept) if "diff" in selected else {},
            # Per changed picture: its version before and after, embedded. See image_versions.
            "images": image_versions(kept, args, selected),
            # Per file: the agent's notes on lines of the diff. See line_notes.
            "notes": notes,
        }) + ";",
    }
    for marker in ("{{TITLE}}", "<!--@PROVENANCE-->", "<!--@MERMAID-->", "<!--@BRIEF-->", "<!--@COMMENTS-->", "/*@DATA*/"):
        if marker not in page:
            fail(f"template is missing the {marker} slot: assets/template.html is damaged. Restore it from the config repo (git checkout -- on that file)")
    # One pass, so text inside a filled slot is never mistaken for another slot.
    page = re.sub("|".join(re.escape(m) for m in slots), lambda m: slots[m.group(0)], page)

    paths = [path for path, _ in kept]
    for item in left_out:
        print(f"LEFT-OUT\t{qd.safe_path(item['path'])}\t+{item['add']} -{item['del']}\t{item['reason']}")
    for p in paths:
        if p not in rationales:
            print(f"WARN\tno rationale for {qd.safe_path(p)}")
        if "summary" in selected and p not in roles:
            print(f"WARN\tno role for {qd.safe_path(p)}; the Change summary shows \"not recorded\"")
    for p in rationales:
        if p not in paths:
            print(f"WARN\trationale for {qd.safe_path(p)}, which is not in the diff")
    changed = sum(sum(qd.counts(block)) for _, block in kept)
    if changed > 2000 and "diff" in selected:
        print("NOTE\tThis diff is large; the artifact may take a few seconds to parse on first load.")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print(f"WROTE\t{args.out}\t{len(paths)} files, {changed} changed lines, parts: {', '.join(p for p in PART_ORDER if p in selected)}, "
          f"{len(diagrams.rendered)} diagrams, {os.path.getsize(args.out) // 1024} KiB")

    step("checking the page with the validator")
    return subprocess.run([sys.executable, "-I", VALIDATOR, args.out]).returncode


# ---------------------------------------------------------------------------------------------
# Self-test: builds small pages from inline fixtures in a throwaway git repo.

SELF_BRIEF = (
    '<h2 id="intent">Intent</h2><p>Show how the handler answers a request.</p>'
    '<h2 id="context">Context</h2><p>The handler sits behind the gateway.</p>{DIAGRAM}'
    '<h2 id="change-api">API change</h2><p>The handler now validates input first.</p>'
    '<h2 id="verified">Verified</h2><p>Unit tests ran locally. A lab run is not recorded.</p>'
    '<h2 id="open-items">Open items</h2><h3>Before production</h3><ul><li>None</li></ul><h3>Backlog</h3><ul><li>None</li></ul>'
)
SELF_FILES = ["src/api/handler.py", "src/api/models.py", "web/ui/app.js", "tests/test_handler.py", "docs/guide.md"]
SELF_D2_ARCH = "direction: right\nsite: Site {\n  class: container\n  ap: Access point {class: existing}\n  broker: Broker {class: new}\n  ap -> broker: mqtt {class: new-edge}\n}\ngw: Gateway {class: changed}\nsite.broker -> gw: http\n"
SELF_D2_SEQ = "shape: sequence_diagram\na: Client\nb: Server\na -> b: request\nb -> a: response\n"
SELF_MMD_FLOW = "flowchart LR\n  A[Client] --> B[Server]\n  B --> C[Store]\n"
SELF_MMD_GANTT = "gantt\n  dateFormat YYYY-MM-DD\n  section Plan\n  Build :a1, 2026-01-01, 3d\n"
SELF_MMD_SEQ = "sequenceDiagram\n  Client->>Server: request\n  Server-->>Client: response\n"


def setup_odd(page, page_id):
    """Selftest: the page with Windows line ends, a sentence that quotes the start of the page's data, and a block whose
    ids are not text."""
    bad = '<script type="application/json" class="qx-comments">' + json.dumps({"v": 1, "id": page_id, "items": [{"id": ["a"], "text": "x"}], "gone": {"k": 1}}) + "</script>"
    a = page.rfind(CM_OPEN)
    page = page[:a].replace("<body>", "<body><p>The data starts with const QX = and goes on.</p>", 1) + CM_OPEN + bad + page[page.find(CM_SHUT, a):]
    return page.replace("\n", "\r\n")


def selftest():
    import shutil

    results, d2_cases = [], [0]
    exe = qd.find_d2()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        def case(name, ok, note="", d2=False):
            if d2:
                d2_cases[0] += 1
            results.append((ok, name, note))

        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=Selftest", "-c", "user.email=selftest@example.invalid", "-C", repo] + list(a),
                                        capture_output=True, check=True)
        git("init", "-q", "-b", "main")
        for i, f in enumerate(SELF_FILES):
            os.makedirs(os.path.dirname(os.path.join(repo, f)), exist_ok=True)
            open(os.path.join(repo, f), "w", newline="\n").write(f"line one {i}\nline two\n")
        git("add", "-A")
        git("commit", "-q", "-m", "chore: seed")
        for f in SELF_FILES:
            open(os.path.join(repo, f), "a", newline="\n").write("an added line\n")
        git("add", "-A")
        git("commit", "-q", "-m", "feat(260101_DEMO_PLAN): change the handler")
        diff_file = os.path.join(root, "change.diff")
        open(diff_file, "w", encoding="utf-8", newline="\n").write(subprocess.run(
            ["git", "-C", repo, "diff", "HEAD~1..HEAD"], capture_output=True).stdout.decode("utf-8"))

        sha = lambda rev: subprocess.run(["git", "-C", repo, "rev-parse", "--short=8", rev], capture_output=True).stdout.decode().strip()
        main_tip, first, second = sha("HEAD"), sha("HEAD~1"), sha("HEAD")
        git("checkout", "-q", "-b", "side", "HEAD~1")
        open(os.path.join(repo, "src/api/handler.py"), "a", newline="\n").write("a side line\n")
        git("commit", "-q", "-am", "feat: side work")
        git("checkout", "-q", "main")
        # Provenance forms: the base must be what git diffs against, and the branch the one the range ends on
        prov = lambda a: repo_provenance("r", repo, a)
        for form in ("main...side", "--merge-base main side"):
            p = prov(form)
            case(f"provenance base of '{form}' is the merge base", p["base"] == first and p["base"] != main_tip and p["branch"] == "side", str(p))
        for form in ("HEAD^!", "HEAD^..HEAD", "HEAD~1..HEAD"):
            p = prov(form)
            case(f"provenance of '{form}' is the parent and the commit", p["base"] == first and p["head"] == second and p["branch"] == "main", str(p))
        p = prov("HEAD~1")
        case("provenance of a single revision runs to the working tree", p["base"] == first and "uncommitted" in p["head"], str(p))
        case("provenance counts the commits", prov("HEAD~1..HEAD")["commits"] == "1" and prov("HEAD^!")["commits"] == "1", "")

        # The functions a change touches, and their callers by name
        fnrepo = os.path.join(root, "fnrepo")
        os.makedirs(os.path.join(fnrepo, "secrets"))
        fgit = lambda *a: subprocess.run(["git", "-c", "user.name=Selftest", "-c", "user.email=selftest@example.invalid", "-C", fnrepo] + list(a),
                                         capture_output=True, check=True)
        fw = lambda name, text: open(os.path.join(fnrepo, name), "w", encoding="utf-8", newline="\n").write(text)
        fgit("init", "-q", "-b", "main")
        fw("a.py", "import os\n\n\nclass Tool:\n    def helper(self, x):\n        return x\n\n    def other(self):\n        return self.helper(1)\n")
        fw("b.py", "from a import Tool\nvalue = Tool().helper(2)\n# helper is only named here\nprint(my_helper(3), helper_more(4))\n")
        fw("secrets/k.py", "x = helper(5)\n")
        os.makedirs(os.path.join(fnrepo, "vendor"))
        fw("vendor/lib.py", "y = helper(7)\n")  # a generated or vendored file is not a caller worth listing
        long_method = "class Big:\n    def run(self):\n" + "".join(f"        step_{i} = {i}\n" for i in range(1, 12))
        fw("m.py", long_method)  # a method whose declaration stands above the hunk of its change
        fw("s.py", "def reshaped(a):\n    return a\n")  # nothing calls it, and the change only gives it a parameter
        fgit("add", "-A")
        fgit("commit", "-q", "-m", "seed")
        fw("a.py", "import os\n\n\nclass Tool:\n    def helper(self, x):\n        return x + 1\n\n    def other(self):\n        return self.helper(1)\n")
        fw("m.py", long_method.replace("step_9 = 9", "step_9 = 90"))
        fw("s.py", "def reshaped(a, b=0):\n    return a\n")
        fw("n.py", "def fresh_unused(x):\n    return x\n\n\ndef fresh_used(x):\n    return x\n\n\n@route(\"/x\")\ndef fresh_routed(x):\n    return x\n\n\n"
                   "@route(\n    \"/y\",\n)\nasync def fresh_routed_long(x):\n    return x\n\n\ndef test_fresh(x):\n    return fresh_used(x)\n\n\ndef main():\n    return 0\n\n\n"
                   "def fresh_tested(x):\n    return x\n\n\ndef fresh_passed(x):\n    return x\n\n\nworker = dict(target=fresh_passed)\n\n\n"
                   "# fresh_noted is named by the comment above it\ndef fresh_noted(x):\n    return x\n\n\ndef testimonial(x):\n    return x\n\n\n"
                   "def __enter__(x):\n    return x\n\n\n@route(\"/z\")\n# why this route\ndef fresh_routed_noted(x):\n    return x\n")
        os.makedirs(os.path.join(fnrepo, "tests"))
        fw("tests/test_n.py", "from n import fresh_tested\n\n\ndef test_it():\n    assert fresh_tested(1)\n\n\ndef support_only(x):\n    return x\n")
        fw("NOTES.md", "fresh_unused(x) is planned.\n")  # a document that names a function does not call it
        fw("r.rs", "#[test]\nfn parses_empty() {\n}\n\nfn fresh_rust() {\n}\n")
        fw("k.kt", "@Test fun checksThing() {\n}\n\noverride fun onCreate() {\n}\n")
        fw("g.go", "package g\n\nfunc init() {\n}\n")
        fw("p.js", "export default function Page() {\n}\n")
        fgit("add", "n.py", "tests/test_n.py", "NOTES.md", "r.rs", "k.kt", "g.go", "p.js")
        fgit("commit", "-q", "-am", "change helper")
        fkept = qd.filter_files(qd.split_files(qd.capture(fnrepo, "HEAD~1..HEAD")), [])[0]
        space = lambda **kw: argparse.Namespace(**{"target": None, "repo": fnrepo, "diff_args": None, "diff_file": None, "exclude": [], **kw})
        fns, searched = changed_functions(fkept, space(diff_args="HEAD~1..HEAD"), {"diff"})
        one = (fns.get("a.py") or {"hunks": [], "list": [{}]})
        case("a hunk inside a method is labelled with the method, and the method is listed", one["hunks"] == ["def helper(self, x)"] and [f.get("name") for f in one["list"]] == ["helper"], str(one))
        case("callers are the places that call the name: not its definition, a longer name, a mention in a comment or a secret-named file",
             searched and one["list"][0].get("callers") == [["a.py", 9], ["b.py", 2]] and one["list"][0].get("more") == 0, str(one))
        fns_x, _ = changed_functions(fkept, space(diff_args="HEAD~1..HEAD", exclude=["b.py"]), {"diff"})
        case("a path the page leaves out is not named as a caller either", (fns_x.get("a.py") or {"list": [{}]})["list"][0].get("callers") == [["a.py", 9]], str(fns_x.get("a.py")))
        fns, searched = changed_functions(fkept, space(diff_file="x.diff"), {"diff"})
        case("a page built from a diff file names the functions and lists no callers", not searched and "callers" not in fns["a.py"]["list"][0], str(fns))
        case("a page without the Diff review part carries no function data", changed_functions(fkept, space(diff_args="HEAD~1..HEAD"), {"brief"}) == ({}, False), "")
        # A new function that nothing calls by name
        def uncalled_of(parts, **kw):
            found = []
            changed_functions(fkept, space(**kw), parts, found)
            return found
        lone = uncalled_of({"diff"}, diff_args="HEAD~1..HEAD")
        expected = [("n.py", "fresh_unused"), ("n.py", "fresh_tested"), ("n.py", "fresh_noted"), ("n.py", "testimonial"), ("r.rs", "fresh_rust")]
        case("a new function that only a test, a document or a comment names is reported; one that is called, one passed as a value, "
             "one whose declaration only changed, one under a decorator or an attribute, a test, main, init, an override, a default export, "
             "a name the language calls and a function of a test file are not", lone == expected, str(lone))
        case("the search covers the whole repository when --repo names a folder inside it",
             uncalled_of({"diff"}, repo=os.path.join(fnrepo, "tests"), diff_args="HEAD~1..HEAD") == expected, "")
        # Two repos: a use in the other repo is a use
        other = os.path.join(root, "fnother")
        os.makedirs(other)
        ogit = lambda *a: subprocess.run(["git", "-c", "user.name=Selftest", "-c", "user.email=selftest@example.invalid", "-C", other] + list(a), capture_output=True, check=True)
        ogit("init", "-q", "-b", "main")
        open(os.path.join(other, "u.py"), "w", encoding="utf-8", newline="\n").write("value = 1\n")
        ogit("add", "-A")
        ogit("commit", "-q", "-m", "seed")
        open(os.path.join(other, "u.py"), "w", encoding="utf-8", newline="\n").write("value = fresh_unused(1)\n")
        ogit("commit", "-q", "-am", "use it")
        both = []
        changed_functions([("one/" + p, b) for p, b in fkept], space(target=[f"one={fnrepo}::HEAD~1..HEAD", f"two={other}::HEAD~1..HEAD"]), {"diff"}, both)
        case("with several repos, a use in another repo is a use", both == [("one/" + p, n) for p, n in expected[1:]], str(both))
        real = qd.used_outside_tests, qd.find_callers
        qd.used_outside_tests, qd.find_callers = (lambda *a, **k: None), (lambda *a, **k: ([], None))
        try:
            failed_fns, _ = changed_functions(fkept, space(diff_args="HEAD~1..HEAD"), {"diff"}, failed_found := [])
        finally:
            qd.used_outside_tests, qd.find_callers = real
        case("when the searches fail, nothing is reported and the page lists no callers", failed_found == [] and "callers" not in failed_fns["n.py"]["list"][0], str(failed_found))
        many = uncalled_line([("n.py", f"fn_{i}") for i in range(14)])
        case("the build's line counts every function and names the first twelve", "for 14 new functions: fn_0 (n.py)" in many and "fn_11 (n.py) and 2 more." in many, many[:300])
        case("the report does not depend on the Diff review part", uncalled_of({"brief"}, diff_args="HEAD~1..HEAD") == lone, "")
        case("a path the page leaves out still counts as a use", uncalled_of({"diff"}, diff_args="HEAD~1..HEAD", exclude=["n.py"]) == lone, "")
        case("a page built from a diff file reports no uncalled function: nothing was searched", uncalled_of({"diff"}, diff_file="x.diff") == [], "")
        case("a search that failed is not a search that found nothing",
             qd.find_callers(fnrepo, "no-such-revision", "helper") == ([], None) and qd.used_outside_tests(fnrepo, "no-such-revision", "helper") is None,
             str(qd.find_callers(fnrepo, "no-such-revision", "helper")))
        line = uncalled_line([("n.py", "fresh_unused")])
        case("the build's line names the function and its file, and says what to write",
             line.startswith("WARN\tno use found outside tests for 1 new function: fresh_unused (n.py).") and "Brief" in line, line)
        case("the capture uses git's per-language rule: a change in a method is headed by the method, not by its class",
             bool(re.search(r"^@@ [^@]+ @@ def run\(self\):$", qd.capture(fnrepo, "HEAD~1..HEAD"), re.M)), qd.capture(fnrepo, "HEAD~1..HEAD")[-300:])

        # A changed picture, before and after
        import struct
        import zlib

        def png(width, colour):
            chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 4, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress((b"\x00" + bytes(colour) * width) * 4)) + chunk(b"IEND", b""))
        imrepo = os.path.join(root, "imrepo")
        os.makedirs(imrepo)
        igit = lambda *a: subprocess.run(["git", "-c", "user.name=Selftest", "-c", "user.email=selftest@example.invalid", "-c", "core.autocrlf=false", "-C", imrepo] + list(a),
                                         capture_output=True, check=True)
        iw = lambda name, data: open(os.path.join(imrepo, name), "wb").write(data)
        igit("init", "-q", "-b", "main")
        for name, data in (("a.png", png(8, (10, 20, 30))), ("gone.png", png(8, (1, 2, 3))), ("big.png", png(8, (0, 0, 0)) + os.urandom(IMAGE_CAP)),
                           ("fake.png", b"this is text, not a picture\n"), ("s.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='4' height='4'/></svg>\n"),
                           ("k.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><text>a</text></svg>\n"), ("notes.txt", b"one\n")):
            iw(name, data)
        igit("add", "-A")
        igit("commit", "-q", "-m", "seed")
        for name, data in (("a.png", png(12, (200, 20, 30))), ("new.png", png(6, (9, 9, 9))), ("big.png", png(8, (0, 0, 0)) + os.urandom(IMAGE_CAP + 10)),
                           ("fake.png", b"still text, still not a picture\n"), ("s.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='9' height='4'/></svg>\n"),
                           ("k.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><text>password = \"Zx81-kq77-Lm42-pp09\"</text></svg>\n"), ("notes.txt", b"two\n"),
                           ("tok.png", png(5, (1, 2, 3)) + b"gh" + b"p_" + b"A" * 36)):  # a token-shaped text after the picture's data
            iw(name, data)
        os.remove(os.path.join(imrepo, "gone.png"))
        igit("add", "-A")
        igit("commit", "-q", "-m", "change")
        ikept = qd.split_files(qd.capture(imrepo, "HEAD~1..HEAD"))
        ins = lambda **kw: argparse.Namespace(**{"target": None, "repo": imrepo, "diff_args": "HEAD~1..HEAD", "diff_file": None, **kw})
        im = image_versions(ikept, ins(), {"diff"})
        shown = lambda v: bool(v) and v.get("uri", "").startswith("data:image/")
        case("a picture whose bytes hold credential-shaped text is named and not shown", "credential-shaped" in ((im.get("tok.png") or {}).get("after") or {}).get("note", "")
             and not shown((im.get("tok.png") or {}).get("after")), str(im.get("tok.png"))[:200])
        case("a changed picture carries both versions, read from git", shown(im.get("a.png", {}).get("before")) and shown(im["a.png"]["after"]) and im["a.png"]["before"]["uri"] != im["a.png"]["after"]["uri"]
             and base64.b64decode(im["a.png"]["after"]["uri"].split(",", 1)[1]) == png(12, (200, 20, 30)), str(sorted(im)))
        case("a new picture has no version before, a removed one none after", im["new.png"]["before"] is None and shown(im["new.png"]["after"]) and shown(im["gone.png"]["before"]) and im["gone.png"]["after"] is None, "")
        case("a picture over the size limit, a file that is not the picture its name says, and an SVG with credential-shaped text are named, not shown",
             all("note" in im[n][s] for n in ("big.png", "fake.png") for s in ("before", "after")) and "limit" in im["big.png"]["after"]["note"]
             and shown(im["k.svg"]["before"]) and "credential" in im["k.svg"]["after"].get("note", "") and shown(im["s.svg"]["after"]), str({k: {s: (v or {}).get("note") for s, v in d.items()} for k, d in im.items()}))
        case("a text file is not a picture, and a page built from a diff file or without the Diff part embeds none",
             "notes.txt" not in im and image_versions(ikept, ins(diff_file="x.diff"), {"diff"}) == {} and image_versions(ikept, ins(), {"brief"}) == {}, "")
        budget = globals()["IMAGE_BUDGET"]
        globals()["IMAGE_BUDGET"] = len(png(12, (200, 20, 30))) + 10  # room for one picture, not for two
        try:
            tight = image_versions(ikept, ins(), {"diff"})
        finally:
            globals()["IMAGE_BUDGET"] = budget
        told = [v for d in tight.values() for v in d.values() if v and "together would pass" in v.get("note", "")]
        case("once the pictures of a page pass the page's limit, the next ones are named and not shown", sum(1 for d in tight.values() for v in d.values() if shown(v)) == 1 and len(told) >= 2, str(len(told)))
        iw("a.png", png(20, (1, 200, 3)))  # changed and not committed: only the working file holds this version
        loose = image_versions(qd.split_files(qd.capture(imrepo, "HEAD -- a.png")), ins(diff_args="HEAD -- a.png"), {"diff"})
        case("a picture changed and not committed is read from the working file", shown(loose.get("a.png", {}).get("after"))
             and base64.b64decode(loose["a.png"]["after"]["uri"].split(",", 1)[1]) == png(20, (1, 200, 3)), str(loose)[:200])

        content = os.path.join(root, "content")
        diag = os.path.join(content, "diagrams")
        os.makedirs(diag)
        w = lambda name, text, folder=content: open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n").write(text)
        w("brief.html", SELF_BRIEF.replace("{DIAGRAM}", ""))
        w("rationales.json", json.dumps({f: f"Why {f} changed." for f in SELF_FILES}))
        w("roles.json", json.dumps({f: f"What {f} does." for f in SELF_FILES}))
        w("walkthrough.html", '<p>Intro.</p><section data-subsystem="API"><h2>API</h2><p>x</p></section><section data-subsystem="Web UI"><h2>UI</h2><p>y</p></section>')

        def run(name, extra, env=None, base_args=None):
            out = os.path.join(root, name + ".html")
            cmd = [sys.executable, "-I", os.path.abspath(__file__), "--out", out, "--title", "Selftest"] + (base_args if base_args is not None else ["--repo", repo, "--diff-args", "HEAD~1..HEAD"]) + extra
            proc = subprocess.run(cmd, capture_output=True, env=env)
            text = open(out, encoding="utf-8").read() if os.path.exists(out) else ""
            return proc.returncode, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace"), text


        std = ["--brief", os.path.join(content, "brief.html"), "--rationales", os.path.join(content, "rationales.json")]
        # Part combinations without D2
        rc, log, page = run("brief-only", std + ["--parts", "brief"])
        case("brief-only page builds and validates", rc == 0 and 'id="part-diff"' not in page and 'data-part="diff"' not in page and '"rawDiff": ""' in page, log[-300:])
        case("a page without the Diff review part loads no highlighter", "highlight.min.js" not in page and "<!--@HLJS-->" not in page, "")
        rc, log, page = run("brief-diff", std)
        case("brief and diff page", rc == 0 and 'id="part-diff"' in page and "diff --git" in page, log[-300:])
        u_rc, u_log, _ = run("uncalled", std + ["--parts", "brief"], base_args=["--repo", fnrepo, "--diff-args", "HEAD~1..HEAD"])
        case("the build prints the new functions nothing uses, whatever the parts", u_rc == 0 and "WARN\tno use found outside tests for 5 new functions: fresh_unused (n.py)" in u_log, u_log[-400:])
        # A credential-shaped value on the line git prints after the second @@
        crepo = os.path.join(root, "crepo")
        os.makedirs(crepo)
        cgit = lambda *a: subprocess.run(["git", "-c", "user.name=Selftest", "-c", "user.email=selftest@example.invalid", "-c", "core.autocrlf=false", "-C", crepo] + list(a),
                                         capture_output=True, check=True)
        cred_line = 'def login(user, pass' + 'word="Zx81-kq77-Lm42-pp09"):\n'
        body = "".join(f"    step_{i} = {i}\n" for i in range(1, 12))
        cgit("init", "-q", "-b", "main")
        open(os.path.join(crepo, "auth.py"), "w", encoding="utf-8", newline="\n").write(cred_line + body)
        cgit("add", "-A")
        cgit("commit", "-q", "-m", "seed")
        open(os.path.join(crepo, "auth.py"), "w", encoding="utf-8", newline="\n").write(cred_line + body.replace("step_9 = 9", "step_9 = 90"))
        cgit("commit", "-q", "-am", "change")
        c_rat = os.path.join(content, "c-rationales.json")
        open(c_rat, "w", encoding="utf-8").write(json.dumps({"auth.py": "Why."}))
        c_args = ["--brief", os.path.join(content, "brief.html"), "--rationales", c_rat]
        c_base = ["--repo", crepo, "--diff-args", "HEAD~1..HEAD"]
        c_rc, c_log, c_page = run("cred-header", c_args, base_args=c_base)
        c_key = re.search(r"CREDENTIAL\tauth\.py\tcontext (\d+)", c_log)
        case("a credential-shaped value on the line git prints after the second @@ stops the build and is named by its own key",
             c_rc != 0 and bool(c_key) and "Zx81" not in c_log, c_log[-400:])
        c_rc, c_log, c_page = run("cred-header-masked", c_args + ["--mask-credential", f"auth.py:context:{c_key.group(1) if c_key else 0}"], base_args=c_base)
        case("masked by that key, the page builds and carries the value neither in the diff nor in a function label", c_rc == 0 and "def login" in c_page and "Zx81" not in c_page, c_log[-400:])
        c_value = "Zx81" + "-kq77-Lm42-pp09"  # the fixture's value, as an agent might quote it in its own text
        c_brief = os.path.join(content, "brief-quotes-value.html")
        open(c_brief, "w", encoding="utf-8", newline="\n").write(open(os.path.join(content, "brief.html"), encoding="utf-8").read() + f"\n<p>The fixture value is <code>{c_value}</code>.</p>\n")
        c_rc, c_log, c_page = run("cred-quoted", ["--brief", c_brief, "--rationales", c_rat, "--mask-credential", f"auth.py:context:{c_key.group(1) if c_key else 0}"], base_args=c_base)
        case("a brief that quotes the value of a masked match stops the build, which names the file and the match and never the value",
             c_rc != 0 and c_page == "" and "brief holds the value of the credential-shaped match auth.py:context:" in c_log and "Zx81" not in c_log, c_log[-400:])
        policy = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page)
        policy = policy.group(1) if policy else ""
        case("the page declares a content security policy: nothing by default, scripts from the pinned scripts' host only, no evaluated code, no network calls",
             "default-src 'none'" in policy and "connect-src 'none'" in policy and "unsafe-eval" not in policy
             and all("https://" + url.split("/")[2] in policy.split("script-src")[1].split(";")[0] for url in (MERMAID_URL, HLJS_URL)), policy)
        case("the build prints a line for each stage, in order", [line.split("\t")[1].split(" (")[0] for line in log.replace("\r", "").split("\n") if line.startswith("STEP\t")]
             == ["reading the diff", "reading your content files", "checking and drawing the diagrams", "scanning the diff and your files for credential-shaped text", "filling the page",
                 "checking the page with the validator"], log[-500:])
        # Refusals say what to do next
        bad_json = os.path.join(content, "bad.json")
        open(bad_json, "w", encoding="utf-8").write('{"a": 1,}')
        list_json = os.path.join(content, "list.json")
        open(list_json, "w", encoding="utf-8").write('["a"]')
        brief_arg = ["--brief", os.path.join(content, "brief.html")]
        twice_dir, icon_dir = os.path.join(root, "twice-diagrams"), os.path.join(root, "icon-diagrams")
        for folder in (twice_dir, icon_dir):
            os.makedirs(folder)
        open(os.path.join(twice_dir, "flow.mmd"), "w", encoding="utf-8", newline="\n").write(SELF_MMD_FLOW)
        twice_json = os.path.join(content, "maps-twice.json")
        open(twice_json, "w", encoding="utf-8").write(json.dumps({"views": [{"key": "system", "label": "One", "diagram": "flow"}, {"key": "system", "label": "Two", "diagram": "flow"}]}))
        open(os.path.join(icon_dir, "arch.d2"), "w", encoding="utf-8", newline="\n").write("a: A {icon: https://example.invalid/x.svg}\n")
        icon_brief = os.path.join(content, "brief-icon.html")
        open(icon_brief, "w", encoding="utf-8", newline="\n").write(SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="arch"></div>'))
        for name, extra, base_args, want in (
                ("an empty diff", std, ["--repo", repo, "--diff-args", "HEAD..HEAD"], "tell the user there is nothing to explain"),
                ("a revision that does not exist", std, ["--repo", repo, "--diff-args", "no-such-rev..HEAD"], "git rev-parse"),
                ("a part selected without its file", std + ["--parts", "brief,maps"], None, "take maps out of --parts"),
                ("a content file that is not valid JSON", brief_arg + ["--rationales", bad_json], None, "Fix the file at that line and column"),
                ("a rationales file of the wrong shape", brief_arg + ["--rationales", list_json], None, '{"path/as/in/the/diff"'),
                ("a diagrams folder that is not a folder", std + ["--diagrams", bad_json], None, "Pass the folder that holds"),
                ("an exclude that matches nothing", std + ["--exclude", "no/such/*.zzz"], None, "Write the glob against the path"),
                ("a content file that does not exist", ["--brief", os.path.join(content, "no-such-brief.html"), "--rationales", os.path.join(content, "rationales.json")], None, "Check the path, and save the file as UTF-8"),
                ("a roles file of the wrong shape", std + ["--parts", "brief,summary", "--roles", list_json], None, "One sentence on what the file does"),
                ("a mask that matches no line", std + ["--mask-credential", "src/api/handler.py:new:9999"], None, "exactly as measure-change.py printed it"),
                ("a map view given twice", std + ["--parts", "brief,maps", "--maps", twice_json, "--diagrams", twice_dir], None, "Keep one, or give each its own"),
                ("a D2 construct the build refuses", std + ["--diagrams", icon_dir, "--brief", icon_brief], None, "Remove it from the source and build again")):
            r_rc, r_log, _ = run("refusal", extra, base_args=base_args)
            case(f"a refusal names the next action: {name}", r_rc == 2 and "ERROR\t" in r_log and want in r_log, r_log[-300:])
        # Blocks marked as changed in a rebuild
        marked_brief = os.path.join(content, "brief-marked.html")
        marked = lambda attr: (open(marked_brief, "w", encoding="utf-8", newline="\n").write(SELF_BRIEF.replace("{DIAGRAM}", "").replace(
            "<p>The handler now validates input first.</p>", f"<p {attr}>The handler now validates input first.</p><ul><li data-changed>One more case.</li></ul>")),
            run("brief-marked", ["--brief", marked_brief, "--rationales", os.path.join(content, "rationales.json")]))[1]
        m_rc, m_log, m_page = marked('data-changed="Answer to comment 2: said what is checked first"')
        case("blocks marked as changed are kept on the page and counted", m_rc == 0 and "NOTE\t2 blocks are marked as changed" in m_log
             and 'data-changed="Answer to comment 2: said what is checked first"' in m_page and "<li data-changed>" in m_page, m_log[-300:])
        m_rc, m_log, m_page = marked('data-changed="' + "x" * 330 + '"')
        case("a reason that is too long stops the build and says how long it may be", m_rc != 0 and "keep it under 300" in m_log, m_log[-300:])
        case("a page with no marked block says nothing about them", "marked as changed" not in log, "")
        # Files named on Brief sections
        named_brief = os.path.join(content, "brief-files.html")
        filed = lambda files, extra=(): (open(named_brief, "w", encoding="utf-8", newline="\n").write(SELF_BRIEF.replace("{DIAGRAM}", "").replace(
            '<h2 id="change-api">', f'<h2 id="change-api" data-files="{files}">')), run("brief-files", ["--brief", named_brief, "--rationales", os.path.join(content, "rationales.json")] + list(extra)))[1]
        f_rc, f_log, f_page = filed("src/api/handler.py, src/api/models.py")
        case("a Brief section that names its files gets a line of links to their diff cards",
             f_rc == 0 and '<p class="sec-files"><span>Files:</span> <a href="#part-diff" data-file="src/api/handler.py"' in f_page and f_page.count('class="sec-files"') == 1, f_log[-300:])
        rest_at, verified_at = f_page.find('class="sec-files sec-rest"'), f_page.find('<h2 id="verified"')
        case("files that no section names are listed once, where the change sections end, and the build says so",
             0 < rest_at < verified_at and all(f_page.count(f'data-file="{p}"') == 1 for p in SELF_FILES) and "NOTE\t3 changed files are named by no Brief section and listed" in f_log, f_log[-400:])
        f_rc, f_log, f_page = filed("src/api/handler.py, src/api/missing.py")
        case("a Brief section that names a file not on the page stops the build and lists the files of the page",
             f_rc != 0 and "src/api/missing.py, which is not a file of this page" in f_log and "docs/guide.md" in f_log, f_log[-400:])
        f_rc, f_log, f_page = filed("src/api/handler.py", ["--parts", "brief"])
        case("without the Diff review part the files are named and not linked", f_rc == 0 and 'class="sec-files"' in f_page and "data-file=" not in f_page and "<code title=\"src/api/handler.py\">" in f_page, f_log[-300:])
        case("data-changed-by is another attribute: it is not counted as a mark",
             changed_marks([("brief.html", '<p data-changed-by="x">a</p><p data-changed="said why">b</p><p data-changed>c</p>')]) == (2, []), "")
        w_buf = io.StringIO()
        with contextlib.redirect_stdout(w_buf):
            brief_files('<h2 id="change-a" data-files="a.py">A</h2><p data-files="a.py">x</p>', ["a.py"], True)
        case("data-files outside a change heading is reported, not silently ignored", "WARN\tdata-files stands 1 time(s) outside" in w_buf.getvalue(), w_buf.getvalue()[:200])
        w_note = os.path.join(content, "notes-unused.json")
        open(w_note, "w", encoding="utf-8", newline="\n").write("[]")
        w_rc, w_log, w_page = run("notes-unused", std + ["--notes", w_note, "--parts", "brief"])
        case("--notes without the Diff review part is reported as ignored", w_rc == 0 and "WARN\t--notes was given but the diff part is not in --parts" in w_log, w_log[-300:])
        # Notes on diff lines
        note_file = os.path.join(content, "notes.json")
        noted = lambda notes: (open(note_file, "w", encoding="utf-8", newline="\n").write(json.dumps(notes)), run("notes", std + ["--notes", note_file]))[1]
        n_rc, n_log, n_page = noted([{"path": "src/api/handler.py", "line": 3, "note": "This line is why the change exists."},
                               {"path": "docs/guide.md", "side": "old", "line": 1, "end": 2, "note": "Unchanged on purpose."}])
        case("notes on diff lines are checked and written into the page", n_rc == 0 and '"This line is why the change exists."' in n_page and '"s": "old"' in n_page and '"b": 2' in n_page, n_log[-300:])
        n_rc, n_log, n_page = noted([{"path": "src/api/handler.py", "line": 40, "note": "Not in the diff."}])
        case("a note on a line the diff does not show stops the build", n_rc != 0 and "line 40 is not shown on the new side" in n_log, n_log[-300:])
        n_rc, n_log, n_page = noted([{"path": "src/api/handler.py", "side": "old", "line": 3, "note": "Line 3 is new."}])
        case("a note on the old side cannot point at an added line", n_rc != 0 and "line 3 is not shown on the old side" in n_log, n_log[-300:])
        n_rc, n_log, n_page = noted([{"path": "src/nowhere.py", "line": 1, "note": "x"}, {"path": "docs/guide.md", "line": "3", "note": "y"}])
        case("a note on a file that is not on the page, or with a line that is not a number, stops the build", n_rc != 0 and "not on the page" in n_log and "line numbers" in n_log, n_log[-400:])
        n_rc, n_log, n_page = noted([{"path": "src/api/handler.py", "line": 3, "note": "use pass" + 'word = "Zq7Mv2Lp9Xk4" here'}])
        case("a note is scanned like every text the agent writes", n_rc != 0 and "credential-shaped" in n_log, n_log[-300:])
        n_rc, n_log, n_page = noted([{"path": "src/api/handler.py", "line": 3, "end": 2, "note": "The end is before the line."}])
        case("a note whose end is before its line stops the build", n_rc != 0 and "the end not before the line" in n_log, n_log[-300:])
        n_rc, n_log, n_page = noted([{"path": "src/api/handler.py", "line": 3, "note": "x" * 601}])
        case("a note of 601 characters stops the build; one of 600 does not", n_rc != 0 and "longer than 600" in n_log
             and noted([{"path": "src/api/handler.py", "line": 3, "note": "x" * 600}])[0] == 0, n_log[-300:])
        case("the page carries an explanation id made of the repo and the file name", '"id": "repo--brief-diff"' in page, page[page.find("const QX"):][:120])
        case("the Info menu holds the provenance once, with the page path row and no id", page.count('class="prov-row pagepath"') == 1 and 'id="pagepath' not in page, "")
        eid = explanation_id
        case("explanation id drops the date prefix and a _vN suffix, so a rebuild keeps it",
             eid("x/260819_ARUBA_LIVENESS_EXPLANATION.html", ["gwadapter"]) == eid("y/260901-1530_ARUBA_LIVENESS_EXPLANATION_v3.html", ["gwadapter"])
             == "gwadapter--aruba-liveness-explanation", eid("x/260819_ARUBA_LIVENESS_EXPLANATION.html", ["gwadapter"]))
        case("explanation id differs between repos and joins several", eid("a.html", ["one"]) != eid("a.html", ["two"])
             and eid("a.html", ["gw", "se"]) == "gw-se--a", eid("a.html", ["gw", "se"]))
        case("--id overrides the explanation id", eid("a.html", ["one"], "My Review 7") == "my-review-7", "")
        # Comments blocks: kept over a rebuild, replies added once, a comments-only update, refusals
        region = lambda t: t[comments_region(t)[0]:comments_region(t)[1]] if comments_region(t) else None
        rc, log, page = run("cm", std)
        cm_out, cm_id = os.path.join(root, "cm.html"), "repo--cm"
        case("a page has one place for comments, empty at first", rc == 0 and page.count(CM_OPEN) == 1 and page.count(CM_SHUT) == 1 and region(page) == "", log[-200:])
        blk = lambda pid, cid: '<script type="application/json" class="qx-comments">' + script_json({"v": 1, "id": pid, "items": [{"id": cid, "text": "a </script> typed by a reader", "part": "page"}], "gone": {"cgone": 5}, "edits": {}}) + "</script>"
        mine, other = blk(cm_id, "c1"), blk("another--page", "c2")
        open(cm_out, "w", encoding="utf-8", newline="\n").write(page.replace(CM_OPEN + CM_SHUT, CM_OPEN + mine + other + CM_SHUT))
        rc, log, page = run("cm", std)
        case("a rebuild keeps the comments blocks of the page it replaces as written, and leaves out one of another explanation",
             rc == 0 and region(page) == mine and "belongs to another explanation" in log and "1 comments block(s) kept" in log, log[-300:])
        w("replies.json", json.dumps({"by": "  Ada   L ", "replies": [{"to": "c1", "text": "Addressed: <b>done</b> </script><script>x"}, {"to": "c1", "text": "Addressed: <b>done</b> </script><script>x"}]}))
        rep_arg = ["--replies", os.path.join(content, "replies.json")]
        rc, log, page = run("cm", std + rep_arg)
        added = [json.loads(m) for m in CM_BLOCK.findall(region(page) or "")]
        case("replies are added as one block: the author is the agent of the named person, the text is kept and cannot end the block, the same reply twice is one",
             rc == 0 and len(added) == 2 and len(added[1]["items"]) == 1 and added[1]["items"][0]["by"] == "Ada L's agent" and added[1]["items"][0]["re"] == "c1"
             and added[1]["items"][0]["agent"] is True and added[1]["items"][0]["text"].endswith("</script><script>x") and "</script><script>x" not in region(page)
             and CM_BLOCK.sub("", region(page)) == "" and "in the page already" in log, log[-300:])
        case("an agent that names itself where the person's name goes is not shown as its own agent",
             [reply_author(x) for x in ("Agent", " the  AI agent ", "assistant", "", "Agnes", "Ada L")] == ["Agent", "Agent", "Agent", "Agent", "Agnes's agent", "Ada L's agent"])
        before = page
        only = lambda extra: subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--comments-only", "--out", cm_out] + extra, capture_output=True)
        text_of = lambda p: p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
        proc = only(rep_arg)
        case("a reply already in the page is not added again, and the page is not touched", proc.returncode == 0 and "is unchanged" in text_of(proc) and read(cm_out) == before, text_of(proc)[-300:])
        w("replies2.json", json.dumps([{"to": "c1", "text": "Deferred: later."}, {"to": "cgone", "text": "x"}]))
        proc = only(["--replies", os.path.join(content, "replies2.json")])
        after = read(cm_out)
        r_before, r_after = comments_region(before), comments_region(after)
        new_items = [c for m in CM_BLOCK.findall(region(after)) for c in json.loads(m)["items"]]
        case("--comments-only adds the replies and changes nothing else in the page; with no name the author is Agent",
             proc.returncode == 0 and after[:r_after[0]] == before[:r_before[0]] and after[r_after[1]:] == before[r_before[1]:] and region(after).startswith(region(before))
             and sum(1 for c in new_items if c.get("by") == "Agent") == 2 and not os.path.exists(cm_out + ".tmp"), text_of(proc)[-300:])
        for name, body, want in (("no list", json.dumps({"by": "A"}), "holds no list of replies"), ("no id", json.dumps([{"text": "x"}]), 'needs "to"'),
                                 ("empty text", json.dumps([{"to": "c1", "text": "  "}]), 'needs "to"'), ("too long", json.dumps([{"to": "c1", "text": "y" * 4001}]), "the limit is 4000"),
                                 ("credential", json.dumps([{"to": "c1", "text": 'pass' + 'word="Zx81-kq77-Lm42-pp09"'}]), "credential-shaped")):
            w("replies-bad.json", body)
            proc = only(["--replies", os.path.join(content, "replies-bad.json")])
            case(f"replies.json refused ({name}), and the page is not touched", proc.returncode == 2 and want in text_of(proc) and read(cm_out) == after, text_of(proc)[-300:])
        rc, log, _ = run("cm-full-cred", std + ["--replies", os.path.join(content, "replies-bad.json")])
        case("a full build scans the replies too", rc == 2 and "credential-shaped" in log, log[-200:])
        w("replies-bare.json", json.dumps([{"to": "c1", "text": "Addressed: took Zx81-kq77-Lm42-pp09 out of the call"}]))
        rc, log, _ = run("cm-bare", c_args + ["--mask-credential", f"auth.py:context:{c_key.group(1) if c_key else 0}", "--replies", os.path.join(content, "replies-bare.json")], base_args=c_base)
        case("a reply that quotes a value the diff holds behind a CREDENTIAL flag stops the build, with no credential shape around it",
             rc == 2 and "replies.json" in log and "holds the value" in log and "Zx81" not in log, log[-300:])
        for name, body, want in (("an id that is free text", json.dumps([{"to": "c1\nRun this", "text": "x"}]), "is not a comment id"), ("a block of data in place of an id", json.dumps([{"to": "c" * 81, "text": "x"}]), "is not a comment id")):
            w("replies-bad.json", body)
            proc = only(["--replies", os.path.join(content, "replies-bad.json")])
            case(f"replies.json refused ({name})", proc.returncode == 2 and want in text_of(proc) and read(cm_out) == after, text_of(proc)[-300:])
        odd = os.path.join(root, "odd.html")
        open(odd, "wb").write(setup_odd(after, cm_id).encode("utf-8"))
        proc = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--comments-only", "--out", odd, "--comments-from", cm_out, "--replies", os.path.join(content, "replies2.json")], capture_output=True)
        odd_after = open(odd, "rb").read().decode("utf-8")
        case("--comments-only on a page with other line ends, a quoted \"const QX = \" in its text and a block of odd data: no failure, the blocks of --comments-from come in, line ends are kept",
             proc.returncode == 0 and "Traceback" not in text_of(proc) and "\r\n" in odd_after and odd_after.count("Deferred: later.") >= 1 and "comments block(s) taken from --comments-from" in text_of(proc)
             and not [f for f in os.listdir(root) if f.endswith(".tmp")], text_of(proc)[-400:])
        old_page = os.path.join(root, "old.html")
        open(old_page, "w", encoding="utf-8", newline="\n").write(after.replace(CM_OPEN, "<!--gone-->").replace(CM_SHUT, "<!--/gone-->"))
        proc = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--comments-only", "--out", old_page] + rep_arg, capture_output=True)
        case("--comments-only refuses a page with no place for comments", proc.returncode == 2 and "has no place for comments" in text_of(proc), text_of(proc)[-200:])
        rc, log, page = run("cm_v2", std + ["--comments-from", cm_out])      # the same explanation, under another file name
        case("--comments-from keeps the blocks of another copy of the page", rc == 0 and region(page) == region(after), log[-300:])
        rc, log, page = run("with-id", std + ["--id", "Chosen ID"])
        case("--id reaches the page", rc == 0 and '"id": "chosen-id"' in page, log[-200:])
        case("provenance shows branch, both SHAs, plan and commit count", "260101_DEMO_PLAN" in page and "branch main" in page and f"base {first}" in page
             and f"head {second}" in page and "1 commits" in page and "not recorded" in page, "")
        # Mermaid-only, all parts
        w("arch.mmd", SELF_MMD_FLOW, diag)
        w("time.mmd", SELF_MMD_GANTT, diag)
        w("flow.mmd", SELF_MMD_SEQ, diag)
        w("brief-m.html", SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="time"></div>'), content)
        maps = {"views": [{"key": "system", "label": "System", "diagram": "arch", "tour": [{"caption": "Start", "highlight": ["A"]}, {"caption": "End", "highlight": ["B", "C"]}]},
                          {"key": "sequence", "label": "Sequence", "diagram": "flow", "tour": [{"caption": "Call", "highlight": ["request"]}]}]}
        w("maps-m.json", json.dumps(maps))
        allp = ["--brief", os.path.join(content, "brief-m.html"), "--rationales", os.path.join(content, "rationales.json"), "--roles", os.path.join(content, "roles.json"),
                "--parts", "brief,walkthrough,maps,summary,diff", "--walkthrough", os.path.join(content, "walkthrough.html"), "--maps", os.path.join(content, "maps-m.json"),
                "--diagrams", diag, "--ticket", "PSS-1", "--link", "Plan=https://example.invalid/plan"]
        rc, log, page = run("all-mermaid", allp)
        case("all parts with Mermaid-only diagrams", rc == 0 and MERMAID_URL in page and "cytoscape" not in page.lower() and 'class="sub-btn' in page, log[-400:])
        case("summary rows link to the diff", page.count('data-file="') == len(SELF_FILES) and "What src/api/handler.py does." in page, "")
        case("tickets and links are in the provenance", "PSS-1" in page and 'href="https://example.invalid/plan"' in page, "")
        case("without --lang the page says it is in English", '<html lang="en">' in page and "{{LANG}}" not in page, page[:80])
        rc, log, page = run("lang-fr", std + ["--parts", "brief", "--lang", "fr"])
        case("--lang sets the page's lang attribute", rc == 0 and '<html lang="fr">' in page, log[-200:] + page[:80])
        rc, log, page = run("lang-bad", std + ["--parts", "brief", "--lang", 'fr"><script>'])
        case("a --lang that is not a language code stops the build", rc == 2 and page == "" and "is not a language code" in log, log[-200:])
        # A # that Mermaid parses without an error and draws as other text
        hp = mermaid_hash_problems
        case("a # in a sequence message, a note or a participant name is refused, with its line",
             hp("sequenceDiagram\n  A->>B: User#save called\n") == ["line 2: in a sequence diagram the text after # is not drawn"]
             and len(hp("sequenceDiagram\n  participant A as User#save\n  A->>B: hi\n  Note right of A: see #field\n")) == 2, str(hp("sequenceDiagram\n  A->>B: User#save called\n")))
        case("#35; and a named entity pass in a sequence diagram, and so does a # in a comment line",
             hp("%% set by #12\nsequenceDiagram\n  %% see #field\n  A->>B: User#35;save #quot;now#quot;\n") == [], str(hp("sequenceDiagram\n  A->>B: User#35;save\n")))
        case("in a flowchart a # in a label passes and #word; is refused unless it is an entity",
             hp('flowchart TD\n  A["Device#owner"] --> B["#my_field"]\n  C["say #quot;hi#quot; #35;1"]\n') == []
             and hp('flowchart TD\n  A["#owner_id; set"]\n') == ["line 2: #owner_id; is drawn as &owner_id;"], str(hp('flowchart TD\n  A["#owner_id; set"]\n')))
        case("a colour in a style line is not taken for text", hp("flowchart TD\n  A --> B\n  classDef new fill:#e6ffec,stroke:#abc;\n  style A fill:#fed;\n") == [], "")
        w("flow.mmd", "sequenceDiagram\n  Client->>Server: User#save\n  Server-->>Client: response\n", diag)
        rc, log, page = run("mermaid-hash", allp)
        case("a Mermaid source that would be drawn with other text stops the build, which says what to write",
             rc == 2 and page == "" and "flow.mmd refused" in log and "line 2" in log and "#35;" in log, log[-300:])
        w("flow.mmd", SELF_MMD_SEQ, diag)
        # Screenshots named by a figure and read from the --shots folder
        sdir = os.path.join(root, "shots")
        os.makedirs(sdir)
        wb = lambda name, data, folder=sdir: open(os.path.join(folder, name), "wb").write(data)
        wb("after.png", png(12, (10, 200, 30)))
        wb("before.png", png(12, (200, 20, 30)))
        wb("one.png", png(6, (9, 9, 9)))
        wb("spare.png", png(6, (1, 1, 1)))
        pasted = '<figure style="margin:0 0 28px 0;">\n  <img src="data:image/png;base64,AAAA"\n       alt="x" />\n  <figcaption style="color:#555;">Pasted by hand</figcaption>\n</figure>'
        pair = '<figure data-shot="after.png" data-before="before.png" data-changed="Answer to comment 2">The orders screen, <code>before</code> and after.</figure>'
        shot_brief = lambda extra: w("brief-shots.html", SELF_BRIEF.replace("{DIAGRAM}", extra)) and None
        sargs = ["--brief", os.path.join(content, "brief-shots.html"), "--rationales", os.path.join(content, "rationales.json"), "--parts", "brief,walkthrough",
                 "--walkthrough", os.path.join(content, "walk-shots.html")]
        w("walk-shots.html", "<section data-subsystem=\"UI\"><h2>UI</h2><p>y</p><figure class='wide' data-shot='one.png'>The new setting.</figure></section>")
        shot_brief(pair + pasted)
        rc, log, page = run("shots", sargs + ["--shots", sdir])
        uri = lambda name: "data:image/png;base64," + base64.b64encode(open(os.path.join(sdir, name), "rb").read()).decode("ascii")
        case("a figure that names a screenshot and its before picture becomes a pair that carries both pictures and the caption",
             rc == 0 and '<figure class="shot shot-pair" data-changed="Answer to comment 2">' in page and uri("after.png") in page and uri("before.png") in page
             and "<figcaption>The orders screen, <code>before</code> and after.</figcaption>" in page and "data-shot" not in page and "data-before" not in page
             and 'alt="Before: The orders screen, before and after."' in page and page.count('class="shot-v') == 2 and 'class="shot-sbs"' in page, log[-400:])
        case("a figure in the walkthrough is filled too, keeps its own class, and a single picture has no switch",
             '<figure class="shot wide">' in page and uri("one.png") in page and page.count('class="shot-big"') == 2 and page.count('class="shot-sbs"') == 1, "")
        case("a figure with no data-shot is left exactly as it was written", pasted in page, "")
        case("the build counts the screenshots and names a picture no figure uses",
             "NOTE\t2 screenshot figure(s), 3 picture(s)" in log and "WARN\tscreenshot spare.png is in --shots and no figure names it" in log and "after.png is in" not in log, log[-500:])
        for n in range(10):
            wb(f"big{n}.png", png(8, (n, n, n)) + os.urandom(300 * 1024))
        shot_brief("".join(f'<figure data-shot="big{n}.png">Screen {n}.</figure>' for n in range(10)))
        rc, log, page = run("shots-many", sargs + ["--shots", sdir])
        case("ten pictures of 300 KiB build: the page has no limit on screenshots together", rc == 0 and page.count('class="shot"') == 10 and "10 picture(s)" not in log and "11 picture(s)" in log, log[-400:])
        heavy = Shots(None)
        heavy.figures, heavy.pictures, heavy.bytes = 1, 1, SHOT_HEAVY + 1
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            heavy.report()
        case("above 20 MiB of screenshots the build says the page is heavy and that this is not a limit", "not a limit" in said.getvalue() and "do not leave a screen out" in said.getvalue(), said.getvalue())
        shot_brief('<figure data-shot="after.png">Same words.</figure><figure data-shot="one.png">Same words.</figure>')
        rc, log, page = run("shots-twice", sargs + ["--shots", sdir])
        case("two screenshots with the same caption build with a warning", rc == 0 and "caption(s) are used more than once" in log, log[-400:])
        wb("huge.png", png(8, (0, 0, 0)) + os.urandom(SHOT_CAP))
        wb("fake.png", b"this is text, not a picture\n")
        wb("tok.png", png(5, (1, 2, 3)) + b"gh" + b"p_" + b"A" * 36)
        for extra, flags, want, name in (
                ('<figure data-shot="nowhere.png">A caption.</figure>', ["--shots", sdir], ["has no such picture", "after.png"], "a screenshot name that is not in the folder stops the build, which lists the folder"),
                ('<figure data-shot="after.png">A caption.</figure>', [], ["no --shots folder was given"], "a figure that names a screenshot without --shots stops the build"),
                ('<figure data-shot="huge.png">A caption.</figure>', ["--shots", sdir], ["over the 2048 KiB limit", "Do not leave the screen out"], "a picture over the limit for one picture stops the build, which says how to make it smaller"),
                ('<figure data-shot="fake.png">A caption.</figure>', ["--shots", sdir], ["not a readable .png picture"], "a file that is not the picture its name says stops the build"),
                ('<figure data-shot="tok.png">A caption.</figure>', ["--shots", sdir], ["credential-shaped text in its data"], "a screenshot whose data holds credential-shaped text stops the build"),
                ('<figure data-shot="after.png">  </figure>', ["--shots", sdir], ["needs a caption"], "a screenshot with no caption stops the build"),
                ('<figure data-shot="after.png"><img src="x.png">A caption.</figure>', ["--shots", sdir], ["needs a caption and nothing else"], "a screenshot figure that already holds a picture stops the build")):
            shot_brief(extra)
            rc, log, page = run("shots-bad", sargs + flags)
            case(name, rc == 2 and page == "" and all(x in log for x in want), log[-300:])
        # Refusals and failures that need no d2
        rc, log, page = run("bad-cred", ["--brief", os.path.join(content, "brief.html"), "--rationales", os.path.join(content, "rationales.json"), "--ticket", "pass" + 'word = "Zq7Mv2Lp9Xk4"'])
        case("credential-shaped ticket is refused", rc == 2 and page == "", log[-200:])
        w("bad-brief.html", SELF_BRIEF.replace("{DIAGRAM}", "") + "<p>use pass" + 'word = "Zq7Mv2Lp9Xk4" here</p>')
        rc, log, page = run("bad-cred2", ["--brief", os.path.join(content, "bad-brief.html"), "--rationales", os.path.join(content, "rationales.json")])
        case("credential-shaped brief is refused", rc == 2 and page == "", log[-200:])
        rc, log, page = run("bad-parts", std + ["--parts", "brief,nonsense"])
        case("unknown part is refused", rc == 2, log[-200:])
        rc, log, page = run("no-walk", std + ["--parts", "brief,walkthrough"])
        case("walkthrough part without its file is refused", rc == 2, log[-200:])
        rc, log, page = run("diff-file-no-base", std, base_args=["--diff-file", diff_file])
        case("--diff-file without --base and --head is refused", rc == 2, log[-200:])
        rc, log, page = run("diff-file", std + ["--base", "abc1234", "--head", "feature"], base_args=["--diff-file", diff_file])
        case("--diff-file page builds", rc == 0 and "abc1234" in page, log[-300:])
        w("ghost.html", SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="ghost"></div>'), content)
        rc, log, page = run("ghost", ["--brief", os.path.join(content, "ghost.html"), "--rationales", os.path.join(content, "rationales.json"), "--diagrams", diag])
        case("placeholder naming a missing diagram is refused", rc == 2 and "ghost" in log, log[-200:])
        both = os.path.join(root, "both")
        os.makedirs(both)
        w("x.d2", "a -> b\n", both)
        w("x.mmd", SELF_MMD_FLOW, both)
        rc, log, page = run("both", std + ["--diagrams", both])
        case("a diagram in both D2 and Mermaid is refused", rc == 2 and "both" in log, log[-200:])
        for label, body, want in (("icon:", "a: A {icon: https://example.invalid/i.svg}\n", "construct icon:"), ("@import", "@import foo\na -> b\n", "construct @import"),
                                  ("...@ import", "...@other\n", "construct ...@"), ("a double-quoted @ import", 'x: @"C:/other/file"\n', "construct @ import"),
                                  ("a single-quoted @ import", "x: @'../other'\n", "construct @ import"), ("link:", 'a: A {link: "javascript:alert(1)"}\n', "construct link:"),
                                  ("layers:", "layers: { x: { a } }\na\n", "construct layers:"), ("steps:", "steps: { x: { a } }\na\n", "construct layers:"),
                                  ("credential-shaped text", "pass" + 'word = "Zq7Mv2Lp9Xk4"\n', "credential-shaped")):
            bad = os.path.join(root, "bad-d2")
            shutil.rmtree(bad, ignore_errors=True)
            os.makedirs(bad)
            w("bad.d2", body, bad)
            w("brief-bad.html", SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="bad"></div>'), content)
            rc, log, page = run("bad-d2", ["--brief", os.path.join(content, "brief-bad.html"), "--rationales", os.path.join(content, "rationales.json"), "--diagrams", bad])
            case(f"D2 source with {label} is refused, naming the construct", rc == 2 and page == "" and want in log, log[-300:])
        rc, log, page = run("base-only", std + ["--base", "x"])
        case("--base without --diff-file is refused", rc == 2 and "only for --diff-file" in log, log[-200:])
        for bad in ("Plan=https://example.invalid/p?X-Amz-Signature=abc", "Plan=https://example.invalid/p?token=abc", "Plan=https://user:pw@example.invalid/p"):
            rc, log, page = run("bad-link", std + ["--link", bad])
            case(f"--link {bad.split('?')[-1][:20]} is refused", rc == 2 and page == "" and "--link" in log, log[-200:])
        rc, log, page = run("brief-maps", ["--brief", os.path.join(content, "brief-m.html"), "--rationales", os.path.join(content, "rationales.json"), "--parts", "brief,maps",
                                           "--maps", os.path.join(content, "maps-m.json"), "--diagrams", diag])
        case("brief and maps page without diff", rc == 0 and 'id="part-diff"' not in page and 'id="part-maps"' in page, log[-300:])
        rc, log, page = run("brief-summary", std + ["--parts", "brief,summary", "--roles", os.path.join(content, "roles.json")])
        case("summary without diff has no links into it", rc == 0 and "What src/api/handler.py does." in page and 'data-file="' not in page and 'id="part-diff"' not in page, log[-300:])
        # D2 hidden: the env points at nothing and PATH is an empty folder; --diff-file needs no git.
        good = os.path.join(root, "good-d2")
        os.makedirs(good)
        w("arch.d2", SELF_D2_ARCH, good)
        w("brief-d2.html", SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="arch"></div>'), content)
        empty = os.path.join(root, "empty-path")
        os.makedirs(empty)
        hidden = {**os.environ, "QEXPLAIN_D2": os.path.join(root, "no-such-d2"), "PATH": empty}
        rc, log, page = run("d2-missing", ["--brief", os.path.join(content, "brief-d2.html"), "--rationales", os.path.join(content, "rationales.json"), "--diagrams", good,
                                           "--base", "a", "--head", "b"], env=hidden, base_args=["--diff-file", diff_file])
        case("a D2 source with d2 missing fails clearly", rc == 2 and "d2 was not found" in log and page == "", log[-300:])
        # D2 render cases: skipped, and counted as skipped, when d2 is absent.
        if exe:
            w("seq.d2", SELF_D2_SEQ, good)
            w("brief-d2.html", SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="arch"></div><div data-diagram="seq"></div>' + '<div data-diagram="time"></div>'), content)
            w("time.mmd", SELF_MMD_GANTT, good)
            d2maps = {"views": [
                {"key": "system", "label": "System", "diagram": "arch", "subsystem": "Core",
                 "tour": [{"caption": "The broker", "highlight": ["site.broker"]}, {"caption": "Link", "highlight": ["site.ap", "site.broker"]},
                          {"caption": "Edge", "highlight": ["site.(ap -> broker)[0]"]}]},
                {"key": "sequence", "label": "Sequence", "diagram": "seq", "subsystem": "Core", "tour": [{"caption": "Call", "highlight": ["(a -> b)[0]"]}]},
                {"key": "dataflow", "label": "Flow", "diagram": "arch", "subsystem": "Edge site", "tour": [{"caption": "The site", "highlight": ["site.ap"]}]}]}
            w("maps-d2.json", json.dumps(d2maps))
            args = ["--brief", os.path.join(content, "brief-d2.html"), "--rationales", os.path.join(content, "rationales.json"), "--roles", os.path.join(content, "roles.json"),
                    "--parts", "brief,walkthrough,maps,summary,diff", "--walkthrough", os.path.join(content, "walkthrough.html"), "--maps", os.path.join(content, "maps-d2.json"), "--diagrams", good]
            rc, log, page = run("all-d2", args)
            case("all parts with D2 architecture and sequence diagrams", rc == 0 and "D2: v" in page, log[-500:], d2=True)
            case("each diagram names itself on its wrapper and in the page data", bool(re.search(r'<div class="dg" id="dg-\d+" data-name="arch" data-kind="d2">', page))
                 and bool(re.search(r'"dg": \{', page)) and bool(re.search(r'"arch": \{\s*"kind": "d2",\s*"ids": \{', page)) and '"src": ' in page, page[page.find('"dg"'):][:160], d2=True)
            case("each D2 diagram is inlined in four variants", all(page.count(f'class="dgv v-{t} v-{s}"') >= 3 for t in ("light", "dark") for s in ("sketch", "classic")), "", d2=True)
            import collections
            ids = re.findall(r'\sid="([^"]+)"', page)
            case("the Maps tour carries resolved, non-empty D2 class tokens", bool(re.search(r'"mark": \[\s*"[^"]+"', page)) and bool(re.search(r'"tokens": \[\s*"[^"]+"', page)), "", d2=True)
            case("a diagram used twice has no duplicate ids", len(ids) == len(set(ids)) and len(ids) > 20, str([k for k, v in collections.Counter(ids).items() if v > 1][:4]), d2=True)
            case("system view has the Show changes switch", "Show changes" in page and "toggleChanges" in page, "", d2=True)
            case("Maps get one sub-tab per subsystem", 'data-sub="maps-core"' in page and 'data-sub="maps-edge-site"' in page, "", d2=True)
            case("Mermaid gantt sits beside D2 in the brief", 'class="mermaid mmd"' in page, "", d2=True)
            ids_ok = "<svg" in page and "Gateway" in page
            case("D2 text reaches the page", ids_ok, "", d2=True)
            w("maps-bad.json", json.dumps({"views": [{"key": "system", "label": "S", "diagram": "arch", "tour": [{"caption": "x", "highlight": ["site.nope"]}]}]}))
            rc, log, page = run("bad-tour", ["--brief", os.path.join(content, "brief.html"), "--rationales", os.path.join(content, "rationales.json"), "--parts", "brief,maps",
                                             "--maps", os.path.join(content, "maps-bad.json"), "--diagrams", good])
            case("an unknown tour id fails and lists the valid ids", rc == 2 and "site.broker" in log and page == "", log[-300:], d2=True)
            w("maps-short.json", json.dumps({"views": [{"key": "system", "label": "S", "diagram": "arch", "tour": []}]}))
            rc, log, page = run("short-tour", ["--brief", os.path.join(content, "brief.html"), "--rationales", os.path.join(content, "rationales.json"), "--parts", "brief,maps",
                                               "--maps", os.path.join(content, "maps-short.json"), "--diagrams", good])
            case("a map view with fewer tour steps than the tier's lowest number stops the build, which says how many it asks",
                 rc == 2 and page == "" and "fewer tour steps" in log and "Tiny: at least 1" in log and "system (0)" in log, log[-300:], d2=True)
            w("broken.d2", "a -> {\n", good)
            w("brief-broken.html", SELF_BRIEF.replace("{DIAGRAM}", '<div data-diagram="broken"></div>'), content)
            rc, log, page = run("broken", ["--brief", os.path.join(content, "brief-broken.html"), "--rationales", os.path.join(content, "rationales.json"), "--diagrams", good])
            case("a D2 source that does not compile fails clearly", rc == 2 and "could not render" in log, log[-300:], d2=True)

    failed = [r for r in results if not r[0]]
    for ok, name, note in results:
        print(("PASS\t" if ok else "FAIL\t") + name + ("" if ok else "\t" + note.replace("\n", " | ")))
    print(f"build selftest: {len(results)} cases, {len(failed)} failed")
    print(f"D2 cases: {d2_cases[0]} run" if exe else "D2 cases: skipped (d2 not found)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
