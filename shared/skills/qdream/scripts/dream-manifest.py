#!/usr/bin/env python3
"""dream-manifest.py -- /qdream session selection, transcript stripping and
the sweep-due signal.

Subcommands:
  manifest --state <file> --repo <config repo> [--claude-home <dir>]
           [--kiro-home <dir>] [--add <path>]... [--full <path>]...
           [--exclude-session <id>]...
      Discovers projects (Methods A, B, C of the qdream skill's [ORI-DISCOVER],
      plus --add and the state file's own projects), selects every session
      with activity after its project's baseline (per-record timestamps,
      never file mtime), writes one decoded, stripped transcript per selected
      session, the index manifest.json and its side files into the work
      folder, and prints one line per project and the totals.
      Baselines: a project in the state file -> its own last_analyzed. A
      project absent from it -> the state's last_run: its sessions entirely
      before that are not read, only counted (older_sessions_not_read) -- a
      project named only by history.jsonl prompts that all predate last_run
      is still listed, with those sessions counted. --full <path>
      (repeatable) reads that project's whole history. No state file (first
      run) or no valid last_run -> the config repo's last commit time for
      every project absent from the state; when that time cannot be read
      (git fails), those projects are read in full (baseline_rule `full`,
      plus an errors[] line).
      A Kiro session whose session.json names a rootConversationId other than
      its own id is a sub-agent or workflow node, not a user session: it is
      skipped (not listed, counted or dispatched; its parent is read).
      A path inside `<project>/.claude/worktrees/` (a Claude Code sub-agent
      worktree copy) is not a project: its sessions and history attribute
      to `<project>`, its state entry is ignored, and the top-level errors[]
      names each copy.
      manifest.json is a compact index the orchestrator reads whole: per
      project status, discovered_by, subdirectory_of, baseline_rule,
      older_sessions_not_read, empty_sessions (Kiro session folders without
      messages.jsonl and without activity -- not errors), counts, sessions
      (each with first_activity: its earliest record time, or null),
      fork_collapsed (Claude fork duplicates not listed), errors, due,
      memory_file, `detail` (the side file projects/<hash>.json)
      and, when the state file names the project under a key that differs
      from the reported one (e.g. drive-letter case), `state_key`: that
      verbatim key, which [APP-STATE] stamps instead of adding a second key.
      A project whose memory directory is shared with other projects (two
      checkouts of one remote, a folder and its repo's toplevel: the store
      resolver maps them to one directory) is one store unit: the leader
      (the first member by path that is not removed) builds the memory
      entries, the plans and the Task 4 classification once; the other
      members carry their own sessions and last_analyzed only, with
      memory_file null. The manifest has no field naming the unit: no
      script or prose reads one, so none is emitted.
      A store no known checkout serves (no session, state key or `local`
      STORE identity names a folder for it) is a project of its own, keyed
      `store:<STORE identity>` (for example `store:remote example.com/org/proj`;
      `<identity> path <subpath>` for a monorepo store). The key is a
      store, never a path: no folder is probed for it, it has no sessions,
      and its memory file is the store's. A state file that holds such a
      key while no store directory is attached to it this run keeps the
      entry as `known` with the reason in errors[] when the store repo
      cannot be read, when its store directory exists but its STORE file is
      invalid, or when a checkout now serves the store and has no state
      entry of its own. It reports it `removed` when the store directory is
      gone from a readable store repo, or when the serving checkout has its
      own state entry (errors[] says "superseded by <checkout>"; the
      user acknowledges the removal in the sweep). The manifest has no
      other status values.
      A store repo that exists but cannot be scanned (an unreadable STORE
      file among the stores) is named once in the top-level errors[]; no
      project memory or plans are read from it, and no store-only project
      is listed.
      A project with a memory_file also carries the quiet-project cadence
      (sweep-orient.md [ORI-DISPATCH]): quiet_sweeps -- the state's quiet_sweeps.projects value
      under that key (keys compared normalized, as for projects), or when
      absent the seed int(sha256(key)[:8 hex], 16) % 5 of the verbatim key
      (state_key, else the reported key); memory_flags -- the entry flags
      raised in its memory file (ENTRY_FLAGS); and memory_pass --
      `flagged` when an entry has stale_after_passed,
      governance_conflict_open or stale_when_fired (TRIGGER_FLAGS; every
      other flag is an input for a dispatched agent, not a trigger), else
      `periodic` when quiet_sweeps >= 4, else null. The index's user_memory
      block carries the same three fields for the user memory as a whole
      (key "user memory", value quiet_sweeps.user_memory) plus file_flags:
      each user memory file with any flag -> its flags, and file_suspects:
      each user memory file -> its suspect count. counts.suspects (per
      project, and for user memory) counts the entries whose `suspect` is
      true: any flag but governance_conflict_open and stale_when_unknown
      (memory-rules.md § Suspect memory entries; an unreadable version
      condition counts as not fired, user decision 2026-10-06).
      Anchor and version flags, read-only: cited_path_changed lists files
      cited on the entry's `**Source**:` line (its anchor; a path named only
      in Why or How to apply is not checked) that a git repository tracks
      and whose last commit day is after the
      entry's Verified day (one `git log --name-only` per repository from
      the file's oldest Verified day; a same-day change is not seen; a plan
      present only through its archive is not looked up); cited_commit_missing
      lists backticked 7-40 lowercase hex tokens with a letter that no known
      repository holds as a commit; a `**Stale-when**: <tool> version >
      <x.y[.z]>` line sets stale_when_fired when the tool's version is later
      at the precision written, or stale_when_unknown when the tool is not
      in STALE_WHEN_TOOLS or its version cannot be read. Versions come from
      session records (claude-code: the last `version` in the newest
      projects/*/*.jsonl) or the harness log (kiro-cli: the adjacent
      `"origin":"KIRO_CLI","version":"x.y.z"` pair in the newest
      ~/.kiro/logs/*/kiro.log that holds one), never from running the
      tool. Any other `Stale-when` line is never a flag; one that holds
      `version` and `>` but misses the form is named in errors[]. The
      anchor lookups fail open, each named once in the top-level errors[]
      and never failing the run: a Verified value that is not a real day
      (that entry's paths are not checked), a folder git cannot read, a
      shallow clone, a failed `git log` or `cat-file` (that repository is
      skipped), and no complete repository answering `cat-file` (no commit
      is reported missing; a shallow clone can show a commit present, never
      absent). A stored value that is not a non-negative integer,
      or a quiet_sweeps / quiet_sweeps.projects that is not an object, is
      named in errors[] and seeded.
      A cited path counts as present when it resolves under the memory
      file's own folder, the project root or its workspace store; the config
      repo is tried only when none of those holds the path's first
      component; a first component naming a known project's folder resolves
      in that project; an absolute path is checked only inside a known
      project; a missing plans/<name>.md is present when that plans/done/
      holds <name> or the same title under another date prefix. A plan slug
      counts as present when any known project's plans/ (done/ included),
      a workspace store's plans/ or the config repo's plans/ holds it.
      The side file holds the project's entries (each with its flags,
      `suspect`, and governance_conflict_open: the non-terminal Governance-conflict states
      -- rule-update-pending, deferred -- recorded on it), plans,
      older_sessions (id, provider, kind, last_activity of each session not
      read -- what a --full recovery would add) and empty_session_ids;
      the user memory is in user_memory.json, and Kiro empty sessions naming
      no workspace in unattributed.json. A Kiro session folder without
      messages.jsonl whose session.json shows activity (lastModifiedAt more
      than 60 s after createdAt) is an error, not an empty session.
      new_plans excerpts: at most 40 decisions rows and 60 review_log lines,
      each item at most 400 characters; `truncated` is false, or
      {decisions: {kept, total}, review_log: {kept, total}, items_shortened}.
      Each new plan also carries memory_relied_on, its header's `> **Memory
      relied on**:` line (the Usage feeder; case-sensitive label, first
      line wins): null when the header has no such line, [] for `none`
      (also `none.` or `none` in backticks), else the ` | `-separated
      headings (a ` | ` inside a backticked span, single or double, does not separate; a
      heading that is itself `none` is dropped) -- at most 20, each at
      most 200 characters;
      memory_relied_on_truncated is false, or {kept, total, items_shortened,
      shortened: indexes of the cut headings}.
      Recent intents are capped at 400 characters. plans.recent and
      plans.accept_and_note are present whenever the archive is found,
      whether or not any plan is new. A manifest.json over
      200 KB prints a warning line.
  count    same options as manifest; writes nothing and prints two lines:
           "sweep due: yes|no (N new sessions, K projects near deletion)" (N
           leaves out history_only stubs and scratchpad pseudo-projects) and
           "memory budget: <words>/<pin>" (plus " OVER" when over): the words
           of <repo>/memory/MEMORY.md + HIGHER_ORDER.md, counted by
           qmemory-eval.py, against MEMORY_BUDGET_WORDS. Warn-only.
  clean    deletes the work folder, and only it.
  baseline --session <transcript.jsonl> [--until <record uuid or ISO timestamp>] [--by-role]
      Token totals of one Claude Code session (read-only): sums
      message.usage once per message.id -- Claude Code 2.1.281 repeats a
      message's usage on every content-block record -- across the session
      file and <session>/subagents/*.jsonl, keeping the largest value of
      each field seen for an id. Prints the fields used, per-field totals,
      a `tokens:` total, per-model totals and the sub-agent transcript
      count. Exit 4 when no usage record is found (Kiro records none).
      A message that called the advisor holds one model call per entry of
      message.usage.iterations: the top-level fields sum its `message`
      iterations, and its `advisor_message` iterations (the advisor's own
      calls) are added as `advisor_tokens`, counted in `tokens:`, under the
      advisor's model and under the role of the file that called it.
      --until sums the session file only up to and including that record
      (a record uuid; or an ISO timestamp: the last record, in file order,
      not time order, dated at or before it -- every line up to it counts)
      and includes a sub-agent transcript, whole, only if its earliest
      record time is at or before the cutoff time (the cutoff record's
      timestamp, else the latest earlier one); a sub-agent file without
      records counts as an agent with 0 tokens, and one whose records are
      all undated is left out and named on an `error:` line. An `until:`
      line reports the cut. An unknown uuid is a usage error (exit 2),
      never a full sum.
      --by-role adds, after the usual lines, one `role <name>: files N,
      tokens: T` line for each of orchestrator, task4, verifier, drafter,
      other, then one `peak context <name>: P` line per role: the largest
      input_tokens + cache_creation_input_tokens + cache_read_input_tokens
      of one model call among that role's files -- the largest `message`
      iteration of a message that has iterations, never their sum (output
      tokens left out; 0 for a role with no message), the session file included
      under orchestrator. Then `peak context orchestrator (session): P`
      for the session file alone, and one `peak context <role> <agent-file
      name>: P` line per sub-agent file of the orchestrator role (phase
      agents) and of the drafter role, the largest first and at most 8 per
      role; more are summed on one `peak context <role> (more): N agent(s)
      not listed, largest P` line. A message.id seen in two files is
      attributed to the first file read, as for tokens. When the session
      file is unreadable, the session line reads `n/a (session transcript
      unreadable)` (a number, even 0, would pass for a measured peak) and
      the rest is printed from the sub-agent files. The session file is
      `orchestrator`; a sub-agent file's role comes from its first user
      record's text. The explicit markers are tested first, in this order:
      `Dream Phase Agent Brief` -> orchestrator (a phase agent's cost is
      the orchestrator's), `Dream Drafter Brief` -> drafter, `Dream
      Verifier Brief` -> verifier, `Dream Sub-agent Brief` -> task4; that
      order is applied to the first non-blank line; the whole text is then
      tested for the verifier and task4 markers only, in that order (a
      phase or drafter marker below the first line is a mention). First
      match wins. Only when no marker matches does the
      fallback for older transcripts run: `Cross-validation` or `verifier`
      -> verifier, else other. A message.id is counted once, under the
      role of the file it is first seen in, so the role totals add up to
      `tokens:`. Each `other` file gets an `other:` line with its name and
      the first 80 characters of that text, `(first user record has no
      text)` when that record holds no text, or `(no user record)` when the
      file has none. A file without records is 0 tokens. An unreadable
      sub-agent file is named on an `error:` line and gets no role; without
      --until it still counts in `agents:`, so the role file counts can sum
      to fewer than `agents:` + 1.
  context [--session <transcript.jsonl>] [--marker <text>] [--limit <tokens> | --orchestrator]
      The context of one Claude Code transcript's last model call (read-only),
      measured as `baseline`'s peak is (largest `message` iteration).
      Without --session, the transcript of CLAUDE_CODE_SESSION_ID under
      ~/.claude/projects/*/ (inside a sub-agent the variable names the parent
      session). --marker picks instead the file of <session>/subagents/
      whose first user record contains that text: a phase agent passes its own
      brief path, which only its prompt holds; zero matches is a usage error.
      Several matches (a second sweep in one session re-uses brief names)
      take the file whose first record is the latest, the older ones having
      ended, and a `note:` line names how many matched; matches whose latest
      first-record time is undated or tied are a usage error. Prints `context: <path>`, `context: N tokens at the last
      model call (<timestamp>)` and `over limit: yes|no (limit L)`, L being
      --limit, ORCHESTRATOR_CONTEXT_LIMIT (--orchestrator, the orchestrator's
      own reading; refused with --limit and --marker) or PHASE_CONTEXT_LIMIT.
      Exit 4 when the transcript holds no
      usage record (Kiro records none).
  --selftest [--work <dir>]
      runs the fixture cases under fixtures/dream-manifest/ in temporary
      homes with a temporary --repo; --work names the parent directory for
      that scratch space and is accepted only together with --selftest.

Work folder: ~/.agent-playbook/dream-work (%USERPROFILE%\\.agent-playbook\\
dream-work on Windows), resolved from the user's home directory only. No
option or environment variable of a real run redirects it: `manifest` and
`clean` refuse (exit 3) unless the folder's real path equals
<real home>/.agent-playbook/dream-work component by component (case-
insensitively on Windows), so a symlinked or junctioned component is refused,
not followed. `manifest` creates the folder and writes only inside it;
`clean` deletes only it; `count` writes nothing anywhere.

The home directory must be absolute, an existing directory and not a
filesystem root, or every subcommand refuses (exit 3). `manifest` creates the
work folder (and `.agent-playbook` when missing) with mode 0700 and every file
in it with mode 0600 (best effort on Windows, where POSIX modes do not apply).
`clean` renames the folder to a unique sibling inside `.agent-playbook`,
re-checks that the renamed path is a real directory directly inside the real
<home>/.agent-playbook, and only then deletes it.

Nothing is redacted. A stripped transcript is the user's and the assistant's
text verbatim (minus harness records, tool traffic and shell-mode `!` records;
a Claude Code answer to an AskUserQuestion and a message typed mid-turn are kept,
labelled [user:answer] and [user:mid-turn]), so anything the user typed -- a
pasted token included -- is in the work folder until `clean` runs.

Claude Code forks: a fork or background handoff writes a new transcript that
carries the whole earlier history under the same record `uuid`s, so two files
hold the same turns. Within one project, the selected local Claude sessions
are taken in keeper order -- more records first, a tie to the smaller session
id, then to the smaller file path -- and each record is kept by the first
session that holds it, so a chain
of forks keeps every record once. A session whose every conversation turn is
already kept is not listed; its project's `fork_collapsed` names it
(`dropped`; `kept`, the session holding most of its records, a tie to the
smaller id; `shared_records`). A session that shares only a prefix keeps its
own turns: its boundary moves to its first conversation turn that is not
shared (a turn without a record uuid is its own), and a shared record after
that boundary, which its keeper already shows, is left out of its stripped
transcript (a header line counts them). A session whose every record is held
by a larger transcript that is not selected in the same project this sweep
(another project, or not selected) is kept, so no user turn is dropped, and
its project's errors[] reads "every record of Claude session <id> is also in
session <id> (<file>), a fork in another project or not selected in this
one; <id> is kept so no turn is dropped". Transcripts are compared per file:
when one session id has two files in a project, a file whose every record is
in the other is not listed and errors[] names both files; two files that each
hold turns of their own are both listed, the second with its own stripped
file, and errors[] says so.

New plans (manifest `plans.new_plans`): for a project the last sweep stamped
(its last_analyzed equals the state's last_run), a plan is new when the commit
that added it to the archive is not an ancestor of the commit that last
modified the state file (`git merge-base --is-ancestor`), so the answer does
not depend on any machine's clock. Otherwise -- a project that sweep did not
stamp (its agent failed or was skipped, or it is absent from the state), the
state file uncommitted or modified, git absent, or the archive's repository
not holding that commit (a project repo other than the config repo) -- the
time rule applies: added-commit time (else the file-name prefix) later than
the project's baseline, so a plan archived since the project was last read
is never lost to a later state commit.

Exit codes: 0 ok, 2 usage, 3 guard refusal, 4 `baseline` found no usage,
5 leftover work folder (printed
with its snapshot_at so the orchestrator can ask resume / discard / stop),
6 `clean` could not delete the renamed folder (its path is printed; delete it
by hand).

Canonical rules: shared/skills/qdream/sweep-orient.md [ORI-DISCOVER] and
[ORI-DISPATCH] (dispatch, quiet-project cadence); memory-rules.md § State File
Format and § Staleness nudge (the `count` line); sweep-gather.md § GAT-PLANS
(plans). Provider facts:
providers/claude/steering/memory-sources.md,
providers/kiro/steering/memory-sources.md. Python 3.8+, stdlib only.
"""

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

IS_WINDOWS = os.name == "nt"

EXIT_OK, EXIT_USAGE, EXIT_GUARD, EXIT_LEFTOVER, EXIT_CLEAN_FAILED = 0, 2, 3, 5, 6
EXIT_NO_USAGE = 4

# message.usage fields summed by `baseline` (Claude Code 2.1.281).
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens")

DEFERRED_HOURS = 24          # in_progress newer than this is deferred (memory-sources.md)
DUE_MARGIN_DAYS = 7          # due at max(1, deletion age - 7) (memory-rules.md § Staleness nudge)
DEFAULT_CLEANUP_DAYS = 30    # Claude Code default cleanupPeriodDays
KIRO_CLEANUP_KEY = "cleanup.periodDays"   # kiro-cli settings/cli.json; unset = no Kiro due flag
SWEEP_DUE_SESSIONS = 50      # memory-rules.md § Staleness nudge, work-volume arm
SWEEP_DUE_DAYS = 14          # memory-rules.md § Staleness nudge, quiet-period arm
RECENT_PLANS = 50            # plan-cluster window (sweep-gather.md § GAT-PLANS)
STRUCT_MAX_DEPTH = 6         # Method B recursion bound
INTENT_MAX_CHARS = 400       # plans.recent[].intent excerpt cap
PLAN_DECISIONS_MAX = 40      # new_plans[].decisions rows, per plan
PLAN_REVIEW_LOG_MAX = 60     # new_plans[].review_log lines, per plan
PLAN_ITEM_MAX_CHARS = 400    # one decisions row / review_log line
PLAN_MEMORY_MAX = 20         # new_plans[].memory_relied_on headings, per plan
PLAN_MEMORY_MAX_CHARS = 200  # one memory_relied_on heading
KIRO_ACTIVITY_SECONDS = 60   # lastModifiedAt - createdAt beyond this = used
MANIFEST_WARN_BYTES = 200 * 1024   # manifest.json is read whole by the orchestrator
QUIET_CYCLE = 5              # a quiet memory file's whole pass every 5th sweep (sweep-orient.md [ORI-DISPATCH])
QUIET_PERIODIC_AT = QUIET_CYCLE - 1   # quiet_sweeps value at which the pass is due
INT64_MAX = 2 ** 63 - 1       # largest quiet_sweeps value both state validators accept
USER_MEMORY_KEY = "user memory"       # the user memory's quiet_sweeps key (memory-rules.md § State File Format)
NON_TERMINAL_CONFLICT = ("rule-update-pending", "deferred")
ENTRY_FLAGS = ("stale_after_passed", "cited_paths_missing", "cited_slugs_missing",
               "governance_conflict_open", "cited_path_changed", "cited_commit_missing",
               "stale_when_fired", "stale_when_unknown")
# User decision 2026-09-25 (A): only these set memory_pass `flagged`; the
# path and slug flags stay in memory_flags as inputs for a dispatched agent,
# and so do cited_path_changed, cited_commit_missing and stale_when_unknown
# (memory-rules.md § Suspect memory entries). stale_when_fired joined at the
# Phase 8 gate (plan 261006 P-13, user decision 2026-10-06, "stale_when_fired
# only"): cited_path_changed would dispatch most quiet files every sweep.
TRIGGER_FLAGS = ("stale_after_passed", "governance_conflict_open", "stale_when_fired")
# Every flag but these makes an entry a suspect (memory-rules.md § Suspect
# memory entries): an open adjudication is not a sign the entry changed, and
# an unreadable version condition counts as not fired (user decision
# 2026-10-06, "Unknown is not a suspect"); stale_when_unknown is informational.
NON_SUSPECT_FLAGS = ("governance_conflict_open", "stale_when_unknown")
# The tools a version-shaped Stale-when may name. Their version is read from
# the harness's own session records, never by running the tool: a tool name
# taken from memory text must never become a command.
STALE_WHEN_TOOLS = ("claude-code", "kiro-cli")

# Session-start memory context budget (memory-rules.md § Session-start memory
# context budget): the word pin on the always-loaded user memory, memory/MEMORY.md
# plus memory/HIGHER_ORDER.md, counted by qmemory-eval.py's compute_memory_tax.
# Warn-only: `count` and dream-check.py `budget` print it; no exit code depends
# on it. Ratchet: after a deliberate reduction, lower the pin to
# min(current pin, ceil(measured words x 1.10)) -- the ratchet verify-mass
# applies to shared/AGENTS.md, which rounds down instead. Raising the pin needs
# the user's approval, recorded in the commit message.
MEMORY_BUDGET_WORDS = 12400

# Skill-body detection (memory-sources.md): a user turn holds an expanded skill body when it
# carries at least SKILL_MIN_MATCHES of the skill's distinctive lines AND at
# least SKILL_MIN_COVERAGE of them. A pasted excerpt or a draft stays text.
SKILL_ANCHOR_MIN_LEN = 40
SKILL_MIN_MATCHES = 3
SKILL_MIN_COVERAGE = 0.5

MARKER = "=== NEW TURNS BEGIN ==="
PRUNE_DIRS = {".git", "node_modules", "__pycache__", "venv", ".tox", "dist",
              "build", "fixtures", ".cache", ".idea", ".vscode"}
TYPE_SECTIONS = {"## Feedback", "## Decision", "## Pattern"}
NON_HUMAN_ORIGINS = {"task-notification", "peer"}
# Harness text inside a user record, judged per content block. `!` shell-mode
# records (<bash-input>, <bash-stdout>, <bash-stderr>) are harness text too:
# their output can carry secrets and is never user speech.
HARNESS_TEXT_PREFIXES = (
    "This session is being continued",
    "<task-notification>",
    "<local-command-",
    "[Request interrupted by user",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
)
COMMAND_TAG_PREFIXES = ("<command-name>", "<command-message>")
# Directly under the home directory: never walked by Method B.
HOME_PRUNE_NAMES = ("AppData", "Library")
HOME_PRUNE_PREFIXES = ("OneDrive",)
HISTORY_PREFIX_MATCH = 20    # R9: common normalized prefix for a history match
PRIVATE_DIR, PRIVATE_FILE = 0o700, 0o600

# Test-only interposition points (the selftest simulates races through them);
# a real run never sets one.
_HOOKS = {}


def _hook(name, *args):
    fn = _HOOKS.get(name)
    if fn is not None:
        fn(*args)


def _rmtree(path):
    shutil.rmtree(path)


class Usage(Exception):
    pass


class Ctx:
    """Home and clock. A real run uses Path.home() and the wall clock; only
    run_selftest constructs another one. No CLI flag reaches this."""

    def __init__(self, home=None, now=None, env=None):
        self.home = Path(home) if home is not None else Path.home()
        self.now = now if now is not None else dt.datetime.now(dt.timezone.utc)
        self.env = env if env is not None else dict(os.environ)


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?"
    r"\s*(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_time(value):
    """ISO-8601 string or Unix seconds/milliseconds -> aware UTC datetime.
    A naive timestamp is read as UTC. Returns None when unparseable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000.0 if value > 1e11 else float(value)
        try:
            return dt.datetime.fromtimestamp(secs, dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0"))
    if tz is None or tz in ("Z", "z"):
        tzinfo = dt.timezone.utc
    else:
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        tzinfo = dt.timezone(sign * dt.timedelta(hours=int(digits[:2]),
                                                 minutes=int(digits[2:])))
    try:
        t = dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0),
                        int(ss or 0), micro, tzinfo)
    except ValueError:
        return None
    return t.astimezone(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Paths and the work-folder guard
# --------------------------------------------------------------------------

_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")

# plan 261016 Phase 5: the key of a project that is only a store (no checkout is known on this
# machine) is `store:` plus the STORE identity text. It is a key, never a path.
STORE_KEY_PREFIX = "store:"
# Opens the top-level errors[] line that says the store repo exists but cannot be read. dream-write.py reads
# it: while it is there, a project memory file outside the store repo is not written.
STORE_REPO_UNREADABLE = "store repo unreadable:"


def norm_key(path):
    """memory-rules.md § Path normalization: absolute (links not followed),
    strip \\\\?\\, backslashes to '/', no trailing separator, case-folded.
    Used for comparison only; the verbatim path is what gets reported."""
    p = str(path)
    if p.startswith(STORE_KEY_PREFIX):
        return p.casefold()     # plan 261016 Phase 5: a store-only project key is not a path
    if not _ABS_RE.match(p):
        p = os.path.abspath(p)
    if p.startswith("\\\\?\\UNC\\"):
        p = "//" + p[8:]
    elif p.startswith("\\\\?\\"):
        p = p[4:]
    p = p.replace("\\", "/")
    while len(p) > 1 and p.endswith("/") and not re.match(r"^[A-Za-z]:/$", p):
        p = p[:-1]
    return p.casefold()


_DRIVE_RE = re.compile(r"^(\\\\\?\\)?([A-Za-z])(:(?:[\\/]|$))")


def canon_path(path):
    """A project key as reported: the path verbatim except a Windows drive
    letter, which is uppercased ('c:\\x' -> 'C:\\x') -- state keys use 'C:\\',
    while Kiro workspacePaths and history.jsonl may carry 'c:\\'. Used
    wherever a project key is built, so one project never gets two keys."""
    p = str(path)
    m = _DRIVE_RE.match(p)
    if m:
        p = (m.group(1) or "") + m.group(2).upper() + p[m.end(2):]
    return p


def _parts(path):
    parts = Path(path).parts
    return [x.casefold() for x in parts] if IS_WINDOWS else list(parts)


def worktree_parent(path):
    """The project folder a Claude Code sub-agent worktree copy belongs to,
    for a path inside `<project>/.claude/worktrees/` (the folder itself is
    not inside it); None for any other path. The path is tried as given,
    then resolved, so a link into a copy is caught too."""
    cands = [str(path)]
    if os.path.lexists(str(path)):
        cands.append(os.path.realpath(str(path)))
    for cand in cands:
        parts = Path(cand).parts
        low = [x.casefold() for x in parts]
        for i in range(len(parts) - 2):
            if low[i] == ".claude" and low[i + 1] == "worktrees" and i > 0:
                return str(Path(*parts[:i]))
    return None


def expected_work(home):
    """The only folder any subcommand may create or delete."""
    return Path(os.path.realpath(str(home))) / ".agent-playbook" / "dream-work"


def work_path(home):
    return Path(home) / ".agent-playbook" / "dream-work"


def guard_reason(candidate, home):
    """None when candidate's real path is exactly the expected folder,
    compared component-wise (case-insensitive on Windows), and neither the
    folder nor <home>/.agent-playbook is a link; else the refusal reason,
    naming the resolved path. A prefix match is not a match."""
    cand = str(candidate)
    real = os.path.realpath(cand)
    for p in (os.path.join(str(home), ".agent-playbook"), cand):
        if os.path.islink(p):
            return "%s is a link (resolves to %s)" % (p, os.path.realpath(p))
    if _parts(real) != _parts(expected_work(home)):
        return "%s resolves to %s, not %s" % (cand, real, expected_work(home))
    return None


def guard_ok(candidate, home):
    return guard_reason(candidate, home) is None


def home_problem(home):
    """None for a usable home directory, else why it is refused."""
    h = str(home)
    if not os.path.isabs(h):
        return "is a relative path"
    for p in (Path(h), Path(os.path.realpath(h))):
        if p.parent == p:
            return "is a filesystem root"
    if not os.path.isdir(h):
        return "is not an existing directory"
    return None


def is_inside(child, parent):
    c, p = _parts(os.path.realpath(str(child))), _parts(os.path.realpath(str(parent)))
    return len(c) > len(p) and c[:len(p)] == p


def mkdir_private(path):
    """mkdir with mode 0700 (FileExistsError when anything is there, a link
    included); the mode is best effort on Windows."""
    os.mkdir(str(path), PRIVATE_DIR)
    if not IS_WINDOWS:
        try:
            os.chmod(str(path), PRIVATE_DIR)
        except OSError:
            pass


def write_in_work(work, rel, text):
    """Create work/rel (mode 0600) and write text; never overwrites -- a second
    write to one path raises FileExistsError."""
    target = Path(work) / rel
    if not is_inside(target, work):
        raise RuntimeError("refusing write outside the work folder: %s" % target)
    missing, d = [], target.parent
    while not os.path.lexists(str(d)):
        missing.append(d)
        d = d.parent
    for d in reversed(missing):
        mkdir_private(d)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) \
        | getattr(os, "O_BINARY", 0)
    fd = os.open(str(target), flags, PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def read_text(path):
    with open(str(path), "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    return text


# Deepest JSON nesting a transcript line may have. json.loads alone gives no
# single answer: where it raises RecursionError follows the interpreter (the
# recursion limit, about 1000, on Python 3.8-3.11; the C recursion limit on
# 3.12-3.13; the C stack on 3.14+) and the platform, so a line nested 10000
# deep parses on 3.13 Linux and is refused elsewhere. A fixed cap well under
# every one of those gives "nested too deeply" the same verdict on every
# Python and OS; real transcript lines nest a few dozen levels.
JSONL_MAX_DEPTH = 512
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def _json_too_deep(raw, limit=JSONL_MAX_DEPTH):
    """True when raw -- text json.loads accepted -- nests [ / { deeper than
    limit. A line with no more than limit brackets cannot, so it is not
    scanned; otherwise string literals (where a bracket is not structure)
    are removed first, which is exact on valid JSON."""
    if raw.count("[") + raw.count("{") <= limit:
        return False
    depth = 0
    for ch in _JSON_STRING.sub("", raw):
        if ch == "[" or ch == "{":
            depth += 1
            if depth > limit:
                return True
        elif ch == "]" or ch == "}":
            depth -= 1
    return False


def read_jsonl(path):
    """-> (records, errors). records: list of (lineno, obj). CRLF-tolerant.
    A torn FINAL line (a writer mid-append) is ignored silently; any other
    unparseable line (too deeply nested included: deeper than
    JSONL_MAX_DEPTH, or deep enough for json to raise RecursionError) is
    reported, and lines that parse but hold invalid UTF-8 or a non-object
    value are counted in one error line per file."""
    with open(str(path), "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    lines = data.split(b"\n")
    last = len(lines)
    while last > 0 and not lines[last - 1].strip():
        last -= 1
    recs, errs, odd = [], [], 0
    for i in range(last):
        raw_b = lines[i].rstrip(b"\r")
        if not raw_b.strip():
            continue
        bad_utf8 = False
        try:
            raw = raw_b.decode("utf-8")
        except UnicodeDecodeError:
            bad_utf8 = True
            raw = raw_b.decode("utf-8", errors="replace")
        try:
            obj = json.loads(raw)
            too_deep = _json_too_deep(raw)
        except RecursionError:
            too_deep = True
        except ValueError:
            if i == last - 1:
                continue
            errs.append("unparseable line L%d in %s" % (i + 1, path))
            continue
        if too_deep:
            errs.append("unparseable line L%d in %s (nested too deeply)" % (i + 1, path))
            continue
        if bad_utf8 or not isinstance(obj, dict):
            odd += 1
        if isinstance(obj, dict):
            recs.append((i + 1, obj))
    if odd:
        errs.append("%d line(s) with invalid UTF-8 or non-object JSON in %s" % (odd, path))
    return recs, errs


def load_json(path):
    try:
        return json.loads(read_text(path))
    except (OSError, ValueError, RecursionError):
        return None


def git_rc(repo, *args):
    """Exit code of a git command, or None when git cannot run."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo)] + list(args),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode


def git_out(repo, *args):
    # --no-optional-locks: `git status` must not refresh the index -- the
    # script writes nothing outside the work folder, .git included.
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo)] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------
# Skill-body detection (providers/*/steering/memory-sources.md)
# --------------------------------------------------------------------------

