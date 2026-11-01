## Symlink and Folder-Structure Investigation (2026-08)

> **Reference only — not deployed.** Method, matrices and open gaps from probing whether Kiro IDE
> and kiro-cli follow symlinks or accept nested skill/steering directories. It loads on demand only
> — not in `inventory.tsv`, so it never reaches a session's context. **Read when** re-probing
> whether Kiro IDE or kiro-cli follow symlinks or accept nested skill directories (method,
> matrices, open gaps). Indexed from `memory/topics/kiro-cli.md`.

The current conclusions live in `providers/kiro/steering/kiro-guidelines.md § Symlinks and Folder
Structure in `.kiro/``. This file is the measurement behind them. v2-only findings (nested-skill
config limits, the retired `v2-only/` steering split) are dropped — v2 is retired.

**Measured 2026-08-17, Windows**, on `kiro-cli-chat 2.18.1` (v3) and Kiro IDE `1.0.309`. Evidence: `/context show` on the CLI — the mechanical record of what was injected — and the Agent Steering & Skills panel in the IDE. Every link was created with PowerShell `New-Item -ItemType SymbolicLink` and its `LinkType` asserted before any run; **Git Bash `ln -s` writes a plain copy on this machine**, and a copy passes every check a link would.

### Symlinks

`Yes` / `No` are measured; `Untested` is exactly that. **Project** = `<workspace>/.kiro/`, **user** = `~/.kiro/`.

| Shape | Tier | v3 | IDE |
|---|---|---|---|
| steering file is a symlink | project | Yes | **Yes** |
| steering file is a symlink | user | Yes | **Yes** |
| `SKILL.md` is a symlink inside a real skill dir | project | Yes | **Yes** |
| `SKILL.md` is a symlink inside a real skill dir | user | Yes | **Yes** |
| the skill **directory** is a symlink | project | Yes | **Yes** |
| the skill **directory** is a symlink | user | Yes | **Yes** |
| link target path contains spaces | both | Yes | Yes |
| the whole **container** is a symlink (skills and steering) | project | **Yes** | **Yes** |
| the whole **container** is a symlink (skills and steering) | user | **Yes** | **Yes** |

**Every surface follows every symlink shape tested, at both tiers.** The 2026-04-02 finding — symlinked steering and skills silently invisible in the IDE's panel — **does not reproduce**. That finding is the stated reason `setup.ps1` copies; the rationale is stale even though the deployment is unchanged. No migration was performed and none is proposed here.

> **The user-tier container row was measured by the LITERAL swap**, user-run 2026-08-17: `~/.kiro/skills` and `~/.kiro/steering` were each renamed aside and a symlink created at the original name pointing at the renamed directory, so content stayed reachable throughout. All 27 skills and every steering file loaded on v3 and the IDE; the swap was then reversed and `LinkType` re-checked empty. **One attribution caveat**: the IDE check was run with the *home directory* as the workspace, so `<workspace>/.kiro` and `~/.kiro` were the same directory and the tier cannot be told apart from the output. Container *traversal* is unambiguous either way — those files existed only behind the link. The v3 run is clean on tier too: it listed the skills under the absolute user-tier path form.

> **IDE injection is CONFIRMED, not just discovery.** Asked neutrally to list marker words of the form `word-1234`, the IDE returned `usubstr-2008` (a user-tier steering subfolder), `ccontstr-2006` (a steering file behind a **symlinked container**) and `ccontskl-2005` (a skill description behind a symlinked container), attributing each to the rule or skill it came from. It listed only the markers reachable from the loaded paths and none of the others on disk, which is what context-based recall looks like rather than a filesystem scan. Minor caveat: the reply showed one collapsed tool call, so a read cannot be fully excluded; the selective marker set is the reason this is recorded as confirmed anyway.

### Folder structure: flat is mandatory for the IDE

`skills/<category>/<name>/SKILL.md` versus flat `skills/<name>/SKILL.md`, and nested steering subfolders:

This table is **capability**, not as-shipped behaviour. Cells marked † need a one-line glob change first, and behave as No until it is made.

| Layout | Tier | v3 | IDE |
|---|---|---|---|
| flat skill (control) | both | Yes | Yes |
| **nested** skill, all-real dirs | both | Yes | **No** |
| nested skill, real category + **symlinked skill dir** | user | Yes | No |
| nested skill, **symlinked category** dir | user | Yes † | No |
| steering **subfolder** | project | Yes | Yes |
| steering **subfolder** | user | Yes † | Yes |

**Reaching each †**, each verified with a throwaway probe agent:

- **v3 nested under a symlinked category** — add `skill://~/.kiro/skills/*/*/SKILL.md`.
- **v3 user-tier steering subfolder** — in `kiro_default.md`, `file://~/.kiro/steering/*.md` → `**/*.md`. (`kiro_default.md` currently declares only the non-recursive form; nothing is nested under `~/.kiro/steering/` as deployed today, so this cell is untested capability, not a live gap.)

Two consequences:

