#!/usr/bin/env python3
"""qmemory-eval.py -- read-only memory-health metrics. Writes nothing."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _load_sibling(filename, modname):
    """A sibling script loaded by path, never through sys.path or a bytecode cache
    (plan 261016 Phase 5; the hook imports this file, so no import-time failure here)."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


_RESOLVER = None


def _config_plans_done(config_repo):
    """The config repo's plans/done/: in its own workspace store when that store holds plans (like any
    workspace's), else the in-repo plans/done/ (an older tree, or a fixture without a store repo)."""
    try:
        r = _resolver().find(str(config_repo), "plans")
        if r.status == "found" and r.path is not None and (Path(r.path) / "plans").is_dir():
            return Path(r.path) / "plans" / "done"
    except Exception:  # noqa: BLE001 -- a lookup fault falls back to the in-repo archive
        pass
    return Path(config_repo) / "plans" / "done"


def _resolver():
    """store-resolver.py (plan 261016 Phase 5): every store lookup below goes through it."""
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = _load_sibling("store-resolver.py", "store_resolver")
    return _RESOLVER


_ENTRIES = None


def _memory_entries():
    """memory-entries.py (plan 261016 Phase 11): every memory file below is parsed through it."""
    global _ENTRIES
    if _ENTRIES is None:
        _ENTRIES = _load_sibling("memory-entries.py", "memory_entries")
    return _ENTRIES


def _store_artifact(config_repo, project_path_key):
    """A project's memory class, per the resolver: the store-repo store that holds it, else none."""
    return _resolver().resolve_artifact(project_path_key, "memory")


# A store-only project's key (dream-manifest.py STORE_KEY_PREFIX): `store:` plus its STORE identity text.
STORE_KEY_PREFIX = "store:"


def _store_dir_for_key(key_text):
    """-> ('ok', store dir or None) for a `store:<identity>` key's identity text, or ('unreadable', None)
    when the store repo is missing or cannot be scanned. The store is the one whose STORE identity equals
    the key's (`remote <host/path>`, then ` path <subpath>` for a monorepo store, or `local <path>`)."""
    r = _resolver()
    st, valid, _inv, _why = r.scan_stores()
    if st != "ok":
        return "unreadable", None
    d = r.store_for_key(key_text, valid)
    return "ok", (Path(d) if d is not None else None)


def _heading_verdict(store_dir, heading):
    """The present/absent test of a store's memory file: resolved, confirmed-absent, or indeterminate
    when the store holds no memory file or it cannot be read."""
    store_mem = store_dir / "memory" / "MEMORY.md"
    if not store_mem.exists():
        return "indeterminate"
    try:
        entries = parse_memory_entries(store_mem.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return "indeterminate"
    if heading in {e["heading"] for e in entries}:
        return "resolved"
    return "confirmed-absent"


# --- Anchor detection (anchor completeness) ---

ANCHOR_RES = [
    re.compile(r"#L\d+(-\d+)?\b"),
    re.compile(r"(?i)\bsessions?\s+[0-9a-f]{6,}"),
    re.compile(r"plans/done/\S+\.md"),
    # A plan-slug (YYMMDD followed by - or _) is re-openable regardless of any
    # trailing section/phase, so it counts — matches 260520-1700,
    # 260612-1725_TITLE, 260521_PRECOMPUTE. A 4-digit-year date (2026-06-12) has
    # no 6-digit run and a hex hash lacks the trailing separator, so neither
    # false-matches; a bare governance "file § section" ref carries no slug and
    # stays free-text.
    re.compile(r"\b\d{6}[-_]"),
]


def is_anchor(field: str) -> bool:
    """A governance 'file § section' ref is NOT a provenance anchor."""
    return bool(field) and any(r.search(field) for r in ANCHOR_RES)


# --- Memory file parsing ---

def parse_memory_entries(text: str, include_signals: bool = False) -> list:
    """Extract entries from a MEMORY.md or HIGHER_ORDER.md file.

    Each entry starts with a ### heading and may have a Source field.
    Skips the preamble, the ## Declined section and, unless include_signals
    is true, [improvement_signal] entries: anchor completeness does not count
    signals, but a `user memory § [improvement_signal] ...` Support-set
    pointer must still resolve, so the heading set asks for them.
    Entries and their Source value follow memory-entries.py (fence-aware; a
    ### before any ## is not an entry, and a "# " line ends the section, so
    a ### after it and before the next ## is not one either); a section whose
    name starts with "Declined" is skipped.
    """
    me = _memory_entries()
    entries = []
    for section, heading, body, _line_no in me.entries(text):
        if section.startswith("Declined") or not heading:
            continue
        if include_signals or not heading.startswith("[improvement_signal]"):
            entries.append({"heading": heading, "source": me.source(body)})
    return entries


# --- Support-set parsing and resolution ---

POINTER_PREFIX_RE = re.compile(
    r"(?:episodic_ledger #|user memory §|project memory \(|session |\d{6}[-_]\S+ § )"
)


def split_support_set(raw: str) -> list:
    """Split bracket-wrapped support-set into individual pointers.

    Splits on ', ' only before a known pointer prefix to avoid
    over-splitting headings that contain commas.
    """
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]

    if not raw:
        return []

    pointers = []
    current_start = 0

    for m in POINTER_PREFIX_RE.finditer(raw):
        pos = m.start()
        if pos == 0:
            continue
        # Check if preceded by ", "
        if pos >= 2 and raw[pos - 2:pos] == ", ":
            pointers.append(raw[current_start:pos - 2].strip())
            current_start = pos

    pointers.append(raw[current_start:].strip())
    return [p for p in pointers if p]


def resolve_pointer(pointer: str, state: dict, config_memory_headings: set,
                    plans_done_dir: Path, config_repo: Path = None) -> str:
    """Resolve a single support-set pointer.

    Returns: 'resolved', 'confirmed-absent', or 'indeterminate'.

    config_repo is optional so the unit-assert call sites, which test pointer
    forms that never touch the store, can keep passing four arguments. Omitting
    it makes every `project memory (...)` pointer indeterminate -- the behaviour
    before the store existed.
    """
    p = pointer.strip()

    # episodic_ledger #<N> — 1-based per memory-rules.md
    m = re.match(r"episodic_ledger #(\d+)", p)
    if m:
        n = int(m.group(1))
        ledger = state.get("episodic_ledger", [])
        if not isinstance(ledger, list):
            return "indeterminate"
        if 1 <= n <= len(ledger):
            return "resolved"
        return "confirmed-absent"

    # user memory § <heading>
    m = re.match(r"user memory §\s*(.+)", p)
    if m:
        heading = m.group(1).strip()
        if heading in config_memory_headings:
            return "resolved"
        return "confirmed-absent"

    # project memory (<path-key>) § <heading>, or project memory (store:<identity>) § <heading>
    m = re.match(r"project memory \(([^)]+)\)\s*§\s*(.+)", p)
    if m:
        # A project memory file lives in the store repo, so it is readable here
        # and its pointers resolve definitively.
        #
        # Everything else returns indeterminate: a project with no store this
        # machine can see may keep its memory in a store repo clone we are not
        # on, so its absence right now is not evidence of anything. Do not widen
        # this to "the path happens to exist" -- that answer flaps with what is
        # mounted, and a support-set outcome that changes between runs is worse
        # than one that is honestly unknown.
        #
        # A path key is looked up through the store resolver (the store repo by
        # STORE identity); a `store:<identity>` key names its store directly and is
        # matched by identity, never by a directory name. Never re-derive the
        # basename+hash key: the digest is encoding-sensitive (four encodings of one
        # path produced four different keys when this was measured).
        if config_repo is None:
            return "indeterminate"
        project_path_key = m.group(1).strip()
        heading = m.group(2).strip()
        if project_path_key.startswith(STORE_KEY_PREFIX):
            # An unknown identity is indeterminate, as a path key with no store is.
            repo_state, store_dir = _store_dir_for_key(project_path_key[len(STORE_KEY_PREFIX):])
            if repo_state != "ok" or store_dir is None:
                return "indeterminate"
            return _heading_verdict(store_dir, heading)
        # A store repo that exists but cannot be read may hide the project's store: a heading
        # missing then is not evidence of absence (plan 261016 Phase 5 review F1).
        art = _store_artifact(config_repo, project_path_key) if project_path_key else None
        if art is not None and art.store_repo == "unreadable":
            return "indeterminate"
        store_dir = _store_dir_of(art)    # the one lookup above: no second scan of the store repo
        if store_dir is None:
            return "indeterminate"
        return _heading_verdict(store_dir, heading)

    # session <id> — always indeterminate
    if re.match(r"session\s+[0-9a-f]+", p, re.IGNORECASE):
        return "indeterminate"

    # <plan-slug> § <section> (6-digit date prefix)
    m = re.match(r"(\d{6}[-_]\S+?)\s*§", p)
    if m:
        slug = m.group(1)
        # Check plans/done/ in config repo
        plan_file = plans_done_dir / f"{slug}.md"
        if plan_file.exists():
            return "resolved"
        # Could be in another project's plans/done/
        return "indeterminate"

    # Bare/basename project memory pointers or anything else
    return "indeterminate"


def _higher_order_entries(text: str) -> list:
    """[(heading, [Support-set values])] for every ### entry of HIGHER_ORDER.md outside ## Declined, read with
    memory-entries.py: a fenced ### is no entry, and a fenced **Support-set**: line is not one either."""
    me = _memory_entries()
    out = []
    for section, heading, body, _line in me.entries(text):
        if section.strip() == "Declined":
            continue
        values, fence = [], None
        for line in body:
            fm = me.FENCE_RE.match(line)
            if fence:
                if fm and fm.group(1) == fence:
                    fence = None
                continue
            if fm:
                fence = fm.group(1)
                continue
            if line.startswith("**Support-set**:"):
                values.append(line.split(":", 1)[1].strip())
        out.append((heading, values))
    return out


def parse_higher_order_support_sets(text: str) -> list:
    """Extract all Support-set values from HIGHER_ORDER.md (every entry, signals included)."""
    return [v for _h, values in _higher_order_entries(text) for v in values]


def parse_higher_order_nodes(text: str) -> list:
    """Extract all nodes from HIGHER_ORDER.md with per-node Support-set association.

    Returns a list of dicts: [{"heading": str, "support_set_raw": str or None}, ...], the last Support-set
    line of a node winning. Used by --per-node mode. Does NOT replace parse_higher_order_support_sets
    (store-wide). An [improvement_signal] entry is no node.
    """
    return [{"heading": h, "support_set_raw": values[-1] if values else None}
            for h, values in _higher_order_entries(text) if not h.startswith("[improvement_signal]")]


def node_label(R, CA, I):
    """Derive groundedness label from resolved/confirmed-absent/indeterminate counts."""
    if R + CA + I == 0:
        return "no-support-set"
    if R == 0 and CA == 0:
        return "unverifiable"   # only indeterminate — tool couldn't check; NEUTRAL, not weak
    if R == 0 and CA > 0 and I == 0:
        # Aligns with the sweep's ungrounded gate exactly (memory-rules.md § the
        # ungrounded trigger): >=1 pointer, ALL confirmed-absent, zero resolved
        # AND zero indeterminate. A single indeterminate blocks the gate (the
        # node is kept), so it must not be labelled "ungrounded" here either —
        # otherwise the tool the read-time advisory points at (--per-node) would
        # call a node "ungrounded" that the sweep keeps. Such nodes fall to weak.
        return "ungrounded"
    if CA > 0:
        return "weak"           # some verified-gone ground, but resolved and/or indeterminate present → gate keeps it
    return "grounded"           # R>0, CA==0: all checkable ground present


# --- Outcome resolution ---

def compute_outcome(state: dict):
    """Compute outcome resolution from outcome_tags."""
    tags = state.get("outcome_tags", [])
    # L14: Guard against non-list outcome_tags
    if not isinstance(tags, list):
        return {"graded": 0, "total": 0, "recurred": 0, "not_recurred": 0}
    total = len(tags)
    graded = [t for t in tags if isinstance(t, dict) and t.get("outcome") is not None]
    if not graded:
        return {"graded": 0, "total": total, "recurred": 0, "not_recurred": 0}
    recurred = sum(1 for t in graded if t.get("outcome") == "recurred")
    return {
        "graded": len(graded),
        "total": total,
        "recurred": recurred,
        "not_recurred": len(graded) - recurred,
    }


