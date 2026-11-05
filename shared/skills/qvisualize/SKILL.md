---
name: qvisualize
description: "Create interactive visualizations (D3 charts, maps, system and data-flow maps, viz-calendar, mockups, simulations, share/export, PNG export for documents) as standalone HTML. Visual IS the deliverable. PA: emit_visualization; standalone: Start-Process."
---

# /qvisualize

- A request to add a website, app page, component, or other file to the project is not a visualization request, even when the deliverable contains charts or interactive content. A request to visualize, map or diagram something is one, even when it names an output folder: write the fragment and render it there.
- Create a visualization only when the user needs to see or explore something in context and it materially improves the answer. Do not create one merely because the request involves data.
- Use a normal Markdown table when the user asks for a table; return it directly and do not create a visualization file.
- Use Mermaid when labeled nodes and edges fully explain a static structure of about 8 nodes or fewer and auto-layout is acceptable; return a fenced Mermaid block and no visualization file. Use HTML for system and data-flow maps, dynamics, spatial motion, adjustable inputs, and other visuals.
- On a map or explainer, take every name, path, key, route, status and command from code, a document, or command output read in this session, never from an earlier visualization. Suffix anything you did not check with a visible `(assumed)`.
- Send no chat text until the final response: no commentary or progress updates while reading this skill, writing files, or running render.py. The final response must be your first user-facing message. This covers chat text only: `emit_visualization` calls are how the user sees progress, so make them.
- In user-facing prose, describe only what the visual helps the user see or decide. Never announce this skill, HTML, scripts, local files, or implementation details.

## Read the complete skill

Read this file in full before authoring. Reread truncated ranges in smaller calls. Copy into every compaction summary: `Reload the full qvisualize skill before creating or updating a visualization.`

## When NOT to use

- **Design spike / throwaway prototype** — use `/qprototype` instead.
- **Small static labeled-node diagram** (about 8 nodes or fewer, auto-layout acceptable) — use a fenced Mermaid block.
- **Data table** — return a Markdown table directly.
- **Project file / site page** — use the project's own build tools; this skill is for in-context answer visualizations only.

## Fragment output contract

Write only an HTML fragment: no `<!doctype>`, `<html>`, `<head>`, or `<body>`.

- Write literal markup. Never embed the fragment in an inline Python, JavaScript, or shell string. Read it back; rewrite literal `\"` or `\n`.
- Give the fragment root a unique lowercase-hyphenated `id` and select it with `document.getElementById(...)`. Never derive the root from `document.currentScript`.
- Keep visualizations under 1 MB. Aggregate, bin, or downsample large inline datasets.
- Load external resources only from the CDN allowlist (below). Never use `fetch`, XHR, WebSocket, or other API calls inside the fragment.
- Check that JavaScript has no undefined identifiers, every queried element exists, and the primary interaction updates the visual.
- `emit_visualization` takes any absolute path to the rendered `.html` file, up to 16 MB. PowerAtlas keeps its own copy, so write the files where step 1 says; emitting the same file again updates the card in place.

## CDN allowlist

Only these origins are permitted; others are blocked by CSP and fail silently:

- `cdnjs.cloudflare.com`
- `cdn.jsdelivr.net`
- `esm.sh`
- `unpkg.com`
- `fonts.googleapis.com`
- `fonts.gstatic.com`
- `fonts.bunny.net`

## Design token contract

Use only the CSS variables defined in the agent-facing contract block of `assets/visualize.css` (block marked `/* Agent-facing contract */`). These are the 33 semantic tokens (`--background` through `--yellow`) and the 6 data-series tokens (`--viz-series-1` through `--viz-series-6`). Never use internal implementation variables (`--font-sans`, `--radius-*`, etc.) or legacy aliases (`--viz-bg`, `--viz-panel`, etc.).

