"""Render an HTML visualization fragment as a standalone sandboxed page.

Usage
-----
    <python> render.py <fragment-path> [<output-path>] [--serve] [--no-layout-check]
    <python> render.py --scaffold <fragment-path> [--title "Chart title"]
    <python> render.py <fragment-path> --export-png <dir>
    <python> render.py --selftest

    fragment-path   Path to the HTML fragment to render.
    output-path     Optional output file (default: <fragment-stem>.rendered.html
                    in the same directory as the fragment).
    --serve         Serve the rendered page on a random local port and open it
                    in the browser. Exits on Ctrl-C.
    --no-layout-check
                    Skip the layout check. By default, before writing or
                    serving, every <figure> SVG is measured in headless Chrome
                    or Edge, and the render fails (exit 3) when a text label
                    overlaps another, crosses the edge of a rect or circle, or
                    leaves the viewBox. Skipped with a "layout check skipped"
                    notice when no browser is found or the browser cannot run.
    --scaffold      Write a small ready-to-render skeleton fragment to
                    fragment-path instead of rendering one. The skeleton has
                    marked places (STEP:DATA, STEP:RENDER, STEP:CONTROLS) for
                    the visualization to be filled in, a piece at a time.
                    Refuses to overwrite an existing file.
    --export-png    Write each <figure> that holds a static <svg viewBox> as a
                    2x light-theme PNG in dir, for pasting into documents.
                    Named from the figure id, else fig-N. Needs Chrome or Edge;
                    set QVISUALIZE_BROWSER to point at another executable.
    --selftest      Run the built-in cases; exit 0 when none failed. A case
                    printed as SKIP (no browser) is not a pass.

Exit codes
----------
    0   Success.
    1   General error: file not found, I/O error, or write failure; for
        --export-png also no browser found, or the browser failed.
    2   Invalid fragment: path is a symbolic link, fragment exceeds 1 MB,
        or fragment is a complete HTML document (has <!doctype / <html / etc.);
        for --export-png also a fragment with no exportable figure.
        Note: a path that does not exist exits 1, not 2.
    3   Layout check failed: the colliding labels are listed on stderr and no
        output is written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import webbrowser
import zlib
from html import escape, unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKILL_DIRECTORY = Path(__file__).resolve().parents[1]
_FRAGMENT_PLACEHOLDER = "<!-- KIRO_FRAGMENT_PLACEHOLDER -->"
_MAX_FRAGMENT_BYTES = 1_000_000
_DOCUMENT_MARKUP = re.compile(
    r"\A\s*(?:<!doctype\s|<\s*html(?:\s|>))", re.IGNORECASE
)

# CDN origins permitted inside the inner sandboxed iframe.
_CDN_SOURCES = " ".join(
    (
        "blob:",
        "data:",
        "https://cdnjs.cloudflare.com",
        "https://cdn.jsdelivr.net",
        "https://esm.sh",
        "https://fonts.bunny.net",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
        "https://unpkg.com",
    )
)

# Strict CSP for the inner sandboxed iframe (no same-origin, no networking
# beyond the CDN allowlist).
_FRAME_CSP = "; ".join(
    (
        "default-src 'none'",
        f"script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' {_CDN_SOURCES}",
        f"style-src 'unsafe-inline' {_CDN_SOURCES}",
        f"img-src {_CDN_SOURCES}",
        f"font-src {_CDN_SOURCES}",
        f"media-src blob: data:",
        "worker-src blob:",
        "connect-src blob: data:",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    )
)

# The outer shell must allow a srcdoc child frame.
_SHELL_CSP = "; ".join(
    (
        "default-src 'none'",
        f"script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' {_CDN_SOURCES}",
        f"style-src 'unsafe-inline' {_CDN_SOURCES}",
        f"img-src {_CDN_SOURCES}",
        f"font-src {_CDN_SOURCES}",
        f"media-src blob: data:",
        "worker-src blob:",
        "connect-src blob: data:",
        "frame-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    )
)
assert "frame-src 'self'" in _SHELL_CSP

# Permissive CSP used when serving via --serve (matches the /api/viz/ route
# in PowerAtlas so standalone and PA output are identical).
_SERVE_CSP = (
    "default-src 'self' 'unsafe-inline' blob: data: "
    "https://unpkg.com https://cdn.jsdelivr.net https://esm.sh "
    "https://cdnjs.cloudflare.com https://fonts.googleapis.com "
    "https://fonts.gstatic.com https://fonts.bunny.net"
)


# ---------------------------------------------------------------------------
# Fragment validation
# ---------------------------------------------------------------------------


def _read_fragment(source: Path) -> str:
    """Read and validate the fragment file.

    Exits with code 2 for: symlink, size > 1 MB, complete HTML document.
    Exits with code 1 for: not found, not a regular file, I/O or decode error.
    """
    # Check symlink FIRST — is_file() follows symlinks and would return True
    # for a symlink pointing to a file, masking the symlink check.
    if source.is_symlink():
        sys.stderr.write(f"error: source is a symbolic link: {source}\n")
        sys.exit(2)

    try:
        if not source.is_file():
            sys.stderr.write(
                f"error: not found or not a regular file: {source}\n"
            )
            sys.exit(1)
        size = source.stat().st_size
    except OSError as exc:
        sys.stderr.write(f"error: {exc}\n")
        sys.exit(1)

    if size > _MAX_FRAGMENT_BYTES:
        sys.stderr.write(
            f"error: fragment exceeds the 1 MB size limit ({size} bytes)\n"
        )
        sys.exit(2)

    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        sys.exit(1)

    if _DOCUMENT_MARKUP.search(text):
        sys.stderr.write(
            "error: source must be an HTML fragment, not a complete document\n"
        )
        sys.exit(2)

    return text


_SCAFFOLD = """<div id="{root}">
<style>
#{root}{{color:var(--foreground);width:100%;box-sizing:border-box}}
#{root} .{root}-title{{font-weight:500;margin:0 0 8px}}
#{root} .{root}-stage{{width:100%;min-height:240px}}
#{root} .{root}-detail{{min-height:1.4em;color:var(--muted-foreground)}}
/* STEP:STYLES */
</style>
<h2 class="{root}-title">{title}</h2>
<div class="viz-controls" id="{root}-controls"></div>
<div class="{root}-stage" id="{root}-stage" role="img" aria-label="{title}"></div>
<p class="{root}-detail text-small" id="{root}-detail" aria-live="polite">Building this visualization&hellip;</p>
<script>
(function () {{
  var root = document.getElementById("{root}");
  var stage = document.getElementById("{root}-stage");
  var detail = document.getElementById("{root}-detail");
  var controls = document.getElementById("{root}-controls");
  /* STEP:DATA */
  /* STEP:RENDER */
  /* STEP:CONTROLS */
}})();
</script>
</div>
"""


def _scaffold(target: Path, title: str | None) -> int:
    """Write the skeleton fragment to `target`; never overwrite a file."""
    if target.exists() or target.is_symlink():
        sys.stderr.write(
            f"error: refusing to overwrite: {target}. Use a new file name, or "
            "delete it first if it is yours.\n")
        return 1
    stem = re.sub(r"[^a-z0-9]+", "-", target.stem.lower()).strip("-") or "chart"
    root = ("viz-" + stem) if not stem[0].isalpha() else stem
    heading = escape(title or _default_title(target))
    try:
        target.write_text(_SCAFFOLD.format(root=root, title=heading),
                          encoding="utf-8", newline="\n")
    except OSError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(str(target) + "\n")
    return 0


def _default_title(source: Path) -> str:
    """Derive a human-readable title from the fragment file name."""
    words = source.stem.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) or "Visualization"


def _calendar_script(fragment: str) -> str:
    """Return a <script> tag bundling the viz-calendar element if used."""
    if re.search(r"\bviz-calendar\b", fragment, re.IGNORECASE) is None:
        return ""
    cal_path = _SKILL_DIRECTORY / "assets" / "calendar.js"
    try:
        source = cal_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"error: missing or unreadable skill asset: "
            f"{Path(exc.filename).name if hasattr(exc, 'filename') else str(exc)}\n"
        )
        sys.exit(1)
    return "<script>" + source.replace("</script", "<\\/script") + "</script>"


# ---------------------------------------------------------------------------
# Document rendering
# ---------------------------------------------------------------------------


def _render_document(fragment: str, title: str) -> str:
    """Wrap the fragment in a double-iframe sandboxed standalone page."""
    assets = _SKILL_DIRECTORY / "assets"
    _css_path = assets / "visualize.css"
    try:
        stylesheet = _css_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"error: missing or unreadable skill asset: "
            f"{Path(exc.filename).name if hasattr(exc, 'filename') else str(exc)}\n"
        )
        sys.exit(1)
    _kit_path = assets / "visualize.html"
    try:
        inner_kit = _kit_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"error: missing or unreadable skill asset: "
            f"{Path(exc.filename).name if hasattr(exc, 'filename') else str(exc)}\n"
        )
        sys.exit(1)
    _bridge_path = assets / "standalone-host-bridge.js"
    try:
        host_bridge = _bridge_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"error: missing or unreadable skill asset: "
            f"{Path(exc.filename).name if hasattr(exc, 'filename') else str(exc)}\n"
        )
        sys.exit(1)
    host_bridge = host_bridge.replace("</script", r"<\/script")
    _shell_path = assets / "standalone-shell.js"
    try:
        shell = _shell_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"error: missing or unreadable skill asset: "
            f"{Path(exc.filename).name if hasattr(exc, 'filename') else str(exc)}\n"
        )
        sys.exit(1)
    shell = shell.replace("</script", r"<\/script")

    # Inject calendar element (if used) and the fragment into the template.
    inner_html = inner_kit.replace(
        _FRAGMENT_PLACEHOLDER, _calendar_script(fragment) + fragment
    )
    document_title = escape(title)

    # -----------------------------------------------------------------------
    # Inner iframe: sandboxed, contains the fragment + design system + bridge.
    # standalone-shell.js replaces `window.__vizWidgetState=/*_KIRO_WS_PLACEHOLDER_*/null;` with the
    # saved state from localStorage before setting frame.srcdoc.
    # -----------------------------------------------------------------------
    frame_html = f"""<!doctype html>
