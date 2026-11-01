#!/usr/bin/env python3
"""close-plan.py -- archive an active project file by deriving the
YYMMDD-HHMM_UPPER_CASE.md destination and running `git mv`.

Called by /qclose Steps 4 (dry-run preview) and 6 (live move). One script for
every platform: the Python port of close-plan.sh and close-plan.ps1 (plan
261016 Phase 15). Same flags as the .sh, same stdout lines and exit codes,
except these decided changes:
  - A git command the move needs that fails (`git diff --quiet` erroring,
    `git add`, `git mv`, or no git binary) exits 2 with
    "guard did not run: ..." on stderr, where the twins passed git's own code
    (usually 128) through. A `git mv -n` preflight runs before anything is
    staged; when `git mv` still fails after the unstaged edit was staged, the
    source's prior index entry is put back (`git update-index --cacheinfo`);
    and a plans/done/ directory this run created is removed again on
    failure, so a failure never leaves a partial move. If even that index
    restore fails, the message says so and names the Recovery step below.
  - A destination path prints in one canonical form: forward slashes; on
    Windows the resolved absolute path ("C:/...", upper-case drive letter,
    the on-disk case and long names of every existing directory, no "\\\\?\\"
    prefix), so a DRY_RUN line equals the later MOVED line for the same
    input; never the MSYS "/c/..." form. An MSYS "/c/..." --dest or
    --project-root on Windows is read as "C:/...".
  - Path prefix and repository-identity comparisons are case-insensitive on
    Windows, and a source repository whose identity git cannot report stops
    the run (exit 2) instead of comparing two empty identities as equal.
  - Refusals the twins lacked: a destination inside the source repository's
    git directory or common git directory (exit 4); a destination in another
    linked worktree of the source's repository (exit 5, dry run included);
    an untracked source under plans/ without --dest (exit 4); a merge,
    rebase, cherry-pick or revert in progress in the source's worktree
    (exit 4).
Runs only under the playbook venv (<config repo>/.venv-agent-playbook); any
other interpreter exits 2 ("guard did not run: venv missing"). Stdlib only,
Python 3.8+.

Usage:
  close-plan.py [--dry-run] [--dest <full-dest-path>] [--name <UPPER>]
                [--project-root <dir>] <source>
  close-plan.py --selftest

Flags:
  --dry-run                Preview only; print DRY_RUN<TAB><dest> and exit 0.
  --dest <full-dest>       Override destination entirely (used by Step 6 to
                           lock the timestamp captured during Step 4's
                           dry-run, and by governance overrides). A relative
                           value resolves against the effective project root,
                           never the CWD. On Windows pass a drive-letter path
                           ("C:/..." or "C:\\..."); an MSYS "/c/..." path is
                           translated to "C:/...".
  --name <UPPER>           Override only the UPPER_NAME portion (A-Z, 0-9 and
                           _ only, else exit 4); the date prefix is still
                           derived from current time.
                           /qclose's wired flow uses only --dry-run and
                           --dest; --name is kept for ad-hoc CLI use (a
                           manual rename). --dest wins over --name.
  --project-root <dir>     OPTIONAL override of the root used to locate
                           plans/. The default (see "Root derivation" below)
                           already handles a workspace store and a monorepo
                           sub-directory, so this flag is rarely needed.
                           Pass an ABSOLUTE path: a relative value resolves
                           against the script's CWD, which for a store-backed
                           plan is normally a DIFFERENT repository, and the
                           script then exits 4. NOTE: this flag means
                           something DIFFERENT in qvalidate.py, where it names
                           the CODE root for git operations. Here it names
                           "where plans/ lives". That divergence is deliberate
                           -- the two scripts answer different questions -- so
                           the names are documented apart, not unified.
  --selftest               Run the fixture selftest (fixtures/ next to this
                           script) and print a one-line summary.
  --help, -h               Print this header and exit 0.
  <source>                 Path to the project file (absolute or relative to
                           cwd; resolved against the cwd's git root if not
                           found).

Path resolution (three-tier):
  1. Resolve plans/ relative to --project-root (or, with no flag, the
     source's own plans/ parent -- see "Root derivation" below).
  2. If source is not under that plans/, accept it if the filename matches
     the active-plan pattern (YYMMDD_UPPER_CASE.md) AND is git-tracked.
  3. If --dest is supplied, skip all source-location validation.

Root derivation:
  A provisional CWD-derived root exists only so a relative <source> that is
  not found under the CWD can still be resolved. The REAL repo root is then
  derived from the resolved SOURCE path, before any git operation, so
  `git mv` runs in the repository the plan actually lives in -- the case a
  workspace store creates (shared/skills/qdream/memory-rules.md § Workspace
  Store).

  The DESTINATION root (where plans/done/ is built) is derived from the
  SOURCE too, but NOT from its repo root: when the source's immediate parent
  directory is literally named `plans`, the destination root is that
  directory's parent. So a store plan at <store>/plans/<file>.md (in the
  store repo) archives to <store>/plans/done/ -- INSIDE the store -- with no
  flag at all, and a monorepo plan at <repo>/<sub>/plans/<file>.md archives
  to <repo>/<sub>/plans/done/. Only when the source is not directly under a
  `plans/` directory does the destination root fall back to the source's
  repo root.

  Cross-repository archival is refused with exit 5. The check runs on EVERY
  invocation -- against --project-root, against --dest, and against the
  derived default alike -- by comparing the repository identity (the
  absolute common git dir) AND the worktree root (`--show-toplevel`) of the
  destination's nearest EXISTING ancestor directory against the source's, so
  another linked worktree of the same repository is refused too. A
  destination inside the source's git directory or common git directory is
  refused first, with exit 4 (it names no work-tree path at all). These
  checks run BEFORE any directory is created, so a refused destination
  leaves nothing littered in the foreign repository.

Output schema:
  DRY_RUN<TAB><absolute-destination-path>   (--dry-run mode)
  MOVED<TAB><absolute-destination-path>     (live mode, success)

Exit codes:
  0  Success (or dry-run preview).
  2  The SOURCE's directory is not in a git repo; or the guard did not run
     (venv missing, git missing, or a git command the move needs failed --
     nothing was moved).
  3  Destination already exists (same-minute collision; re-invoke or
     pass an explicit --dest).
  4  Source OR flag validation failure: a non-existent / wrong-location /
     malformed-name / untracked source without a --dest override, a missing
     or malformed flag argument, a --project-root naming a directory that
     does not exist (remember a RELATIVE --project-root resolves against the
     CWD), a destination inside the source repository's git directory or
     common git directory, or a merge / rebase / cherry-pick / revert in
     progress in the source's worktree.
  5  The DESTINATION is in a DIFFERENT repository than the source, or in a
     different linked worktree of it -- whether it came from --project-root,
     from --dest, or from the derived default.

Recovery: the script restores the index itself on a `git mv` failure. Only
when its message says that restore failed too, run `git status` and
`git restore --staged <files>` to undo the half-staged state, then re-invoke
this script.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

NAME = "close-plan.py"
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
WIN = os.name == "nt"
RE_PLAN = re.compile(r"^[0-9]{6}_[A-Z0-9_]+\.md$", re.ASCII)
RE_PREFIX = re.compile(r"^[0-9]{6}_", re.ASCII)
RE_NAME = re.compile(r"^[A-Z0-9_]+$", re.ASCII)  # --name: the UPPER_NAME part only, never a path
RE_REPO_ID_SHAPE = re.compile(r"^(/|[A-Za-z]:)", re.ASCII)
RE_ABS_DEST = re.compile(r"^([A-Za-z]:[\\/]|[\\/])" if WIN else r"^/", re.ASCII)
WARN_PATH_FORMAT = ("close-plan: WARN: git lacks 'rev-parse --path-format' (needs git >= 2.31); fell back to "
                    "--show-toplevel for the same-repo test, which cannot tell two linked worktrees of one "
                    "repository apart")


# --- venv guard stub: same text as the qdream scripts', except the one line naming where venv-selfcheck.py is ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "qdream", "scripts", "venv-selfcheck.py")
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


class Stop(Exception):
    """End the run: args = (exit code, stderr lines without the `close-plan.py: ` prefix)."""


def _clock():
    """The archive name's YYMMDD-HHMM, from the local clock. The selftest replaces this function."""
    return time.strftime("%y%m%d-%H%M", time.localtime())


