## MCP Troubleshooting

### Agent-level mcpServers override global mcp.json

When `"includeMcpJson": true` is set in the agent definition (`~/.kiro/agents/<name>.json`), both the agent's `mcpServers` and the global `~/.kiro/settings/mcp.json` are merged. However, **the agent's entry takes precedence** — if the agent has `"disabled": true` for a server, editing only `mcp.json` has no effect.

**Diagnosis**: When `/mcp` shows "disabled" despite `mcp.json` having `"disabled": false`, check the active agent's `.json` file for a conflicting `mcpServers` entry.

**Fix**: Edit the server entry in the agent definition (`~/.kiro/agents/<name>.json`), not just `mcp.json`.

### Remote MCP servers use native url transport — not mcp-remote

Kiro CLI handles OAuth for remote MCP servers natively via the `url` field. Do NOT use the `mcp-remote` npm proxy for servers that support the MCP auth protocol (like Atlassian). The native flow:

1. Config: `"url": "https://..."`
2. On session start, the server shows "Needs authentication" in `/mcp`
3. Press Enter on the server in the `/mcp` panel (or Ctrl+Y from the status bar) to copy the OAuth URL
4. Open the URL in a browser to complete OAuth

### `forceAuth` is not a kiro-cli setting — leave it out

No installed KAS bundle reads `forceAuth` (zero occurrences in `acp-server.js` for every version from 2.21.2 to 2.24.0, checked 2026-09-24). The key is silently ignored. The only `ForceAuth` in `tui.js` is the `/mcp` panel's `onForceAuth` callback, which sends `/mcp auth <server>` — an explicit re-auth request, covered in the next section. Do not add `forceAuth` to `mcp.json` or the agent definition; a later reader will blame it for failures it cannot cause.

### Atlassian OAuth: send exactly one authenticate request (verified 2026-09-24, kiro-cli 2.24.0)

**Symptom**: OAuth completes in the browser, `/mcp` shows `loading` indefinitely (or falls back to `auth-required`), and `~/.kiro/secrets.json` holds `kiro.mcp.<hash>.client`, `.discovery` and `.verifier` but never `.tokens`. Every new session asks for authentication again. Same on Windows and WSL.

**Mechanism** (from `acp-server.js`, 2.24.0): every explicit authenticate request (Ctrl+Y from the status bar, or `/mcp auth <server>`) runs `resetServer(name, startOAuth=true)`. `resetServer` awaits the in-flight connection, then tears it down, and the new connection calls `invalidateCredentials("all")` before starting its own flow. Extra requests queue. So when the first flow succeeds and saves its tokens, the next queued request closes that connection, deletes the tokens and opens a new browser flow that nobody completes; it times out after 60 s and its failure is suppressed ("server was removed or changed status"). One Ctrl+Y produces exactly one request (measured) — the duplicates come from pressing it again while the first flow seems idle.

**Fix**: Press Ctrl+Y **once** and complete the browser flow within 60 s. If a flow stalls, wait for the 60 s timeout before triggering again. Verified end to end on WSL: one Ctrl+Y → consent → `Connected`, `.tokens` written, and a fresh `kiro-cli` connects Atlassian (41 tools) with no prompt.

**Where the URL goes**: kiro-cli does not open a browser for MCP OAuth. It copies the authorization URL to the clipboard and shows `OAuth URL copied to clipboard`. On Linux/WSL it tries `wl-copy`, `xclip`, `xsel`, then falls back to an OSC 52 escape, which reaches the Windows clipboard through Windows Terminal but not through tmux by default.

**Diagnosis**: count `Resetting connection` lines with `startOAuth: true` in `~/.kiro/logs/<session>/mcp.log` — more than one per intended login, followed by `Connected` and then `Connection closed`, is this failure. Confirm with the secrets.json watcher below: `+tokens` followed shortly by `-tokens`.

**Supersedes** the earlier diagnosis here of a "kiro-cli 2.23.x token exchange regression with no workaround" (2026-09-23). That record's evidence — tokens never appearing — matches this mechanism; the token exchange itself succeeds.