<html lang="en" data-visualize-standalone>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="{_FRAME_CSP}">
<title>{document_title}</title>
<style>{stylesheet}
html>body{{padding:0}}</style>
</head>
<body>
<script>window.__vizWidgetState=/*_KIRO_WS_PLACEHOLDER_*/null;</script>
<script>{host_bridge}</script>
{inner_html}
</body>
</html>
"""

    # -----------------------------------------------------------------------
    # Outer shell: relaxed CSP that allows the srcdoc child frame.
    # The inner HTML is stored in data-fragment-src; standalone-shell.js
    # reads it, injects widget state, and sets frame.srcdoc.
    # -----------------------------------------------------------------------
    return f"""<!doctype html>
<html lang="en" data-visualize-standalone>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="{_SHELL_CSP}">
<title>{document_title}</title>
<style>:root{{color-scheme:light dark;background:light-dark(rgb(255 255 255),rgb(24 24 24))}}html,body{{margin:0}}body{{box-sizing:border-box;padding:1rem;background:inherit}}iframe{{display:block;width:100%;height:calc(100vh - 2rem);margin:0 auto;border:0}}</style>
</head>
<body>
<iframe id="kiro-visualization" sandbox="allow-scripts" referrerpolicy="no-referrer" title="{document_title}" data-fragment-src="{escape(frame_html)}"></iframe>
<script>{shell}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# PNG export
# ---------------------------------------------------------------------------

