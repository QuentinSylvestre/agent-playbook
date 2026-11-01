## PowerShell Syntax & Anti-Patterns

Reference for Kiro CLI agents executing shell commands on Windows.

> **Also read `memory/topics/powershell.md` in the config repo** before debugging a PowerShell script
> that behaves strangely rather than failing outright. This file covers syntax and anti-patterns;
> that one records measured runtime surprises — a type coercion and an output-capture trap that both
> produce wrong answers silently, with no error to notice.
>
> The pointer sits here rather than only in user memory's `## Topics` index because this file is what
> an agent is already reading when that knowledge becomes relevant. An index consulted at session
> start is a reminder the agent has to act on unprompted, later, about a task it did not yet have.

### Syntax

- Variables use `$` prefix: `$myVar = "value"`
- Escape character is backtick (`` ` ``), not backslash
- String interpolation: `"Hello $name"` or `"Hello $($obj.Property)"`
- Cmdlets use Verb-Noun naming: `Get-ChildItem`, `Set-Location`, `New-Item`
- Pipe operator passes objects, not text — use `Select-Object`, `Where-Object`, `ForEach-Object`
- Registry access: `HKLM:\SOFTWARE\...`, `HKCU:\...` (NOT raw `HKEY_LOCAL_MACHINE\...`)
- Environment variables: read `$env:NAME`, set `$env:NAME = "value"` (NOT `Set-Variable`, NOT bash `export`)
- Call operator for paths with spaces: `& "C:\Program Files\App\app.exe" arg1 arg2`
- Here-strings: use `@'...'@` (literal) over `@"..."@` (interpolated) unless you need variable expansion. The closing `'@` MUST be at column 0 — no indentation, no trailing content on that line. This is the #1 agent parse error with here-strings.
- Stop-parsing token for passthrough args: `git log --% --format=%H`

### File-based scripts for anything non-trivial

For any non-trivial script — multi-line, embedded quotes, non-ASCII characters (accents), or output expected to exceed ~20 lines — write the script to a file and execute the file, redirecting output to a file, then read the output file. Do not iterate on inline one-liners: output truncation, missing flush, encoding corruption, and quote mangling are known inline failure modes, not fixed by retrying variants.

### Unix Equivalents

| Unix | PowerShell |
|---|---|
| `head -n N` / `tail -n N` | `Get-Content file -TotalCount N` / `-Tail N`; piped: `Select-Object -First N` / `-Last N` |
| `which name` | `(Get-Command name).Source` |
| `touch file` | `if (-not (Test-Path file)) { New-Item -ItemType File file }` (never `-Force` on files) |
| `wc -l file` | `(Get-Content file \| Measure-Object -Line).Lines` |
| `mkdir -p path` | `New-Item -ItemType Directory -Force path` |
| `rm -rf path` | `Remove-Item -Recurse -Force path` |
| `ln -s target link` | `New-Item -ItemType SymbolicLink -Path link -Target target` (may need admin on PS 5.1) |
| `chmod` / `chown` | N/A on Windows; use `icacls` only if ACL changes required |
| `2>/dev/null` | `2>$null` |
| `VAR=x cmd` | `$env:VAR = 'x'; cmd` (PS has no inline env-var prefix) |
| `grep pattern` | `Select-String -Pattern pattern` |
| `cat file` | `Get-Content file` |
| `echo text` | `Write-Output text` |
| `diff a b` | `Compare-Object (Get-Content a) (Get-Content b)` |
| `basename path` | `Split-Path path -Leaf` |
| `dirname path` | `Split-Path path -Parent` |

### Dangerous Gotchas

- `New-Item -ItemType File -Force` destroys and recreates existing files as empty. `-ItemType Directory -Force` is safe (creates parents, no-ops on existing). Prefer `Set-Content`/`Out-File` for writing file content.
- `-ErrorAction SilentlyContinue` suppresses error output but the cmdlet failure still sets `$?` to `$false` and the error record persists in `$Error`. For truly non-fatal: `try { Cmdlet -ErrorAction Stop } catch {}` (without `-ErrorAction Stop`, non-terminating errors skip the `catch`).
- `$ErrorActionPreference = 'Stop'` does NOT control native .exe exit codes — check `$LASTEXITCODE`. Stderr from native commands (git, python) CAN trigger terminating errors under strict mode. Temporarily set `$ErrorActionPreference = 'Continue'` around native calls and check `$LASTEXITCODE` manually. Alternative: wrap single native calls in `try { & git ... 2>$null } catch {}` when you only care about output/exit code.
- `ConvertFrom-Json` (PS 5.1) parses all depths but resulting PSCustomObjects may lose fidelity at deep nesting. `ConvertTo-Json` (PS 5.1) silently truncates output at depth 2 — always pass `-Depth 32` minimum. Round-trip danger: read deep JSON → modify → write back → truncated. For deep JSON on PS 5.1, use Python or raw string manipulation.
- Before creating files/dirs via shell, verify parent exists with `Test-Path`.

### Command Chaining

- In shell tool calls, prefer `;` over newlines for clarity (`;` runs sequentially regardless of prior failures)
- Use the shell tool's `working_dir` parameter instead of prefixing with `Set-Location` or `cd`. In `.ps1` scripts, `Push-Location`/`Pop-Location` is acceptable when multiple commands need the same working directory.
- Do NOT use `&&` or `||` — these are PS 7-only (unavailable on PS 5.1)

### Interactive/Blocking Commands

The shell tool runs with `-NonInteractive`. These will hang:

- NEVER use `Read-Host`, `Get-Credential`, `Out-GridView`, `$Host.UI.PromptForChoice`, or `pause`
- Destructive cmdlets (`Remove-Item`, `Stop-Process`, `Clear-Content`) may prompt for confirmation. Add `-Confirm:$false` to proceed. Use `-Force` for read-only/hidden items.

### Sleep Anti-Patterns

- Don't sleep between commands that can run immediately — just run them
- Don't retry failing commands in a sleep loop — diagnose the root cause
- If polling an external process, use a check command rather than sleeping first
- Keep necessary sleeps short (≤3s for process startup warmup only)

### PS 5.1 Compatibility

Assume PS 5.1 unless confirmed otherwise:

- No `&&`/`||` operators (use `;` or separate statements)
- No `-Depth` parameter on `ConvertTo-Json` (defaults to depth 2); `ConvertFrom-Json` has no depth limit but parsed objects lose fidelity
- `New-Item -ItemType SymbolicLink` may require admin (prefer `Copy-Item` or `cmd /c mklink` fallback)
- Verify with `$PSVersionTable.PSVersion.Major` when PS 7 features are needed
