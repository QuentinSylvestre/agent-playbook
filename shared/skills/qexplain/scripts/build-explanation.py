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
        (--diff-args "<git diff arguments>" | --diff-file <unified.diff>) \
        --narrative <narrative.html> --summary <summary.html> \
        --maps <maps.json> --rationales <rationales.json> [--repo <dir>]

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
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "template.html")
VALIDATOR = os.path.join(HERE, "validate-explanation.py")
VIEW_ORDER = ["system", "dataflow", "deps", "actions", "sequence"]
KINDS = {"graph", "sequence", "cards"}


def fail(msg):
    print(f"ERROR\t{msg}", file=sys.stderr)
    sys.exit(2)


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")


def read_json(path):
    try:
        return json.loads(read(path))
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}")


def capture_diff(args):
    if args.diff_file:
        return read(args.diff_file)
    cmd = ["git", "-C", args.repo, "-c", "core.quotepath=off", "diff", "--unified=3", "--no-color",
           "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/"] + shlex.split(args.diff_args)
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        fail("git diff failed: " + proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout.decode("utf-8", "replace")


def changed_paths(raw):
    paths = []
    for line in raw.split("\n"):
        if line.startswith("diff --git a/") and " b/" in line:
            paths.append(line.rsplit(" b/", 1)[1])
    return paths


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
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--base", required=True, help="base commit SHA")
    ap.add_argument("--head", required=True, help="head branch name, or SHA when there is no branch")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--diff-args", help='arguments for git diff, e.g. "abc123..def456" or "main...HEAD -- src/"')
    src.add_argument("--diff-file", help="a unified diff already captured as UTF-8 (e.g. from a PR)")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--narrative", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--maps", required=True)
    ap.add_argument("--rationales", required=True)
    args = ap.parse_args()

    raw = capture_diff(args)
    if not raw.strip():
        fail("the diff is empty")
    rationales = read_json(args.rationales)
    if not isinstance(rationales, dict):
        fail("rationales.json must map file paths to sentences")
    views = check_views(read_json(args.maps))

    page = read(TEMPLATE)
    slots = {
        "{{TITLE}}": html.escape(args.title),
        "{{BASE_REF}}": html.escape(args.base),
        "{{HEAD_REF}}": html.escape(args.head),
        "<!--@NARRATIVE-->": read(args.narrative),
        "<!--@MAPS-->": maps_html(views),
        "<!--@SUMMARY-->": read(args.summary),
        "/*@DATA*/": "const QX = " + script_json({
            "base": args.base, "head": args.head, "views": views,
            "rationales": rationales, "rawDiff": raw,
        }) + ";",
    }
    for marker in slots:
        if marker not in page:
            fail(f"template is missing the {marker} slot")
    # One pass, so text inside a filled slot is never mistaken for another slot.
    page = re.sub("|".join(re.escape(m) for m in slots), lambda m: slots[m.group(0)], page)

    paths = changed_paths(raw)
    for p in paths:
        if p not in rationales:
            print(f"WARN\tno rationale for {p}")
    for p in rationales:
        if p not in paths:
            print(f"WARN\trationale for {p}, which is not in the diff")
    changed = sum(1 for line in raw.split("\n")
                  if line[:1] in "+-" and not line.startswith(("+++", "---")))
    if changed > 2000:
        print("NOTE\tThis diff is large; the artifact may take a few seconds to parse on first load.")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(page)
    print(f"WROTE\t{args.out}\t{len(paths)} files, {changed} changed lines")

    return subprocess.run([sys.executable, VALIDATOR, args.out]).returncode


if __name__ == "__main__":
    sys.exit(main())
