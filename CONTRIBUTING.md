# Contributing to agent-playbook

Thanks for helping. This file says how the repo is organised, what a good change looks like and
how it gets merged. The rules agents follow when they edit this repo are in
[AGENTS.md](AGENTS.md) (project scope) and [shared/AUTHORING.md](shared/AUTHORING.md) (authoring
conventions). Read both before a non-trivial change.

## Ground rules

- **Every change is a pull request**, reviewed and approved by the maintainer
  ([CODEOWNERS](.github/CODEOWNERS)). Nothing is pushed to `main` directly.
- **Sign off every commit (DCO).** `git commit -s` adds `Signed-off-by: Your Name <you@example.com>`,
  certifying the [Developer Certificate of Origin](https://developercertificate.org/): you wrote
  the change, or have the right to submit it under the project's license (Apache-2.0). CI rejects a
  commit without a matching sign-off.
- **CI must be green.** It runs every guard and self-test on Windows and Linux, a setup dry
  run, and a scan for personal paths, emails and credentials.
- **Governance is critical code.** `shared/AGENTS.md` and the skills load into every session of every
  user. A wrong sentence there costs more than a wrong line of code, so the review bar is high and
  small, well-argued changes merge fastest.

## Repository layout

| Path | What lives there |
|---|---|
| `shared/AGENTS.md` | Cross-provider instructions, deployed to every provider. Kept lean: a size budget (`verify-mass.py`) caps it. |
| `shared/AUTHORING.md` | Authoring conventions, read on demand. |
| `shared/skills/<name>/` | Skills shared by every provider: `SKILL.md` plus auxiliary files and `scripts/`. Must stay provider-agnostic. |
| `providers/<name>/` | Provider-specific deployables: Claude Code hooks and statusline, Kiro agents, steering and overlays, reference notes. |
| `providers/kiro/skills/<name>/OVERLAY.md` | Kiro-only additions appended to a shared `SKILL.md` at deploy time (`<stem>.OVERLAY.md` for an auxiliary file). |
| `inventory.tsv` | The deployment manifest every setup and verify script reads. |
| `setup.sh` / `setup.ps1` | Twin installers. A change to one needs the same change to the other. |
| `templates/` | Starting files setup copies (empty user memory). |
| `docs/` | Architecture and glossary. |

Your own memory, plans and artifacts are never part of this repo: they live in your store repo
(`~/.agent-playbook/stores`), and the repo's `memory` is a gitignored link into it.

## Making a change

1. **Fork, clone your fork, run `./setup.sh`** (or `.\setup.ps1`). Setup puts your clone on the
   `local-improvements` branch. That is where your own sessions' improvements land (`/qconfig-sync`
   and `/qdream` never commit to `main`). For a contribution, branch from `main`:
   `git switch -c my-change origin/main`.
   On Windows, turn on `core.longpaths` before cloning (see the README quickstart).
2. **Make the change and its tests together.** A script change needs a self-test case, which can be a
   fixture under the script's `fixtures/` folder. A governance change needs every citation of what
   it renames or removes updated, and `verify-links.py` and `verify-citations.py` passing.
3. **Run the checks** (below) and fix what they report. Do not weaken a guard to make it pass.
4. **Commit with Conventional Commits and sign-off**: `git commit -s -m "fix(qplan): Keep phase IDs stable"`.
   Imperative mood, at most 50 characters in the subject; explain the *why* in the body.
5. **Open a pull request** against `main` and fill in the template.

### Running the checks

```bash
./setup.sh --dry-run --no-stores        # once, so the venv exists (or ./setup.sh)
.venv-agent-playbook/bin/python -I shared/skills/qconfig-sync/scripts/run-checks.py .
bash shared/skills/qconfig-sync/scripts/test-parity.sh
```

On Windows, use `.venv-agent-playbook\Scripts\python.exe`, and run `test-parity.sh` from **Git
Bash**: `bash` typed in PowerShell is WSL's bash, and every PowerShell parity assertion silently
skips there. Checks that need a live deployment or your memory print `SKIP`, not a failure, in a
fresh clone.

## What a good change looks like

- **Lean, harness-neutral skills.** A shared `SKILL.md` holds what a frontier model needs. A
  weaker model's extra discipline goes in a Kiro overlay. Overlays cite shared text by section
  name or stable step ID, never by step number.
- **A structure needs a consumer.** Add a section, file or field only when something reads it
  ([shared/AUTHORING.md § Structure Requires a Consumer](shared/AUTHORING.md)).
- **Contract changes are swept.** Renaming a skill's step, argument or output means finding and
  updating every file that refers to it. A citation is prose (`file § Section`) or a backticked
  repo path, so no compiler will catch the stale one.
- **Mechanical over behavioral.** Prefer a script that checks something to an instruction that asks
  the agent to remember it.
- **Canonical, not local.** Steering and governance state the setup everyone has. Never one
  machine's paths, names, employer or tools; CI's leak scan rejects home paths and emails.
- **Measured claims are dated.** A claim about a tool's behavior ("Kiro follows symlinks") names
  the version and date it was measured ([shared/AUTHORING.md § Measured Claims](shared/AUTHORING.md)).

## Provider parity

Test the providers you use; you do not need all of them. Kiro overlays, Windows-specific code and
the PowerShell twin are maintained by the maintainer when a contributor cannot test them. Say in
the pull request which providers and platforms you tested, and CI covers the rest of the
platform matrix.

## Proposing a new skill

Open a "Skill proposal" issue first. Say what the skill does, when an agent should invoke it, what
it reads and writes, and why an existing skill cannot absorb it. A skill that only reformats
advice already in `shared/AGENTS.md` will not be accepted. One with a script-checked contract is
much more likely to be.

## Code of conduct

Be kind, assume good faith, and keep discussion about the work. The maintainer moderates issues
and pull requests and may lock or close threads that do not follow this.