# --- Sweep cost (v3 cost_records) ---

COST_TREND_WINDOW = 5
VS_BASELINE_SCOPE = "not like-for-like: baseline measured to the first Phase 4b question"


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _sub(rec: dict, key: str, field: str):
    v = rec.get(key)
    return _count(v.get(field)) if isinstance(v, dict) else None


def _inconsistent(rec: dict) -> list:
    """memory-rules.md § State File Format: findings.kept and
    proposals.applied never exceed their surfaced count."""
    out = []
    for key, part, verb in (("findings", "kept", "kept"), ("proposals", "applied", "applied")):
        n, total = _sub(rec, key, part), _sub(rec, key, "surfaced")
        if n is not None and total is not None and n > total:
            out.append(f"{key} {verb} exceeds surfaced")
    # The drop stages sum to at most surfaced - kept (the gap is user Skips
    # and Defers, sweep-decide-apply.md § APP-STATE). Checked only when
    # kept <= surfaced, so one broken record gets one flag here.
    kept, total = _sub(rec, "findings", "kept"), _sub(rec, "findings", "surfaced")
    fd = rec.get("findings")
    stages = fd.get("dropped_by_stage") if isinstance(fd, dict) else None
    if kept is not None and total is not None and kept <= total and isinstance(stages, dict):
        vals = [_count(v) for v in stages.values()]
        if None not in vals and sum(vals) > total - kept:
            out.append("findings dropped_by_stage exceeds surfaced minus kept")
    return out


def _cost_summary(rec: dict) -> dict:
    agents = rec.get("agents")
    n_agents = sum(_count(v) or 0 for v in agents.values()) if isinstance(agents, dict) else None
    return {
        "date": rec.get("date") if isinstance(rec.get("date"), str) else "?",
        "tokens": _count(rec.get("tokens")),
        "agents": n_agents,
        "sessions_read": _count(rec.get("sessions_read")),
        "bytes_read": _count(rec.get("bytes_read")),
        "findings_surfaced": _sub(rec, "findings", "surfaced"),
        "findings_kept": _sub(rec, "findings", "kept"),
        "proposals_surfaced": _sub(rec, "proposals", "surfaced"),
        "proposals_applied": _sub(rec, "proposals", "applied"),
        "inconsistent": _inconsistent(rec),
    }


def _pct(new, old):
    if new is None or old is None or old == 0:
        return None
    return round(100 * (new - old) / old)


# tokens_by_role key sets (memory-rules.md § State File Format): the five
# roles, or the four legacy roles of a record written before the drafter
# role existed. Shares print in TOKEN_ROLES order, for the record's roles.
TOKEN_ROLES = ("orchestrator", "task4", "verifier", "drafter", "other")
TOKEN_ROLES_LEGACY = ("orchestrator", "task4", "verifier", "other")


def _per(tokens, n):
    return None if tokens is None or not n else round(tokens / n)


def _role_shares(rec: dict):
    """Each role's percentage of the record's tokens_by_role sum (the
    `baseline --by-role` totals, memory-rules.md § State File Format), one
    decimal, keyed by the record's own roles (five, or the four legacy
    ones). None when the field is absent, malformed (any other key set
    included) or sums to 0."""
    tr = rec.get("tokens_by_role")
    if not isinstance(tr, dict) or set(tr) not in (set(TOKEN_ROLES), set(TOKEN_ROLES_LEGACY)):
        return None
    roles = [r for r in TOKEN_ROLES if r in tr]
    vals = {r: _count(tr[r]) for r in roles}
    if any(v is None for v in vals.values()):
        return None
    total = sum(vals.values())
    if total == 0:
        return None
    return {r: round(100 * vals[r] / total, 1) for r in roles}


def _cost_ratios(rec: dict) -> dict:
    """Read-time ratios of one kind-sweep record (plan 261006 SC-11)."""
    tokens = _count(rec.get("tokens"))
    return {
        "date": rec.get("date") if isinstance(rec.get("date"), str) else "?",
        "tokens_per_surfaced_finding": _per(tokens, _sub(rec, "findings", "surfaced")),
        "tokens_per_applied_proposal": _per(tokens, _sub(rec, "proposals", "applied")),
        "role_shares": _role_shares(rec),
        "inconsistent": bool(_inconsistent(rec)),
    }


def compute_cost(state: dict):
    """Cost records of a v3 state (memory-rules.md § State File Format):
    the last baseline, the last sweep, the sweep's change against the
    baseline, and the token trend over the last sweeps. None when the state
    has no cost_records section (v1/v2), so older files render unchanged."""
    recs = state.get("cost_records")
    if not isinstance(recs, list):
        return None
    recs = [r for r in recs if isinstance(r, dict)]
    baselines = [r for r in recs if r.get("kind") == "baseline"]
    sweeps = [r for r in recs if r.get("kind") == "sweep"]
    base = _cost_summary(baselines[-1]) if baselines else None
    last = _cost_summary(sweeps[-1]) if sweeps else None
    trend_recs = [r for r in sweeps if _count(r.get("tokens")) is not None][-COST_TREND_WINDOW:]
    trend = [_count(r.get("tokens")) for r in trend_recs]
    # A sweep whose agents include a `collector` role ran the retired gather
    # path; a trend mixing it with retained-path sweeps is not like for like.
    paths = {isinstance(r.get("agents"), dict) and "collector" in r["agents"] for r in trend_recs}
    bad = [{"date": r.get("date") if isinstance(r.get("date"), str) else "?",
            "kind": r.get("kind"), "problems": _inconsistent(r)} for r in recs if _inconsistent(r)]
    return {
        "records": len(recs),
        "last_baseline": base,
        "last_sweep": last,
        "vs_baseline": {
            "tokens_pct": _pct(last and last["tokens"], base and base["tokens"]),
            "agents_pct": _pct(last and last["agents"], base and base["agents"]),
        },
        "token_trend": trend,
        "token_trend_mixed_paths": len(paths) > 1,
        "inconsistent_records": bad,
        "ratios": _cost_ratios(sweeps[-1]) if sweeps else None,
    }


def _fmt_cost_rec(label: str, s) -> str:
    if s is None:
        return f"{label}: none"

    def na(v):
        # A null count (a kind-baseline record's unmeasured field,
        # memory-rules.md § State File Format) prints n/a, never None.
        return "n/a" if v is None else v
    agents = "?" if s["agents"] is None else s["agents"]
    flag = "".join(f" (inconsistent: {m})" for m in s["inconsistent"])
    return (f"{label} {s['date']}: tokens {na(s['tokens'])}, agents {agents}, "
            f"sessions {na(s['sessions_read'])}, bytes {na(s['bytes_read'])}, "
            f"findings surfaced {na(s['findings_surfaced'])} kept {na(s['findings_kept'])}, "
            f"proposals surfaced {na(s['proposals_surfaced'])} applied {na(s['proposals_applied'])}"
            f"{flag}")


def format_cost(cost: dict) -> str:
    if cost["records"] == 0:
        return "- Cost (cost_records): N/A — 0 records"
    parts = [_fmt_cost_rec("last baseline", cost["last_baseline"]),
             _fmt_cost_rec("last sweep", cost["last_sweep"])]
    vs = cost["vs_baseline"]
    if cost["last_baseline"] and cost["last_sweep"]:
        def sign(p):
            return "n/a" if p is None else f"{p:+d}%"
        # Not like-for-like (memory-rules.md § State File Format,
        # cost_records): a kind-baseline record measures the
        # old path to the first Phase 4b question, a kind-sweep record the
        # whole sweep. The label says so wherever the percentages print.
        parts.append(f"sweep vs baseline ({VS_BASELINE_SCOPE}): tokens {sign(vs['tokens_pct'])}, "
                     f"agents {sign(vs['agents_pct'])}")
    trend = cost["token_trend"]
    if len(trend) >= 2:
        change = _pct(trend[-1], trend[0])
        tail = "" if change is None else f" ({change:+d}%)"
        scope = (" (not like for like: retired-path sweeps with a collector role mixed with "
                 "retained-path sweeps)") if cost["token_trend_mixed_paths"] else ""
        parts.append(f"token trend over {len(trend)} sweeps{scope}: "
                     + " → ".join(str(t) for t in trend) + tail)
    else:
        parts.append("token trend: n/a (fewer than 2 sweeps with tokens)")
    for b in cost["inconsistent_records"]:
        parts.append(f"inconsistent record {b['date']} {b['kind']}: " + ", ".join(b["problems"]))
    return f"- Cost (cost_records, {cost['records']} records): " + "; ".join(parts)


def format_cost_ratios(cost: dict) -> str:
    """The ratio line under the Cost line: the last kind-sweep record's
    tokens per surfaced finding and per applied proposal, and its role
    shares. n/a when tokens is null or the denominator is 0. The short
    role-share label `n/a (no tokens_by_role)` also covers a malformed
    tokens_by_role and one that sums to 0. `(inconsistent record)` closes
    the line when _inconsistent flags the record it reads."""
    r = cost.get("ratios")
    if r is None:
        return "- Cost ratios: n/a — no sweep record"

    def na(v):
        return "n/a" if v is None else v
    sh = r["role_shares"]
    shares = ("n/a (no tokens_by_role)" if sh is None
              else ", ".join(f"{k} {sh[k]:.1f}%" for k in TOKEN_ROLES if k in sh))
    return (f"- Cost ratios (last sweep {r['date']}): tokens per surfaced finding "
            f"{na(r['tokens_per_surfaced_finding'])}, tokens per applied proposal "
            f"{na(r['tokens_per_applied_proposal'])}; role shares {shares}"
            f"{' (inconsistent record)' if r['inconsistent'] else ''}")


# --- Memory footprint (the session-start memory context budget) ---

def compute_memory_tax(config_repo: Path) -> dict:
    """Word footprint of the config-repo memory files loaded at every session start.

    Prose surfaces (Report, SKILL.md) call this the "memory footprint"; the
    results key stays memory_tax. It is the only counter behind the
    session-start memory context budget (memory-rules.md § Session-start
    memory context budget): dream-manifest.py loads this function for its
    `count` line and dream-check.py for its `budget` memory row. Config-repo files only, so the number is a
    lower bound — project memory files are not counted.
    Tokens approximated as words * 4/3 (English prose averages ~0.75 words/token).
    Read-only; a missing file contributes nothing, and a file that exists but
    cannot be read (a directory, invalid UTF-8, an OSError) contributes nothing
    and is named in `unreadable`, so no report presents it as counted.
    """
    files = {}
    unreadable = []
    total_words = 0
    for name in ("MEMORY.md", "HIGHER_ORDER.md"):
        path = config_repo / "memory" / name
        if not path.exists():
            continue
        try:
            words = len(path.read_text(encoding="utf-8").split())
        except (OSError, UnicodeDecodeError):
            unreadable.append(name)
            continue
        files[name] = words
        total_words += words
    return {
        "files": files,
        "unreadable": unreadable,
        "total_words": total_words,
        "approx_tokens": round(total_words * 4 / 3),
    }


# --- Core engine ---

def find_repo_root(start: Path) -> Path:
    """Walk up from start to find .git directory."""
    current = start.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return start.resolve()


def _store_dir_of(art):
    """The store directory of a resolved artifact (a store-repo store that holds it), else None."""
    if art is not None and art.source == "store-repo" and art.store is not None:
        return Path(art.store)
    return None


def resolve_project_memory(config_repo: Path, project_path_key: str):
    """Resolve a project's memory file.

    shared/skills/qdream/memory-rules.md § Resolution contract, through the resolver: the
    nearest level's store-repo store that holds memory. When none does, the resolver's
    folder_fallback decides whether an in-workspace memory/ may be read (a no-create folder
    no store serves, with a readable store repo). -> the MEMORY.md path, or None when there is
    nothing to read.
    """
    if not (project_path_key or "").strip():
        return None
    art = _store_artifact(config_repo, project_path_key)
    if art.source == "store-repo" and art.path is not None:
        mem = Path(art.path) / "MEMORY.md"
        return mem if mem.exists() else None
    if art.source == "none":
        found = _resolver().folder_fallback(project_path_key, "memory")
        if found is not None:
            return Path(found) / "MEMORY.md"
    return None


