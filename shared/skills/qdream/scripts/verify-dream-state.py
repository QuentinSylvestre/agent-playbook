#!/usr/bin/env python3
"""verify-dream-state.py -- deterministic schema validator for the /qdream
state file (memory/.dream-state.json).

Validates the file against its DECLARED schema_version (canonical spec:
shared/skills/qdream/memory-rules.md § State File Format):
  v1: schema_version / last_run / projects only (legacy, pre-migration).
  v2: v1 keys plus rejected_lessons / outcome_tags / episodic_ledger, with
      per-element key sets, reason/outcome vocabularies, and YYYY-MM-DD
      date fields checked.
  v3: v2 keys plus cost_records / model_routing / deferred_sessions /
      quiet_sweeps, with key sets, routing roles, count and date fields,
      the kind-baseline null rule checked. A quiet_sweeps.projects key
      need not be a projects key (a project with a memory file is counted
      before it is first stamped). Integers above 2**63-1 FAIL (the bound the
      .ps1 twin had: its ConvertFrom-Json made them BigInteger).
      The optional cost-record tokens_by_role holds the five roles
      (orchestrator, task4, verifier, drafter, other) or the four legacy
      ones (no drafter), needs a non-null tokens and sums to it. A
      model_routing provider needs task4 and verifier; drafter is optional
      and, when present, a non-empty string. A kind-sweep record carrying
      tokens_by_role must also list all five dropped_by_stage stages and hold
      findings.kept <= surfaced and sum(dropped_by_stage) <= surfaced - kept;
      a record without it is exempt (written before the field existed). An
      earlier FAIL on the record skips these invariants, and they stop at the
      first FAIL.
Unknown top-level keys, half-migrated files (a v1 file carrying v2 or v3
sections, a v2 file carrying v3 sections), and malformed elements FAIL.
v2 and v3 files also get the append-only check: the baseline's
episodic_ledger must be an exact prefix of the current one -- element-wise
JSON equality, key order ignored -- so a dropped, rewritten or reordered
record FAILs even when the count is padded back (see --ledger-baseline).
On that FAIL restore the records from `git show HEAD:memory/.dream-state.json`;
never pad or edit the ledger to pass. The /qdream sweep runs this after every
state write (dream-write.py's run_validator); it is the deterministic tool
consumer for the state-file shapes (shared/AGENTS.md § Structure Requires a
Consumer).

Usage:
  verify-dream-state.py [--help] [--ledger-baseline <file>] [<state-file>]
  verify-dream-state.py --selftest

  <state-file>  Path to the state file. Default: memory/.dream-state.json
                relative to the repo root inferred from this script's real
                location (symlinks resolved; shared/skills/qdream/scripts/ ->
                repo root).
  --ledger-baseline <file>
                Compare episodic_ledger against this file instead of git.
                Without it, the baseline is `git show HEAD:memory/.dream-state.json`,
                used only when <state-file> IS memory/.dream-state.json of
                its git work tree; otherwise (fixtures, temp copies, no
                git, file not committed at HEAD) the check prints a
                "note: episodic_ledger shrink check skipped (...)" line
                and is not counted. A baseline that cannot be read or is not
                a JSON object is a FAIL.
  Unknown options, a missing or empty --ledger-baseline value and a second
  positional argument exit 2 (usage on stderr).

Output: "ok:" / "FAIL:" / "note:" lines plus a summary line
"verify-dream-state: ok=N fail=M (schema vX)" on stdout (UTF-8, LF line
endings). Exit 0 when fail=0, else 1. A missing state file is a SKIP (exit 0,
"SKIP: state file not found (no full /qdream run yet)") -- no full /qdream run
has happened yet. A path that exists but is not a regular file (a directory, a
dangling link) is a SKIP too (exit 0, "SKIP: not a regular file: <path>").
dream-write.py's run_validator reads either SKIP over a path that exists as
"did not run", never as a pass. A state file that cannot be read (an OSError
such as a permission error) prints nothing on stdout, a one-line reason on
stderr, and exits 2: the guard did not run, as the journal validator does;
dream-write.py reads it as "did not run" and refuses the swap.
Exit 2, the guard did not run: not run in the playbook venv (the venv guard
below), a usage error, or any other unexpected exception, which prints
nothing on stdout and "verify-dream-state.py: guard did not run: <reason>"
on stderr.

Encoding and JSON: read as utf-8-sig, so a leading BOM never changes a
verdict. A file that is not UTF-8, is empty or whitespace-only, or is nested
too deeply to decode (RecursionError) is "FAIL: not valid JSON". JSON follows
Python's json module: a duplicate key keeps the last value, keys are
case-sensitive, a one-element top-level array is not an object, ISO-timestamp
strings stay strings, NaN/Infinity parse as numbers, and lenient syntax
(trailing commas, single quotes, comments) is a parse error. Where the .ps1
twin (ConvertFrom-Json) differed, this script keeps the Python behaviour.

--selftest runs every row of fixtures/dream-state/expected.tsv in process
(exit code and must_contain substring, the consumer test-parity.sh also
asserts on the twins), the missing-file SKIP, the not-a-regular-file SKIP of
a directory (in process and as a subprocess), the exact summary line of the
valid fixture, an injected unreadable file (exit 1, stderr reason), an
injected deep-nesting file (parse FAIL, exit 1), an injected unexpected
exception (exit 2, did-not-run line), the git-HEAD skip notes, and the usage
errors; a few rows also run as a subprocess the way dream-write.py's
run_validator launches it ([sys.executable, "-I", this file,
"--ledger-baseline", <file>, <path>]), checking the CLI, LF stdout and exit
code. Prints "verify-dream-state selftest: N failure(s), M check(s), 0 skipped"
and exits 1 on any failure.

Python 3.8+, stdlib only. The Python successor of verify-dream-state.{sh,ps1}
(plan 261016 Phase 14); dream-write.py's run_validator launches this script.
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "dream-state")


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


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\S+$")
DEFERRED_KEY_RE = re.compile(r"^[^:]+:.+$")
V1_KEYS = {"schema_version", "last_run", "projects"}
V2_ONLY_KEYS = ["rejected_lessons", "outcome_tags", "episodic_ledger"]
V3_ONLY_KEYS = ["cost_records", "model_routing", "deferred_sessions", "quiet_sweeps"]
# Optional v3 section: absent means an empty ledger (memory-rules.md § Singleton ledger).
SINGLETON_KEY = "singleton_ledger"
ROUTING_ROLES = ["task4", "verifier"]
# Optional routing roles: absent is valid, present must be a non-empty string.
ROUTING_OPTIONAL = ["drafter"]
# tokens_by_role: the five roles, or the four legacy roles of records written
# before the drafter role existed (plan 261012 Phase 3).
TOKEN_ROLES = ["orchestrator", "task4", "verifier", "drafter", "other"]
TOKEN_ROLES_LEGACY = ["orchestrator", "task4", "verifier", "other"]
DROP_STAGES = ["already_known", "not_durable", "unsupported", "suppressed", "contradicts_governance"]
COST_RECORDS_MAX = 20
LIVE_REL_PATH = "memory/.dream-state.json"
# The same file as the store repo sees it: user memory lives in its reserved user/ directory, behind the
# config repo's `memory` link (shared/AGENTS.md § Config Repo Locations).
STORE_REL_PATH = "user/memory/.dream-state.json"
INT64_MAX = 2 ** 63 - 1
LEDGER_FIX = ("append-only: restore the baseline records from "
              "`git show HEAD:memory/.dream-state.json` (in the store repo: "
              "`git show HEAD:user/memory/.dream-state.json`), never pad")
SKIP_MISSING = "SKIP: state file not found (no full /qdream run yet)"
SKIP_NOT_REGULAR = "SKIP: not a regular file: %s"
USAGE = "usage: verify-dream-state.py [--help] [--ledger-baseline <file>] [<state-file>]"


def default_path():
    return os.path.join(HERE, "..", "..", "..", "..", "memory", ".dream-state.json")


def _read_text(path):
    """The one read of a state or baseline file (the selftest replaces it to inject failures)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def is_date(v):
    return nonempty_str(v) and DATE_RE.match(v) is not None