Key tokens: `--background`, `--foreground`, `--card`, `--card-foreground`, `--popover`, `--popover-foreground`, `--primary`, `--primary-foreground`, `--secondary`, `--secondary-foreground`, `--muted`, `--muted-foreground`, `--accent`, `--accent-foreground`, `--destructive`, `--border`, `--input`, `--ring`, `--blue`, `--orange`, `--green`, `--red`, `--purple`, `--yellow`, `--viz-series-1` … `--viz-series-6`.

## Workflow

Build in small steps. Each response has its own output limit that your reasoning shares; at high effort, reasoning plus one large write can use all of it and end the turn with no file and no error. So the first action is always a tool call, and nothing is planned at length before it.

`<python>` below is `"<config-repo>\.venv-agent-playbook\Scripts\python.exe" -I` (`<config-repo>`: `shared/AGENTS.md § Config Repo Locations`), the playbook's one interpreter. If that file is missing or fails to start, stop and tell the user "venv missing — run setup.ps1"; never use a Python from `PATH`.

1. **Scaffold first, before any other reasoning.** Create the skeleton in the folder the user named. If the user named none, use the folder this prints, and fall back to the session working directory only if it fails:
   ```powershell
   & <python> <config-repo>\shared\skills\qdream\scripts\store-resolver.py scratch "<session working directory>" <YYMMDD>-<topic>
   ```
   `<topic>` takes only letters, digits, `.`, `_` and `-`. That folder is deleted after 30 days without changes. If the user asks to keep a file, move it to the store's `artifacts/`, or to a folder they name when there is no store. Then scaffold in the chosen folder, by absolute path, here and in every later command:
   ```powershell
   & <python> <config-repo>\shared\skills\qvisualize\scripts\render.py --scaffold "<folder>\chart.html" --title "Concise title"
   ```
   It writes a small, valid fragment with marked places: `/* STEP:STYLES */`, `/* STEP:DATA */`, `/* STEP:RENDER */`, `/* STEP:CONTROLS */`. It refuses to overwrite: on a second visualization the same day, use a new topic.
