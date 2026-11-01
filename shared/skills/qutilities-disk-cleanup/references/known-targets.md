# Known Cleanup Targets

Reference file for `/qutilities-disk-cleanup`. Cross-referenced during Step 2 to pre-classify discovered directories.

## Safe to delete

Items that rebuild automatically on next use — no data loss from removal.

| Target | Typical location | Why safe | Cleanup command |
|--------|-----------------|----------|-----------------|
| pip cache | **Win**: `%LOCALAPPDATA%\pip\Cache` | Downloaded wheel/sdist archives; pip re-downloads on next install | **Win**: `pip cache purge` **Lin/Mac**: `pip cache purge` |
| npm cache | **Win**: `%APPDATA%\npm-cache` **Lin/Mac**: `~/.npm` | Package tarballs; npm re-downloads as needed | `npm cache clean --force` |
| PyCharm/JetBrains caches | **Win**: `%LOCALAPPDATA%\JetBrains\<product>\caches` **Lin/Mac**: `~/.cache/JetBrains/` | Index caches; IDE rebuilds on next open | Delete the `caches/` subdirectory per product |
| SquirrelTemp | **Win**: `%LOCALAPPDATA%\SquirrelTemp` | Installer staging for Electron apps; safe after install completes | **Win**: `Remove-Item -Recurse -Force "$env:LOCALAPPDATA\SquirrelTemp"` |
| Kiro installer MSIs in Temp | **Win**: `%TEMP%\kiro-*.msi` | Old installer packages left after update | **Win**: `Remove-Item "$env:TEMP\kiro-*.msi"` |
| Stale temp files (>7 days) | **Win**: `%TEMP%` **Lin/Mac**: `/tmp` | Old temp files no process still holds | **Win**: `Get-ChildItem $env:TEMP -Recurse \| Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } \| Remove-Item -Recurse -Force -ErrorAction SilentlyContinue` **Lin/Mac**: `find /tmp -mtime +7 -delete 2>/dev/null` |
| `__pycache__` directories | Any Python project | Bytecode cache; Python regenerates on next import | **Win**: `Get-ChildItem -Recurse -Directory -Filter __pycache__ \| Remove-Item -Recurse -Force` **Lin/Mac**: `find . -type d -name __pycache__ -exec rm -rf {} +` |
| NuGet cache | **Win**: `%USERPROFILE%\.nuget\packages` | Package cache; restores from feeds on next build | `dotnet nuget locals all --clear` |
| Gradle cache | **Win**: `%USERPROFILE%\.gradle\caches` **Lin/Mac**: `~/.gradle/caches` | Build cache; Gradle re-downloads dependencies | Delete `caches/` subdirectory |

## Compactable

Items that can be shrunk without deleting content. Requires the associated service to be fully shut down.

| Target | Typical location | Why compactable | Prerequisites | Cleanup command |
|--------|-----------------|-----------------|---------------|-----------------|
| WSL vhdx | **Win**: `%LOCALAPPDATA%\Packages\CanonicalGroupLimited.*\LocalState\ext4.vhdx` | WSL allocates disk space but never releases it; compaction reclaims unused internal space | `wsl --shutdown` (wait 10s); laptop on power recommended | **Win**: `Optimize-VHD -Path "<path>" -Mode Full` (requires Hyper-V module + elevation) or `diskpart` method: `select vdisk file="<path>"` → `compact vdisk` |
| Docker vhdx | **Win**: `%LOCALAPPDATA%\Docker\wsl\data\ext4.vhdx` | Same as WSL — Docker Desktop's VM disk grows but doesn't shrink | Docker Desktop fully quit (not just stopped); `wsl --shutdown` | Same as WSL vhdx compaction |
| Docker unused images/volumes | All platforms | Dangling images, stopped containers, unused volumes accumulate | Docker daemon running | `docker system prune -a --volumes` (interactive confirmation built-in) |

## Confirm before deleting

Items where deletion is safe in context but the user should confirm because of potential rebuild cost or data loss.

| Target | Typical location | Risk of deletion | Cleanup command |
|--------|-----------------|------------------|-----------------|
| Claude Desktop vm_bundles | **Win**: `%APPDATA%\Claude\vm_bundles` | Large runtime bundles; Claude Desktop re-downloads but may delay next launch | **Win**: `Remove-Item -Recurse -Force "$env:APPDATA\Claude\vm_bundles"` |
| Rust `target/` directories | Any Rust project root | Full rebuild required (~5-30 min depending on project); safe if not actively iterating | **Win/Lin/Mac**: `cargo clean` in the project, or `Remove-Item -Recurse target/` |
| Python `.venv` directories | Any Python project root | Virtual env must be recreated (`python -m venv .venv` + `pip install`); no source code lost | Delete the `.venv` directory |
| Build/dist output | `build/`, `dist/`, `out/` in project roots | Must re-build; safe if not about to deploy | Delete the directory |
| Large log files | `*.log` files >100 MB anywhere | May contain diagnostic info; truncate or archive before delete | Inspect first; `Remove-Item` or `truncate -s 0` |
| Node modules | `node_modules/` in JS projects | `npm install` / `pnpm install` restores; safe if `package-lock.json` exists | Delete `node_modules/`; restore with `npm ci` |
| Conda environments | **Win**: `%USERPROFILE%\miniconda3\envs\*` **Lin/Mac**: `~/miniconda3/envs/*` | Named environments; must recreate from `environment.yml` if one exists | `conda env remove -n <name>` |
| Old Kiro session data | **Win**: `%USERPROFILE%\.kiro\sessions\cli\` (files older than 30 days) | Historical conversation data; non-recoverable once deleted | Selective deletion of `.jsonl`/`.json` pairs by date |

## Leave alone

Items the skill must never suggest deleting, even if large.

| Target | Why it must stay |
|--------|-----------------|
| `.git/` in tracked repos | Repository history; deletion destroys version control |
| OneDrive/SharePoint cloud-only placeholders | Files exist only as pointers; deletion propagates to cloud and removes the file for all synced users |
| Windows system directories (`C:\Windows\`, `C:\Windows\WinSxS`) | OS integrity; corruption risk even with elevation |
| Program Files / Program Files (x86) | Installed applications; use proper uninstaller instead |
| User Documents / Desktop (unless user-confirmed) | Personal files; never assume deletable |
| Active database files (`.sqlite`, `.db` in running apps) | Data corruption risk if deleted while in use |
| SSH keys / GPG keys (`~/.ssh/`, `~/.gnupg/`) | Cryptographic material; loss means access loss |
