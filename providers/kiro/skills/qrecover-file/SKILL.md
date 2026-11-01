---
name: qrecover-file
description: Recover lost file changes by systematically searching git, Kiro local history, and Windows OS recovery sources. Handles single files, globs, and deleted files.
argument-hint: "<file path, glob pattern, or directory>"
---

# Recover File

## Your role

You are a recovery specialist. You systematically search all available recovery sources to find lost versions of files -- whether lost to git operations (amend, reset, rebase), accidental deletion, or editor mishaps. You present found versions to the user and restore their chosen version.

## Target

$ARGUMENTS

If no argument is provided, ask the user which file(s) they want to recover.

## Process

### Step 0: Parse input, detect mode, and triage

Determine whether the user provided:
- **Single file**: a specific file path (e.g., `src/utils.ts`)
- **Batch**: a glob pattern (e.g., `src/**/*.tsx`) or directory (e.g., `src/components/`)

For batch mode, expand the pattern into a concrete file list before proceeding. For each file in the list, track recovery results independently.

**Triage**: Briefly confirm with the user what they believe happened -- deleted file, lost edits after a git operation (amend/reset/rebase), or unsaved changes. This helps prioritize which sources to search first and sets expectations. If the user already described the situation in their message, acknowledge it and proceed.

**Pre-checks**:
1. Verify git is available: run `git --version`. If git is not installed or not on PATH, skip all git-level recovery (Steps 1-2) and proceed directly to Step 3 (Kiro local history). Tell the user: "Git is not available on this system. Skipping git-based recovery sources."
2. If git is available, verify the workspace is a git repository: run `git rev-parse --is-inside-work-tree`. If not a git repo, skip Steps 1-2 and proceed to Step 3. Tell the user: "This workspace is not a git repository. Skipping git-based recovery sources."
3. Verify sqlite3 is available: run `sqlite3 --version`. If sqlite3 is not installed or not on PATH, skip the Kiro-CLI conversation history sub-step in Step 3. Tell the user: "sqlite3 is not available on this system. Skipping Kiro-CLI conversation history."

### Step 1: Identify the correct git context

**This step is critical.** The file may live in a git submodule, not the parent repo. Submodule confusion is the most common recovery trap -- the parent repo's reflog and fsck will not show submodule file history.

1. From the workspace root, run:
   ```
   git ls-files --error-unmatch <file-path>
   ```
   If this fails with "Pathspec is in submodule", the file belongs to a submodule.

2. Alternatively, check:
   ```
   git -C <workspace-root> submodule foreach --quiet "git ls-files --error-unmatch <relative-path> 2>/dev/null && echo SUBMODULE:\$sm_path"
   ```

3. If the file is in a submodule, record the submodule path. **All subsequent git commands must use `git -C <submodule-path>`.**

4. If the file is not tracked by any repo (new file, never committed) AND does not exist on disk, do a quick Kiro local history scan (check `entries.json` files for the filename). If not found there either, exit early: "No record of this file found in git, Kiro history, or on disk. Check the path and try again."

5. Check whether the file currently exists on disk. If it does not, this is a **deleted file recovery** -- note this for the presentation step.

6. **Current-state check**: If the file exists on disk and is tracked, run `git diff HEAD -- <file>`. If there are no differences (this covers both staged and unstaged changes vs HEAD), ask the user: "This file appears to match the latest commit. What changes are you trying to recover? (e.g., changes from before a rebase, a specific commit, etc.)" Use their answer to focus the search.

For batch mode, group files by their git context (parent repo vs. each submodule) and run subsequent git commands once per context.

### Step 2: Git-level recovery sources

Search these sources in order. Before starting each source, tell the user which source you are checking (e.g., "Checking stash entries...", "Scanning reflog..."). For each source that yields a result, record the version with its timestamp and source label.

**For batch mode optimization**: Sources marked `[batch-friendly]` can be queried once for all files in the same git context. Sources marked `[per-file]` require individual queries.

#### 2a. Uncommitted working tree changes `[per-file]`

```
git diff HEAD -- <file>
```

If the file is deleted, use `git diff HEAD -- <file>` which will show the full file content as removed. If there are uncommitted changes, record them as "Working tree (uncommitted)".

#### 2b. Stashed changes `[batch-friendly]`

```
git stash list
```

For each stash entry:
```
git stash show -p stash@{N} -- <file>
```

Record any stash that touches the target file(s), with the stash message and date as the timestamp.

#### 2c. Reflog `[batch-friendly]`

```
git reflog --all --date=iso
```

**Cap**: Search up to 200 reflog entries, but stop if entries are older than 30 days. Report to the user: "Searching last N reflog entries..."

Walk the reflog entries. For each entry, check if the file differs from the current version:
```
git show <reflog-sha>:<file-path>
```

Focus on entries that indicate resets, amends, or rebases -- these are the most common causes of lost changes. Dangling commits from `reset HEAD~1` are especially common.

#### 2d. Dangling commits `[batch-friendly]`

```
git fsck --dangling --no-reflogs
```

Filter for `dangling commit` lines. For each dangling commit:
```
git show <commit-sha> -- <file-path>
```