- **A user-tier steering subfolder is invisible to v3 as shipped, and one glob fixes it.** `kiro_default.md` declares `file://~/.kiro/steering/*.md`, non-recursive. A probe agent declaring `file://~/.kiro/steering/**/*.md` loaded the subfolder, so the fix is proven if it's ever needed.
- **The IDE rejects nested skills at both tiers and no setting can change it — confirmed from IDE source.** `resources/app/extensions/kiro.kiro-agent/dist/extension.js` implements `scanSkillsDirectory` as a single flat `readdir` that joins `<entry>/SKILL.md` directly: no recursion, no depth parameter, no config hook. Its sibling `scanSteeringDirectory` calls `findMarkdownFilesRecursively`, which is exactly why steering subfolders work in the IDE and nested skills do not. The same loop's `if (!e.isDirectory() && !e.isSymbolicLink()) continue` is source-level confirmation of the symlink results above. **Keep every skill the IDE must see at flat `skills/<name>/SKILL.md`** — changing this needs a change by Kiro.

### One `**` expansion quirk on v3

**v3's `**` will not descend *past* a symlinked directory into a further subdirectory.** The rule is about position, not depth:

| Layout | v3 `**/SKILL.md` |
|---|---|
| `link/SKILL.md` — symlink is the terminal dir | matches |
| `real/link/SKILL.md` — symlink is the terminal dir, at depth 2 | matches |
| `link/real/SKILL.md` — symlink must be traversed to reach a further dir | **does not match** |

So a symlinked directory may *hold* the `SKILL.md`, at any depth; it may not sit *between* the root and a deeper directory.

**Confirmed by a controlled A/B, 2026-08-17.** Two v3 agents, identical in every respect — same workspace, same steering resource — differing only in the single skill pattern:

| Agent | Sole skill pattern | `flat/` | `real/nested/` | `link/nested/` |
|---|---|---|---|---|
| `zzA` | `.kiro/skills/**/SKILL.md` | found | found | **missed** |
| `zzB` | `.kiro/skills/*/*/SKILL.md` | found | found | **found** |

One variable, opposite results: it is a `**` expansion limit and an explicit two-level pattern beats it. The path-form confounder was separately ruled out.

**Declare both patterns, not `*/*/` alone.** In these runs `*/*/SKILL.md` also matched the one-level `flat/SKILL.md`, behaving as a superset of `**` rather than a strict two-level pattern — but that is one observation per version, not a studied result.

### Method notes for anyone re-running this

- **Probe the `description`, not the body.** A `SKILL.md` reaches context as its frontmatter `description` only; the body is not injected until the skill is invoked. An early attempt got a body sentinel back — from an `fs_read` **tool call**, not the loader. With tools denied, no body was visible at all.
- **Never ask a session whether symlinks are supported.** This file's conclusions are loaded in every session, so the answer would be a recitation. Ask only for nonsense sentinels.
- Always run a **positive control** (a real directory holding a real file) in the same pass, so a negative is attributable.
- **v3 cannot be automated.** `kiro-cli chat --v3 --no-interactive` hangs with no output — measured twice, with a slash command and with a plain prose prompt. Drive v3 interactively (`kiro-cli --v3`) and read `/context show`. Note also that `kiro-cli --v3 chat …` silently runs **v2**; the flag must follow the subcommand.
- **`kiro-cli` has two slash-command layers; never generalise one to the other.** In the interactive TUI, skills are slash commands — typing `/q` autocompletes `/qplan`, `/qreview` and the rest with their descriptions. Under `--no-interactive` the parser knows only built-in subcommands, and `/<skill-name>` errors with `unrecognized subcommand`. A probe that invokes a skill therefore has to run interactively, or not use the slash form at all.
- Use a **throwaway probe agent** rather than editing `kiro_default`. A workspace `.kiro/agents/<name>.md` declaring only the patterns under test isolates a glob question cleanly. Assert the agent took — the header must name it — because an unknown agent name falls back to `kiro_default` in silence.

### Open gaps

Every symlink cell is measured; the `**` limit is settled by a controlled A/B; and the IDE nesting question is closed from source — `scanSkillsDirectory` is a flat, non-recursive, non-configurable `readdir`, so **no setting exists**. Nothing is open.

Two things are deliberately **not claimed** rather than unknown: `#[[file:…]]` behaviour inside the Kiro IDE at runtime (no live IDE probe was run, though its source contains no parser; steering-file transclusion is separately settled), and whether `*/*/SKILL.md` is genuinely a superset of `**` (one observation per version, not studied).

**`#[[file:…]]` transclusion is re-verified dead on 2.18.1 — measured 2026-08-17, with a control.** A workspace steering file carried its own marker plus `#[[file:sentinel.md]]`; with tools denied, v3 returned the steering file's own marker and every skill-description marker, and **not** the sentinel. The control is what makes it conclusive: the steering file demonstrably loaded and the transcluded phrase still never arrived. The v3 session adds two internal checks — its marker list matched its own `/context show` exactly, omitting the one skill its glob had not loaded, and its only tool call was the session-title hook rather than a read of the sentinel. Source agrees across both surfaces: KAS 2.18.1 carries 3 occurrences, all system-prompt prose; the IDE extension carries 3 prose plus `buildFileReference()`, which *generates* the syntax for editor actions. No regex matching `[[file` and no parse or resolve function exists in any bundle. **The IDE emits this syntax but nothing found parses it** — emitting is not resolving.

**Re-verify when** kiro-cli changes minor version, or the Kiro IDE updates.