def compute_provenance_scope(entries: list) -> dict:
    """Compute anchor completeness (re-openable Source) for a list of entries."""
    anchored = 0
    free_text = 0
    for e in entries:
        field = e.get("source")
        if is_anchor(field):
            anchored += 1
        else:
            free_text += 1
    return {"anchored": anchored, "total": anchored + free_text, "free_text": free_text}


# --- Topic memory (the on-demand half of user memory) ---

def load_config_topic_entries(config_repo: Path) -> list:
    """Parse every memory/topics/*.md file under the config repo.

    Topic files are the on-demand half of user memory (shared/AGENTS.md
    § Memory locations, "Topic memory"): same tier, same entry format, same
    write-time gates and /qdream processing as memory/MEMORY.md -- only the
    load timing differs (memory-rules.md § Memory File Format, "Route to a
    topic file before writing"). So a `user memory § <heading>` Support-set
    pointer must resolve against a topic-file heading exactly as it resolves
    against memory/MEMORY.md (memory-rules.md § Support-set referential
    integrity), and a topic entry's provenance is worth tracking too --
    just reported separately from the config-repo bucket, which feeds the
    session-start memory context budget (memory-rules.md § Session-start
    memory context budget), scoped to ALWAYS-LOADED user memory only.

    Returns a flat list of entries in parse_memory_entries() shape, in
    sorted filename order for determinism. Read-only; a missing topics/
    directory or an unreadable file degrades to fewer entries, never a
    crash -- consistent with every other memory-file read in this script.
    """
    topics_dir = config_repo / "memory" / "topics"
    entries = []
    if not topics_dir.is_dir():
        return entries
    try:
        topic_files = sorted(topics_dir.glob("*.md"))
    except OSError:
        return entries
    for path in topic_files:
        try:
            entries.extend(parse_memory_entries(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return entries


def config_user_memory_headings(config_repo: Path) -> set:
    """Every entry heading a `user memory § <heading>` pointer may name:
    memory/MEMORY.md plus memory/topics/*.md, [improvement_signal] entries
    included (memory-rules.md § Support-set referential integrity; signals
    live in memory/topics/improvement-signals.md). Read-only; an unreadable
    file contributes nothing."""
    headings = set()
    files = [config_repo / "memory" / "MEMORY.md"]
    topics_dir = config_repo / "memory" / "topics"
    if topics_dir.is_dir():
        try:
            files += sorted(topics_dir.glob("*.md"))
        except OSError:
            pass
    for path in files:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for e in parse_memory_entries(text, include_signals=True):
            headings.add(e["heading"])
    return headings


def run_metrics(repo_root: Path, state_file: Path, omit_support_set: bool = False,
                per_node: bool = False, _state_override: dict = None):
    """Compute all metrics and return structured results.

    Args:
        _state_override: If provided, use this dict instead of loading state_file.
                         Used internally by fixture tests to inject modified state.
        per_node: If True, include per-node groundedness breakdown in results.
    """
    # Load state file
    if _state_override is not None:
        state = _state_override
    else:
        if not state_file.exists():
            return {"skip": True, "reason": "state file not found"}

        try:
            # utf-8-sig: tolerate a leading BOM, consistent with the dream
            # validators (a BOM'd-but-valid state should read, not skip).
            with open(state_file, "r", encoding="utf-8-sig") as f:
                state = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            return {"skip": True, "reason": f"state file corrupt: {e}"}
        except OSError as e:
            # exists() passed but the file is unreadable (lock / permission /
            # OneDrive-sync contention). Degrade to SKIP rather than crashing
            # with a traceback — mirrors the per-project read's OSError catch.
            return {"skip": True, "reason": f"state file unreadable: {e}"}

        # H13: JSON non-dict → AttributeError on state.get()
        if not isinstance(state, dict):
            return {"skip": True, "reason": "state file has unexpected structure"}

    config_repo = repo_root.resolve()

    # --- Anchor completeness ---
    provenance_results = {}

    # Config-repo scope: user memory + HIGHER_ORDER
    config_memory_path = config_repo / "memory" / "MEMORY.md"
    config_ho_path = config_repo / "memory" / "HIGHER_ORDER.md"

    config_entries = []
    if config_memory_path.exists():
        try:
            config_entries.extend(parse_memory_entries(config_memory_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            pass  # Degrade to empty entries rather than crash
    if config_ho_path.exists():
        try:
            config_entries.extend(parse_memory_entries(config_ho_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            pass  # Degrade to empty entries rather than crash

    provenance_results["config-repo"] = compute_provenance_scope(config_entries)

    # Topic scope (the on-demand tier, memory/topics/*.md): reported
    # SEPARATELY from config-repo, never merged into it -- config-repo is
    # what the session-start memory context budget counts (always-loaded
    # user memory only), and
    # folding topic entries in would distort that budget the moment an
    # entry is routed out of memory/MEMORY.md and into a topic file.
    topic_entries = load_config_topic_entries(config_repo)
    topics_results = None
    if topic_entries:
        topics_results = {"provenance": compute_provenance_scope(topic_entries)}

    # Per-project scope (deduped against config-repo)
    projects = state.get("projects", {})
    if not isinstance(projects, dict):
        projects = {}
    counted_files = set()
    for path_key in sorted(projects.keys()):
        # L12: Skip empty-string keys that would resolve to CWD
        if not path_key:
            continue
        if path_key.startswith(STORE_KEY_PREFIX):
            # A store-only project: its key names the store by identity, never a path.
            _repo_state, store_dir = _store_dir_for_key(path_key[len(STORE_KEY_PREFIX):])
            if store_dir is None:
                continue
            project_mem = store_dir / "memory" / "MEMORY.md"
        else:
            project_path = Path(path_key)
            try:
                project_path.resolve()  # validity probe only: skip malformed keys
            except (OSError, ValueError):
                continue
            # Store-aware: the memory file is wherever the resolution contract
            # points (None: nothing may be read for this key).
            project_mem = resolve_project_memory(config_repo, path_key)
            if project_mem is None:
                continue
        # Dedup by RESOLVED-FILE IDENTITY, not repo equality. The equality test
        # this replaces served two purposes -- a config-repo guard AND the
        # dedup this comment's header names -- and narrowing it to the guard
        # alone would double-count a file two keys reach. Identity catches a
        # store-backed alias of a file counted under another key, which repo
        # equality never could. The config repo's own memory/ is the user tier
        # (step 0 of the resolution contract): neither the resolver nor
        # folder_fallback names it as project memory, and this test is the
        # backstop that skips the user memory file already counted above.
        try:
            if project_mem.resolve() == config_memory_path.resolve():
                continue
        except (OSError, ValueError):
            pass
        if not project_mem.exists():
            continue
        # plan 261016 Phase 5: two state keys that resolve to one memory file (checkouts of
        # one remote, a folder under its repo's store) are one store unit: count the file once.
        try:
            file_id = os.path.normcase(str(project_mem.resolve()))
        except (OSError, ValueError):
            file_id = os.path.normcase(str(project_mem))
        if file_id in counted_files:
            continue
        counted_files.add(file_id)
        try:
            text = project_mem.read_text(encoding="utf-8")
            entries = parse_memory_entries(text)
            if entries:
                provenance_results[path_key] = compute_provenance_scope(entries)
        except (OSError, PermissionError, UnicodeDecodeError):
            continue

    # --- Support-set resolution ---
    support_set_results = None
    if not omit_support_set:
        # Topic entries are user memory too (memory-rules.md § Support-set
        # referential integrity) -- a `user memory § <heading>` pointer must
        # resolve here exactly as it would against memory/MEMORY.md, not go
        # confirmed-absent just because the entry was routed to the
        # on-demand tier. Signals are included for the same reason.
        config_memory_headings = config_user_memory_headings(config_repo)

        plans_done_dir = _config_plans_done(config_repo)

        ho_text = ""
        if config_ho_path.exists():
            try:
                ho_text = config_ho_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass  # Degrade to empty higher-order text

        raw_sets = parse_higher_order_support_sets(ho_text)
        all_pointers = []
        for raw in raw_sets:
            all_pointers.extend(split_support_set(raw))

        resolved_count = 0
        absent_count = 0
        indeterminate_count = 0

        for ptr in all_pointers:
            result = resolve_pointer(ptr, state, config_memory_headings, plans_done_dir, config_repo)
            if result == "resolved":
                resolved_count += 1
            elif result == "confirmed-absent":
                absent_count += 1
            else:
                indeterminate_count += 1

        support_set_results = {
            "resolved": resolved_count,
            "confirmed_absent": absent_count,
            "indeterminate": indeterminate_count,
            "total_pointers": len(all_pointers),
            "total_nodes": len(raw_sets),
        }

    # --- Outcome resolution ---
    outcome = compute_outcome(state)

    results = {
        "skip": False,
        "provenance": provenance_results,
        "support_set": support_set_results,
        "outcome": outcome,
        "memory_tax": compute_memory_tax(config_repo),
    }
    # Emitted only for a state carrying cost_records (v3), so v1/v2 files
    # render and serialise exactly as before.
    cost = compute_cost(state)
    if cost is not None:
        results["cost"] = cost
    # Emitted only when at least one topic entry exists, so a repo with no
    # memory/topics/ renders and serialises exactly as it did before topic
    # awareness.
    if topics_results is not None:
        results["topics"] = topics_results

    # --- Per-node groundedness (only when --per-node is passed) ---
    if per_node:
        ho_text_for_nodes = ""
        if config_ho_path.exists():
            try:
                ho_text_for_nodes = config_ho_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

        # Build config_memory_headings if not already done (when omit_support_set was True)
        if omit_support_set:
            config_memory_headings = config_user_memory_headings(config_repo)
            plans_done_dir = _config_plans_done(config_repo)

        nodes = parse_higher_order_nodes(ho_text_for_nodes)
        per_node_results = []
        for nd in nodes:
            raw_ss = nd["support_set_raw"]
            if raw_ss is None:
                per_node_results.append({
                    "heading": nd["heading"],
                    "resolved": 0,
                    "confirmed_absent": 0,
                    "indeterminate": 0,
                    "total": 0,
                    "label": "no-support-set",
                })
                continue
            pointers = split_support_set(raw_ss)
            r_count = 0
            ca_count = 0
            i_count = 0
            for ptr in pointers:
                result = resolve_pointer(ptr, state, config_memory_headings, plans_done_dir, config_repo)
                if result == "resolved":
                    r_count += 1
                elif result == "confirmed-absent":
                    ca_count += 1
                else:
                    i_count += 1
            label = node_label(r_count, ca_count, i_count)
            per_node_results.append({
                "heading": nd["heading"],
                "resolved": r_count,
                "confirmed_absent": ca_count,
                "indeterminate": i_count,
                "total": r_count + ca_count + i_count,
                "label": label,
            })
        results["per_node"] = per_node_results

    return results


# --- Output formatting ---

def _disambiguate_project_key(scope_key: str, prov: dict) -> str:
    """Return a short display name for a project key, using parent/leaf if basename is ambiguous."""
    leaf = Path(scope_key).name
    # Check if any other key shares the same basename
    same_basename = [
        k for k in prov
        if k != "config-repo" and k != scope_key and Path(k).name == leaf
    ]
    if same_basename:
        parent = Path(scope_key).parent.name
        return f"{parent}/{leaf}"
    return leaf


def format_text(results: dict) -> str:
    """Format results as labeled-quantity text."""
    if results.get("skip"):
        return f"SKIP — {results['reason']}"

    lines = ["Memory-health metrics (qmemory-eval — read-only snapshot):"]

    # Anchor completeness
    prov = results["provenance"]
    config = prov.get("config-repo", {"anchored": 0, "total": 0, "free_text": 0})
    if config["total"] > 0:
        pct = round(100 * config["anchored"] / config["total"])
        lines.append(
            f"- Anchor completeness (config-repo): "
            f"{config['anchored']}/{config['total']} anchored ({pct}%); "
            f"{config['free_text']} free-text"
        )
    else:
        lines.append("- Anchor completeness (config-repo): 0/0 anchored; no entries")

    topics = results.get("topics")
    if topics is not None:
        tprov = topics["provenance"]
        pct = round(100 * tprov["anchored"] / tprov["total"]) if tprov["total"] else 0
        lines.append(
            f"- Anchor completeness (topic memory, on-demand tier — "
            f"{tprov['total']} entries, not counted toward the config-repo "
            f"session-start memory context budget): {tprov['anchored']}/{tprov['total']} anchored "
            f"({pct}%); {tprov['free_text']} free-text"
        )

    for scope_key, scope_data in sorted(prov.items()):
        if scope_key == "config-repo":
            continue
        if scope_data["total"] > 0:
            pct = round(100 * scope_data["anchored"] / scope_data["total"])
            short_key = _disambiguate_project_key(scope_key, prov)
            lines.append(
                f"  - {short_key}: "
                f"{scope_data['anchored']}/{scope_data['total']} anchored ({pct}%); "
                f"{scope_data['free_text']} free-text"
            )

    # Support-set
    ss = results.get("support_set")
    if ss is not None:
        lines.append(
            f"- Support-set resolution (reachable-now): "
            f"{ss['resolved']} resolved, {ss['confirmed_absent']} confirmed-absent, "
            f"{ss['indeterminate']} indeterminate "
            f"({ss['total_pointers']} node pointers / {ss['total_nodes']} nodes)"
        )

    # Outcome
    outcome = results["outcome"]
    if outcome["graded"] == 0:
        lines.append(
            f"- Outcome resolution: N/A — 0/{outcome['total']} graded"
        )
    else:
        lines.append(
            f"- Outcome resolution: {outcome['graded']}/{outcome['total']} graded "
            f"({outcome['recurred']} recurred, {outcome['not_recurred']} not-recurred)"
        )

    cost = results.get("cost")
    if cost is not None:
        lines.append(format_cost(cost))
        if cost["records"]:
            lines.append(format_cost_ratios(cost))

    # Memory footprint (the session-start memory context budget's word count)
    tax = results.get("memory_tax")
    if tax is not None:
        lines.append(format_footprint(tax))

    return "\n".join(lines)


def unreadable_note(tax: dict) -> str:
    """' (MEMORY.md unreadable)' for each memory file that exists but could
    not be read, else ''. Shared with dream-manifest.py's budget line."""
    names = tax.get("unreadable") or []
    return "".join(f" ({name} unreadable)" for name in names)


def format_footprint(tax: dict) -> str:
    """The Memory footprint line."""
    head = "- Memory footprint (config-repo files, session-start load): "
    if tax["total_words"] > 0:
        parts = ", ".join(f"{name} {w}" for name, w in sorted(tax["files"].items()))
        return (f"{head}{tax['total_words']} words (~{tax['approx_tokens']} tokens) — "
                f"{parts}{unreadable_note(tax)}")
    if tax.get("unreadable"):
        return f"{head}0 words — no readable memory files{unreadable_note(tax)}"
    return f"{head}0 words — no memory files"


def format_json(results: dict) -> str:
    """Format results as JSON."""
    return json.dumps(results, indent=2)


def format_per_node_text(results: dict) -> str:
    """Format per-node groundedness breakdown as text."""
    if results.get("skip"):
        return f"SKIP — {results['reason']}"

    per_node_data = results.get("per_node", [])
    lines = [
        "Per-node groundedness (qmemory-eval --per-node "
        "\u2014 read-only, reachable-now snapshot; not the sweep\u2019s reconciliation):"
    ]
    for nd in per_node_data:
        lines.append(
            f"- \"{nd['heading']}\": "
            f"{nd['resolved']}R/{nd['confirmed_absent']}CA/{nd['indeterminate']}I "
            f"({nd['total']} ptrs) -> {nd['label']}"
        )
    return "\n".join(lines)


# --- Selftest ---

def run_higher_order_parser_units():
    """plan 261016 Step 9: the HIGHER_ORDER walkers read through memory-entries.py, fence-aware."""
    text = ("# Higher-Order\n\n## Pattern\n\n### Node one\n\n**Support-set**: a.md\n\n"
            "```\n### Fenced heading\n**Support-set**: fenced.md\n```\n\n"
            "### [improvement_signal] Signal\n\n**Support-set**: sig.md\n\n"
            "### Node two\n\n**Support-set**: b.md\n**Support-set**: c.md\n\n## Declined\n\n- x\n\n"
            "### Declined node\n\n**Support-set**: declined.md\n")
    fails = []
    nodes = parse_higher_order_nodes(text)
    want = [{"heading": "Node one", "support_set_raw": "a.md"}, {"heading": "Node two", "support_set_raw": "c.md"}]
    if nodes != want:
        fails.append("higher-order nodes: got %r, want %r" % (nodes, want))
    sets = parse_higher_order_support_sets(text)
    if sets != ["a.md", "sig.md", "b.md", "c.md"]:
        fails.append("higher-order support sets: got %r" % (sets,))
    return fails


def run_selftest(script_path: Path):
    """Run fixture tests and no-writes source-grep assertion."""
    failures = []
    failures.extend(run_higher_order_parser_units())

    # No-writes source-grep — only check lines OUTSIDE run_selftest
    source = script_path.read_text(encoding="utf-8")
    write_patterns = [
        re.compile(r"""open\([^)]*,\s*['"][wa]['"]"""),
        re.compile(r"\.write_text\("),
        re.compile(r"\bos\.remove\("),
        re.compile(r"\bshutil\.rmtree\("),
        re.compile(r"\bshutil\.move\("),
        re.compile(r"\bshutil\.copy\("),
        re.compile(r"\bsubprocess\.(run|call|Popen|check_call|check_output)\("),
    ]

    # Find the line range of run_selftest to exclude it from the check
    source_lines = source.splitlines()
    in_selftest = False
    selftest_lines = set()
    for i, line in enumerate(source_lines, 1):
        if re.match(r"^def run_selftest\(", line):
            in_selftest = True
        elif in_selftest and re.match(r"^def \w+\(", line):
            in_selftest = False
        if in_selftest:
            selftest_lines.add(i)

    for i, line in enumerate(source_lines, 1):
        if i in selftest_lines:
            continue
        for pat in write_patterns:
            if pat.search(line):
                failures.append(f"NO-WRITES VIOLATION line {i}: {line.strip()}")

    # Run fixture tests
    fixture_dir = script_path.parent / "fixtures" / "qmemory-eval"
    if not fixture_dir.exists():
        failures.append(f"Fixture directory not found: {fixture_dir}")
        return failures

    # plan 261016 Phase 5: the fixtures must never see the live store repo. An env root that does not
    # exist makes the resolver skip that source (a reader fails open), so only the fixture's own stores count.
    import tempfile
    iso = tempfile.TemporaryDirectory(prefix="qme-iso-")
    saved_env = os.environ.get("AGENT_PLAYBOOK_STORES")
    os.environ["AGENT_PLAYBOOK_STORES"] = os.path.join(iso.name, "no-store-repo")
    try:
        fixture_failures = run_fixture_tests(fixture_dir)
    finally:
        if saved_env is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved_env
        iso.cleanup()
    failures.extend(fixture_failures)

    # An existing but unreadable memory file is named, never counted silently
    # as 0. Built in a temporary directory (invalid UTF-8 is not committed):
    # MEMORY.md is invalid UTF-8, HIGHER_ORDER.md holds 3 words.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qme-") as tmp:
        mem = Path(tmp) / "memory"
        mem.mkdir()
        (mem / "MEMORY.md").write_bytes(b"# Memory\n\xff\xfe broken\n")
        (mem / "HIGHER_ORDER.md").write_bytes(b"one two three\n")
        tax = compute_memory_tax(Path(tmp))
    if tax["unreadable"] != ["MEMORY.md"] or tax["total_words"] != 3:
        failures.append(f"UNREADABLE footprint: got {tax}")
    want = ("- Memory footprint (config-repo files, session-start load): 3 words "
            "(~4 tokens) — HIGHER_ORDER.md 3 (MEMORY.md unreadable)")
    if format_footprint(tax) != want:
        failures.append(f"UNREADABLE footprint: line {format_footprint(tax)!r}, expected {want!r}")

    return failures


class _StoresEnv:
    """AGENT_PLAYBOOK_STORES set to `path` for the block, then restored."""

    def __init__(self, path):
        self.path = str(path)

    def __enter__(self):
        self.saved = os.environ.get("AGENT_PLAYBOOK_STORES")
        os.environ["AGENT_PLAYBOOK_STORES"] = self.path
        return self

    def __exit__(self, *_exc):
        if self.saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = self.saved
        return False


def _materialize_store_scope(fixture_path: Path, tmp: str):
    """A copy of the store_scope fixture under `tmp`, its `stores/` made a store repo. A checked-in
    `stores/<dir>/STORE` reads `local {{ROOT}}/<folder>` (a checked-in file cannot know the clone's
    path); here it is rewritten to that folder's identity as the resolver computes it, and the state
    keys to absolute paths. -> (root, state file, store repo root)."""
    import shutil
    r = _resolver()
    root = Path(tmp) / "fx"
    shutil.copytree(str(fixture_path), str(root))
    stores = root / "stores"
    for sf in sorted(stores.glob("*/STORE")):
        rel = sf.read_bytes().decode("utf-8-sig").strip()[len("local {{ROOT}}/"):]
        ident = r.identity(str(root / rel)).path
        r.fixture_store(stores, sf.parent.name, r.id_line(ident) + "\n")
    state_file = root / ".dream-state.json"
    state = json.loads(state_file.read_bytes().decode("utf-8-sig"))
    state["projects"] = {str(root if k == "." else root / k): v for k, v in state["projects"].items()}
    state_file.write_bytes(json.dumps(state).encode("utf-8"))
    return root, state_file, stores


def run_project_pointer_units(fixture_dir: Path) -> list:
    """Unit-assert resolve_pointer on `project memory (...)` pointers.

    Before the workspace store existed these were indeterminate unconditionally,
    on the grounds that a remote project may be offline or unmounted. A file in
    a store this machine's store repo holds is readable here, so that reason does
    not hold for it and the pointer resolves definitively.

    The cases below pin both halves: the store-backed pair must give a real
    verdict, and the no-store case must still refuse to guess. Assert them
    together -- a fix that resolved everything would pass the first two alone.
    """
    failures = []
    src = fixture_dir / "store_scope"
    if not src.is_dir():
        return ["run_project_pointer_units: fixture missing: %s" % src]
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qme-ptr-") as tmp:
        root, _state, stores = _materialize_store_scope(src, tmp)
        so = str(root / "store_only_project")
        with _StoresEnv(stores):
            cases = [
                # (pointer, expected, why)
                ("project memory (%s) § Store-backed entry with plans/done anchor" % so,
                 "resolved",
                 "heading is present in the store-backed file"),
                ("project memory (%s) § No such heading anywhere" % so,
                 "confirmed-absent",
                 "store file is readable and the heading is genuinely not in it"),
                ("project memory (%s) § Anything" % (root / "no_such_project"),
                 "indeterminate",
                 "no store matches, so the file was never reachable to look in"),
            ]
            for pointer, expected, why in cases:
                got = resolve_pointer(pointer, {}, set(), root / "plans" / "done", root)
                if got != expected:
                    failures.append(
                        "PROJECT-POINTER UNIT: %r -> %s, expected %s (%s)"
                        % (pointer, got, expected, why))

            # Omitting config_repo must reproduce the pre-store behaviour exactly.
            got = resolve_pointer(
                "project memory (%s) § Store-backed entry with plans/done anchor" % so,
                {}, set(), root / "plans" / "done")
            if got != "indeterminate":
                failures.append(
                    "PROJECT-POINTER UNIT: with no config_repo -> %s, expected indeterminate "
                    "(the four-argument call sites must keep their old behaviour)" % got)

        # plan 261016 Phase 10: a `store:<identity>` key (a store-only project, dream-manifest.py)
        # names its store by STORE identity, matched through scan_stores and id_key, then the same
        # present/absent test as a path key. An identity no store has is indeterminate, as a path
        # key with no store is; a missing or unreadable store repo is indeterminate.
        r = _resolver()
        sr = Path(tmp) / "store-key-repo"
        sd = r.fixture_store(sr, "proj-abcdef", "remote example.com/org/proj\n")
        (sd / "memory").mkdir()
        (sd / "memory" / "MEMORY.md").write_bytes(
            b"# Memory\n\n## Feedback\n\n### Store-key entry\n\n**Why**: Test.\n")
        # A monorepo store: its key carries ` path <subpath>`, so a parse that drops it matches nothing.
        md_mono = r.fixture_store(sr, "mono-123456", "remote example.com/org/mono\npath svc/api\n")
        (md_mono / "memory").mkdir()
        (md_mono / "memory" / "MEMORY.md").write_bytes(
            b"# Memory\n\n## Feedback\n\n### Mono entry\n\n**Why**: Test.\n")
        r.fixture_store(sr, "bare-654321", "remote example.com/org/bare\n")
        key = "store:remote example.com/org/proj"
        for label, stores_root, build, pointer_key, heading, want in (
                ("present", sr, None, key, "Store-key entry", "resolved"),
                ("present, case differs", sr, None, "store:remote Example.com/Org/Proj",
                 "Store-key entry", "resolved"),
                ("absent: store exists, entry gone", sr, None, key, "Gone entry", "confirmed-absent"),
                ("monorepo store key, present", sr, None,
                 "store:remote example.com/org/mono path svc/api", "Mono entry", "resolved"),
                ("store without a memory file", sr, None,
                 "store:remote example.com/org/bare", "Store-key entry", "indeterminate"),
                ("unknown identity", sr, None, "store:remote example.com/org/ghost",
                 "Store-key entry", "indeterminate"),
                ("missing store repo", Path(tmp) / "no-such-store-repo", None, key,
                 "Store-key entry", "indeterminate"),
                ("unreadable store repo", sr, lambda: os.makedirs(str(sr / "zzz-bad-000000" / "STORE")),
                 key, "Store-key entry", "indeterminate")):
            if build is not None:
                build()
            with _StoresEnv(stores_root):
                pointer = "project memory (%s) § %s" % (pointer_key, heading)
                got = resolve_pointer(pointer, {}, set(), root / "plans" / "done", root)
            if got != want:
                failures.append("PROJECT-POINTER UNIT (store key, %s): %r -> %s, expected %s"
                                % (label, pointer, got, want))

        # plan 261016 Phase 5 review F1: a store repo that exists but cannot be read (one STORE among
        # several is a directory) may hide the project's store. Neither a missing heading nor a present
        # one is a verdict then. The same pointers on the readable store repo keep their verdicts, so
        # the unreadable state is what changes them.
        for label, build, want_absent, want_present in (
                ("readable store repo", lambda: None, "confirmed-absent", "resolved"),
                ("unreadable store repo", lambda: os.makedirs(str(stores / "zzz-bad-000000" / "STORE")),
                 "indeterminate", "indeterminate")):
            build()
            with _StoresEnv(stores):
                for heading, want in (("No such heading anywhere", want_absent),
                                      ("Store-backed entry with plans/done anchor", want_present)):
                    pointer = "project memory (%s) § %s" % (so, heading)
                    got = resolve_pointer(pointer, {}, set(), root / "plans" / "done", root)
                    if got != want:
                        failures.append("PROJECT-POINTER UNIT (%s): %r -> %s, expected %s"
                                        % (label, heading, got, want))

    return failures


def run_store_scope_dedupe_unit(fixture_dir: Path) -> list:
    """Two state keys that reach one memory file (a path and the same path with a trailing separator,
    plan 261016 Phase 5) are one store unit: the file is counted once. The precondition (both keys
    resolve to the same file) is asserted, so the count cannot pass by the keys resolving apart."""
    failures = []
    src = fixture_dir / "store_scope"
    if not src.is_dir():
        return ["run_store_scope_dedupe_unit: fixture missing: %s" % src]
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qme-dedupe-") as tmp:
        root, state_file, stores = _materialize_store_scope(src, tmp)
        key = str(root / "store_only_project")
        twin = key + os.sep
        with _StoresEnv(stores):
            a = resolve_project_memory(root, key)
            b = resolve_project_memory(root, twin)
            if a is None or b is None or not a.exists() or os.path.normcase(str(a.resolve())) != os.path.normcase(str(b.resolve())):
                failures.append("STORE-UNIT DEDUPE: precondition: %s and %s do not resolve to one existing file (%s, %s)"
                                % (key, twin, a, b))
                return failures
            state = json.loads(state_file.read_bytes().decode("utf-8-sig"))
            state["projects"][twin] = {"last_session": "2026-08-14"}
            state_file.write_bytes(json.dumps(state).encode("utf-8"))
            results = run_metrics(root, state_file, omit_support_set=True)
        counted = [k for k in results["provenance"] if "store_only_project" in k.replace("\\", "/")]
        if len(counted) != 1:
            failures.append("STORE-UNIT DEDUPE: the one memory file of two state keys was counted %d times: %s"
                            % (len(counted), counted))
    return failures


def run_store_key_provenance_unit(fixture_dir: Path) -> list:
    """A `store:<identity>` state key (a store-only project) is counted from its store's memory file,
    found by STORE identity; an identity no store has is skipped; a path key reaching the same file
    leaves it counted once."""
    failures = []
    src = fixture_dir / "store_scope"
    if not src.is_dir():
        return ["run_store_key_provenance_unit: fixture missing: %s" % src]
    import tempfile
    r = _resolver()
    with tempfile.TemporaryDirectory(prefix="qme-skey-") as tmp:
        root, state_file, stores = _materialize_store_scope(src, tmp)
        path_key = str(root / "store_only_project")
        skey = STORE_KEY_PREFIX + r.id_line(r.identity(path_key).path)
        ghost = STORE_KEY_PREFIX + "remote example.com/org/ghost"
        for label, keys, want in (("store key alone", [skey, ghost], [skey]),
                                  ("store key and its path key", [skey, path_key], [path_key, skey])):
            state = json.loads(state_file.read_bytes().decode("utf-8-sig"))
            state["projects"] = {k: {"last_session": "2026-08-14"} for k in keys}
            state_file.write_bytes(json.dumps(state).encode("utf-8"))
            with _StoresEnv(stores):
                prov = run_metrics(root, state_file, omit_support_set=True)["provenance"]
            got = [k for k in prov if k != "config-repo"]
            if label == "store key alone":
                scope = prov.get(skey, {})
                if got != want or scope.get("anchored") != 1 or scope.get("free_text") != 1:
                    failures.append("STORE-KEY PROVENANCE (%s): got %s, expected only %s with 1 anchored "
                                    "and 1 free-text" % (label, {k: prov[k] for k in got}, skey))
            elif len(got) != 1 or got[0] not in want:
                failures.append("STORE-KEY PROVENANCE (%s): the one memory file was counted as %s"
                                % (label, got))
    return failures


def run_node_label_units() -> list:
    """Unit-assert node_label boundary cases — especially that a single
    indeterminate pointer blocks the 'ungrounded' label, keeping the tool's
    label aligned with the sweep's ungrounded gate (memory-rules.md § the
    ungrounded trigger). Pins the fix for the tool-vs-gate 'ungrounded' drift."""
    failures = []
    cases = [
        # (R, CA, I, expected_label)
        (0, 2, 0, "ungrounded"),    # all confirmed-absent, zero indeterminate → gate-ungrounded
        (0, 1, 1, "weak"),          # one indeterminate blocks the gate → NOT ungrounded
        (0, 0, 3, "unverifiable"),  # only indeterminate → neutral
        (2, 1, 0, "weak"),
        (3, 0, 0, "grounded"),
        (0, 0, 0, "no-support-set"),
    ]
    for R, CA, I, expected in cases:
        got = node_label(R, CA, I)
        if got != expected:
            failures.append(
                f"NODE-LABEL node_label({R},{CA},{I}) → '{got}', expected '{expected}'"
            )
    return failures


def run_fixture_store_scope(fixture_path: Path) -> list:
    """Store-layout scenarios (memory-rules.md § Workspace Store).

    Three cases in one tree:
      - `store_only_project` has no in-workspace memory, so resolution returns
        the store-backed file and that scope is counted from it.
      - `both_project` has a store-repo store AND an in-workspace memory/: only
        the store's file is counted (the in-workspace copy is never read once a
        store holds memory) and no ambiguity is reported.
      - the `.` key is the config repo itself. It must dedup away by RESOLVED
        FILE IDENTITY -- the check that replaced the old repo-equality
        short-circuit -- because it resolves to the same file the config-repo
        scope already counted.

    The checked-in keys and STORE files are relative; _materialize_store_scope
    copies the tree to a temporary directory and makes them absolute there, so
    nothing is written inside the repo.
    """
    failures = []
    if not (fixture_path / ".dream-state.json").exists():
        failures.append("FIXTURE store_scope: .dream-state.json not found")
        return failures

    import tempfile
    with tempfile.TemporaryDirectory(prefix="qme-scope-") as tmp:
        root, state_file, stores = _materialize_store_scope(fixture_path.resolve(), tmp)
        with _StoresEnv(stores):
            results = run_metrics(root, state_file, omit_support_set=True)
        results["provenance"] = {(Path(k).name if os.path.isabs(k) else k): v
                                 for k, v in results["provenance"].items()}
        text_out = format_text(results)

    if results.get("skip"):
        failures.append(f"FIXTURE store_scope: unexpected skip — {results.get('reason')}")
        return failures

    prov = results["provenance"]

    # The config repo's own "." key deduped away: exactly one config-repo scope.
    config_prov = prov.get("config-repo", {})
    if config_prov.get("anchored") != 1 or config_prov.get("total") != 1:
        failures.append(
            f"FIXTURE store_scope: config-repo provenance mismatch — "
            f"got anchored={config_prov.get('anchored')} total={config_prov.get('total')}, "
            f"expected anchored=1 total=1"
        )
    if "fx" in prov:
        failures.append(
            "FIXTURE store_scope: the config repo's own project key was counted "
            "again — the resolved-file-identity dedup did not fire"
        )

    # Store-only project: counted from the store-backed file.
    store_prov = prov.get("store_only_project", {})
    if store_prov.get("anchored") != 1 or store_prov.get("free_text") != 1:
        failures.append(
            f"FIXTURE store_scope: store_only_project provenance mismatch — "
            f"got anchored={store_prov.get('anchored')} "
            f"free_text={store_prov.get('free_text')}, expected anchored=1 free_text=1"
        )

    # Both-locations project: the store's file counts (its 2 entries, both with a plans/done anchor),
    # never the in-workspace file (1 free-text entry), and nothing is reported ambiguous.
    both_prov = prov.get("both_project", {})
    if both_prov.get("total") != 2 or both_prov.get("anchored") != 2 or both_prov.get("free_text") != 0:
        failures.append(
            f"FIXTURE store_scope: both_project should be counted from the store "
            f"file only — got total={both_prov.get('total')} "
            f"anchored={both_prov.get('anchored')} free_text={both_prov.get('free_text')}, "
            f"expected total=2 anchored=2 free_text=0"
        )
    if "store_ambiguous" in results or "AMBIGUOUS" in text_out:
        failures.append(
            "FIXTURE store_scope: an ambiguity is reported, but only the store repo is read"
        )

    return failures


def run_fixture_topics(fixture_path: Path) -> list:
    """Topic-memory fixture (memory/topics/*.md as an additional user-memory
    source, shared/AGENTS.md § Memory locations "Topic memory").

    memory/MEMORY.md carries a `## Topics` index row and one always-loaded
    entry; memory/topics/testing.md carries one on-demand entry;
    memory/HIGHER_ORDER.md has a node whose Support-set names BOTH headings
    via the identical `user memory § <heading>` pointer form. Asserts:
      - the topic entry's provenance is reported on its OWN line, separate
        from the config-repo (always-loaded) line — the config-repo total
        must stay exactly what it would be without memory/topics/ at all
        (2, from MEMORY.md + HIGHER_ORDER.md), so the session-start memory
        context budget is not distorted;
      - the pointer naming the topic-file heading resolves (2 resolved, not
        1 resolved + 1 confirmed-absent) — the regression this fixture pins.
    """
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    results = run_metrics(repo_root, state_file, omit_support_set=False)
    output = format_text(results)

    expected = (
        "Memory-health metrics (qmemory-eval — read-only snapshot):\n"
        "- Anchor completeness (config-repo): 2/2 anchored (100%); 0 free-text\n"
        "- Anchor completeness (topic memory, on-demand tier — 1 entries, "
        "not counted toward the config-repo session-start memory context budget): 1/1 anchored (100%); "
        "0 free-text\n"
        "- Support-set resolution (reachable-now): 2 resolved, 0 confirmed-absent, "
        "0 indeterminate (2 node pointers / 1 nodes)\n"
        "- Outcome resolution: N/A — 0/0 graded\n"
        "- Memory footprint (config-repo files, session-start load): 114 words (~152 tokens) — "
        "HIGHER_ORDER.md 59, MEMORY.md 55"
    )

    if output != expected:
        failures.append(f"FIXTURE topics: output mismatch\nGOT:\n{output}\nEXPECTED:\n{expected}")

    # The topics bucket must never leak into the generic per-project scope
    # loop (it is not a project) and the config-repo bucket must be
    # unaffected by whether memory/topics/ exists at all.
    if "topics" in results["provenance"]:
        failures.append(
            "FIXTURE topics: 'topics' key leaked into results['provenance'] "
            "(must be a separate top-level results['topics'] key, not a "
            "provenance scope — it would otherwise print as a fake project "
            "in the per-project loop)"
        )
    config_prov = results["provenance"].get("config-repo", {})
    if config_prov.get("total") != 2:
        failures.append(
            f"FIXTURE topics: config-repo total should be unaffected by "
            f"memory/topics/ — got {config_prov.get('total')}, expected 2"
        )

    # A repo with NO memory/topics/ directory must render/serialise exactly
    # as before topic-awareness: no 'topics' key, no extra line.
    basic_results = run_metrics(fixture_path.parent / "basic",
                                fixture_path.parent / "basic" / ".dream-state.json",
                                omit_support_set=False)
    if "topics" in basic_results:
        failures.append(
            "FIXTURE topics: a fixture with no memory/topics/ directory "
            "(basic) unexpectedly got a 'topics' key — topic-awareness must "
            "be a no-op when the directory is absent"
        )
    if "Anchor completeness (topic memory" in format_text(basic_results):
        failures.append(
            "FIXTURE topics: the topic-memory line leaked into the 'basic' "
            "fixture's text output, which has no memory/topics/ directory"
        )

    return failures


def run_fixture_signals(fixture_path: Path) -> list:
    """[improvement_signal] entries (memory-rules.md § [improvement_signal]
    sub-form): one in memory/topics/improvement-signals.md, one still in
    memory/MEMORY.md. HIGHER_ORDER.md has one node whose Support-set names
    both signals, a signal that exists nowhere, and the plain MEMORY.md
    entry. Asserts:
      - both signal pointers resolve, whichever file holds the signal, and
        the never-written one is confirmed-absent (3 resolved, 1 absent);
      - anchor completeness still skips signals: config-repo counts the
        plain entry and the node only (2), and a topic directory holding
        nothing but signals adds no topic-memory line.
    """
    failures = []
    results = run_metrics(fixture_path, fixture_path / ".dream-state.json",
                          omit_support_set=False)
    ss = results.get("support_set") or {}
    want = {"resolved": 3, "confirmed_absent": 1, "indeterminate": 0,
            "total_pointers": 4, "total_nodes": 1}
    got = {k: ss.get(k) for k in want}
    if got != want:
        failures.append(f"FIXTURE signals: support-set counts {got}, expected {want}")
    config_prov = results["provenance"].get("config-repo", {})
    if config_prov.get("total") != 2:
        failures.append(
            f"FIXTURE signals: config-repo anchor total {config_prov.get('total')}, "
            f"expected 2 (signals are not counted)")
    if "topics" in results:
        failures.append(
            "FIXTURE signals: a topics/ directory holding only signals produced "
            "a 'topics' key; signals are not counted for anchor completeness")
    return failures


def run_parse_units() -> list:
    """parse_memory_entries on memory-entries.py: a ### in a ``` or ~~~ fence (the other marker
    nested in it) is not an entry, Declined is skipped, a signal only when asked, and a Source
    that quotes a ` | ` keeps it (only the `| **Verified**:` tail is cut)."""
    text = ("# Memory\n\n## Feedback\n\n### Kept one\n"
            "**Source**: recap \"a | b\" | **Verified**: 2026-09-01\n"
            "```\n### Fenced backtick\n~~~\n### Fenced nested\n```\n"
            "~~~\n### Fenced tilde\n```\n~~~\n"
            "### [improvement_signal] A signal\n**Source**: s\n"
            "### Kept two\n\n## Declined\n\n### Declined one\n")
    failures = []
    got = [(e["heading"], e["source"]) for e in parse_memory_entries(text)]
    want = [("Kept one", 'recap "a | b"'), ("Kept two", None)]
    if got != want:
        failures.append(f"PARSE: parse_memory_entries gave {got}, expected {want}")
    got = [e["heading"] for e in parse_memory_entries(text, include_signals=True)]
    if got != ["Kept one", "[improvement_signal] A signal", "Kept two"]:
        failures.append(f"PARSE: with signals gave {got}")
    return failures


def run_fixture_tests(fixture_dir: Path) -> list:
    """Run all fixture scenarios and assert expected output."""
    failures = []

    # Test 0c: the parser (memory-entries.py): fences, Declined, signals, Source
    failures.extend(run_parse_units())

    # Test 0: node_label boundary units (tool-label ↔ sweep-gate alignment)
    failures.extend(run_node_label_units())

    # Test 0b: project-memory pointer resolution against a store-backed file
    failures.extend(run_project_pointer_units(fixture_dir))

    # Test 1: Basic scenario with mixed sources
    failures.extend(run_fixture_basic(fixture_dir / "basic"))

    # Test 2: Edge cases — comma in heading, 0-graded tags
    failures.extend(run_fixture_edge_cases(fixture_dir / "edge_cases"))

    # Test 3: Missing state file
    failures.extend(run_fixture_missing_state(fixture_dir / "missing_state"))

    # Test 4: Source-only anchor classification
    failures.extend(run_fixture_source_anchor(fixture_dir / "source_anchor"))

    # Test 5: Project-scope fixture (dedup + per-project provenance)
    failures.extend(run_fixture_project_scope(fixture_dir / "project_scope"))

    # Test 6: Per-node groundedness fixture
    failures.extend(run_fixture_per_node(fixture_dir / "per_node"))

    # Test 7: Store-layout fixture (store-only, both-locations, identity dedup)
    failures.extend(run_fixture_store_scope(fixture_dir / "store_scope"))
    failures.extend(run_store_scope_dedupe_unit(fixture_dir))
    failures.extend(run_store_key_provenance_unit(fixture_dir))

    # Test 8: Topic-memory fixture (memory/topics/*.md as an additional
    # user-memory source — separate provenance line, Support-set resolution
    # reaching a topic-file heading)
    failures.extend(run_fixture_topics(fixture_dir / "topics"))

    # Test 8b: improvement signals -- pointers resolve in either user-memory
    # file; anchor completeness still skips them
    failures.extend(run_fixture_signals(fixture_dir / "signals"))

    # Test 9: Cost line from v3 cost_records (last baseline vs last sweep,
    # token trend), and its absence / N/A forms
    failures.extend(run_fixture_cost(fixture_dir / "cost-baseline-and-sweeps"))

    # L10: Validate --json output round-trips through json.loads
    for name in ("basic", "edge_cases", "source_anchor", "project_scope", "topics",
                 "cost-baseline-and-sweeps"):
        sub = fixture_dir / name
        state_file = sub / ".dream-state.json"
        if state_file.exists():
            results = run_metrics(sub, state_file, omit_support_set=False)
            json_str = format_json(results)
            try:
                parsed = json.loads(json_str)
                if not isinstance(parsed, dict):
                    failures.append(f"JSON round-trip {name}: parsed to non-dict")
            except (json.JSONDecodeError, ValueError) as e:
                failures.append(f"JSON round-trip {name}: invalid JSON — {e}")

    return failures


def run_fixture_cost(fixture_path: Path) -> list:
    """v3 state with one baseline and three sweeps (one without tokens)."""
    failures = []
    state_file = fixture_path / ".dream-state.json"
    results = run_metrics(fixture_path, state_file, omit_support_set=True)
    output = format_text(results)
    expected_cost = (
        "- Cost (cost_records, 4 records): last baseline 2026-09-24: tokens 1000000, agents 53, "
        "sessions 40, bytes 5000000, findings surfaced 10 kept 6, proposals surfaced 4 applied 2; "
        "last sweep 2026-10-15: tokens 600000, agents 9, sessions 12, "
        "bytes 1500000, findings surfaced 10 kept 6, proposals surfaced 4 applied 2; "
        "sweep vs baseline (not like-for-like: baseline measured to the first "
        "Phase 4b question): tokens -40%, agents -83%; "
        "token trend over 2 sweeps: 800000 → 600000 (-25%)"
    )
    if expected_cost not in output.split("\n"):
        failures.append(f"FIXTURE cost: cost line mismatch\nGOT:\n{output}\nEXPECTED LINE:\n{expected_cost}")
    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)
    empty = dict(state, cost_records=[])
    out_empty = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                        _state_override=empty))
    if "- Cost (cost_records): N/A — 0 records" not in out_empty.split("\n"):
        failures.append(f"FIXTURE cost: empty cost_records should print N/A\nGOT:\n{out_empty}")
    only_base = dict(state, cost_records=[r for r in state["cost_records"] if r.get("kind") == "baseline"])
    out_base = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                       _state_override=only_base))
    want_base = ("- Cost (cost_records, 1 records): last baseline 2026-09-24: tokens 1000000, agents 53, "
                 "sessions 40, bytes 5000000, findings surfaced 10 kept 6, proposals surfaced 4 "
                 "applied 2; last sweep: none; "
                 "token trend: n/a (fewer than 2 sweeps with tokens)")
    if want_base not in out_base.split("\n"):
        failures.append(f"FIXTURE cost: baseline-only line mismatch\nGOT:\n{out_base}\nEXPECTED LINE:\n{want_base}")
    # A kind-baseline record with the fields memory-rules.md § State File
    # Format allows to be null.
    null_base = [dict(r, projects_analyzed=None, bytes_read=None, findings=None, proposals=None)
                 if r.get("kind") == "baseline" else r for r in state["cost_records"]]
    out_null = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                       _state_override=dict(state, cost_records=null_base)))
    want_null = ("last baseline 2026-09-24: tokens 1000000, agents 53, sessions 40, bytes n/a, "
                 "findings surfaced n/a kept n/a, proposals surfaced n/a applied n/a; ")
    cost_line = next((l for l in out_null.split("\n") if l.startswith("- Cost")), "")
    if want_null not in cost_line or "None" in cost_line:
        failures.append(f"FIXTURE cost: null baseline fields must print n/a\nGOT:\n{out_null}")
    # The percentage line always carries the scope label, and only when a
    # baseline and a sweep both exist (review 2026-09-25: a whole-sweep total
    # against a to-first-Phase-4b baseline must not read as a like-for-like
    # change).
    label = "sweep vs baseline (not like-for-like: baseline measured to the first Phase 4b question): "
    line = next((l for l in output.split("\n") if l.startswith("- Cost")), "")
    if line.count(label) != 1 or "sweep vs baseline:" in line:
        failures.append(f"FIXTURE cost: the sweep-vs-baseline line must carry the scope label\nGOT:\n{line}")
    if "sweep vs baseline" in next((l for l in out_base.split("\n") if l.startswith("- Cost")), ""):
        failures.append("FIXTURE cost: a baseline-only state must print no sweep-vs-baseline part")
    # findings / proposals sanity (memory-rules.md § State File Format):
    # kept > surfaced and applied > surfaced are flagged on the record and
    # listed for any record, shown or not; equal counts are consistent.
    recs = [dict(r) for r in state["cost_records"]]
    recs[1] = dict(recs[1], findings={"surfaced": 5, "kept": 7, "dropped_by_stage": {}})
    recs[3] = dict(recs[3], findings={"surfaced": 6, "kept": 6, "dropped_by_stage": {}},
                   proposals={"surfaced": 3, "applied": 4})
    out_bad = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                      _state_override=dict(state, cost_records=recs)))
    bad_line = next((l for l in out_bad.split("\n") if l.startswith("- Cost")), "")
    for want in ("last sweep 2026-10-15: tokens 600000, agents 9, sessions 12, bytes 1500000, "
                 "findings surfaced 6 kept 6, proposals surfaced 3 applied 4 "
                 "(inconsistent: proposals applied exceeds surfaced);",
                 "inconsistent record 2026-10-01 sweep: findings kept exceeds surfaced",
                 "inconsistent record 2026-10-15 sweep: proposals applied exceeds surfaced"):
        if want not in bad_line:
            failures.append(f"FIXTURE cost: inconsistency flag missing {want!r}\nGOT:\n{bad_line}")
    if "findings kept exceeds surfaced" in bad_line.split("last sweep")[1].split(";")[0] \
            or "2026-09-24 baseline" in bad_line:
        failures.append(f"FIXTURE cost: a consistent record must not be flagged\nGOT:\n{bad_line}")
    # Token trend: a retired-path sweep (collector role) mixed with a
    # retained-path one is labelled not like for like; all one path is not.
    mixed = [dict(r) for r in state["cost_records"]]
    mixed[3] = dict(mixed[3], agents={"task4": 4, "verifier": 2})
    out_mixed = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                        _state_override=dict(state, cost_records=mixed)))
    want_mixed = ("token trend over 2 sweeps (not like for like: retired-path sweeps with a "
                  "collector role mixed with retained-path sweeps): 800000 → 600000 (-25%)")
    if want_mixed not in out_mixed:
        failures.append(f"FIXTURE cost: mixed-path trend must be labelled\nGOT:\n{out_mixed}")
    if "not like for like: retired-path" in output:
        failures.append(f"FIXTURE cost: a single-path trend must carry no mixed-path label\nGOT:\n{output}")
    v2 = {k: v for k, v in state.items() if k != "cost_records"}
    out_v2 = format_text(run_metrics(fixture_path, state_file, omit_support_set=True, _state_override=v2))
    if "Cost" in out_v2:
        failures.append(f"FIXTURE cost: a state without cost_records must print no cost line\nGOT:\n{out_v2}")
    failures.extend(run_fixture_cost_ratios(fixture_path, state_file, state, output, out_empty, out_base))
    return failures


