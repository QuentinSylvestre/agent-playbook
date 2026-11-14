# agent-playbook setup (Windows PowerShell): a thin bootstrap. Twin: setup.sh.
# It finds Python 3.8+ (py -3, then python) and runs setup\setup.py with it in isolated mode, passing
# every flag through; setup\setup.py does the work, on every platform (its docstring has the modes, the
# deploy lock and the ownership rule). With no Python 3.8+ it exits 2 and says what to install.
# Requires: Developer Mode enabled OR run as Administrator (symlinks).

param(
    [string]$Providers = "",
    [switch]$DryRun,
    [switch]$Yes,
    [string]$StoresUrl = "",
    [switch]$NoStores,
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$Help
)

if ($Help) {
    Write-Host @"
Usage: setup.ps1 [options]

Deploys agent-playbook into the AI providers you choose. Safe to re-run.

  -Providers LIST   comma-separated subset of: claude,codex,gemini,kiro (or "all").
                    Default: interactive -- the detected ones, confirmed; otherwise all.
  -DryRun           print every change instead of making it; nothing is written.
  -Yes              accept every default without asking (create a local store repo
                    when none exists, create the engine branch, back up and replace
                    a file of yours that is in the way). Your own ~\.claude\CLAUDE.md
                    or ~\.gemini\GEMINI.md is never replaced: the playbook loads beside it.
                    For Gemini CLI, setup then adds "AGENT-PLAYBOOK.md" to context.fileName
                    in ~\.gemini\settings.json, with or without -Yes; when it cannot edit
                    that file (comments in it, say), it prints the line to add by hand.
  -StoresUrl URL    clone the store repo from URL when it is missing.
  -NoStores         do not set up a store repo (memory is disabled until you do).
  -Uninstall        remove what setup deployed for the chosen providers: links into
                    this repo, the files it wrote and you did not edit (by the deploy
                    lock), the Claude Code settings entries; restore each .bak setup
                    made, and kiro-cli's default agent when setup set it.
  -Purge            with -Uninstall: also remove ~\.agent-playbook\config and the
                    repo's memory link. The store repo itself is never touched.
  -Help             this text.

Requires Python 3.8+ (py -3 or python) and git. setup\setup.py does the work.

Environment: AGENT_PLAYBOOK_STORES (store repo path), AGENT_PLAYBOOK_CONFIG (pointer
file path), AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (do not change kiro-cli's global settings).
AGENT_PLAYBOOK_TEST_VENV_DIR and AGENT_PLAYBOOK_TEST_GEMINI_HELPER are for the setup
scenario test only (the venv folder to use instead of the repo's .venv-agent-playbook,
and a script to run instead of providers/gemini/context-filename.py).
"@
    exit 0
}

# Find-Python: @(exe, pre-args) of the first working Python 3.8+, or $null. Native stderr is dropped
# (the Microsoft Store `python` alias prints there and exits non-zero), and $ErrorActionPreference is
# relaxed so Windows PowerShell 5.1 does not turn that into a terminating error.
function Find-Python {
    $check = "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 3)"
    foreach ($c in @(@('py', '-3'), @('python'))) {
        if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
        $pre = @($c | Select-Object -Skip 1)
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & $c[0] @pre -c $check 2>$null | Out-Null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
        finally { $ErrorActionPreference = $prev }
        if ($ok) { return , @($c[0], $pre) }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    $lock = Join-Path (Join-Path $env:USERPROFILE ".agent-playbook") "deploy-lock.tsv"
    [Console]::Error.WriteLine("ERROR: setup needs Python 3.8+ (tried: py -3, python) and found none.")
    [Console]::Error.WriteLine("  Install it from python.org or the Microsoft Store, then run setup.ps1 again.")
    [Console]::Error.WriteLine("  What an earlier setup deployed is listed in $lock;")
    [Console]::Error.WriteLine("  README.md (Uninstall) says how to remove it by hand.")
    exit 2
}

$pass = @()
if ($Providers) { $pass += @('--providers', $Providers) }
if ($DryRun) { $pass += '--dry-run' }
if ($Yes) { $pass += '--yes' }
if ($StoresUrl) { $pass += @('--stores-url', $StoresUrl) }
if ($NoStores) { $pass += '--no-stores' }
if ($Uninstall) { $pass += '--uninstall' }
if ($Purge) { $pass += '--purge' }

$prevName = $env:AGENT_PLAYBOOK_SETUP_NAME
$env:AGENT_PLAYBOOK_SETUP_NAME = 'setup.ps1'
$pre = @($python[1])
try {
    & $python[0] @pre -X utf8 -I (Join-Path $PSScriptRoot 'setup\setup.py') @pass
    $code = $LASTEXITCODE
} finally {
    # the variable is for this run only: never leave it in the caller's session
    $env:AGENT_PLAYBOOK_SETUP_NAME = $prevName
}
exit $code