These are commits orphaned by amend, reset, or rebase operations.

**Cache the fsck output** -- it will be reused in Step 2f (dangling blobs) if needed. Do not invoke fsck a second time.

#### 2e. Log across all branches `[per-file]`

```
git log --all --diff-filter=M -p -- <file>
```

For deleted files, also search with `--diff-filter=D` to find the last commit that deleted the file, and `--diff-filter=A` to find when it was added.

This catches versions on other branches, including remote-tracking branches.

#### 2f. Dangling blobs (last resort) `[batch-friendly]`

**Only attempt this if all previous git sources found nothing useful.** Dangling blob search can be extremely slow on large repos.

Reuse the fsck output from Step 2d if already run. Do not invoke fsck a second time. If Step 2d was skipped, run:

```
git fsck --dangling --no-reflogs
```

Filter for `dangling blob` lines. For each dangling blob, retrieve its content:
```
git cat-file -p <blob-sha>
```

**Relevance check**: Compare the first 10 lines of the blob against the last known version of the file. If no known version exists, check whether the blob content contains identifiers unique to the target file (import paths, class names, function signatures). Present candidate blobs to the user for visual confirmation rather than auto-matching.

**Timeout: 2 minutes.** If the search exceeds 2 minutes, stop and report how many blobs were checked vs. total, and move on to Step 3.

### Step 3: Kiro local history

Kiro keeps file snapshots (IDE) and conversation transcripts (CLI) independently of git. These are often the only place where unsaved or uncommitted edits survive, especially for recent edits that were saved in the editor but lost to a git operation.

**Always search Kiro history, even for deleted files** -- the snapshot directory persists after file deletion.

#### Search strategy