def run_fixture_cost_ratios(fixture_path, state_file, state, output, out_empty, out_base) -> list:
    """The Cost ratios line (plan 261006 SC-11): the last sweep's tokens per
    surfaced finding and per applied proposal, role shares from
    tokens_by_role, and every n/a path; --json carries them under cost."""
    failures = []

    def ratio_line(text):
        return next((l for l in text.split("\n") if l.startswith("- Cost ratios")), None)

    # Fixture as is: last sweep 600000 tokens, 10 surfaced, 2 applied, no
    # tokens_by_role.
    want = ("- Cost ratios (last sweep 2026-10-15): tokens per surfaced finding 60000, "
            "tokens per applied proposal 300000; role shares n/a (no tokens_by_role)")
    if ratio_line(output) != want:
        failures.append(f"FIXTURE cost ratios: line mismatch\nGOT:\n{ratio_line(output)}\nEXPECTED:\n{want}")
    # tokens_by_role present: shares of its own sum, one decimal, every role.
    recs = [dict(r) for r in state["cost_records"]]
    recs[3] = dict(recs[3], tokens_by_role={"orchestrator": 648, "task4": 262, "verifier": 90, "other": 0})
    res = run_metrics(fixture_path, state_file, omit_support_set=True,
                      _state_override=dict(state, cost_records=recs))
    want_roles = ("- Cost ratios (last sweep 2026-10-15): tokens per surfaced finding 60000, "
                  "tokens per applied proposal 300000; role shares orchestrator 64.8%, "
                  "task4 26.2%, verifier 9.0%, other 0.0%")
    if ratio_line(format_text(res)) != want_roles:
        failures.append(f"FIXTURE cost ratios: role shares mismatch\nGOT:\n{ratio_line(format_text(res))}")
    got_json = json.loads(format_json(res)).get("cost", {}).get("ratios")
    want_json = {"date": "2026-10-15", "tokens_per_surfaced_finding": 60000,
                 "tokens_per_applied_proposal": 300000,
                 "role_shares": {"orchestrator": 64.8, "task4": 26.2, "verifier": 9.0, "other": 0.0},
                 "inconsistent": False}
    if got_json != want_json:
        failures.append(f"FIXTURE cost ratios: --json cost.ratios mismatch\nGOT: {got_json}\nEXPECTED: {want_json}")
    # A five-role record (plan 261012 Phase 3): every role printed, drafter
    # between verifier and other. Shares by hand: 500/300/120/80/0 of 1000.
    five = [dict(r) for r in state["cost_records"]]
    five[3] = dict(five[3], tokens_by_role={"orchestrator": 500, "task4": 300, "verifier": 120,
                                            "drafter": 80, "other": 0})
    res5 = run_metrics(fixture_path, state_file, omit_support_set=True,
                       _state_override=dict(state, cost_records=five))
    want_five = ("- Cost ratios (last sweep 2026-10-15): tokens per surfaced finding 60000, "
                 "tokens per applied proposal 300000; role shares orchestrator 50.0%, "
                 "task4 30.0%, verifier 12.0%, drafter 8.0%, other 0.0%")
    if ratio_line(format_text(res5)) != want_five:
        failures.append(f"FIXTURE cost ratios: five-role shares mismatch\nGOT:\n{ratio_line(format_text(res5))}")
    got5 = json.loads(format_json(res5)).get("cost", {}).get("ratios", {}).get("role_shares")
    if got5 != {"orchestrator": 50.0, "task4": 30.0, "verifier": 12.0, "drafter": 8.0, "other": 0.0}:
        failures.append(f"FIXTURE cost ratios: five-role --json role_shares mismatch\nGOT: {got5}")
    # Any other key set is n/a: four keys with drafter in place of other,
    # and the legacy four plus an unknown fifth.
    for label, tbr in (("drafter without other", {"orchestrator": 500, "task4": 300, "verifier": 120,
                                                    "drafter": 80}),
                       ("legacy plus collector", {"orchestrator": 500, "task4": 300, "verifier": 120,
                                                  "other": 0, "collector": 80})):
        bad = [dict(r) for r in state["cost_records"]]
        bad[3] = dict(bad[3], tokens_by_role=tbr)
        line = ratio_line(format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                                  _state_override=dict(state, cost_records=bad)))) or ""
        if not line.endswith("role shares n/a (no tokens_by_role)"):
            failures.append(f"FIXTURE cost ratios: {label} must print n/a\nGOT:\n{line}")
    # n/a paths: null tokens, zero denominators, tokens_by_role summing to 0
    # or malformed.
    na_recs = [dict(r) for r in state["cost_records"]]
    na_recs[3] = dict(na_recs[3], tokens=None)
    zero = [dict(r) for r in state["cost_records"]]
    zero[3] = dict(zero[3], findings={"surfaced": 0, "kept": 0, "dropped_by_stage": {}},
                   proposals={"surfaced": 4, "applied": 0},
                   tokens_by_role={"orchestrator": 0, "task4": 0, "verifier": 0, "other": 0})
    bad_role = [dict(r) for r in state["cost_records"]]
    bad_role[3] = dict(bad_role[3], tokens_by_role={"orchestrator": 5, "task4": -1, "verifier": 0, "other": 0})
    for label, rs, want_na in (
            ("null tokens", na_recs, "tokens per surfaced finding n/a, tokens per applied proposal n/a; "
                                     "role shares n/a (no tokens_by_role)"),
            ("zero denominators", zero, "tokens per surfaced finding n/a, tokens per applied proposal n/a; "
                                        "role shares n/a (no tokens_by_role)"),
            ("malformed tokens_by_role", bad_role, "role shares n/a (no tokens_by_role)")):
        line = ratio_line(format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                                  _state_override=dict(state, cost_records=rs)))) or ""
        if want_na not in line or "None" in line:
            failures.append(f"FIXTURE cost ratios: {label} must print n/a\nGOT:\n{line}")
    # Drop stages above surfaced - kept: flagged on the Cost line and on the
    # ratio line; stages exactly at the gap are consistent.
    over = [dict(r) for r in state["cost_records"]]
    over[3] = dict(over[3], findings={"surfaced": 10, "kept": 6, "dropped_by_stage": {"already_known": 5}})
    out_over = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                       _state_override=dict(state, cost_records=over)))
    if "inconsistent record 2026-10-15 sweep: findings dropped_by_stage exceeds surfaced minus kept" not in out_over:
        failures.append(f"FIXTURE cost ratios: stage sum above surfaced - kept must be flagged\nGOT:\n{out_over}")
    if not (ratio_line(out_over) or "").endswith("role shares n/a (no tokens_by_role) (inconsistent record)"):
        failures.append(f"FIXTURE cost ratios: an inconsistent record must be marked\nGOT:\n{ratio_line(out_over)}")
    at_gap = [dict(r) for r in state["cost_records"]]
    at_gap[3] = dict(at_gap[3], findings={"surfaced": 10, "kept": 6, "dropped_by_stage": {"already_known": 4}})
    out_gap = format_text(run_metrics(fixture_path, state_file, omit_support_set=True,
                                      _state_override=dict(state, cost_records=at_gap)))
    if "inconsistent" in "\n".join(l for l in out_gap.split("\n") if l.startswith("- Cost")):
        failures.append(f"FIXTURE cost ratios: stages equal to surfaced - kept are consistent\nGOT:\n{out_gap}")
    if ratio_line(out_base) != "- Cost ratios: n/a — no sweep record":
        failures.append(f"FIXTURE cost ratios: a baseline-only state must print n/a\nGOT:\n{out_base}")
    if ratio_line(out_empty) is not None:
        failures.append(f"FIXTURE cost ratios: empty cost_records must print no ratio line\nGOT:\n{out_empty}")
    return failures