def _nl(line):
    return " ".join(line.split())


class SkillIndex:
    def __init__(self):
        self.anchors = {}      # normalized line -> set(skill)
        self.totals = {}       # skill -> distinct anchor count
        self.lines = {}        # skill -> set(all normalized non-empty lines)
        self.arg_forms = {}    # skill -> list of (prefix, suffix, prev, next)

    @classmethod
    def from_repo(cls, repo):
        """Every .md file of every skill directory (fixtures excluded) is
        indexed: SKILL.md and its Kiro OVERLAY.md as the unit '<skill>';
        any other file as '<skill>/<path>', with a '<stem>.OVERLAY.md'
        joining '<skill>/<stem>.md' -- so a skill split into several files
        (qdream's sweep-*.md) is still recognised file by file."""
        idx = cls()
        repo = Path(repo)
        dirs = sorted(d for d in repo.glob("shared/skills/*") if d.is_dir())
        dirs += sorted(d for d in repo.glob("providers/*/skills/*") if d.is_dir())
        for d in dirs:
            for f in sorted(d.rglob("*.md")):
                rel = f.relative_to(d)
                if any(part in PRUNE_DIRS or part.startswith(".") for part in rel.parts[:-1]):
                    continue
                name = rel.as_posix()
                if name in ("SKILL.md", "OVERLAY.md"):
                    unit = d.name
                else:
                    if name.endswith(".OVERLAY.md"):
                        name = name[:-len(".OVERLAY.md")] + ".md"
                    unit = "%s/%s" % (d.name, name)
                try:
                    idx.add(unit, read_text(f))
                except OSError:
                    continue
        return idx

    def add(self, name, text):
        lines = text.replace("\r\n", "\n").split("\n")
        all_lines = self.lines.setdefault(name, set())
        forms = self.arg_forms.setdefault(name, [])
        anchors = set()
        nonempty = [(i, _nl(l)) for i, l in enumerate(lines) if _nl(l)]
        for pos, (i, n) in enumerate(nonempty):
            if "$ARGUMENTS" in n:
                pre, _, suf = n.partition("$ARGUMENTS")
                prev_l = nonempty[pos - 1][1] if pos > 0 else None
                next_l = nonempty[pos + 1][1] if pos + 1 < len(nonempty) else None
                forms.append((pre.strip(), suf.strip(), prev_l, next_l))
                continue
            all_lines.add(n)
            if len(n) >= SKILL_ANCHOR_MIN_LEN:
                anchors.add(n)
        for a in anchors:
            self.anchors.setdefault(a, set()).add(name)
        self.totals[name] = len({a for a, s in self.anchors.items() if name in s})

    def replace_bodies(self, text):
        """Replace each expanded skill body with '[skill body: <name>]',
        keeping the substituted arguments and the user's own text."""
        if not self.anchors or len(text) < SKILL_ANCHOR_MIN_LEN * SKILL_MIN_MATCHES:
            return text
        lines = text.split("\n")
        norm = [_nl(l) for l in lines]
        hits = {}
        for i, n in enumerate(norm):
            for s in self.anchors.get(n, ()):
                hits.setdefault(s, []).append(i)
        found = []
        for s, idxs in hits.items():
            distinct = len({norm[i] for i in idxs})
            total = self.totals.get(s) or 1
            if distinct >= SKILL_MIN_MATCHES and distinct / total >= SKILL_MIN_COVERAGE:
                found.append((min(idxs), max(idxs), s))
        if not found:
            return text
        found.sort()
        out, pos = [], 0
        for start, end, s in found:
            if start < pos:
                continue
            body = self.lines.get(s, set())
            while start > pos and (not norm[start - 1] or norm[start - 1] in body):
                start -= 1
            while end + 1 < len(lines) and (not norm[end + 1] or norm[end + 1] in body):
                end += 1
            while start < end and not norm[start]:
                start += 1
            args = self._arguments(s, lines[start:end + 1], norm[start:end + 1])
            out.extend(lines[pos:start])
            out.append("[skill body: %s]%s" % (s, (" " + args) if args else ""))
            pos = end + 1
        out.extend(lines[pos:])
        return "\n".join(out)

    def _arguments(self, s, span, nspan):
        body = self.lines.get(s, set())
        got = []
        for pre, suf, prev_l, next_l in self.arg_forms.get(s, []):
            if pre or suf:
                for raw, n in zip(span, nspan):
                    if n in body or not n:
                        continue
                    if n.startswith(pre) and n.endswith(suf) and len(n) > len(pre) + len(suf):
                        mid = n[len(pre):len(n) - len(suf)] if suf else n[len(pre):]
                        got.append(mid.strip())
                        break
                continue
            # Bare $ARGUMENTS line: take the lines between its template
            # neighbours, as found in this span.
            try:
                a = nspan.index(prev_l) + 1 if prev_l is not None else 0
            except ValueError:
                continue
            b = len(nspan)
            if next_l is not None:
                try:
                    b = nspan.index(next_l, a)
                except ValueError:
                    continue
            chunk = [r for r, n in zip(span[a:b], nspan[a:b]) if n and n not in body]
            if chunk:
                got.append("\n".join(chunk).strip())
        seen, res = set(), []
        for g in got:
            if g and g not in seen:
                seen.add(g)
                res.append(g)
        return " ".join(res)


# --------------------------------------------------------------------------
# Record extraction (providers/*/steering/memory-sources.md)
# --------------------------------------------------------------------------

def _block_text(content):
    """(text, only_tool_results)"""
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False
    texts, tool = [], False
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            texts.append(b["text"])
        elif b.get("type") == "tool_result":
            tool = True
    return "\n".join(texts), (tool and not texts)


_CMD_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)


_SHELL_OUT_RE = re.compile(r"<bash-(stdout|stderr)>.*?</bash-\1>", re.S)


def _user_blocks(content):
    """-> (text blocks, only_tool_results). A string content is one block."""
    if isinstance(content, str):
        return [content], False
    if not isinstance(content, list):
        return [], False
    texts, tool = [], False
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            texts.append(b["text"])
        elif b.get("type") == "tool_result":
            tool = True
    return texts, (tool and not texts)


def claude_user_text(rec):
    """Genuine user speech of one Claude Code record, or None. Harness text
    is dropped per content block, so a user block after an interruption
    notice survives; a slash command is rendered only when the text starts
    with its tags, so a pasted tag mid-text stays as typed."""
    if rec.get("type") != "user":
        return None
    if rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary"):
        return None
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") in NON_HUMAN_ORIGINS:
        return None
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
    blocks, only_tools = _user_blocks(msg.get("content"))
    if only_tools:
        return None
    return _clean_user_blocks(blocks)


def _clean_user_blocks(blocks):
    """The text of a user turn's text blocks with harness blocks dropped, or None."""
    kept = []
    for b in blocks:
        b = b.strip()
        if not b or b.startswith(HARNESS_TEXT_PREFIXES):
            continue
        b = _SHELL_OUT_RE.sub("[shell output omitted]", b).strip()
        if b:
            kept.append(b)
    text = "\n".join(kept)
    if not text:
        return None
    if text.startswith(COMMAND_TAG_PREFIXES):
        m = _CMD_RE.search(text)
        if m:
            a = _ARGS_RE.search(text)
            text = (m.group(1) + (" " + a.group(1).strip() if a and a.group(1).strip() else "")).strip()
    return text or None


def claude_dialog_texts(rec):
    """[(role, text)] for the two channels of user speech that are not text
    blocks of a type:user record. Role "user:answer": one entry per question of
    an AskUserQuestion result, read only from toolUseResult.answers (the
    tool_result text is harness framing, never read). Role "user:mid-turn": a
    message typed while the agent worked, read from the queued_command
    attachment's prompt (the <system-reminder> it is rendered as is never
    parsed). Every exclusion of claude_user_text applies again here; a shape
    that is not certainly human yields nothing."""
    if rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary"):
        return []
    kind = rec.get("type")
    if kind == "user":
        origin = rec.get("origin")
        if isinstance(origin, dict) and origin.get("kind") in NON_HUMAN_ORIGINS:
            return []
        res = rec.get("toolUseResult")
        if not isinstance(res, dict):
            return []
        answers, questions = res.get("answers"), res.get("questions")
        if not isinstance(answers, dict) or not isinstance(questions, list):
            return []
        # An AskUserQuestion result answers the questions it asked; another
        # tool's result that merely has an `answers` key does not qualify.
        asked = {q.get("question") for q in questions if isinstance(q, dict)}
        return [("user:answer", "Q: %s → A: %s" % (q.strip(), a.strip()))
                for q, a in answers.items()
                if q in asked and isinstance(a, str) and a.strip()]
    if kind == "attachment":
        att = rec.get("attachment")
        if not isinstance(att, dict) or att.get("type") != "queued_command":
            return []
        origin = att.get("origin")
        if not isinstance(origin, dict) or origin.get("kind") != "human":
            return []
        blocks, _ = _user_blocks(att.get("prompt"))
        text = _clean_user_blocks(blocks)
        return [("user:mid-turn", text)] if text else []
    return []


def claude_assistant_text(rec):
    if rec.get("type") != "assistant" or rec.get("isSidechain"):
        return None
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
    text, _ = _block_text(msg.get("content"))
    return text.strip() or None


_KIRO_MACHINE_RE = re.compile(
    r'^(\[WORKFLOW NOTIFICATION\]|<original_user_request>|\{\s*"method"\s*:\s*"_kiro/)')


def kiro_machine(payload, text):
    """A kiro-cli v3 `user` record the harness wrote, not the user: a workflow
    or system notification (`_meta.kiro.notification`), a workflow step's
    notification block, or a workflow child's restated request. Live steering
    (`[LIVE STEERING ...]`, `source: steer` text) is the user's own and stays
    `user`."""
    meta = payload.get("_meta")
    kiro = meta.get("kiro") if isinstance(meta, dict) else None
    if isinstance(kiro, dict) and "notification" in kiro:
        return True
    return bool(_KIRO_MACHINE_RE.match(text))


def kiro_texts(rec):
    """-> (role, text) or None for one kiro-cli v3 record; role is user,
    assistant, or system for a harness-written `user` record."""
    payload = rec.get("payload")
    if not isinstance(payload, dict):
        return None
    t = payload.get("type")
    if t not in ("user", "assistant"):
        return None
    text, _ = _block_text(payload.get("content"))
    text = text.strip()
    if not text:
        return None
    if t == "user" and kiro_machine(payload, text):
        t = "system"
    return (t, text)


class Parsed:
    def __init__(self):
        self.recs = []        # (lineno, role, text, ts); role: user, user:answer, user:mid-turn, assistant
        self.ids = {}         # record id -> lineno (Kiro watermarks)
        self.errors = []
        self.last_id = None
        self.user_texts = set()   # normalized genuine user text (history-only dedup)
        self.uuid_lines = {}      # Claude record uuid -> lineno (fork detection)


def parse_claude(path, sid, history_by_session, skills):
    p = Parsed()
    try:
        raw, p.errors = read_jsonl(path)
    except OSError as e:
        p.errors.append("unreadable %s: %s" % (path, e))
        return p
    pending = list(history_by_session.get(sid, []))
    prev_ts = None
    for ln, rec in raw:
        uid = rec.get("uuid")
        if isinstance(uid, str) and uid:
            p.uuid_lines.setdefault(uid, ln)
        ut = claude_user_text(rec)
        if ut:
            items = [("user", ut)]
        else:
            # one answer record holds one entry per question, all at its line
            items = claude_dialog_texts(rec)
            if not items:
                at = claude_assistant_text(rec)
                items = [("assistant", at)] if at else []
        rec_ts = parse_time(rec.get("timestamp"))
        for role, text in items:
            ts = rec_ts
            typed = role in ("user", "user:mid-turn")   # words the user typed
            if typed:
                p.user_texts.add(_nl(text))
            if ts is None and typed:
                ts = _history_match(pending, text)
            if ts is None and role == "assistant":
                ts = prev_ts
            if typed:
                text = skills.replace_bodies(text)
            prev_ts = ts
            p.recs.append((ln, role, text, ts))
    return p


def _history_match(pending, text):
    """Timestamp of the history prompt matching text: normalized equality,
    or a common prefix of at least HISTORY_PREFIX_MATCH characters (history
    shortens pasted content). A short reply like "ok" never matches a longer
    prompt; no match leaves the record undated."""
    key = _nl(text)
    for k, (ts, disp, _ln, _proj) in enumerate(pending):
        d = _nl(disp)
        if d and (d == key or len(os.path.commonprefix([d, key])) >= HISTORY_PREFIX_MATCH):
            del pending[:k + 1]
            return ts
    return None


def parse_kiro(path, skills):
    p = Parsed()
    try:
        raw, p.errors = read_jsonl(path)
    except OSError as e:
        p.errors.append("unreadable %s: %s" % (path, e))
        return p
    for ln, rec in raw:
        rid = rec.get("id")
        if isinstance(rid, str):
            p.ids[rid] = ln
            p.last_id = rid
        got = kiro_texts(rec)
        if not got:
            continue
        role, text = got
        if role == "user":
            text = skills.replace_bodies(text)
        p.recs.append((ln, role, text, parse_time(rec.get("timestamp"))))
    return p


def select(parsed, baseline, watermark_line=None):
    """Session selection ([ORI-DISCOVER]). -> None (not new) or the boundary: a line number or 'unknown'."""
    recs = parsed.recs
    if not recs:
        return None
    if watermark_line is not None:
        after = [r for r in recs if r[0] > watermark_line]
        return after[0][0] if after else None
    if baseline is None:
        return recs[0][0]
    for ln, _role, _text, ts in recs:
        if ts is not None and ts > baseline:
            return ln
    if any(r[3] is None for r in recs):
        return "unknown"
    return None


def fork_rank(key, sid, uuids):
    """Keeper order: more records first, a tie to the smaller session id,
    then to the smaller file path (one session id may have two files)."""
    return (-len(uuids), sid, key)


def resolve_forks(group):
    """Claude Code fork duplicates within one project's selected sessions.
    group: [(key, sid, parsed, boundary)], key the transcript's file path.
    -> {key: (boundary, fork, skip)}. fork is None or {"of", "of_key",
    "shared", "kind"}: kind "full" (every conversation turn is held by a
    transcript earlier in keeper order: drop it; "of" is the one holding most
    of its records, a tie to the smaller id) or "partial" (the boundary moves
    to its first conversation turn that is not shared). skip: the lines after
    a partial fork's boundary whose record a keeper already shows after its
    own boundary, so each record is read once. Keepers resolve largest-first
    across every overlapping transcript, so a record a larger transcript owns
    is never kept a second time by a smaller one (a chain of forks included).
    A transcript is keyed by file, so it is never a fork of itself."""
    owner = {}    # record uuid -> key of the transcript that keeps it
    lines = {k: parsed.uuid_lines for k, _sid, parsed, _b in group}
    sids = {k: sid for k, sid, _p, _b in group}
    final = {}    # key -> final boundary of a listed transcript
    out = {}
    for key, sid, parsed, boundary in sorted(group, key=lambda g: fork_rank(g[0], g[1], g[2].uuid_lines)):
        mine = parsed.uuid_lines
        shared = [u for u in mine if u in owner]
        if not shared:
            owner.update((u, key) for u in mine)
            final[key] = boundary
            out[key] = (boundary, None, set())
            continue
        by = {}
        for u in shared:
            by[owner[u]] = by.get(owner[u], 0) + 1
        of_key = min(by, key=lambda o: (-by[o], sids[o], o))
        fork = {"of": sids[of_key], "of_key": of_key, "shared": len(shared)}
        # A conversation turn without a shared record uuid (a uuid-less record
        # included) is this transcript's own; a fork copies a prefix, so its
        # own turns follow the shared records.
        shared_lines = {mine[u] for u in shared}
        own = [r[0] for r in parsed.recs if r[0] not in shared_lines]
        if not own:
            fork["kind"] = "full"
            out[key] = (None, fork, set())
            continue
        owner.update((u, key) for u in mine if u not in owner)
        if boundary == "unknown" or own[0] > boundary:
            boundary = own[0]
        final[key] = boundary
        skip = set()
        for u in shared:
            k = owner[u]
            kb = final.get(k)
            if mine[u] > boundary and kb is not None and (kb == "unknown" or lines[k][u] >= kb):
                skip.add(mine[u])
        fork["kind"] = "partial"
        out[key] = (boundary, fork, skip)
    return out


def outside_keeper(key, sid, uuids, group_keys, uuid_sets):
    """A parsed transcript outside this project's selected sessions that holds
    every record of this one and ranks before it as keeper -> (key, sid), or
    None. uuid_sets: file key -> (sid, record uuids)."""
    if not uuids:
        return None
    hits = [o for o, (osid, theirs) in uuid_sets.items()
            if o not in group_keys and fork_rank(o, osid, theirs) < fork_rank(key, sid, uuids)
            and all(u in theirs for u in uuids)]
    if not hits:
        return None
    o = min(hits, key=lambda o: fork_rank(o, *uuid_sets[o]))
    return o, uuid_sets[o][0]


def render(header, recs, boundary, preface=None, skip=()):
    """skip: lines after the boundary left out (a fork's records its keeper
    already shows)."""
    out = list(header)
    if preface:
        out.append(preface)
    placed = False
    for ln, role, text, _ts in recs:
        if not placed and (boundary == "unknown" or ln == boundary):
            out.append(MARKER)
            placed = True
        if placed and ln in skip:
            continue
        out.append("L%d [%s] %s" % (ln, role, text))
    return "\n".join(out) + "\n"


DIGEST_USER_CHARS = 1500       # one user turn kept in a session digest
DIGEST_ASSISTANT_CHARS = 600   # the assistant text kept before each user turn


def _clip_head(text, limit):
    return text if len(text) <= limit else text[:limit] + " [... %d chars cut]" % (len(text) - limit)


def _clip_tail(text, limit):
    return text if len(text) <= limit else "[%d chars cut ...] " % (len(text) - limit) + text[-limit:]


def render_digest(header, recs, boundary, skip=()):
    """A session's user turns after the boundary, each with the end of the assistant text before it,
    and the session's closing assistant text. Every line keeps its L number, which indexes the
    stripped transcript, so a reader can open the span behind a line."""
    out = list(header)
    placed = False
    tail = None
    for ln, role, text, _ts in recs:
        if not placed and (boundary == "unknown" or ln == boundary):
            placed = True
        if role == "assistant":
            # Assistant text before the boundary still frames the first user turn after it.
            if not (placed and ln in skip):
                tail = (ln, text)
            continue
        if not placed or ln in skip:
            continue
        if tail is not None:
            out.append("L%d [assistant] %s" % (tail[0], _clip_tail(tail[1], DIGEST_ASSISTANT_CHARS)))
            tail = None
        out.append("L%d [%s] %s" % (ln, role, _clip_head(text, DIGEST_USER_CHARS)))
    if placed and tail is not None:
        out.append("L%d [assistant] %s" % (tail[0], _clip_tail(tail[1], DIGEST_ASSISTANT_CHARS)))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# Memory entries (manifest entries[])
# --------------------------------------------------------------------------

_STALE_AFTER_RE = re.compile(r"^\*\*Stale-after\*\*:\s*(\d{4}-\d{2}-\d{2})")
_TICK_RE = re.compile(r"`([^`\n]+)`")
_PATHLIKE_RE = re.compile(r"^[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*/?$")
_SLUG_RE = re.compile(r"\b\d{6}(?:-\d{4})?_([A-Z][A-Z0-9_]*[A-Z0-9])\b")
# memory-rules.md § Governance-conflict adjudication: "**Governance-conflict**:
# <contradicts | subsumed by> <file § section> — adjudicated <date>: <state>
# (optional note)"; the first "adjudicated <date>:" names the state.
_CONFLICT_RE = re.compile(
    r"^\*\*Governance-conflict\*\*:.*?\badjudicated\s+\d{4}-\d{2}-\d{2}\s*:\s*([a-z-]+)")
# memory-rules.md § Suspect memory entries: the one Stale-when form the script
# evaluates. Any other Stale-when text is left to the model.
_STALE_WHEN_VER_RE = re.compile(
    r"^\*\*Stale-when\*\*:\s*(\S+)\s+version\s*>\s*(\d+\.\d+(?:\.\d+)?)\s*$")
# A Stale-when field line, bullet or quote prefix allowed: what a near miss
# of the version form must look like before it is reported.
_STALE_WHEN_FIELD_RE = re.compile(r"^\W*\*\*Stale-when\*\*:")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)")


def _load_sibling(filename, modname):
    """A sibling script beside this file, loaded by path: never through sys.path or a bytecode
    cache (Kiro deploys qdream as a copy, and a stray __pycache__ there reads as drift)."""
    import importlib.util
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        here = Path(os.path.realpath(__file__)).parent
        spec = importlib.util.spec_from_file_location(modname, str(here / filename))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


_ENTRIES = None


def memory_entries():
    """memory-entries.py (plan 261016 Phase 11), the one memory-file parser and the one owner of
    the fence rule (its FENCE_RE, which dream-write.py and dream-check.py use too). Loaded on first
    use, never before a script's venv guard runs: a broken parser must not hide that guard's exit 2."""
    global _ENTRIES
    if _ENTRIES is None:
        _ENTRIES = _load_sibling("memory-entries.py", "memory_entries")
    return _ENTRIES


def parse_entries(text):
    """-> list of (heading, body_lines) for ### entries under the three type
    sections (memory-entries.py rules: fence-aware; ## Declined and the
    preamble are not entries)."""
    return [(h, b) for s, h, b, _n in memory_entries().entries(text) if "## " + s in TYPE_SECTIONS]


def declined_strays(memory_file):
    """`###` entries in the `## Declined` section (memory-entries.py rules):
    parse_entries reads no entry there, so each one is invisible to every sweep."""
    try:
        text = read_text(memory_file)
    except OSError:
        return []
    return ["memory file %s: entry below ## Declined is not read by the sweep "
            "(move it above ## Declined): %s" % (memory_file, h)
            for s, h, _b, _n in memory_entries().entries(text) if s == "Declined"]


def open_conflicts(body_lines):
    """The non-terminal Governance-conflict states recorded on an entry
    (outside code fences), sorted and unique."""
    states, fence = set(), None
    for line in body_lines:
        fm = memory_entries().FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        cm = _CONFLICT_RE.match(line.strip())
        if cm and cm.group(1) in NON_TERMINAL_CONFLICT:
            states.add(cm.group(1))
    return sorted(states)


def entry_flags(entry):
    """The flags an entry raises, in ENTRY_FLAGS order (sweep-orient.md [ORI-DISPATCH])."""
    return [f for f in ENTRY_FLAGS if entry.get(f)]


def quiet_seed(key):
    """The first-pass offset of a key never stored in quiet_sweeps, so
    first whole passes spread over QUIET_CYCLE sweeps."""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % QUIET_CYCLE


def quiet_index(stored):
    """quiet_sweeps.projects -> {normalized key: (verbatim key, value)}, so a
    key differing only by drive-letter case, separators or a trailing
    separator still matches its project."""
    if not isinstance(stored, dict):
        return {}
    return {norm_key(canon_path(k)): (k, v) for k, v in stored.items()}


def memory_cadence(stored, key, flags):
    """-> (quiet_sweeps, memory_pass) of one memory scope (sweep-orient.md
    [ORI-DISPATCH]). Only a TRIGGER_FLAGS flag makes the pass `flagged`
    (user decisions 2026-09-25, and 2026-10-06 for stale_when_fired)."""
    quiet = stored if stored is not None else quiet_seed(key)
    if any(f in TRIGGER_FLAGS for f in flags):
        return quiet, "flagged"
    return quiet, "periodic" if quiet >= QUIET_PERIODIC_AT else None


_ABS_CITE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/)[^\n*?<>|\"]+$")
_SEP_RE = re.compile(r"[\\/]+")
_DATE_PREFIX_RE = re.compile(r"^\d{6}(?:-\d{4})?_")
_MSYS_RE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?:/|$)")
# Folder names common to many trees. A relative cited path whose first
# component is one of these is judged only under the scope's own roots:
# never under the config repo (project memory) and never inside a known
# project that merely has this folder name, so a project that lost its
# `docs/` or `scripts/` is not reported present through another tree.
GENERIC_FOLDERS = frozenset((
    "api", "app", "assets", "bin", "build", "cli", "common", "config", "data", "dist",
    "docs", "done", "examples", "lib", "memory", "plans", "scripts", "skills", "src",
    "test", "tests", "tools", "utils", "web"))


def msys_to_native(path, windows=IS_WINDOWS):
    """A Git Bash or Cygwin absolute path on Windows (`/c/Users/x`,
    `/cygdrive/c/Users/x`) as `C:/Users/x`; a bare drive (`/c`) as the drive
    root `C:/`, never the drive-relative `C:`. Any other path (`/cc/x`,
    `//c/x`, `/c:/x`) is unchanged. `windows` is a parameter so the selftest
    can exercise the mapping on any host."""
    if not windows:
        return path
    return _MSYS_RE.sub(lambda m: m.group(1).upper() + ":/", path, count=1)


def _file_like(tok):
    last = _SEP_RE.split(tok.rstrip("\\/"))[-1]
    return tok.endswith(("/", "\\")) or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", last))


def cited_paths(body, keep_abs=None):
    """Repo-relative paths cited in backticks, plus absolute ones for which
    keep_abs(path) is true (those inside a known project; any
    other absolute path is not checked, as before)."""
    res = []
    for tok in _TICK_RE.findall(body):
        tok = re.sub(r":\d+(?:-\d+)?(?:,\d+)*$", "", tok.strip())
        if _ABS_CITE_RE.match(tok):
            if keep_abs is not None and _file_like(tok) and keep_abs(tok) and tok not in res:
                res.append(tok)
            continue
        if "/" not in tok or not _PATHLIKE_RE.match(tok) or tok.startswith(("http", "~")):
            continue
        if not _file_like(tok):
            continue
        if tok not in res:
            res.append(tok)
    return res


def source_text(body):
    """The entry's Source value by the memory-entries.py rule (the first
    `**Source**:` line, without an inline `| **Verified**:` tail, stripped);
    "" when it has none. cited_path_changed reads only this anchor
    (memory-rules.md § Suspect memory entries), so a path named in Why or How
    to apply never marks the entry. Shared with
    providers/claude/memory-load-hook.py."""
    return memory_entries().source(body) or ""


def source_paths(body, keep_abs=None):
    """cited_paths() over the entry's one Source line only."""
    return cited_paths(source_text(body), keep_abs=keep_abs)


def plan_title(stem):
    """A plan's title: its stem without the YYMMDD_ / YYMMDD-HHMM_ date
    prefix, case-folded. /qclose Step 4 archives `plans/260416_X.md` as
    `plans/done/260416-1830_X.md`, so the title is what survives archival."""
    return _DATE_PREFIX_RE.sub("", stem, count=1).casefold()


