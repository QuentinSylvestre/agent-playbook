#!/usr/bin/env python3
"""Validate a /qexplain explanation artifact.

Checks the generated HTML against the guarantees the skill promises: external
libraries are version-pinned and from a known CDN, nothing depends on an API
that dies on a file:// origin, code blocks keep their newlines, every link
resolves, every part, map tab and sub-tab has a panel (and the reverse), the
Brief has its fixed headings in order and says what was verified, and no emoji.
The page may hold any set of parts, so every check looks only at what is present.

Standard library only; nothing to install. <python> is the interpreter of <config-repo>/.venv-agent-playbook, run with -I (shared/AGENTS.md, Config Repo Locations).

Usage:
    <python> validate-explanation.py <path-to-html>
    <python> validate-explanation.py --selftest

Exit codes:
    0  every check passed (or the selftest passed)
    1  at least one check FAILed (or the selftest failed)
    2  the file could not be read
"""

import argparse
import json
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

# The Brief's heading ids, in the order they must appear. change-* ids share one rank.
BRIEF_ORDER = ["intent", "context", "change", "decisions", "precedent", "deploy", "surface", "verified", "open-items"]
BRIEF_REQUIRED = ["intent", "context", "change", "verified", "open-items"]
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
RAW_DIFF = re.compile(r'"rawDiff": "[^"\\]*(?:\\.[^"\\]*)*"')
# Active content a diagram or fragment must not carry: a javascript: URL, or a remote image-like resource.
JS_URL = re.compile(r"""\b(?:href|src)\s*=\s*["']\s*javascript:""", re.I)
REMOTE_RESOURCE = re.compile(r"""<(?:image|use|iframe|object|embed)\b[^>]*?\b(?:href|src|data)\s*=\s*["']\s*(?:https?:)?//""", re.I)


def brief_rank(el_id):
    """The Brief section a heading id names, or None when it is not one of the allowed ids."""
    if el_id.startswith("change-") and len(el_id) > len("change-"):
        return "change"
    return el_id if el_id in BRIEF_ORDER and el_id != "change" else None


