#!/usr/bin/env python3
"""Validate a /qexplain explanation artifact.

Checks the generated HTML against the guarantees the skill promises: external
libraries are version-pinned and from a known CDN, nothing depends on an API
that dies on a file:// origin, code blocks keep their newlines, every link
resolves, every part and map tab has a panel (and every part-panel has a
matching control and vice versa), the Narrative part says what was verified,
and no emoji.

Standard library only; nothing to install. <python> is the interpreter of <config-repo>/.venv-agent-playbook, run with -I (shared/AGENTS.md, Config Repo Locations).

Usage:
    <python> validate-explanation.py <path-to-html>

Exit codes:
    0  every check passed
    1  at least one check FAILed
    2  the file could not be read
"""

import argparse
import os
import re
import sys
from html.parser import HTMLParser

# CDNs the skill is allowed to load from. Edit deliberately.
KNOWN_HOSTS = {"cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com"}

# A pinned URL carries a full semver somewhere in the path.
SEMVER = re.compile(r"\d+\.\d+\.\d+")
UNPINNED = re.compile(r"@(latest|\^|~|\*)|@\d+(?:\.\d+)?/", re.I)

# Emoji-bearing ranges. Arrows (U+2190-U+21FF) and box drawing are deliberately
# excluded -- they are legitimate in a diagram.
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-⛿✀-➿️⬀-⯿]")

REMOTE_URL = re.compile(
    r"""(?:\bsrc\s*=\s*["']|<link\b[^>]*?\bhref\s*=\s*["']"""
    r"""|url\(\s*["']?|@import\s+["'])\s*((?:https?:)?//[^"')\s]+)""",
    re.I,
)

# Module scripts are blocked on a file:// origin in most browsers. UMD builds
# are the reason this skill pins dist/*.min.js rather than *.esm.mjs.
MODULE_SCRIPT = re.compile(r"""<script\b[^>]*\btype\s*=\s*["']module["']""", re.I)

# The artifact's own data must be inlined, not fetched at runtime.
RUNTIME_FETCH = re.compile(
    r"\bfetch\s*\(|\bXMLHttpRequest\b|\bd3\.(?:json|csv|tsv|text|xml)\s*\("
    r"|\bnavigator\.sendBeacon\b|\bnew\s+WebSocket\b|\bEventSource\b"
)

WHITESPACE_OK = re.compile(r"white-space\s*:\s*(pre|pre-wrap|break-spaces)", re.I)
CODEISH_CLASS = re.compile(r"\b(code|snippet|sample|listing|diff)\b", re.I)