def archive_matches(archive, cited):
    """An archived plan file name stands for the cited plan file name: the
    same name, or the same plan_title with an archive date on or after the
    cited plan's own date (/qclose Step 4 prefixes the archival date, which
    never precedes the authoring date). A cited name without a date prefix
    matches any archive date; one with a date never matches an undated
    archive."""
    if archive == cited:
        return True
    a = archive[:-3] if archive.endswith(".md") else archive
    c = cited[:-3] if cited.endswith(".md") else cited
    if plan_title(a) != plan_title(c):
        return False
    cd = prefix_time(c)
    if cd is None:
        return True
    ad = prefix_time(a)
    return ad is not None and ad.date() >= cd.date()


def present_under(root, parts):
    """The cited path `parts` exists under root, or it names
    plans/<name>.md and root's matching plans/done/ holds the archived plan
    file (archive_matches). Only a file stands for a cited plan file: a
    plans/done/<name>/ folder never does."""
    if not root or not parts:
        return False
    if Path(root).joinpath(*parts).exists():
        return True
    if len(parts) >= 2 and parts[-2] == "plans" and parts[-1].endswith(".md"):
        try:
            for f in Path(root).joinpath(*parts[:-1], "done").iterdir():
                if f.is_file() and archive_matches(f.name, parts[-1]):
                    return True
        except OSError:
            return False
    return False


class CiteCheck:
    """(User decision 2026-09-25) Where a path cited in a memory
    entry may resolve. A relative path is tried under the memory file's own
    folder and the scope's own roots (project root, workspace store; the
    config repo for user memory). Only when none of those holds the path's
    first component is it tried under the fallback roots (the config repo,
    for project memory) and, when that component is a known project's
    folder name, inside that project; both fallbacks are skipped when that
    component is a GENERIC_FOLDERS name. An absolute path (a Git Bash
    `/c/...` form included, on Windows) is checked only inside a known
    project, against that project. No other root is tried, so a short
    relative name the project owns never matches elsewhere."""

    def __init__(self, known, fallback=(), windows=IS_WINDOWS):
        self.known = sorted({norm_key(canon_path(k)): k for k in known if k}.items(),
                            key=lambda kv: -len(kv[0]))
        self.by_name = {}
        for _, path in self.known:
            self.by_name.setdefault(Path(path).name.casefold(), []).append(path)
        self.fallback = [r for r in fallback if r]
        self.windows = windows

    def owner(self, cited):
        """-> (known project path, the cited path's parts below it) or None."""
        cited = msys_to_native(cited, self.windows)
        nk = norm_key(canon_path(cited))
        for k, path in self.known:
            if nk == k or nk.startswith(k.rstrip("/") + "/"):
                depth = len([x for x in _SEP_RE.split(path) if x])
                return path, [x for x in _SEP_RE.split(cited) if x][depth:]
        return None

    def locate(self, memory_file, own_roots, cited):
        """-> (present, the path it resolved to or None). The path is None
        when the cited path is absent or is an absolute path outside every
        known project (present: not checked)."""
        def hit(root, parts):
            direct = Path(root).joinpath(*parts)
            # Defensive: a plans/<name>.md present only through its
            # plans/done/ archive has no file at the cited path, so it is
            # never looked up in git.
            return True, (direct if direct.exists() else None)

        if _ABS_CITE_RE.match(cited):
            own = self.owner(cited)
            if own is None:
                return True, None
            if present_under(own[0], own[1]) or (not own[1] and Path(own[0]).is_dir()):
                return hit(own[0], own[1])
            return False, None
        parts = [x for x in cited.split("/") if x]
        roots = [str(Path(memory_file).parent)] + [r for r in own_roots if r]
        for r in roots:
            if present_under(r, parts):
                return hit(r, parts)
        if any(Path(r, parts[0]).exists() for r in roots):
            return False, None
        if parts[0].casefold() in GENERIC_FOLDERS:
            return False, None
        for r in self.fallback:
            if present_under(r, parts):
                return hit(r, parts)
        for path in self.by_name.get(parts[0].casefold(), []):
            if present_under(path, parts[1:]) or (len(parts) == 1 and Path(path).is_dir()):
                return hit(path, parts[1:])
        return False, None

    def present(self, memory_file, own_roots, cited):
        return self.locate(memory_file, own_roots, cited)[0]


def plan_stems(dirs):
    """Stems of every *.md file under dirs, plus the names of dated folders
    directly under a done/ folder: /qclose research mode archives a run as
    the folder plans/done/<YYMMDD-HHMM>_RESEARCH_<TAG>/, so its slug is a
    folder name. An undated folder (plans/done/assets/) is not a plan."""
    stems = set()
    for d in dirs:
        if d and Path(d).is_dir():
            for f in Path(d).rglob("*"):
                if f.suffix == ".md":
                    stems.add(f.stem)
                elif (f.parent.name == "done" and prefix_time(f.name) is not None
                      and f.is_dir()):
                    stems.add(f.name)
    return stems


def version_tuple(text):
    """'2.1.291' -> (2, 1, 291); the leading dotted digits only; None when
    the text does not start with a number."""
    m = _VERSION_RE.match(text.strip()) if isinstance(text, str) else None
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def version_after(current, written):
    """True when `current` is later than `written` at the precision written:
    against '2.18' only major.minor count, so a patch release never fires."""
    cur, ref = version_tuple(current), version_tuple(written)
    if cur is None or ref is None:
        return None
    cur = (cur + (0,) * len(ref))[:len(ref)]
    return cur > ref


def claude_code_version(claude_home):
    """The Claude Code version, read from its session store, never by running
    it: the `version` of the last record carrying a string one, in the newest
    ~/.claude/projects/*/*.jsonl (by mtime; an older file is tried only when
    a newer one holds no such record -- `last-prompt` and `ai-title` records
    carry none). None when no record has one."""
    files = []
    try:
        for f in (Path(claude_home) / "projects").glob("*/*.jsonl"):
            try:
                files.append((f.stat().st_mtime, str(f)))
            except OSError:
                continue
    except OSError:
        return None
    for _, f in sorted(files, reverse=True):
        try:
            with open(f, "rb") as fh:
                lines = fh.read().split(b"\n")
        except OSError:
            continue
        for raw in reversed(lines):
            if b'"version"' not in raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace"))
            except (ValueError, RecursionError):
                continue
            if isinstance(obj, dict) and isinstance(obj.get("version"), str) \
                    and version_tuple(obj["version"]) is not None:
                return obj["version"]
    return None


# kiro-cli's own startup line, adjacent keys only (plan 261009 Phase 2), as a
# raw string: the JSON sits inside a log line's "message" string, so its
# quotes are backslash-escaped once (`\"origin\":\"KIRO_CLI\",...`); each `\\?`
# also accepts the unescaped form.
_KIRO_CLI_LOG_RE = re.compile(
    r'\\?"origin\\?":\\?"KIRO_CLI\\?",\\?"version\\?":\\?"(\d+\.\d+(?:\.\d+)?)\\?"')


_KIRO_LOG_DIR_RE = re.compile(r"\d{8}T\d{9}")


def kiro_cli_version(kiro_home):
    """The kiro-cli version, read from its harness log, never by running it.
    Source: `<kiro_home>/logs/<ts>/kiro.log`, `<ts>` = YYYYMMDDTHHMMSSmmm.
    Each log is read line by line; a line whose "message" string embeds
    `{\\"origin\\":\\"KIRO_CLI\\",\\"version\\":\\"2.29.0\\",...}` (the pair of
    adjacent keys, quotes escaped once) gives the version. Only folders named
    like a timestamp (`^\\d{8}T\\d{9}$`) are tried, newest first by name; an
    older folder is read only when every newer one holds no match. None when
    `logs/` is missing or unreadable, or no log has the line.
    Measured 2026-10-09 on Windows, kiro-cli 2.29.0 (10 folders, 4 holding
    the line; other platforms unmeasured, and the reader fails open). Logs
    are read as UTF-8 with undecodable bytes replaced, the measured shape. A
    log in another encoding (for example UTF-16) does not match, so it is
    skipped like a log without the line, and an older log's version may be
    returned. Kiro session records hold no CLI version (383 files checked on
    2.27.1, 2026-10-06: only schemaVersion and dataModelVersion; 3 newest on
    2.29.0, 2026-10-09), which is why the log is the source.
    Residuals: the pair is matched anywhere in a line, so user text echoed
    into a log with that exact pair would be read as the version. When the
    newest kept logs are IDE-only (no CLI run), an older CLI run's version is
    returned, which can only under-fire a `version >` condition. The version
    must be 2-3 numeric parts closed by the quote, so a pre-release or
    4-part version (`2.30.0-beta.1`, `2.31.0.1`) in the newest log is
    skipped and an older log's version is returned instead."""
    try:
        folders = sorted((p for p in (Path(kiro_home) / "logs").iterdir()
                          if p.is_dir() and _KIRO_LOG_DIR_RE.fullmatch(p.name)),
                         key=lambda p: p.name, reverse=True)
    except OSError:
        return None
    for folder in folders:
        try:
            with open(folder / "kiro.log", "r", encoding="utf-8",
                      errors="replace") as fh:
                for line in fh:
                    m = _KIRO_CLI_LOG_RE.search(line)
                    if m and version_tuple(m.group(1)) is not None:
                        return m.group(1)
        except OSError:
            continue
    return None


class Anchors:
    """Read-only lookups behind the anchor and version flags, shared by every
    memory file of one run: the git repositories of the known roots, one
    batched `git log` per repository, one `cat-file --batch-check` per
    repository per memory file, and each allowlisted tool's version. Every
    failure fails open and lands in `notes`, which build_run appends to the
    manifest's top-level errors[]."""

    def __init__(self, roots, claude_home, kiro_home):
        self.roots = [r for r in roots if r]
        self._repos = None
        self._toplevel = {}
        self._hist = {}           # work tree -> history_key
        self._shallow = set()     # work trees that are shallow clones
        self._logs = {}           # history_key -> (since, {path key: newest date})
        self._commits = {}        # sha -> present in some known repository
        self._readers = {"claude-code": lambda: claude_code_version(claude_home),
                         "kiro-cli": lambda: kiro_cli_version(kiro_home)}
        self._versions = {}
        self.notes = []           # non-fatal errors[] lines, in first-seen order

    def note(self, line):
        if line not in self.notes:
            self.notes.append(line)

    def _git(self, repo, args, stdin=None):
        """-> (returncode, stdout text) of one read-only git call, or None
        when git cannot run. The selftest replaces it to simulate failures."""
        try:
            r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo)] + list(args),
                               input=stdin, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.returncode, r.stdout.decode("utf-8", errors="replace")

    def toplevel(self, folder):
        """The nearest folder at or above `folder` holding a `.git` entry (a
        folder, or the file of a worktree or submodule), found on disk, not
        by a git call per folder; None when there is none."""
        k = norm_key(folder)
        if k not in self._toplevel:
            cur, walked, top = os.path.realpath(str(folder)), [], None
            while True:
                ck = norm_key(cur)
                if ck in self._toplevel:
                    top = self._toplevel[ck]
                    break
                walked.append(ck)
                if os.path.lexists(os.path.join(cur, ".git")):
                    top = cur
                    break
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
            for w in walked + [k]:
                self._toplevel[w] = top
        return self._toplevel[k]

    def history_key(self, top):
        """(common git folder, HEAD commit) of a work tree: worktrees of one
        repository at one commit share a history, so they share one log.
        None, with an errors[] note, when git cannot read the folder as a
        repository or the repository is a shallow clone: its history is cut,
        so cited_path_changed skips it, and cat-file asks it only whether it
        holds a commit, never to prove one absent. One call per work tree."""
        k = norm_key(top)
        if k not in self._hist:
            got = self._git(top, ["rev-parse", "--is-shallow-repository", "--git-common-dir",
                                  "HEAD"])
            lines = [l.strip() for l in got[1].splitlines() if l.strip()] \
                if got is not None and got[0] == 0 else []
            if len(lines) != 3:
                self.note("git could not read %s: anchor flags (cited_path_changed, "
                          "cited_commit_missing) skipped there" % top)
                self._hist[k] = None
            elif lines[0] == "true":
                self.note("shallow clone %s: cited_path_changed skipped there, and it "
                          "never proves a commit missing" % top)
                self._hist[k] = None
                self._shallow.add(k)
            else:
                self._hist[k] = (norm_key(os.path.join(top, lines[1])), lines[2])
        return self._hist[k]

    def repos(self):
        """-> [(work tree, complete)] for the readable git repositories the
        cite resolver knows (each root's own); complete is False for a
        shallow clone."""
        if self._repos is None:
            seen, self._repos = set(), []
            for r in self.roots:
                top = self.toplevel(r)
                if top and norm_key(top) not in seen:
                    seen.add(norm_key(top))
                    if self.history_key(top) is not None:
                        self._repos.append((top, True))
                    elif norm_key(top) in self._shallow:
                        self._repos.append((top, False))
        return self._repos

    def _log(self, repo, since):
        """{path key: newest commit date} of `repo` since `since` (one day of
        slack before it): one batched `git log` per history. A later call
        that needs an older day reads only the missing span and merges it."""
        k = self.history_key(repo)
        if k is None:
            return {}
        got = self._logs.get(k)
        if got is not None and got[0] <= since:
            return got[1]
        start = (dt.date.fromisoformat(since) - dt.timedelta(days=1)).isoformat()
        span = ["--since=%s" % start]
        if got is not None:
            span.append("--until=%s" % (dt.date.fromisoformat(got[0]) + dt.timedelta(days=1)).isoformat())
        # A NUL marker opens each commit's date line, so a tracked file
        # named like a date is never read as a commit header.
        res = self._git(repo, ["-c", "core.quotePath=false", "log", "--name-only",
                               "--format=%x00%cs"] + span)
        if res is None or res[0] != 0:
            self.note("git log failed in %s: cited_path_changed skipped there" % repo)
            return got[1] if got is not None else {}
        dates, cur = (dict(got[1]) if got is not None else {}), None
        for line in res[1].split("\n"):
            line = line.rstrip("\r")
            if line.startswith("\x00"):
                cur = line[1:]
            elif line and cur:
                pk = line.casefold() if IS_WINDOWS else line
                if pk not in dates or dates[pk] < cur:
                    dates[pk] = cur
        self._logs[k] = (since, dates)
        return dates

    def changed_after(self, path, verified, since):
        """True when the file `path`, tracked in a git repository, last
        changed on a day strictly after `verified` (a same-day change is not
        seen)."""
        real = os.path.realpath(str(path))
        if not os.path.isfile(real):
            return False
        top = self.toplevel(os.path.dirname(real))
        if not top:
            return False
        rel = os.path.relpath(real, top).replace("\\", "/")
        if rel.startswith("../"):
            return False
        last = self._log(top, since).get(rel.casefold() if IS_WINDOWS else rel)
        return bool(last and last > verified)

    def missing_commits(self, shas):
        """The shas of `shas` that no known repository holds as a commit."""
        todo = sorted({s for s in shas if s not in self._commits})
        if todo:
            found, answered = set(), 0
            for repo, complete in self.repos():
                ask = [s for s in todo if s not in found]
                if not ask:
                    break
                res = self._git(repo, ["cat-file", "--batch-check"],
                                "".join("%s^{commit}\n" % s for s in ask).encode())
                lines = res[1].splitlines() if res is not None and res[0] == 0 else None
                if lines is None or len(lines) != len(ask):
                    self.note("git cat-file failed in %s: cited_commit_missing does not "
                              "rely on it" % repo)
                    continue
                # Only a complete repository can prove a commit absent; a
                # shallow one can still show it present.
                answered += 1 if complete else 0
                for s, line in zip(ask, lines):
                    # "<name> missing" only when absent; an ambiguous short
                    # sha is some object, so it is not reported.
                    if not line.endswith(" missing"):
                        found.add(s)
            if not answered and len(found) < len(todo):
                # Fail open: with no repository answering, nothing is known
                # missing, and nothing is cached so a later file may retry.
                self.note("no complete repository answered: cited_commit_missing skipped")
                return []
            for s in todo:
                self._commits[s] = s in found
        return [s for s in shas if self._commits.get(s) is False]

    def version(self, tool):
        if tool not in self._versions:
            self._versions[tool] = self._readers[tool]()
        return self._versions[tool]

    def stale_when(self, line):
        """-> None (not the version form), "fired", "not_fired" or "unknown"
        for one entry line."""
        m = _STALE_WHEN_VER_RE.match(line.strip())
        if not m:
            return None
        if m.group(1) not in STALE_WHEN_TOOLS:
            return "unknown"
        current = self.version(m.group(1))
        after = version_after(current, m.group(2)) if current else None
        if after is None:
            return "unknown"
        return "fired" if after else "not_fired"


def verified_day(body):
    """The entry's Verified date as YYYY-MM-DD; None when it has none; False
    when it has a date-shaped value that is not a real day (2026-02-30).
    The date is the first one memory-entries.py's verified() finds."""
    day = memory_entries().verified(body)
    if day is None:
        return None
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return False
    return day


def commit_tokens(body):
    """Backticked tokens shaped like a commit hash: 7-40 lowercase hex with
    at least one letter, so an all-digit number (a token count) is not one."""
    res = []
    for tok in _TICK_RE.findall(body):
        tok = tok.strip()
        if _SHA_RE.match(tok) and re.search(r"[a-f]", tok) and tok not in res:
            res.append(tok)
    return res


def build_entries(memory_file, own_roots, check, stems, today, anchors=None):
    try:
        text = read_text(memory_file)
    except OSError:
        return None
    parsed = parse_entries(text)
    since, shas = None, []
    for heading, body_lines in parsed:
        body = "\n".join(body_lines)
        vday = verified_day(body)
        if vday is False and anchors is not None:
            anchors.note("invalid Verified date in %s § %s: cited_path_changed not checked"
                         % (memory_file, heading))
        if vday and (since is None or vday < since):
            since = vday
        shas.extend(commit_tokens(body))
    gone = set(anchors.missing_commits(shas)) if anchors is not None and shas else set()
    out, seen = [], {}
    for heading, body_lines in parsed:
        seen[heading] = seen.get(heading, 0) + 1
        body = "\n".join(body_lines)
        missing, changed = [], []
        vday = verified_day(body)
        keep = lambda t: check.owner(t) is not None  # noqa: E731
        # cited_paths_missing reads the whole body: a path the entry names
        # anywhere that no longer exists can make its How to apply wrong.
        # cited_path_changed reads the Source anchor only: an edit to a file
        # merely mentioned in prose is noise (plan 261006 Step 9 D2).
        anchored = set(source_paths(body, keep_abs=keep))
        for c in cited_paths(body, keep_abs=keep):
            ok, where = check.locate(memory_file, own_roots, c)
            if not ok:
                missing.append(c)
            elif c in anchored and vday and anchors is not None and \
                    where is not None and anchors.changed_after(where, vday, since):
                changed.append(c)
        commits = [s for s in commit_tokens(body) if s in gone]
        when = set()
        if anchors is not None:
            for line in body_lines:
                got = anchors.stale_when(line)
                if got:
                    when.add(got)
                elif _STALE_WHEN_FIELD_RE.match(line) and "version" in line and ">" in line:
                    anchors.note("Stale-when line in %s § %s is not the version form "
                                 "`**Stale-when**: <tool> version > <x.y[.z]>` and sets no "
                                 "flag: %s" % (memory_file, heading, line.strip()[:120]))
        slugs = []
        for m in _SLUG_RE.finditer(body):
            full, title = m.group(0), m.group(1)
            if full in slugs:
                continue
            if not any(archive_matches(s, full) for s in stems):
                slugs.append(full)
        stale = False
        for line in body_lines:
            sm = _STALE_AFTER_RE.match(line.strip())
            if sm:
                d = parse_time(sm.group(1))
                stale = bool(d and today > d.date())
        out.append({"file": str(memory_file), "heading": heading,
                    "ordinal": seen[heading],
                    "cited_paths_missing": missing, "cited_slugs_missing": slugs,
                    "stale_after_passed": stale,
                    "governance_conflict_open": open_conflicts(body_lines),
                    "cited_path_changed": changed, "cited_commit_missing": commits,
                    "stale_when_fired": "fired" in when,
                    "stale_when_unknown": "unknown" in when})
        out[-1]["suspect"] = is_suspect(out[-1])
    return out


def is_suspect(entry):
    """memory-rules.md § Suspect memory entries: any flag but an open
    Governance-conflict selects the entry for a full check."""
    return any(f not in NON_SUSPECT_FLAGS for f in entry_flags(entry))


# --------------------------------------------------------------------------
# Plans (sweep-gather.md § GAT-PLANS)
# --------------------------------------------------------------------------

_PLAN_PREFIX_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})(?:-(\d{2})(\d{2}))?_")
_GOV_ARCHIVE_RE = re.compile(r"`([A-Za-z0-9_./-]*plans/done)/?`")


def _sections(text):
    """-> list of (level, heading, lines) fence-aware."""
    out, cur, fence = [], None, None
    for line in text.replace("\r\n", "\n").split("\n"):
        fm = memory_entries().FENCE_RE.match(line)
        if fence or fm:
            if fence and fm and fm.group(1) == fence:
                fence = None
            elif not fence and fm:
                fence = fm.group(1)
            if cur:
                cur[2].append(line)
            continue
        hm = re.match(r"^(#{1,4}) (.*)$", line)
        if hm:
            cur = (len(hm.group(1)), hm.group(2).strip(), [])
            out.append(cur)
            continue
        if cur:
            cur[2].append(line)
    return out


def _section_body(secs, pred, level=None):
    """Lines of the first section matching pred, including its sub-sections."""
    for i, (lv, h, lines) in enumerate(secs):
        if pred(h) and (level is None or lv == level):
            body = list(lines)
            for lv2, h2, l2 in secs[i + 1:]:
                if lv2 <= lv:
                    break
                body.append("#" * lv2 + " " + h2)
                body.extend(l2)
            return body
    return None


def _bullets(lines):
    items, cur = [], None
    for l in lines or []:
        if re.match(r"^\s*(?:[-*]|\d+\.)\s+", l):
            if cur:
                items.append(cur)
            cur = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", l).strip()
        elif cur is not None and l.strip() and l.startswith((" ", "\t")):
            cur += " " + l.strip()
        elif cur is not None and not l.strip():
            items.append(cur)
            cur = None
    if cur:
        items.append(cur)
    return items


def plan_facts(path):
    text = read_text(path)
    secs = _sections(text)
    title = next((h for lv, h, _ in secs if lv == 1), Path(path).stem)
    dm = re.search(r"^>\s*\*\*Date\*\*:\s*(\S+)", text, re.M)
    return text, secs, title, (dm.group(1) if dm else None)


def ack_label(bullet):
    """The disposition label a /qclose `Acknowledged at archival` bullet
    opens with ("Accepted (harness opportunity): ...", "**Skipped**: ...",
    "`Promoted: ...`"), lower-cased: accepted / skipped / promoted, or None."""
    m = re.match(r"^[`*\s]*(accept|skip|promot)", bullet, re.I)
    return {"accept": "accepted", "skip": "skipped", "promot": "promoted"}[m.group(1).lower()] \
        if m else None


def accept_and_note(secs):
    """Harness items /qclose Step 2 Pass 2 kept as Accept and note. When the
    plan has an `Acknowledged at archival` section, only its accepted harness
    bullets count (one labelled Skipped or Promoted never does, nor one whose
    text says it was promoted or skipped without an Accepted label), even
    when that leaves none; the whole `## Harness Improvement Opportunities`
    section is the fallback only for a plan archived without that section."""
    ack = _section_body(secs, lambda h: h.lower().startswith("acknowledged at archival"))
    if ack is not None:
        out = []
        for b in _bullets(ack):
            if not re.search(r"harness opportunit", b, re.I):
                continue
            label = ack_label(b)
            if label == "accepted" or (label is None and re.search(r"accept", b, re.I)
                                       and not re.search(r"\b(promoted|skipped)\b", b, re.I)):
                out.append(b)
        return out
    hio = _section_body(secs, lambda h: h.startswith("Harness Improvement Opportunities"), 2)
    return [b for b in _bullets(hio) if b.strip("* ").lower() != "reserved"]


def archive_added(archive):
    """file name -> (sha, aware datetime) of the newest commit that added it
    (no renames)."""
    out = git_out(archive, "log", "--no-renames", "--diff-filter=A",
                  "--format=%x01%H %cI", "--name-only", "--", ".")
    res = {}
    if out is None:
        return None
    cur = None
    for line in out.split("\n"):
        if line.startswith("\x01"):
            sha, _, when = line[1:].strip().partition(" ")
            cur = (sha, parse_time(when))
        elif line.strip() and cur is not None:
            name = line.strip().rsplit("/", 1)[-1]
            res.setdefault(name, cur)
    return res


def state_commit(state_path):
    """The commit that last modified the state file, or None when the file
    is uncommitted, modified in the work tree, or git is unavailable."""
    sp = Path(state_path)
    if not sp.is_file():
        return None
    out = git_out(sp.parent, "log", "-1", "--format=%H", "--", sp.name)
    if not out or not out.strip():
        return None
    dirty = git_out(sp.parent, "status", "--porcelain", "--", sp.name)
    if dirty is None or dirty.strip():
        return None
    return out.strip()


def prefix_time(name):
    m = _PLAN_PREFIX_RE.match(name)
    if not m:
        return None
    yy, mo, dd, hh, mi = m.groups()
    try:
        return dt.datetime(2000 + int(yy), int(mo), int(dd), int(hh or 0), int(mi or 0),
                           tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def cap_list(items, max_items, max_chars):
    """Keeps the first max_items items, each cut to max_chars characters (the
    only place an item is cut). -> (kept, number of items shortened)."""
    kept = [it if len(it) <= max_chars else it[:max_chars] for it in items[:max_items]]
    return kept, sum(1 for it in items[:max_items] if len(it) > max_chars)


def plan_excerpt(rows, rlines):
    """new_plans excerpt: each list capped on its own (PLAN_DECISIONS_MAX
    rows, PLAN_REVIEW_LOG_MAX lines, PLAN_ITEM_MAX_CHARS per item), so a long
    decisions table never crowds out the review log. -> (decisions,
    review_log, truncated): truncated is False, or the kept/total counts."""
    dec, n1 = cap_list(rows, PLAN_DECISIONS_MAX, PLAN_ITEM_MAX_CHARS)
    rev, n2 = cap_list(rlines, PLAN_REVIEW_LOG_MAX, PLAN_ITEM_MAX_CHARS)
    if len(dec) == len(rows) and len(rev) == len(rlines) and not (n1 or n2):
        return dec, rev, False
    return dec, rev, {"decisions": {"kept": len(dec), "total": len(rows)},
                      "review_log": {"kept": len(rev), "total": len(rlines)},
                      "items_shortened": n1 + n2}


_MEMORY_RELIED_RE = re.compile(r"^>[ \t]*\*\*Memory relied on\*\*:[ \t]*(.*)$", re.M)
_MEMORY_SEP_RE = re.compile(r"(?:^|(?<=\s))\|(?=\s|$)")
# A code span: a run of N backticks, then the next run of exactly N (CommonMark),
# so ``a | b`` and ``a`b`` are spans; a run with no closing run is no span.
_BACKTICK_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)")


def _is_none_value(text):
    """True for an empty value or `none`: a trailing `.` and surrounding
    backticks stripped, any case."""
    return text.rstrip(".").strip().strip("`").rstrip(".").strip().lower() in ("", "none")


def memory_relied_on(text):
    """The plan header's `> **Memory relied on**:` line (Usage feeder,
    memory-rules.md § Derived Utility & Pruning), read from the header only
    (before the first `## ` heading); the label is case-sensitive, and when
    the header holds two such lines the first wins. -> (headings,
    truncated). headings is None when the line is absent; [] for an empty
    value or `none` (a trailing `.` and surrounding backticks stripped, any
    case); else the ` | `-separated headings (a `;` or `,` stays inside its
    heading, and so does a ` | ` inside a backticked span of any backtick
    run length, `` ` `` or ``` `` ```; an unclosed run is no span), stripped, a
    heading that is itself `none` dropped (`none | A` gives ["A"]), at most
    PLAN_MEMORY_MAX of them, each cut to PLAN_MEMORY_MAX_CHARS. truncated
    is False or {kept, total, items_shortened, shortened}: shortened lists
    the 0-based indexes of the kept headings that were cut."""
    head = re.split(r"^## ", text, maxsplit=1, flags=re.M)[0]
    m = _MEMORY_RELIED_RE.search(head)
    if not m:
        return None, False
    value = m.group(1).strip()
    if _is_none_value(value):
        return [], False
    # ` | ` separates; a `|` at either end of the value (already stripped)
    # is a separator too, so a trailing ` |` adds no empty heading. The
    # boundaries are zero-width, so `A | | B` gives two headings; a `|`
    # touching a non-space character, or inside a backticked span, stays
    # inside its heading.
    spans = [mm.span() for mm in _BACKTICK_SPAN_RE.finditer(value)]
    parts, last = [], 0
    for sep in _MEMORY_SEP_RE.finditer(value):
        if any(a <= sep.start() < b for a, b in spans):
            continue
        parts.append(value[last:sep.start()])
        last = sep.end()
    parts.append(value[last:])
    items = [h.strip() for h in parts if h.strip() and not _is_none_value(h)]
    kept, n = cap_list(items, PLAN_MEMORY_MAX, PLAN_MEMORY_MAX_CHARS)
    if len(kept) == len(items) and not n:
        return kept, False
    return kept, {"kept": len(kept), "total": len(items), "items_shortened": n,
                  "shortened": [i for i, h in enumerate(items[:PLAN_MEMORY_MAX])
                                if len(h) > PLAN_MEMORY_MAX_CHARS]}