def run_fixture_basic(fixture_path: Path) -> list:
    """Basic fixture: mixed anchored/free-text sources, support-set, outcome."""
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    results = run_metrics(repo_root, state_file, omit_support_set=False)
    output = format_text(results)

    expected = (
        "Memory-health metrics (qmemory-eval — read-only snapshot):\n"
        "- Anchor completeness (config-repo): 4/6 anchored (67%); 2 free-text\n"
        "- Support-set resolution (reachable-now): 3 resolved, 1 confirmed-absent, "
        "2 indeterminate (6 node pointers / 1 nodes)\n"
        "- Outcome resolution: 2/5 graded (1 recurred, 1 not-recurred)\n"
        "- Memory footprint (config-repo files, session-start load): 162 words (~216 tokens) — "
        "HIGHER_ORDER.md 68, MEMORY.md 94"
    )

    if output != expected:
        failures.append(f"FIXTURE basic: output mismatch\nGOT:\n{output}\nEXPECTED:\n{expected}")

    # M3 boundary test: episodic_ledger #<len> should resolve, #0 should be confirmed-absent
    with open(state_file, "r", encoding="utf-8") as f:
        state_data = json.load(f)
    ledger = state_data.get("episodic_ledger", [])
    plans_done_dir = fixture_path / "plans" / "done"
    # #<len> (last valid 1-based index) should resolve
    result_max = resolve_pointer(f"episodic_ledger #{len(ledger)}", state_data, set(), plans_done_dir)
    if result_max != "resolved":
        failures.append(f"FIXTURE basic boundary: episodic_ledger #{len(ledger)} expected 'resolved', got '{result_max}'")
    # #0 should be confirmed-absent (0 is not valid in 1-based)
    result_zero = resolve_pointer("episodic_ledger #0", state_data, set(), plans_done_dir)
    if result_zero != "confirmed-absent":
        failures.append(f"FIXTURE basic boundary: episodic_ledger #0 expected 'confirmed-absent', got '{result_zero}'")
    # #<len+1> should be confirmed-absent
    result_oob = resolve_pointer(f"episodic_ledger #{len(ledger) + 1}", state_data, set(), plans_done_dir)
    if result_oob != "confirmed-absent":
        failures.append(f"FIXTURE basic boundary: episodic_ledger #{len(ledger) + 1} expected 'confirmed-absent', got '{result_oob}'")

    return failures