_FIGURE = re.compile(r"<figure\b([^>]*)>(.*?)</figure\s*>", re.IGNORECASE | re.DOTALL)
_FIGURE_SVG = re.compile(
    r"<svg\b[^>]*\bviewBox\s*=\s*[\"']\s*-?[\d.]+[\s,]+-?[\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*[\"']"
    r"[^>]*>.*?</svg\s*>",
    re.IGNORECASE | re.DOTALL,
)
_STYLE_BLOCK = re.compile(
    r"<style\b[^>]*>.*?</style\s*>|<link\b[^>]*\brel\s*=\s*[\"']?stylesheet\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
_ROOT_TAG = re.compile(r"\s*<([a-zA-Z][\w-]*)\b[^>]*>")
_ID_ATTRIBUTE = re.compile(r"\bid\s*=\s*[\"']([^\"']+)[\"']")
_EXPORT_PAD = 16
_BROWSER_TIMEOUT = 120


def _figures(fragment: str) -> list[tuple[str, str, str, int, int]]:
    """Return (name, figure attributes, svg markup, width, height) per exportable figure."""
    found = []
    for match in _FIGURE.finditer(fragment):
        svg = _FIGURE_SVG.search(match.group(2))
        if svg is None:
            continue
        width, height = round(float(svg.group(1))), round(float(svg.group(2)))
        if width <= 0 or height <= 0:
            continue
        named = _ID_ATTRIBUTE.search(match.group(1))
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", named.group(1)).strip("-") if named else ""
        found.append((name or f"fig-{len(found) + 1}", match.group(1), svg.group(0), width, height))
    return found


def _find_browser() -> Path | None:
    """Locate Chrome or Edge; QVISUALIZE_BROWSER, when set, is the only candidate."""
    override = os.environ.get("QVISUALIZE_BROWSER")
    if override:
        return Path(override) if Path(override).is_file() else None
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser", "msedge", "microsoft-edge"):
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]
    for base in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(base)
        if root:
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
            candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return next((path for path in candidates if path.is_file()), None)