def build_plans(project_dir, plans_dir, baseline, errors, since_commit=None):
    """plans block for one project; plans_dir is its resolved project-file
    class directory (workspace or store plans/). since_commit: the commit
    that last modified the state file (see the module docstring)."""
    archive, source = None, None
    for gov in ("AGENTS.md", "CLAUDE.md"):
        g = Path(project_dir) / gov
        if not g.is_file():
            continue
        try:
            for rel in _GOV_ARCHIVE_RE.findall(read_text(g)):
                cand = Path(project_dir) / rel
                if rel.strip("/") != "plans/done" and cand.is_dir():
                    archive, source = cand, "governance"
                    break
        except OSError:
            pass
        if archive:
            break
    if archive is None and plans_dir and (Path(plans_dir) / "done").is_dir():
        archive, source = Path(plans_dir) / "done", "default"
    block = {"archive": str(archive) if archive else None,
             "archive_source": source, "new_plans": []}
    if archive is None:
        return block
    files = sorted((f for f in archive.glob("*.md") if not f.name.startswith(".handoff-")),
                   key=lambda f: f.name)
    added = archive_added(archive) or {}
    ancestry = bool(since_commit) and baseline is not None and \
        git_rc(archive, "cat-file", "-e", since_commit + "^{commit}") == 0
    new = []
    for f in files:
        info = added.get(f.name)
        if ancestry and info:
            rc = git_rc(archive, "merge-base", "--is-ancestor", info[0], since_commit)
            if rc == 0:
                continue
            if rc == 1:
                new.append(f)
                continue
        t = (info[1] if info else None) or prefix_time(f.name)
        if baseline is None or t is None or t > baseline or (
                f.name not in added and t.date() >= baseline.date()):
            new.append(f)
    # recent and accept_and_note cover every archived plan on every sweep,
    # new or not (the harness harvest re-reads them each time); only the
    # new_plans excerpts are limited to new plans.
    facts = {}
    for f in files:
        try:
            facts[f.name] = plan_facts(f)
        except OSError as e:
            errors.append("unreadable plan %s: %s" % (f, e))
    for f in new:
        if f.name not in facts:
            continue
        _text, secs, title, date = facts[f.name]
        dec = _section_body(secs, lambda h: "Design Decisions" in h or
                            h.lower().startswith("resolved decisions"))
        rows, prev_row = [], False
        for l in dec or []:
            is_row = l.strip().startswith("|")
            if is_row and prev_row and not re.match(r"^\|[\s:|-]+\|$", l.strip()):
                rows.append(l.strip())
            prev_row = is_row
        rows = [r for r in rows if r] + _bullets(dec)
        rl = _section_body(secs, lambda h: h == "Review Log", 2) or []
        rlines = [l.rstrip() for l in rl if l.strip()]
        rows, rlines, cut = plan_excerpt(rows, rlines)
        relied, relied_cut = memory_relied_on(_text)
        block["new_plans"].append({"file": f.name, "title": title, "date": date,
                                   "decisions": rows, "review_log": rlines,
                                   "truncated": cut, "memory_relied_on": relied,
                                   "memory_relied_on_truncated": relied_cut})
    recent = []
    for f in sorted(files, key=lambda f: f.name, reverse=True)[:RECENT_PLANS]:
        if f.name not in facts:
            continue
        _text, secs, title, date = facts[f.name]
        intent = _section_body(secs, lambda h: h == "Intent", 2) or []
        recent.append({"file": f.name, "title": title, "date": date,
                       "intent": _nl(" ".join(intent))[:INTENT_MAX_CHARS]})
    block["recent"] = recent
    block["accept_and_note"] = [{"plan": n, "item": it} for n in sorted(facts)
                                for it in accept_and_note(facts[n][1])]
    return block


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def has_markers(p, unmarked=()):
    """True when p holds a project marker. `unmarked` lists norm_keys whose
    markers do not count: the config repo's shared/ and providers/, whose
    AGENTS.md is the deployed global file, never a project."""
    p = Path(p)
    if unmarked and norm_key(p) in unmarked:
        return False
    return (p / "memory" / "MEMORY.md").is_file() or (p / "AGENTS.md").is_file() \
        or (p / "plans").is_dir()


def home_pruned(parent, name, home_parts):
    """True for AppData, Library and OneDrive* directly under home: never
    project trees, and the largest folders a home holds."""
    if _parts(os.path.realpath(parent)) != home_parts:
        return False
    return name in HOME_PRUNE_NAMES or name.startswith(HOME_PRUNE_PREFIXES)


def md_populated(d):
    d = Path(d)
    if not d.is_dir():
        return False
    return any(not f.name.startswith(".handoff-") for f in d.rglob("*.md"))


class Project:
    def __init__(self, path):
        self.path = path
        self.by = []
        self.sessions = []
        self.errors = []
        self.in_state = False
        self.empty_sessions = []      # ids: Kiro session dirs without messages.jsonl
        self.older_not_read = []      # sessions before a new project's baseline
        self.state_key = None         # the state file's verbatim key
        self.fork_collapsed = []      # Claude fork duplicates not listed
        self.store_dir = None         # plan 261016 Phase 5: set for a store-only project (no checkout)
        self.store_note = None        # a `store:` state key no store directory is attached to: why it is kept
        self.store_superseded = False  # that key is reported `removed`: a checkout with its own state entry serves it

    @property
    def is_store_key(self):
        """True for a project that is a store, keyed `store:<identity>` (never a path, never probed as one)."""
        return self.path.startswith(STORE_KEY_PREFIX)


def first_cwd(path, limit=200):
    try:
        with open(str(path), "rb") as fh:
            for i, raw in enumerate(fh):
                if i >= limit:
                    break
                try:
                    obj = json.loads(raw.decode("utf-8", errors="replace").lstrip("﻿"))
                except (ValueError, RecursionError):
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("cwd"), str) and obj["cwd"]:
                    return obj["cwd"]
    except OSError:
        return None
    return None


def load_history(path, errors):
    """-> (by_session {sid: [(ts, display, lineno, project)]}, sessionless list)"""
    by, loose = {}, []
    if not Path(path).is_file():
        return by, loose
    try:
        recs, errs = read_jsonl(path)
    except OSError as e:
        errors.append("unreadable %s: %s" % (path, e))
        return by, loose
    errors.extend(errs)
    for ln, r in recs:
        ts = parse_time(r.get("timestamp"))
        disp = r.get("display") if isinstance(r.get("display"), str) else ""
        proj = r.get("project") if isinstance(r.get("project"), str) else None
        item = (ts, disp, ln, proj)
        sid = r.get("sessionId")
        if isinstance(sid, str) and sid:
            by.setdefault(sid, []).append(item)
        else:
            loose.append(item)
    return by, loose


def kiro_active(meta):
    """True when a Kiro session.json shows use: lastModifiedAt more than
    KIRO_ACTIVITY_SECONDS after createdAt (an unparseable or missing time
    shows none)."""
    c, m = parse_time(meta.get("createdAt")), parse_time(meta.get("lastModifiedAt"))
    return c is not None and m is not None and \
        (m - c).total_seconds() > KIRO_ACTIVITY_SECONDS


def kiro_subagent(meta):
    """True when a Kiro session.json belongs to a sub-agent or workflow node,
    not a user session: kiro-cli 2.28.0 writes those as full session folders
    beside the parent's, whose `rootConversationId` names the parent. A
    top-level session has no such key; a session naming itself is top-level."""
    root = meta.get("rootConversationId")
    return isinstance(root, str) and bool(root) and root != meta.get("id")


class Run:
    def __init__(self, args, ctx):
        self.args, self.ctx = args, ctx
        # An absolute path: a relative --repo (`.`) would put relative memory
        # file paths in user_memory.json, which dream-sweep.py dirty records as
        # candidates and drift then refuses as outside the config repo.
        self.repo = Path(canon_path(args.repo if _ABS_RE.match(args.repo)
                                    else os.path.abspath(args.repo)))
        self.claude_home = Path(args.claude_home) if args.claude_home else ctx.home / ".claude"
        self.kiro_home = Path(args.kiro_home) if args.kiro_home else ctx.home / ".kiro"
        # The config repo's shared/ and providers/ are part of the repo, never
        # projects: Method B does not descend into them, and their markers
        # (shared/AGENTS.md) neither name a subdirectory_of parent nor keep a
        # project alive.
        self.unmarked = {norm_key(self.repo / d) for d in ("shared", "providers")}
        self.errors = []
        self.projects = {}
        self.exclude = set(args.exclude_session or [])
        # A copy named by --full keys through its parent, like every other path.
        self.full = {self.pkey(f): canon_path(worktree_parent(f) or f) for f in args.full or []}
        self.empty_unattributed = []
        self.state_copies = []      # state keys naming a worktree copy
        self._arts = {}             # (project key, kind) -> the resolver's Artifact
        self._rc = {}               # (project key, kind) -> (directory or None, error or None)
        self.store_scan = ("ok", [], [], "")   # the store repo scan of this run: (status, valid, invalid, why)

    def pkey(self, path):
        """The self.projects key a session or history cwd attributes to: a
        worktree copy attributes to its parent project."""
        return norm_key(canon_path(worktree_parent(path) or path))

    def skip_worktree(self, path, parent, what):
        """errors[] note for one worktree copy kept out of the project list
        (once per copy and reason)."""
        line = "worktree copy %s is not a project (%s)" % (path, what % parent)
        if line not in self.errors:
            self.errors.append(line)

    def project(self, path, how):
        parent = worktree_parent(path)
        if parent is not None:
            self.skip_worktree(path, parent, "its sessions and history count toward %s")
            path = parent
        path = canon_path(path)
        k = norm_key(path)
        p = self.projects.get(k)
        if p is None:
            p = self.projects[k] = Project(path)
        if how and how not in p.by:
            p.by.append(how)
        return p

    # -- state -----------------------------------------------------------
    def load_state(self):
        st = Path(self.args.state)
        self.first_run = not st.is_file()
        self.state = {} if self.first_run else load_json(st)
        if self.state is None or not isinstance(self.state, dict):
            raise Usage("state file is not valid JSON: %s" % st)
        # Baseline of a project absent from the state file (user decision
        # 2026-09-24, option A): the state's last_run -- its older sessions
        # are counted (older_sessions_not_read), not read; --full <path>
        # reads a project's whole history. With no state file (first run) or
        # no usable last_run: the config repo's last commit time.
        self.new_baseline, self.new_rule = None, "first_run_commit"
        last_run = None if self.first_run else parse_time(self.state.get("last_run"))
        self.last_run = last_run
        if last_run is not None:
            self.new_baseline, self.new_rule = last_run, "last_run"
        else:
            if not self.first_run:
                self.errors.append("state file has no valid last_run; projects absent from it "
                                   "are read from the config repo's last commit time")
            out = git_out(self.repo, "log", "--format=%aI", "-1")
            self.new_baseline = parse_time(out.strip()) if out else None
            if self.new_baseline is None:
                # Never label an unread time first_run_commit: read in full.
                self.new_rule = "full"
                self.errors.append("config repo's last commit time is unreadable (git log failed "
                                   "in %s); projects absent from the state file are read in full"
                                   % self.repo)
        for path, meta in (self.state.get("projects") or {}).items():
            parent = worktree_parent(path)
            if parent is not None:
                # Not a project, so no state of its own: reported as removed
                # (build) so the Removed-projects acknowledgement can drop
                # exactly this key; the parent's entry is not touched.
                self.skip_worktree(path, parent, "its state entry is reported as removed; "
                                                 "state for %s is not changed")
                self.state_copies.append(path)
                continue
            p = self.project(path, "state")
            p.in_state = True
            if p.state_key is None:
                p.state_key = path
            p.last_analyzed = parse_time((meta or {}).get("last_analyzed"))
        self.deferred = self.state.get("deferred_sessions") or {}
        # A missing quiet_sweeps section counts as {}; a present value
        # that is not an object (null included) is named in errors[] and
        # seeded, since both validators FAIL it.
        self.quiet = self.state.get("quiet_sweeps", {})
        if not isinstance(self.quiet, dict):
            self.errors.append("state quiet_sweeps is not an object (%r); every value is seeded"
                               % (self.quiet,))
            self.quiet = {}
        qp = self.quiet.get("projects", {})
        if not isinstance(qp, dict):
            self.errors.append("state quiet_sweeps.projects is not an object (%r); every project "
                               "value is seeded" % (qp,))
        self.quiet_projects = quiet_index(qp)
        self.state_commit = state_commit(st)

    def quiet_value(self, v, where):
        """A present stored quiet_sweeps value, or None when it is invalid
        (null, negative, not an integer, or above INT64_MAX, as both
        validators rule): then it is named in errors[] and seeded. Callers
        pass only values whose key is present; an absent key is seeded
        silently."""
        if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= INT64_MAX:
            return v
        self.errors.append("state quiet_sweeps %s is not a non-negative integer (%r); seeded"
                           % (where, v))
        return None

    def stored_quiet(self, k):
        if k not in self.quiet_projects:
            return None
        key, v = self.quiet_projects[k]
        return self.quiet_value(v, "projects[%r]" % key)

    def baseline_rule(self, p):
        if norm_key(p.path) in self.full:
            return "full"
        return "state" if p.in_state else self.new_rule

    def baseline(self, p):
        rule = self.baseline_rule(p)
        if rule == "full":
            return None
        if rule == "state":
            return getattr(p, "last_analyzed", None)
        return self.new_baseline

    def count_older(self, p, parsed, provider, sid, kind):
        """A session of a project absent from the state that holds records
        but none after the project's baseline: not read, only listed (id and
        last activity) so a --full recovery is informed."""
        if parsed.recs and self.baseline_rule(p) in ("last_run", "first_run_commit"):
            times = [r[3] for r in parsed.recs if r[3] is not None]
            p.older_not_read.append({"id": sid, "provider": provider, "kind": kind,
                                     "last_activity": iso(max(times)) if times else None})

    # -- stores ----------------------------------------------------------
    def scan_claude(self):
        self.claude_sessions = []           # (sid, path, slug_dir, cwd)
        home = self.claude_home
        self.hist_by, self.hist_loose = load_history(home / "history.jsonl", self.errors)
        pdir = home / "projects"
        if not pdir.is_dir():
            return
        try:
            slugs = sorted(d for d in pdir.iterdir() if d.is_dir())
        except OSError as e:
            self.errors.append("unreadable %s: %s" % (pdir, e))
            return
        for slug in slugs:
            try:
                self._scan_claude_slug(slug)
            except OSError as e:
                self.errors.append("unreadable %s: %s" % (slug, e))
        for sid, f, slug, cwd in self.claude_sessions:
            if cwd:
                self.project(cwd, "A")
            elif sid not in self.exclude:
                self.errors.append("unattributed Claude session %s (no cwd, no history record)" % f)

    def _scan_claude_slug(self, slug):
        for f in sorted(slug.glob("*.jsonl")):
            sid = f.stem
            cwd = first_cwd(f)
            if cwd is None:
                hist = self.hist_by.get(sid) or []
                cwd = next((h[3] for h in hist if h[3]), None)
            self.claude_sessions.append((sid, f, slug, cwd))
        # sub-agent transcripts: discovery only (Method A counts them),
        # never a session of their own and never user speech (isSidechain).
        for sub in sorted(slug.glob("*/subagents/*.jsonl")):
            cwd = first_cwd(sub)
            if cwd:
                self.project(cwd, "A")

    def scan_kiro(self):
        self.kiro_sessions = []             # (sid, dir, meta, workspace)
        sdir = self.kiro_home / "sessions"
        if not sdir.is_dir():
            return
        for hdir in sorted(d for d in sdir.iterdir() if d.is_dir() and d.name != "cli"):
            for sj in sorted(hdir.glob("sess_*/session.json")):
                meta = load_json(sj)
                if not isinstance(meta, dict):
                    self.errors.append("unreadable %s" % sj)
                    continue
                if kiro_subagent(meta):
                    continue    # its parent's session is the user's; see kiro_subagent
                wps = meta.get("workspacePaths") or []
                ws = wps[0] if isinstance(wps, list) and wps and isinstance(wps[0], str) \
                    and wps[0] else None
                sid = meta.get("id") if isinstance(meta.get("id"), str) else sj.parent.name
                self.kiro_sessions.append((sid, sj.parent, meta, ws))
                if ws:
                    self.project(ws, "A")
                elif sid in self.exclude:
                    continue
                elif not os.path.lexists(str(sj.parent / "messages.jsonl")) and \
                        not kiro_active(meta):
                    self.empty_unattributed.append(sid)
                else:
                    self.errors.append("Kiro session %s has no workspacePaths (not attributed "
                                       "to any project, not read): %s" % (sid, sj))

    def discover(self):
        R = resolver()
        excluded = sorted(self.unmarked) + [norm_key(R.store_repo_root())]   # Method B never walks the store repo
        # Method C (plan 261016 Phase 5): every STORE names its folder (`local`) or its remote. A `local` store whose
        # folder exists is a project here; the other stores are mapped at the end of discovery.
        st, valid, invalid, why = R.scan_stores()
        # A failed scan lists the stores read before the failure; none of them is trusted (the scan is failed).
        self.store_scan = (st, valid if st == "ok" else [], invalid, why)
        if st != "ok" and not why.startswith(R.MISSING_ROOT):
            # A reader fails open: project memory and plans are not read this run, and no store-only project
            # can be listed. Said once here; a store-only state key says it too.
            self.errors.append("%s %s; project memory and plans in it are not read this run, and "
                               "store-only projects are not listed (resolve it with /qconfig-sync)"
                               % (STORE_REPO_UNREADABLE, why))
        for sdir, ident in self.store_scan[1]:
            if ident.kind == "local" and Path(ident.value).is_dir():
                self.project(ident.value, "C")
        for add in self.args.add or []:
            self.project(add, "add")
        # Method B: below every Method-A path, any directory holding
        # memory/MEMORY.md or AGENTS.md is a project. A root that is the home
        # directory, a filesystem root or an ancestor of home is not walked
        # (a session started there would otherwise walk the whole disk); a
        # root the walk of an outer root already covers is walked once.
        home_real = _parts(os.path.realpath(str(self.ctx.home)))
        cands = []
        for p in list(self.projects.values()):
            if "A" not in p.by or not Path(p.path).is_dir():
                continue
            real = os.path.realpath(p.path)
            rp = _parts(real)
            why = None
            if rp == home_real:
                why = "it is the home directory"
            elif Path(real).parent == Path(real):
                why = "it is a filesystem root"
            elif len(rp) < len(home_real) and home_real[:len(rp)] == rp:
                why = "it is an ancestor of the home directory"
            elif self.in_store_repo(p.path):
                why = "it is at or inside the store repo"
            if why:
                self.errors.append("Method B: not walking %s: %s" % (p.path, why))
                continue
            cands.append((len(rp), p.path, real))
        cands.sort()
        root_keys = {norm_key(r) for _d, _p, r in cands}
        walked, n_dirs, n_roots, n_nested = set(), 0, 0, 0
        started = time.monotonic()
        for _depth, root, root_real in cands:
            if norm_key(root_real) in walked:
                n_nested += 1
                continue
            n_roots += 1
            # depth counts from the nearest root, so a nested root reached by
            # an outer walk still gets its own STRUCT_MAX_DEPTH levels.
            anchor = {root: len(Path(root).parts)}
            for cur, dirs, files in os.walk(root):
                n_dirs += 1
                rel = os.path.relpath(cur, root)
                cur_key = norm_key(os.path.normpath(os.path.join(root_real, rel)))
                walked.add(cur_key)
                a = len(Path(cur).parts) if cur_key in root_keys else anchor.pop(cur, len(Path(root).parts))
                depth = len(Path(cur).parts) - a
                keep = []
                for d in dirs:
                    full = os.path.join(cur, d)
                    if d in PRUNE_DIRS or d.startswith("."):
                        continue
                    if norm_key(full) in excluded or home_pruned(cur, d, home_real):
                        continue
                    keep.append(d)
                dirs[:] = keep if depth < STRUCT_MAX_DEPTH else []
                for d in dirs:
                    anchor[os.path.join(cur, d)] = a
                if cur == root:
                    continue
                if "AGENTS.md" in files or os.path.isfile(os.path.join(cur, "memory", "MEMORY.md")):
                    self.project(cur, "B")
        print("method B: walked %d directories under %d root(s) (%d nested root(s) skipped) "
              "in %.2fs" % (n_dirs, n_roots, n_nested, time.monotonic() - started),
              file=sys.stderr)
        self.add_store_only_projects()

    def add_store_only_projects(self):
        """plan 261016 Phase 5. Each store-repo store that no known project resolves to (find(path)) is read
        for its memory pass as a project of its own, keyed by its STORE identity. A store no project maps
        to has no checkout that a session, the state file or a `local` identity names.

        A `store:` key the state file holds but no store directory is attached to this run is not a path and
        is never probed as one. It is kept (store_note says why) when the store repo cannot be read, when its
        store directory exists but the STORE file is invalid, or when a checkout now serves the store and has no
        state entry of its own; it is `removed` when the store directory is gone from a readable store repo or
        when the serving checkout has its own state entry ("superseded by <checkout>", in errors[])
        (project_status)."""
        R = resolver()
        st, valid, invalid, why = self.store_scan
        served = {}     # norm_key(store dir) -> the first checkout path that find() maps to it
        for p in list(self.projects.values()):
            if p.store_dir is not None or p.is_store_key:
                continue
            res = R.find(p.path)
            if res.status == "found":
                served.setdefault(norm_key(res.path), p.path)
        keys = {}       # norm_key(store key) -> (checkout path serving the store or None)
        for sdir, ident in valid:
            key = STORE_KEY_PREFIX + R.store_key(ident)
            keys[norm_key(key)] = served.get(norm_key(sdir))
            if norm_key(sdir) in served:
                continue
            p = self.project(key, "C")
            p.store_dir = Path(sdir)
        for k, p in list(self.projects.items()):
            if not p.is_store_key or p.store_dir is not None or not p.in_state:
                continue
            if st != "ok":
                p.store_note = ("store %s: the store repo could not be read this run (%s), so the store cannot be "
                                "checked; its state entry is kept" % (p.path[len(STORE_KEY_PREFIX):], why))
            elif keys.get(k) is not None:
                server = self.projects.get(norm_key(keys[k]))
                if server is not None and server.in_state:
                    # the checkout has its own state entry: this one is dead weight, and the sweep's removal
                    # acknowledgement drops it
                    p.store_superseded = True
                    p.store_note = ("store %s: superseded by %s, a checkout with its own state entry that now "
                                    "serves this store" % (p.path[len(STORE_KEY_PREFIX):], keys[k]))
                else:
                    p.store_note = ("store %s: the checkout %s now serves this store and carries its sessions and "
                                    "memory; this state entry names no project this run and is kept"
                                    % (p.path[len(STORE_KEY_PREFIX):], keys[k]))
            else:
                bad = R.invalid_store_for_key(p.path[len(STORE_KEY_PREFIX):], invalid)
                if bad is not None:
                    p.store_note = ("store %s: its store directory %s exists but its STORE file is invalid, so the "
                                    "store cannot be read this run; its state entry is kept"
                                    % (p.path[len(STORE_KEY_PREFIX):], bad))

    # -- per project ----------------------------------------------------
    def attach_sessions(self):
        def setting_days(path, key):
            settings = load_json(path)
            value = settings.get(key) if isinstance(settings, dict) else None
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        # Deletion age per provider; a provider without one gets no due flag.
        claude_days = setting_days(self.claude_home / "settings.json", "cleanupPeriodDays")
        self.due_days = {}
        for provider, days in (
                ("claude", DEFAULT_CLEANUP_DAYS if claude_days is None else claude_days),
                ("kiro", setting_days(self.kiro_home / "settings" / "cli.json", KIRO_CLEANUP_KEY))):
            if days is not None:
                self.due_days[provider] = max(1, days - DUE_MARGIN_DAYS)
        self.skills = SkillIndex.from_repo(self.repo)
        self.watermarks_to_clear = []
        local = set()
        local_texts = {}      # project key -> normalized genuine user texts
        selected = []         # (project, sid, file, parsed, boundary)
        uuid_sets = {}        # file -> (sid, record uuids) of every parsed local transcript
        for sid, f, slug, cwd in self.claude_sessions:
            if sid in self.exclude or not cwd:
                local.add(sid)
                continue
            p = self.projects[self.pkey(cwd)]
            try:
                parsed = parse_claude(f, sid, self.hist_by, self.skills)
            except Exception as e:  # one bad file never stops the run
                p.errors.append("unreadable %s: %s: %s" % (f, type(e).__name__, e))
                local.add(sid)
                continue
            p.errors.extend(parsed.errors)
            if not parsed.recs and self._history_after(sid, self.baseline(p)):
                # A local file with no conversation records while history
                # holds post-baseline prompts: read those prompts instead.
                p.errors.append("Claude transcript %s has no conversation records; its "
                                "history.jsonl prompts are listed as history_only" % f)
                continue
            local.add(sid)
            local_texts.setdefault(self.pkey(cwd), set()).update(parsed.user_texts)
            uuid_sets[str(f)] = (sid, set(parsed.uuid_lines))
            b = select(parsed, self.baseline(p))
            if b is not None:
                selected.append((p, sid, f, parsed, b))
            else:
                self.count_older(p, parsed, "claude", sid, "normal")
        # Fork duplicates resolve per project, among its selected sessions
        # only: a session whose keeper is elsewhere (another project, or not
        # selected) is kept, so no user turn is dropped, and named in errors[].
        # Transcripts are keyed by file: one session id may have two files.
        fork_groups = {}
        for p, sid, f, parsed, b in selected:
            fork_groups.setdefault(id(p), []).append((str(f), sid, parsed, b))
        resolved = {k: resolve_forks(g) for k, g in fork_groups.items()}
        used = set()
        for p, sid, f, parsed, b in selected:
            b, fork, skip = resolved[id(p)][str(f)]
            if fork and fork["kind"] == "full":
                if fork["of"] == sid:
                    p.errors.append("Claude session %s has a second transcript file %s whose every "
                                    "record is also in %s; only the latter is listed"
                                    % (sid, f, fork["of_key"]))
                else:
                    p.fork_collapsed.append({"dropped": sid, "kept": fork["of"],
                                             "shared_records": fork["shared"]})
                continue
            other = outside_keeper(str(f), sid, uuid_sets[str(f)][1],
                                   {g[0] for g in fork_groups[id(p)]}, uuid_sets)
            if other is not None:
                p.errors.append("every record of Claude session %s is also in session %s (%s), a "
                                "fork in another project or not selected in this one; %s is kept "
                                "so no turn is dropped" % (sid, other[1], other[0], sid))
            s = self.session("claude", sid, f, parsed.recs, b, "normal", p.path, skip)
            if s["stripped"] in used:
                # a second listed file of one session id gets its own stripped file
                p.errors.append("Claude session %s has more than one transcript file with turns "
                                "of its own; %s is listed too" % (sid, f))
                n = 2
                while s["stripped"][:-4] + "-%d.txt" % n in used:
                    n += 1
                s["stripped"] = s["stripped"][:-4] + "-%d.txt" % n
            used.add(s["stripped"])
            p.sessions.append(s)
        # History-only sessions (bridge / cloud): prompt text only.
        groups = {}
        for sid, items in self.hist_by.items():
            if sid in local or sid in self.exclude:
                continue
            for it in items:
                if it[3]:
                    groups.setdefault((self.pkey(it[3]), sid), []).append(it)
        for it in self.hist_loose:
            # A sessionless entry whose text a local transcript of the same
            # project already holds is not a coverage gap.
            if it[3] and _nl(it[1]) not in local_texts.get(self.pkey(it[3]), ()):
                groups.setdefault((self.pkey(it[3]), "no-session-id"), []).append(it)
        for (pkey, sid), items in sorted(groups.items()):
            proj = items[0][3]
            known = self.projects.get(pkey)
            base = self.baseline(known) if known else \
                (None if pkey in self.full else self.new_baseline)
            recs = [(ln, "user", self.skills.replace_bodies(disp), ts)
                    for ts, disp, ln, _ in items if disp.strip()]
            parsed = Parsed()
            parsed.recs = recs
            b = select(parsed, base)
            # A project history names and no other method found is listed
            # even when all its prompts predate the baseline: dropping it
            # would hide it from the sweep (its sessions are counted).
            if b is not None or known is None:
                p = self.project(proj, "A")
            else:
                p = known
            if b is not None:
                p.sessions.append(self.session("claude", sid, self.claude_home / "history.jsonl",
                                               recs, b, "history_only", p.path))
            else:
                self.count_older(p, parsed, "claude", sid, "history_only")
        for sid, sdir, meta, ws in self.kiro_sessions:
            if sid in self.exclude or not ws:
                continue
            p = self.projects[self.pkey(ws)]
            msgs = sdir / "messages.jsonl"
            if not os.path.lexists(str(msgs)):
                if kiro_active(meta):
                    p.errors.append("Kiro session %s shows activity (lastModifiedAt %s, createdAt "
                                    "%s) but has no messages.jsonl (not read): %s"
                                    % (sid, meta.get("lastModifiedAt"), meta.get("createdAt"), sdir))
                else:
                    # An empty session (created, never used): listed, not an error.
                    p.empty_sessions.append(sid)
                continue
            try:
                parsed = parse_kiro(msgs, self.skills)
            except Exception as e:
                p.errors.append("unreadable %s: %s: %s" % (msgs, type(e).__name__, e))
                continue
            p.errors.extend(parsed.errors)
            key = "kiro:%s" % sid
            wm = self.deferred.get(key)
            wm_line = parsed.ids.get(wm.get("last_record")) if isinstance(wm, dict) else None
            kind = "normal"
            last_mod = parse_time(meta.get("lastModifiedAt"))
            if meta.get("status") == "in_progress" and last_mod is not None and \
                    self.ctx.now - last_mod < dt.timedelta(hours=DEFERRED_HOURS):
                kind = "deferred"
            if wm_line is not None and kind != "deferred":
                self.watermarks_to_clear.append(key)
            b = select(parsed, self.baseline(p), wm_line)
            if b is not None:
                s = self.session("kiro", sid, msgs, parsed.recs, b, kind, p.path)
                if kind == "deferred":
                    s["last_record"] = parsed.last_id
                p.sessions.append(s)
            elif wm_line is None:
                self.count_older(p, parsed, "kiro", sid, "normal")
        self.watermarks_to_clear.sort()

    def _history_after(self, sid, baseline):
        return any(baseline is None or (ts is not None and ts > baseline)
                   for ts, disp, _ln, _proj in self.hist_by.get(sid, []) if disp.strip())

    def session(self, provider, sid, source, recs, boundary, kind, project_path, skip=None):
        header = ["# dream-manifest stripped transcript",
                  "# session: %s  provider: %s  kind: %s" % (sid, provider, kind),
                  "# source: %s" % source]
        skip = skip or set()
        n_skip = sum(1 for r in recs if r[0] in skip)
        if n_skip:
            header.append("# fork: %d shared record(s) after the boundary left out; the "
                          "session that keeps them shows them" % n_skip)
        preface = None
        if kind == "history_only":
            preface = "[coverage gap: history.jsonl prompt text only -- no transcript, no assistant content]"
        text = render(header, recs, boundary, preface, skip)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", sid)
        # The project hash keeps two projects' sessions of one id (history's
        # "no-session-id" groups) in two files.
        ph = hashlib.sha256(norm_key(project_path).encode("utf-8")).hexdigest()[:8]
        times = [r[3] for r in recs if r[3] is not None]
        return {"id": sid, "provider": provider, "source": str(source),
                "first_activity": iso(min(times)) if times else None,
                "stripped": "sessions/%s-%s-%s%s.txt" % (provider, safe, ph,
                                                        "-history" if kind == "history_only" else ""),
                "bytes": len(text.encode("utf-8")),
                "boundary": boundary if boundary == "unknown" else "L%d" % boundary,
                "kind": kind, "_text": text}

    def art(self, p, kind):
        """The store resolver's read of one artifact class of project `p` (plan 261016): the first
        store-repo store that holds content, walking up from the project folder to its repo toplevel (the
        config repo's plans are its own plans/). A store-only project is its store."""
        key = (norm_key(p.path), kind)
        if key not in self._arts:
            R = resolver()
            if p.is_store_key and p.store_dir is None:
                self._arts[key] = R.Artifact("none", None, None, None)   # a key, not a folder: nothing to resolve
            elif p.store_dir is not None:
                self._arts[key] = R.Artifact("store-repo", p.store_dir / kind, p.store_dir, None)
            else:
                self._arts[key] = R.resolve_artifact(p.path, kind)
        return self._arts[key]

    def _own_store_differs(self, p, a):
        """True when `p`'s nearest store (find, the one its sessions write to) is not `a.store`, the store
        that holds the memory it reads. A store-only project is its store, so never."""
        if p.store_dir is not None or p.is_store_key or a.store is None:
            return False
        own = resolver().find(p.path, "memory")
        return own.status == "found" and norm_key(own.path) != norm_key(a.store)

    def resolve_class(self, p, artifact_dir, is_config):
        """Resolution contract (memory-rules.md) for one class, through the resolver.
        -> (directory or None, error or None). The config repo's memory is its store's only (step 0). With no
        store for the class, an in-workspace directory is read only where the resolver's folder_fallback
        gives one (a no-create folder); anywhere else it is a leftover and the project has none."""
        ck = (norm_key(p.path), artifact_dir, bool(is_config))
        if ck in self._rc:
            return self._rc[ck]
        if p.is_store_key and p.store_dir is None:
            self._rc[ck] = (None, None)
            return self._rc[ck]
        a = self.art(p, artifact_dir)
        if a.source == "failed":
            got = (None, "%s: store lookup failed: %s" % (artifact_dir, a.reason))
        elif is_config and artifact_dir == "memory":
            # Step 0: the config repo's own memory/ is the user tier; its project memory is a store's.
            got = (Path(a.path) if a.source == "store-repo" else None), None
        elif artifact_dir == "memory" and a.source == "store-repo" and self._own_store_differs(p, a):
            # An ancestor's store holds the memory this folder reads, but the folder has a store of its own,
            # where its sessions write (memory-rules.md § Resolution contract step 2). The sweep writes there
            # too: the project gets no memory file here, and store_for names its own store.
            got = None, None
        elif a.source in ("store-repo", "in-workspace") and a.path is not None:
            got = Path(a.path), None
        else:
            got = resolver().folder_fallback(p.path, artifact_dir), None
        self._rc[ck] = got
        return got

    def project_status(self, p):
        """-> (status, exists): new, known or removed (see build).

        A `store:` key is a store, not a folder: it exists when a store directory is attached to it, and a state
        entry for one that is not attached is `removed` only when no reason keeps it (add_store_only_projects
        sets store_note for an unreadable store repo or a checkout now serving the store). The manifest has no
        `indeterminate` or `superseded` status (sweep-orient.md and dream-sweep.py read new, known and removed), so
        a kept entry is `known` with the reason in errors[]."""
        if p.is_store_key:
            exists = p.store_dir is not None
            status = "new" if not p.in_state else "known"
            if p.in_state and not exists and (p.store_note is None or p.store_superseded):
                status = "removed"
            return status, exists
        exists = p.store_dir is not None or Path(p.path).is_dir()
        live = [b for b in p.by if b != "state"]
        status = "new" if not p.in_state else "known"
        if p.in_state and (not exists or (p.store_dir is None and not has_markers(p.path, self.unmarked) and not live)):
            status = "removed"
            st, _valid, _invalid, why = self.store_scan
            if exists and st != "ok":
                # A store repo that could not be scanned is "could not look", not "gone": the folder's store may
                # be there, so the entry is kept (known), as for a `store:` key.
                status = "known"
                R = resolver()
                if why.startswith(R.MISSING_ROOT):
                    cause = ("store repo missing (clone it, see providers/claude/README.md): %s"
                             % why[len(R.MISSING_ROOT):].lstrip(": "))
                else:
                    cause = "%s %s" % (STORE_REPO_UNREADABLE, why)
                p.store_note = "%s; the project's store cannot be checked, so its state entry is kept" % cause
        return status, exists

    def unit_leaders(self, repo_key):
        """plan 261016 Phase 5, the store unit. Projects whose resolved directory for a class is one
        directory (two checkouts of one remote, a folder and its repo's toplevel) are one unit: the
        memory entries, the plans and the Task 4 classification are built once, for the unit's leader.
        The leader is the first project by path that is not removed. Session lists and last_analyzed stay
        per project. -> {(class, directory key): (leader key, [member keys])}"""
        units = {}
        for k in sorted(self.projects, key=lambda k: self.projects[k].path):
            p = self.projects[k]
            status, _exists = self.project_status(p)
            for kind in ("memory", "plans"):
                d, _err = self.resolve_class(p, kind, kind == "memory" and k == repo_key)
                if d is None:
                    continue
                u = units.setdefault((kind, norm_key(d)), {"lead": None, "members": []})
                u["members"].append(k)
                if u["lead"] is None or (u["lead"][1] == "removed" and status != "removed"):
                    u["lead"] = (k, status)
        return {key: (u["lead"][0], u["members"]) for key, u in units.items()}

    def known_plan_stems(self):
        """Plan stems of every known project's plans/ (done/
        included), every workspace store's plans/ (the config repo's own
        store's included) and an in-repo plans/ the config repo may still
        hold, so a slug resolves wherever its plan was archived. Resolution
        errors are reported by build(), not here."""
        dirs = [self.repo / "plans"]
        dirs += [Path(d) / "plans" for d, _ident in self.store_scan[1]]
        for p in self.projects.values():
            got, _ = self.resolve_class(p, "plans", False)
            dirs.append(got)
        seen, uniq = set(), []
        for d in dirs:
            if d is not None and norm_key(d) not in seen:
                seen.add(norm_key(d))
                uniq.append(d)
        return plan_stems(uniq)

    def cite_check(self, is_config):
        """The CiteCheck for one memory scope: the config repo is a fallback
        root for project memory, an own root for user memory."""
        key = "config" if is_config else "project"
        if key not in self._cite_checks:
            known = [p.path for p in self.projects.values()
                     if p.store_dir is None and not p.is_store_key] + [str(self.repo)]
            self._cite_checks[key] = CiteCheck(known, () if is_config else (str(self.repo),))
        return self._cite_checks[key]

    def in_store_repo(self, path):
        """True for the store repo root or a path inside it (plan 261016 Phase 10): its stores hold other
        workspaces' memory, so nothing there is a project (the role the legacy workspaces/ exclusion had)."""
        root = resolver().store_repo_root()
        return norm_key(path) == norm_key(root) or is_inside(path, root)

    def drop_store_repo_projects(self):
        """A project discovered at or inside the store repo root (a session started there) is not a project:
        errors[] names it, once, and its sessions are not read. A state entry there is left to the status rule."""
        for k in sorted(self.projects):
            p = self.projects[k]
            if p.is_store_key or p.in_state or not self.in_store_repo(p.path):
                continue
            self.errors.append("%s is not a project: it is at or inside the store repo %s, whose stores hold other "
                               "workspaces' memory (%d session(s) not read)"
                               % (p.path, resolver().store_repo_root(), len(p.sessions)))
            del self.projects[k]

    def build(self):
        today = self.ctx.now.date()
        self._cite_checks = {}
        self.drop_store_repo_projects()
        self.all_stems = self.known_plan_stems()
        self.anchors = Anchors([p.path for p in self.projects.values()
                                if p.store_dir is None and not p.is_store_key]
                               + [str(self.repo)],
                               self.claude_home, self.kiro_home)
        repo_key = norm_key(self.repo)
        out, details = {}, {}
        units = self.unit_leaders(repo_key)
        for k in sorted(self.projects, key=lambda k: self.projects[k].path):
            p = self.projects[k]
            status, exists = self.project_status(p)
            sub_of = None
            if exists and p.store_dir is None and not p.is_store_key \
                    and not has_markers(p.path, self.unmarked):
                for anc in Path(os.path.abspath(p.path)).parents:
                    if has_markers(anc, self.unmarked):
                        sub_of = str(anc)
                        break
            is_config = k == repo_key
            mem_dir, err = self.resolve_class(p, "memory", is_config)
            if err:
                p.errors.append(err)
            if p.store_note and p.store_note not in p.errors:
                p.errors.append(p.store_note)
            # plan 261016 Phase 5: projects that resolve to one directory are one store unit; its
            # leader builds the memory entries and the plans, the other members carry the sessions only.
            if mem_dir is not None:
                lead, _members = units.get(("memory", norm_key(mem_dir)), (k, [k]))
                if lead != k:
                    mem_dir = None
            memory_file = None
            if mem_dir is not None and (Path(mem_dir) / "MEMORY.md").is_file():
                memory_file = Path(mem_dir) / "MEMORY.md"
            plans_dir, err = self.resolve_class(p, "plans", False)
            if err:
                p.errors.append(err)
            plans_leader = True
            if plans_dir is not None:
                lead, _members = units.get(("plans", norm_key(plans_dir)), (k, [k]))
                plans_leader = lead == k
            art = self.art(p, "memory")
            store = art.store if art.source == "store-repo" else None
            entries = []
            if memory_file is not None:
                got = build_entries(memory_file, [p.path, str(store) if store else None],
                                    self.cite_check(is_config), self.all_stems, today,
                                    self.anchors)
                if got is None:
                    p.errors.append("unreadable memory file %s" % memory_file)
                else:
                    entries = got
                    p.errors.extend(declined_strays(memory_file))
            # The ancestry rule holds only for a project the state commit's
            # sweep stamped; any other project uses the time rule.
            stamped = p.in_state and self.last_run is not None and \
                getattr(p, "last_analyzed", None) == self.last_run
            plans = build_plans(p.path, plans_dir, self.baseline(p), p.errors,
                                self.state_commit if stamped else None) if exists and plans_leader else \
                {"archive": None, "archive_source": None, "new_plans": []}
            due = False
            for s in p.sessions:
                if s["provider"] in self.due_days and s["kind"] == "normal":
                    try:
                        age = self.ctx.now.timestamp() - os.stat(s["source"]).st_mtime
                    except OSError:
                        continue
                    if age >= self.due_days[s["provider"]] * 86400:
                        due = True
            p.sessions.sort(key=lambda s: (s["provider"], s["id"], s["kind"]))
            detail = "projects/%s.json" % project_hash(p.path)
            out[p.path] = {
                "status": status, "discovered_by": sorted(p.by),
                "subdirectory_of": sub_of,
                "baseline_rule": self.baseline_rule(p),
                "older_sessions_not_read": len(p.older_not_read),
                "empty_sessions": len(p.empty_sessions),
                "counts": {"sessions": len(p.sessions), "entries": len(entries),
                           "suspects": sum(1 for e in entries if e["suspect"]),
                           "new_plans": len(plans.get("new_plans") or []),
                           "errors": len(p.errors)},
                "sessions": p.sessions, "errors": p.errors, "due": due,
                "fork_collapsed": sorted(p.fork_collapsed, key=lambda d: d["dropped"]),
                "memory_file": str(memory_file) if memory_file else None,
                "detail": detail,
            }
            if p.state_key is not None and p.state_key != p.path:
                out[p.path]["state_key"] = p.state_key
            if memory_file is not None:
                flags = sorted({f for e in entries for f in entry_flags(e)},
                               key=ENTRY_FLAGS.index)
                skey = p.state_key if p.state_key is not None else p.path
                q, mp = memory_cadence(self.stored_quiet(k), skey, flags)
                out[p.path].update(quiet_sweeps=q, memory_pass=mp, memory_flags=flags)
            details[detail] = {"project": p.path, "entries": entries, "plans": plans,
                               "older_sessions": sorted(p.older_not_read,
                                                        key=lambda o: (o["provider"], o["id"], o["kind"])),
                               "empty_session_ids": sorted(p.empty_sessions)}
        for key in sorted(self.state_copies):
            self.removed_copy(key, out, details)
        return out, details

    def removed_copy(self, key, out, details):
        """A state key naming a worktree copy, as an empty `removed` project
        so the Removed-projects acknowledgement (sweep-decide-apply.md
        APP-STATE) deletes that key and its quiet_sweeps and
        deferred_sessions entries, and nothing of the parent's. No entries,
        sessions or plans are read for it."""
        path = canon_path(key)
        note = "worktree copy of %s is not a project; acknowledging it deletes only this state entry" \
            % worktree_parent(key)
        detail = "projects/%s.json" % project_hash(path)
        out[path] = {
            "status": "removed", "discovered_by": ["state"], "subdirectory_of": None,
            "baseline_rule": "state", "older_sessions_not_read": 0, "empty_sessions": 0,
            "counts": {"sessions": 0, "entries": 0, "suspects": 0, "new_plans": 0,
                       "errors": 1},
            "sessions": [], "errors": [note], "due": False, "fork_collapsed": [],
            "memory_file": None, "detail": detail,
        }
        if key != path:
            out[path]["state_key"] = key
        details[detail] = {"project": path, "entries": [],
                           "plans": {"archive": None, "archive_source": None, "new_plans": []},
                           "older_sessions": [], "empty_session_ids": []}

    def user_memory(self):
        """The config repo's own memory (user memory): memory/MEMORY.md and
        memory/topics/*.md, entries in the per-project entry shape."""
        mem = self.repo / "memory"
        files = [mem / "MEMORY.md"] if (mem / "MEMORY.md").is_file() else []
        files += sorted(f for f in (mem / "topics").glob("*.md") if f.is_file())
        entries = []
        # A user entry's `plans/done/<x>.md` citation names the config repo's archive, which lives in its
        # store like any workspace's: both roots resolve citations.
        sdir = config_store_dir(self.repo)
        roots = [str(self.repo)] + ([str(sdir)] if sdir is not None else [])
        for f in files:
            got = build_entries(f, roots, self.cite_check(True), self.all_stems,
                                self.ctx.now.date(), self.anchors)
            if got is None:
                self.errors.append("unreadable memory file %s" % f)
            else:
                entries.extend(got)
                self.errors.extend(declined_strays(f))
        # A user-tier `Move` writes the topic file, then removes the MEMORY.md
        # copy; a crash between the two leaves the heading in both files
        # (memory-rules.md § Session-start memory context budget).
        first_file = {}
        for e in entries:
            seen = first_file.setdefault(e["heading"], e["file"])
            if seen != e["file"]:
                self.errors.append("duplicate heading across user-memory files: %r in %s and %s"
                                   % (e["heading"], seen, e["file"]))
        file_flags = {}
        for e in entries:
            for f in entry_flags(e):
                got = file_flags.setdefault(e["file"], [])
                if f not in got:
                    got.append(f)
        flags = sorted({f for fl in file_flags.values() for f in fl}, key=ENTRY_FLAGS.index)
        stored = (self.quiet_value(self.quiet["user_memory"], "user_memory")
                  if "user_memory" in self.quiet else None)
        q, mp = memory_cadence(stored, USER_MEMORY_KEY, flags)
        cadence = {"quiet_sweeps": q, "memory_pass": mp, "memory_flags": flags,
                   "file_flags": {k: sorted(v, key=ENTRY_FLAGS.index)
                                  for k, v in file_flags.items()},
                   "file_suspects": {str(f): sum(1 for e in entries
                                                 if e["file"] == str(f) and e["suspect"])
                                     for f in files}}
        return {"files": [str(f) for f in files], "entries": entries}, cadence