def run_fixture_edge_cases(fixture_path: Path) -> list:
    """Edge cases: comma-in-heading support-set, bracket-wrapped."""
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    results = run_metrics(repo_root, state_file, omit_support_set=False)
    output = format_text(results)

    expected = (
        "Memory-health metrics (qmemory-eval — read-only snapshot):\n"
        "- Anchor completeness (config-repo): 1/3 anchored (33%); 2 free-text\n"
        "- Support-set resolution (reachable-now): 1 resolved, 1 confirmed-absent, "
        "1 indeterminate (3 node pointers / 1 nodes)\n"
        "- Outcome resolution: N/A — 0/3 graded\n"
        "- Memory footprint (config-repo files, session-start load): 108 words (~144 tokens) — "
        "HIGHER_ORDER.md 51, MEMORY.md 57"
    )

    if output != expected:
        failures.append(f"FIXTURE edge_cases: output mismatch\nGOT:\n{output}\nEXPECTED:\n{expected}")
    return failures


def run_fixture_missing_state(fixture_path: Path) -> list:
    """Missing state file → SKIP."""
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    results = run_metrics(repo_root, state_file, omit_support_set=False)
    output = format_text(results)

    expected = "SKIP — state file not found"
    if output != expected:
        failures.append(f"FIXTURE missing_state: output mismatch\nGOT:\n{output}\nEXPECTED:\n{expected}")
    return failures


