## Subagent Session Recovery

Reference for extracting deliverables from interrupted or hung kiro-cli v3 subagent sessions. Format details: see `kiro-cli-local-data.md`. For a retired v2 subagent session, see `providers/kiro/reference/kiro-cli-v2-local-data.md`.

### Mental model

A subagent may have completed its work — or produced substantial partial output — before the interruption. Recovery is extraction from the session file, not retry. The deliverable is already written; the orchestrator just didn't receive it.

### Is the subagent actually dead?

Before extracting, confirm the subagent is no longer running:

1. **Check parent session status** — `session.json` → `status` field. If `"in_progress"`, the parent (and potentially subagents) may still be active.
2. **Check sub-execution file mtime** — if the last write was >30 seconds ago with no new content, the subagent is likely dead.
3. **Check process state** — look for active kiro-cli processes. On Windows: `Get-Process kiro* -ErrorAction SilentlyContinue`. On Linux/macOS: `pgrep -f kiro`.

If the subagent is still running, wait rather than extracting from a partially-written file.

### Recovery protocol

`~/.kiro/sessions/<workspace-hash>/sess_<uuid>/sub-executions/<uuid>.jsonl` (linked via `sub_agent_start` → `subSessionId` in parent's `messages.jsonl`).

1. **Check `sub_agent_complete` in parent** — find the message in parent's `messages.jsonl` with `payload.type == "sub_agent_complete"` and matching `subSessionId`.
   - If `status` is `"success"` or `"completed"`: deliverable is in the `response` field. **Do not assume this is the last assistant message.** When the sub-agent terminates via the `subagent_response` tool (the canonical path — its own tool description says *"You MUST call this tool as your final action to complete your task"*), the sub-execution file has **no `assistant`-type lines at all**, and `response` is a copy of that tool call's `args.response` field. `response` equals the last assistant message only in the secondary case where the sub-agent ended with plain text and never called `subagent_response`.
   - If `status` is `"error"`/`"failed"`, or no `sub_agent_complete` exists: fall back to step 2.
2. **Extract from sub-execution file** — read `sub-executions/<uuid>.jsonl`. First look for the last `tool_call` line where `payload.toolName == "subagent_response"`; the deliverable is in `payload.args.response` (this is the primary termination path — see note above). Only if no such call exists, fall back to the last line with `payload.type == "assistant"`, with the deliverable in `payload.content`.
   - **Note**: failed sub-executions (e.g. `"errorMessage": "Invalid model ID"`) typically contain only a `steering_inclusion` record and no `assistant` messages — the agent never ran. In that case the sub-execution file has no recoverable content; retry is the only option.

### Handling truncated files

If the subagent was killed mid-write, the last line of a `.jsonl` file may be truncated (invalid JSON). When the last line fails to parse, try the second-to-last line instead. In snippets: wrap the parse in error handling and fall back to `N-1`.

### Quick-recovery snippets

**PowerShell:**
```powershell
$sessRoot = "$env:USERPROFILE\.kiro\sessions"
Get-ChildItem $sessRoot -Directory | Where-Object { $_.Name -ne "cli" } | ForEach-Object {
    Get-ChildItem $_.FullName -Directory -Filter "sess_*" |
      Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-15) } | ForEach-Object {
        $msgs = Join-Path $_.FullName "messages.jsonl"
        if (Test-Path $msgs) {
            Get-Content $msgs | Where-Object { $_ -match '"sub_agent_complete"' } | ForEach-Object {
                try { $obj = ($_ | ConvertFrom-Json) } catch { return }
                $p = $obj.payload
                Write-Output "=== SubAgent $($p.subSessionId) [status: $($p.status)] ==="
                if ($p.response) { Write-Output $p.response }
                elseif ($p.errorMessage) { Write-Output "ERROR: $($p.errorMessage)" }
            }
        }
    }
}
```

**bash:**
```bash
sess_root=~/.kiro/sessions
find "$sess_root" -maxdepth 3 -name "messages.jsonl" -type f 2>/dev/null |
while read -r msgs; do
  mtime=$(stat -c %Y "$msgs" 2>/dev/null || stat -f %m "$msgs")
  cutoff=$(date -d '15 minutes ago' +%s 2>/dev/null || date -v-15M +%s)
  [[ $mtime -lt $cutoff ]] && continue
  grep 'sub_agent_complete' "$msgs" | jq -r '
    select(.payload.type == "sub_agent_complete") |
    "=== SubAgent \(.payload.subSessionId) [status: \(.payload.status)] ===\n\(.payload.response // .payload.errorMessage // "no output")"
  ' 2>/dev/null
done
```

**Fallback (sub-execution file):**
```bash
# When sub_agent_complete is absent/failed, read the sub-execution directly.
# Check subagent_response FIRST: it's the primary termination path (the tool's
# own description says the agent MUST call it as its final action), and most
# sub-executions have NO "assistant"-type line at all — checking assistant
# first silently returns nothing for the common case.
sub_exec="path/to/sub-executions/<uuid>.jsonl"
tac "$sub_exec" | grep -m1 '"subagent_response"' | jq -r '.payload.args.response' 2>/dev/null ||
  tac "$sub_exec" | grep -m1 '"assistant"' | jq -r '.payload.content' 2>/dev/null ||
  tac "$sub_exec" | grep -m1 '"assistant"' | head -c -1 | jq -r '.payload.content' 2>/dev/null
# On macOS without tac: use tail -r instead
```

### When to retry vs recover

**Recover** (extract from session file) when:
- The subagent's task was to produce a text deliverable (analysis, review, plan)
- The session file shows the subagent made progress (assistant messages present)

**Retry** (re-dispatch the subagent) when:
- The sub-execution file is empty or doesn't exist (subagent never started)
- The last entry is a prompt with no assistant response (crashed immediately)
- The task requires state mutations that didn't complete (check `git status`, working tree for uncommitted writes, running processes)

### Artifact-producing subagents

For subagents that write files or make commits:
1. Check `git log --oneline -5` and `git diff` for expected changes
2. If changes are present: recovery is reading the summary for the orchestrator's log — work is already done
3. If changes are absent AND the session file shows no successful tool calls: retry

### No self-sufficiency bypass

Recovery is a **diagnostic** tool. After extracting a deliverable:
- Present the recovered output to the user or consume it in the orchestrator flow as if it had been returned normally
- Do NOT use recovered partial output to autonomously mark a task complete
- Do NOT auto-retry without user confirmation when recovery fails
- If recovery fails (corrupt file, missing sub-execution, ambiguous state): report what was found and what couldn't be recovered; do not proceed without user decision