def project_hash(path):
    """Side-file name of a project: stable across drive-letter case."""
    return hashlib.sha256(norm_key(canon_path(path)).encode("utf-8")).hexdigest()[:16]


def in_claude_scratchpad(path):
    """True for a path under Claude Code's per-session scratchpad,
    <temp>/claude*/<project>/<session>/scratchpad: a sub-agent's working
    directory, never a project. Its sessions are probes, not work."""
    parts = [x.lower() for x in re.split(r"[\\/]+", str(path)) if x]
    for i, x in enumerate(parts):
        if x in ("temp", "tmp"):
            for j in range(i + 1, len(parts)):
                if parts[j].startswith("claude"):
                    return "scratchpad" in parts[j + 1:]
    return False


def due_session_count(projects):
    """Sessions the work-volume arm counts: every listed session except a
    history_only stub (a transcript-less one-line prompt, typically a bare
    /resume) and any session of a scratchpad pseudo-project. The manifest
    still lists them, and the sweep still reads them."""
    return sum(1 for path, v in projects.items() if not in_claude_scratchpad(path)
               for s in v["sessions"] if s["kind"] != "history_only")


def build_run(args, ctx):
    """-> (manifest index, side files {relative path: object}, n_sessions,
    n_due). The index is what the orchestrator reads whole; each project's
    entries and plans, and the user memory, go to side
    files the index names (`detail`)."""
    run = Run(args, ctx)
    run.load_state()
    run.scan_claude()
    run.scan_kiro()
    run.discover()
    run.attach_sessions()
    # After attach_sessions: a project history.jsonl alone names is known here.
    for key, path in sorted(run.full.items()):
        if key not in run.projects:
            run.errors.append("--full names no discovered project (nothing read in full): %s" % path)
    projects, details = run.build()
    n_sessions = sum(len(v["sessions"]) for v in projects.values())
    n_due = sum(1 for v in projects.values() if v["due"])
    n_counted = due_session_count(projects)
    um, um_cadence = run.user_memory()
    run.errors.extend(run.anchors.notes)
    details["user_memory.json"] = um
    details["unattributed.json"] = {"empty_session_ids": sorted(run.empty_unattributed)}
    manifest = {
        "snapshot_at": iso(ctx.now),
        "sweep_due": n_counted >= SWEEP_DUE_SESSIONS or n_due > 0 or (
            n_counted > 0 and run.last_run is not None
            and (ctx.now - run.last_run).total_seconds() >= SWEEP_DUE_DAYS * 86400),
        "due_sessions": n_counted,
        "new_project_baseline": {"rule": run.new_rule,
                                 "since": iso(run.new_baseline) if run.new_baseline else None},
        "errors": run.errors,
        "empty_sessions": len(run.empty_unattributed),
        "unattributed": "unattributed.json",
        "watermarks_to_clear": run.watermarks_to_clear,
        "user_memory": dict({"detail": "user_memory.json",
                             "counts": {"files": len(um["files"]), "entries": len(um["entries"]),
                                       "suspects": sum(1 for e in um["entries"] if e["suspect"])}},
                            **um_cadence),
        "projects": projects,
    }
    return manifest, details, n_sessions, n_due


def size_warning(n_bytes):
    """The warning line for an oversized manifest.json, else None."""
    if n_bytes > MANIFEST_WARN_BYTES:
        return ("warning: manifest.json is %d bytes (over %d): the orchestrator reads it whole"
                % (n_bytes, MANIFEST_WARN_BYTES))
    return None


def due_line(manifest, n_due):
    return "sweep due: %s (%d new sessions, %d projects near deletion)" % (
        "yes" if manifest["sweep_due"] else "no", manifest["due_sessions"], n_due)


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------

def leftover_snapshot(work):
    m = load_json(Path(work) / "manifest.json")
    if isinstance(m, dict) and isinstance(m.get("snapshot_at"), str):
        return m["snapshot_at"]
    return "unknown"


def refuse(reason):
    print("refused: %s" % reason)
    return EXIT_GUARD