def run_fixture_source_anchor(fixture_path: Path) -> list:
    """Source is the only anchor field; a governance ref is free-text."""
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    results = run_metrics(repo_root, state_file, omit_support_set=True)
    output = format_text(results)

    expected = (
        "Memory-health metrics (qmemory-eval — read-only snapshot):\n"
        "- Anchor completeness (config-repo): 4/7 anchored (57%); 3 free-text\n"
        "- Outcome resolution: N/A — 0/1 graded\n"
        "- Memory footprint (config-repo files, session-start load): 338 words (~451 tokens) — "
        "MEMORY.md 338"
    )

    if output != expected:
        failures.append(f"FIXTURE source_anchor: output mismatch\nGOT:\n{output}\nEXPECTED:\n{expected}")
    return failures


def run_fixture_project_scope(fixture_path: Path) -> list:
    """Project-scope fixture: exercises dedup logic and per-project provenance path.

    Uses the fixture's .dream-state.json as a template but resolves relative
    project keys to absolute paths (in production, projects keys are always absolute).
    """
    failures = []
    if not (fixture_path / ".dream-state.json").exists():
        failures.append("FIXTURE project_scope: .dream-state.json not found")
        return failures
    # sub_project_a keeps its memory in the workspace, which a reader reads only through the
    # resolver's folder_fallback: in a no-create folder (here a copy under the system temp
    # directory, outside git and outside the config repo) with a readable store repo that has no
    # store for it. Run in place, the fixture sits inside the config repo and is never read.
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qme-scope-") as tmp:
        copy = Path(tmp) / "fx"
        shutil.copytree(str(fixture_path), str(copy))
        stores = Path(tmp) / "stores"
        (stores / ".git").mkdir(parents=True)
        with _StoresEnv(stores):
            failures.extend(_project_scope_asserts(copy))
        # A missing store repo reads nothing: the in-workspace copy is not counted then.
        with _StoresEnv(Path(tmp) / "no-such-store-repo"):
            results = run_metrics(copy, copy / ".dream-state.json", omit_support_set=True,
                                  _state_override=_abs_project_keys(copy))
        if str((copy / "sub_project_a").resolve()) in results.get("provenance", {}):
            failures.append("FIXTURE project_scope: sub_project_a counted with the store repo missing "
                            "(a missing store repo must read no in-workspace copy)")
    return failures