def _export_png(source: Path, out_dir: Path) -> int:
    """Write each exportable figure of the fragment as a 2x light-theme PNG."""
    fragment = _read_fragment(source)
    figures = _figures(fragment)
    if not figures:
        sys.stderr.write(
            "error: no exportable figure: --export-png needs <figure> elements "
            "holding a static <svg viewBox=\"0 0 W H\">\n")
        return 2
    browser = _find_browser()
    if browser is None:
        sys.stderr.write(
            "error: no Chrome or Edge found for --export-png; install one, or set "
            "QVISUALIZE_BROWSER to a Chromium-based browser executable\n")
        return 1
    try:
        stylesheet = (_SKILL_DIRECTORY / "assets" / "visualize.css").read_text(encoding="utf-8")
        out_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    # Re-wrap the svg in the fragment's root tag and its own figure, so styles
    # scoped under the root id (#root .x) still match. Light theme is forced
    # three ways: data-theme for fragments keyed on it, an !important
    # color-scheme for light-dark() tokens, and the browser's preferred scheme
    # for prefers-color-scheme media queries.
    styles = "".join(_STYLE_BLOCK.findall(fragment))
    root = _ROOT_TAG.match(fragment)
    root_open, root_close = (root.group(0).strip(), f"</{root.group(1)}>") if root else ("", "")
    with tempfile.TemporaryDirectory(prefix="qvisualize-export-") as work:
        work_dir = Path(work)
        for name, attributes, svg, width, height in figures:
            page = work_dir / f"{name}.html"
            page.write_text(
                f"<!doctype html><html lang=\"en\" data-theme=\"light\"><head><meta charset=\"utf-8\">"
                f"<style>{stylesheet}</style>{styles}"
                f"<style>:root{{color-scheme:light!important}}html,body{{margin:0;padding:0}}"
                f"body{{padding:{_EXPORT_PAD}px!important;background:var(--background)}}"
                f"figure{{margin:0!important;padding:0!important;border:0!important;"
                f"background:none!important;box-shadow:none!important}}"
                f"figure svg{{display:block;width:{width}px!important;height:{height}px!important;"
                f"max-width:none!important;min-width:0!important}}</style></head>"
                f"<body>{root_open}<figure{attributes}>{svg}</figure>{root_close}</body></html>",
                encoding="utf-8")
            png = out_dir / f"{name}.png"
            if png.exists():
                png.unlink()
            command = [
                str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--no-first-run", "--no-default-browser-check", "--blink-settings=preferredColorScheme=1",
                f"--user-data-dir={work_dir / 'profile'}",
                f"--screenshot={png}", f"--window-size={width + 2 * _EXPORT_PAD},{height + 2 * _EXPORT_PAD}",
                "--force-device-scale-factor=2", "--virtual-time-budget=6000", page.as_uri(),
            ]
            try:
                result = subprocess.run(command, capture_output=True, text=True,
                                        timeout=_BROWSER_TIMEOUT)
            except subprocess.TimeoutExpired:
                sys.stderr.write(f"error: {browser.name} timed out after {_BROWSER_TIMEOUT} s on {name}\n")
                return 1
            except OSError as exc:
                sys.stderr.write(f"error: could not start {browser}: {exc}\n")
                return 1
            if not png.is_file():
                tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
                sys.stderr.write(f"error: {browser.name} wrote no PNG for {name} "
                                 f"(exit {result.returncode})\n" + "\n".join(tail) + "\n")
                return 1
            sys.stdout.write(str(png) + "\n")
    return 0


# ---------------------------------------------------------------------------
# Layout check
# ---------------------------------------------------------------------------

