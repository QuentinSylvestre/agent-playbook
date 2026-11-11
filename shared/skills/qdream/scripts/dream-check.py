#!/usr/bin/env python3
"""dream-check.py -- /qdream mechanical checks: the skill load budget and
fence-aware section reads.

Subcommands:
  budget [--repo <dir>]
      Word counts (whitespace-separated tokens, as `wc -w` in a UTF-8 locale;
      a C locale skips lone non-ASCII tokens such as an em dash) of the core
      skill load and the lightweight load (core plus the named sections,
      extracted fence-aware), with the Kiro additions (kiro core: core plus
      the core OVERLAY.md; kiro lightweight: lightweight plus both overlays)
      reported for information. Compared with the pinned budgets; while they are
      unpinned it prints the numbers and exits 0. Exit 1 only over a pinned
      budget or when a named section is missing. Also prints a `memory` row:
      the words of <repo>/memory/MEMORY.md + HIGHER_ORDER.md (counted by
      qmemory-eval.py) as <words>/<pin> against dream-manifest.py's
      MEMORY_BUDGET_WORDS, plus OVER when over. Warn-only: the memory row
      never affects the exit code.
      Without --repo the config repo is this script's own checkout when it
      holds shared/skills/qdream/SKILL.md; else the config repo the work
      folder's manifest read (the base of its user-memory files); else exit 1
      asking for --repo (a deployed copy, e.g. ~/.kiro/skills/qdream/scripts).
  extract --file <md> --section "<heading>" [--exclude "<heading>"]...
      Prints one section, fence-aware (a heading inside a code fence does not
      end it). "## Name" matches that level only; "Name" matches the first
      heading of any level. --exclude drops a sub-section. Exit 1 when the
      section, or an --exclude heading inside it, is not found.
  extract --file <md> --step <ID> [--intro]
      Prints one step, fence-aware: from the line holding its definition tag
      (`[ID]` in backticks) up to the next line holding another step's tag,
      or the next heading at or above the level of the heading the step sits
      under, or the end of the file. --intro first prints that heading and
      its text before its first step (the phase's own rules). Exit 1 when
      the file does not define the step or defines it twice.
  similar --entry-file <md> --target <memory file> [--repo <dir>] [--stores <dir>]
      The write-time repeat check (memory-rules.md § Dedup Check Procedure,
      step 4): scores the one entry in --entry-file (written under its type
      heading, `## Feedback`, `## Decision` or `## Pattern`) against user
      memory and its topic files (improvement-signals.md excluded) and every
      store's memory/MEMORY.md (--stores, default the store repo the
      resolver names), never against --target, the file it would be
      written to. The draft takes the project bars, so a draft stating an
      exception to a higher-tier entry is never read as a restatement. Prints
      the corpus size, each entry at or above dream-manifest.py's
      SIMILAR_THRESHOLD and one verdict line: it states an exception (save it
      with the override noted), it restates the user tier (update that
      entry), it repeats another project (propose user scope; for a user-tier
      target, the sweep offers to remove the copy), related entries only, or
      no repeat. Read-only; exit 0 whatever it finds; exit 1 when the user
      memory directory or the store repo is missing.
  --selftest
      Runs the fixture cases under fixtures/dream-check/budget/.

Exit codes: 0 ok, 1 check failed (see above), 2 usage.

Canonical rules: the lightweight load list is shared/skills/qdream/SKILL.md
§ Lightweight Consolidation; the word pins are the constants below.
Helpers (UTF-8 reads, the code-fence pattern, the run context) come from
dream-manifest.py in this directory. Python 3.8+, stdlib only.
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shlex
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

HERE = Path(os.path.realpath(__file__)).parent


def _load_manifest_module():
    # No __pycache__ in the skill directory: Kiro deploys qdream as a copy, and
    # a stray .pyc there makes verify-deployment report the copy as drifted.
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("dream_manifest", str(HERE / "dream-manifest.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


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


if __name__ == "__main__":
    _require_venv(__file__)

dm = _load_manifest_module()

# Word budgets of the core and lightweight loads (`budget` prints the current
# counts). None = unpinned. Ratchet: after a deliberate reduction, lower a pin
# to min(current pin, ceil(measured words x 1.10)) -- the ratchet verify-mass
# applies to shared/AGENTS.md, which rounds down instead. Raising a pin needs
# the user's approval, recorded in the commit message.
CORE_BUDGET_WORDS = 2166
LIGHTWEIGHT_BUDGET_WORDS = 9250

# (repo-relative file, section or None for the whole file, excluded sub-sections)
# LIGHTWEIGHT_SECTIONS mirrors the Load step of SKILL.md's Lightweight
# Consolidation section; change both together.
CORE_LOAD = [("shared/skills/qdream/SKILL.md", None, ())]
LIGHTWEIGHT_SECTIONS = [
    ("shared/skills/qdream/memory-rules.md", "## Memory File Format",
     ("### [improvement_signal] sub-form", "### Governance-conflict adjudication")),
    ("shared/skills/qdream/memory-rules.md", "### Resolution contract", ()),
    ("shared/skills/qdream/memory-rules.md", "## Exclusion List", ()),
    ("shared/skills/qdream/memory-rules.md", "## Proposal Template", ()),
    ("shared/skills/qdream/memory-rules.md", "## Dedup Check Procedure",
     ("### Native-memory harvest dedup",)),
    ("shared/skills/qdream/memory-rules.md", "## Date References", ()),
    ("shared/skills/qdream/memory-rules.md", "## Type Taxonomy",
     ("### Provenance re-open & auto-demotion",)),
    ("shared/AGENTS.md", "### Write-time quality gates", ()),
]
# Kiro appends these to the deployed files, so they load with them.
KIRO_EXTRA = [("providers/kiro/skills/qdream/OVERLAY.md", None, ()),
              ("providers/kiro/skills/qdream/memory-rules.OVERLAY.md", None, ())]

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


class Usage(Exception):
    pass


class Failure(Exception):
    """A check that cannot complete: printed, exit 1."""


_SKILL_REL = "shared/skills/qdream/SKILL.md"


def default_repo(ctx=None):
    """The config repo when --repo is absent. The script's own checkout
    (scripts/ -> qdream/ -> skills/ -> shared/ -> repo root) only when it
    holds the qdream skill: a deployed copy (~/.kiro/skills/qdream/scripts)
    sits somewhere else. Then the config repo the work folder's manifest read
    (the base of its user-memory files). Else Failure naming --repo."""
    if len(HERE.parents) > 3 and (HERE.parents[3] / _SKILL_REL).is_file():
        return HERE.parents[3]
    home = ctx.home if ctx is not None else Path.home()
    work = dm.work_path(home)
    found = None
    if os.path.isdir(str(work)) and dm.guard_reason(work, home) is None:
        man = dm.load_json(work / "manifest.json")
        um = man.get("user_memory") if isinstance(man, dict) else None
        det = um.get("detail") if isinstance(um, dict) else None
        obj = dm.load_json(work / det) if isinstance(det, str) else None
        files = obj.get("files") if isinstance(obj, dict) else None
        # An absolute first path only: a relative one would resolve against
        # the current directory, naming whatever repo the caller stands in.
        if isinstance(files, list) and files and isinstance(files[0], str) \
                and os.path.isabs(files[0]):
            fp = Path(files[0])
            base = fp.parent.parent if fp.parent.name == "topics" else fp.parent
            found = base.parent
    if found is not None and (found / _SKILL_REL).is_file():
        return found
    raise Failure("no --repo given, and this script (%s) does not sit in the config repo's "
                  "shared/skills/qdream/scripts, nor does the work folder's manifest name "
                  "one: pass --repo <config repo>" % HERE)


# --------------------------------------------------------------------------
# Sections (fence-aware)
# --------------------------------------------------------------------------

_HEAD_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")


def split_lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def headings(lines):
    """-> [(line index, level, text)] outside code fences."""
    out, fence = [], None
    for i, line in enumerate(lines):
        fm = dm.memory_entries().FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        hm = _HEAD_RE.match(line)
        if hm:
            out.append((i, len(hm.group(1)), hm.group(2).strip()))
    return out


def _range(lines, heads, k):
    start, level = heads[k][0], heads[k][1]
    for i, lv, _t in heads[k + 1:]:
        if lv <= level:
            return start, i
    return start, len(lines)


def _htext(t):
    return " ".join(t.replace("`", "").split())


def find_section(lines, spec, heads=None):
    """spec '## Name' (that level) or 'Name' (any level) -> (start, end) or None."""
    heads = headings(lines) if heads is None else heads
    m = re.match(r"^(#{1,6})\s+(.*)$", spec.strip())
    level, name = (len(m.group(1)), m.group(2)) if m else (None, spec)
    name = _htext(name)
    for k, (_i, lv, t) in enumerate(heads):
        if (level is None or lv == level) and _htext(t) == name:
            return _range(lines, heads, k)
    return None


# A step's definition tag: `[ID]` in backticks (SKILL.md § Step-ID convention);
# a citation of the step is `§ ID`, never this form.
_STEP_TAG_RE = re.compile(r"`\[([A-Z]{3}-[A-Z0-9-]+)\]`")


def step_tags(lines):
    """-> [(line index, step id)] of the definition tags outside code fences."""
    out, fence = [], None
    for i, line in enumerate(lines):
        fm = dm.memory_entries().FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        out.extend((i, m.group(1)) for m in _STEP_TAG_RE.finditer(line))
    return out


def step_sections(lines, tags, heads):
    """-> {tag line: (section heading line or None, its level or 0)}. A
    step's section is the heading its run of steps sits under: the first
    tag takes the nearest heading above it; a later tag keeps the previous
    section unless a heading at or above that section's level comes
    between them (then the last such heading), so a deeper heading inside
    a step does not start a section."""
    out, sec, prev = {}, (None, 0), -1
    for t in sorted({i for i, _sid in tags}):
        between = [h for h in heads if prev < h[0] < t]
        if sec[0] is None:
            if between:
                sec = (between[-1][0], between[-1][1])
        else:
            resets = [h for h in between if h[1] <= sec[1]]
            if resets:
                sec = (resets[-1][0], resets[-1][1])
        out[t], prev = sec, t
    return out


def step_text(text, step_id, intro=False):
    """One step's text: from the line holding its definition tag up to the
    next line holding another step's tag, or the next heading at or above
    the level of its section heading (step_sections; a step under no
    heading ends at any heading), or the end of the file. intro prepends
    the section heading and its text before the section's first step tag.
    None when the file does not define the step; Failure when it defines it
    more than once."""
    lines = split_lines(text)
    tags = step_tags(lines)
    at = sorted({i for i, sid in tags if sid == step_id})   # a tag repeated on its line is one
    if not at:
        return None
    if len(at) > 1:
        raise Failure("step %s is defined %d times (lines %s)"
                      % (step_id, len(at), ", ".join(str(i + 1) for i in at)))
    start = at[0]
    heads = headings(lines)
    sec_line, level = step_sections(lines, tags, heads)[start]
    end = len(lines)
    for i, _sid in tags:
        if i > start:
            end = min(end, i)
            break
    for i, lv, _t in heads:
        if i > start and (level == 0 or lv <= level):
            end = min(end, i)
            break
    body = lines[start:end]
    if intro and sec_line is not None:
        first = next((i for i, _sid in tags if i > sec_line), start)
        body = lines[sec_line:min(first, start)] + ([""] if first < start else []) + body
    return "\n".join(body)


def section_text(text, spec, exclude=()):
    lines = split_lines(text)
    heads = headings(lines)
    rng = find_section(lines, spec, heads)
    if rng is None:
        return None
    start, end = rng
    drop = set()
    for ex in exclude:
        sub = find_section(lines[start + 1:end], ex)
        if sub is None:
            raise Failure("excluded heading %r not found inside %r" % (ex, spec))
        drop.update(range(start + 1 + sub[0], start + 1 + sub[1]))
    return "\n".join(l for i, l in enumerate(lines[start:end], start) if i not in drop)

# --------------------------------------------------------------------------
# budget / extract
# --------------------------------------------------------------------------

def words(text):
    return len(text.split())


def load_part(repo, rel, section, exclude):
    p = Path(repo) / rel
    try:
        text = dm.read_text(p)
    except OSError as e:
        raise Failure("cannot read %s: %s" % (rel, e))
    if section is None:
        return text
    got = section_text(text, section, exclude)
    if got is None:
        raise Failure("section %r not found in %s" % (section, rel))
    return got


def budget_report(repo, core_budget, light_budget, memory_budget=None):
    """-> (exit code, lines). memory_budget is the user-memory word pin; the
    memory row it drives is warn-only and never changes the exit code."""
    lines, parts = [], []
    core = 0
    for rel, sec, ex in CORE_LOAD:
        n = words(load_part(repo, rel, sec, ex))
        core += n
        parts.append("  core %s: %d" % (rel, n))
    light = core
    for rel, sec, ex in LIGHTWEIGHT_SECTIONS:
        n = words(load_part(repo, rel, sec, ex))
        light += n
        parts.append("  lightweight %s § %s%s: %d" % (
            rel, sec, (" (without %s)" % ", ".join(ex)) if ex else "", n))
    kiro = kiro_core = 0
    for rel, sec, ex in KIRO_EXTRA:
        p = Path(repo) / rel
        if p.is_file():
            n = words(load_part(repo, rel, sec, ex))
            kiro += n
            if rel == KIRO_EXTRA[0][0]:
                kiro_core = n
            parts.append("  kiro %s: %d" % (rel, n))
    code = EXIT_OK
    for name, got, pinned in (("core", core, core_budget), ("lightweight", light, light_budget)):
        if pinned is None:
            verdict = "unpinned"
        elif got > pinned:
            verdict = "OVER budget %d" % pinned
            code = EXIT_FAIL
        else:
            verdict = "within budget %d" % pinned
        lines.append("budget: %s %d words -- %s" % (name, got, verdict))
    try:
        mem_words, _pin, note = dm.memory_budget(repo)
    except (Exception, SystemExit) as e:  # warn-only: a counter failure never changes the exit code
        lines.append("budget: memory unavailable (%s: %s; warn only)" % (type(e).__name__, e))
    else:
        if memory_budget is None:
            lines.append("budget: memory %d words -- unpinned%s (warn only)" % (mem_words, note))
        else:
            lines.append("budget: memory %d/%d%s%s (memory/MEMORY.md + memory/HIGHER_ORDER.md; warn only)"
                         % (mem_words, memory_budget, " OVER" if mem_words > memory_budget else "", note))
    lines.append("budget: kiro core %d words (core + %d of the Kiro core OVERLAY.md; information only)"
                 % (core + kiro_core, kiro_core))
    lines.append("budget: kiro lightweight %d words (lightweight + %d of Kiro overlays; information only)"
                 % (light + kiro, kiro))
    return code, lines + parts


def cmd_budget(args, ctx):
    repo = Path(args.repo) if args.repo else default_repo(ctx)
    code, lines = budget_report(repo, CORE_BUDGET_WORDS, LIGHTWEIGHT_BUDGET_WORDS,
                                dm.MEMORY_BUDGET_WORDS)
    print("\n".join(lines))
    return code


def cmd_extract(args, ctx):
    try:
        text = dm.read_text(args.file)
    except OSError as e:
        raise Failure("cannot read %s: %s" % (args.file, e))
    if args.step:
        got = step_text(text, args.step, intro=args.intro)
        if got is None:
            raise Failure("step %s is not defined in %s" % (args.step, args.file))
        sys.stdout.write(got.rstrip("\n") + "\n")
        return EXIT_OK
    got = section_text(text, args.section, args.exclude or ())
    if got is None:
        raise Failure("section %r not found in %s" % (args.section, args.file))
    sys.stdout.write(got.rstrip("\n") + "\n")
    return EXIT_OK


# --------------------------------------------------------------------------
# similar: the write-time repeat check (memory-rules.md § Dedup Check Procedure)
# --------------------------------------------------------------------------

def similar_corpus(repo, stores, target):
    """-> similarity documents of user memory and its topic files (improvement signals excluded)
    and every store's memory/MEMORY.md but the user store. Entries of `target` (the file the new
    entry would go to) share the candidate's store key, so they are never its pair."""
    tkey = dm.norm_key(dm.canon_path(str(target)))
    docs = []
    mem = Path(repo) / "memory"
    files = [mem / "MEMORY.md"] + sorted((mem / "topics").glob("*.md"))
    for f in files:
        if f.is_file() and f.name.lower() != "improvement-signals.md":
            k = dm.norm_key(dm.canon_path(str(f)))
            docs += dm.similar_docs(f, "user", "candidate" if k == tkey else "user")
    real_user = os.path.realpath(str(mem))
    for f in sorted(Path(stores).glob("*/memory/MEMORY.md")) if stores else []:
        if os.path.realpath(str(f.parent)) == real_user:
            continue
        k = dm.norm_key(dm.canon_path(str(f)))
        docs += dm.similar_docs(f, "project", "candidate" if k == tkey else k)
    return docs