def cmd_manifest(args, ctx):
    work = work_path(ctx.home)
    if os.path.lexists(str(work.parent)) or os.path.lexists(str(work)):
        why = guard_reason(work, ctx.home)
        if why:
            return refuse(why)
    if os.path.lexists(str(work)):
        print("leftover work folder: %s snapshot_at=%s" % (work, leftover_snapshot(work)))
        return EXIT_LEFTOVER
    manifest, details, n_sessions, n_due = build_run(args, ctx)
    _hook("manifest_before_mkdir", ctx.home)
    # Re-check right before creating anything: the parent may have changed
    # while the manifest was built. mkdir never follows a link that is
    # already there, and an existing work folder is a leftover (exit 5).
    try:
        mkdir_private(work.parent)
    except FileExistsError:
        pass
    why = guard_reason(work, ctx.home)
    if why or not work.parent.is_dir():
        return refuse(why or "%s is not a directory" % work.parent)
    try:
        mkdir_private(work)
    except FileExistsError:
        print("leftover work folder: %s snapshot_at=%s (appeared while the manifest was built)"
              % (work, leftover_snapshot(work)))
        return EXIT_LEFTOVER
    why = guard_reason(work, ctx.home)
    if why:
        return refuse(why)
    total_bytes = 0
    for path, proj in manifest["projects"].items():
        for s in proj["sessions"]:
            text = s.pop("_text")
            try:
                write_in_work(work, s["stripped"], text)
            except FileExistsError:
                manifest["errors"].append("refused to write %s twice (session %s of %s); "
                                          "this session's stripped text is missing"
                                          % (s["stripped"], s["id"], path))
                s["stripped"] = None
                continue
            total_bytes += s["bytes"]
        kinds = [s["kind"] for s in proj["sessions"]]
        print("project %s: status=%s new=%d deferred=%d history_only=%d bytes=%d entries=%d "
              "empty=%d older_not_read=%d forks_collapsed=%d due=%s errors=%d suspects=%d"
              % (path, proj["status"], kinds.count("normal"), kinds.count("deferred"),
                 kinds.count("history_only"), sum(s["bytes"] for s in proj["sessions"]),
                 proj["counts"]["entries"], proj["empty_sessions"],
                 proj["older_sessions_not_read"], len(proj["fork_collapsed"]),
                 "yes" if proj["due"] else "no", len(proj["errors"]),
                 proj["counts"]["suspects"]))
    for rel, obj in sorted(details.items()):
        try:
            write_in_work(work, rel, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
        except FileExistsError:
            manifest["errors"].append("refused to write %s twice; a project's detail file "
                                      "is missing" % rel)
    write_in_work(work, "manifest.json.tmp", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    os.replace(str(work / "manifest.json.tmp"), str(work / "manifest.json"))
    warn = size_warning(os.path.getsize(str(work / "manifest.json")))
    if warn:
        print(warn)
    for f, n in sorted(manifest["user_memory"]["file_suspects"].items()):
        print("user memory %s: suspects=%d" % (f, n))
    print("totals: projects=%d sessions=%d bytes=%d errors=%d" % (
        len(manifest["projects"]), n_sessions, total_bytes,
        len(manifest["errors"]) + sum(len(p["errors"]) for p in manifest["projects"].values())))
    print(due_line(manifest, n_due))
    print("manifest: %s" % (work / "manifest.json"))
    return EXIT_OK


_RESOLVER = None


def resolver():
    """store-resolver.py (plan 261016 Phase 5), loaded by path without a bytecode cache and without
    sys.path. Every store lookup in this script goes through it."""
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = _load_sibling("store-resolver.py", "store_resolver")
    return _RESOLVER


def config_store_dir(repo):
    """The config repo's own workspace store (where its project files live, like any workspace's), or None.
    Never raises."""
    try:
        r = resolver().find(str(repo), "plans")
    except Exception:  # noqa: BLE001 -- a lookup fault means "no store", never a crash
        return None
    return Path(r.path) if r.status == "found" and r.path is not None else None


def config_plans_dir(repo):
    """The config repo's plans/: its store's when that store holds one, else the in-repo plans/ (an older
    tree, or a fixture without a store repo)."""
    d = config_store_dir(repo)
    if d is not None and (d / "plans").is_dir():
        return d / "plans"
    return Path(repo) / "plans"


def _load_qmemory_eval():
    # Loaded lazily (the selftest swaps this function for a broken loader).
    return _load_sibling("qmemory-eval.py", "qmemory_eval")


def memory_budget(config_repo):
    """-> (words, pin, note): the always-loaded user memory's words, from
    qmemory-eval.py's compute_memory_tax (the only counter), the pin, and a
    note naming any memory file that exists but could not be read ('' when
    none), so an unreadable file is never shown as a silent 0."""
    qme = _load_qmemory_eval()
    tax = qme.compute_memory_tax(Path(config_repo))
    return tax["total_words"], MEMORY_BUDGET_WORDS, qme.unreadable_note(tax)


def memory_budget_line(config_repo):
    """The `count` budget line. Warn-only: a failure to count prints
    `memory budget: unknown (<reason>)` and never raises."""
    try:
        words, pin, note = memory_budget(config_repo)
    except (Exception, SystemExit) as e:  # the line is a warning; it never fails `count`
        return "memory budget: unknown (%s: %s)" % (type(e).__name__, e)
    return "memory budget: %d/%d%s%s" % (words, pin, " OVER" if words > pin else "", note)


def cmd_count(args, ctx):
    manifest, _details, n_sessions, n_due = build_run(args, ctx)
    print(due_line(manifest, n_due))
    print(memory_budget_line(canon_path(args.repo)))
    return EXIT_OK


def _renamed_ok(doomed, home):
    """None when doomed (the renamed work folder) is a real directory whose
    real parent is the real <home>/.agent-playbook, which is not a link."""
    ap = os.path.join(str(home), ".agent-playbook")
    expect_ap = _parts(os.path.join(os.path.realpath(str(home)), ".agent-playbook"))
    if os.path.islink(ap):
        return "%s is a link (resolves to %s)" % (ap, os.path.realpath(ap))
    if _parts(os.path.realpath(ap)) != expect_ap:
        return "%s resolves to %s" % (ap, os.path.realpath(ap))
    if os.path.islink(str(doomed)) or not os.path.isdir(str(doomed)):
        return "%s is a link or not a directory" % doomed
    if _parts(os.path.realpath(str(doomed)))[:-1] != expect_ap:
        return "%s resolves to %s" % (doomed, os.path.realpath(str(doomed)))
    return None


def cmd_clean(args, ctx):
    work = work_path(ctx.home)
    if not os.path.lexists(str(work)):
        print("clean: nothing to delete (%s absent)" % work)
        return EXIT_OK
    why = guard_reason(work, ctx.home)
    if why or not work.is_dir():
        return refuse(why or "%s is not a directory" % work)
    _hook("clean_after_guard", ctx.home)
    # Rename first (atomic), re-check the renamed path, then delete: a swap
    # of any component after the guard can no longer redirect the delete.
    doomed = work.parent / ("dream-work.deleting-%d-%s" % (os.getpid(), secrets.token_hex(4)))
    try:
        os.rename(str(work), str(doomed))
    except OSError as e:
        return refuse("could not rename %s before deleting it: %s" % (work, e))
    why = _renamed_ok(doomed, ctx.home)
    if why:
        try:
            os.rename(str(doomed), str(work))
        except OSError:
            why += "; the renamed folder was left at %s" % doomed
        return refuse(why)
    try:
        _rmtree(str(doomed))
    except OSError as e:
        print("clean: could not delete %s: %s -- leftover path %s (delete it by hand)"
              % (work, e, doomed))
        return EXIT_CLEAN_FAILED
    print("clean: deleted %s" % work)
    return EXIT_OK


def cmd_baseline(args, ctx):
    session = Path(args.session)
    if not session.is_file():
        raise Usage("no such transcript: %s" % session)
    subs, loaded, errors = load_session_files(session)
    until_line = None
    if args.until is not None:
        if not loaded or loaded[0][0] != session:
            raise Usage("--until: the session transcript is unreadable: %s" % "; ".join(errors))
        until_line, cut = baseline_cutoff(loaded[0][1], args.until)
        kept, late, undated = [loaded[0]], 0, 0
        for f, recs in loaded[1:]:
            times = [t for t in (parse_time(r.get("timestamp")) for _ln, r in recs) if t]
            if not recs:
                kept.append((f, recs))   # an empty file: an agent with 0 tokens
            elif not times:
                undated += 1
                errors.append("sub-agent transcript %s has no timestamp; left out of the "
                              "--until sum" % f)
            elif min(times) <= cut:
                kept.append((f, recs))
            else:
                late += 1
        subs_total, loaded = len(subs), kept
    u = usage_by_message(loaded, session, until_line)
    per_id, models, records, anon = u["per_id"], u["models"], u["records"], u["anon"]
    key_role, key_file, file_role = u["key_role"], u["key_file"], u["file_role"]
    print("baseline: %s" % session)
    n_subs = len(loaded) - 1 if args.until is not None else len(subs)
    print("files: 1 session + %d sub-agent transcript(s) (%s)"
          % (n_subs, session.parent / session.stem / "subagents"))
    if args.until is not None:
        print("until: %s -- session lines 1-%d, cutoff time %s; sub-agent transcripts left out: "
              "%d started after the cutoff, %d undated (of %d)"
              % (args.until, until_line, iso(cut), late, undated, subs_total))
    for e in errors:
        print("error: %s" % e)
    if not per_id:
        print("baseline: no message.usage record found -- no token count (exit %d)" % EXIT_NO_USAGE)
        return EXIT_NO_USAGE
    totals = {k: sum(v.get(k, 0) for v in per_id.values()) for k in USAGE_FIELDS + (ADVISOR_FIELD,)}
    print("fields used: message.id, message.model, message.usage.{%s}, and the "
          "advisor_message entries of message.usage.iterations" % ",".join(USAGE_FIELDS))
    print("usage records: %d, deduplicated by message.id to %d message(s) (%d without message.id, "
          "counted once each)" % (records, len(per_id), anon))
    print(" ".join("%s=%d" % (k, totals[k]) for k in USAGE_FIELDS + (ADVISOR_FIELD,)))
    print("tokens: %d" % sum(totals.values()))
    by_model = {}
    for key, v in per_id.items():
        m = models.get(key, "unknown")
        by_model[m] = by_model.get(m, 0) + sum(v.get(k, 0) for k in USAGE_FIELDS)
        if v.get(ADVISOR_FIELD):
            a = u["advisor_models"].get(key, "unknown advisor")
            by_model[a] = by_model.get(a, 0) + v[ADVISOR_FIELD]
    for m in sorted(by_model):
        print("model %s: %d" % (m, by_model[m]))
    print("agents: %d" % n_subs)
    if args.by_role:
        files = dict.fromkeys(BASELINE_ROLES, 0)
        tokens = dict.fromkeys(BASELINE_ROLES, 0)
        others = []
        for f, recs in loaded:
            if f == session:
                files["orchestrator"] += 1
                continue
            role, text = file_role[f]
            files[role] += 1
            if role == "other":
                others.append((f.name, text))
        peak = dict.fromkeys(BASELINE_ROLES, 0)
        peak_file = dict.fromkeys((f for f, _recs in loaded), 0)
        for key, v in per_id.items():
            tokens[key_role[key]] += sum(v.values())
            ctx_size = u["context"][key]
            peak[key_role[key]] = max(peak[key_role[key]], ctx_size)
            peak_file[key_file[key]] = max(peak_file[key_file[key]], ctx_size)
        for r in BASELINE_ROLES:
            print("role %s: files %d, tokens: %d" % (r, files[r], tokens[r]))
        for r in BASELINE_ROLES:
            print("peak context %s: %d" % (r, peak[r]))
        # D13: the session's own peak, then each phase agent's and drafter's.
        if session in peak_file:
            print("peak context orchestrator (session): %d" % peak_file[session])
        else:
            print("peak context orchestrator (session): n/a (session transcript unreadable)")
        for r in PEAK_AGENT_ROLES:
            agents = sorted(((peak_file[f], f.stem) for f, _recs in loaded
                             if f != session and file_role[f][0] == r),
                            key=lambda pf: (-pf[0], pf[1]))
            for p, name in agents[:PEAK_AGENT_LINES]:
                print("peak context %s %s: %d" % (r, name, p))
            if len(agents) > PEAK_AGENT_LINES:
                print("peak context %s (more): %d agent(s) not listed, largest %d"
                      % (r, len(agents) - PEAK_AGENT_LINES, agents[PEAK_AGENT_LINES][0]))
        for name, text in others:
            shown = " ".join(text.split())[:80] if text is not None else ""
            print("other: %s: %s" % (name, shown or ("(no user record)" if text is None
                                                      else "(first user record has no text)")))
    return EXIT_OK


def first_time(path):
    """-> the time of the first record of a transcript that has a parseable
    `timestamp`, else None."""
    try:
        recs, _errs = read_jsonl(path)
    except OSError:
        return None
    for _ln, rec in recs:
        return parse_time(rec.get("timestamp"))
    return None


def cmd_context(args, ctx):
    """`context`: the context size of one transcript's last model call."""
    if args.session:
        session = Path(args.session)
    else:
        sid = (ctx.env.get("CLAUDE_CODE_SESSION_ID") or "").strip()
        if not sid or not re.fullmatch(r"[A-Za-z0-9-]{8,80}", sid):
            raise Usage("no --session and no usable CLAUDE_CODE_SESSION_ID (Claude Code only; "
                        "kiro records no usage)")
        found = sorted((ctx.home / ".claude" / "projects").glob("*/%s.jsonl" % sid))
        if len(found) != 1:
            raise Usage("CLAUDE_CODE_SESSION_ID %s: %d transcript(s) under %s"
                        % (sid, len(found), ctx.home / ".claude" / "projects"))
        session = found[0]
    if not session.is_file():
        raise Usage("no such transcript: %s" % session)
    target = session
    if args.marker is not None:
        if not args.marker.strip():
            raise Usage("--marker is empty")
        hits = []
        for f in sorted((session.parent / session.stem / "subagents").glob("*.jsonl")):
            try:
                recs, _errs = read_jsonl(f)
            except OSError:
                continue
            _role, text = baseline_role(recs)
            if text and args.marker in text:
                hits.append(f)
        if not hits:
            raise Usage("--marker matches the first user record of 0 sub-agent transcript(s) of "
                        "%s; it must match exactly one" % session)
        target = hits[0]
        if len(hits) > 1:
            # Single-flight: an older match has ended, so the live one began last.
            times = [first_time(f) for f in hits]
            firsts = None if None in times else sorted(
                zip(times, [f.name for f in hits], hits), key=lambda x: x[:2])
            if firsts is None or firsts[-1][0] == firsts[-2][0]:
                raise Usage("--marker matches the first user record of %d sub-agent "
                            "transcript(s) of %s and their first-record times do not tell the "
                            "latest apart (undated or equal); it must match exactly one"
                            % (len(hits), session))
            top = firsts[-1][0]
            target = firsts[-1][2]
            print("note: --marker matched %d sub-agent transcripts; took the one whose first "
                  "record is the latest (%s, %s)" % (len(hits), target.name, iso(top)))
    try:
        recs, _errs = read_jsonl(target)
    except OSError as e:
        raise Usage("unreadable transcript %s: %s" % (target, e))
    last = None
    for _ln, rec in recs:
        msg = rec.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if isinstance(usage, dict) and any(isinstance(usage.get(k), int) for k in CONTEXT_FIELDS):
            last = (usage_iterations(usage)[0], rec.get("timestamp"))
    print("context: %s" % target)
    if last is None:
        print("context: no message.usage record -- no reading (exit %d)" % EXIT_NO_USAGE)
        return EXIT_NO_USAGE
    limit = args.limit if args.limit is not None else (
        ORCHESTRATOR_CONTEXT_LIMIT if args.orchestrator else PHASE_CONTEXT_LIMIT)
    print("context: %d tokens at the last model call (%s)" % (last[0], last[1] or "undated"))
    print("over limit: %s (limit %d)" % ("yes" if last[0] > limit else "no", limit))
    return EXIT_OK


def load_session_files(session):
    """-> (sub-agent paths, [(path, records)] readable files, errors): a
    transcript and every `<session>/subagents/*.jsonl` beside it."""
    subs = sorted((session.parent / session.stem / "subagents").glob("*.jsonl"))
    loaded, errors = [], []
    for f in [session] + subs:
        try:
            recs, errs = read_jsonl(f)
        except OSError as e:
            errors.append("unreadable %s: %s" % (f, e))
            continue
        errors.extend(errs)
        loaded.append((f, recs))
    return subs, loaded, errors


def usage_iterations(usage):
    """-> (context, advisor_tokens, advisor_model) of one message.usage.
    A message that calls a server tool such as the advisor holds one model
    call per `iterations` entry, and its top-level fields sum the `message`
    iterations: context is the largest single `message` iteration (what one
    call read), not that sum. `advisor_message` iterations are the advisor's
    own calls, absent from the top-level fields, so they are returned apart.
    Without `iterations`, context is the top-level CONTEXT_FIELDS sum."""
    def size(d, fields):
        return sum(d[k] for k in fields
                   if isinstance(d.get(k), int) and not isinstance(d.get(k), bool))
    its = usage.get("iterations")
    its = [i for i in its if isinstance(i, dict)] if isinstance(its, list) else []
    calls = [size(i, CONTEXT_FIELDS) for i in its if i.get("type") == "message"]
    advisor = [i for i in its if i.get("type") == "advisor_message"]
    model = next((i["model"] for i in advisor if isinstance(i.get("model"), str) and i["model"]),
                 None)
    return (max(calls) if calls else size(usage, CONTEXT_FIELDS),
            sum(size(i, USAGE_FIELDS) for i in advisor), model)


def usage_by_message(loaded, session, until_line=None):
    """The `baseline` count: message.usage per message.id (a record without
    one counts once), each field the maximum over the records that repeat
    it, with the role of the file it first appears in (the session is
    orchestrator; a sub-agent file's role is baseline_role). Per key also
    its context (usage_iterations, the largest over the records) and, under
    ADVISOR_FIELD, the advisor iterations' tokens; tokens are the sum of a
    key's values, so the advisor's count under the role that called it."""
    per_id, models, records, anon = {}, {}, 0, 0
    key_role, key_file, file_role = {}, {}, {}
    context, advisor_models = {}, {}
    for f, recs in loaded:
        if f == session:
            role = "orchestrator"
        else:
            file_role[f] = baseline_role(recs)
            role = file_role[f][0]
        for ln, rec in recs:
            if f == session and until_line is not None and ln > until_line:
                break
            msg = rec.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict):
                continue
            vals = {k: usage[k] for k in USAGE_FIELDS
                    if isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool)}
            if not vals:
                continue
            records += 1
            mid = msg.get("id")
            if isinstance(mid, str) and mid:
                key = mid
            else:
                key = "%s:L%d" % (f, ln)
                anon += 1
            cur = per_id.setdefault(key, {})
            key_role.setdefault(key, role)
            key_file.setdefault(key, f)
            for k, v in vals.items():
                cur[k] = max(cur.get(k, 0), v)
            ctx, adv, adv_model = usage_iterations(usage)
            context[key] = max(context.get(key, 0), ctx)
            if adv:
                cur[ADVISOR_FIELD] = max(cur.get(ADVISOR_FIELD, 0), adv)
            if adv_model:
                advisor_models[key] = adv_model
            if isinstance(msg.get("model"), str) and msg["model"]:
                models[key] = msg["model"]
    return {"per_id": per_id, "models": models, "records": records, "anon": anon,
            "key_role": key_role, "key_file": key_file, "file_role": file_role,
            "context": context, "advisor_models": advisor_models}


def session_tokens(session):
    """-> (tokens, tokens_by_role, problem): `baseline --by-role`'s totals for
    one transcript and its sub-agents, or (None, None, why) when it cannot
    give them. dream-write.py `state apply` fills the cost record with it."""
    session = Path(session)
    if not session.is_file():
        return None, None, "no transcript at %s" % session
    _subs, loaded, errors = load_session_files(session)
    if not loaded or loaded[0][0] != session:
        return None, None, "transcript unreadable: %s" % "; ".join(errors)
    u = usage_by_message(loaded, session)
    if not u["per_id"]:
        return None, None, "no message.usage record in %s" % session
    by_role = dict.fromkeys(BASELINE_ROLES, 0)
    for key, v in u["per_id"].items():
        by_role[u["key_role"][key]] += sum(v.values())
    return sum(by_role.values()), by_role, None


# API price ratios per usage field: relative cost, not a quota percentage. The session-cost target
# (memory-rules.md § State File Format, cost_records) is stated in these units.
USAGE_WEIGHTS = {"input_tokens": 1, "output_tokens": 5, "cache_creation_input_tokens": 1.25,
                 "cache_read_input_tokens": 0.1}


def session_weighted(session, since=None):
    """-> (weighted tokens, problem) for one transcript and its sub-agents, counting only records at
    or after `since` (a transcript can hold work from before the sweep). A record with no timestamp
    counts. dream-write.py `state apply` fills the cost record's weighted_tokens with it."""
    session = Path(session)
    if not session.is_file():
        return None, "no transcript at %s" % session
    _subs, loaded, errors = load_session_files(session)
    if not loaded or loaded[0][0] != session:
        return None, "transcript unreadable: %s" % "; ".join(errors)
    cut = parse_time(since) if since else None
    if cut is not None:
        def kept(rec):
            ts = parse_time(rec.get("timestamp"))
            return ts is None or ts >= cut
        loaded = [(f, [(ln, r) for ln, r in recs if kept(r)]) for f, recs in loaded]
    u = usage_by_message(loaded, session)
    total = sum(USAGE_WEIGHTS.get(k, 1) * n for v in u["per_id"].values() for k, n in v.items())
    return int(round(total)), None


BASELINE_ROLES =("orchestrator", "task4", "verifier", "drafter", "other")
# A call's context size (D13 peak context): everything the model read on that
# call, so output_tokens is left out.
CONTEXT_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# The per-message key that holds the advisor iterations' tokens (usage_iterations).
ADVISOR_FIELD = "advisor_tokens"
# `context`'s default limit: the reading above which a phase agent hands off
# at its next step boundary (sweep-handoff.md § Dream Phase Agent Brief, Budget).
PHASE_CONTEXT_LIMIT = 200000
# The orchestrator's own limit (`context --orchestrator`): the reading above
# which it hands off at its next step boundary (sweep-handoff.md, Context
# budget). One constant; the prose names the flag, not the number.
ORCHESTRATOR_CONTEXT_LIMIT = 500000
# The roles whose sub-agent files get a per-agent peak line (a phase agent
# counts under orchestrator), and the most lines printed for one role, the
# largest peaks first; the rest are summed up on one `(more)` line.
PEAK_AGENT_ROLES = ("orchestrator", "drafter")
PEAK_AGENT_LINES = 8
# The explicit brief markers, in test order. A phase agent's brief names the
# briefs it dispatches, and a drafter's or verifier's brief may name the
# Task-4 brief, so the phase marker is tested first and task4 last.
BRIEF_MARKERS = (("Dream Phase Agent Brief", "orchestrator"),
                 ("Dream Drafter Brief", "drafter"),
                 ("Dream Verifier Brief", "verifier"),
                 ("Dream Sub-agent Brief", "task4"))


def baseline_role(recs):
    """`baseline --by-role`: -> (role, text of the first user record) for a
    sub-agent transcript; text is "" when that record holds no text and None
    when the file has no user record. BRIEF_MARKERS are tested in order on
    the first non-blank line; then the verifier and task4 markers only, in
    that order, on the whole text (a phase or drafter marker further down is
    a mention, as in any agent that quotes a brief); the older-transcript
    fallback runs only when no marker matches."""
    for _ln, rec in recs:
        msg = rec.get("message")
        if rec.get("type") != "user" or not isinstance(msg, dict):
            continue
        c = msg.get("content")
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            text = "\n".join(b["text"] for b in c if isinstance(b, dict)
                             and b.get("type") == "text" and isinstance(b.get("text"), str))
        else:
            text = ""
        # The marker on the first non-blank line names the brief; a marker
        # further down is only a mention (a Task-4 brief naming the verifier
        # brief stays task4, plan 261006 Phase 9). The whole-text pass keeps
        # the verifier and task4 markers only: a real phase or drafter
        # dispatch carries its marker on the first line, and an agent that
        # merely quotes those names is not a sweep agent (plan 261012 Phase 3
        # review, Q2).
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        for whole, scope in ((False, first), (True, text)):
            for marker, role in BRIEF_MARKERS:
                if whole and role in ("orchestrator", "drafter"):
                    continue
                if marker in scope:
                    return role, text
        # Fallback, only when no marker matched: transcripts older than the
        # verifier brief's marker line (plan 261006 Phase 9).
        if "Cross-validation" in text or "verifier" in text:
            return "verifier", text
        return "other", text
    return "other", None


def baseline_cutoff(recs, until):
    """`baseline --until`: -> (last session line summed, cutoff time). A
    record uuid cuts at that record; its time is its own timestamp, else the
    latest earlier one. An ISO timestamp cuts at the last record dated at or
    before it. An unknown uuid, or a cutoff no record time can date, is a
    usage error, never a silent full sum."""
    t = parse_time(until)
    if t is not None:
        lines = [ln for ln, r in recs
                 if parse_time(r.get("timestamp")) is not None
                 and parse_time(r.get("timestamp")) <= t]
        if not lines:
            raise Usage("--until %s: no session record is dated at or before it" % until)
        return max(lines), t
    last_t = None
    for ln, r in recs:
        rt = parse_time(r.get("timestamp"))
        if rt is not None:
            last_t = rt
        if r.get("uuid") == until:
            if last_t is None:
                raise Usage("--until %s: that record and every earlier one are undated" % until)
            return ln, last_t
    raise Usage("--until %s: no record with that uuid in the session transcript and not an "
                "ISO timestamp" % until)


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="dream-manifest.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?",
                    choices=["manifest", "count", "clean", "baseline", "context"])
    ap.add_argument("--state")
    ap.add_argument("--repo")
    ap.add_argument("--claude-home")
    ap.add_argument("--kiro-home")
    ap.add_argument("--add", action="append")
    ap.add_argument("--full", action="append")
    ap.add_argument("--exclude-session", action="append")
    ap.add_argument("--work")
    ap.add_argument("--session")
    ap.add_argument("--until")
    ap.add_argument("--by-role", action="store_true")
    ap.add_argument("--marker")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--orchestrator", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        raise Usage("bad arguments") if e.code else e
    if args.work is not None and not args.selftest:
        raise Usage("--work is accepted only with --selftest; a real run always uses "
                    "~/.agent-playbook/dream-work")
    if args.selftest:
        if args.command:
            raise Usage("--selftest takes no subcommand")
        return args
    if not args.command:
        raise Usage("a subcommand is required: manifest | count | clean | baseline | context")
    if args.command != "context" and (args.marker is not None or args.limit is not None
                                      or args.orchestrator):
        raise Usage("--marker, --limit and --orchestrator are accepted only by context")
    if args.command == "baseline":
        if not args.session or any([args.state, args.repo, args.claude_home, args.kiro_home,
                                    args.add, args.full, args.exclude_session]):
            raise Usage("baseline takes --session <transcript.jsonl> [--until <record uuid "
                        "or ISO timestamp>] [--by-role] and nothing else")
        return args
    if args.command == "context":
        if args.until is not None or args.by_role or any(
                [args.state, args.repo, args.claude_home, args.kiro_home, args.add, args.full,
                 args.exclude_session]):
            raise Usage("context takes [--session <transcript.jsonl>] [--marker <text>] "
                        "[--limit <tokens> | --orchestrator] and nothing else")
        if args.orchestrator and (args.limit is not None or args.marker is not None):
            raise Usage("--orchestrator is the orchestrator's own limit: it is refused with "
                        "--limit and --marker")
        if args.limit is not None and args.limit <= 0:
            raise Usage("--limit must be a positive token count")
        return args
    if args.session or args.until is not None or args.by_role:
        raise Usage("--session, --until and --by-role are accepted only by baseline")
    if args.command in ("manifest", "count") and (not args.state or not args.repo):
        raise Usage("%s needs --state and --repo" % args.command)
    if args.command == "clean" and any([args.state, args.repo, args.claude_home, args.kiro_home,
                                        args.add, args.full, args.exclude_session]):
        raise Usage("clean takes no options")
    return args