# Runs in the headless browser once fonts are ready. For each figure SVG it
# reports a <text> that overlaps another <text>, crosses the edge of a drawn
# rect or circle (partly inside, partly out), or leaves the viewBox. Lines and
# paths are not checked. The result goes into a <pre> read back by --dump-dom.
_LAYOUT_SCRIPT = """
(() => {
  // A text box is the font's line box, taller than the glyphs, so the
  // vertical tolerance grows with the text: a quarter of its height.
  const SLACK = 2;
  const box = (el) => { const r = el.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom}; };
  const vslack = (a) => Math.max(SLACK, (a.b - a.t) / 4);
  const overlap = (a, b) => Math.min(a.r, b.r) - Math.max(a.l, b.l) > SLACK
    && Math.min(a.b, b.b) - Math.max(a.t, b.t) > Math.min(vslack(a), vslack(b));
  const inside = (a, b) => a.l >= b.l - SLACK && a.r <= b.r + SLACK && a.t >= b.t - vslack(a) && a.b <= b.b + vslack(a);
  const UNRENDERED = "defs, symbol, marker, clipPath, mask, pattern";
  const clear = (c) => c === "none" || c === "transparent" || /^rgba\\(.*,\\s*0\\)$/.test(c);
  const drawn = (el) => {
    if (el.closest(UNRENDERED)) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    let opacity = 1;
    for (let n = el; n instanceof Element; n = n.parentElement) opacity *= parseFloat(getComputedStyle(n).opacity);
    const s = getComputedStyle(el);
    const fill = !clear(s.fill) && parseFloat(s.fillOpacity) > 0;
    const stroke = !clear(s.stroke) && parseFloat(s.strokeOpacity) > 0 && parseFloat(s.strokeWidth) > 0;
    return opacity > 0 && s.visibility !== "hidden" && (fill || stroke);
  };
  const label = (el) => JSON.stringify((el.textContent || "").trim().slice(0, 40));
  const report = [];
  const measure = () => {
    for (const svg of document.querySelectorAll("figure[data-qv-name] svg[data-qv-svg]")) {
      const name = svg.closest("figure").dataset.qvName;
      const frame = box(svg);
      if (frame.r - frame.l <= 0 || frame.b - frame.t <= 0) continue;
      const texts = [...svg.querySelectorAll("text")].filter((t) => (t.textContent || "").trim() && drawn(t)).map((t) => [t, box(t)]);
      const shapes = [...svg.querySelectorAll("rect, circle")].filter(drawn).map((s) => [s, box(s)]).filter(([, b]) => b.r - b.l > 4 && b.b - b.t > 4);
      texts.forEach(([t, a], i) => {
        if (!inside(a, frame)) report.push(`${name}: text ${label(t)} runs outside the viewBox`);
        for (const [u, b] of texts.slice(i + 1)) if (overlap(a, b)) report.push(`${name}: text ${label(t)} overlaps text ${label(u)}`);
        // A probe badge (text wholly inside a circle) may sit on a node's edge by design.
        if (shapes.some(([s, b]) => s.tagName === "circle" && inside(a, b))) return;
        for (const [s, b] of shapes) if (overlap(a, b) && !inside(a, b)) report.push(`${name}: text ${label(t)} crosses the edge of a ${s.tagName}`);
      });
    }
    const pre = document.createElement("pre");
    pre.id = "qv-layout-report";
    pre.textContent = JSON.stringify([...new Set(report)]);
    document.body.append(pre);
  };
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(measure, measure);
})();
"""
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_LAYOUT_REPORT = re.compile(r"<pre id=\"qv-layout-report\">(.*?)</pre>", re.DOTALL)
_LAYOUT_EXIT = 3


def _layout_check(fragment: str) -> int:
    """Fail (exit 3) when a figure SVG has colliding or clipped text labels.

    Fragments without a figure SVG pass. With no usable browser the check is
    skipped with a notice on stderr, since there is nothing to measure with.
    """
    figures = _figures(fragment)
    if not figures:
        return 0
    # Report text can hold any label; under -I stderr would otherwise be the
    # console code page.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    browser = _find_browser()
    if browser is None:
        override = os.environ.get("QVISUALIZE_BROWSER")
        why = (f"QVISUALIZE_BROWSER is set to {override}, which is not a file" if override
               else "no Chrome or Edge found (set QVISUALIZE_BROWSER to enable it)")
        sys.stderr.write(f"notice: layout check skipped: {why}\n")
        return 0
    try:
        stylesheet = (_SKILL_DIRECTORY / "assets" / "visualize.css").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    # Measure the figures in place, inside the whole fragment, so styles keyed
    # on wrapper elements still apply. Scripts are stripped: only static SVG is
    # checked. Each exportable figure is tagged with the name _figures gives it.
    names = iter(name for name, *_ in figures)

    def tag(match: re.Match[str]) -> str:
        svg = _FIGURE_SVG.search(match.group(2))
        if svg is None or round(float(svg.group(1))) <= 0 or round(float(svg.group(2))) <= 0:
            return match.group(0)
        # Pin the SVG to its viewBox size so one user unit is one pixel and the
        # 2 px tolerance means the same thing in every figure.
        # A figure may hold several SVGs, such as a legend before the diagram:
        # mark and pin every one that has a viewBox, so each is measured.
        name = escape(next(names))
        body, pins, marked, last = match.group(2), [], [], 0
        for index, each in enumerate(_FIGURE_SVG.finditer(match.group(2))):
            width, height = round(float(each.group(1))), round(float(each.group(2)))
            if width <= 0 or height <= 0:
                continue
            marked.append(body[last:each.start()] + f"<svg data-qv-svg=\"{index}\"")
            last = each.start() + 4
            pins.append(f"figure[data-qv-name=\"{name}\"] svg[data-qv-svg=\"{index}\"]{{width:{width}px!important;"
                        f"height:{height}px!important;max-width:none!important;min-width:0!important}}")
        marked.append(body[last:])
        return (f"<style>{''.join(pins)}</style>"
                f"<figure{match.group(1)} data-qv-name=\"{name}\">{''.join(marked)}</figure>")

    static = _SCRIPT_BLOCK.sub("", _FIGURE.sub(tag, fragment))
    widest = max(width for _, _, _, width, _ in figures)
    with tempfile.TemporaryDirectory(prefix="qvisualize-layout-") as work:
        work_dir = Path(work)
        page = work_dir / "layout.html"
        page.write_text(
            f"<!doctype html><html lang=\"en\" data-theme=\"light\"><head><meta charset=\"utf-8\">"
            f"<style>{stylesheet}</style><style>html,body{{margin:0;padding:16px}}</style></head>"
            f"<body>{static}<script>{_LAYOUT_SCRIPT}</script></body></html>",
            encoding="utf-8")
        command = [
            str(browser), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={work_dir / 'profile'}",
            f"--window-size={max(widest + 32, 1280)},1000", "--virtual-time-budget=6000",
            "--dump-dom", page.as_uri(),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=_BROWSER_TIMEOUT)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"notice: layout check skipped: {browser.name} timed out after "
                             f"{_BROWSER_TIMEOUT} s\n")
            return 0
        except OSError as exc:
            sys.stderr.write(f"notice: layout check skipped: could not start {browser}: {exc}\n")
            return 0
    found = _LAYOUT_REPORT.search(result.stdout or "")
    if found is None:
        # A browser that cannot run headless (policy, broken install) must not
        # block every render; the skill then falls back to a screenshot check.
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        sys.stderr.write(f"notice: layout check skipped: {browser.name} returned no report "
                         f"(exit {result.returncode})\n" + "".join(f"  {line}\n" for line in tail))
        return 0
    problems = json.loads(unescape(found.group(1)))
    if not problems:
        return 0
    sys.stderr.write(f"error: layout check found {len(problems)} label problem(s); move the "
                     "labels or widen the boxes, then render again (or pass "
                     "--no-layout-check to skip the check deliberately):\n")
    sys.stderr.write("".join(f"  {problem}\n" for problem in problems))
    return _LAYOUT_EXIT


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