class Doc(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.id_list = []              # every id, with repeats, to find duplicates
        self.anchor_targets = []       # hrefs of the form #foo
        self.tab_views = []            # data-view="key" on a map control
        self.panel_views = set()       # id="view-key"
        self.sub_tabs = []             # data-sub="key" on a sub-tab control
        self.sub_panels = set()        # id="sub-key"
        self.part_controls = []        # data-part="key" on a part control
        self.part_panels = set()       # id="part-key"
        self.code_containers = []      # (tag, classes, has_inline_whitespace)
        self.pre_depth = 0
        self.in_title = False
        self.title = ""
        self.saw_html = False
        # The Brief panel, read with the parser so a brief-only page and a nested panel both work.
        self.brief_depth = 0           # div depth inside the Brief panel; 0 means outside it
        self.brief_seen = False
        self.brief_headings = []       # heading ids in document order
        self.brief_sections = []       # [id, words] for each id-bearing heading
        self.svg_depth = 0
        self.skip_depth = 0            # inside <style> or <script>

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.saw_html = True
        if tag == "title":
            self.in_title = True
        if tag in ("style", "script"):
            self.skip_depth += 1
        if tag == "svg":
            self.svg_depth += 1

        el_id = a.get("id")
        if el_id:
            self.ids.add(el_id)
            self.id_list.append(el_id)
            if el_id.startswith("view-"):
                self.panel_views.add(el_id[len("view-"):])
            if el_id.startswith("sub-"):
                self.sub_panels.add(el_id[len("sub-"):])
            if el_id.startswith("part-"):
                self.part_panels.add(el_id[len("part-"):])

        href = a.get("href")
        if href and href.startswith("#") and len(href) > 1:
            self.anchor_targets.append(href[1:])

        if a.get("data-view"):
            self.tab_views.append(a["data-view"])
        if a.get("data-sub"):
            self.sub_tabs.append(a["data-sub"])
        if a.get("data-part") and not (el_id or "").startswith("part-"):
            self.part_controls.append(a["data-part"])

        if tag == "div":
            if self.brief_depth:
                self.brief_depth += 1
            elif el_id == "part-brief":
                self.brief_depth, self.brief_seen = 1, True
        if self.brief_depth and tag in HEADINGS and el_id and not self.svg_depth:
            self.brief_headings.append(el_id)
            self.brief_sections.append([el_id, []])

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
        if tag in ("style", "script") and self.skip_depth:
            self.skip_depth -= 1
        if tag == "svg" and self.svg_depth:
            self.svg_depth -= 1
        if tag == "div" and self.brief_depth:
            self.brief_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.brief_depth and not self.svg_depth and not self.skip_depth and self.brief_sections:
            self.brief_sections[-1][1].extend(data.split())


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


def check_brief(doc):
    """Return '' when the Brief is sound, else what is wrong. Reads heading ids only."""
    if not doc.brief_seen:
        return 'no Brief panel (id="part-brief"): every page has one'
    problems = []
    ranks = []
    for el_id in doc.brief_headings:
        rank = brief_rank(el_id)
        if rank is None:
            problems.append(f'heading id "{el_id}" is not a Brief section (allowed: intent, context, change-*, '
                            "decisions, precedent, deploy, surface, verified, open-items)")
        else:
            ranks.append((BRIEF_ORDER.index(rank), el_id))
    present = {brief_rank(i) for i in doc.brief_headings}
    for need in BRIEF_REQUIRED:
        if need not in present:
            problems.append("missing required section " + ("change-<name>" if need == "change" else need))
    if [r for r, _ in ranks] != sorted(r for r, _ in ranks):
        problems.append("sections are out of order; the order is intent, context, change-*, decisions, precedent, deploy, surface, verified, open-items")
    by_id = {sid: words for sid, words in doc.brief_sections}
    if "verified" in by_id and len(by_id["verified"]) < 5:
        problems.append('the "verified" section needs text after its heading: what was and was not verified')
    if "open-items" in by_id:
        text = " ".join(by_id["open-items"])
        if not ("No open items recorded" in text or ("Before production" in text and "Backlog" in text)):
            problems.append('"open-items" needs the lists "Before production" and "Backlog", or the line "No open items recorded"')
    return "; ".join(problems)


def strip_raw_diff(source):
    """Remove the embedded diff, whatever the order of the data keys. The diff is the repo's own text."""
    return RAW_DIFF.sub('"rawDiff": ""', source)


def strip_data(source):
    """Remove the inlined data object (const QX = {...};): it is the repo's own text and the agent's data, not page code."""
    at = source.find("const QX = ")
    if at < 0:
        return source
    try:
        _, end = json.JSONDecoder().raw_decode(source, at + len("const QX = "))
    except ValueError:
        return source
    return source[:at] + "const QX = null" + source[end:]


def run_source(source):
    doc = Doc()
    doc.feed(source)
    results = []

    def check(name, ok, detail=""):
        results.append(("PASS" if ok else "FAIL", name, "" if ok else detail))

    code = strip_data(source)
    check("document-shape", doc.saw_html, "no <html> element -- not a standalone page")
    check("title-present", bool(doc.title.strip()), "missing or empty <title>")

    # External libraries: allowed, but pinned and from a known CDN.
    bad_urls = []
    for url in REMOTE_URL.findall(code):
        h = host_of(url)
        if h not in KNOWN_HOSTS:
            bad_urls.append(f"{url} (unknown host {h})")
        elif UNPINNED.search(url) or not SEMVER.search(url):
            bad_urls.append(f"{url} (not pinned to an exact version)")
    check("remote-assets-pinned", not bad_urls, "; ".join(bad_urls[:4]))

    check(
        "no-module-scripts",
        not MODULE_SCRIPT.search(code),
        '<script type="module"> is blocked on a file:// origin -- use the UMD build',
    )
    check(
        "no-runtime-fetch",
        not RUNTIME_FETCH.search(code),
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
    seen, dupes = set(), set()
    for el_id in doc.id_list:
        (dupes if el_id in seen else seen).add(el_id)
    check(
        "anchors-resolve",
        not dangling and not dupes,
        "; ".join(([f"href targets with no matching id: {', '.join(dangling[:8])}"] if dangling else [])
                  + ([f"duplicate ids (a url(#id) may resolve to the wrong copy): {', '.join(sorted(dupes)[:6])}"] if dupes else [])),
    )
    active = (["a javascript: URL in an href or src"] if JS_URL.search(code) else []) \
        + (["a remote URL in an <image>, <use>, <iframe>, <object> or <embed>"] if REMOTE_RESOURCE.search(code) else [])
    check("no-active-links", not active, "; ".join(active) + ". Remove it: the page must not run script or fetch from a diagram")

    # Map views and sub-tabs: each control has a panel and each panel a control.
    tabs, subs = set(doc.tab_views), set(doc.sub_tabs)
    detail = []
    if tabs - doc.panel_views:
        detail.append("map tabs with no panel: " + ", ".join(sorted(tabs - doc.panel_views)))
    if doc.panel_views - tabs:
        detail.append("map panels with no tab: " + ", ".join(sorted(doc.panel_views - tabs)))
    if subs - doc.sub_panels:
        detail.append("sub-tabs with no panel: " + ", ".join(sorted(subs - doc.sub_panels)))
    if doc.sub_panels - subs:
        detail.append("sub-panels with no tab: " + ", ".join(sorted(doc.sub_panels - subs)))
    check("tabs-wired", not detail, "; ".join(detail))

    # Top-level parts: controls and panels match one-to-one; fails if no panels found.
    controls = set(doc.part_controls)
    panels = doc.part_panels
    pdetail = []
    if not panels:
        pdetail.append("no part panels found (expected id=\"part-<key>\")")
    if controls - panels:
        pdetail.append("part controls with no panel: " + ", ".join(sorted(controls - panels)))
    if panels - controls:
        pdetail.append("part panels with no control: " + ", ".join(sorted(panels - controls)))
    check("parts-wired", not pdetail, "; ".join(pdetail))

    problem = check_brief(doc)
    check("brief-sections", not problem, problem)

    # The rule covers what the agent writes. The diff is the repo's own text, shown as it is.
    found = EMOJI.findall(strip_raw_diff(source))
    check("no-emoji", not found, "emoji present: " + " ".join(sorted(set(found))[:8]))

    return results


def run(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return run_source(fh.read())


# ---------------------------------------------------------------------------------------------
# Self-test: inline fixtures, one pass and at least one fail case per check.

GOOD_BRIEF = (
    '<h2 id="intent">Intent</h2><p>Why the change exists.</p>'
    '<h2 id="context">Context</h2><p>What it sits on.</p>'
    '<h2 id="change-api">API change</h2><p>The change.</p>'
    '<h2 id="verified">Verified</h2><p>Unit tests ran locally. Lab run not recorded.</p>'
    '<h2 id="open-items">Open items</h2><h3>Before production</h3><ul><li>None</li></ul><h3>Backlog</h3><ul><li>None</li></ul>'
)


def fixture(parts=("brief",), brief=GOOD_BRIEF, head_extra="", body_extra="", data='const QX = {"rawDiff": "", "excluded": []};', title="T"):
    """A minimal page in the shape the template emits."""
    labels = {"brief": "Brief", "walkthrough": "Walkthrough", "maps": "Maps", "summary": "Change summary", "diff": "Diff review"}
    bar = "".join(f'<button class="part-btn" data-part="{p}">{labels[p]}</button>' for p in parts)
    panels = ""
    for p in parts:
        inner = brief if p == "brief" else f"<p>{p}</p>"
        panels += f'<div id="part-{p}" class="part-panel"><div class="page">{inner}</div></div>\n'
    return (f"<!DOCTYPE html><html><head><title>{title}</title>{head_extra}<style>pre {{ white-space: pre-wrap; }}</style></head>"
            f"<body><div class=\"part-bar\">{bar}</div>\n{panels}{body_extra}<script>{data}</script></body></html>")


def selftest():
    fails, counts = [], {"cases": 0}
    em = "\U0001F600"
    mermaid = '<script src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"></script>'

    def verdict(source):
        return {name: status for status, name, _ in run_source(source)}

    def expect(name, source, check_name, want):
        counts["cases"] += 1
        got = verdict(source).get(check_name)
        if got != want:
            fails.append(f"{name}: {check_name} was {got}, wanted {want}")

    def ok_all(name, source):
        counts["cases"] += 1
        bad = [k for k, v in verdict(source).items() if v != "PASS"]
        if bad:
            fails.append(f"{name}: expected a clean page, failed {bad}")

    # Whole pages
    ok_all("brief-only page", fixture())
    ok_all("brief and diff page", fixture(("brief", "diff")))
    all_parts = fixture(("brief", "walkthrough", "maps", "summary", "diff"), head_extra=mermaid,
                        body_extra='<div id="sub-wt-a"></div><button data-sub="wt-a"></button>'
                                   '<button data-view="system"></button><div id="view-system"></div>')
    ok_all("all-parts page", all_parts)
    # document-shape, title-present
    expect("no html", "<p>hi</p>", "document-shape", "FAIL")
    expect("empty title", fixture(title=""), "title-present", "FAIL")
    expect("title", fixture(), "title-present", "PASS")
    # remote-assets-pinned
    expect("pinned", fixture(head_extra=mermaid), "remote-assets-pinned", "PASS")
    expect("unpinned", fixture(head_extra='<script src="https://cdn.jsdelivr.net/npm/mermaid@latest/dist/m.js"></script>'), "remote-assets-pinned", "FAIL")
    expect("unknown host", fixture(head_extra='<script src="https://evil.example/x@1.2.3/a.js"></script>'), "remote-assets-pinned", "FAIL")
    expect("data url font is local", fixture(head_extra="<style>@font-face{src:url(\"data:font/woff2;base64,AAAA\")}</style>"), "remote-assets-pinned", "PASS")
    # no-module-scripts, no-runtime-fetch
    expect("module script", fixture(head_extra='<script type="module">1</script>'), "no-module-scripts", "FAIL")
    expect("fetch call", fixture(data="fetch('x')"), "no-runtime-fetch", "FAIL")
    # code-whitespace
    expect("code outside pre", fixture(body_extra="<code>x</code>"), "code-whitespace", "FAIL")
    expect("code in pre", fixture(body_extra="<pre><code>x</code></pre>"), "code-whitespace", "PASS")
    expect("code with safe rule", fixture(head_extra="<style>code{white-space:pre-wrap}</style>", body_extra="<code>x</code>"), "code-whitespace", "PASS")
    # anchors-resolve
    expect("anchor ok", fixture(body_extra='<a href="#part-brief">x</a>'), "anchors-resolve", "PASS")
    expect("anchor dangling", fixture(body_extra='<a href="#nowhere">x</a>'), "anchors-resolve", "FAIL")
    expect("bare hash is ignored", fixture(body_extra='<a href="#">x</a>'), "anchors-resolve", "PASS")
    # anchors-resolve: duplicate ids
    expect("duplicate ids", fixture(body_extra='<svg><g id="x"></g><g id="x"></g></svg>'), "anchors-resolve", "FAIL")
    expect("distinct ids", fixture(body_extra='<svg><g id="x"></g><g id="y"></g></svg>'), "anchors-resolve", "PASS")
    # no-active-links
    expect("javascript href", fixture(body_extra='<a href="javascript:alert(1)">x</a>'), "no-active-links", "FAIL")
    expect("javascript xlink href", fixture(body_extra='<svg><a xlink:href="JavaScript:alert(1)"><g></g></a></svg>'), "no-active-links", "FAIL")
    expect("remote image href", fixture(body_extra='<svg><image href="https://evil.example/t.png"/></svg>'), "no-active-links", "FAIL")
    expect("remote use href", fixture(body_extra='<svg><use xlink:href="//evil.example/s.svg#a"/></svg>'), "no-active-links", "FAIL")
    expect("remote iframe src", fixture(body_extra='<iframe src="https://evil.example/"></iframe>'), "no-active-links", "FAIL")
    expect("local use href", fixture(body_extra='<svg><use href="#a"/></svg>'), "no-active-links", "PASS")
    expect("plain https link", fixture(body_extra='<a href="https://example.invalid/x">x</a>'), "no-active-links", "PASS")
    # fetch( and url(https://) inside the diff are the repo's own text
    in_code = 'const QX = {"rawDiff": "+ fetch(x) and url(https://x.example/y.png) and javascript:void(0)\\n", "excluded": []};'
    expect("fetch in the diff passes", fixture(data=in_code), "no-runtime-fetch", "PASS")
    expect("remote url in the diff passes", fixture(data=in_code), "remote-assets-pinned", "PASS")
    expect("fetch outside the data still fails", fixture(data=in_code + " fetch('x')"), "no-runtime-fetch", "FAIL")
    # tabs-wired
    expect("tab without panel", fixture(body_extra='<button data-view="a"></button>'), "tabs-wired", "FAIL")
    expect("panel without tab", fixture(body_extra='<div id="view-a"></div>'), "tabs-wired", "FAIL")
    expect("sub-tab without panel", fixture(body_extra='<button data-sub="a"></button>'), "tabs-wired", "FAIL")
    expect("sub-panel without tab", fixture(body_extra='<div id="sub-a"></div>'), "tabs-wired", "FAIL")
    expect("tabs matched", fixture(body_extra='<button data-view="a"></button><div id="view-a"></div><button data-sub="s"></button><div id="sub-s"></div>'), "tabs-wired", "PASS")
    # parts-wired
    expect("control without panel", fixture(body_extra='<button class="part-btn" data-part="maps"></button>'), "parts-wired", "FAIL")
    expect("panel without control", fixture(body_extra='<div id="part-maps"></div>'), "parts-wired", "FAIL")
    expect("no panels", "<html><head><title>t</title></head><body></body></html>", "parts-wired", "FAIL")
    # brief-sections
    expect("brief good", fixture(), "brief-sections", "PASS")
    expect("no brief panel", fixture(("diff",)), "brief-sections", "FAIL")
    expect("missing intent", fixture(brief=GOOD_BRIEF.replace('id="intent"', 'id="x-intent"')), "brief-sections", "FAIL")
    expect("missing context", fixture(brief=GOOD_BRIEF.replace('id="context"', 'id="why"')), "brief-sections", "FAIL")
    expect("no change section", fixture(brief=GOOD_BRIEF.replace('id="change-api"', 'id="api"')), "brief-sections", "FAIL")
    expect("missing open-items", fixture(brief=GOOD_BRIEF.replace('id="open-items"', 'id="todo"')), "brief-sections", "FAIL")
    expect("missing verified", fixture(brief=GOOD_BRIEF.replace('id="verified"', 'id="checked"')), "brief-sections", "FAIL")
    short = GOOD_BRIEF.replace("Unit tests ran locally. Lab run not recorded.", "Tests ran.")
    expect("verified too short", fixture(brief=short), "brief-sections", "FAIL")
    expect("out of order", fixture(brief=GOOD_BRIEF.replace('id="intent"', 'id="XX"').replace('id="context"', 'id="intent"').replace('id="XX"', 'id="context"')), "brief-sections", "FAIL")
    expect("unknown id", fixture(brief=GOOD_BRIEF.replace("<h2 id=\"verified\">", '<h2 id="risks">Risks</h2><p>x</p><h2 id="verified">')), "brief-sections", "FAIL")
    with_optional = GOOD_BRIEF.replace('<h2 id="verified">', '<h2 id="decisions">D</h2><p>d</p><h2 id="precedent">P</h2><p>p</p><h2 id="deploy">Dep</h2><p>x</p><h2 id="surface">S</h2><p>s</p><h2 id="verified">')
    expect("all optional sections in order", fixture(brief=with_optional), "brief-sections", "PASS")
    expect("optional after verified", fixture(brief=GOOD_BRIEF.replace('<h2 id="open-items">', '<h2 id="decisions">D</h2><p>d</p><h2 id="open-items">')), "brief-sections", "FAIL")
    two = GOOD_BRIEF.replace('<h2 id="verified">', '<h2 id="change-ui">UI</h2><p>u</p><h2 id="verified">')
    expect("two change sections", fixture(brief=two), "brief-sections", "PASS")
    expect("open-items none line", fixture(brief=GOOD_BRIEF.split('<h2 id="open-items">')[0] + '<h2 id="open-items">Open items</h2><p>No open items recorded</p>'), "brief-sections", "PASS")
    expect("open-items without lists", fixture(brief=GOOD_BRIEF.split('<h2 id="open-items">')[0] + '<h2 id="open-items">Open items</h2><p>Some things remain.</p>'), "brief-sections", "FAIL")
    expect("svg ids are not headings", fixture(brief=GOOD_BRIEF.replace("<p>The change.</p>", '<svg><g id="zz"></g></svg><p>The change.</p>')), "brief-sections", "PASS")
    expect("brief nested divs", fixture(brief="<div><div>" + GOOD_BRIEF + "</div></div>"), "brief-sections", "PASS")
    expect("ids outside brief are ignored", fixture(("brief", "walkthrough"), body_extra='<h2 id="whatever">x</h2>'), "brief-sections", "PASS")
    # no-emoji, with the diff excluded whatever the key order
    expect("emoji in text", fixture(brief=GOOD_BRIEF + f"<p>{em}</p>"), "no-emoji", "FAIL")
    in_diff = 'const QX = {"rawDiff": "+ ' + em + ' in the repo\\n", "excluded": []};'
    expect("emoji only in the diff, rawDiff first", fixture(data=in_diff), "no-emoji", "PASS")
    in_diff2 = 'const QX = {"excluded": [], "base": "a", "rawDiff": "+ ' + em + ' \\" tricky \\\\ end", "head": "b"};'
    expect("emoji only in the diff, rawDiff in the middle", fixture(data=in_diff2), "no-emoji", "PASS")
    expect("emoji outside the diff, rawDiff last", fixture(brief=GOOD_BRIEF + f"<p>{em}</p>", data='const QX = {"a": 1, "rawDiff": "x"};'), "no-emoji", "FAIL")

    for line in fails:
        print("FAIL\t" + line)
    print(f"selftest: {counts['cases']} cases, {len(fails)} failed")
    return 1 if fails else 0


def main():
    # -I ignores PYTHONIOENCODING, and a piped Windows console cannot print every character.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", nargs="?", help="path to the generated explanation HTML file")
    ap.add_argument("--selftest", action="store_true", help="run the built-in fixtures and exit")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.path:
        ap.error("a path is required unless --selftest is given")

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
