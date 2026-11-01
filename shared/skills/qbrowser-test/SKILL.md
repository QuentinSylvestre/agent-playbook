---
name: qbrowser-test
description: Procedural knowledge for verifying, testing, or interacting with browser-accessible content using Playwright MCP browser tools or standalone scripts.
argument-hint: "<URL or path to test>"
---

# Browser Test

## Your role

You verify and interact with browser-accessible content using Playwright-based browser tools. Use MCP browser tools when available (primary); fall back to standalone Playwright scripts when they are not.

## Scope

$ARGUMENTS

If an argument is provided, treat it as the target URL or file path to test. If no argument is provided, determine the target from the current task context (the file just created, the server just started, the URL under test).

## MCP Browser Tools

### Tool reference

| Tool | Use for |
|---|---|
| `browser_run_code_unsafe` | Execute arbitrary Playwright code (navigation, complex assertions, multi-step flows) |
| `browser_snapshot` | Accessibility tree snapshot — preferred for structural assertions (element presence, text content, ARIA roles) |
| `browser_take_screenshot` | Visual verification — use when layout/styling matters or snapshot is insufficient |
| `browser_click` | Click an element identified from a snapshot |
| `browser_type` | Type into an input identified from a snapshot |
| `browser_console_messages` | Check for JS errors after page load |
| `browser_close` | Close the browser page — call after verification is complete |

### Loading local HTML files

Use `browser_run_code_unsafe` with `page.goto('file://...')` for local files. Do NOT start an HTTP server — the file:// protocol works directly. Only `browser_navigate` blocks `file://` (see "When file:// is blocked"); `page.goto()` via `browser_run_code_unsafe` does not.

```javascript
async (page) => {
  await page.goto('file:///C:/path/to/file.html');
  await page.waitForLoadState('domcontentloaded');
  return await page.title();
}
```

Use absolute paths. On Windows, use forward slashes in the URL: `file:///C:/Users/...`. On Linux/macOS: `file:///home/user/...`.

### Verification pattern

1. **Navigate** — `browser_run_code_unsafe` with `page.goto()`
2. **Wait** — `waitForLoadState('domcontentloaded')` or `waitForSelector()`
3. **Assert structure** — `browser_snapshot` for element presence and text
4. **Check errors** — `browser_console_messages` with `level: "error"`
5. **Interact** — `browser_click` / `browser_type` on elements from snapshot
6. **Re-assert** — snapshot or screenshot after interaction
7. **Cleanup** — `browser_close` to close the page; delete any screenshot files saved to disk

### Clicks right after navigation (Claude-in-Chrome MCP)

A ref-based click issued within seconds of a navigation can be dropped silently: no pointer events reach the page. Before concluding a click "does nothing", let the page settle, prefer a coordinate click taken from a fresh screenshot, and confirm delivery with a capture-phase `pointerdown` listener. Recompute coordinates after any window resize.

### Snapshot vs screenshot

- **Snapshot** (`browser_snapshot`): use for structural verification — element exists, text content matches, ARIA roles correct. Machine-readable, fast, deterministic.
- **Screenshot** (`browser_take_screenshot`): use for visual/layout verification — CSS rendering, spacing, colors, responsive behavior. Requires visual inspection.

Default to snapshot. Use screenshot only when the question is visual.

When using `browser_take_screenshot`, prefer omitting the `filename` parameter — the image data is returned inline with no file on disk. If you pass `filename` (e.g., for the user to inspect later), delete the file after verification is complete.

For additional MCP snippets (element counting / content verification, JS error capture), kiro carries worked examples in its overlay.

## Standalone Scripts

Use when MCP browser tools are unavailable (e.g., CI, headless environments).

### Static HTML testing

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("file:///C:/path/to/file.html")
    page.wait_for_load_state("domcontentloaded")

    assert page.locator(".card").count() == 3
    assert "Expected Title" in page.title()

    browser.close()
```

For additional script snippets (dynamic webapp interaction, console-log capture), kiro carries worked examples in its overlay.

## When file:// is blocked

The MCP `browser_navigate` tool may block `file://` access ("Access to file: protocol is blocked"). When this happens, serve the file over HTTP. Capture the process for cleanup.