_SELFTEST_FRAGMENT = """<div id="map">
<style>#map .box{fill:var(--card);stroke:var(--border)}
:root:not([data-theme="light"]){color-scheme:dark}</style>
<figure id="recording path"><svg viewBox="0 0 200 100" role="img" aria-label="a"><rect class="box" x="10" y="10" width="80" height="40"/></svg><figcaption>One</figcaption></figure>
<figure><table><tr><td>not a diagram</td></tr></table></figure>
<figure class="diagram"><svg viewBox="0 0 120 60"><text x="4" y="20">b</text></svg></figure>
</div>
"""


# Two overlapping labels, a label straddling a box edge, a label leaving the
# viewBox, and a probe badge on a box corner (allowed).
_SELFTEST_CLASH = """<div id="clash">
<figure id="clash-map"><svg viewBox="0 0 300 120" role="img" aria-label="clash">
<rect x="10" y="10" width="100" height="40" fill="none" stroke="black"/>
<text x="20" y="34" font-size="12">gateway</text>
<text x="30" y="36" font-size="12">tracker</text>
<text x="80" y="80" font-size="12">a long label</text>
<rect x="60" y="66" width="40" height="30" fill="none" stroke="black"/>
<text x="285" y="110" font-size="12">edge</text>
<circle cx="110" cy="10" r="9" fill="red"/>
<text x="110" y="14" font-size="11" text-anchor="middle">1</text>
</svg></figure>
</div>
"""


_SELFTEST_COPY = """<div id="copy">
<div class="card"><button type="button">unrelated</button><pre id="plain">echo one</pre></div>
<pre id="opted" data-no-copy>not a command</pre>
<div><pre id="owned">echo two</pre><button type="button">copy</button></div>
</div>
"""

# A label that fits its box only under a style keyed on a wrapper element, and
# a <text> inside <defs> that is never drawn. Both must pass.
_SELFTEST_IN_PLACE = """<div id="inplace">
<style>#inplace .flow text{font-size:6px}</style>
<section class="flow"><figure id="in-place"><svg viewBox="0 0 200 60" role="img" aria-label="in place">
<defs><marker id="inplace-m" viewBox="0 0 10 10"><text x="0" y="0">x</text></marker></defs>
<rect x="10" y="10" width="70" height="30" fill="none" stroke="black"/>
<text x="14" y="30">service-alpha-x</text>
<rect x="0" y="20" width="40" height="20" fill="transparent"/>
<rect x="0" y="20" width="40" height="20" fill="blue" fill-opacity="0"/>
<text x="16" y="30" opacity="0">hover-only label</text>
<text x="16" y="30" style="display:none">hidden label</text>
</svg></figure></section>
</div>
"""

# A legend SVG before the diagram SVG in one figure: the diagram is the one
# measured, and its clash must be found.
_SELFTEST_TWO_SVGS = """<div id="twosvg">
<figure id="two"><svg viewBox="0 0 100 20"><text x="4" y="14">legend</text></svg>
<svg viewBox="0 0 300 120"><text x="20" y="40">beta label</text><text x="30" y="42">gamma label</text></svg></figure>
</div>
"""


