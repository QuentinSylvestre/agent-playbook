#!/usr/bin/env python3
"""Build a /qexplain artifact from the shared template and the agent's content files.

The agent writes the parts that need judgement (brief, walkthrough, maps, diagram sources,
per-file rationales and roles). This script does the mechanical rest: captures the diff as
UTF-8, renders D2 diagrams, works out the provenance from git, builds the change summary,
inlines every piece of data safely, wires the tabs, drops the parts that were not selected,
then runs the validator on the result.

Standard library only; nothing to install. <python> is the interpreter of <config-repo>/.venv-agent-playbook, run with -I (shared/AGENTS.md, Config Repo Locations).

Usage:
    <python> build-explanation.py --out <path.html> --title <text> \
        (--diff-args "<git diff arguments>" [--repo <dir>] | --diff-file <unified.diff> --base <text> --head <text> \
         | --target "<label>=<repo>::<git diff arguments>" ...) \
        --brief <brief.html> --rationales <rationales.json> \
        [--parts brief,walkthrough,maps,summary,diff] [--walkthrough <walkthrough.html>] [--maps <maps.json>] \
        [--roles <roles.json>] [--diagrams <dir>] [--ticket <text>]... [--link <label>=<url>]... \
        [--base <text>] [--head <text>] [--exclude <glob>]... \
        [--allow-credential <path>:<side>:<line>]... [--mask-credential ...]... [--user-confirmed-credential ...]...
    <python> build-explanation.py --selftest

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
import datetime
import html
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I leaves the script's folder off the path
import qexplain_diff as qd  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "assets", "template.html")
VALIDATOR = os.path.join(HERE, "validate-explanation.py")
VIEW_ORDER = ["system", "dataflow", "deps", "actions", "sequence"]
PART_ORDER = ["brief", "walkthrough", "maps", "summary", "diff"]
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js"
D2_TIMEOUT = 60
PLACEHOLDER = re.compile(r"""<div\s+data-diagram=["']([A-Za-z0-9._-]+)["']\s*>\s*</div>""")
SECTION = re.compile(r"""<section\s+data-subsystem=["']([^"']+)["']\s*>(.*?)</section>""", re.S)
SEQ_D2 = re.compile(r"^\s*shape\s*:\s*sequence_diagram", re.M)
SEQ_MMD = re.compile(r"\A(?:\s*(?:%%[^\n]*|---.*?---)\s*)*sequenceDiagram\b", re.S)
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
                    fail(f"cannot run d2 ({exc})")
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
                fail(f"--diagrams {folder} is not a folder")
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
            if kind == "d2":
                for why in qd.d2_refusals(text):
                    fail(f"diagram {name}.d2 refused: {why}")
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
            rec = {"kind": "d2", "variants": variants, "ids": ids, "tokens": sorted(ids.values()), "seq": False}
        else:
            mid = f"m{self.counter}"
            self.mermaid[mid] = text
            rec = {"kind": "mermaid", "html": f'<div class="mermaid mmd" data-mid="{mid}" title="Click to enlarge"></div>',
                   "ids": {}, "tokens": [], "seq": bool(SEQ_MMD.search(text))}
        self.rendered[name] = rec
        return rec

    def unit(self, name):
        """Return (html, wrapper id) for one use of a diagram. Each use gets its own wrapper id."""
        rec = self.render(name)
        self.instances += 1
        dg = f"dg-{self.instances}"
        if rec["kind"] == "d2":
            inner = "".join(f'<div class="dgv v-{theme} v-{style}" title="Click to enlarge">{uniquify_ids(rec["variants"][(theme, style)], f"u{self.instances}-{theme[0]}{style[0]}-")}</div>'
                            for theme in ("light", "dark") for style in ("sketch", "classic"))
            return f'<div class="dg" id="{dg}">{inner}</div>', dg
        return f'<div class="dg" id="{dg}">{rec["html"]}</div>', dg


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
            fail("each map view must be an object")
        key = v.get("key")
        if key not in VIEW_ORDER:
            fail(f"map view key {key!r} is not one of {', '.join(VIEW_ORDER)}")
        sub = v.get("subsystem") or None
        if (key, sub) in seen:
            fail(f"map view {key!r} appears twice" + (f" in subsystem {sub!r}" if sub else ""))
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
    ap.add_argument("--parts", default="brief,diff", help="comma list of brief, walkthrough, maps, summary, diff (brief is always emitted)")
    ap.add_argument("--brief")
    ap.add_argument("--walkthrough")
    ap.add_argument("--maps")
    ap.add_argument("--rationales")
    ap.add_argument("--roles")
    ap.add_argument("--diagrams")
    ap.add_argument("--ticket", action="append", default=[], help="a ticket reference to show in the provenance strip")
    ap.add_argument("--link", action="append", default=[], help="label=https://url to show in the provenance strip")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
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
            fail(f"the {part} part is selected but --{part} was not given")
        if part not in selected and flag:
            print(f"WARN\t--{part} was given but the {part} part is not in --parts; it is ignored")
    tickets, links = [t.strip() for t in args.ticket if t.strip()], parse_links(args.link)

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
    roles = read_json(args.roles) if args.roles else {}
    if not isinstance(roles, dict):
        fail("roles.json must map file paths to sentences")
    brief = read(args.brief)
    walkthrough = read(args.walkthrough) if args.walkthrough and "walkthrough" in selected else ""
    maps_text = read(args.maps) if args.maps and "maps" in selected else ""
    maps = read_json(args.maps) if maps_text else None

    # Diagrams: names, refusals, the d2 lookup, then rendering.
    diagrams = Diagrams(args.diagrams)
    for m in PLACEHOLDER.finditer(brief):
        diagrams.need(m.group(1), "brief.html")
    for m in PLACEHOLDER.finditer(walkthrough):
        diagrams.need(m.group(1), "walkthrough.html")
    views = check_views(maps, diagrams) if maps is not None else []
    for name in diagrams.sources:
        if name not in diagrams.used:
            print(f"WARN\tdiagram {name} is not used by the brief, the walkthrough or a map view")
    diagrams.check_sources()

    # Provenance
    if args.diff_file:
        repos, plans = [{"label": "diff file", "branch": "not recorded", "base": args.base, "head": args.head, "commits": "not recorded"}], []
        base_text, head_text = args.base, args.head
    else:
        targets = [qd.parse_target(t) for t in args.target] if args.target else [(None, args.repo, args.diff_args)]
        repos, plans = [], []
        for label, repo, diff_args in targets:
            repos.append(repo_provenance(label, repo, diff_args))
            plans += [s for s in qd.plans_in_range(repo, diff_args)[0] if s not in plans]
        base_text = "; ".join((f"{r['label']}: " if len(repos) > 1 else "") + r["base"] for r in repos)
        head_text = "; ".join((f"{r['label']}: " if len(repos) > 1 else "") + r["head"] for r in repos)
    prov = provenance_html(repos, plans, diagrams.d2_version or "not used", tickets, links, left_out, "diff" not in selected)

    # Credential scan: the diff, then everything the agent wrote.
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
               ("roles.json", read(args.roles) if args.roles else ""), ("title and refs", f"{args.title}\n{args.base}\n{args.head}"),
               ("tickets and links", "\n".join(tickets + [f"{a} {b}" for a, b in links])),
               ("provenance", "\n".join(f"{r['label']} {r['branch']} {r['base']} {r['head']}" for r in repos))]
    written += diagrams.source_texts(diagrams.used)
    for name, text in written:
        hits += qd.scan_content_file(name, text)
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
    brief_out = fill_placeholders(brief, diagrams, "brief.html")
    walk_out = walkthrough_html(fill_placeholders(walkthrough, diagrams, "walkthrough.html")) if "walkthrough" in selected else ""
    maps_out, view_data = ("", [])
    if "maps" in selected:
        maps_out, view_data = maps_html(views, diagrams)
    labelled = bool(args.target)
    summary_out = summary_html(kept, rationales, roles, labelled, "diff" in selected) if "summary" in selected else ""

    mermaid_used = bool(diagrams.mermaid)
    page = strip_parts(read(TEMPLATE), selected)
    slots = {
        "{{TITLE}}": html.escape(args.title),
        "{{BASE_REF}}": html.escape(base_text),
        "{{HEAD_REF}}": html.escape(head_text),
        "<!--@PROVENANCE-->": prov,
        "<!--@MERMAID-->": f'<script src="{MERMAID_URL}"></script>' if mermaid_used else "",
        "<!--@BRIEF-->": brief_out,
        "<!--@WALKTHROUGH-->": walk_out,
        "<!--@MAPS-->": maps_out,
        "<!--@SUMMARY-->": summary_out,
        "/*@DATA*/": "const QX = " + script_json({
            "base": base_text, "head": head_text, "views": view_data, "mermaid": diagrams.mermaid,
            "hasD2": any(r["kind"] == "d2" for r in diagrams.rendered.values()),
            "rationales": rationales, "rawDiff": raw if "diff" in selected else "", "excluded": left_out,
            "paths": [path for path, _ in kept],
        }) + ";",
    }
    for marker in ("{{TITLE}}", "<!--@PROVENANCE-->", "<!--@MERMAID-->", "<!--@BRIEF-->", "/*@DATA*/"):
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

    sys.stdout.flush()
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
        rc, log, page = run("brief-diff", std)
        case("brief and diff page", rc == 0 and 'id="part-diff"' in page and "diff --git" in page, log[-300:])
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
                {"key": "dataflow", "label": "Flow", "diagram": "arch", "subsystem": "Edge site"}]}
            w("maps-d2.json", json.dumps(d2maps))
            args = ["--brief", os.path.join(content, "brief-d2.html"), "--rationales", os.path.join(content, "rationales.json"), "--roles", os.path.join(content, "roles.json"),
                    "--parts", "brief,walkthrough,maps,summary,diff", "--walkthrough", os.path.join(content, "walkthrough.html"), "--maps", os.path.join(content, "maps-d2.json"), "--diagrams", good]
            rc, log, page = run("all-d2", args)
            case("all parts with D2 architecture and sequence diagrams", rc == 0 and "D2: v" in page, log[-500:], d2=True)
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