def _git(root, *args):
    """-> (exit code, stdout text, stderr text) of `git -c core.quotepath=off -C <root> <args>`. A missing
    git binary stops the run: no call site can stand in for it."""
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", root] + list(args), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise Stop(2, ["guard did not run: git not found"])
    except OSError as exc:
        raise Stop(2, ["guard did not run: git could not start: %s" % exc])
    return r.returncode, r.stdout.decode("utf-8", "surrogateescape"), r.stderr.decode("utf-8", "surrogateescape")


def _tail(err):
    """git's reason: the last `fatal:` or `error:` line (a `hint:` often follows it), else the last line."""
    lines = [l.strip() for l in err.replace("\r", "\n").split("\n") if l.strip()]
    if not lines:
        return "no message"
    marked = [l for l in lines if l.startswith(("fatal:", "error:"))]
    return (marked or lines)[-1][:300]


def _fwd(p):
    """A path in the printed form: forward slashes."""
    return p.replace("\\", "/") if WIN else p


RE_MSYS = re.compile(r"^/([A-Za-z])(/|$)", re.ASCII)


def _from_msys(p):
    """On Windows, an MSYS "/c/..." path -> "C:/..."; anything else unchanged."""
    m = RE_MSYS.match(p) if WIN else None
    return (m.group(1).upper() + ":/" + p[m.end():]) if m else p


def _strip_verbatim(p):
    r"""Drop a Windows "\\?\" (or "\\?\UNC\") prefix, in either slash form."""
    for pre, rep in (("\\\\?\\UNC\\", "\\\\"), ("//?/UNC/", "//"), ("\\\\?\\", ""), ("//?/", "")):
        if p[:len(pre)].upper() == pre.upper():
            return rep + p[len(pre):]
    return p


def _canon(p):
    """The destination in its one printed and used form. On Windows: absolute and normalized, the nearest
    existing directory resolved (os.path.realpath: on-disk case, long names), the not-yet-existing tail kept
    as given, no verbatim prefix, upper-case drive letter, forward slashes. Elsewhere: the path as given."""
    if not WIN:
        return p
    p = os.path.normpath(os.path.abspath(p))
    anchor = _nearest_existing_dir(p)
    if anchor:
        real = os.path.realpath(anchor)
        rest = os.path.relpath(p, anchor) if _key(p) != _key(anchor) else ""
        p = os.path.join(real, rest) if rest and rest != "." else real
    p = _strip_verbatim(p)
    if len(p) > 1 and p[1] == ":":
        p = p[0].upper() + p[1:]
    return _fwd(p)


def _key(p):
    """A path as compared: absolute, and case-folded on Windows (normcase), with forward slashes."""
    return _fwd(os.path.normcase(os.path.abspath(p)))


def _under(path, parent):
    return _key(path).startswith(_key(parent).rstrip("/") + "/")


def _toplevel(d):
    """-> the git work-tree root containing directory d, or '' when d is not in one."""
    rc, out, _err = _git(d, "rev-parse", "--show-toplevel")
    out = out.strip()
    return os.path.normpath(out) if rc == 0 and out else ""