def _png_header(path: Path) -> tuple[int, int, tuple[int, ...]]:
    """Return (width, height, RGB of the top-left pixel) of a PNG file."""
    data = path.read_bytes()
    position, compressed, width, height = 8, b"", 0, 0
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            compressed += body
        position += 12 + length
    # Every PNG filter leaves the first pixel of the first row unchanged.
    return width, height, tuple(zlib.decompress(compressed)[1:4])


def _selftest() -> int:
    results: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append("pass" if ok else "fail")
        if not ok:
            sys.stdout.write(f"FAIL {name} {detail}\n")

    def cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), *args],
                              capture_output=True, text=True, env=env, timeout=300)

    figures = _figures(_SELFTEST_FRAGMENT)
    check("extract-names", [f[0] for f in figures] == ["recording-path", "fig-2"],
          repr([f[0] for f in figures]))
    check("extract-sizes", [(f[3], f[4]) for f in figures] == [(200, 100), (120, 60)],
          repr([(f[3], f[4]) for f in figures]))
    carried = _STYLE_BLOCK.findall(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X"><style>a{}</style>'
        '<link rel="preconnect" href="https://fonts.gstatic.com">')
    check("styles-and-font-links", len(carried) == 2 and "googleapis" in carried[0], repr(carried))

    with tempfile.TemporaryDirectory(prefix="qvisualize-selftest-") as work:
        work_dir = Path(work)
        fragment = work_dir / "map.html"
        fragment.write_text(_SELFTEST_FRAGMENT, encoding="utf-8")
        bare = work_dir / "bare.html"
        bare.write_text("<div id=\"bare\"><p>no figure</p></div>\n", encoding="utf-8")

        run = cli(str(bare), "--export-png", str(work_dir / "out-bare"))
        check("no-figure-exit-2", run.returncode == 2 and "no exportable figure" in run.stderr,
              f"exit {run.returncode}: {run.stderr.strip()}")

        env = dict(os.environ, QVISUALIZE_BROWSER=str(work_dir / "missing-browser.exe"))
        run = cli(str(fragment), "--export-png", str(work_dir / "out-none"), env=env)
        check("no-browser-exit-1", run.returncode == 1 and "QVISUALIZE_BROWSER" in run.stderr,
              f"exit {run.returncode}: {run.stderr.strip()}")
        run = cli(str(fragment), str(work_dir / "missing-out.html"), env=env)
        check("layout-mistyped-browser-named", run.returncode == 0
              and "missing-browser.exe, which is not a file" in run.stderr,
              f"exit {run.returncode}: {run.stderr.strip()}")

        if _find_browser() is None:
            sys.stdout.write("SKIP live-export: no Chrome or Edge found\n")
            results.append("skip")
        else:
            out_dir = work_dir / "out"
            run = cli(str(fragment), "--export-png", str(out_dir))
            check("live-export-exit-0", run.returncode == 0, f"exit {run.returncode}: {run.stderr.strip()}")
            for name, width, height in (("recording-path", 200, 100), ("fig-2", 120, 60)):
                png = out_dir / f"{name}.png"
                if not png.is_file():
                    check(f"live-export-{name}", False, "no PNG written")
                    continue
                size = _png_header(png)
                expected = (2 * (width + 2 * _EXPORT_PAD), 2 * (height + 2 * _EXPORT_PAD))
                check(f"live-export-{name}-size", size[:2] == expected, f"{size[:2]} != {expected}")
                check(f"live-export-{name}-light", size[2] == (255, 255, 255), f"corner pixel {size[2]}")

            run = cli(str(fragment), str(work_dir / "map-out.html"))
            check("layout-clean-exit-0", run.returncode == 0, f"exit {run.returncode}: {run.stderr.strip()}")
            clashing = work_dir / "clash.html"
            clashing.write_text(_SELFTEST_CLASH, encoding="utf-8")
            run = cli(str(clashing), str(work_dir / "clash-out.html"))
            check("layout-clash-exit-3", run.returncode == 3 and not (work_dir / "clash-out.html").exists(),
                  f"exit {run.returncode}: {run.stderr.strip()}")
            for needle in ('"gateway" overlaps text "tracker"', '"a long label" crosses the edge of a rect',
                           '"edge" runs outside the viewBox'):
                check(f"layout-clash-reports {needle}", needle in run.stderr, run.stderr.strip())
            check("layout-badge-exempt", '"1"' not in run.stderr, run.stderr.strip())
            run = cli(str(clashing), str(work_dir / "clash-out.html"), "--no-layout-check")
            check("layout-skip-flag-exit-0", run.returncode == 0, f"exit {run.returncode}: {run.stderr.strip()}")
            in_place = work_dir / "in-place.html"
            in_place.write_text(_SELFTEST_IN_PLACE, encoding="utf-8")
            run = cli(str(in_place), str(work_dir / "in-place-out.html"))
            check("layout-wrapper-styles-defs-invisible-exit-0", run.returncode == 0,
                  f"exit {run.returncode}: {run.stderr.strip()}")
            two = work_dir / "two.html"
            two.write_text(_SELFTEST_TWO_SVGS, encoding="utf-8")
            run = cli(str(two), str(work_dir / "two-out.html"))
            check("layout-second-svg-measured", run.returncode == 3 and "beta label" in run.stderr,
                  f"exit {run.returncode}: {run.stderr.strip()}")
            check("layout-tight-legend-not-flagged", '"legend"' not in run.stderr, run.stderr.strip())
            broken = dict(os.environ, QVISUALIZE_BROWSER=sys.executable)
            run = cli(str(clashing), str(work_dir / "broken-out.html"), env=broken)
            check("layout-unusable-browser-skips", run.returncode == 0
                  and "layout check skipped" in run.stderr and (work_dir / "broken-out.html").exists(),
                  f"exit {run.returncode}: {run.stderr.strip()}")

            # Copy buttons: run the kit's copy runtime (alone, so the kit's CDN
            # scripts cannot delay it) on three <pre> blocks and count the
            # buttons it adds (one opted out, one with its own button).
            kit = (_SKILL_DIRECTORY / "assets" / "visualize.html").read_text(encoding="utf-8")
            runtime = re.search(r"<script id=\"kiro-visualization-copy\">.*?</script>", kit, re.DOTALL)
            check("copy-runtime-in-kit", runtime is not None, "kiro-visualization-copy script missing")
            page = work_dir / "copy.html"
            page.write_text("<!doctype html><html><body>" + _SELFTEST_COPY
                            + (runtime.group(0) if runtime else "") + "</body></html>", encoding="utf-8")
            dumped = subprocess.run(
                [str(_find_browser()), "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={work_dir / 'copy-profile'}", "--virtual-time-budget=3000",
                 "--dump-dom", page.as_uri()],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_BROWSER_TIMEOUT).stdout
            added = dumped.count('class="viz-copy-button"')
            check("copy-buttons-added-once", added == 1, f"{added} buttons added")
            check("copy-button-wraps-plain-pre", '<div class="viz-copy"><pre id="plain">' in dumped,
                  "plain <pre> not wrapped")

    failed, skipped = results.count("fail"), results.count("skip")
    sys.stdout.write(f"render.py selftest: {results.count('pass')} passed, {failed} failed, {skipped} skipped\n")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render an HTML visualization fragment as a sandboxed standalone page."
        ),
        epilog=(
            "Exit codes: 0 = success, 1 = I/O error, "
            "2 = invalid fragment (symlink / >1 MB / complete HTML document), "
            "3 = layout check failed."
        ),
    )
    parser.add_argument(
        "fragment",
        type=Path,
        nargs="?",
        help="path to the HTML fragment",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help=(
            "output HTML path "
            "(default: <fragment-stem>.rendered.html in the fragment's directory)"
        ),
    )
    parser.add_argument(
        "--no-layout-check",
        action="store_true",
        help="skip the check for colliding or clipped labels in <figure> SVGs",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="write a skeleton fragment to the fragment path instead of rendering",
    )
    parser.add_argument(
        "--title",
        help="heading for --scaffold (default: derived from the file name)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help=(
            "serve the rendered page on a random local port and open it in the "
            "browser; exits on Ctrl-C"
        ),
    )
    parser.add_argument(
        "--export-png",
        type=Path,
        metavar="DIR",
        help=(
            "write each <figure> SVG as a 2x light-theme PNG in DIR instead of "
            "rendering (needs Chrome or Edge, or QVISUALIZE_BROWSER)"
        ),
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the built-in cases and exit",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.fragment is None:
        parser.error("the fragment path is required")
    if args.scaffold:
        return _scaffold(args.fragment, args.title)
    if args.export_png is not None:
        return _export_png(args.fragment, args.export_png)

    fragment_text = _read_fragment(args.fragment)
    if not args.no_layout_check:
        checked = _layout_check(fragment_text)
        if checked:
            return checked
    title = _default_title(args.fragment)
    document = _render_document(fragment_text, title)

    # Compute output path (default: <stem>.rendered.html next to the fragment).
    if args.output is not None:
        output_path = args.output
    else:
        output_path = args.fragment.with_name(args.fragment.stem + ".rendered.html")

    if args.serve:
        encoded = document.encode("utf-8")

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # type: ignore[override]
                if self.path not in ("/", "/index.html"):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Content-Security-Policy", _SERVE_CSP)
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass  # suppress access-log noise

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        url = f"http://127.0.0.1:{server.server_port}/"
        sys.stdout.write(url + "\n")
        sys.stdout.flush()
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        try:
            output_path.write_text(document, encoding="utf-8", newline="\n")
        except OSError as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 1
        sys.stdout.write(str(output_path) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
