#!/usr/bin/env python3
"""Build a /qexplain artifact from the shared template and the agent's content files.

The agent writes the parts that need judgement (narrative, maps, change summary,
per-file rationales). This script does the mechanical rest: captures the diff as
UTF-8, inlines every piece of data safely inside the page's script, wires the map
tabs, then runs the validator on the result.

Standard library only; nothing to install. <python> is <config-repo>/.venv-agent-playbook/Scripts/python.exe -I.

Usage:
    <python> build-explanation.py --out <path.html> --title <text> \
        --base <base-ref> --head <head-ref> \
        (--diff-args "<git diff arguments>" | --diff-file <unified.diff> \
         | --target "<label>=<repo>::<git diff arguments>" ...) \
        --narrative <narrative.html> --summary <summary.html> \
        --maps <maps.json> --rationales <rationales.json> [--repo <dir>] \
        [--exclude <glob>]... [--allow-credential <path>:<side>:<line>]...

--target may repeat, one per repo. Each repo's paths then start with <label>/, and
rationales.json uses those labelled paths. Give --base and --head one readable text
that names each repo's ref.

--exclude leaves a file out of the page, on top of a built-in list of secret-bearing file
names. The page names each file left out, with its line counts and never its content.

Any remaining credential-shaped text stops the build, with its path and line and never its
value. Exclude the file, or pass --allow-credential with the match's path, side and line as
measure-change.py prints them (for example a_test.go:new:12), which the build accepts only for
a match marked made-up-test-value=yes. --mask-credential takes the same form for any match: it
replaces the value on the page and keeps the rest of the file, so prefer it for a test file.
--user-confirmed-credential is for a match the user has personally said is not a live credential.
Text in the content files, title and refs cannot be allowed; reword it.

Content files:
    narrative.html, summary.html  HTML fragments, placed inside the part's page column.
    rationales.json               {"path/in/diff": "One sentence on why it changed.", ...}
    maps.json                     {"views": [view, ...]}. Each view has "key" (system,
                                  dataflow, deps, actions, sequence), "label", "kind" and
                                  optional "note" and "tour". By kind:
                                    graph:    "elements" (Cytoscape nodes and edges),
                                              optional "rankDir" ("LR" default, or "TB");
                                              tour steps {"caption", "highlight": [ids]}
                                    sequence: "mermaid" (sequenceDiagram source);
                                              tour steps {"caption", "scrollTo": text}
                                    cards:    "html" (elements tagged data-node="<id>");
                                              tour steps {"caption", "highlight": [ids]}

Exit codes:
    0  built, and every validator check passed
    1  built, but a validator check FAILed
    2  bad input; nothing written
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I leaves the script's folder off the path
import qexplain_diff as qd  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "assets", "template.html")
VALIDATOR = os.path.join(HERE, "validate-explanation.py")
VIEW_ORDER = ["system", "dataflow", "deps", "actions", "sequence"]
KINDS = {"graph", "sequence", "cards"}


def fail(msg):
    print(f"ERROR\t{msg}", file=sys.stderr)
    sys.exit(2)


def read(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read {path} as UTF-8: {exc}")


def read_json(path):
    try:
        return json.loads(read(path))
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")


def capture_diff(args):
    if args.diff_file:
        return read(args.diff_file)
    try:
        if args.target:
            parts = [qd.capture(repo, diff_args, label)
                     for label, repo, diff_args in (qd.parse_target(t) for t in args.target)]
            return "\n".join(p.rstrip("\n") for p in parts if p.strip()) + "\n"
        return qd.capture(args.repo, args.diff_args)
    except (ValueError, RuntimeError) as exc:
        fail(str(exc))


def check_views(maps):
    views = maps.get("views") if isinstance(maps, dict) else None
    if not isinstance(views, list):
        fail('maps.json must be an object with a "views" list')
    seen = set()
    for v in views:
        key, kind = v.get("key"), v.get("kind")
        if key not in VIEW_ORDER:
            fail(f"map view key {key!r} is not one of {', '.join(VIEW_ORDER)}")
        if key in seen:
            fail(f"map view {key!r} appears twice")
        seen.add(key)
        if kind not in KINDS:
            fail(f"map view {key!r}: kind must be one of {', '.join(sorted(KINDS))}")
        need = {"graph": "elements", "sequence": "mermaid", "cards": "html"}[kind]
        if not v.get(need):
            fail(f"map view {key!r} of kind {kind} needs a non-empty {need!r}")
        if not v.get("label"):
            fail(f"map view {key!r} needs a label")
    return sorted(views, key=lambda v: VIEW_ORDER.index(v["key"]))


def maps_html(views):
    if not views:
        return "<p>No maps at this size tier.</p>"
    bar = "".join(
        f'<button class="map-btn{" active" if i == 0 else ""}" data-view="{v["key"]}" '
        f'onclick="switchMap(\'{v["key"]}\')">{html.escape(v["label"])}</button>'
        for i, v in enumerate(views)
    )
    panels = "".join(
        f'<div id="view-{v["key"]}" class="map-panel{" active" if i == 0 else ""}"></div>\n'
        for i, v in enumerate(views)
    )
    return f'<div class="map-bar">{bar}</div>\n{panels}'


def script_json(data):
    # "<" never appears raw, so no "</script>" or "<!--" inside the data can end the script early.
    text = json.dumps(data, ensure_ascii=False, indent=1)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def main():
    # -I ignores PYTHONIOENCODING, and a piped Windows console cannot print every file name.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--base", required=True, help="base commit SHA")
    ap.add_argument("--head", required=True, help="head branch name, or SHA when there is no branch")
    src = ap.add_mutually_exclusive_group(required=True)
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
    ap.add_argument("--narrative", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--maps", required=True)
    ap.add_argument("--rationales", required=True)
    args = ap.parse_args()

    raw = capture_diff(args)
    if not raw.strip():
        fail("the diff is empty")
    kept, left_out, unused = qd.filter_files(qd.split_files(raw), args.exclude)
    if not kept:
        fail("no file can be shown: every file was left out, or the input holds no diff. "
             "Check the LEFT-OUT lines from measure-change.py and tell the user this change has no page")
    kept, unmatched = qd.mask_files(kept, args.mask_credential)
    if unmatched:
        fail("--mask-credential matched nothing: " + ", ".join(qd.safe_path(k) for k in unmatched))
    for key in args.mask_credential:
        print(f"MASKED\t{qd.safe_path(key)}")
    raw = "\n".join(block for _, block in kept) + "\n"
    if unused:
        fail("--exclude matched nothing, so a file meant to stay out may be on the page: " + ", ".join(unused))
    rationales = read_json(args.rationales)
    if not isinstance(rationales, dict):
        fail("rationales.json must map file paths to sentences")
    views = check_views(read_json(args.maps))
    narrative, summary = read(args.narrative), read(args.summary)

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
    for name, text in (("narrative", narrative), ("summary", summary), ("maps.json", read(args.maps)),
                       ("rationales.json", read(args.rationales)), ("title and refs", f"{args.title}\n{args.base}\n{args.head}")):
        hits += qd.scan_content_file(name, text)
    if hits:
        for hit in hits:
            print(qd.hit_line(hit), file=sys.stderr)
        fail("credential-shaped text found; nothing written. Exclude the file, allow a made-up test value by its "
             "path:side:line, or reword your own text")

    page = read(TEMPLATE)
    slots = {
        "{{TITLE}}": html.escape(args.title),
        "{{BASE_REF}}": html.escape(args.base),
        "{{HEAD_REF}}": html.escape(args.head),
        "<!--@NARRATIVE-->": narrative,
        "<!--@MAPS-->": maps_html(views),
        "<!--@SUMMARY-->": summary,
        "/*@DATA*/": "const QX = " + script_json({
            "base": args.base, "head": args.head, "views": views,
            "rationales": rationales, "rawDiff": raw, "excluded": left_out,
            "paths": [path for path, _ in kept],
        }) + ";",
    }
    for marker in slots:
        if marker not in page:
            fail(f"template is missing the {marker} slot")
    # One pass, so text inside a filled slot is never mistaken for another slot.
    page = re.sub("|".join(re.escape(m) for m in slots), lambda m: slots[m.group(0)], page)

    paths = [path for path, _ in kept]
    for item in left_out:
        print(f"LEFT-OUT\t{qd.safe_path(item['path'])}\t+{item['add']} -{item['del']}\t{item['reason']}")
    for p in paths:
        if p not in rationales:
            print(f"WARN\tno rationale for {qd.safe_path(p)}")
    for p in rationales:
        if p not in paths:
            print(f"WARN\trationale for {qd.safe_path(p)}, which is not in the diff")
    changed = sum(sum(qd.counts(block)) for _, block in kept)
    if changed > 2000:
        print("NOTE\tThis diff is large; the artifact may take a few seconds to parse on first load.")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print(f"WROTE\t{args.out}\t{len(paths)} files, {changed} changed lines")

    return subprocess.run([sys.executable, VALIDATOR, args.out]).returncode


if __name__ == "__main__":
    sys.exit(main())