class RepoId(object):
    """repository identity: the absolute common git dir, so two linked worktrees of one repository compare
    equal and two different repositories never do. On git < 2.31, `rev-parse --path-format=absolute` echoes
    the unknown flag and exits 0, so the gate is the SHAPE of the result; anything else falls back to
    --show-toplevel and WARNs once on stderr."""

    def __init__(self, err_lines):
        self.err = err_lines
        self.warned = False

    def __call__(self, d):
        rc, out, _e = _git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
        out = out.strip()
        if rc == 0 and RE_REPO_ID_SHAPE.match(out):
            return _fwd(out)
        rc, out, _e = _git(d, "rev-parse", "--show-toplevel")
        out = out.strip()
        if rc == 0 and out:
            if not self.warned:
                self.warned = True
                self.err.append(WARN_PATH_FORMAT)
            return _fwd(out)
        return ""


def _same_id(a, b):
    """Two repository identities name one repository (case-insensitive on Windows)."""
    return os.path.normcase(a) == os.path.normcase(b)


def _nearest_existing_dir(p):
    """-> the closest existing ancestor directory of p (p itself when it exists), or '' at a fixpoint."""
    d = p
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d or parent == "":
            return ""
        d = parent
    return d


def parse_args(argv):
    """-> options dict, or 'help' / 'selftest'. Mirrors the .sh loop: a value flag takes the next word
    whatever it is; an empty --dest or --project-root counts as absent, an empty --name is refused (exit 4) like
    any other value outside A-Z, 0-9 and _; any other --word is unknown."""
    o = {"dry": False, "dest": "", "name": None, "root": "", "source": ""}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--dry-run":
            o["dry"] = True
        elif a in ("--dest", "--name", "--project-root"):
            if i + 1 >= len(argv):
                raise Stop(4, ["%s requires an argument" % a])
            o[{"--dest": "dest", "--name": "name", "--project-root": "root"}[a]] = argv[i + 1]
            i += 1
        elif a in ("--help", "-h"):
            return "help"
        elif a == "--selftest":
            return "selftest"
        elif a.startswith("--"):
            raise Stop(4, ["unknown flag: %s" % a])
        elif o["source"]:
            raise Stop(4, ["unexpected positional argument: %s (source already set to %s)" % (a, o["source"])])
        else:
            o["source"] = a
        i += 1
    if not o["source"]:
        raise Stop(4, ["source plan path is required",
                       "usage: close-plan.py [--dry-run] [--dest <path>] [--name <UPPER>] [--project-root <dir>] <source>"])
    return o