On Windows, use `Start-Process -WindowStyle Hidden -PassThru` (not `-NoNewWindow` which hangs the shell, and not `Start-Job` which doesn't persist across shell tool calls):

```powershell
# Start server and capture process
$server = Start-Process -FilePath "python" -ArgumentList "-m http.server 8767 --directory `"<dir>`"" -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 3
# Verify it's ready before navigating
Test-NetConnection -ComputerName localhost -Port 8767
```

On Linux/macOS:
```bash
python -m http.server 8767 --directory "<dir>" &
SERVER_PID=$!
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://localhost:8767/<file>
```

Always verify the server responds before calling `browser_navigate`.

## Electron apps (non-Playwright fallback)

Playwright's browser tools drive Chrome tabs, not Electron `BrowserWindow`s — an
Electron app has no Chrome-tab surface for `browser_navigate`/`browser_snapshot`
to attach to. Check first whether the app's dev tooling forwards a remote-debugging
port: many Electron dev setups (e.g. `vite-plugin-electron`'s `startup()` helper)
already honor a `REMOTE_DEBUGGING_PORT` env var and forward it to Electron's CLI as
`--remote-debugging-port`, exposing the live renderer over the Chrome DevTools
Protocol with no code or config change to the app itself.

If a `vite-plugin-electron` app fails to build or start (native modules, preload
entries, `package.json` `type`), read `memory/topics/electron-vite.md` in the
config repo before debugging the bundler config.

Launch with the env var set (e.g. `REMOTE_DEBUGGING_PORT=9333 npm run dev`), then
connect directly via raw CDP — no Playwright/Puppeteer dependency needed (Node 24+
ships a global `WebSocket` client):

1. `GET http://localhost:<port>/json` to find the page target's `webSocketDebuggerUrl`
2. Open a WebSocket to that URL
3. Send `Runtime.evaluate` with `expression`, `returnByValue: true`,
   `awaitPromise: true` to run arbitrary JS in the live renderer — reading DOM
   state, dispatching real `MouseEvent`s (not bare `.click()`, which some frameworks'
   event delegation ignores), or calling a generic IPC bridge the preload script
   exposes (e.g. `window.electronAPI.invoke(channel, ...)`)

This last point matters for surfaces gated behind a native OS dialog (file picker,
save dialog) that CDP cannot drive: if the renderer exposes a generic
`invoke(channel, ...)` bridge, call the target channel directly with a real
argument instead of trying to drive the dialog, or reporting BLOCKED. This
exercises the identical real IPC handler and downstream logic the UI's own flow
would use — it bypasses only the dialog, not the pipeline.

Always confirm no orphaned Electron process survives a prior session before
launching (`electron.exe` can persist after a shell tool's own process is
stopped), and tear down (kill the process, confirm via a process list) after
verification completes.

**After verification, kill the server:**

Windows:
```powershell
Stop-Process -Id $server.Id
```

Linux/macOS:
```bash
kill $SERVER_PID
```


## Heavy QA delegation

When browser verification involves multiple checks (>3 assertions), cross-browser testing, or full visual regression suites, delegate the browser work to a **sub-agent**. The orchestrator's responsibilities are:

1. Ensure servers/services are running and accessible
2. Close any open Playwright browser session (`browser_close`) so the sub-agent gets exclusive access
3. Dispatch the sub-agent with a structured check list (URLs, JS evaluate expressions, expected values)
4. Receive compact pass/fail results — no screenshots in orchestrator context

The sub-agent owns the Playwright session exclusively, performs all checks, and returns a summary table.

**Light/rapid single-check verification** (e.g., "is the server up?", "did dark mode apply?") can still be done inline by the orchestrator without sub-agent dispatch.

## Post-verification cleanup

After all browser verification is complete (whether inline or sub-agent), perform cleanup:

1. **Close the browser page** — `browser_close` if the Playwright session is still open
2. **Remove temp files** — delete the `.playwright-mcp/` directory if it exists (screenshots, snapshots, console logs)
3. **Stop test-only processes** — kill any server processes that were started specifically for the verification (not pre-existing user processes)

This cleanup is mandatory and automatic — do not wait for the user to ask about leftover artifacts.
