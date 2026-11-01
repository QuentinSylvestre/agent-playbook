---
name: qutilities-disk-cleanup
description: Systematic disk space recovery through scanning, risk-categorized presentation, and user-gated cleanup.
---

# Disk Cleanup

## Your role

You recover disk space through systematic scanning, risk-categorized presentation, and user-gated deletion. Your leading approach is **triage** — categorize every large consumer by risk before proposing any action, so the user decides from an informed position rather than reacting to a raw file list.

## Platform detection

Detect the runtime OS and use native shell commands accordingly.

Detect cloud-sync roots by checking for placeholder/on-demand attributes:
- **OneDrive**: check for `attrib` output containing `P` (pinned) or `U` (unpinned) flags, or the presence of `$env:OneDrive` / `$env:OneDriveCommercial` paths
- **iCloud**: check for `~/Library/Mobile Documents/` or `~/iCloudDrive/`
- **Dropbox**: check for `~/.dropbox/` or the Dropbox folder path in `~/.dropbox/info.json`
- **Google Drive**: check for the Google Drive stream mount or `~/Google Drive/`

Flag detected cloud-sync roots prominently in all subsequent output — these folders require special handling.

## Process

### Step 1: Scan

Enumerate available drives/mounts and their free space. Present the overview and let the user choose which drive(s) to scan deeper.

Scan breadth-first: top-2 directory levels first, drilling deeper only on user request. This prevents context exhaustion on large drives while surfacing the biggest consumers quickly.

Report inaccessible directories as "permission denied — skipped" rather than silently omitting them.

Cross-reference discovered directories against `shared/skills/qutilities-disk-cleanup/references/known-targets.md` to pre-classify items by category.

**Why scan before presenting**: scanning first prevents the common failure mode of deleting small caches while a 60 GB temp folder goes unnoticed. The ranked list ensures effort targets the largest consumers.

**Completion**: a ranked list of directories >500 MB exists, with cloud-synced folders flagged and known targets pre-classified.

### Step 2: Present

Show a summary table with these columns:

| Folder | Size | Category | Risk | Notes |
|--------|------|----------|------|-------|

Categories and risk levels come from the known-targets reference file. Cloud-synced folders are marked with a visible indicator (e.g., `[cloud]`). Exclude items matching the "Leave alone" category — do not present them to the user.

Sort by size descending — the user sees the largest consumers first.

**Completion**: table rendered with at least one row, every row has a Category value from the known-targets reference.

### Step 3: Interview

Walk through the table depth-first, starting with the largest and most ambiguous items. For each:
- State what it is and why it matters
- State the risk of deletion (data loss, rebuild time, service disruption)
- Ask for the user's decision

**Batch-confirm known-safe items**: present the full batch with sizes, then ask for a single confirmation. The user confirms or removes items from the batch.

The user can respond:
- **delete** — approved for removal
- **compact** — approved for compaction (vhdx, docker prune)
- **keep** — leave untouched
- **investigate** — drill deeper before deciding; after investigating, re-present the item with updated information and ask for a final decision
- **skip** — defer the decision; skipped items are excluded from execution and reported as deferred in Step 5

**Completion**: every item >500 MB has a user decision (keep/delete/compact/investigate/skip).

### Step 4: Execute

Present the full command list as a dry-run preview before executing anything. Include a prominently-placed reminder that CLI deletion bypasses Recycle Bin and is irreversible once executed. Group commands by execution tier:

1. **Caches and temp files** — lowest risk, fastest wins
2. **Known-safe build artifacts** — safe but may require rebuild on next use
3. **User-confirmed large items** — items that passed the interview
4. **Compaction operations** — vhdx/docker, run last (requires shutdown verification)

After user approves the command list, execute in tier order. The user can say "stop" or "abort" at any point during execution to halt remaining commands. Report freed space per action as a running table:

| Action | Target | Freed | Status |
|--------|--------|-------|--------|

On failure (locked file, permission denied): report which process holds the lock (use `Get-Process` / `lsof`), skip the item, continue with the next. For operations requiring elevation: report as a manual action with the exact command to copy-paste, or offer to launch an elevated process.

Re-check target size at execution time. If the actual size differs >20% from the presented size (another process may have modified it), re-confirm with the user before proceeding.

**Completion**: all approved actions attempted (or halted by user abort), per-action results reported in the running table.

### Step 5: Verify

Show a before/after free-space comparison:

| Drive | Before | After | Recovered |
|-------|--------|-------|-----------|

Note any skipped items: failures, deferred decisions, items that required elevation the user declined, items halted by user abort.

**Completion**: final free-space numbers reported, user sees the net recovery.

## Rules

- Always confirm before deleting — even known-safe items are batch-confirmed, never silently purged
- Always present a dry-run command list (with irreversibility warning) before execution; execute only after user approval
- The user can abort execution at any point — halt remaining commands immediately
- On deletion failure: report the error, identify the blocking process when possible, skip the item, continue — never force-terminate processes without explicit user instruction
- For operations requiring elevation (vhdx compaction, system file cleanup): report as a manual action with the command to copy-paste, or offer to launch an elevated process with a UAC prompt
- For vhdx compaction: verify VM/WSL is fully shut down before compacting; recommend laptop is on power; note compaction is idempotent (safe to re-run if interrupted)
- Scan breadth-first with depth limits — never recursively enumerate an entire drive in one pass
- Re-check target size at execution time; if delta >20% from presented size, re-confirm with user
- Cloud-synced folders must be detected and flagged — never offer to delete a cloud-sync root without an explicit warning that deletion may propagate to cloud storage
- When a directory is both large and ambiguous (no known-targets match), prefer "investigate" over "delete" in the recommendation