def _abs_project_keys(fixture_path: Path) -> dict:
    """The fixture's .dream-state.json with its relative project keys made absolute."""
    with open(fixture_path / ".dream-state.json", "r", encoding="utf-8") as f:
        state_data = json.load(f)
    state_data["projects"] = {str((fixture_path / k).resolve()): v
                              for k, v in state_data.get("projects", {}).items()}
    return state_data


def _project_scope_asserts(fixture_path: Path) -> list:
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    # Project keys rewritten to absolute paths (the fixture uses relative names)
    results = run_metrics(repo_root, state_file, omit_support_set=True,
                          _state_override=_abs_project_keys(fixture_path))

    if results.get("skip"):
        failures.append(f"FIXTURE project_scope: unexpected skip — {results.get('reason')}")
        return failures

    # Config-repo should have 1 anchored entry (session anchor)
    config_prov = results["provenance"].get("config-repo", {})
    if config_prov.get("anchored") != 1 or config_prov.get("total") != 1:
        failures.append(
            f"FIXTURE project_scope: config-repo provenance mismatch — "
            f"got anchored={config_prov.get('anchored')} total={config_prov.get('total')}, "
            f"expected anchored=1 total=1"
        )

    # sub_project_a (resolved via absolute path) should have 1 anchored, 1 free-text
    sub_a_key = str((fixture_path / "sub_project_a").resolve())
    sub_a_prov = results["provenance"].get(sub_a_key, {})
    if sub_a_prov.get("anchored") != 1 or sub_a_prov.get("free_text") != 1:
        failures.append(
            f"FIXTURE project_scope: sub_project_a provenance mismatch — "
            f"got anchored={sub_a_prov.get('anchored')} free_text={sub_a_prov.get('free_text')}, "
            f"expected anchored=1 free_text=1"
        )

    # sub_project_b has no memory/MEMORY.md — should NOT appear in results
    sub_b_key = str((fixture_path / "sub_project_b").resolve())
    if sub_b_key in results["provenance"]:
        failures.append("FIXTURE project_scope: sub_project_b should not appear (no MEMORY.md)")

    # Outcome: 1/1 graded (not_recurred)
    outcome = results["outcome"]
    if outcome["graded"] != 1 or outcome["not_recurred"] != 1:
        failures.append(
            f"FIXTURE project_scope: outcome mismatch — "
            f"got graded={outcome['graded']} not_recurred={outcome['not_recurred']}, "
            f"expected graded=1 not_recurred=1"
        )

    return failures


def run_fixture_per_node(fixture_path: Path) -> list:
    """Per-node groundedness fixture: covers all 5 label cases."""
    failures = []
    state_file = fixture_path / ".dream-state.json"
    repo_root = fixture_path

    if not state_file.exists():
        failures.append("FIXTURE per_node: .dream-state.json not found")
        return failures

    # Run with per_node=True
    results = run_metrics(repo_root, state_file, omit_support_set=False, per_node=True)

    if results.get("skip"):
        failures.append(f"FIXTURE per_node: unexpected skip — {results.get('reason')}")
        return failures

    per_node_data = results.get("per_node")
    if per_node_data is None:
        failures.append("FIXTURE per_node: 'per_node' key missing from results")
        return failures

    # Expected labels for each node (order matches HIGHER_ORDER.md)
    expected_nodes = [
        # Grounded: episodic_ledger #1 (resolved), user memory § Entry one with anchor (resolved),
        #           260101-1200_FIXTURE_PLAN § Intent (resolved via plans/done/)
        {"heading": "Grounded node \u2014 all checkable ground present", "label": "grounded",
         "resolved": 3, "confirmed_absent": 0, "indeterminate": 0},
        # Weak: episodic_ledger #2 (resolved), user memory § Nonexistent heading gone (confirmed-absent),
        #       episodic_ledger #1 (resolved)
        {"heading": "Weak node \u2014 some verified-gone ground alongside resolved", "label": "weak",
         "resolved": 2, "confirmed_absent": 1, "indeterminate": 0},
        # Ungrounded: user memory § Deleted heading alpha (confirmed-absent),
        #             user memory § Deleted heading beta (confirmed-absent)
        {"heading": "Ungrounded node \u2014 all checkable ground gone", "label": "ungrounded",
         "resolved": 0, "confirmed_absent": 2, "indeterminate": 0},
        # Unverifiable: session abc12345 (indeterminate), session def67890 (indeterminate),
        #               project memory (SomeProject) § Some heading (indeterminate)
        {"heading": "Unverifiable node \u2014 only indeterminate pointers", "label": "unverifiable",
         "resolved": 0, "confirmed_absent": 0, "indeterminate": 3},
        # No-support-set: no Support-set line
        {"heading": "No-support-set node \u2014 no Support-set line at all", "label": "no-support-set",
         "resolved": 0, "confirmed_absent": 0, "indeterminate": 0},
    ]

    if len(per_node_data) != len(expected_nodes):
        failures.append(
            f"FIXTURE per_node: node count mismatch — "
            f"got {len(per_node_data)}, expected {len(expected_nodes)}"
        )
        return failures

    for i, (actual, expected) in enumerate(zip(per_node_data, expected_nodes)):
        if actual["heading"] != expected["heading"]:
            failures.append(
                f"FIXTURE per_node[{i}]: heading mismatch — "
                f"got '{actual['heading']}', expected '{expected['heading']}'"
            )
        if actual["label"] != expected["label"]:
            failures.append(
                f"FIXTURE per_node[{i}]: label mismatch — "
                f"got '{actual['label']}', expected '{expected['label']}'"
            )
        if actual["resolved"] != expected["resolved"]:
            failures.append(
                f"FIXTURE per_node[{i}]: resolved mismatch — "
                f"got {actual['resolved']}, expected {expected['resolved']}"
            )
        if actual["confirmed_absent"] != expected["confirmed_absent"]:
            failures.append(
                f"FIXTURE per_node[{i}]: confirmed_absent mismatch — "
                f"got {actual['confirmed_absent']}, expected {expected['confirmed_absent']}"
            )
        if actual["indeterminate"] != expected["indeterminate"]:
            failures.append(
                f"FIXTURE per_node[{i}]: indeterminate mismatch — "
                f"got {actual['indeterminate']}, expected {expected['indeterminate']}"
            )

    # Verify default run (per_node=False) does NOT include per_node key
    results_default = run_metrics(repo_root, state_file, omit_support_set=False, per_node=False)
    if "per_node" in results_default:
        failures.append("FIXTURE per_node: 'per_node' key present in default (per_node=False) results")

    # Verify --json round-trip for per-node results
    json_str = format_json(results)
    try:
        parsed = json.loads(json_str)
        if "per_node" not in parsed:
            failures.append("FIXTURE per_node: 'per_node' missing from JSON output")
        elif not isinstance(parsed["per_node"], list):
            failures.append("FIXTURE per_node: 'per_node' in JSON is not a list")
        elif len(parsed["per_node"]) != 5:
            failures.append(f"FIXTURE per_node: 'per_node' in JSON has {len(parsed['per_node'])} items, expected 5")
    except (json.JSONDecodeError, ValueError) as e:
        failures.append(f"FIXTURE per_node: JSON round-trip failed — {e}")

    return failures


# --- Main ---

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


def main():
    _require_venv(__file__)
    parser = argparse.ArgumentParser(
        description="Read-only memory-health metrics.",
        epilog="Cost line (v3 cost_records): each printed record shows tokens, agents, sessions, "
               "bytes, findings surfaced/kept and proposals surfaced/applied; a record whose kept "
               "or applied count exceeds its surfaced count is flagged 'inconsistent' (every such "
               "record is listed). The token trend is labelled 'not like for like' when it mixes "
               "retired-path sweeps (an agents role `collector`) with retained-path sweeps.")
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="Config repo root (default: auto-detect from script location)")
    parser.add_argument("--state-file", type=Path, default=None,
                        help="Path to .dream-state.json (default: <repo-root>/memory/.dream-state.json)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as JSON")
    parser.add_argument("--omit-support-set", action="store_true",
                        help="Skip support-set metric (for in-sweep caller)")
    parser.add_argument("--per-node", action="store_true",
                        help="Per-node groundedness breakdown (standalone, read-only)")
    parser.add_argument("--selftest", action="store_true",
                        help="Run fixture tests + no-writes assertion")
    args = parser.parse_args()

    if args.selftest:
        script_path = Path(__file__).resolve()
        failures = run_selftest(script_path)
        if failures:
            print(f"SELFTEST FAILED ({len(failures)} failure(s)):", file=sys.stderr)
            for f in failures:
                print(f"  {f}", file=sys.stderr)
            sys.exit(1)
        print("SELFTEST PASSED")
        sys.exit(0)

    repo_root = args.repo_root
    if repo_root is None:
        repo_root = find_repo_root(Path(__file__).resolve().parent)

    state_file = args.state_file
    if state_file is None:
        state_file = repo_root / "memory" / ".dream-state.json"

    results = run_metrics(repo_root, state_file, omit_support_set=args.omit_support_set,
                          per_node=args.per_node)

    if results.get("skip"):
        print(f"SKIP — {results['reason']}")
        sys.exit(0)

    if args.per_node:
        if args.json_output:
            print(format_json(results))
        else:
            print(format_per_node_text(results))
    elif args.json_output:
        print(format_json(results))
    else:
        print(format_text(results))


if __name__ == "__main__":
    main()