def cmd_similar(args, ctx):
    repo = Path(args.repo) if args.repo else default_repo(ctx)
    stores = Path(args.stores) if args.stores else Path(dm.resolver().store_repo_root())
    if not os.path.isfile(args.entry_file):
        raise Failure("cannot read %s" % args.entry_file)
    for what, d in (("user memory", Path(repo) / "memory"), ("store repo", stores)):
        if not d.is_dir():
            raise Failure("%s %s is not a directory: the check would compare against nothing" % (what, d))
    tdir = os.path.realpath(str(Path(repo) / "memory"))
    tier = "user" if os.path.realpath(str(Path(args.target).parent)) in (tdir, os.path.join(tdir, "topics"))         else "project"
    # The draft is scored as a project document whatever its target, so it pairs with every user-tier
    # file but its target, and its own bars (a stated exception) apply.
    cand = [dict(d, store="candidate", file="(new entry)")
            for d in dm.similar_docs(args.entry_file, "project", "candidate")]
    if len(cand) != 1:
        raise Failure("%s holds %d entries under a type section; write the proposed entry as one `### ` "
                      "entry under its `## Feedback`, `## Decision` or `## Pattern` heading"
                      % (args.entry_file, len(cand)))
    corpus = similar_corpus(repo, stores, args.target)
    print("similar: scanned %d user-tier and %d project entries" % (
        sum(d["tier"] == "user" for d in corpus), sum(d["tier"] == "project" for d in corpus)))
    offered, excluded = dm.similar_pairs(corpus + cand)
    mine = [p for p in offered + excluded if "(new entry)" in (p["a"]["file"], p["b"]["file"])]
    mine.sort(key=lambda p: -p["score"])
    if not mine:
        print("similar: no repeat at or above %.2f; write it at the narrowest true scope" % dm.SIMILAR_THRESHOLD)
        return EXIT_OK

    def other(p):
        return p["b"] if p["a"]["file"] == "(new entry)" else p["a"]

    for p in mine:
        o = other(p)
        print("%.2f %s %s § %s%s" % (p["score"], o["tier"], o["file"], o["heading"],
                                          "  (excluded: %s)" % p["why"] if p.get("why") else ""))
    user_hit = any(other(p)["tier"] == "user" for p in mine)
    proj_hit = any(other(p)["tier"] == "project" and not p.get("why") for p in mine)
    if cand[0]["bar"] == "exception":
        print("similar: states an exception to a higher-tier entry: save it at its own scope with the "
              "override noted in Why (step 4, memory-tier branch); never fold it into that entry")
    elif user_hit:
        print("similar: restates the user tier: update that entry instead of saving a copy")
    elif proj_hit and tier == "user":
        print("similar: another project holds a copy: save it; the next /qdream sweep offers to remove "
              "that copy")
    elif proj_hit:
        print("similar: repeats another project: propose user scope (promotion to user memory); "
              "the user decides, and the next /qdream sweep offers to remove the other copy")
    else:
        print("similar: related entries only, each excluded by a bar (listed above); write it at the "
              "narrowest true scope")
    return EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv):
    ap = argparse.ArgumentParser(prog="dream-check.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["budget", "extract", "similar"])
    for opt in ("--repo", "--file", "--section", "--step", "--entry-file", "--target", "--stores"):
        ap.add_argument(opt)
    ap.add_argument("--exclude", action="append")
    ap.add_argument("--intro", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        raise Usage("bad arguments") if e.code else e
    given = {k for k, v in vars(args).items() if v not in (None, False) and k != "command"}
    if args.selftest:
        if args.command or given - {"selftest"}:
            raise Usage("--selftest takes no other argument")
        return args
    need = {
        "budget": (set(), {"repo"}),
        "extract": ({"file", "section"}, {"exclude"}),
        "similar": ({"entry_file", "target"}, {"repo", "stores"}),
    }
    if not args.command:
        raise Usage("a subcommand is required: budget | extract | similar")
    if args.command == "extract" and "step" in given:
        if given & {"section", "exclude"}:
            raise Usage("extract takes --section [--exclude] or --step [--intro], not both")
        if not re.fullmatch(r"[A-Z]{3}-[A-Z0-9-]+", args.step):
            raise Usage("--step takes a step id such as SYN-WRITE")
        need["extract"] = ({"file", "step"}, {"intro"})
    req, opt = need[args.command]
    if req - given:
        raise Usage("%s needs %s" % (args.command,
                                     ", ".join("--" + k for k in sorted(req - given))))
    if given - req - opt:
        raise Usage("%s does not take %s" % (args.command,
                                             ", ".join("--" + k for k in sorted(given - req - opt))))
    return args


def main(argv=None, ctx=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except Usage as e:
        print("usage error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    if args.selftest:
        return run_selftest()
    ctx = ctx or dm.Ctx()
    fn = {"budget": cmd_budget, "extract": cmd_extract, "similar": cmd_similar}[args.command]
    try:
        return fn(args, ctx)
    except Failure as e:
        print("dream-check: %s" % e, file=sys.stderr)
        return EXIT_FAIL


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

FIXDIR = HERE / "fixtures" / "dream-check"


def _run(argv, ctx):
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv, ctx)
    except Exception as e:
        code = "exception %s: %s" % (type(e).__name__, e)
    return code, out.getvalue(), err.getvalue()

# -- budget / extract --------------------------------------------------------

def _case_budget():
    spec = json.loads(dm.read_text(FIXDIR / "budget" / "cases.json"))
    repo = FIXDIR / "budget" / "tree"
    results = []
    fails = []
    code, lines = budget_report(repo, None, None)
    text = "\n".join(lines)
    for s in spec["budget_lines"]:
        if s not in text:
            fails.append("budget output lacks %r: %s" % (s, text[:400]))
    if code != 0:
        fails.append("unpinned budget exit %s" % code)
    core, light = spec["core"], spec["lightweight"]
    for cb, lb, want in ((core, light, 0), (core - 1, light, 1), (core, light - 1, 1)):
        c, _l = budget_report(repo, cb, lb)
        if c != want:
            fails.append("pinned (%s, %s): exit %s, expected %s" % (cb, lb, c, want))
    results.append(("budget/fenced-heading-inside-section", fails))
    # The memory row: under and over the pin both exit 0 (warn only).
    mem = spec["memory"]
    for pin, over in ((mem, False), (mem - 1, True)):
        fails = []
        c, lines = budget_report(repo, core, light, pin)
        row = [ln for ln in lines if ln.startswith("budget: memory ")]
        want = "budget: memory %d/%d%s" % (mem, pin, " OVER" if over else "")
        if c != 0:
            fails.append("memory pin %d: exit %s, expected 0" % (pin, c))
        if len(row) != 1 or not row[0].startswith(want + " "):
            fails.append("memory pin %d: row %r, expected it to start %r" % (pin, row, want))
        if not over and row and "OVER" in row[0]:
            fails.append("memory pin %d: row says OVER under the pin" % pin)
        results.append(("budget/memory-row-%s" % ("over" if over else "under"), fails))
    # A counter failure: the row says unavailable; the exit code and the other
    # lines are those of the run without it.
    fails = []
    saved = dm.memory_budget

    def broken(_repo):
        raise OSError("qmemory-eval.py not found")
    dm.memory_budget = broken
    try:
        for cb, lb, want in ((core, light, 0), (core - 1, light, 1)):
            c, lines = budget_report(repo, cb, lb, mem)
            if c != want:
                fails.append("counter failure (%s, %s): exit %s, expected %s" % (cb, lb, c, want))
            row = [ln for ln in lines if ln.startswith("budget: memory ")]
            if row != ["budget: memory unavailable (OSError: qmemory-eval.py not found; warn only)"]:
                fails.append("counter failure: row %r" % row)
            if not any(ln.startswith("budget: kiro lightweight ") for ln in lines):
                fails.append("counter failure dropped the other lines")
    finally:
        dm.memory_budget = saved
    results.append(("budget/memory-row-unavailable", fails))
    # A loader raising SystemExit (e.g. a qmemory-eval.py that exits at import)
    # is caught too: the row says unavailable and the exit code is unchanged.
    fails = []

    def exits(_repo):
        raise SystemExit(3)
    dm.memory_budget = exits
    try:
        c, lines = budget_report(repo, core, light, mem)
        row = [ln for ln in lines if ln.startswith("budget: memory ")]
        if c != 0:
            fails.append("SystemExit loader: exit %s, expected 0" % c)
        if row != ["budget: memory unavailable (SystemExit: 3; warn only)"]:
            fails.append("SystemExit loader: row %r" % row)
    except BaseException as e:
        fails.append("SystemExit loader escaped: %s %s" % (type(e).__name__, e))
    finally:
        dm.memory_budget = saved
    results.append(("budget/memory-row-systemexit", fails))
    for case in spec["extract_cases"]:
        fails = []
        argv = ["extract", "--file", str(repo / case["file"])]
        if "step" in case:
            argv += ["--step", case["step"]] + (["--intro"] if case.get("intro") else [])
        else:
            argv += ["--section", case["section"]]
        for ex in case.get("exclude", []):
            argv += ["--exclude", ex]
        code, out, err = _run(argv, dm.Ctx())
        if code != case.get("exit", 0):
            fails.append("exit %s, expected %s: %s" % (code, case.get("exit", 0), err.strip()))
        for s in case.get("contains", []):
            if s not in out:
                fails.append("output lacks %r" % s)
        for s in case.get("not_contains", []):
            if s in out:
                fails.append("output contains %r" % s)
        results.append(("extract/" + case["name"], fails))
    return results


_LOAD_PREFIX = {"<skill-dir>/": "shared/skills/qdream/", "<config-repo>/": ""}


def load_block_commands(core_text):
    """The fenced blocks inside the core's `### Lightweight Consolidation`
    -> list of [(file, section, excludes)] per fence, from each
    `dream-check.py extract` line (placeholders mapped to repo paths)."""
    sec = section_text(core_text, "### Lightweight Consolidation")
    if sec is None:
        raise Failure("core has no ### Lightweight Consolidation")
    fences, cur = [], None
    for line in split_lines(sec):
        if line.strip().startswith("```"):
            if cur is None:
                cur = []
            else:
                fences.append(cur)
                cur = None
            continue
        if cur is None or "dream-check.py extract" not in line:
            continue
        tok = shlex.split(line)
        f, s, ex = None, None, []
        for k, v in enumerate(tok[:-1]):
            if v == "--file":
                f = tok[k + 1]
            elif v == "--section":
                s = tok[k + 1]
            elif v == "--exclude":
                ex.append(tok[k + 1])
        for ph, repl in _LOAD_PREFIX.items():
            if f and f.startswith(ph):
                f = repl + f[len(ph):]
        cur.append((f, s, tuple(ex)))
    return fences


def _case_load_block():
    """LIGHTWEIGHT_SECTIONS must equal the extract commands of the core's
    first Load fence; the Kiro fence's sections must exist in the Kiro
    memory-rules overlay."""
    fails = []
    # A ctx with a home that holds no work folder: this case never reads the
    # real HOME's manifest, so a deployed copy fails here (naming the cause)
    # rather than silently depending on whichever sweep ran last.
    try:
        repo = default_repo(dm.Ctx(home=HERE / "no-such-home"))
    except Failure as e:
        return [("budget/load-block-matches-lightweight-sections",
                 ["needs the config repo's checkout; run the selftest from "
                  "shared/skills/qdream/scripts (%s)" % e])]
    fences = load_block_commands(dm.read_text(repo / "shared/skills/qdream/SKILL.md"))
    if len(fences) < 2:
        fails.append("expected the Load fence and the Kiro fence, found %d fence(s)" % len(fences))
    else:
        want = [(f, s, tuple(ex)) for f, s, ex in LIGHTWEIGHT_SECTIONS]
        if fences[0] != want:
            fails.append("LIGHTWEIGHT_SECTIONS %r != core Load block %r" % (want, fences[0]))
        overlay = dm.read_text(repo / KIRO_EXTRA[1][0])
        for f, s, ex in fences[1]:
            if f != "shared/skills/qdream/memory-rules.md":
                fails.append("Kiro fence reads %r, expected memory-rules.md" % f)
            try:
                if section_text(overlay, s, ex) is None:
                    fails.append("Kiro fence section %r not in %s" % (s, KIRO_EXTRA[1][0]))
            except Failure as e:
                fails.append(str(e))
    return [("budget/load-block-matches-lightweight-sections", fails)]


def _case_usage():
    fails = []
    for argv in ([], ["budget", "--file", "f"], ["extract", "--file", "f"],
                 ["extract", "--section", "s"], ["budget", "--section", "s"],
                 ["--selftest", "--repo", "r"], ["budget", "extract"],
                 ["quotes", "--items", "i"], ["cache", "plan"], ["cache", "merge"]):
        code, _o, _e = _run(argv, dm.Ctx())
        if code != EXIT_USAGE:
            fails.append("argv %s: exit %s, expected %s" % (argv, code, EXIT_USAGE))
    return [("usage/argument-errors", fails)]


def _case_similar():
    """`similar`: a draft that restates a user-tier entry says so; one that repeats another store's
    entry proposes user scope; an unrelated one, or one whose only match sits in --target itself,
    finds no repeat; a file with no typed entry is refused."""
    import shutil
    import tempfile
    fails = []
    tmp = Path(tempfile.mkdtemp(prefix="dream-check-similar-"))

    def put(rel, text):
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def ent(h, why, how):
        return "### %s\n\n**Why**: %s\n**How to apply**: %s\n**Source**: s | **Verified**: 2026-10-01\n\n" % (h, why, how)

    filler = "".join(ent("Filler %s note" % w, "The %s note is unrelated." % w, "Leave the %s note." % w)
                     for w in ("amber", "basalt", "cedar", "dune", "ember", "fjord"))
    put("repo/memory/MEMORY.md", "# Memory\n\n## Feedback\n\n" + ent(
        "Tram timetable exports drop night service rows", "A tram timetable export dropped night service rows.",
        "Count night service rows after a tram timetable export.") + filler + "## Declined\n")
    put("repo/memory/topics/improvement-signals.md", "# Signals\n\n## Feedback\n\n" + ent(
        "Glacier archive restores take twelve hours", "Glacier archive restores took twelve hours.",
        "Plan glacier archive restores twelve hours ahead."))
    put("stores/alpha-000001/memory/MEMORY.md", "# Alpha\n\n## Feedback\n\n" + ent(
        "Orchard sensor batteries fail below minus ten", "Orchard sensor batteries failed below minus ten.",
        "Fit cold-rated orchard sensor batteries before winter.") + filler)
    target = put("stores/beta-000002/memory/MEMORY.md", "# Beta\n\n## Feedback\n\n" + ent(
        "Violin rosin dust fouls pickup contacts", "Violin rosin dust fouled pickup contacts.",
        "Wipe violin rosin dust off pickup contacts weekly.") + filler)
    drafts = {
        "user": ("Tram timetable exports lose night service rows", "Night service rows vanished from a tram timetable export.",
                 "Check night service rows of each tram timetable export.", "restates the user tier"),
        "project": ("Orchard sensor batteries die below minus ten", "Orchard sensor batteries died below minus ten.",
                    "Use cold-rated orchard sensor batteries in winter.", "repeats another project"),
        "own-store": ("Violin rosin dust on pickup contacts", "Violin rosin dust fouled the pickup contacts.",
                      "Wipe the pickup contacts free of violin rosin dust.", "no repeat"),
        "signals": ("Glacier archive restore lead time", "Glacier archive restores took twelve hours.",
                    "Ask for glacier archive restores twelve hours ahead.", "no repeat"),
        "none": ("Lighthouse lamp filaments crack on cold restarts", "Lighthouse lamp filaments cracked.",
                 "Warm lighthouse lamp filaments first.", "no repeat"),
    }
    try:
        for name, (h, why, how, want) in drafts.items():
            f = put("draft-%s.md" % name, "## Feedback\n\n" + ent(h, why, how))
            code, out, err = _run(["similar", "--entry-file", str(f), "--target", str(target),
                                   "--repo", str(tmp / "repo"), "--stores", str(tmp / "stores")], dm.Ctx())
            if code != EXIT_OK or want not in out:
                fails.append("%s: exit %s, expected %r in %r %r" % (name, code, want, out[-300:], err[-200:]))
        f = put("draft-exception.md", "## Feedback\n\n" + ent(
            "Tram timetable exports keep night service rows here, an exception to the export rule",
            "A tram timetable export here kept night service rows.",
            "Skip the night service row count after a tram timetable export here."))
        code, out, err = _run(["similar", "--entry-file", str(f), "--target", str(target),
                               "--repo", str(tmp / "repo"), "--stores", str(tmp / "stores")], dm.Ctx())
        if code != EXIT_OK or "states an exception" not in out or "restates" in out:
            fails.append("exception draft: exit %s, %r %r" % (code, out[-300:], err[-200:]))
        f = put("draft-user-target.md", "## Feedback\n\n" + ent(*drafts["user"][:3]))
        code, out, err = _run(["similar", "--entry-file", str(f), "--target",
                               str(tmp / "repo" / "memory" / "topics" / "trams.md"),
                               "--repo", str(tmp / "repo"), "--stores", str(tmp / "stores")], dm.Ctx())
        if code != EXIT_OK or "restates the user tier" not in out:
            fails.append("user-tier target: exit %s, %r %r" % (code, out[-300:], err[-200:]))
        code, _o, err = _run(["similar", "--entry-file", str(f), "--target", str(target),
                              "--repo", str(tmp / "repo"), "--stores", str(tmp / "no-such-stores")], dm.Ctx())
        if code != EXIT_FAIL or "is not a directory" not in err:
            fails.append("missing store repo: exit %s, %r" % (code, err[-200:]))
        bare = put("draft-bare.md", ent("No section", "w", "h"))
        code, _o, err = _run(["similar", "--entry-file", str(bare), "--target", str(target),
                              "--repo", str(tmp / "repo"), "--stores", str(tmp / "stores")], dm.Ctx())
        if code != EXIT_FAIL or "under its" not in err:
            fails.append("no type section: exit %s, %r" % (code, err[-200:]))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return [("similar/write-time-verdicts", fails)]


def _case_default_repo():
    """`budget` without --repo: the script's own checkout only when it holds
    the qdream skill; else the manifest's config repo; else a refusal naming
    --repo. The copied-script cases run a real subprocess against a fake home."""
    import shutil
    import subprocess
    import tempfile
    results = []
    tree = FIXDIR / "budget" / "tree"
    # In-repo location: unchanged.
    fails = []
    got = default_repo(dm.Ctx(home=HERE / "no-such-home"))
    if got != HERE.parents[3]:
        fails.append("in-repo default_repo() = %s, expected %s" % (got, HERE.parents[3]))
    results.append(("budget/default-repo-in-repo", fails))
    tmp = Path(tempfile.mkdtemp(prefix="dream-check-st-"))
    try:
        # A deployed copy: the scripts below, under <tmp>/deployed/skills/qdream/scripts.
        scripts = tmp / "deployed" / "skills" / "qdream" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("dream-check.py", "dream-manifest.py", "memory-entries.py", "qmemory-eval.py", "store-resolver.py",
                     "venv-selfcheck.py"):
            shutil.copyfile(str(HERE / name), str(scripts / name))

        def run_copy(home, cwd=None):
            env = dict(os.environ, USERPROFILE=str(home), HOME=str(home))
            r = subprocess.run([sys.executable, "-I", str(scripts / "dream-check.py"), "budget"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               universal_newlines=True, encoding="utf-8", timeout=120,
                               cwd=str(cwd) if cwd is not None else None)
            return r.returncode, r.stdout, r.stderr

        def mk_home(name, files_obj):
            """A fake home whose work folder's manifest points at a
            user_memory.json holding files_obj."""
            h = tmp / name
            w = h / ".agent-playbook" / "dream-work"
            w.mkdir(parents=True)
            (w / "manifest.json").write_text(
                json.dumps({"projects": {}, "user_memory": {"detail": "user_memory.json"}}),
                encoding="utf-8")
            (w / "user_memory.json").write_text(json.dumps(files_obj), encoding="utf-8")
            return h

        # No work folder: refusal naming --repo.
        fails = []
        h1 = tmp / "home-none"
        h1.mkdir()
        rc, out, err = run_copy(h1)
        if rc != EXIT_FAIL or "--repo" not in err or "budget:" in out:
            fails.append("no manifest: exit %s, stdout %r, stderr %r" % (rc, out[:120], err[:200]))
        results.append(("budget/default-repo-copy-no-manifest-refuses", fails))
        # A manifest whose user memory sits in the repo: that repo is used.
        fails = []
        h2 = tmp / "home-man"
        work = h2 / ".agent-playbook" / "dream-work"
        work.mkdir(parents=True)
        (work / "manifest.json").write_text(
            json.dumps({"projects": {}, "user_memory": {"detail": "user_memory.json"}}),
            encoding="utf-8")
        (work / "user_memory.json").write_text(
            json.dumps({"files": [str(tree / "memory" / "MEMORY.md"),
                                  str(tree / "memory" / "topics" / "t.md")], "entries": []}),
            encoding="utf-8")
        rc, out, err = run_copy(h2)
        if rc != EXIT_OK or "budget: core " not in out:
            fails.append("manifest repo: exit %s, stdout %r, stderr %r" % (rc, out[:120], err[:200]))
        results.append(("budget/default-repo-copy-uses-manifest-repo", fails))
        # A manifest naming a folder that is no config repo: refusal.
        fails = []
        h3 = tmp / "home-bad"
        work = h3 / ".agent-playbook" / "dream-work"
        work.mkdir(parents=True)
        (work / "manifest.json").write_text(
            json.dumps({"projects": {}, "user_memory": {"detail": "user_memory.json"}}),
            encoding="utf-8")
        (work / "user_memory.json").write_text(
            json.dumps({"files": [str(tmp / "elsewhere" / "memory" / "MEMORY.md")]}),
            encoding="utf-8")
        rc, out, err = run_copy(h3)
        if rc != EXIT_FAIL or "--repo" not in err:
            fails.append("bad manifest repo: exit %s, stderr %r" % (rc, err[:200]))
        results.append(("budget/default-repo-copy-bad-manifest-refuses", fails))
        # A manifest user_memory.json with no usable first path: refusal naming
        # --repo. The relative path is run from inside the real config repo,
        # where resolving it against the current directory would succeed.
        here_repo = HERE.parents[3]
        for what, obj, cwd in (
                ("empty-files", {"files": []}, None),
                ("non-list-files", {"files": "memory/MEMORY.md"}, None),
                ("relative-first-path", {"files": ["memory/MEMORY.md"]}, here_repo)):
            fails = []
            rc, out, err = run_copy(mk_home("home-" + what, obj), cwd=cwd)
            if rc != EXIT_FAIL or "--repo" not in err or "budget:" in out:
                fails.append("%s: exit %s, stdout %r, stderr %r" % (what, rc, out[:120], err[:200]))
            results.append(("budget/default-repo-copy-%s-refuses" % what, fails))
        # Precedence: the script's own checkout wins over a manifest that names
        # another config repo (run in-process, where HERE is the checkout).
        fails = []
        other = tmp / "other-repo"
        (other / "shared" / "skills" / "qdream").mkdir(parents=True)
        (other / "shared" / "skills" / "qdream" / "SKILL.md").write_text("# x", encoding="utf-8")
        h5 = mk_home("home-other", {"files": [str(other / "memory" / "MEMORY.md")]})
        got = default_repo(dm.Ctx(home=h5))
        if got != HERE.parents[3]:
            fails.append("in-repo script with a manifest naming %s: default_repo() = %s, "
                         "expected %s" % (other, got, HERE.parents[3]))
        results.append(("budget/default-repo-in-repo-beats-manifest", fails))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return results


def run_selftest():
    results = []
    for fn in (_case_budget, _case_load_block, _case_default_repo, _case_usage, _case_similar):
        try:
            results.extend(fn())
        except Exception as e:  # one broken group never stops the run
            results.append((fn.__name__, ["group raised %s: %s" % (type(e).__name__, e)]))
    failed = 0
    for name, fails in results:
        if fails:
            failed += 1
            print("FAIL %s" % name)
            for f in fails:
                print("  - %s" % f)
        else:
            print("PASS %s" % name)
    print("selftest: %d case(s), %d failed" % (len(results), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