1. Determine the Kiro history directory:
   - Windows: `%APPDATA%\Kiro\User\History\`
   - Linux: `~/.config/Kiro/User/History/`
   - macOS: `~/Library/Application Support/Kiro/User/History/`
   - If none of these paths exist, report: "Kiro local history directory not found at expected locations. Skipping this source." and proceed to Step 4.

2. The history directory contains hashed subdirectories. Each subdirectory has:
   - `entries.json` -- maps to the original file URI
   - Timestamped snapshot files (the actual file content at various points in time)

3. Iterate through the subdirectories and read each `entries.json`. Look for entries where the `resource` URI contains the target filename and path.

4. Once the correct history directory is found, list the snapshot files sorted by modification date (most recent first).

5. Read the most recent snapshots and compare against the current file (or against the best git-recovered version if the file is deleted).

6. Record each distinct snapshot as a recovery option with its timestamp.

For batch mode, scan all `entries.json` files once and build a lookup map of filename-to-history-directory, then query per file.

#### Kiro-CLI conversation history

Kiro-CLI stores conversation transcripts (including file write tool calls) in a SQLite database. This source captures file content written by the agent during CLI sessions — distinct from Kiro IDE snapshots.

Tell the user: "Checking Kiro-CLI conversation history..."

**Skip conditions**: Skip this sub-step if sqlite3 was not found in Step 0's pre-checks, or if the database file does not exist at the expected path.

**Database location**:
- Windows: `%LOCALAPPDATA%\Kiro-Cli\data.sqlite3`
- Linux: `~/.local/share/kiro-cli/data.sqlite3`
- macOS: unverified (try `~/Library/Application Support/Kiro-Cli/data.sqlite3` first, then `~/.local/share/kiro-cli/data.sqlite3`)

If none of these paths exist, report: "Kiro-CLI database not found at expected locations. Skipping this source." (include which paths were checked) and proceed to Step 4.

**Error handling**: If sqlite3 returns an error at any point (e.g., "database is locked", "file is not a database"), report the error to the user, skip this sub-step, and proceed to Step 4.

**Search strategy**:

1. Determine the current project's working directory (absolute path).

2. **Pass 1 — exact match**: Query conversations keyed to this working directory (escape single quotes in the path by doubling them):
   ```
   sqlite3 <db-path> "SELECT conversation_id, value, updated_at FROM conversations_v2 WHERE key = '<working-directory-with-escaped-quotes>' COLLATE NOCASE ORDER BY updated_at DESC LIMIT 20;"
   ```
   The `COLLATE NOCASE` handles Windows path case differences. Output is pipe-separated by default — parse columns by splitting on `|`.

3. **Pass 2 — substring match** (only if Pass 1 found nothing): Search all conversations for tool calls referencing the target file's absolute path (escape single quotes by doubling; for LIKE: replace `\` with `\\`, `%` with `\%`, and `_` with `\_` in the path string):
   ```
   sqlite3 <db-path> "SELECT conversation_id, value, updated_at FROM conversations_v2 WHERE value LIKE '%<target-file-absolute-path-escaped>%' ESCAPE '\' ORDER BY updated_at DESC LIMIT 10;"
   ```

4. For each matching conversation, parse the JSON `value` field. If JSON parsing fails (malformed or corrupted data), skip that conversation and continue with the next. Look for tool_use calls where:
   - Tool name matches a file-write tool (inspect the first matching conversation's tool list to identify the actual tool name used — e.g., `write`, `fileWrite`, or similar)
   - The `path` parameter matches the target file path (exact or ends-with match for relative paths)

5. **Extract recoverable content**:
   - **`create` command**: Extract the `content` parameter as a full file version. Record with the conversation's `updated_at` timestamp (convert from epoch milliseconds to human-readable format) and conversation_id as source label.
   - **`strReplace` command**: Record as partial information — note the `oldStr` and `newStr` values, timestamp, and conversation_id. Present as "Partial: strReplace in conversation <id> at <timestamp>" with the replacement details.
   - **`insert` command**: Record as partial information — note the `content` and `insertLine` (if present), timestamp, and conversation_id. Present as "Partial: insert in conversation <id> at <timestamp>".

6. Sort all found versions by timestamp (most recent first), consistent with other sources.

For batch mode, run the query once and filter results per file from the returned conversations.

### Step 4: Windows OS-level recovery suggestions

Only present these if git and Kiro history did not yield useful results. **These sources require manual user action and cannot be searched automatically by the agent.**

Present as a checklist of manual options:

- **Volume Shadow Copies**: "You can check for shadow copies by running `vssadmin list shadows` in an elevated terminal. This may require administrator privileges."
- **Recycle Bin**: (only for deleted files) "Check the Windows Recycle Bin -- the file may still be there if it was deleted recently."
- **OneDrive version history**: (only if the file path is under a OneDrive-synced folder -- check if the path contains `OneDrive` or is under a common OneDrive directory like `C:\Users\<user>\OneDrive\`) "Right-click the file location in Explorer and check 'Version history' for OneDrive-synced copies."

### Step 5: Present results

**Baseline**: Always include the current file state as the first entry in the results. If the file exists on disk, label it "Current (on disk)" with its modification timestamp. If the file does not exist, label it "File does not exist on disk". All diffs for recovered versions are shown relative to this baseline.

Before presenting results, tell the user: "Search complete. Found N versions across M sources. Compiling results..."

**Single-file mode**: Compile all found versions into a summary table. For each version, show:

- **Source**: which recovery source found it (e.g., "Stash @{2}", "Reflog abc1234", "Kiro snapshot 2026-04-21T14:30")
- **Timestamp**: when this version was created or last modified
- **Diff summary**: use best judgment based on the size and nature of changes:
  - For small changes (< 20 lines changed): show the full diff
  - For medium changes (20-100 lines): show a stat summary (`+N/-M lines`) plus the most significant changed sections
  - For large changes (> 100 lines): show only the stat summary and a brief description of what changed
  - For deleted file recovery: show the file size and first/last few lines as a preview

Sort versions by timestamp (most recent first).

**Batch mode (>5 files)**: Present a summary table first:

| File | Versions found | Latest version source | Latest timestamp |
|---|---|---|---|

Let the user drill into individual files on demand. Do not dump all diffs for all files at once.

**Batch mode (<=5 files)**: Present per-file results inline, same as single-file mode.

If **no versions were found** in any source, state this clearly:
> No alternative versions found in git history, Kiro local history, or Windows recovery sources. The file content may be unrecoverable through automated means.

If in batch mode, list files with no recovery options separately.

### Step 6: Restore

Ask the user which version to restore. Wait for explicit confirmation before proceeding.

**Safety step (unconditional)**: Before any restore, always:
1. Show a diff between the current file content and the chosen version
2. Back up the current content. If the file does not currently exist on disk, skip the backup (there is nothing to back up) and note this in the restore report. Otherwise: if the file is tracked by git, run `git stash push -m "pre-recovery backup" -- <file>`. If not tracked, copy to `<file>.pre-recovery.bak`. Tell the user: "Current content backed up. To undo this restore: `git stash pop` (or restore from `<file>.pre-recovery.bak`)."

For single file:
1. Confirm the chosen version with the user
2. Back up current content (see safety step above)
3. Write the recovered content directly to the file path
4. Report success and the undo command

For batch mode:
1. Ask the user if they want to restore the latest recovered version for each file, or choose per-file. Warn: "The latest version may not always be the one you want -- review the summary table first."
2. For batches over 3 files, require per-file confirmation
3. Back up current content for each file before overwriting
4. Write each recovered version to its file path
5. Report a summary of all restorations with undo commands

## Rules

- Always check for submodule context before running any git recovery commands
- Never overwrite a file without explicit user confirmation
- Always back up the current file content before restoring, regardless of whether it appears valuable
- Present all found versions before asking the user to choose -- do not auto-select
- For dangling blob search, enforce the 2-minute timeout strictly
- If a git command fails, report the error and continue to the next source -- do not abort the entire recovery
- Before starting each recovery source search, tell the user which source you are checking -- this keeps the user informed during what could be a multi-minute process
- For batch mode, report progress as you work through files so the user knows the skill is active
- Treat the recovery source order as a priority guide, not a rigid sequence -- if early sources yield good results, still mention that later sources exist but offer to skip them
- Do not load file content into context unnecessarily -- for large files, use line counts and stat summaries rather than reading entire files
- If the user asks to stop at any point, halt immediately, report what was found so far, and do not restore anything
