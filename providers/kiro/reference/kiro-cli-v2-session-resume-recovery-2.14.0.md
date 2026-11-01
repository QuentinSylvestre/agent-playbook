## Session Resume Recovery (kiro-cli 2.14.0+, v2)

> **Reference only — not deployed.** kiro-cli v2 is retired and this workaround is obsolete on v3.
> It loads on demand only — not in `inventory.tsv`, so it never reaches a session's context.
> **Read when** a v2 session on kiro-cli 2.14.x fails to resume with a dirty state. Indexed from
> `memory/topics/kiro-cli.md`.

**Temporary workaround** — remove when kiro-cli handles dirty-state resume gracefully.

### Symptom

Resuming an existing v2 session fails with "Agent connection closed unexpectedly." New sessions work fine.

### Root Cause

The session process crashed/died mid-turn (e.g., during a long `/qplan` or subagent dispatch). The JSONL received partial writes but the `.json` metadata was never updated with the new turn entry. kiro-cli 2.14.0+ validates metadata/JSONL consistency on resume and rejects the mismatch.

### Diagnosis

```powershell
$id = "<session-id>"
$dir = "$env:USERPROFILE\.kiro\sessions\cli"
$meta = Get-Content "$dir\$id.json" -Raw | ConvertFrom-Json
$lastMsgId = $meta.session_state.conversation_metadata.user_turn_metadatas[-1].message_ids |
  Where-Object { $_ } | Select-Object -Last 1
$jsonl = Get-Content "$dir\$id.jsonl"
# Find where the last tracked message is in the JSONL
for ($i = 0; $i -lt $jsonl.Count; $i++) {
  if (($jsonl[$i] | ConvertFrom-Json).data.message_id -eq $lastMsgId) {
    "Last tracked message at line $i of $($jsonl.Count - 1)"
    "Orphan tail: $($jsonl.Count - 1 - $i) lines"
    break
  }
}
```

If orphan tail > 0 (typically 5-50 lines), the session has a dirty state.

### Fix

Truncate the JSONL to remove the untracked tail:

```powershell
$id = "<session-id>"
$dir = "$env:USERPROFILE\.kiro\sessions\cli"
$meta = Get-Content "$dir\$id.json" -Raw | ConvertFrom-Json
$lastMsgId = $meta.session_state.conversation_metadata.user_turn_metadatas[-1].message_ids |
  Where-Object { $_ } | Select-Object -Last 1
$jsonl = Get-Content "$dir\$id.jsonl"
for ($i = 0; $i -lt $jsonl.Count; $i++) {
  if (($jsonl[$i] | ConvertFrom-Json).data.message_id -eq $lastMsgId) { break }
}
$keepLines = $i + 1
"Truncating from $($jsonl.Count) to $keepLines lines (removing $($jsonl.Count - $keepLines) orphan lines)"
$jsonl[0..($keepLines - 1)] | Set-Content "$dir\$id.jsonl" -Encoding UTF8
```

After truncation, resume normally with `kiro-cli chat --resume-id <session-id>`.

### What's lost

The orphan lines represent a partially-executed turn that crashed. Any work from that turn that was committed to git (files written, commits made) is preserved — only the conversational context of the unfinished turn is lost. Re-invoke the skill/command that was running when the crash occurred.

### Notes

- The "Response was interrupted by the user" placeholder messages (from Ctrl+C cancellations) are harmless — they sit inside the tracked range and don't cause this issue.
- Only orphan lines *after* the last tracked `message_id` trigger the resume failure.
- First observed: 2026-07-23, kiro-cli 2.14.0 (binary 0.12.333).