def archive(o, out, notes):
    """The archive itself. -> 0, or raises Stop. `notes` collects stderr lines printed on any outcome."""
    source = o["source"]
    # --- source resolution: a provisional CWD-derived root, for a relative source only ---
    if os.path.exists(source):
        src = os.path.abspath(source)
    else:
        prov = _toplevel(os.getcwd())
        if prov and os.path.exists(os.path.join(prov, source)):
            src = os.path.abspath(os.path.join(prov, source))
        else:
            raise Stop(4, ["source not found: %s" % source])
    if not os.path.isfile(src):
        raise Stop(4, ["source is not a regular file: %s" % _fwd(src)])
    # One form for the source as for the destination: git reports the real path (a subst drive or a
    # junction resolved), so an unresolved source would fail the tracking check for a tracked file.
    src = _canon(src)
    base = os.path.basename(src)

    # --- git-repo preflight: the root derived from the SOURCE ---
    repo_root = _toplevel(os.path.dirname(src))
    if not repo_root:
        raise Stop(2, ["not in a git repo: %s" % _fwd(src)])
    repo_id = RepoId(notes)
    rc, out_dirs, err = _git(repo_root, "rev-parse", "--git-dir", "--git-common-dir")
    dirs = [l.strip() for l in out_dirs.replace("\r", "").split("\n") if l.strip()]
    if rc != 0 or len(dirs) != 2:
        raise Stop(2, ["guard did not run: git rev-parse --git-dir failed: %s" % _tail(err)])
    git_dir, common_dir = [os.path.abspath(os.path.join(repo_root, x)) for x in dirs]
    # --- an operation in progress: the archival commit would land inside it ---
    for marker, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase or am"),
                         ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert")):
        if os.path.exists(os.path.join(git_dir, marker)):
            raise Stop(4, ["%s is in progress in %s (%s exists); finish or abort it first"
                           % (what, _fwd(repo_root), marker)])

    # --- the destination root: --project-root, else the source's plans/ parent, else its repo root ---
    if o["root"]:
        eff = _from_msys(o["root"])
    elif os.path.basename(os.path.dirname(src)) == "plans":
        eff = os.path.dirname(os.path.dirname(src))
    else:
        eff = repo_root
    if not os.path.isdir(eff):
        raise Stop(4, ["--project-root directory does not exist: %s" % eff])
    eff = os.path.abspath(eff)

    src_id = repo_id(repo_root)
    if not src_id:
        raise Stop(2, ["guard did not run: git could not report the repository of %s" % _fwd(repo_root)])
    if o["root"]:
        dst_id = repo_id(eff)
        if not _same_id(src_id, dst_id):
            raise Stop(5, ["--project-root is in a different repository than the source",
                           "  source repo: %s (%s)" % (src_id, _fwd(src)),
                           "  --project-root repo: %s (%s)" % (dst_id or "<not a git repo>", _fwd(eff))])
        if _key(_toplevel(eff) or eff) != _key(repo_root):
            raise Stop(5, ["--project-root is in a different worktree of the source's repository",
                           "  source worktree: %s" % _fwd(repo_root),
                           "  --project-root worktree: %s" % _fwd(_toplevel(eff) or "<none>")])

    plans_dir = os.path.join(eff, "plans")
    done_dir = os.path.join(plans_dir, "done")
    if _under(src, done_dir):
        raise Stop(4, ["source already lives in plans/done/: %s" % _fwd(src)])
    if _under(src, plans_dir):
        if not o["dest"] and not RE_PLAN.match(base):
            raise Stop(4, ["source name does not match active-plan pattern (YYMMDD_UPPER_CASE.md): %s" % base,
                           "pass --dest <full-dest-path> to override"])
    elif not o["dest"]:
        if not RE_PLAN.match(base):
            raise Stop(4, ["source not under plans/ and name doesn't match active-plan pattern: %s" % base,
                           "pass --dest <full-dest-path> or --project-root <dir> to override"])
    if not o["dest"]:
        rc, _out, _err = _git(repo_root, "ls-files", "--error-unmatch", "--", src)
        if rc != 0:
            raise Stop(4, ["source is not tracked by git: %s" % _fwd(src)])

    # --- destination derivation ---
    if o["dest"]:
        given = _from_msys(o["dest"])
        dest = _fwd(given) if RE_ABS_DEST.match(given) else _fwd(eff) + "/" + _fwd(given)
    elif o["name"] is not None:
        if not RE_NAME.fullmatch(o["name"]):
            raise Stop(4, ["--name must be the UPPER_NAME part only (A-Z, 0-9, _): %s" % o["name"],
                           "pass --dest <full-dest-path> to archive under another path"])
        dest = _fwd(done_dir) + "/" + _clock() + "_" + o["name"] + ".md"
    else:
        dest = _fwd(done_dir) + "/" + _clock() + "_" + RE_PREFIX.sub("", base, count=1)
    dest = _canon(dest)

    # --- the repository's own git directory is never a destination ---
    for gd in (git_dir, common_dir):
        if _key(dest) == _key(gd) or _under(dest, gd):
            raise Stop(4, ["destination is inside the repository's git directory: %s" % dest,
                           "  git directory: %s" % _fwd(gd)])

    # --- destination repository guard: before any directory is created ---
    anchor = _nearest_existing_dir(os.path.dirname(dest))
    dst_id = repo_id(anchor) if anchor else ""
    if not _same_id(src_id, dst_id):
        raise Stop(5, ["destination is in a different repository than the source",
                       "  source repo: %s (%s)" % (src_id, _fwd(src)),
                       "  destination repo: %s (%s)" % (dst_id or "<not a git repo>", dest)])
    dst_top = _toplevel(anchor)
    if _key(dst_top or anchor) != _key(repo_root):
        raise Stop(5, ["destination is in a different worktree of the source's repository",
                       "  source worktree: %s" % _fwd(repo_root),
                       "  destination worktree: %s (%s)" % (_fwd(dst_top) if dst_top else "<none>", dest)])

    if os.path.exists(dest):
        raise Stop(3, ["destination exists: %s" % dest])

    if o["dry"]:
        out.write(("DRY_RUN\t%s\n" % dest).encode("utf-8", "surrogateescape"))
        return 0

    # --- live mode: every check that can fail runs before anything is staged or moved ---
    created = []
    d = os.path.dirname(dest)
    while d and not os.path.isdir(d):
        created.append(d)
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd

    entry = []  # the source's index entry before `git add` staged the edit: (mode, sha, path from the root)

    def fail(what, err):
        lines = []
        if entry:  # put the index back the way it was, so "nothing changed" holds after a staged edit too
            mode, sha, path = entry
            rc2, _o2, err2 = _git(repo_root, "update-index", "--cacheinfo", "%s,%s,%s" % (mode, sha, path))
            if rc2 != 0:
                lines.append("the edit of %s stays staged: git update-index failed: %s; run "
                             "`git restore --staged -- %s` (see Recovery in --help)" % (_fwd(src), _tail(err2), path))
        for c in created:  # innermost first; only directories this run made, and only while empty
            try:
                os.rmdir(c)
            except OSError:
                break
        raise Stop(2, ["guard did not run: %s failed: %s; nothing moved" % (what, _tail(err))] + lines)

    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    except OSError as exc:
        fail("creating %s" % _fwd(os.path.dirname(dest)), str(exc))
    # `git mv` moves the index entry, so unstaged edits to the source (Step 6 edits the file in place first)
    # would miss the archival commit: stage them, keeping the rename and the content update atomic.
    rc, _o, err = _git(repo_root, "diff", "--quiet", "--", src)
    if rc not in (0, 1):
        fail("git diff", err)
    dirty = rc == 1
    rc, _o, err = _git(repo_root, "mv", "-n", "--", src, dest)
    if rc != 0:
        fail("git mv", err)
    if dirty:
        rc, ls, err = _git(repo_root, "ls-files", "-s", "-z", "--", src)
        meta, _tab, path = ls.split("\0")[0].partition("\t")
        if rc != 0 or len(meta.split()) != 3 or not path:
            fail("git ls-files -s", err)
        entry[:] = [meta.split()[0], meta.split()[1], path]
        rc, _o, err = _git(repo_root, "add", "--", src)
        if rc != 0:
            fail("git add", err)
    rc, _o, err = _git(repo_root, "mv", "--", src, dest)
    if rc != 0:
        fail("git mv", err)
    out.write(("MOVED\t%s\n" % dest).encode("utf-8", "surrogateescape"))
    return 0


def run(argv, out, err):
    """-> exit code. `out`/`err` are binary streams."""
    notes = []

    def flush_notes():
        for n in notes:
            err.write((n + "\n").encode("utf-8", "surrogateescape"))
    try:
        o = parse_args(argv)
        if o == "help":
            out.write((__doc__.strip("\n") + "\n").encode("utf-8"))
            return 0
        if o == "selftest":
            return selftest()
        rc = archive(o, out, notes)
        flush_notes()
        return rc
    except Stop as exc:
        flush_notes()
        for line in exc.args[1]:
            err.write(("%s: %s\n" % (NAME, line)).encode("utf-8", "surrogateescape"))
        return exc.args[0]
    except Exception as exc:
        flush_notes()
        err.write(("%s: guard did not run: unexpected error: %s: %s\n" % (NAME, type(exc).__name__, exc))
                  .encode("utf-8", "surrogateescape"))
        return 2
    finally:
        out.flush()
        err.flush()