# --- venv guard stub: identical in every qdream script (venv-selfcheck.py --selftest compares them) ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "venv-selfcheck.py")
    name = os.path.basename(script or __file__)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("venv_selfcheck", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        sys.stderr.write("%s: guard did not run: venv self-check unavailable (%s: %s)\n"
                         % (name, type(exc).__name__, exc))
        sys.exit(2)
    finally:
        sys.dont_write_bytecode = saved
    mod.require(script or __file__)
# --- end venv guard stub ---


def main(argv=None, ctx=None):
    _require_venv(__file__)
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except Usage as e:
        print("usage error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    if args.selftest:
        return run_selftest(args.work)
    ctx = ctx or Ctx()
    if args.command in ("baseline", "context"):
        try:
            return (cmd_baseline if args.command == "baseline" else cmd_context)(args, ctx)
        except Usage as e:
            print("usage error: %s" % e, file=sys.stderr)
            return EXIT_USAGE
    bad = home_problem(ctx.home)
    if bad:
        return refuse("home directory %s %s" % (ctx.home, bad))
    try:
        if args.command == "manifest":
            return cmd_manifest(args, ctx)
        if args.command == "count":
            return cmd_count(args, ctx)
        return cmd_clean(args, ctx)
    except Usage as e:
        print("usage error: %s" % e, file=sys.stderr)
        return EXIT_USAGE


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

REQUIRED_CASES = [
    "claude-per-record-timestamps", "claude-no-timestamps-history-fallback",
    "claude-tool-result-user-records", "claude-ismeta-and-compaction", "claude-sidechain",
    "claude-history-only-bridge", "claude-subagents-folder", "kiro-in-progress-recent",
    "kiro-in-progress-stale", "kiro-deferred-watermark", "kiro-prompt-skill-body-with-args",
    "kiro-invocation-without-leading-slash", "kiro-pasted-skill-draft", "mixed-timezone-offsets",
    "near-deletion-age", "kiro-near-deletion-age", "kiro-retention-unset", "store-backed-workspace", "store-repo-unit", "structural-subproject", "structural-config-shared", "no-new-sessions",
    "torn-final-line", "leftover-work-folder", "guard-prefix-and-dotdot", "count-writes-nothing", "count-due-after-days",
    # review fixes (2026-09-24)
    "claude-shell-mode-records", "claude-harness-blocks", "claude-loose-history-two-projects",
    "user-memory-entries", "user-memory-duplicate-heading", "kiro-missing-parts", "claude-empty-local-transcript",
    "claude-malformed-lines", "claude-history-match-strict", "skill-body-aux-file",
    "method-b-home-roots", "plans-ancestry-not-clock", "hardening-units",
    # baseline token counts
    "baseline-duplicate-message-id", "baseline-subagent-file", "baseline-no-usage-records",
    # Windows findings (2026-09-24)
    "new-project-last-run-baseline", "new-project-full-history", "first-run-commit-baseline",
    "drive-letter-keys", "plans-excerpt-caps",
    # new-project baseline review fixes
    "new-project-history-older", "first-run-commit-unreadable",
    # plan harvest review fixes
    "plans-none-new-still-harvested",
    # 2026-09-24 sweep: Claude Code fork duplicates
    "claude-fork-duplicates",
    # 2026-09-28: dialog answers and mid-turn messages are user speech
    "claude-dialog-answers-and-mid-turn",
    # quiet-project cadence (2026-09-25)
    "quiet-periodic-due", "quiet-not-due", "quiet-flagged", "quiet-conflict-deferred-flag",
    "quiet-flag-beats-periodic", "quiet-seed-absent", "quiet-key-normalized",
    "quiet-stale-when-not-flag", "user-memory-quiet-pair",
    # trigger rule, cited-path and slug resolution (user decisions
    # 2026-09-25), review findings
    "quiet-path-slug-not-trigger", "quiet-conflict-rule-update-pending",
    "user-memory-stored-periodic", "cite-resolution", "cite-resolution-missing",
    # 2026-09-28: fork chains and cross-project keepers, baseline --until,
    # plan folders are not plan files
    "claude-fork-chain", "claude-fork-cross-project", "claude-fork-keeper-most-shared",
    "claude-fork-unknown-boundary", "baseline-until-record", "baseline-until-timestamp",
    "baseline-until-unknown-uuid", "cite-plan-folder-not-archive",
    # fork review fixes (2026-09-28)
    "claude-fork-same-session-two-files", "claude-fork-uuidless-turn",
    "claude-fork-cross-project-partial", "claude-fork-interleaved-skip",
    "baseline-until-empty-subagent",
    # 2026-10-06: baseline --by-role (P-10)
    "baseline-by-role", "baseline-by-role-off",
    # 2026-10-06: --by-role review fixes
    "baseline-by-role-refused", "baseline-by-role-no-text",
    "baseline-by-role-leading-whitespace",
    # 2026-10-08: verifier brief marker line (plan 261006 Phase 9)
    "baseline-by-role-verifier-marker", "baseline-by-role-verifier-names-task4",
    # 2026-10-14: phase and drafter markers, peak context (plan 261012 Phase 3)
    "baseline-by-role-phase-marker", "baseline-by-role-drafter", "baseline-peak-context",
    # review fixes: per-agent peak lines and their cap, whole-text order
    "baseline-peak-context-cap", "baseline-by-role-whole-text-order",
    # second review fixes: the cap boundary, an unreadable session file
    "baseline-peak-context-eight", "baseline-unreadable-session",
    # final review (2026-09-28): Accept-and-note dispositions, ancestry only
    # for a project the state commit's sweep stamped
    "plans-acknowledged-dispositions", "plans-ancestry-uncovered-project",
    # user-scope improvement signals live in a topic file
    "user-memory-topic-signals",
    # suspect memory entries: anchor and version flags (2026-10-06)
    "suspect-path-changed", "suspect-commit-missing", "suspect-stale-when-version",
    "suspect-stale-when-no-version",
    # Phase 8 gate (2026-10-06): stale_when_fired dispatches; cited_path_changed
    # and stale_when_unknown stay inputs
    "quiet-stale-when-fired-trigger", "quiet-path-changed-not-trigger",
    # kiro-cli version from harness logs (plan 261009 Phase 2)
    "suspect-kiro-log-adjacent-version", "suspect-kiro-log-non-adjacent-version",
    "suspect-kiro-log-ide-only", "suspect-kiro-log-no-logs",
    "suspect-kiro-log-newer-ide-over-older-cli",
    # plan 261009 Step 9: a pre-release newest log is skipped, the closing-quote anchor
    "suspect-kiro-log-prerelease-newest-skipped",
    # plan header `Memory relied on`, the Usage feeder (plan 261006 Phase 10)
    "plans-memory-relied-on", "plans-memory-relied-on-none", "plans-memory-relied-on-absent",
    # plan-less governance capture: an in-session `Sessions` marker (plan 261006 Phase 11)
    "user-memory-topic-signal-in-session",
    # Claude Code sub-agent worktree copies are not projects
    "worktree-copy-not-a-project",
]


def _snapshot(root, skip=None):
    snap = {}
    for cur, dirs, files in os.walk(str(root)):
        if skip is not None and _parts(os.path.realpath(cur))[:len(_parts(skip))] == _parts(skip):
            dirs[:] = []
            continue
        for name in dirs + files:
            full = os.path.join(cur, name)
            rel = os.path.relpath(full, str(root))
            if os.path.islink(full):
                snap[rel] = ("link", os.readlink(full))
            elif os.path.isfile(full):
                st = os.stat(full)
                with open(full, "rb") as fh:
                    snap[rel] = ("file", hashlib.sha256(fh.read()).hexdigest(), st.st_mtime)
            else:
                snap[rel] = ("dir",)
    return snap


_PATH_TAIL = r"[^\s'\"<>|:*?,;()\[\]]*"


def _norm_seps(obj, roots, on=None):
    """Comparator normalization for Windows: fixtures write paths with '/'
    ({ROOT} is substituted in POSIX form) while the script reports native
    '\\' paths, so on Windows a path that starts with the fixture root (in
    either form, listed in roots) has its '\\' turned into '/' -- in strings
    and dict keys of both the expected and the actual value. Every other
    backslash (a path outside the root, regex text) is compared as is.
    Elsewhere (on=False) the values are returned unchanged. The script's own
    output is never altered; only the comparison is."""
    if on is None:
        on = os.sep == "\\"
    if not on:
        return obj
    if isinstance(obj, str):
        for r in sorted(set(roots), key=len, reverse=True):
            obj = re.sub(re.escape(r) + _PATH_TAIL,
                         lambda m: m.group(0).replace("\\", "/"), obj)
        return obj
    if isinstance(obj, list):
        return [_norm_seps(x, roots, on) for x in obj]
    if isinstance(obj, dict):
        return {_norm_seps(k, roots, on): _norm_seps(v, roots, on) for k, v in obj.items()}
    return obj


def _key_sep_problems(keys, native_root, sep=None):
    """Project keys the script composed from the fixture root (they start
    with its native form) must use the native separator only: '/' on
    Windows, '\\' elsewhere, is a finding the comparator would otherwise
    hide. Keys that start with another form were taken verbatim from input
    files and are not checked."""
    sep = sep or os.sep
    alt = "/" if sep == "\\" else "\\"
    return ["project key %r mixes separators (native is %r)" % (k, sep)
            for k in keys if k.startswith(native_root) and alt in k[len(native_root):]]


INDEX_BULKY_KEYS = ("entries", "plans", "older_sessions",
                    "empty_session_ids")


def _manifest_view(man, work):
    """-> (the index with every side file merged back in, problems). The
    fixtures' `manifest` expectations are written against this view;
    problems lists index entries that hold bulky keys or name a missing or
    unreadable side file."""
    view, probs = json.loads(json.dumps(man)), []
    for ppath, proj in (view.get("projects") or {}).items():
        for k in INDEX_BULKY_KEYS:
            if k in proj:
                probs.append("index project %s holds %r (belongs in its side file)" % (ppath, k))
        det = load_json(Path(work) / proj.get("detail", "")) if proj.get("detail") else None
        if not isinstance(det, dict) or det.get("project") != ppath:
            probs.append("side file %r of %s missing or not this project's" % (proj.get("detail"), ppath))
            continue
        for k in INDEX_BULKY_KEYS:
            proj[k] = det.get(k)
    um = view.get("user_memory") or {}
    if "entries" in um or "files" in um:
        probs.append("index user_memory holds files/entries (belong in user_memory.json)")
    det = load_json(Path(work) / um["detail"]) if isinstance(um.get("detail"), str) else None
    if not isinstance(det, dict):
        probs.append("user_memory side file %r missing" % um.get("detail"))
    else:
        view["user_memory"] = dict(um, files=det.get("files"), entries=det.get("entries"))
    un = view.get("unattributed")
    det = load_json(Path(work) / un) if isinstance(un, str) else None
    if not isinstance(det, dict):
        probs.append("unattributed side file %r missing" % un)
    else:
        view["unattributed"] = det
    return view, probs


def _match(exp, act, where):
    errs = []
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return ["%s: expected object, got %r" % (where, act)]
        for k, v in exp.items():
            if k == "$absent":
                for a in v:
                    if a in act:
                        errs.append("%s: key %r should be absent" % (where, a))
            elif k == "$len":
                pass
            elif k not in act:
                errs.append("%s: missing key %r" % (where, k))
            else:
                errs.extend(_match(v, act[k], "%s.%s" % (where, k)))
        return errs
    if isinstance(exp, list):
        if not isinstance(act, list) or len(act) != len(exp):
            return ["%s: expected %d items, got %r" % (where, len(exp), act)]
        for i, (e, a) in enumerate(zip(exp, act)):
            errs.extend(_match(e, a, "%s[%d]" % (where, i)))
        return errs
    if isinstance(exp, str) and exp.startswith("$contains:"):
        ok = isinstance(act, str) and exp[len("$contains:"):] in act
        return [] if ok else ["%s: expected text containing %r, got %r" % (where, exp[10:], act)]
    if isinstance(exp, str) and exp.startswith("$maxlen:"):
        n = int(exp[len("$maxlen:"):])
        ok = isinstance(act, str) and len(act) <= n
        return [] if ok else ["%s: expected a string of at most %d characters, got %d"
                              % (where, n, len(act) if isinstance(act, str) else -1)]
    if exp == "$nonnull":
        return ["%s: expected a value, got null" % where] if act is None else []
    if exp != act:
        errs.append("%s: expected %r, got %r" % (where, exp, act))
    return errs


def _subst(obj, root):
    if isinstance(obj, str):
        return obj.replace("{ROOT}", root)
    if isinstance(obj, list):
        return [_subst(x, root) for x in obj]
    if isinstance(obj, dict):
        return {_subst(k, root): _subst(v, root) for k, v in obj.items()}
    return obj


def _materialize(case_dir, root):
    """Copy case_dir/tree into root, substituting {ROOT}; apply setup."""
    rs = root.as_posix()
    src = case_dir / "tree"
    if src.is_dir():
        for f in sorted(src.rglob("*")):
            rel = f.relative_to(src)
            dst = root / rel
            if f.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            # bytes-level substitution: a fixture may hold invalid UTF-8 on purpose
            dst.write_bytes(f.read_bytes().replace(b"{ROOT}", rs.encode("utf-8")))


def _fixture_time(text):
    """Fixture clock values, parsed independently of parse_time (under test)."""
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


# Fixture git calls never start background maintenance (git 2.53+ may after a commit): it writes
# .git/objects/maintenance.lock into a fixture repo while the case checks what was written.
FIXTURE_GIT = ["-c", "maintenance.auto=false", "-c", "gc.auto=0"]


def _run_case(case_dir, scratch):
    spec = json.loads(read_text(case_dir / "case.json"))
    tmp = Path(tempfile.mkdtemp(prefix="dm-", dir=scratch))
    root = Path(os.path.realpath(str(tmp))) / "root"
    root.mkdir()
    fails = []
    # plan 261016 Phase 5: a case never sees the live store repo. By default it gets an empty store repo
    # outside its tree (plan 261016 Phase 10: a missing store repo is failed, and no in-workspace copy is
    # read); `no_store_repo` leaves the store repo missing; a case with `store_repo` names a directory of its
    # tree that becomes one. The tree sits in the system temp directory, a no-create folder, so a project
    # with no store reads its in-workspace copy (folder_fallback); `normal_folders` makes the tree an ordinary
    # place, where an in-workspace copy is a leftover and is not read.
    saved_stores = os.environ.get("AGENT_PLAYBOOK_STORES")
    os.environ["AGENT_PLAYBOOK_STORES"] = str(Path(os.path.realpath(str(tmp))) / "no-store-repo")
    try:
        _materialize(case_dir, root)
        if spec.get("store_repo"):
            (root / spec["store_repo"] / ".git").mkdir(parents=True, exist_ok=True)
            os.environ["AGENT_PLAYBOOK_STORES"] = str(root / spec["store_repo"])
        elif not spec.get("no_store_repo"):
            (Path(os.path.realpath(str(tmp))) / "empty-stores" / ".git").mkdir(parents=True)
            os.environ["AGENT_PLAYBOOK_STORES"] = str(Path(os.path.realpath(str(tmp))) / "empty-stores")
        if spec.get("normal_folders"):
            resolver()._TEST.update(temp=[str(root / "fake-system-temp")])
        spec = _subst(spec, root.as_posix())
        roots = [str(root), root.as_posix()]
        # Files a git tree cannot hold (a `.git` file naming a missing
        # directory makes every git call in that folder fail).
        for rel, text in spec.get("write", {}).items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        for rel in spec.get("mkdirs", []):
            # Directories a git tree cannot hold: an empty one, or a STORE that is a directory (unreadable as a file).
            (root / rel).mkdir(parents=True, exist_ok=True)
        for rel in spec.get("crlf", []):
            f = root / rel
            f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        for rel, target in spec.get("symlinks", {}).items():
            link = root / rel
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(str(root / target), str(link), target_is_directory=True)
            except (OSError, NotImplementedError):
                # No symlink privilege (Windows without Developer Mode): the
                # linked-folder run cannot be staged; the unit checks still run.
                fails = []
                for unit in spec.get("units", []):
                    fails.extend(UNITS[unit](root, root / "home"))
                return fails or ["SKIP: symlinks unavailable; unit checks passed"]
        for d in spec.get("git", []):
            env = dict(os.environ, GIT_AUTHOR_DATE="2026-09-01T00:00:00Z",
                       GIT_COMMITTER_DATE="2026-09-01T00:00:00Z",
                       GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t")
            for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
                subprocess.run(["git"] + FIXTURE_GIT + ["-C", str(root / d)] + cmd, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for d, url in spec.get("git_origin", {}).items():
            subprocess.run(["git"] + FIXTURE_GIT + ["-C", str(root / d), "remote", "add", "origin", url],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for step in spec.get("git_steps", []):
            gdir = root / step["dir"]
            env = dict(os.environ, GIT_AUTHOR_DATE=step["date"], GIT_COMMITTER_DATE=step["date"],
                       GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t")
            cmds = [] if (gdir / ".git").exists() else [["init", "-q"]]
            cmds += [["add", "--"] + step["paths"], ["commit", "-q", "-m", step.get("message", "step")]]
            for cmd in cmds:
                subprocess.run(["git"] + FIXTURE_GIT + ["-C", str(gdir)] + cmd, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        for rel, when in spec.get("mtimes", {}).items():
            t = _fixture_time(when).timestamp()
            os.utime(str(root / rel), (t, t))
        home = root / "home"
        home.mkdir(exist_ok=True)
        # The case's environment only (default none), so a selftest run inside
        # a Claude Code session never reads that session's CLAUDE_CODE_SESSION_ID.
        ctx = Ctx(home=home, now=_fixture_time(spec["now"]), env=spec.get("env", {}))
        exp = spec["expect"]
        work = work_path(home)
        expect_exit = exp.get("exit", 0)
        # Everything outside the work folder must be untouched; on a refusal
        # or leftover exit, the work folder must be untouched too.
        protect_work = expect_exit != 0 or spec["argv"][0] == "count"
        before = _snapshot(root, None if protect_work else expected_work(home))
        buf, ebuf = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
                code = main(spec["argv"], ctx)
        except Exception as e:  # a crash is a failed case, not a crashed selftest
            code = "exception %s: %s" % (type(e).__name__, e)
        out, err = buf.getvalue(), ebuf.getvalue()
        after = _snapshot(root, None if protect_work else expected_work(home))
        if not protect_work:
            # manifest may create the work folder's parent, and nothing else.
            for rel in (os.path.join("home", ".agent-playbook"),
                        os.path.join("home", ".agent-playbook", "dream-work")):
                after.pop(rel, None)
                before.pop(rel, None)
        if before != after:
            changed = sorted(set(before) ^ set(after)) + sorted(
                k for k in before if k in after and before[k] != after[k])
            fails.append("wrote outside the permitted folder: %s" % changed[:5])
        if code != expect_exit:
            fails.append("exit %s, expected %s; stdout: %s" % (code, expect_exit, out.strip()[:400]))
        for s in exp.get("stdout_contains", []):
            if _norm_seps(s, roots) not in _norm_seps(out, roots):
                fails.append("stdout lacks %r: %s" % (s, out.strip()[:400]))
        for s in exp.get("stdout_not_contains", []):
            if _norm_seps(s, roots) in _norm_seps(out, roots):
                fails.append("stdout contains %r: %s" % (s, out.strip()[:400]))
        for s in exp.get("stderr_contains", []):
            if _norm_seps(s, roots) not in _norm_seps(err, roots):
                fails.append("stderr lacks %r: %s" % (s, err.strip()[:400]))
        if not IS_WINDOWS:
            for pattern, mode in exp.get("modes", {}).items():
                hits = sorted(root.glob(pattern))
                if not hits:
                    fails.append("modes: nothing matches %s" % pattern)
                for h in hits:
                    got = oct(os.stat(str(h)).st_mode & 0o777)
                    if got != mode:
                        fails.append("mode of %s is %s, expected %s" % (h.relative_to(root), got, mode))
        if exp.get("work_absent") and os.path.lexists(str(work)):
            fails.append("work folder exists but should not")
        for rel in exp.get("exists", []):
            if not os.path.lexists(str(root / rel)):
                fails.append("expected path missing: %s" % rel)
        man = None
        if spec["argv"][0] == "manifest" and expect_exit == 0:
            man = load_json(work / "manifest.json")
            if man is None:
                fails.append("manifest.json not written")
        if man is not None:
            view, probs = _manifest_view(man, work)
            fails.extend(probs)
            fails.extend(_key_sep_problems(list(man.get("projects") or {}), str(root)))
            view, index = _norm_seps(view, roots), _norm_seps(man, roots)
            if "manifest" in exp:
                fails.extend(_match(_norm_seps(exp["manifest"], roots), view, "manifest"))
            if "index" in exp:
                fails.extend(_match(_norm_seps(exp["index"], roots), index, "index"))
            # the view's dump: side-file content (errors, entries) included
            dump = json.dumps(view, ensure_ascii=False)
            for c in exp.get("json_contains", []):
                if json.dumps(_norm_seps(c, roots), ensure_ascii=False)[1:-1] not in dump:
                    fails.append("manifest.json lacks %r" % c)
            for c in exp.get("json_not_contains", []):
                if json.dumps(_norm_seps(c, roots), ensure_ascii=False)[1:-1] in dump:
                    fails.append("manifest.json contains %r" % c)
            by_id = {}
            for ppath, proj in view["projects"].items():
                for s in proj["sessions"]:
                    k = s["id"] + ("#history" if s["kind"] == "history_only" else "")
                    by_id[k] = s
                    by_id["%s::%s" % (ppath, k)] = s
            for sid, checks in exp.get("stripped", {}).items():
                s = by_id.get(_norm_seps(sid, roots))
                if s is None:
                    fails.append("no session %s in manifest" % sid)
                    continue
                try:
                    txt = read_text(work / s["stripped"])
                except (OSError, TypeError):
                    fails.append("stripped file missing for %s" % sid)
                    continue
                for c in checks.get("contains", []):
                    if c not in txt:
                        fails.append("%s stripped lacks %r" % (sid, c))
                for c in checks.get("not_contains", []):
                    if c in txt:
                        fails.append("%s stripped contains %r" % (sid, c))
                pos = -1
                for c in checks.get("order", []):
                    nxt = txt.find(c, pos + 1)
                    if nxt < 0:
                        fails.append("%s stripped: %r not found after position %d" % (sid, c, pos))
                        break
                    pos = nxt
        for unit in spec.get("units", []):
            fails.extend(UNITS[unit](root, home))
    finally:
        if spec.get("normal_folders"):
            resolver()._TEST.pop("temp", None)
        if saved_stores is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved_stores
        shutil.rmtree(str(tmp), ignore_errors=True)
    return fails


def _unit_guard(root, home):
    """Guard unit checks: a prefix-sharing sibling and a dot-dot path are not
    the work folder; the exact folder is."""
    fails = []
    home = root / "unit-home"
    home.mkdir()
    ap = home / ".agent-playbook"
    (ap / "dream-work").mkdir(parents=True, exist_ok=True)
    (ap / "dream-work-evil").mkdir(parents=True, exist_ok=True)
    cases = [
        (ap / "dream-work", True),
        (ap / "dream-work-evil", False),
        (ap / "dream-work" / ".." / "dream-work-evil", False),
        (ap / "dream-work" / "sub" / "..", True),
        (ap, False),
        (ap / "dream-work" / "inner", False),
    ]
    for cand, want in cases:
        if guard_ok(cand, home) != want:
            fails.append("guard_ok(%s) != %s" % (cand, want))
    shutil.rmtree(str(ap / "dream-work"))
    shutil.rmtree(str(ap / "dream-work-evil"))
    # clean must refuse a work folder that is a link to a prefix-sharing
    # sibling, and leave the link target intact.
    victim = ap / "dream-work-victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    try:
        os.symlink(str(victim), str(ap / "dream-work"), target_is_directory=True)
    except (OSError, NotImplementedError):
        return fails
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["clean"], Ctx(home=home, now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)))
    if code != EXIT_GUARD or not (victim / "precious.txt").is_file():
        fails.append("clean through a linked work folder: exit %s, victim intact=%s"
                     % (code, (victim / "precious.txt").is_file()))
    if "is a link" not in buf.getvalue() or str(os.path.realpath(str(victim))) not in buf.getvalue():
        fails.append("guard refusal does not name the link and its resolved path: %r"
                     % buf.getvalue().strip())
    os.unlink(str(ap / "dream-work"))
    shutil.rmtree(str(victim))
    return fails


def _unit_usage(root, home):
    """--work is test-only; clean takes no options; subcommand required."""
    fails = []
    for argv in (["manifest", "--state", "s", "--repo", "r", "--work", str(root / "w")],
                 ["count", "--state", "s", "--repo", "r", "--work", str(root / "w")],
                 ["clean", "--work", str(root / "w")],
                 ["clean", "--repo", str(root)],
                 ["manifest", "--repo", str(root)],
                 []):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = main(argv, Ctx(home=home))
        if code != EXIT_USAGE:
            fails.append("argv %s: exit %s, expected %s" % (argv, code, EXIT_USAGE))
    if os.path.lexists(str(root / "w")):
        fails.append("a refused --work run created %s" % (root / "w"))
    return fails


def _quiet_main(argv, ctx):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = main(argv, ctx)
    return code, buf.getvalue()


def _unit_home(root, home):
    """A relative home, a filesystem root and a missing home are refused."""
    fails = []
    for h in (Path("relative-home"), Path(os.path.abspath(os.sep)), root / "no-such-home"):
        code, out = _quiet_main(["clean"], Ctx(home=h))
        if code != EXIT_GUARD or "refused" not in out:
            fails.append("home %s: exit %s, expected %s (%s)" % (h, code, EXIT_GUARD, out.strip()))
    return fails


def _unit_config_plans(root, home):
    """The config repo's plans live in its own workspace store (no carve-out): config_plans_dir returns the
    store's plans/ when that store holds one, else the in-repo plans/; config_store_dir is that store."""
    fails = []
    R = resolver()
    cfg = root / "cfgplans" / "agent-playbook"
    R.fixture_repo(cfg, url="https://github.com/example/agent-playbook.git")
    stores = root / "cfgplans-stores"
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    saved_temp = R._TEST.get("temp")
    os.environ["AGENT_PLAYBOOK_STORES"] = str(stores)
    R._TEST["temp"] = [str(root / "fake-system-temp")]
    R._invalidate_scan_cache()
    try:
        R.fixture_store(stores, "agent-playbook-abcdef", "remote github.com/example/agent-playbook\n")
        R._invalidate_scan_cache()
        sdir = stores / "agent-playbook-abcdef"
        if config_plans_dir(cfg) != cfg / "plans":
            fails.append("a store without plans/: expected the in-repo plans/, got %s" % config_plans_dir(cfg))
        (sdir / "plans" / "done").mkdir(parents=True)
        got_store = config_store_dir(cfg)
        if got_store is None or norm_key(got_store) != norm_key(sdir):
            fails.append("config_store_dir: expected %s, got %s" % (sdir, got_store))
        if norm_key(config_plans_dir(cfg)) != norm_key(sdir / "plans"):
            fails.append("a store with plans/: expected %s, got %s" % (sdir / "plans", config_plans_dir(cfg)))
    finally:
        if saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved
        if saved_temp is None:
            R._TEST.pop("temp", None)
        else:
            R._TEST["temp"] = saved_temp
        R._invalidate_scan_cache()
    return fails


def _unit_races(root, home):
    """Swaps between a check and the act it guards (simulated through the
    test hooks) never redirect a create or a delete."""
    fails = []
    now = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)
    repo = root / "race-repo"
    repo.mkdir()
    man_argv = ["manifest", "--state", str(repo / "absent-state.json"), "--repo", str(repo)]

    def swap_to_link(h, target):
        ap = Path(h) / ".agent-playbook"
        if os.path.lexists(str(ap)):
            os.rename(str(ap), str(Path(h) / "moved-agent-playbook"))
        os.symlink(str(target), str(ap), target_is_directory=True)

    probe = root / "race-link-probe"
    try:
        os.symlink(str(repo), str(probe), target_is_directory=True)
        can_link = True
        os.unlink(str(probe))
    except (OSError, NotImplementedError):
        can_link = False    # Windows without symlink privilege: link swaps skipped

    # clean: .agent-playbook becomes a link after the guard passed.
    h1 = root / "race-home-1"
    (h1 / ".agent-playbook" / "dream-work").mkdir(parents=True)
    victim = root / "race-victim-1"
    (victim / "dream-work").mkdir(parents=True)
    (victim / "dream-work" / "precious.txt").write_text("keep", encoding="utf-8")
    _HOOKS["clean_after_guard"] = lambda h: swap_to_link(h, victim) if can_link else None
    try:
        code, out = _quiet_main(["clean"], Ctx(home=h1, now=now))
    except OSError as e:
        code, out = "exception %s" % e, ""
    finally:
        _HOOKS.clear()
    if can_link and (code != EXIT_GUARD or not (victim / "dream-work" / "precious.txt").is_file()):
        fails.append("clean after a post-guard swap: exit %s, victim intact=%s (%s)"
                     % (code, (victim / "dream-work" / "precious.txt").is_file(), out.strip()))

    # manifest: the work folder appears while the manifest is built -> 5.
    h2 = root / "race-home-2"
    h2.mkdir()
    _HOOKS["manifest_before_mkdir"] = lambda h: (Path(h) / ".agent-playbook" / "dream-work").mkdir(parents=True)
    try:
        code, out = _quiet_main(man_argv, Ctx(home=h2, now=now))
    except Exception as e:
        code, out = "exception %s: %s" % (type(e).__name__, e), ""
    finally:
        _HOOKS.clear()
    if code != EXIT_LEFTOVER:
        fails.append("work folder created during the build: exit %s, expected %s (%s)"
                     % (code, EXIT_LEFTOVER, out.strip()))

    # manifest: .agent-playbook becomes a link while the manifest is built.
    h3 = root / "race-home-3"
    h3.mkdir()
    victim3 = root / "race-victim-3"
    victim3.mkdir()
    _HOOKS["manifest_before_mkdir"] = lambda h: swap_to_link(h, victim3)
    try:
        code, out = _quiet_main(man_argv, Ctx(home=h3, now=now)) if can_link else (EXIT_GUARD, "")
    except Exception as e:
        code, out = "exception %s: %s" % (type(e).__name__, e), ""
    finally:
        _HOOKS.clear()
    if code != EXIT_GUARD or os.listdir(str(victim3)):
        fails.append("manifest after a parent swap: exit %s, link target now holds %s"
                     % (code, os.listdir(str(victim3))))

    # clean: a delete that fails reports the leftover path and exits 6.
    h4 = root / "race-home-4"
    (h4 / ".agent-playbook" / "dream-work").mkdir(parents=True)
    saved = globals()["_rmtree"]

    def failing_rmtree(path):
        raise PermissionError("simulated: file in use")
    globals()["_rmtree"] = failing_rmtree
    try:
        code, out = _quiet_main(["clean"], Ctx(home=h4, now=now))
    except Exception as e:
        code, out = "exception %s: %s" % (type(e).__name__, e), ""
    finally:
        globals()["_rmtree"] = saved
    if code != EXIT_CLEAN_FAILED or "leftover path" not in out:
        fails.append("failed delete: exit %s, expected %s (%s)" % (code, EXIT_CLEAN_FAILED, out.strip()))
    return fails


def _unit_selftest_robust(root, home):
    """A case that raises is a FAIL line; the run continues and the summary
    still prints."""
    fixdir = root / "robust-fixtures"
    (fixdir / "a-broken").mkdir(parents=True)
    (fixdir / "a-broken" / "case.json").write_text("{not json", encoding="utf-8")
    (fixdir / "b-broken").mkdir()
    (fixdir / "b-broken" / "case.json").write_text("{}", encoding="utf-8")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = run_selftest(str(root), fixdir=fixdir, required=())
    except Exception as e:
        return ["run_selftest raised %s: %s" % (type(e).__name__, e)]
    out = buf.getvalue()
    if code != 1 or "FAIL a-broken" not in out or "FAIL b-broken" not in out \
            or "selftest: 2 case(s), 2 failed" not in out:
        return ["crashing cases not reported as FAIL lines: %r" % out]
    return []


def _unit_prune(root, home):
    """AppData, Library and OneDrive* are pruned directly under home only."""
    fails = []
    hp = _parts(os.path.realpath(str(home)))
    for parent, name, want in ((home, "AppData", True), (home, "Library", True),
                               (home, "OneDrive - ExampleCo", True), (home, "src", False),
                               (home / "proj", "Library", False)):
        if home_pruned(str(parent), name, hp) != want:
            fails.append("home_pruned(%s, %s) != %s" % (parent, name, want))
    return fails


def _unit_seps(root, home):
    """The Windows comparator normalization (simulated with on=True and root
    C:\\t\\root): '\\' becomes '/' only in paths under the fixture root, in
    strings and dict keys of expected and actual values, so a native Windows
    manifest matches a fixture written with '/'; other backslashes are kept;
    with on=False nothing changes. The separator check flags a composed key
    that mixes separators."""
    fails = []
    roots = ["C:\\t\\root", "C:/t/root"]
    act = {"projects": {"C:\\t\\root\\proj\\mono\\services\\api": {
        "memory_file": "C:\\t\\root\\proj\\mono\\services\\api\\memory\\MEMORY.md",
        "errors": ["unparseable line L1 in C:\\t\\root\\x.jsonl: bad record"]},
        "C:/t/root/proj\\walked": {}}}
    exp = {"projects": {"C:/t/root/proj/mono/services/api": {
        "memory_file": "C:/t/root/proj/mono/services/api/memory/MEMORY.md",
        "errors": ["$contains:in C:/t/root/x.jsonl: bad record"]},
        "C:/t/root/proj/walked": {}}}
    got = _match(_norm_seps(exp, roots, True), _norm_seps(act, roots, True), "m")
    if got:
        fails.append("normalized Windows paths do not match: %s" % got)
    if not _match(_norm_seps(exp, roots, False), _norm_seps(act, roots, False), "m"):
        fails.append("without normalization a backslash path matched a '/' fixture")
    if _norm_seps(["C:\\t\\root\\a", {"C:\\t\\root\\k": "C:/t/root\\v"}], roots, True) != \
            ["C:/t/root/a", {"C:/t/root/k": "C:/t/root/v"}]:
        fails.append("_norm_seps does not normalize list items and dict keys")
    kept = ["regex a\\d+ b", "D:\\other\\p", {"D:\\x\\y": "z"}]
    if _norm_seps(kept, roots, True) != kept:
        fails.append("_norm_seps altered a backslash outside the fixture root: %r"
                     % _norm_seps(kept, roots, True))
    probs = _key_sep_problems(["C:\\t\\root\\a\\b", "C:\\t\\root\\a/b", "C:/t/root/c\\d"],
                              "C:\\t\\root", "\\")
    if len(probs) != 1 or "a/b" not in probs[0]:
        fails.append("separator check on Windows keys: %r" % probs)
    if _key_sep_problems(["/t/root/a\\b"], "/t/root", "/") == [] or \
            _key_sep_problems(["/t/root/a/b"], "/t/root", "/"):
        fails.append("separator check on POSIX keys is wrong")
    return fails


def _unit_entries(root, home):
    """parse_entries on memory-entries.py: only the three type sections; a ### in a ``` or ~~~
    fence (the other marker nested in it) is body text, not an entry; source_text and
    verified_day read the first Source line and Verified date."""
    fails = []
    text = ("# Memory\n\n## Topics\n\n### Not a type section\n\n## Feedback\n\n### One\n"
            "- **Source**: `a/b.md` | quoted | **Verified**: 2026-09-01\n"
            "```\n### Fenced backtick\n~~~\n### Fenced nested\n```\n"
            "~~~\n### Fenced tilde\n```\n## Fenced section\n~~~\n"
            "### Two\n**Verified**: 2026-02-30\n\n## Declined\n\n### Declined one\n")
    got = [h for h, _b in parse_entries(text)]
    if got != ["One", "Two"]:
        fails.append("parse_entries headings %r, expected ['One', 'Two']" % got)
    bodies = dict(parse_entries(text))
    one = "\n".join(bodies.get("One", []))
    if source_text(one) != "`a/b.md` | quoted" or verified_day(one) != "2026-09-01":
        fails.append("source_text/verified_day of One: %r, %r" % (source_text(one), verified_day(one)))
    if verified_day("\n".join(bodies.get("Two", []))) is not False or source_text("x") != "":
        fails.append("an invalid Verified day is not False, or a missing Source is not ''")
    return fails


def _unit_drive(root, home):
    """Drive letters are uppercased in project keys; nothing else changes."""
    fails = []
    for raw, want in (("c:\\Users\\q\\proj", "C:\\Users\\q\\proj"), ("d:/src/x", "D:/src/x"),
                      ("C:\\Already", "C:\\Already"), ("\\\\?\\c:\\long", "\\\\?\\C:\\long"),
                      ("/home/c:/x", "/home/c:/x"), ("relative/c:", "relative/c:")):
        if canon_path(raw) != want:
            fails.append("canon_path(%r) = %r, expected %r" % (raw, canon_path(raw), want))
    if project_hash("c:\\Users\\q") != project_hash("C:\\Users\\q"):
        fails.append("project_hash differs by drive-letter case")
    return fails


def _unit_caps(root, home):
    """Excerpt caps (each list on its own) and manifest size warning."""
    fails = []
    rows = ["d" * 500] + ["r%d" % i for i in range(1, 50)]
    lines = ["l%d" % i for i in range(1, 100)]
    dec, rev, cut = plan_excerpt(rows, lines)
    if len(dec) != PLAN_DECISIONS_MAX or len(rev) != PLAN_REVIEW_LOG_MAX or \
            dec[0] != "d" * PLAN_ITEM_MAX_CHARS or dec[1:] != rows[1:PLAN_DECISIONS_MAX] or \
            rev != lines[:PLAN_REVIEW_LOG_MAX]:
        fails.append("plan_excerpt kept %d/%d items" % (len(dec), len(rev)))
    if cut != {"decisions": {"kept": 40, "total": 50}, "review_log": {"kept": 60, "total": 99},
               "items_shortened": 1}:
        fails.append("plan_excerpt truncated marker %r" % (cut,))
    # Long decisions never crowd out the review log.
    dec, rev, cut = plan_excerpt(["x" * 399] * 40, ["y"])
    if rev != ["y"] or cut is not False:
        fails.append("plan_excerpt: review log crowded out or false truncation (%r, %r)" % (rev, cut))
    dec, rev, cut = plan_excerpt(["x" * 401], [])
    if dec != ["x" * 400] or not cut or cut["items_shortened"] != 1:
        fails.append("plan_excerpt: an item over %d characters is not cut and marked"
                     % PLAN_ITEM_MAX_CHARS)
    if (PLAN_DECISIONS_MAX, PLAN_REVIEW_LOG_MAX, PLAN_ITEM_MAX_CHARS) != (40, 60, 400):
        fails.append("excerpt caps are %r, expected (40, 60, 400)"
                     % ((PLAN_DECISIONS_MAX, PLAN_REVIEW_LOG_MAX, PLAN_ITEM_MAX_CHARS),))
    if (PLAN_MEMORY_MAX, PLAN_MEMORY_MAX_CHARS) != (20, 200):
        fails.append("memory_relied_on caps are %r, expected (20, 200)"
                     % ((PLAN_MEMORY_MAX, PLAN_MEMORY_MAX_CHARS),))
    # memory_relied_on: 21 headings, one of 201 characters next to one of
    # exactly 200 -> 20 kept, only the 201-character one cut and listed;
    # 20 headings of exactly 200 characters -> nothing cut.
    heads = ["h%02d" % i for i in range(1, 21)] + ["z" * 201]
    heads[0] = "a" * 201
    heads[1] = "c" * 200
    got, cut = memory_relied_on("# T\n\n> **Memory relied on**: %s\n" % " | ".join(heads))
    if got != ["a" * 200] + heads[1:20] or \
            cut != {"kept": 20, "total": 21, "items_shortened": 1, "shortened": [0]}:
        fails.append("memory_relied_on caps: %r / %r" % (got and len(got), cut))
    got, cut = memory_relied_on("# T\n\n> **Memory relied on**: %s\n"
                                % " | ".join(["b" * 200] * 20))
    if got != ["b" * 200] * 20 or cut is not False:
        fails.append("memory_relied_on: boundary 20 x 200 characters marked as cut (%r)" % (cut,))
    # Only the header counts: a body line of the same shape is not the field.
    got, cut = memory_relied_on("# T\n\n> **Scope**: s\n\n## Intent\n\n> **Memory relied on**: X\n")
    if got is not None:
        fails.append("memory_relied_on read a line below the header: %r" % (got,))
    # `none` variants: a trailing `.` and surrounding backticks are stripped.
    for v in ("none.", "`none`", "`none.`", "`none`.", "NONE"):
        got, cut = memory_relied_on("# T\n\n> **Memory relied on**: %s\n" % v)
        if got != [] or cut is not False:
            fails.append("memory_relied_on(%r) gave %r, expected []" % (v, got))
    got, _ = memory_relied_on("# T\n\n> **Memory relied on**: none of these\n")
    if got != ["none of these"]:
        fails.append("memory_relied_on: 'none of these' read as %r" % (got,))
    # The label never spans a newline: a bare `>` line followed by the label
    # on the next line is not the field.
    got, _ = memory_relied_on("# T\n\n>\n**Memory relied on**: X\n")
    if got is not None:
        fails.append("memory_relied_on matched across a newline: %r" % (got,))
    # An empty segment between two separators is dropped, not glued on.
    got, _ = memory_relied_on("# T\n\n> **Memory relied on**: A | | B\n")
    if got != ["A", "B"]:
        fails.append("memory_relied_on('A | | B') gave %r, expected ['A', 'B']" % (got,))
    # A ` | ` inside a backticked span stays inside its heading.
    got, _ = memory_relied_on("# T\n\n> **Memory relied on**: use `a | b` form | C\n")
    if got != ["use `a | b` form", "C"]:
        fails.append("memory_relied_on: backticked pipe split the heading: %r" % (got,))
    got, _ = memory_relied_on("# T\n\n> **Memory relied on**: A | tick ` alone | B\n")
    if got != ["A", "tick ` alone", "B"]:
        fails.append("memory_relied_on: an unmatched backtick swallowed a separator: %r" % (got,))
    # A double-backtick span (it may hold a single backtick) protects its
    # pipes too; an unclosed double run protects nothing.
    for v, want in (("use ``a | b`` form | C", ["use ``a | b`` form", "C"]),
                    ("``a ` | b`` | C", ["``a ` | b``", "C"]),
                    ("A | ``tick | B", ["A", "``tick", "B"])):
        got, _ = memory_relied_on("# T\n\n> **Memory relied on**: %s\n" % v)
        if got != want:
            fails.append("memory_relied_on(%r) gave %r, expected %r" % (v, got, want))
    # A list item that is exactly `none` is dropped.
    for v, want in (("none | A", ["A"]), ("A | None. | B", ["A", "B"]),
                    ("`none` | A", ["A"]), ("none | none", []),
                    ("A | none of these", ["A", "none of these"])):
        got, cut = memory_relied_on("# T\n\n> **Memory relied on**: %s\n" % v)
        if got != want or cut is not False:
            fails.append("memory_relied_on(%r) gave %r, expected %r" % (v, got, want))
    # Two header lines: the first wins.
    got, _ = memory_relied_on("# T\n\n> **Memory relied on**: First\n"
                              "> **Memory relied on**: Second\n")
    if got != ["First"]:
        fails.append("memory_relied_on: two header lines gave %r, expected the first" % (got,))
    if size_warning(MANIFEST_WARN_BYTES) is not None or \
            "warning: manifest.json" not in (size_warning(MANIFEST_WARN_BYTES + 1) or ""):
        fails.append("size_warning threshold is not 'over %d bytes'" % MANIFEST_WARN_BYTES)
    if MANIFEST_WARN_BYTES != 200 * 1024:
        fails.append("MANIFEST_WARN_BYTES is %d, expected 200 KB" % MANIFEST_WARN_BYTES)
    # manifest prints the warning after writing manifest.json (threshold
    # lowered for the run so a tiny manifest crosses it).
    h = root / "caps-home"
    h.mkdir()
    repo = root / "caps-repo"
    repo.mkdir()
    saved = globals()["MANIFEST_WARN_BYTES"]
    globals()["MANIFEST_WARN_BYTES"] = 10
    try:
        code, out = _quiet_main(["manifest", "--state", str(repo / "absent-state.json"),
                                 "--repo", str(repo)],
                                Ctx(home=h, now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)))
    finally:
        globals()["MANIFEST_WARN_BYTES"] = saved
    if code != EXIT_OK or "warning: manifest.json is" not in out:
        fails.append("manifest over the size threshold printed no warning: exit %s, %r"
                     % (code, out.strip()[-300:]))
    return fails


def _unit_quiet_seed(root, home):
    """Quiet-cadence seed and key lookup, checked against values computed here: the
    literal seed of fixed keys (1-3, so a seed replaced by 0 fails), the
    manifest's seeded projects (value recomputed from each key), and a
    drive-letter-case variant of a stored key."""
    fails = []
    for key, want in (("user memory", 2), ("/fixture/quiet", 3), ("/srv/beta", 3)):
        if quiet_seed(key) != want:
            fails.append("quiet_seed(%r) = %r, expected %d" % (key, quiet_seed(key), want))
    idx = quiet_index({"c:\\Fixture\\Proj\\": 4})
    got = idx.get(norm_key(canon_path("C:\\Fixture\\Proj")))
    if got != ("c:\\Fixture\\Proj\\", 4):
        fails.append("quiet_index misses a drive-letter-case variant: %r" % (idx,))
    man = load_json(work_path(home) / "manifest.json")
    if not isinstance(man, dict):
        return fails + ["quiet-seed: manifest.json not readable"]
    st = load_json(root / "repo" / "memory" / ".dream-state.json") or {}
    stored = {norm_key(canon_path(k)) for k in
              ((st.get("quiet_sweeps") or {}).get("projects") or {})}
    seen = 0
    for key, proj in (man.get("projects") or {}).items():
        if proj.get("memory_file") is None:
            continue
        skey = proj.get("state_key", key)
        if norm_key(canon_path(skey)) in stored:
            continue
        seen += 1
        want = int(hashlib.sha256(skey.encode("utf-8")).hexdigest()[:8], 16) % 5
        if proj.get("quiet_sweeps") != want:
            fails.append("project %s: quiet_sweeps %r, expected the seed %d"
                         % (key, proj.get("quiet_sweeps"), want))
    if not stored and not seen:
        fails.append("quiet-seed: no seeded project with a memory file in the manifest")
    return fails


def _quiet_state_run(base, quiet, state_key=None):
    """One manifest run over a fresh project `alpha` with a clean memory file,
    stopping before build() so a test can set its state_key. -> (project
    index entry, user_memory cadence, top-level errors, project path)."""
    base.mkdir()
    proj, repo, h = base / "proj" / "alpha", base / "repo", base / "home"
    (proj / "memory").mkdir(parents=True)
    (proj / "AGENTS.md").write_text("# alpha\n", encoding="utf-8")
    (proj / "memory" / "MEMORY.md").write_text(
        "# Memory\n\n## Feedback\n\n### Clean\n\n**Why**: unit.\n**How to apply**: unit.\n"
        "**Source**: unit | **Verified**: 2026-09-01\n", encoding="utf-8")
    repo.mkdir()
    h.mkdir()
    ppath = proj.as_posix()
    st = {"schema_version": 3, "last_run": "2026-09-22T07:33:27+02:00",
          "projects": {ppath: {"last_analyzed": "2026-09-23T00:00:00Z"}},
          "rejected_lessons": [], "outcome_tags": [], "episodic_ledger": [],
          "cost_records": [], "model_routing": {}, "deferred_sessions": {}}
    if quiet is not _ABSENT:
        st["quiet_sweeps"] = _subst(quiet, ppath)
    (repo / "state.json").write_text(json.dumps(st), encoding="utf-8")
    args = parse_args(["manifest", "--state", str(repo / "state.json"), "--repo", str(repo)])
    run = Run(args, Ctx(home=h, now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)))
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        run.load_state()
        run.scan_claude()
        run.scan_kiro()
        run.discover()
        run.attach_sessions()
        if state_key is not None:
            run.projects[norm_key(canon_path(ppath))].state_key = state_key
        projects, _ = run.build()
        _, cadence = run.user_memory()
    return projects.get(canon_path(ppath)) or {}, cadence, run.errors, ppath


_ABSENT = object()


def _unit_quiet_state(root, home):
    """Quiet-cadence state handling: an invalid stored value (null and integers above
    INT64_MAX included) is seeded and named in errors[] (project and user
    memory), while 2**63 - 1 is kept; a quiet_sweeps or projects value of
    the wrong shape is named in errors[] and seeded; a valid state names
    nothing; the seed is taken from state_key when it differs from the
    reported key."""
    fails = []
    base = root / "quiet-state"
    base.mkdir()
    proj, cad, errs, ppath = _quiet_state_run(
        base / "invalid", {"projects": {"{ROOT}": -1}, "user_memory": "4"})
    if proj.get("quiet_sweeps") != quiet_seed(ppath):
        fails.append("stored -1: quiet_sweeps %r, expected the seed %d"
                     % (proj.get("quiet_sweeps"), quiet_seed(ppath)))
    if not any("quiet_sweeps projects[" in e and "not a non-negative integer (-1)" in e for e in errs):
        fails.append("stored -1: no errors[] line naming it: %r" % (errs,))
    if cad.get("quiet_sweeps") != quiet_seed(USER_MEMORY_KEY) or \
            not any("quiet_sweeps user_memory is not a non-negative integer ('4')" in e for e in errs):
        fails.append("stored user_memory '4': value %r, errors %r (expected the seed %d and a line)"
                     % (cad.get("quiet_sweeps"), errs, quiet_seed(USER_MEMORY_KEY)))
    # Present but invalid values the validators FAIL: null, and integers
    # above INT64_MAX (2**63 - 1 itself is valid).
    for name, stored, uwant in (("null-values", None, "None"), ("over-int64", 2 ** 63, str(2 ** 63))):
        proj, cad, errs, ppath = _quiet_state_run(
            base / name, {"projects": {"{ROOT}": stored}, "user_memory": stored})
        if proj.get("quiet_sweeps") != quiet_seed(ppath) or not any(
                "quiet_sweeps projects[" in e and "not a non-negative integer (%s)" % uwant in e
                for e in errs):
            fails.append("stored project %s: quiet_sweeps %r, errors %r (expected the seed %d and "
                         "a line)" % (name, proj.get("quiet_sweeps"), errs, quiet_seed(ppath)))
        if cad.get("quiet_sweeps") != quiet_seed(USER_MEMORY_KEY) or not any(
                "quiet_sweeps user_memory is not a non-negative integer (%s)" % uwant in e
                for e in errs):
            fails.append("stored user_memory %s: value %r, errors %r (expected the seed %d and a "
                         "line)" % (name, cad.get("quiet_sweeps"), errs, quiet_seed(USER_MEMORY_KEY)))
    proj, cad, errs, _ = _quiet_state_run(
        base / "int64-max", {"projects": {"{ROOT}": 2 ** 63 - 1}, "user_memory": 2 ** 63 - 1})
    if (proj.get("quiet_sweeps") != 2 ** 63 - 1 or cad.get("quiet_sweeps") != 2 ** 63 - 1
            or any("quiet_sweeps" in e for e in errs)):
        fails.append("stored 2**63-1: project %r, user_memory %r, errors %r (expected it kept)"
                     % (proj.get("quiet_sweeps"), cad.get("quiet_sweeps"), errs))
    shapes = [("list", [], "quiet_sweeps is not an object"),
              ("null", None, "quiet_sweeps is not an object"),
              ("projects-null", {"projects": None}, "quiet_sweeps.projects is not an object"),
              ("zero", 0, "quiet_sweeps is not an object"),
              ("empty-string", "", "quiet_sweeps is not an object"),
              ("projects-list", {"projects": []}, "quiet_sweeps.projects is not an object"),
              ("projects-int", {"projects": 7}, "quiet_sweeps.projects is not an object")]
    for name, shape, want in shapes:
        proj, cad, errs, ppath = _quiet_state_run(base / name, shape)
        if not any(want in e for e in errs):
            fails.append("quiet_sweeps %r: no errors[] line %r: %r" % (shape, want, errs))
        if proj.get("quiet_sweeps") != quiet_seed(ppath):
            fails.append("quiet_sweeps %r: project not seeded (%r)" % (shape, proj.get("quiet_sweeps")))
    for name, shape in (("valid-empty", {}), ("absent", _ABSENT)):
        _, _, errs, _ = _quiet_state_run(base / name, shape)
        if any("quiet_sweeps" in e for e in errs):
            fails.append("quiet_sweeps %s: unexpected errors[] line %r" % (name, errs))
    # The seed follows state_key (the key [APP-STATE] stamps under), not the
    # reported key: pick a key variant whose seed differs, so the check never
    # passes by collision.
    probe = (base / "state-key" / "proj" / "alpha").as_posix()
    variant = next((probe + "/" * n for n in range(1, 40)
                    if quiet_seed(probe + "/" * n) != quiet_seed(probe)), None)
    if variant is None:
        return fails + ["state-key: no key variant with a different seed"]
    proj, _, _, ppath = _quiet_state_run(base / "state-key", {}, state_key=variant)
    if proj.get("state_key") != variant or proj.get("quiet_sweeps") != quiet_seed(variant):
        fails.append("state_key %r: quiet_sweeps %r, expected its seed %d (reported key seed %d)"
                     % (variant, proj.get("quiet_sweeps"), quiet_seed(variant), quiet_seed(ppath)))
    return fails


def _unit_anchors_commit(root, home):
    """cited_commit_missing on a present commit: a short and a full sha of a
    commit in the first known repository, and one held only by a second
    known repository, are present; a sha in no known repository is missing.
    Also version_after at the precision written."""
    fails = []
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    shas = []
    for name in ("unit-one", "unit-two"):
        d = root / name
        d.mkdir()
        (d / "f.txt").write_text(name, encoding="utf-8")
        for cmd in (["init", "-q"], ["add", "f.txt"], ["commit", "-q", "-m", name]):
            subprocess.run(["git"] + FIXTURE_GIT + ["-C", str(d)] + cmd, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        out = git_out(d, "rev-parse", "HEAD")
        if not out:
            return ["anchors-commit: could not create the %s repository" % name]
        shas.append(out.strip())
    one, two = shas
    mem = root / "unit-one" / "MEMORY.md"
    mem.write_text("# Memory\n\n## Feedback\n\n### Present\n\n**Source**: `%s` and `%s` "
                   "and `%s` | **Verified**: 2026-09-01\n\n### Absent\n\n**Source**: "
                   "`%s` | **Verified**: 2026-09-01\n"
                   % (one[:7], one, two[:9], "0" * 39 + "a"), encoding="utf-8")
    roots = [str(root / "unit-one"), str(root / "unit-two")]
    got = build_entries(mem, [roots[0]], CiteCheck(roots), set(),
                        dt.date(2026, 9, 24), Anchors(roots, home / ".claude", home / ".kiro"))
    want = {"Present": [], "Absent": ["0" * 39 + "a"]}
    for e in got or []:
        if e["cited_commit_missing"] != want.get(e["heading"]):
            fails.append("anchors-commit: %s -> %r, expected %r"
                         % (e["heading"], e["cited_commit_missing"], want.get(e["heading"])))
    if [e["heading"] for e in got or []] != ["Present", "Absent"]:
        fails.append("anchors-commit: entries %r" % (got,))
    # A later memory file needing an older day reads the missing span of
    # the same history and keeps what the first read found.
    d = root / "unit-span"
    d.mkdir()
    for name, when in (("old.txt", "2026-07-10T10:00:00Z"), ("new.txt", "2026-08-10T10:00:00Z")):
        (d / name).write_text(name, encoding="utf-8")
        denv = dict(env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        for cmd in ([["init", "-q"]] if name == "old.txt" else []) + [["add", name],
                                                                    ["commit", "-q", "-m", name]]:
            subprocess.run(["git"] + FIXTURE_GIT + ["-C", str(d)] + cmd, env=denv, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
    anc = Anchors([str(d)], home / ".claude", home / ".kiro")
    for name, verified, want in (("new.txt", "2026-08-01", True), ("old.txt", "2026-07-01", True),
                                 ("new.txt", "2026-08-01", True), ("old.txt", "2026-07-10", False)):
        if anc.changed_after(d / name, verified, verified) is not want:
            fails.append("anchors span: %s verified %s -> not %r" % (name, verified, want))
    # Git failing must fail open, with a note: no runner at all, a shallow
    # clone, and a readable repository whose cat-file and log calls fail.
    sha = "0" * 39 + "a"
    head = git_out(d, "rev-parse", "HEAD").strip()
    stubs = (
        ("no git", lambda repo, args, stdin=None: None,
         ["git could not read", "no complete repository answered: cited_commit_missing skipped"]),
        ("shallow", lambda repo, args, stdin=None:
            (0, "true\n.git\n%s\n" % head) if args[0] == "rev-parse" else (0, ""),
         ["shallow clone", "no complete repository answered: cited_commit_missing skipped"]),
        ("calls fail", lambda repo, args, stdin=None:
            (0, "false\n.git\n%s\n" % head) if args[0] == "rev-parse" else (128, ""),
         ["git cat-file failed", "no complete repository answered: cited_commit_missing skipped",
          "git log failed"]),
    )
    for label, stub, want_notes in stubs:
        anc = Anchors([str(d)], home / ".claude", home / ".kiro")
        anc._git = stub
        if anc.missing_commits([sha]) != []:
            fails.append("anchors %s: a commit reported missing with no repository answering"
                         % label)
        if anc.changed_after(d / "new.txt", "2026-08-01", "2026-08-01"):
            fails.append("anchors %s: a path reported changed without a readable log" % label)
        for w in want_notes:
            if not any(w in n for n in anc.notes):
                fails.append("anchors %s: no note containing %r in %r" % (label, w, anc.notes))
    # A shallow clone cannot prove a commit absent, but can show it present.
    anc = Anchors([str(d)], home / ".claude", home / ".kiro")
    anc._git = lambda repo, args, stdin=None: \
        (0, "true\n.git\n%s\n" % head) if args[0] == "rev-parse" else (0, "%s commit 100\n" % sha)
    if anc.missing_commits([sha]) != [] or any("no complete repository answered" in n for n in anc.notes):
        fails.append("anchors shallow hit: a commit a shallow clone holds was not found (%r)"
                     % anc.notes)
    # A shallow clone that answers "missing" proves nothing: with no complete
    # repository answering, no commit is reported missing.
    anc = Anchors([str(d)], home / ".claude", home / ".kiro")
    anc._git = lambda repo, args, stdin=None: \
        (0, "true\n.git\n%s\n" % head) if args[0] == "rev-parse" \
        else (0, "%s^{commit} missing\n" % sha)
    if anc.missing_commits([sha]) != [] or \
            not any("no complete repository answered" in n for n in anc.notes):
        fails.append("anchors shallow miss: a shallow clone proved a commit absent (%r)"
                     % anc.notes)
    # A linked worktree's common git folder may have a space in its path.
    anc = Anchors([str(d)], home / ".claude", home / ".kiro")
    anc._git = lambda repo, args, stdin=None: (0, "false\nC:/My Repo/.git\n%s\n" % head)
    got = anc.history_key(str(d))
    if got is None or got[1] != head or not got[0].endswith("my repo/.git"):
        fails.append("anchors spaced common dir: history_key %r, notes %r" % (got, anc.notes))
    for cur, ref, want in (("2.1.291", "2.1", False), ("2.2.0", "2.1", True),
                           ("2.1.291", "2.1.290", True), ("2.18", "2.18.0", False),
                           ("3", "2.18", True), ("dev", "2.1", None)):
        if version_after(cur, ref) is not want:
            fails.append("version_after(%r, %r) is %r, expected %r"
                         % (cur, ref, version_after(cur, ref), want))
    return fails


def _unit_cite_msys(root, home):
    """A Git Bash absolute path (/c/...) inside a known project is checked
    against that project when the mapping is on (forced here, so it runs
    on any host) and left unchecked when it is off. On a host whose case
    root has a drive letter, the real tree is used too: an existing file is
    present and a missing one is reported."""
    fails = []
    mem = root / "proj" / "alpha" / "memory" / "MEMORY.md"
    for known, cited in (("C:/x/proj/alpha", "/c/x/proj/alpha/nope.md"),
                         ("D:\\X\\Proj\\Alpha", "/d/x/proj/alpha/nope.md")):
        on, off = CiteCheck([known], windows=True), CiteCheck([known], windows=False)
        if on.owner(cited) is None or on.present(mem, [], cited):
            fails.append("mapping on: %r under %r not reported missing" % (cited, known))
        if cited_paths("`%s`" % cited, keep_abs=lambda t: on.owner(t) is not None) != [cited]:
            fails.append("mapping on: %r not extracted as a cited path" % cited)
        if off.owner(cited) is not None:
            fails.append("mapping off: %r owned by %r" % (cited, known))
    for path, want in (("/c/x", "C:/x"), ("/c", "C:/"), ("/c/", "C:/"),
                       ("/cygdrive/c/x", "C:/x"), ("/cygdrive/d", "D:/"),
                       ("/home/x", "/home/x"), ("/cc/x", "/cc/x"), ("//c/x", "//c/x"),
                       ("/c:/x", "/c:/x"), ("/cygdrive/cc/x", "/cygdrive/cc/x")):
        got = msys_to_native(path, windows=True)
        if got != want:
            fails.append("msys_to_native(%r) = %r, expected %r" % (path, got, want))
    if msys_to_native("/c/x", windows=False) != "/c/x":
        fails.append("msys_to_native maps /c/x with the mapping off")
    cyg = CiteCheck(["C:/x/proj/alpha"], windows=True)
    if cyg.owner("/cygdrive/c/x/proj/alpha/nope.md") is None:
        fails.append("mapping on: /cygdrive/c/x/proj/alpha/nope.md not owned by C:/x/proj/alpha")
    cwd = re.match(r"^([A-Za-z]):[\\/].", os.getcwd())
    if cwd:
        # A bare drive is its root, never the drive-relative form that
        # resolves to the current directory and so to the project holding it.
        bare = "/" + cwd.group(1).lower()
        if CiteCheck([os.getcwd()], windows=True).owner(bare) is not None:
            fails.append("mapping on: bare %s owned by the current directory %s"
                         % (bare, os.getcwd()))
    m = re.match(r"^([A-Za-z]):/(.*)$", root.as_posix())
    if m:
        msys = "/%s/%s" % (m.group(1).lower(), m.group(2))
        chk = CiteCheck([(root / "proj" / "alpha").as_posix()], windows=True)
        if not chk.present(mem, [], msys + "/proj/alpha/docs/other.md"):
            fails.append("real tree: existing %s/proj/alpha/docs/other.md not present" % msys)
        if chk.present(mem, [], msys + "/proj/alpha/nope.md"):
            fails.append("real tree: missing %s/proj/alpha/nope.md not reported" % msys)
    return fails


def _unit_due_count(root, home):
    """The work-volume arm leaves out history_only stubs and the sessions of
    a Claude Code scratchpad pseudo-project; the manifest still lists them."""
    fails = []
    for path, want in (
            ("C:\\Users\\u\\AppData\\Local\\Temp\\claude\\C--Users-u-proj\\abc\\scratchpad\\chan_cwd", True),
            ("C:\\Users\\u\\AppData\\Local\\Temp\\claude\\C--Users-u-proj\\abc\\scratchpad", True),
            ("/tmp/claude-1000/-home-u-proj/abc/scratchpad", True),
            ("C:\\Users\\u\\Documents\\src\\PowerAtlas", False),
            ("C:\\Users\\u\\AppData\\Local\\Temp\\dm-abc\\proj\\alpha", False),
            ("C:\\Users\\u\\AppData\\Local\\Temp\\claude\\C--Users-u-proj\\abc", False),
            ("/home/u/claude/scratchpad", False)):
        if in_claude_scratchpad(path) != want:
            fails.append("in_claude_scratchpad(%r) != %s" % (path, want))
    scratch = "/tmp/claude-1000/-home-u-proj/abc/scratchpad"
    projects = {
        "/p/a": {"sessions": [{"kind": "normal"}, {"kind": "deferred"}, {"kind": "history_only"}]},
        scratch: {"sessions": [{"kind": "normal"}]},
    }
    if due_session_count(projects) != 2:
        fails.append("due_session_count counted %d, expected 2" % due_session_count(projects))
    return fails


def _unit_baseline_unreadable(root, home):
    """`baseline --by-role` on a session file that cannot be read while its
    sub-agent files can (the case dir's tree: a phase agent with 10+20+1 = 31
    tokens, peak context 30; a drafter with 40+2 = 42 tokens, peak 40): the
    run names the file, prints the session peak as n/a and exits 0."""
    global read_jsonl
    fails = []
    session = home / ".claude" / "projects" / "-ROOT-proj" / ("b5a00000-0000-4000-8000-%012d.jsonl" % 18)
    real = read_jsonl

    def locked(path):
        if Path(path) == session:
            raise OSError("locked")
        return real(path)

    buf = io.StringIO()
    read_jsonl = locked
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main(["baseline", "--session", str(session), "--by-role"])
    except BaseException as e:
        return ["baseline with an unreadable session raised %s: %s" % (type(e).__name__, e)]
    finally:
        read_jsonl = real
    out = buf.getvalue()
    if code != EXIT_OK:
        fails.append("exit %r, expected %d" % (code, EXIT_OK))
    for want in ("error: unreadable %s: locked\n" % session,
                 "files: 1 session + 2 sub-agent transcript(s)",
                 "tokens: 73\n",
                 "role orchestrator: files 1, tokens: 31\n",
                 "role drafter: files 1, tokens: 42\n",
                 "peak context orchestrator (session): n/a (session transcript unreadable)\n"
                 "peak context orchestrator agent-a0000000000000001: 30\n"
                 "peak context drafter agent-a0000000000000002: 40\n"):
        if want not in out:
            fails.append("unreadable session: output lacks %r: %s" % (want, out.strip()[:500]))
    return fails


def _unit_memory_budget(root, home):
    """The `count` budget line: OVER over the pin; an unreadable memory file
    is named; a counter failure prints `unknown` and never raises."""
    global MEMORY_BUDGET_WORDS, _load_qmemory_eval
    fails = []
    repo = root / "mb-repo"
    (repo / "memory").mkdir(parents=True)
    (repo / "memory" / "MEMORY.md").write_text("one two three four five six\n", encoding="utf-8")
    (repo / "memory" / "HIGHER_ORDER.md").write_text("seven eight\n", encoding="utf-8")
    saved_pin, saved_loader = MEMORY_BUDGET_WORDS, _load_qmemory_eval
    try:
        for pin, want in ((8, "memory budget: 8/8"), (7, "memory budget: 8/7 OVER")):
            MEMORY_BUDGET_WORDS = pin
            got = memory_budget_line(repo)
            if got != want:
                fails.append("pin %d: %r, expected %r" % (pin, got, want))
        MEMORY_BUDGET_WORDS = saved_pin
        (repo / "memory" / "MEMORY.md").write_bytes(b"bad \xff\xfe utf-8\n")
        got = memory_budget_line(repo)
        want = "memory budget: 2/%d (MEMORY.md unreadable)" % saved_pin
        if got != want:
            fails.append("unreadable MEMORY.md: %r, expected %r" % (got, want))

        def broken():
            raise OSError("qmemory-eval.py not found")
        _load_qmemory_eval = broken
        got = memory_budget_line(repo)
        if got != "memory budget: unknown (OSError: qmemory-eval.py not found)":
            fails.append("loader failure: %r" % got)

        def exits():
            raise SystemExit(3)
        _load_qmemory_eval = exits
        got = memory_budget_line(repo)
        if got != "memory budget: unknown (SystemExit: 3)":
            fails.append("SystemExit loader: %r" % got)
    except BaseException as e:
        fails.append("memory budget line raised %s: %s" % (type(e).__name__, e))
    finally:
        MEMORY_BUDGET_WORDS, _load_qmemory_eval = saved_pin, saved_loader
    return fails


UNITS = {"baseline-unreadable": _unit_baseline_unreadable, "memory-budget": _unit_memory_budget, "due-count": _unit_due_count, "anchors-commit": _unit_anchors_commit,
         "cite-msys": _unit_cite_msys, "quiet-seed": _unit_quiet_seed, "quiet-state": _unit_quiet_state, "guard": _unit_guard, "usage": _unit_usage, "home": _unit_home,
         "races": _unit_races, "selftest-robust": _unit_selftest_robust,
         "prune": _unit_prune, "seps": _unit_seps, "drive": _unit_drive, "caps": _unit_caps,
         "entries": _unit_entries, "config-plans": _unit_config_plans}


def run_selftest(scratch=None, fixdir=None, required=None):
    fixdir = Path(fixdir) if fixdir is not None else \
        Path(os.path.realpath(__file__)).parent / "fixtures" / "dream-manifest"
    required = REQUIRED_CASES if required is None else required
    if scratch is not None:
        Path(scratch).mkdir(parents=True, exist_ok=True)
    names = sorted(d.name for d in fixdir.iterdir() if (d / "case.json").is_file()) \
        if fixdir.is_dir() else []
    failed = 0
    for req in required:
        if req not in names:
            print("FAIL %s: fixture missing" % req)
            failed += 1
    for name in names:
        try:
            fails = _run_case(fixdir / name, scratch)
        except Exception as e:  # one broken case never stops the run
            fails = ["case raised %s: %s" % (type(e).__name__, e)]
        if fails and all(f.startswith("SKIP:") for f in fails):
            print("SKIP %s: %s" % (name, fails[0][5:].strip()))
        elif fails:
            failed += 1
            print("FAIL %s" % name)
            for f in fails:
                print("  - %s" % f)
        else:
            print("PASS %s" % name)
    print("selftest: %d case(s), %d failed" % (len(names), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