def nonneg_int(v):
    # Bounded at int64, the range the .ps1 twin accepted ([int]/[long]).
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= INT64_MAX


def is_count_map(v):
    return isinstance(v, dict) and all(nonneg_int(x) for x in v.values())


def canon(v):
    # Element identity for the prefix check: key order ignored; types kept
    # distinct (1 vs 1.0 vs true).
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


class _Checker(object):
    def __init__(self):
        self.out = []
        self.ok_count = 0
        self.fail_count = 0

    def ok(self, msg):
        self.ok_count += 1
        self.out.append("ok: " + msg)

    def fail(self, msg):
        self.fail_count += 1
        self.out.append("FAIL: " + msg)

    def note(self, msg):
        self.out.append("note: " + msg)

    def summary(self, schema_label):
        self.out.append("verify-dream-state: ok=%d fail=%d (schema %s)"
                        % (self.ok_count, self.fail_count, schema_label))
        return (1 if self.fail_count else 0), self.out, []

    # --- v2 array sections --------------------------------------------------

    def check_elements(self, name, arr, allowed, checker):
        # Per-element pass shared by every array section: object check, the
        # section's checker, then unknown keys. Returns True when all passed.
        section_ok = True
        for i, el in enumerate(arr):
            if not isinstance(el, dict):
                self.fail("%s[%d] -- not an object" % (name, i))
                section_ok = False
                continue
            if not checker(name, i, el):
                section_ok = False
            for k in sorted(set(el.keys()) - allowed):
                self.fail('%s[%d] -- unknown key "%s"' % (name, i, k))
                section_ok = False
        return section_ok

    def check_array(self, data, name, allowed, checker):
        arr = data.get(name)
        if not isinstance(arr, list):
            self.fail("%s missing or not an array (required since v2)" % name)
            return
        if self.check_elements(name, arr, allowed, checker):
            self.ok("%s (%d records)" % (name, len(arr)))

    def check_singleton(self, name, i, el):
        good = True
        for k in ("target", "gist"):
            if not (isinstance(el.get(k), str) and el[k].strip()):
                self.fail("%s[%d] -- %s must be a non-empty string" % (name, i, k))
                good = False
        s = el.get("sessions")
        if not (isinstance(s, list) and s and all(isinstance(x, str) and x for x in s)):
            self.fail("%s[%d] -- sessions must be a non-empty list of session ids" % (name, i))
            good = False
        for k in ("first_seen", "last_seen"):
            if not (isinstance(el.get(k), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", el[k])):
                self.fail("%s[%d] -- %s must be YYYY-MM-DD" % (name, i, k))
                good = False
        return good

    def check_rejected(self, name, i, el):
        good = True
        for key in ("target", "signal"):
            if not nonempty_str(el.get(key)):
                self.fail("%s[%d] -- %s missing or empty" % (name, i, key))
                good = False
        if el.get("reason") not in ("refuted", "skipped"):
            self.fail('%s[%d] -- reason must be "refuted" or "skipped"' % (name, i))
            good = False
        if not (nonempty_str(el.get("date")) and DATE_RE.match(el["date"])):
            self.fail("%s[%d] -- date must be YYYY-MM-DD" % (name, i))
            good = False
        return good

    def check_outcome(self, name, i, el):
        good = True
        if not nonempty_str(el.get("target")):
            self.fail("%s[%d] -- target missing or empty" % (name, i))
            good = False
        if not (nonempty_str(el.get("applied")) and DATE_RE.match(el["applied"])):
            self.fail("%s[%d] -- applied must be YYYY-MM-DD" % (name, i))
            good = False
        has_outcome = "outcome" in el
        has_checked = "checked" in el
        if has_outcome != has_checked:
            self.fail("%s[%d] -- outcome and checked must be set together" % (name, i))
            good = False
        if has_outcome and el.get("outcome") not in ("recurred", "not-recurred"):
            self.fail('%s[%d] -- outcome must be "recurred" or "not-recurred"' % (name, i))
            good = False
        if has_checked and not (nonempty_str(el.get("checked")) and DATE_RE.match(el["checked"])):
            self.fail("%s[%d] -- checked must be YYYY-MM-DD" % (name, i))
            good = False
        return good

    def check_episode(self, name, i, el):
        good = True
        for key in ("what", "where", "outcome"):
            if not nonempty_str(el.get(key)):
                self.fail("%s[%d] -- %s missing or empty" % (name, i, key))
                good = False
        if not (nonempty_str(el.get("when")) and DATE_RE.match(el["when"])):
            self.fail("%s[%d] -- when must be YYYY-MM-DD" % (name, i))
            good = False
        ss = el.get("support_set")
        if not (isinstance(ss, list) and all(nonempty_str(p) for p in ss)):
            self.fail("%s[%d] -- support_set must be an array of non-empty strings" % (name, i))
            good = False
        return good

    # --- v3 sections --------------------------------------------------------

    def check_cost_record(self, name, i, el):
        good = True
        if not is_date(el.get("date")):
            self.fail("%s[%d] -- date must be YYYY-MM-DD" % (name, i))
            good = False
        if el.get("kind") not in ("sweep", "baseline"):
            self.fail('%s[%d] -- kind must be "sweep" or "baseline"' % (name, i))
            good = False
        # A kind-baseline record may hold null for the fields its source could
        # not measure (plan D27); the key must still be present.
        nullable = ({"projects_analyzed", "bytes_read", "findings", "proposals"}
                    if el.get("kind") == "baseline" else set())

        def null_ok(key):
            return key in nullable and key in el and el[key] is None
        for key in ("projects_analyzed", "sessions_read", "bytes_read"):
            if null_ok(key):
                continue
            if not nonneg_int(el.get(key)):
                self.fail("%s[%d] -- %s must be a non-negative integer" % (name, i, key))
                good = False
        if not is_count_map(el.get("agents")):
            self.fail("%s[%d] -- agents must be an object of role -> non-negative integer" % (name, i))
            good = False
        models = el.get("models")
        if not (isinstance(models, dict) and all(nonempty_str(x) for x in models.values())):
            self.fail("%s[%d] -- models must be an object of role -> model name" % (name, i))
            good = False
        fd = el.get("findings")
        if not null_ok("findings") and not (
                isinstance(fd, dict) and set(fd.keys()) == {"surfaced", "kept", "dropped_by_stage"}
                and nonneg_int(fd["surfaced"]) and nonneg_int(fd["kept"])
                and is_count_map(fd["dropped_by_stage"])):
            self.fail("%s[%d] -- findings must be {surfaced, kept, dropped_by_stage} with "
                      "non-negative integer counts" % (name, i))
            good = False
        pr = el.get("proposals")
        if not null_ok("proposals") and not (
                isinstance(pr, dict) and set(pr.keys()) == {"surfaced", "applied"}
                and nonneg_int(pr["surfaced"]) and nonneg_int(pr["applied"])):
            self.fail("%s[%d] -- proposals must be {surfaced, applied} with non-negative integer counts"
                      % (name, i))
            good = False
        if not ("tokens" in el and (el["tokens"] is None or nonneg_int(el["tokens"]))):
            self.fail("%s[%d] -- tokens must be a non-negative integer or null" % (name, i))
            good = False
        if "weighted_tokens" in el and not nonneg_int(el["weighted_tokens"]):
            self.fail("%s[%d] -- weighted_tokens must be a non-negative integer" % (name, i))
            good = False
        # tokens_by_role (plan 261006 Phase 9): optional, accepted on any kind.
        # Its presence on a kind-sweep record also opts the record into the
        # findings invariants, so records written before the field existed stay
        # exempt.
        if "tokens_by_role" in el:
            tr = el["tokens_by_role"]
            if not (isinstance(tr, dict)
                    and (set(tr.keys()) == set(TOKEN_ROLES) or set(tr.keys()) == set(TOKEN_ROLES_LEGACY))
                    and all(nonneg_int(v) for v in tr.values())):
                self.fail("%s[%d] -- tokens_by_role must be {orchestrator, task4, verifier, other} or "
                          "{orchestrator, task4, verifier, drafter, other} with non-negative integer counts"
                          % (name, i))
                good = False
            else:
                # The role totals come from the same baseline run as tokens, so
                # they need it and add up to it.
                if el.get("tokens") is None:
                    self.fail("%s[%d] -- tokens_by_role needs a non-null tokens" % (name, i))
                    good = False
                elif nonneg_int(el.get("tokens")) and sum(tr.values()) != el["tokens"]:
                    self.fail("%s[%d] -- tokens_by_role must sum to tokens" % (name, i))
                    good = False
            if good and el.get("kind") == "sweep" and isinstance(fd, dict) and nonneg_int(fd.get("surfaced")) \
                    and nonneg_int(fd.get("kept")) and is_count_map(fd.get("dropped_by_stage")):
                if set(fd["dropped_by_stage"].keys()) != set(DROP_STAGES):
                    self.fail("%s[%d] -- findings.dropped_by_stage must list every stage: %s"
                              % (name, i, ", ".join(DROP_STAGES)))
                    good = False
                elif fd["kept"] > fd["surfaced"]:
                    self.fail("%s[%d] -- findings.kept exceeds findings.surfaced" % (name, i))
                    good = False
                elif sum(fd["dropped_by_stage"].values()) > fd["surfaced"] - fd["kept"]:
                    self.fail("%s[%d] -- findings.dropped_by_stage sums above surfaced minus kept"
                              % (name, i))
                    good = False
        return good

    def check_keyed_section(self, name, obj, allowed, checker, unit):
        # Object-of-objects sections (model_routing, deferred_sessions).
        section_ok = True
        for key, val in obj.items():
            if not isinstance(val, dict):
                self.fail('%s["%s"] -- not an object' % (name, key))
                section_ok = False
                continue
            if not checker(name, key, val):
                section_ok = False
            for k in sorted(set(val.keys()) - allowed):
                self.fail('%s["%s"] -- unknown key "%s"' % (name, key, k))
                section_ok = False
        if section_ok:
            self.ok("%s (%d %s)" % (name, len(obj), unit))

    def check_routing(self, name, key, val):
        good = True
        for role in ROUTING_ROLES:
            if not nonempty_str(val.get(role)):
                self.fail('%s["%s"] -- %s missing or empty' % (name, key, role))
                good = False
        for role in ROUTING_OPTIONAL:
            if role in val and not nonempty_str(val[role]):
                self.fail('%s["%s"] -- %s must be a non-empty string when present' % (name, key, role))
                good = False
        if not is_date(val.get("confirmed")):
            self.fail('%s["%s"] -- confirmed must be YYYY-MM-DD' % (name, key))
            good = False
        return good

    def check_deferred(self, name, key, val):
        good = True
        if not DEFERRED_KEY_RE.match(key):
            self.fail('%s["%s"] -- key must be "<provider>:<session id>"' % (name, key))
            good = False
        for field in ("project", "last_record"):
            if not nonempty_str(val.get(field)):
                self.fail('%s["%s"] -- %s missing or empty' % (name, key, field))
                good = False
        if not is_date(val.get("since")):
            self.fail('%s["%s"] -- since must be YYYY-MM-DD' % (name, key))
            good = False
        return good

    def check_v3(self, data):
        cr = data.get("cost_records")
        if not isinstance(cr, list):
            self.fail("cost_records missing or not an array (required in v3)")
        else:
            section_ok = True
            if len(cr) > COST_RECORDS_MAX:
                self.fail("cost_records -- %d records, at most %d are kept (drop the oldest kind sweep record)"
                          % (len(cr), COST_RECORDS_MAX))
                section_ok = False
            allowed = {"date", "kind", "projects_analyzed", "sessions_read", "bytes_read",
                       "agents", "models", "findings", "proposals", "tokens", "tokens_by_role",
                       "weighted_tokens"}
            if not self.check_elements("cost_records", cr, allowed, self.check_cost_record):
                section_ok = False
            if section_ok:
                self.ok("cost_records (%d records)" % len(cr))

        mr = data.get("model_routing")
        if not isinstance(mr, dict):
            self.fail("model_routing missing or not an object (required in v3)")
        else:
            self.check_keyed_section("model_routing", mr,
                                     set(ROUTING_ROLES) | set(ROUTING_OPTIONAL) | {"confirmed"},
                                     self.check_routing, "providers")

        dsec = data.get("deferred_sessions")
        if not isinstance(dsec, dict):
            self.fail("deferred_sessions missing or not an object (required in v3)")
        else:
            self.check_keyed_section("deferred_sessions", dsec, {"project", "last_record", "since"},
                                     self.check_deferred, "sessions")

        # quiet_sweeps (plan D24): {"projects": {<projects key>: int >= 0},
        # "user_memory": int >= 0}, both optional. A projects key need not be a
        # key of projects: a never-stamped project with a memory file is counted
        # too (Phase 10 review, 2026-09-25).
        qs = data.get("quiet_sweeps")
        if not isinstance(qs, dict):
            self.fail("quiet_sweeps missing or not an object (required in v3)")
        else:
            section_ok = True
            for k in sorted(set(qs.keys()) - {"projects", "user_memory"}):
                self.fail('quiet_sweeps -- unknown key "%s"' % k)
                section_ok = False
            if "user_memory" in qs and not nonneg_int(qs["user_memory"]):
                self.fail("quiet_sweeps -- user_memory must be a non-negative integer")
                section_ok = False
            qp = qs.get("projects", {})
            if not isinstance(qp, dict):
                self.fail("quiet_sweeps -- projects must be an object")
                section_ok = False
                qp = {}
            for key, v in qp.items():
                if not nonneg_int(v):
                    self.fail('quiet_sweeps.projects["%s"] -- must be a non-negative integer' % key)
                    section_ok = False
            if section_ok:
                self.ok("quiet_sweeps (%d projects)" % len(qp))


# --- episodic_ledger is append-only (v2 and later) ---------------------------
# Baseline: --ledger-baseline <file> when given; else, only when the state file
# is memory/.dream-state.json of its git work tree, the HEAD-committed version.
# Anything else is a printed, uncounted skip. The baseline ledger must be an
# exact prefix of the current one: HIGHER_ORDER.md nodes point at records
# positionally (`episodic_ledger #N`), so a count-only check would let a
# dropped-then-appended or rewritten record re-point them silently.

def ledger_baseline_text(state_path, base_arg):
    """-> (text, skip_reason); text None + reason None means unreadable."""
    if base_arg:
        try:
            return _read_text(base_arg), None
        except (OSError, UnicodeDecodeError):
            return None, None
    state_dir = os.path.dirname(os.path.abspath(state_path))

    def git(*args):
        try:
            r = subprocess.run(["git", "-C", state_dir] + list(args), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            return r.returncode, r.stdout
        except OSError:
            return 127, b""

    rc, out = git("rev-parse", "--show-prefix")
    if rc != 0:
        return None, "no git work tree"
    rel = out.decode("utf-8", "replace").strip() + os.path.basename(state_path)
    if rel not in (LIVE_REL_PATH, STORE_REL_PATH):
        return None, "not the repo's memory/.dream-state.json and no ledger baseline given"
    rc, out = git("show", "HEAD:" + rel)
    if rc != 0:
        return None, "%s not committed at HEAD" % rel
    return out.decode("utf-8-sig", "replace"), None


def _check_ledger(c, data, state_path, base_arg):
    ledger = data.get("episodic_ledger")
    if not isinstance(ledger, list):
        c.note("episodic_ledger shrink check skipped (episodic_ledger is not an array)")
        return
    base_text, skip_reason = ledger_baseline_text(state_path, base_arg)
    if skip_reason is not None:
        c.note("episodic_ledger shrink check skipped (%s)" % skip_reason)
        return
    try:
        base = json.loads(base_text) if base_text is not None else None
    except (ValueError, RecursionError):
        base = None
    if not isinstance(base, dict):
        c.fail("episodic_ledger baseline is not a readable JSON object")
        return
    bl = base.get("episodic_ledger")
    if not isinstance(bl, list):
        bl = []
    if len(ledger) < len(bl):
        c.fail("episodic_ledger shrank to %d records from baseline %d (%s)" % (len(ledger), len(bl), LEDGER_FIX))
        return
    diff_at = next((j for j in range(len(bl)) if canon(ledger[j]) != canon(bl[j])), None)
    if diff_at is not None:
        c.fail("episodic_ledger[%d] differs from the baseline record at that position (%s)" % (diff_at, LEDGER_FIX))
    else:
        c.ok("episodic_ledger append-only (%d records, baseline %d is a prefix)" % (len(ledger), len(bl)))


def check(path, baseline=""):
    """-> (exit code, stdout lines, stderr lines). Never prints."""
    if not os.path.isfile(path):
        if os.path.lexists(path):
            return 0, [SKIP_NOT_REGULAR % path], []
        return 0, [SKIP_MISSING], []
    c = _Checker()
    try:
        text = _read_text(path)
    except UnicodeDecodeError:
        text = None
    except OSError as exc:
        return 2, [], ["verify-dream-state: cannot read %s (%s: %s)" % (path, type(exc).__name__, exc)]
    try:
        if text is None:
            raise ValueError("not UTF-8")
        data = json.loads(text)
    except (ValueError, RecursionError):  # RecursionError: nesting too deep to decode
        c.fail("not valid JSON")
        return c.summary("unknown")

    if not isinstance(data, dict):
        c.fail("top-level is not a JSON object")
        return c.summary("unknown")
    c.ok("valid JSON object")

    sv = data.get("schema_version")
    if not (isinstance(sv, int) and not isinstance(sv, bool) and sv in (1, 2, 3)):
        c.fail("schema_version must be the integer 1, 2 or 3")
        return c.summary("unknown")
    c.ok("schema_version %d" % sv)
    schema_label = "v%d" % sv

    if nonempty_str(data.get("last_run")) and ISO_RE.match(data["last_run"]):
        c.ok("last_run")
    else:
        c.fail("last_run missing or not an ISO-8601 timestamp")

    projects = data.get("projects")
    if not isinstance(projects, dict):
        c.fail("projects missing or not an object")
    else:
        section_ok = True
        for ppath, meta in projects.items():
            if not isinstance(meta, dict):
                c.fail('projects["%s"] -- not an object' % ppath)
                section_ok = False
                continue
            if not (nonempty_str(meta.get("last_analyzed")) and ISO_RE.match(meta["last_analyzed"])):
                c.fail('projects["%s"] -- last_analyzed missing or not an ISO-8601 timestamp' % ppath)
                section_ok = False
            for k in sorted(set(meta.keys()) - {"last_analyzed"}):
                c.fail('projects["%s"] -- unknown key "%s"' % (ppath, k))
                section_ok = False
        if section_ok:
            c.ok("projects (%d entries)" % len(projects))

    allowed_top = set(V1_KEYS)
    if sv >= 2:
        allowed_top |= set(V2_ONLY_KEYS)
    if sv >= 3:
        allowed_top |= set(V3_ONLY_KEYS) | {SINGLETON_KEY}
    top_ok = True
    for k in sorted(set(data.keys()) - allowed_top):
        if k in V3_ONLY_KEYS or k == SINGLETON_KEY:
            c.fail('v%d file carries v3 section "%s" (half-migrated write?)' % (sv, k))
        elif k in V2_ONLY_KEYS:
            c.fail('v1 file carries v2 section "%s" (half-migrated write?)' % k)
        else:
            c.fail('unknown top-level key "%s"' % k)
        top_ok = False
    if top_ok:
        c.ok("top-level keys")

    if SINGLETON_KEY in data and sv >= 3:
        c.check_array(data, SINGLETON_KEY, {"target", "gist", "sessions", "first_seen", "last_seen"},
                      c.check_singleton)
    if sv >= 2:
        c.check_array(data, "rejected_lessons", {"target", "signal", "reason", "date"}, c.check_rejected)
        c.check_array(data, "outcome_tags", {"target", "applied", "outcome", "checked"}, c.check_outcome)
        c.check_array(data, "episodic_ledger", {"what", "where", "when", "outcome", "support_set"},
                      c.check_episode)
    if sv >= 3:
        c.check_v3(data)
    if sv >= 2:
        _check_ledger(c, data, path, baseline)

    if sv == 1:
        c.note("schema v1 (legacy) -- the next /qdream full run migrates this file to v3")
    elif sv == 2:
        c.note("schema v2 -- the next /qdream full run migrates this file to v3")
    return c.summary(schema_label)


def run_check(path, baseline=""):
    """check(), with any unexpected exception turned into exit 2 ("guard did not run") instead of a
    traceback that would exit 1 and read as a finding. -> (exit code, stdout lines, stderr lines)."""
    try:
        return check(path, baseline)
    except Exception as exc:
        return 2, [], ["verify-dream-state.py: guard did not run: %s: %s" % (type(exc).__name__, exc)]


def parse_args(argv):
    """-> ("help"|"selftest"|"run", state path or "", baseline or "") or (None, stderr lines, 2)."""
    state, baseline = "", ""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--help":
            return "help", "", ""
        if a == "--selftest":
            return "selftest", "", ""
        if a == "--ledger-baseline":
            if i + 1 >= len(argv) or argv[i + 1] == "":
                return None, [USAGE], 2
            baseline = argv[i + 1]
            i += 2
            continue
        if a.startswith("-"):
            return None, ["verify-dream-state.py: unknown option: %s" % a, USAGE], 2
        if state:
            return None, ["verify-dream-state.py: unexpected extra argument: %s" % a, USAGE], 2
        state = a
        i += 1
    return "run", state, baseline


# --- selftest -----------------------------------------------------------------

def _read_rows():
    rows = []
    with open(os.path.join(FIXTURES, "expected.tsv"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line.strip() or line.startswith("#") or line.startswith("fixture\t"):
                continue
            fx, code, base, must = line.split("\t", 3)
            rows.append((fx, int(code), base, must))
    return rows


def selftest():
    fails, checks = [], [0]

    def chk(label, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (label, (": " + detail) if detail else ""))

    def fx(name):
        return os.path.join(FIXTURES, name)

    rows = _read_rows()
    chk("expected.tsv lists rows", len(rows) > 0)
    listed = set(r[0] for r in rows)
    for name in sorted(os.listdir(FIXTURES)):
        if name.endswith(".json") and not name.startswith("ledger-baseline"):
            chk("%s: has a row in expected.tsv" % name, name in listed)
    for name, code, base, must in rows:
        chk("%s: input exists" % name, os.path.isfile(fx(name)))
        b = "" if base == "-" else fx(base)
        try:
            rc, out, err = check(fx(name), b)
        except Exception as exc:  # a crash of the code under test fails the row, not the run
            chk("%s: runs" % name, False, "%s: %s" % (type(exc).__name__, exc))
            continue
        chk("%s: exit" % name, rc == code, "got %d, expected %d; %r" % (rc, code, out[-3:]))
        chk("%s: output contains %r" % (name, must), any(must in ln for ln in out), repr(out))
        chk("%s: ends with the summary line" % name,
            bool(out) and out[-1].startswith("verify-dream-state: ok="), repr(out[-1:]))

    # Exact summaries and skip notes.
    rc, out, err = check(fx("v3-valid.json"), fx("ledger-baseline.json"))
    chk("v3-valid: exact summary", out[-1:] == ["verify-dream-state: ok=13 fail=0 (schema v3)"], repr(out[-1:]))
    rc, out, err = check(fx("v3-valid.json"))
    chk("v3-valid without baseline: skip note, uncounted",
        rc == 0 and any(ln.startswith("note: episodic_ledger shrink check skipped (") for ln in out)
        and out[-1] == "verify-dream-state: ok=12 fail=0 (schema v3)", repr(out))
    rc, out, err = check(fx("does-not-exist.json"))
    chk("missing file: SKIP, exit 0", (rc, out, err) == (0, [SKIP_MISSING], []), repr((rc, out, err)))
    rc, out, err = check(FIXTURES)
    chk("a directory: not-a-regular-file SKIP, exit 0",
        (rc, out, err) == (0, ["SKIP: not a regular file: " + FIXTURES], []), repr((rc, out, err)))
    rc, out, err = check(fx("v3-valid.json"), fx("does-not-exist.json"))
    chk("unreadable baseline: FAIL", rc == 1 and "FAIL: episodic_ledger baseline is not a readable JSON object"
        in out, repr(out))

    # Injected reads: unreadable file, not UTF-8, deep nesting, an unexpected exception.
    real_read = globals()["_read_text"]
    vpath = fx("v3-valid.json")

    def deny(path):
        raise PermissionError(13, "Permission denied", path)

    def not_utf8(path):
        return b"\xff\xfe{}".decode("utf-8")

    def deep(path):
        return "[" * 100000 + "]" * 100000

    def empty(path):
        return "   \n\t\n"

    def boom(path):
        raise RuntimeError("injected")
    try:
        globals()["_read_text"] = deny
        rc, out, err = run_check(vpath)
        chk("cannot-read: exit 2, no stdout, one stderr reason",
            rc == 2 and out == [] and len(err) == 1 and err[0].startswith("verify-dream-state: cannot read ")
            and "PermissionError" in err[0], repr((rc, out, err)))
        for label, reader in (("not UTF-8", not_utf8), ("deep nesting", deep), ("whitespace only", empty)):
            globals()["_read_text"] = reader
            rc, out, err = run_check(vpath)
            chk("%s: parse FAIL, exit 1" % label,
                (rc, out, err) == (1, ["FAIL: not valid JSON",
                                       "verify-dream-state: ok=0 fail=1 (schema unknown)"], []),
                repr((rc, out, err)))
        globals()["_read_text"] = boom
        rc, out, err = run_check(vpath)
        chk("unexpected exception: exit 2, did-not-run line",
            (rc, out, err) == (2, [], ["verify-dream-state.py: guard did not run: RuntimeError: injected"]),
            repr((rc, out, err)))
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            rc = main([vpath])
        chk("unexpected exception via main: exit 2, did-not-run on stderr",
            rc == 2 and so.getvalue() == ""
            and se.getvalue() == "verify-dream-state.py: guard did not run: RuntimeError: injected\n",
            "rc %r, stdout %r, stderr %r" % (rc, so.getvalue(), se.getvalue()))
    finally:
        globals()["_read_text"] = real_read

    # Usage errors.
    for label, argv in (("unknown option", ["--bogus"]), ("lone dash", ["-"]),
                        ("extra positional", [vpath, fx("v2-plain.json")]),
                        ("baseline without value", ["--ledger-baseline"]),
                        ("baseline empty", ["--ledger-baseline", "", vpath])):
        chk("usage: %s exits 2" % label, parse_args(argv)[0] is None and parse_args(argv)[2] == 2,
            repr(parse_args(argv)))
    chk("usage: flag after the positional", parse_args([vpath, "--ledger-baseline", "b"]) == ("run", vpath, "b"))

    # Subprocess runs, the way dream-write.py's run_validator launches this file.
    me = os.path.realpath(__file__)
    for label, args, code, last in (
            ("v3-valid with baseline", ["--ledger-baseline", fx("ledger-baseline.json"), vpath], 0,
             "verify-dream-state: ok=13 fail=0 (schema v3)"),
            ("v3-ledger-shrunk with baseline",
             ["--ledger-baseline", fx("ledger-baseline.json"), fx("v3-ledger-shrunk.json")], 1, None),
            ("missing file", [fx("does-not-exist.json")], 0, SKIP_MISSING),
            ("a directory", [FIXTURES], 0, "SKIP: not a regular file: " + FIXTURES),
            ("unknown option", ["--bogus"], 2, None)):
        r = subprocess.run([sys.executable, "-I", me] + args, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        chk("%s (subprocess): exit" % label, r.returncode == code,
            "got %d, expected %d; stderr %r" % (r.returncode, code, r.stderr[:300]))
        chk("%s (subprocess): LF stdout" % label, b"\r" not in r.stdout, repr(r.stdout[:300]))
        if last is not None:
            lines = r.stdout.decode("utf-8", "replace").split("\n")
            chk("%s (subprocess): last line" % label, len(lines) >= 2 and lines[-2] == last
                and lines[-1] == "", repr(lines[-3:]))
        if code == 2:
            chk("%s (subprocess): nothing on stdout" % label, r.stdout == b"", repr(r.stdout[:300]))

    # The git baseline: the state file committed at HEAD, in the config repo (memory/) or, with user memory
    # behind the `memory` link, in the store repo (user/memory/); any other path has no git baseline.
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="vds-git-")
    try:
        for label, rel in (("config repo", LIVE_REL_PATH), ("store repo", STORE_REL_PATH),
                           ("other path", "elsewhere/.dream-state.json")):
            repo = os.path.join(tmp, label.replace(" ", "-"))
            f = os.path.join(repo, *rel.split("/"))
            os.makedirs(os.path.dirname(f))
            with open(f, "w", encoding="utf-8", newline="\n") as fh:
                fh.write('{"episodic_ledger": []}\n')
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t.invalid",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t.invalid")
            ok = True
            for args in (["init", "-q"], ["add", "-A"], ["-c", "commit.gpgsign=false", "commit", "-q", "-m", "s"]):
                try:
                    ok = ok and subprocess.run(["git", "-C", repo] + args, env=env, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                except OSError:
                    ok = False
            if not ok:
                chk("git baseline (%s): git available" % label, False, "git init/commit failed")
                continue
            text, why = ledger_baseline_text(f, "")
            if label == "other path":
                chk("git baseline (%s): none" % label, text is None and "no ledger baseline" in (why or ""), repr(why))
            else:
                chk("git baseline (%s): read from HEAD" % label, text is not None and "episodic_ledger" in text,
                    repr((text, why)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for f in fails:
        print("FAIL: " + f)
    print("verify-dream-state selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
    return 1 if fails else 0


def main(argv=None):
    _require_venv(__file__)
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    argv = sys.argv[1:] if argv is None else argv
    mode, a, b = parse_args(argv)
    if mode is None:
        for line in a:
            sys.stderr.write(line + "\n")
        return b
    if mode == "help":
        sys.stdout.write(__doc__)
        return 0
    if mode == "selftest":
        return selftest()
    rc, out, err = run_check(a or default_path(), b)
    for line in out:
        sys.stdout.write(line + "\n")
    for line in err:
        sys.stdout.flush()
        sys.stderr.write(line + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