def main(argv=None):
    _require_venv(__file__)
    argv = sys.argv[1:] if argv is None else argv
    return run(argv, sys.stdout.buffer, sys.stderr.buffer)


# ---------------------------------------------------------------------------
# Selftest. The fixture plans live in fixtures/ as *.md.in (so verify-links and verify-citations never
# scan them); a case copies one to its place in a scratch git layout and drops the .in. Cases run in
# process with a fixed clock, so a derived destination is exact; a few run as a subprocess.
# ---------------------------------------------------------------------------

GIT_ID = ["-c", "user.name=close-plan-selftest", "-c", "user.email=selftest@example.invalid",
          "-c", "commit.gpgsign=false", "-c", "core.hooksPath=.cp-no-hooks", "-c", "core.autocrlf=false"]
STAMP = "261231-2359"
PLAN = "260101_CP_FIXTURE.md"
LOWER = "260101_lower_name.md"


def _sg(d, *args):
    r = subprocess.run(["git"] + GIT_ID + ["-C", d] + list(args), stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("git %s in %s: %s" % (" ".join(args), d, r.stderr.decode("utf-8", "replace")))
    return r.stdout.decode("utf-8", "replace")


def _init(d):
    os.makedirs(d, exist_ok=True)
    _sg(d, "init", "-q", "-b", "main")
    return d


def _place(fixture, dst, repo=None, name=None):
    """Copy fixtures/<fixture>.in to dst/<name or fixture>; with repo, stage and commit it. -> the path."""
    os.makedirs(dst, exist_ok=True)
    path = os.path.join(dst, name or fixture)
    shutil.copyfile(os.path.join(FIXTURES, fixture + ".in"), path)
    if repo:
        _sg(repo, "add", "--", path)
        _sg(repo, "commit", "-q", "-m", "add %s" % os.path.basename(path))
    return path


def _inv(argv, cwd):
    """Run in process with the fixed clock. -> (exit code, stdout text, stderr text, stdout bytes)."""
    out, err = io.BytesIO(), io.BytesIO()
    here = os.getcwd()
    os.chdir(cwd)
    try:
        rc = run(argv, out, err)
    finally:
        os.chdir(here)
    return rc, out.getvalue().decode("utf-8"), err.getvalue().decode("utf-8"), out.getvalue()


def selftest():
    fails, checks, skips = [], [0], []

    def chk(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (name, (": " + detail) if detail else ""))

    def case(name, argv, cwd, rc, stdout=None, stderr_has=None):
        got = _inv(argv, cwd)
        chk("%s: exit %d" % (name, rc), got[0] == rc, "exit %s, stdout %r, stderr %r" % got[:3])
        chk("%s: LF-only stdout" % name, b"\r" not in got[3])
        if stdout is not None:
            chk("%s: stdout" % name, got[1] == stdout, "%r != %r" % (got[1], stdout))
        if rc != 0:
            chk("%s: no stdout on a refusal" % name, got[1] == "", repr(got[1]))
            chk("%s: stderr names the script" % name, got[2].startswith(NAME + ": "), repr(got[2]))
        if stderr_has is not None:
            chk("%s: stderr says %r" % (name, stderr_has), stderr_has in got[2], repr(got[2]))
        return got

    def status(repo):
        return _sg(repo, "status", "--porcelain").replace("\r", "")

    saved_clock = globals()["_clock"]
    globals()["_clock"] = lambda: STAMP
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="close-plan-selftest-"))
    try:
        F = _fwd
        # --- a plan in its own repo: dry run, foreign cwd, relative --dest, live move with an unstaged edit ---
        own = _init(os.path.join(tmp, "own"))
        src = _place(PLAN, os.path.join(own, "plans"), own)
        want = F(os.path.join(own, "plans", "done", STAMP + "_CP_FIXTURE.md"))
        case("own repo dry run", ["--dry-run", "plans/" + PLAN], own, 0, "DRY_RUN\t%s\n" % want)
        chk("own repo dry run: creates nothing", not os.path.exists(os.path.join(own, "plans", "done")))
        case("own repo dry run from a foreign cwd", ["--dry-run", src], tmp, 0, "DRY_RUN\t%s\n" % want)
        case("--name overrides only the UPPER_NAME part", ["--dry-run", "--name", "RENAMED", src], tmp, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(own, "plans", "done", STAMP + "_RENAMED.md")))
        case("--dest wins over --name", ["--dry-run", "--name", "RENAMED", "--dest", "plans/done/D.md", src], tmp, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(own, "plans", "done", "D.md")))
        case("--name without a value", [src, "--name"], tmp, 4, stderr_has="--name requires an argument")
        case("--name with path segments is refused", ["--dry-run", "--name", "X/../../../shared/skills/evil", src], tmp, 4,
             stderr_has="--name must be the UPPER_NAME part only")
        case("--name with a backslash is refused", ["--dry-run", "--name", "A\\B", src], tmp, 4,
             stderr_has="--name must be the UPPER_NAME part only")
        case("--name with a trailing newline is refused", ["--dry-run", "--name", "ABC\n", src], tmp, 4,
             stderr_has="--name must be the UPPER_NAME part only")
        case("--name empty is refused", ["--dry-run", "--name", "", src], tmp, 4,
             stderr_has="--name must be the UPPER_NAME part only")
        case("--name in lower case is refused", ["--dry-run", "--name", "renamed", src], tmp, 4,
             stderr_has="--name must be the UPPER_NAME part only")
        case("own repo dry run, relative source from a sub-directory (provisional root)",
             ["--dry-run", "plans/" + PLAN], os.path.join(own, "plans"), 0, "DRY_RUN\t%s\n" % want)
        case("relative --dest resolves against the derived root", ["--dry-run", "--dest", "plans/done/X.md", src],
             tmp, 0, "DRY_RUN\t%s/plans/done/X.md\n" % F(own))
        with open(src, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("edited before the move\n")
        case("own repo live move", [src], tmp, 0, "MOVED\t%s\n" % want)
        st = status(own)
        chk("own repo live move: a staged rename, nothing unstaged",
            st == "R  plans/%s -> plans/done/%s_CP_FIXTURE.md\n" % (PLAN, STAMP), repr(st))
        chk("own repo live move: the unstaged edit is in the index",
            "edited before the move" in _sg(own, "show", ":plans/done/%s_CP_FIXTURE.md" % STAMP))
        # --- collisions: the derived name (fixed clock) and an explicit --dest ---
        two = _place(PLAN, os.path.join(own, "plans"), own, "260102_CP_TWO.md")
        clash = os.path.join(own, "plans", "done", STAMP + "_CP_TWO.md")
        with open(clash, "w") as fh:
            fh.write("x\n")
        case("same-minute collision (dry run)", ["--dry-run", two], tmp, 3, stderr_has="destination exists")
        case("same-minute collision (live)", [two], tmp, 3, stderr_has="destination exists")
        chk("same-minute collision: the source is not moved", os.path.isfile(two))
        case("an explicit --dest that exists", ["--dest", F(clash), two], tmp, 3)
        # --- a nested repo inside the source's worktree is another repository ---
        nested = _init(os.path.join(own, "nested"))
        case("--dest into a nested repo", ["--dest", F(os.path.join(nested, "plans", "done", "x.md")), two], tmp, 5,
             stderr_has="destination is in a different repository")
        chk("--dest into a nested repo: nothing created there", not os.path.exists(os.path.join(nested, "plans")))

        # --- a store-repo plan, run from the code repo's cwd ---
        stores = _init(os.path.join(tmp, "stores"))
        store = os.path.join(stores, "fixture-abc123")
        ssrc = _place(PLAN, os.path.join(store, "plans"), stores, "261101_CP_STORE.md")
        code = _init(os.path.join(tmp, "code"))
        with open(os.path.join(code, "README.md"), "w") as fh:
            fh.write("code\n")
        _sg(code, "add", "README.md")
        _sg(code, "commit", "-q", "-m", "code")
        swant = F(os.path.join(store, "plans", "done", STAMP + "_CP_STORE.md"))
        case("store plan dry run from the code repo", ["--dry-run", ssrc], code, 0, "DRY_RUN\t%s\n" % swant)
        xdest = F(os.path.join(code, "plans", "done", "x.md"))
        case("store plan --dest into the code repo", ["--dry-run", "--dest", xdest, ssrc], code, 5,
             stderr_has="destination is in a different repository")
        case("store plan --dest into the code repo (live)", ["--dest", xdest, ssrc], code, 5)
        chk("store plan cross-repo --dest: nothing moved, nothing created",
            os.path.isfile(ssrc) and not os.path.exists(os.path.join(code, "plans")) and status(code) == "")
        case("store plan --project-root of the code repo", ["--dry-run", "--project-root", code, ssrc], code, 5,
             stderr_has="--project-root is in a different repository")
        case("store plan live move from the code repo", [ssrc], code, 0, "MOVED\t%s\n" % swant)
        chk("store plan live move: archived inside the store, code repo untouched",
            os.path.isfile(swant) and not os.path.exists(ssrc) and status(code) == ""
            and status(stores) == "R  fixture-abc123/plans/261101_CP_STORE.md -> fixture-abc123/plans/done/%s_CP_STORE.md\n"
            % STAMP, repr(status(stores)))

        # --- a monorepo sub-folder, --project-root absolute and relative, Tier 2 ---
        mono = _init(os.path.join(tmp, "mono"))
        msrc = _place(PLAN, os.path.join(mono, "sub", "plans"), mono, "260101_CP_SUB.md")
        case("monorepo sub-folder plan", ["--dry-run", msrc], tmp, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(mono, "sub", "plans", "done", STAMP + "_CP_SUB.md")))
        case("--project-root absolute (the repo root, Tier 2)", ["--dry-run", "--project-root", mono, msrc], tmp, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(mono, "plans", "done", STAMP + "_CP_SUB.md")))
        case("--project-root relative to the cwd", ["--dry-run", "--project-root", "sub", msrc], mono, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(mono, "sub", "plans", "done", STAMP + "_CP_SUB.md")))
        case("--project-root relative, missing", ["--dry-run", "--project-root", "sub", msrc], tmp, 4,
             stderr_has="--project-root directory does not exist: sub")
        dsrc = _place(PLAN, os.path.join(mono, "docs"), mono, "260101_CP_DOC.md")
        case("Tier 2: a tracked plan outside plans/", ["--dry-run", dsrc], tmp, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(mono, "plans", "done", STAMP + "_CP_DOC.md")))
        usrc = _place(PLAN, os.path.join(mono, "docs"), None, "260101_CP_UNTRACKED.md")
        case("Tier 2: an untracked plan outside plans/", ["--dry-run", usrc], tmp, 4, stderr_has="not tracked by git")
        case("Tier 3: --dest skips the location checks", ["--dry-run", "--dest", "plans/done/U.md", usrc], tmp, 0,
             "DRY_RUN\t%s/plans/done/U.md\n" % F(mono))

        # --- non-plan inputs ---
        lsrc = _place(LOWER, os.path.join(mono, "sub", "plans"), mono)
        case("a malformed name under plans/", ["--dry-run", lsrc], tmp, 4, stderr_has="does not match active-plan pattern")
        case("a malformed name with --dest", ["--dry-run", "--dest", "plans/done/L.md", lsrc], tmp, 0)
        nsrc = _place(PLAN, os.path.join(mono, "docs"), mono, "notes.md")
        case("a non-plan name outside plans/", ["--dry-run", nsrc], tmp, 4, stderr_has="doesn't match active-plan pattern")
        asrc = _place(PLAN, os.path.join(mono, "plans", "done"), mono, "260101_CP_OLD.md")
        case("a source already in plans/done/", ["--dry-run", asrc], tmp, 4, stderr_has="already lives in plans/done/")
        case("a missing source", ["--dry-run", os.path.join(mono, "nope.md")], tmp, 4, stderr_has="source not found")
        case("a directory as source", ["--dry-run", os.path.join(mono, "sub")], tmp, 4, stderr_has="not a regular file")
        case("no source", ["--dry-run"], tmp, 4, stderr_has="source plan path is required")
        case("an unknown flag", ["--bogus", "X", msrc], tmp, 4, stderr_has="unknown flag: --bogus")
        case("--dest without a value", [msrc, "--dest"], tmp, 4, stderr_has="--dest requires an argument")
        case("two positionals", [msrc, msrc], tmp, 4, stderr_has="unexpected positional argument")
        nogit = os.path.join(tmp, "nogit")
        _place(PLAN, os.path.join(nogit, "plans"), None, "260101_NOGIT.md")
        case("a source outside any git repo", ["--dry-run", "plans/260101_NOGIT.md"], nogit, 2,
             stderr_has="not in a git repo")

        # --- the repository's own git directory is never a destination (exit 4, nothing moved) ---
        case("--dest inside .git/", ["--dry-run", "--dest", F(os.path.join(own, ".git", "x.md")), two], tmp, 4,
             stderr_has="destination is inside the repository's git directory")
        case("--dest .git/hooks/pre-commit, relative, live", ["--dest", ".git/hooks/pre-commit", two], tmp, 4,
             stderr_has="destination is inside the repository's git directory")
        chk("--dest into .git/: nothing moved", os.path.isfile(two)
            and not os.path.exists(os.path.join(own, ".git", "hooks", "pre-commit")))
        # --- a linked worktree shares the common git dir but is another worktree (exit 5, dry run too) ---
        wt = os.path.join(tmp, "own-wt")
        _sg(own, "worktree", "add", "-q", "-b", "wt", wt)
        wtwo = os.path.join(wt, "plans", "260102_CP_TWO.md")
        case("--dest into another linked worktree (dry run)",
             ["--dry-run", "--dest", F(os.path.join(wt, "plans", "done", "x.md")), two], tmp, 5,
             stderr_has="destination is in a different worktree")
        case("--project-root in another linked worktree", ["--dry-run", "--project-root", wt, two], tmp, 5,
             stderr_has="--project-root is in a different worktree")
        case("a linked-worktree plan, --dest into the common git dir",
             ["--dry-run", "--dest", F(os.path.join(own, ".git", "y.md")), wtwo], tmp, 4,
             stderr_has="destination is inside the repository's git directory")
        case("a linked-worktree plan, dry run", ["--dry-run", wtwo], tmp, 0,
             "DRY_RUN\t%s\n" % F(os.path.join(wt, "plans", "done", STAMP + "_CP_TWO.md")))
        # --- an operation in progress in the source's worktree (exit 4, dry run too) ---
        for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            mp = os.path.join(own, ".git", marker)
            if marker.startswith("rebase"):
                os.makedirs(mp)
            else:
                with open(mp, "w") as fh:
                    fh.write("0" * 40 + "\n")
            case("%s present" % marker, ["--dry-run", two], tmp, 4, stderr_has="in progress in")
            if marker == "MERGE_HEAD":
                chk("%s in progress (stderr names it)" % marker,
                    "(MERGE_HEAD exists)" in _inv(["--dry-run", two], tmp)[2])
                case("a merge in the main worktree does not block a linked worktree", ["--dry-run", wtwo], tmp, 0)
            (shutil.rmtree if os.path.isdir(mp) else os.remove)(mp)
        # --- an untracked plan under plans/ (exit 4, before any git mv) ---
        new = _place(PLAN, os.path.join(own, "plans"), None, "260103_CP_NEW.md")
        case("an untracked plan under plans/ (dry run)", ["--dry-run", new], tmp, 4, stderr_has="source is not tracked by git")
        case("an untracked plan under plans/ (live)", [new], tmp, 4, stderr_has="source is not tracked by git")
        os.remove(new)
        # --- Windows: case-insensitive keys and identities; one canonical destination form; MSYS /c/ ---
        if WIN:
            chk("_key folds case and slashes", _key("C:/Ab/cD") == _key("c:\\aB\\Cd"))
            chk("_same_id folds case", _same_id("C:/Repo/.git", "c:/rEPO/.GIT"))
            case("--project-root and source differing only in case",
                 ["--dry-run", "--project-root", own.swapcase(), "--dest", "plans/done/K.md", two.swapcase()], tmp, 0,
                 "DRY_RUN\t%s/plans/done/K.md\n" % F(own))
            drv, rest = os.path.splitdrive(own)
            case("an MSYS /c/ --dest", ["--dry-run", "--dest", "/" + drv[0].lower() + F(rest) + "/plans/done/M.md", two],
                 tmp, 0, "DRY_RUN\t%s/plans/done/M.md\n" % F(own))
            three = _place(PLAN, os.path.join(own, "plans"), own, "260104_CP_THREE.md")
            canon = F(own) + "/plans/done/C.md"
            forms = [drv.lower() + rest.swapcase() + "\\plans\\DONE\\C.md", "\\\\?\\" + own + "\\plans\\done\\C.md",
                     F(own) + "/plans/x/../done//C.md"]
            for form in forms:
                case("one canonical destination for %r" % form, ["--dry-run", "--dest", form, three], tmp, 0,
                     "DRY_RUN\t%s\n" % canon)
            case("the MOVED line equals the DRY_RUN line", ["--dest", forms[0], three], tmp, 0, "MOVED\t%s\n" % canon)
        else:
            skips.append("Windows path cases: not on Windows")

        # --- a source repository whose identity git cannot report; an unexpected exception ---
        real_call = RepoId.__call__
        RepoId.__call__ = lambda self, d: ""
        try:
            case("an empty source identity stops the run", ["--dry-run", msrc], tmp, 2,
                 stderr_has="guard did not run: git could not report the repository")
        finally:
            RepoId.__call__ = real_call
        real_git = globals()["_git"]

        def boom(root, *args):
            raise ValueError("injected")
        globals()["_git"] = boom
        try:
            case("an unexpected exception exits 2", ["--dry-run", msrc], tmp, 2,
                 stderr_has="guard did not run: unexpected error: ValueError: injected")
        finally:
            globals()["_git"] = real_git

        # --- a failing git command: exit 2, nothing moved (in process) ---
        real_git = globals()["_git"]
        for label, hit in (("git mv", lambda a: a[0] == "mv" and "-n" not in a),
                           ("git mv -n preflight", lambda a: a[:2] == ("mv", "-n")),
                           ("git diff", lambda a: a[0] == "diff"),
                           ("git add", lambda a: a[0] == "add")):
            fsrc = os.path.join(mono, "sub", "plans", "260101_CP_SUB.md")
            with open(fsrc, "a") as fh:
                fh.write("dirty\n")
            before = status(mono)

            def fake(root, *args, _hit=hit):
                if _hit(args):
                    return 128, "", "error: x\nfatal: injected\nhint: a hint after the reason\n"
                return real_git(root, *args)
            globals()["_git"] = fake
            try:
                got = _inv([fsrc], tmp)
            finally:
                globals()["_git"] = real_git
            chk("an injected failing %s exits 2 with the reason" % label, got[0] == 2 and got[1] == ""
                and "guard did not run: git" in got[2] and "fatal: injected; nothing moved" in got[2], repr(got[:3]))
            chk("an injected failing %s moves nothing" % label, os.path.isfile(fsrc)
                and not os.path.exists(os.path.join(mono, "sub", "plans", "done")), repr(os.listdir(os.path.dirname(fsrc))))
            chk("an injected failing %s leaves the index as it was" % label, status(mono) == before, repr(status(mono)))
            _sg(mono, "checkout", "--", fsrc)
            _sg(mono, "restore", "--staged", "--", fsrc)
            _sg(mono, "checkout", "--", fsrc)

        # --- git mv fails after the edit was staged AND the index restore fails: the message says so ---
        fsrc = os.path.join(mono, "sub", "plans", "260101_CP_SUB.md")
        with open(fsrc, "a") as fh:
            fh.write("dirty\n")

        def fake2(root, *args):
            if (args[0] == "mv" and "-n" not in args) or args[0] == "update-index":
                return 128, "", "fatal: injected %s\n" % args[0]
            return real_git(root, *args)
        globals()["_git"] = fake2
        try:
            got = _inv([fsrc], tmp)
        finally:
            globals()["_git"] = real_git
        chk("a failed index restore is reported", got[0] == 2 and "fatal: injected mv; nothing moved" in got[2]
            and "stays staged: git update-index failed: fatal: injected update-index" in got[2]
            and "git restore --staged" in got[2], repr(got[:3]))
        _sg(mono, "restore", "--staged", "--", fsrc)
        _sg(mono, "checkout", "--", fsrc)

        def no_git(root, *args):
            raise Stop(2, ["guard did not run: git not found"])
        globals()["_git"] = no_git
        try:
            got = _inv(["--dry-run", msrc], tmp)
        finally:
            globals()["_git"] = real_git
        chk("no git binary exits 2", got[0] == 2 and got[2] == NAME + ": guard did not run: git not found\n", repr(got[:3]))

        # --- as a subprocess: --help, the real clock, the venv guard ---
        def sub(argv, cwd):
            r = subprocess.run([sys.executable, "-I", "-B", os.path.realpath(__file__)] + argv, cwd=cwd,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            return r.returncode, r.stdout, r.stderr
        rc, out, err = sub(["--help"], tmp)
        chk("--help prints the header", rc == 0 and out.startswith(b"close-plan.py -- archive") and b"--selftest" in out
            and b"\r" not in out, "%s %r" % (rc, out[:80]))
        rc, out, err = sub(["--dry-run", msrc], tmp)
        chk("the real clock stamps YYMMDD-HHMM", rc == 0 and re.match(
            r"^DRY_RUN\t.*/sub/plans/done/[0-9]{6}-[0-9]{4}_CP_SUB\.md\n$", out.decode("utf-8")) is not None,
            "%s %r %r" % (rc, out, err))
        other_py = getattr(sys, "_base_executable", None)
        if other_py and os.path.normcase(os.path.realpath(other_py)) != os.path.normcase(os.path.realpath(sys.executable)):
            r = subprocess.run([other_py, "-I", "-B", os.path.realpath(__file__), "--dry-run", msrc],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            chk("another interpreter exits 2 with the venv message", r.returncode == 2 and r.stdout == b""
                and b"guard did not run: venv missing" in r.stderr, "%s %r" % (r.returncode, r.stderr[:200]))
        else:
            skips.append("venv guard: no interpreter outside the venv to try")
    except Exception as exc:
        chk("selftest ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        globals()["_clock"] = saved_clock
        shutil.rmtree(tmp, ignore_errors=True)
    for s in skips:
        print("SKIP: %s" % s)
    for f in fails:
        print("FAIL: %s" % f)
    print("close-plan selftest: %d failure(s), %d check(s), %d skipped" % (len(fails), checks[0], len(skips)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