### Atlassian MCP — working config (verified kiro-cli 2.22.x and 2.24.0)

`mcp.json` (`~/.kiro/settings/mcp.json`):
```json
"atlassian": {
  "url": "https://mcp.atlassian.com/v1/mcp/authv2",
  "disabled": false
}
```

The endpoint is `/v1/mcp/authv2` (not `/v1/sse` which is deprecated since June 2026). The Kiro IDE uses this same URL.

### Bedrock `TOOL_SCHEMA_INVALID` — one MCP tool lists a `required` entry twice (verified kiro-cli 2.27.1, 2026-10-05)

**Symptom**: every model request fails with `The json schema definition at toolConfig.tools.N.toolSpec.inputSchema is invalid ... $.required: the items in the array must be unique`. The error names only a tool index, never the tool or the server, and no tool call is involved. It can start mid-session: requests succeed until the MCP server finishes connecting, then all fail. Zoho Desk does this on 69 of its 128 tools (for example `required: ["path_variables", "path_variables"]`).

**Why only some clients hit it**: with tool search off, the agent sends every MCP tool's full schema on each request, so one bad schema fails all of them. `kiro-cli acp` does not read `~/.kiro/settings/cli.json`; the terminal UI reads `toolSearch.*` from it and forwards it at `initialize`, which defers MCP schemas. A client that forwards nothing (PowerAtlas did until 2026-10-05) gets tool search off. Tool search only hides the defect: a bad tool the model loads is still sent.

**Diagnosis**: run the server's `tools/list` and look for a `required` array with repeated items, at any depth. Claude Code reporting "N tools excluded (invalid input schema)" for a server is the same defect.

**Fix**: run the server through `~/.kiro/mcp-wrappers/dedupe-required.mjs`, which deduplicates `required` in each tool's schema and passes everything else through unchanged. In `mcp.json`: `"command": "node"`, `"args": ["<wrapper path>", "npx", "-y", "mcp-remote@latest", "<url>"]`. The script is user-level and not in this repo. To undo, restore the original command and args.

### Watching secrets.json during an OAuth flow

The Kiro IDE (Electron) stores OAuth tokens separately, not in `secrets.json`, so it is unaffected by the queued-reauth failure above.

```powershell
# Watch secrets.json for token writes and deletions in real time (run before triggering OAuth)
$f = "$env:USERPROFILE\.kiro\secrets.json"
$prev = @{}
for ($i = 0; $i -lt 600; $i++) {
    $c = Get-Content $f -Raw | ConvertFrom-Json -AsHashtable
    $keys = @($c.Keys | Where-Object { $_ -match 'kiro\.mcp\.' } | Sort-Object)
    $added = $keys | Where-Object { -not $prev.ContainsKey($_) }
    $removed = @($prev.Keys) | Where-Object { $keys -notcontains $_ }
    if ($added) { "$(Get-Date -Format 'HH:mm:ss.fff') +$($added -join '; ')" }
    if ($removed) { "$(Get-Date -Format 'HH:mm:ss.fff') -$($removed -join '; ')" }
    $prev = @{}; foreach ($k in $keys) { $prev[$k] = $true }
    Start-Sleep -Milliseconds 100
}
```

### Single source of truth: mcp.json, not the agent definition

MCP server configs live in `~/.kiro/settings/mcp.json` only. The v3 agent definition (`~/.kiro/agents/kiro_default.md`) declares `includeMcpJson: true` — it inherits everything from `mcp.json`. Do not add server entries to the agent definition; they take precedence and create hidden overrides.

### Layered-config precedence — check the override before iterating on the mechanism

In any layered-config system, establish which layer actually wins **before** iterating on a setting's mechanism — a setting that reads correct at the layer you are editing is not evidence that it is in force. (The Atlassian failure above cost several config-mechanism variants and restart-and-test cycles for exactly this reason: the *visible* setting in `mcp.json` looked correct and simply had no effect.)