2. **In PowerAtlas, show the skeleton at once**: render it and emit it as below, so the user sees progress within seconds. Skip step 6's screenshot check for this render. Use the same output file for every render: a different name makes a second card.
3. **Fill the markers one at a time**, each a separate edit of at most about 6 KB that replaces one marker (keep the marker line's neighbours intact), in this order: data, render, controls, styles. Think only about the piece in hand. After each piece that changes what is visible, render and deliver again; in PowerAtlas the card updates in place. In the standalone branch, deliver only once, at the end.
4. Read the file back once at the end to confirm no marker is left and the script is complete.
5. **Check every fact in a command.** For each container, bucket, port, path, URL and table name in a probe card or label, find it in a file or command output read in this session. An earlier visualization or rendered page is never a source: its facts were generated, not checked, so confirm each one in code, a document, or command output. Suffix any you cannot find with `(assumed)`.
6. Run render.py:
   ```powershell
   & <python> <config-repo>\shared\skills\qvisualize\scripts\render.py "<folder>\chart.html" "<folder>\chart-out.html"
   ```
   Before writing, it measures every static `<figure>` SVG in a headless browser. When the fragment has none (a D3 chart drawn by script), or render.py printed `layout check skipped`, take one browser screenshot of the output instead and check it for overlapping or clipped labels; fix and render again before delivering.
7. **If render.py exits 3**, it lists each label that overlaps another, crosses a box or circle edge, or leaves the viewBox. Move those labels or widen those boxes, then render again; repeat until it exits 0. Never pass `--no-layout-check` unless the user asks for it. **On any other non-zero exit**, surface the full stderr to the user and stop. Do not proceed to the delivery branch.
8. Branch on context:

**PowerAtlas branch** (both conditions must be true):
- `$env:POWER_ATLAS_SESSION` is set, AND
- `emit_visualization` is available in your tool list.

Read your session id from the shell: `$env:KIRO_SESSION_ID` (starts with `sess_`). It is the only reliable source; the MCP handshake is not visible to you. Then call:
```
emit_visualization(path="<absolute-path-to-chart-out.html>", title="<concise title ≤50 chars>", session_id="<value of $env:KIRO_SESSION_ID>")
```
The visualization renders as an inline iframe card in the ACP transcript.
If `emit_visualization` returns an MCP error, surface the error message to the user and fall back to `Start-Process <absolute-path-to-chart-out.html>` to open in the browser, then continue as the standalone branch: deliver only once more, at the end.

If `$env:POWER_ATLAS_SESSION` is set but `emit_visualization` is not in your tool list, the PowerAtlas viz MCP server did not load. Open the file with the standalone branch and say in your final message that the inline card was unavailable, so the user can report it.

**Standalone branch** (all other cases):
```powershell
Start-Process <absolute-path-to-chart-out.html>
```

## Visualization types

### D3 charts and plots

Use D3 for data-rich Cartesian or statistical plots. Load the version-pinned CDN script `https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js`.

- Render directly on the transparent host surface. Never wrap charts in `.card`, rounded panels, filled backgrounds, or shadowed containers.
- Give each figure a concise visible title. Render in its own responsive SVG with matching `viewBox`, thin frame, and `text.axis-title[data-axis="x"]` and `text.axis-title[data-axis="y"]` showing quantities and units.
- Set each SVG `viewBox` from its container's measured width; redraw with `ResizeObserver`. Reserve at least 64px for the y axis.
- Derive padded domains with `d3.extent(...)`. Inset scale ranges for marker radii; keep all paths inside `rect[data-chart-frame]`.
- Use `--viz-series-1` for one measure or active state; `--viz-series-2` through `--viz-series-6` for persistent category identity. Use `--foreground` and `--border` for neutrals.
- Give every SVG label `fill: var(--foreground)` and `font-size: 12px`; never shrink below 11 screen pixels.
- Share one root-relative `<div class="tooltip" role="tooltip">` using `--popover` and `--popover-foreground`.
- Find ordered observations with `d3.bisector(d => d.x).center(values, x)`.
- Animate transitions between states; never loop motion; honor `prefers-reduced-motion`.

### Geographic maps

Always project published GeoJSON/TopoJSON data with `d3-geo`; never hard-code geographic outlines.

- For world countries: import `https://esm.sh/@d3-maps/atlas@1.0.0/world/countries/countries-110m` and convert with `topojson-client@3.1.0`.
- For US states/counties: use `https://cdn.jsdelivr.net/npm/us-atlas@3/counties-10m.json/+esm`.
- Show the full region behind points or partial choropleths with modest padding.
- Let the map dominate the composition; use at most one compact selection/detail area.

### viz-calendar

Use the bundled `<viz-calendar>` web component for day schedules. Supply verified dates and events; the component handles durations, overlap lanes, and responsive layout. Never stretch the schedule to fit secondary text or wrap in another card.

Required attributes: `date="YYYY-MM-DD"`, `start="HH:MM"`, `end="HH:MM"`, `events="[{...}]"`.
Optional: `now`, `lang`, `time-zone`, `empty-label`, `interactive`.

### UI mockups with variant carousels

For alternative designs of the same component or screen, use a `.viz-carousel` with `[data-variant]` panels. Use descriptive variant names without numeric or ordinal prefixes (e.g., `Compact`, never `01 · Compact`). Add `.viz-dotted-background` to the surrounding preview area for a quiet dot grid.

**Critical**: never use visualization CSS variables or utility classes inside a mockup (`--card`, `.btn`, etc.). Define root-scoped, product-specific colors, typography, surfaces, and controls instead. This rule overrides all general visualization guidance.

Use product context already available in the conversation. Match the product's chrome, navigation, typography, and colors. If unavailable, infer from platform and request.

### Interactive explainers and simulations

Use compact controls or status, one compact dominant visual, and at most one single-line selected-state detail. Default to no summary cards; allow up to three only when changing metrics are central. Crop empty space and fit the available inline width.

### System and data-flow maps

Use for a pipeline, architecture or data-flow map that Mermaid's auto-layout cannot hold: more than about 8 nodes, a fixed grid, markers on edges, or labels that must not collide. Hand-author static inline SVG.

- Put each diagram in its own `<figure>` holding one `<svg viewBox="0 0 W H">` and a `<figcaption>`. Place nodes on a grid.
- Label every arrow with what moves across it (`HTTP POST /meas`, `flush ≈5 min`).
- Draw stores (databases, buckets, queues) in a different shape and token from services.
- Size each box from its longest label: about 0.6 em per character for monospace at the 12px label size, plus padding.
- **Operational maps**: when the reader will check the running system, put numbered markers on the nodes or edges to probe. Below the figures, give one card per number: the command in a `<pre>`, then an `Expect:` line naming the output that means healthy. The rendered page adds a copy button to every `<pre>` present when it loads, wrapping it in a `div.viz-copy`, so style the `<pre>` by class, never as a direct child (`.card > pre`). Mark a `<pre>` that is not a command with `data-no-copy`.
- **Read `assets/example-system-map.html` before drawing a system map**, and follow its shape: a title with context chips (identifiers, environment, time zone); a legend of node kinds; one wide figure per flow (real-time path, batch path), left to right, with lane labels in capitals above each column; small side figures in a two-column grid for record format, timing, states or decision rules; a "where the data lives" table (data, store, key or table, written by, read by, probe); then the probe cards. Copy the structure and the token use, not the example's content.

### Share and export pages

When the user explicitly asks to export or share a visualization, use the `share-shell.js` and `share-shell.css` assets in `assets/`. The share page wraps the visualization in a 3D-flip card with an optional Sources panel. Provide `<script type="application/json" id="visualization-share">` with the configuration object (metadata + labels).

### Document export

When diagrams go into Confluence, Word or PowerPoint, run render.py with `--export-png <dir>`. It writes one 2x light-theme PNG per `<figure>` SVG, named from the figure `id` or `fig-N`. Put diagrams in the document as images. Keep tables and commands as native document text so readers can search and copy them.

## Silent execution rule

Work silently until the final response. Do not send progress messages while writing the fragment file, running render.py, or calling emit_visualization. The rendered output reference is your first and only user-facing message.

## Mermaid vs HTML routing

| Input | Output |
|---|---|
| Small static labeled-node diagram (about 8 nodes or fewer), flowchart, sequence diagram | Fenced Mermaid block |
| System or data-flow map: more than about 8 nodes, grid, probes, or dense labels | Hand-authored SVG fragment → render.py |
| Dynamics, spatial motion, adjustable inputs, simulations | HTML fragment → render.py |
| Markdown data table | Markdown table |
| Everything else that requires visual exploration | HTML fragment → render.py |

## Runtime styles

### Color

Make every fill, stroke, text, border, shadow, chart, and canvas color theme-aware via the contract tokens. Never hardcode light or dark values such as white panels, black text, or Tailwind literals.

- Use `--viz-series-1` for a single measure or active state. Use `--viz-series-2` through `--viz-series-6` only for important persistent category identity; never color every peer differently by default.
- Use `--primary` and `--primary-foreground` for filled selected or pressed controls. Reserve `--accent` for subtle interactive surfaces.
- Use series colors only for chart marks and legend swatches. Keep axis text and labels in `--foreground` or `--muted-foreground`.
- Keep chart grids thin and neutral: 1–2px neutral structural paths.

### Typography

- Scale type with `--font-size-base`. Use normal text by default and `.text-small` only for secondary annotations; never below 11px.
- Use only weights `400` and `500`. Never set custom font sizes or line heights.
- Use `.tabular-nums` on changing or aligned numbers.

## Composition

Choose the smallest composition that fits.

- Prefer interaction detail over permanent panels, toolbars, repeated legends, or long stacks.
- Show only metrics that explain the requested behavior. Put live values in control headers or on the visual before cards.
- Keep filters, selections, and other presentation-only interactions local to the fragment.

### Remembering interaction state

- Read saved state from `window.openai.widgetState` when rendering. Listen for `openai:set_globals` and apply `event.detail.globals.widgetState` when present. Use defaults for missing or incompatible state.
- After meaningful interactions, call `window.openai.setWidgetState({ modelContent, privateContent }).catch(() => {})`. Updates are optimistic; keep state under 16 KiB.
- Put choices useful for follow-up questions in `modelContent`, UI details worth restoring in `privateContent`. Never save on load or state events. No secrets or images.
- In standalone mode, widget state is in-memory only and does not survive page reloads (sandbox null-origin restriction). Use safe defaults on load.

## Layout and accessibility

- Use semantic HTML, keyboard-accessible controls, and concise labels.
- Use `aria-live="polite"` for dynamic results, selections, and simulator updates. Use `role="alert"` for validation errors.
- Keep the top-level surface transparent and unframed; fill the available inline width. Design for 736px (normal) or 1,024px (wide), and support down to 320px.
- Size every SVG from its actual container. At narrow widths, reduce ticks and declutter annotations; never shrink below 11px.
- Keep native tab order; never add `tabindex`.
- On coarse pointers, provide non-overlapping effective targets about 44px × 44px.
- Keep essential content available without hover.

## Design system utilities

### Surfaces and layout

- `.card`: use for a necessary numeric summary, selected-item summary, or bounded interactive field. Never nest cards. Never recreate card chrome on rows, panels, or wrappers.
- `.viz-stat` + `.viz-stat-value`: compact metric summary inside a `.card`.
- `.viz-grid`: peer metrics or choices in equal-width columns.
- `.viz-row`: wrapping horizontal group for related values or inline actions.
- `.viz-badge`: compact display-only accent pill.
- `.viz-controls`: wrapping row for controls affecting the same visualization.
- `.viz-dotted-background`: quiet dot grid for mockup preview areas only.

### Tabs

```html
<div class="nav nav-pills" role="tablist" aria-label="Platform">
  <button class="nav-link active" id="mac" role="tab" aria-controls="mac-panel" aria-selected="true" type="button">macOS</button>
  <button class="nav-link" id="win" role="tab" aria-controls="win-panel" aria-selected="false" type="button">Windows</button>
</div>
<div id="mac-panel" role="tabpanel" aria-labelledby="mac">macOS content</div>
<div id="win-panel" role="tabpanel" aria-labelledby="win" hidden>Windows content</div>
```

Tab behavior is handled by the bundled JavaScript runtime.

### Controls

- `.btn`: content-sized secondary action. `.btn-primary`: one main action per group. `.btn-ghost`: low emphasis.
- `[data-tooltip]`: concise supplementary text on static or dynamic triggers.
- `.form-label` + `.form-control`: text, date, file, or color input.
- `.form-label` + `.form-select`: select element.
- `.form-check` + `.form-switch`: toggle / switch.
- `.form-range`: range slider with a visible label showing current value.

### Tables

- `.table`: quiet, unframed data view with subtle horizontal dividers. Sentence case for headers.
- `.table-responsive`: wrap when columns cannot fit at narrow widths.
- `.table-sm`: reduced cell padding when more rows need to fit.

## Charts

- Prefer inline SVG for simple charts; use version-pinned CDN libraries when native interaction, scales, or legends materially improve the result.
- Resolve theme colors before passing to canvas or chart APIs that cannot parse CSS variables.
- Scope SVG styles to the chart class. Never target every `svg` in a container that also holds Lucide icons.
- Include labeled axes, units, and directly labeled important values. Give every chart a concise screen-reader summary.
- Add a legend only when multiple series cannot be labeled directly. Pair color with shape or text.

## Icons

Use the sandbox-provided `lucide` global. Add an icon name with `data-lucide`:

```html
<i data-lucide="search" aria-hidden="true"></i>
```

Never author inline icon SVG or icon paths. Mark decorative icons `aria-hidden="true"`. After adding icons dynamically, call `lucide.createIcons({ attrs: { width: 16, height: 16 } })`.