class Doc(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.anchor_targets = []       # hrefs of the form #foo
        self.tab_views = []            # data-view="key" on a map control
        self.panel_views = set()       # id="view-key"
        self.part_controls = []        # data-part="key" on a part control
        self.part_panels = {}          # key -> Optional[str]: data-source string if present, None if absent (retained as dead store; available for future extension)
        self.code_containers = []      # (tag, classes, has_inline_whitespace)
        self.pre_depth = 0
        self.in_title = False
        self.title = ""
        self.saw_html = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.saw_html = True
        if tag == "title":
            self.in_title = True

        el_id = a.get("id")
        if el_id:
            self.ids.add(el_id)
            if el_id.startswith("view-"):
                self.panel_views.add(el_id[len("view-"):])
            if el_id.startswith("part-"):
                self.part_panels[el_id[len("part-"):]] = a.get("data-source")

        href = a.get("href")
        if href and href.startswith("#") and len(href) > 1:
            self.anchor_targets.append(href[1:])

        if a.get("data-view"):
            self.tab_views.append(a["data-view"])
        if a.get("data-part") and not (el_id or "").startswith("part-"):
            self.part_controls.append(a["data-part"])

        if tag == "pre":
            self.pre_depth += 1
            return

        classes = (a.get("class") or "").split()
        inline_ws = bool(WHITESPACE_OK.search(a.get("style") or ""))
        if self.pre_depth == 0:
            if tag == "code" or any(CODEISH_CLASS.search(c) for c in classes):
                self.code_containers.append((tag, classes, inline_ws))

    def handle_endtag(self, tag):
        if tag == "pre" and self.pre_depth > 0:
            self.pre_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def whitespace_safe_selectors(source):
    """Class names, and the code tag itself, whose CSS rule preserves whitespace."""
    safe, code_tag_safe = set(), False
    for style in re.findall(r"<style\b[^>]*>(.*?)</style>", source, re.S | re.I):
        for rule in style.split("}"):
            if "{" not in rule:
                continue
            selector, _, body = rule.partition("{")
            if WHITESPACE_OK.search(body):
                safe.update(re.findall(r"\.([A-Za-z0-9_-]+)", selector))
                # A bare `code` selector (not `.x code` or `code.x`) covers every <code>.
                if any(part.strip() == "code" for part in selector.split(",")):
                    code_tag_safe = True
    return safe, code_tag_safe


def host_of(url):
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


def run(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        source = fh.read()

    doc = Doc()
    doc.feed(source)
    results = []

    def check(name, ok, detail=""):
        results.append(("PASS" if ok else "FAIL", name, "" if ok else detail))

    check("document-shape", doc.saw_html, "no <html> element -- not a standalone page")
    check("title-present", bool(doc.title.strip()), "missing or empty <title>")

    # External libraries: allowed, but pinned and from a known CDN.
    bad_urls = []
    for url in REMOTE_URL.findall(source):
        h = host_of(url)
        if h not in KNOWN_HOSTS:
            bad_urls.append(f"{url} (unknown host {h})")
        elif UNPINNED.search(url) or not SEMVER.search(url):
            bad_urls.append(f"{url} (not pinned to an exact version)")
    check("remote-assets-pinned", not bad_urls, "; ".join(bad_urls[:4]))

    check(
        "no-module-scripts",
        not MODULE_SCRIPT.search(source),
        '<script type="module"> is blocked on a file:// origin -- use the UMD build',
    )
    check(
        "no-runtime-fetch",
        not RUNTIME_FETCH.search(source),
        "runtime data fetch found -- the artifact's own data must be inlined",
    )

    safe, code_tag_safe = whitespace_safe_selectors(source)
    offenders = [
        f"<{tag} class=\"{' '.join(classes) or '(none)'}\">"
        for tag, classes, inline_ws in doc.code_containers
        if not inline_ws and not any(c in safe for c in classes)
        and not (tag == "code" and code_tag_safe)
    ]
    check(
        "code-whitespace",
        not offenders,
        "code container outside <pre> with no white-space: pre/pre-wrap: "
        + ", ".join(offenders[:5]),
    )

    dangling = sorted({t for t in doc.anchor_targets if t not in doc.ids})
    check(
        "anchors-resolve",
        not dangling,
        "href targets with no matching id: " + ", ".join(dangling[:8]),
    )

    # Map sub-tabs.
    tabs = set(doc.tab_views)
    detail = []
    if tabs - doc.panel_views:
        detail.append("map tabs with no panel: " + ", ".join(sorted(tabs - doc.panel_views)))
    if doc.panel_views - tabs:
        detail.append("map panels with no tab: " + ", ".join(sorted(doc.panel_views - tabs)))
    check("tabs-wired", not detail, "; ".join(detail))

    # Top-level parts — controls and panels must match one-to-one; fails if no panels found.
    controls = set(doc.part_controls)
    panels = set(doc.part_panels)
    pdetail = []
    if not panels:
        pdetail.append("no part panels found (expected id=\"part-<key>\")")
    if controls - panels:
        pdetail.append("part controls with no panel: " + ", ".join(sorted(controls - panels)))
    if panels - controls:
        pdetail.append("part panels with no control: " + ", ".join(sorted(panels - controls)))
    check("parts-wired", not pdetail, "; ".join(pdetail))

    # The section must sit in the Narrative part and say something after its heading.
    narrative = re.search(r"""id=["']part-narrative["'](.*?)id=["']part-maps["']""", source, re.S)
    section = re.search(r"""<(h[1-6])\b[^<>]{0,512}\bid=["']verified["'][^<>]{0,512}>.*?</\1>(.*?)(?=<h[1-6]\b|\Z)""",
                        narrative.group(1) if narrative else "", re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", section.group(2)) if section else ""
    check("verified-section", len(body.split()) >= 5,
          'no heading with id="verified" and text after it in the Narrative part -- '
          "it must say what was and was not verified")

    # The rule covers what the agent writes. The diff is the repo's own text, shown as it is.
    start = source.find('"rawDiff": "')
    end = source.find('"excluded":', start) if start >= 0 else -1
    written = source[:start] + source[end:] if start >= 0 and end >= 0 else source
    found = EMOJI.findall(written)
    check("no-emoji", not found, "emoji present: " + " ".join(sorted(set(found))[:8]))

    return results


def main():
    # -I ignores PYTHONIOENCODING, and a piped Windows console cannot print every character.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="path to the generated explanation HTML file")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        print(f"ERROR\tno such file: {args.path}", file=sys.stderr)
        return 2

    try:
        results = run(args.path)
    except OSError as exc:
        print(f"ERROR\t{exc}", file=sys.stderr)
        return 2

    failed = 0
    for status, name, detail in results:
        print(f"{status}\t{name}" + (f"\t{detail}" if detail else ""))
        if status == "FAIL":
            failed += 1

    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
