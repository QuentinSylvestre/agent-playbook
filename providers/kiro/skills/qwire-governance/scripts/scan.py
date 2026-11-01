#!/usr/bin/env python3
"""scan.py -- enumerate AGENTS.md/CLAUDE.md and nested .kiro/ governance content
for /qwire-governance Step 1. Python port of scan.sh / scan.ps1.

Output: newline-delimited workspace-relative paths, globally sorted (byte order,
as LC_ALL=C sort) and deduplicated across both passes. Forward slashes only, LF
line ends, UTF-8.

Usage:
  scan.py [--help] [--selftest] [<workspace-path>]

  --help          Print this header and exit 0.
  --selftest [--tmpdir DIR]
                  Run the fixture self-test (fixtures/ beside this script);
                  temp workspaces go under DIR (default: the system temp dir).
  <workspace>     Workspace root to scan. Defaults to the current directory.

Exit codes:
  0   Success (output may be empty if nothing matches).
  1   A directory could not be read during the walk (output still printed),
      as `find` reports it; or, with --selftest, a failed check.
  2   Workspace path does not exist or is not a directory; venv guard failed;
      or an unexpected error (one stderr line).

Pass 1 (governance files): respects .gitignore via `git ls-files --cached
--others --exclude-standard` filtered by basename. Falls back to a filesystem
walk with standard prunes when the workspace is not a git work tree. When the
fallback replaces git where git was expected -- `git ls-files` fails, git is
missing or `git rev-parse` fails in a folder holding .git, or git reports no
work tree (run inside a .git directory) -- one stderr note says so, because
the walk does not honour .gitignore; the exit code stays 0. Caveat: in the
in-repo branch the prunes are whatever .gitignore declares -- a tracked or
un-gitignored AGENTS.md inside node_modules/ etc. is emitted by design.

Pass 2 (nested .kiro/): bypasses .gitignore because .kiro/ is commonly
gitignored in user repos. Walks the filesystem with the prunes. The workspace
root's own .kiro/ is excluded -- we wire INTO it, not from it. Steering files
match at any depth under a .kiro/steering/ (.kiro/steering/sub/x.md counts);
skills match only .kiro/skills/<name>/SKILL.md, one level deep.

Prunes: directories named node_modules, .git, dist, build, __pycache__ or
target, or starting with .venv, are not descended (nor are symlinked
directories and junctions), so an unreadable directory inside one is never
read. Symlinked files are not listed by the walk (find -type f).
"""

import fnmatch
import os
import re
import shutil
import subprocess
import sys

PROG = "scan.py"

# Directory prunes. scan.sh filters with find -path '*/node_modules/*' and the
# like; since every such pattern needs a directory segment of that name (or, for
# '*/.venv*/*', a segment starting with .venv), not descending those
# directories gives the same output.
PRUNE_DIRS = frozenset(("node_modules", ".git", "dist", "build", "__pycache__", "target"))
PRUNE_PREFIX = ".venv"
PASS1_NAMES = ("AGENTS.md", "CLAUDE.md")
STEERING_PATTERN = "*/.kiro/steering/*.md"  # find -path: `*` crosses `/`
SKILL_RE = re.compile(r"(^|/)\.kiro/skills/[^/]+/SKILL\.md$")  # one level only
PASS2_ROOT_EXCLUDE = "./.kiro/*"
GIT_NAME_RE = re.compile(rb"(^|/)(AGENTS|CLAUDE)\.md$")
FALLBACK_NOTE = "; Pass 1 used the filesystem walk, which does not honour .gitignore"


# --- venv guard stub: same text as the qdream scripts', except the one line naming where venv-selfcheck.py is ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))))), "shared", "skills", "qdream", "scripts", "venv-selfcheck.py")
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


def _err(msg):
    """One stderr line, UTF-8 with LF whatever the console code page."""
    sys.stderr.flush()
    sys.stderr.buffer.write((PROG + ": " + msg + "\n").encode("utf-8", "surrogateescape"))
    sys.stderr.buffer.flush()


def _shown(path):
    """A walk path as the output shows it: workspace-relative, '/'-joined."""
    if path is None:
        return "?"
    p = os.fsdecode(path).replace(os.sep, "/")
    return (p[2:] if p.startswith("./") else p) or "."


def _is_junction(path):
    isj = getattr(os.path, "isjunction", None)
    return bool(isj and isj(path))


def _descend(top, d):
    if d in PRUNE_DIRS or d.startswith(PRUNE_PREFIX):
        return False
    return not _is_junction(os.path.join(top, d))


def walk_files(errors):
    """Yield workspace-relative '/'-joined paths of regular files under '.', not
    following symlinked directories (find -P) and not descending pruned ones.
    Unreadable directories are noted in `errors` and skipped, as find does."""
    def onerror(exc):
        errors.append(exc)
    for top, dirs, files in os.walk(".", onerror=onerror, followlinks=False):
        dirs[:] = [d for d in dirs if _descend(top, d)]
        reltop = "" if top == "." else top[2:].replace(os.sep, "/")
        for f in files:
            full = os.path.join(top, f)
            try:
                if os.path.islink(full) or not os.path.isfile(full):
                    continue  # find -type f: regular files only
            except OSError:
                continue
            yield (reltop + "/" + f) if reltop else f


def _enc(text):
    return text.encode("utf-8", "surrogateescape")


def git_pass1():
    """Return (lines, note). lines is the Pass 1 list from git, or None to use
    the filesystem fallback. note is the stderr note for a fallback that
    replaces git where git was expected, else None."""
    has_dotgit = os.path.lexists(".git")
    try:
        rp = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    except OSError:
        return None, ("git not found in a folder with .git" if has_dotgit else None)
    if rp.returncode != 0:
        # "not a git repository" is the ordinary no-repo case; any other failure (safe.directory, a
        # broken GIT_DIR) means git was expected and could not answer, wherever the cwd sits.
        if has_dotgit or b"not a git repository (or any of the parent directories)" not in rp.stderr.lower():
            return None, "git rev-parse failed"
        return None, None
    if rp.stdout.strip() != b"true":
        # Inside a .git directory (or a bare repo): rev-parse succeeds but
        # there is no work tree, so ls-files would fail.
        return None, "git reports no work tree here (inside a .git directory?)"
    try:
        res = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files",
                              "--cached", "--others", "--exclude-standard"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
    except OSError:
        return None, "git ls-files could not run"
    if res.returncode != 0:
        # e.g. a corrupt index. scan.sh keeps whatever ls-files printed (often
        # nothing); falling back keeps Pass 1 from being silently empty.
        return None, "git ls-files failed"
    return [ln for ln in res.stdout.split(b"\n") if ln and GIT_NAME_RE.search(ln)], None


def scan(errors):
    out = set()
    p1, note = git_pass1()
    if note:
        _err("note: " + note + FALLBACK_NOTE)
    fs_files = list(walk_files(errors))
    if p1 is None:
        out.update(_enc(rel) for rel in fs_files if rel.rsplit("/", 1)[-1] in PASS1_NAMES)
    else:
        out.update(p1)
    for rel in fs_files:
        dp = "./" + rel
        if not (fnmatch.fnmatchcase(dp, STEERING_PATTERN) or SKILL_RE.search(rel)):
            continue
        if fnmatch.fnmatchcase(dp, PASS2_ROOT_EXCLUDE):
            continue
        out.add(_enc(rel))
    return sorted(out)


def run(argv):
    ws = argv[0] if argv and argv[0] != "" else os.getcwd()
    if not os.path.isdir(ws):
        _err("workspace not found: " + ws)
        return 2
    os.chdir(ws)
    errors = []
    lines = scan(errors)
    sys.stdout.buffer.write(b"".join(ln + b"\n" for ln in lines))
    sys.stdout.buffer.flush()
    if errors:
        for exc in errors:
            _err("cannot read directory: %s: %s" % (_shown(getattr(exc, "filename", None)),
                                                    getattr(exc, "strerror", None) or exc))
        return 1
    return 0


# ---------------------------------------------------------------------------
# Selftest. Fixture trees live in fixtures/<case>/. Files named *.md.in become
# *.md, path segments named dot-<x> become .<x> and dunder-pycache becomes
# __pycache__ in a temp copy, so the repo's own scans, .gitignore and link
# checks never see them as real files.
# ---------------------------------------------------------------------------

def _materialize(src, dst):
    for top, dirs, files in os.walk(src):
        rel = os.path.relpath(top, src)
        parts = [] if rel == "." else rel.split(os.sep)
        parts = ["__pycache__" if p == "dunder-pycache" else "." + p[4:] if p.startswith("dot-") else p
                 for p in parts]
        dtop = os.path.join(dst, *parts)
        os.makedirs(dtop, exist_ok=True)
        for f in files:
            name = f[:-3] if f.endswith(".md.in") else f
            if name.startswith("dot-"):
                name = "." + name[4:]
            shutil.copyfile(os.path.join(top, f), os.path.join(dtop, name))


def _lines(*paths):
    return b"".join(p.encode("utf-8") + b"\n" for p in paths)


SELFTEST_CASES = [
    # (case, git?, expected stdout)
    ("parity", False, _lines(
        "AGENTS.md", "nested/.kiro/skills/foo/SKILL.md", "nested/.kiro/steering/x.md",
        "sub/AGENTS.md", "wired/.kiro/steering/agents-bridge.md", "wired/AGENTS.md")),
    ("gitrepo", True, _lines(
        "AGENTS.md", "app/.kiro/skills/bar/SKILL.md", "app/.kiro/steering/s.md",
        "app/CLAUDE.md", "node_modules/pkg/AGENTS.md")),
    ("plain", False, _lines(
        "AGENTS.md", "deep/a/b/CLAUDE.md",
        "n/.kiro/skills/foo/SKILL.md", "n/.kiro/steering/sub/deep.md",
        "n/.kiro/steering/top.md", "secret/AGENTS.md")),
    ("empty", False, b""),
    ("nonascii", False, _lines("café/.kiro/steering/été.md", "café/AGENTS.md")),
    ("nonascii", True, _lines("café/.kiro/steering/été.md", "café/AGENTS.md")),
]

# gitrepo with git disabled (GIT_DIR points nowhere): rev-parse fails, so the
# filesystem fallback applies and the gitignored and pruned files flip.
GITREPO_FALLBACK = _lines(
    "AGENTS.md", "app/.kiro/skills/bar/SKILL.md", "app/.kiro/steering/s.md",
    "app/CLAUDE.md", "secret/AGENTS.md")


def _note(text):
    return ("scan.py: note: " + text + FALLBACK_NOTE + "\n").encode("utf-8")


def _in_process(ws, fail_dirs=(), raise_in_scan=None):
    """Run main([ws]) in this process with stdout/stderr captured as bytes.
    The captured streams are cp1252 text layers with CRLF newlines, like a
    redirected Windows console, so a write that bypasses the UTF-8/LF byte
    path shows up. fail_dirs: workspace-relative directories whose listing
    raises PermissionError (an injected unreadable directory). raise_in_scan:
    an exception scan() raises instead of running."""
    import io
    saved = (sys.stdout, sys.stderr, os.scandir, os.getcwd(), globals()["scan"])
    fail = {os.path.normpath(d) for d in fail_dirs}
    real_scandir = os.scandir

    def fake_scandir(path="."):
        if os.path.normpath(os.fsdecode(path)) in fail:
            raise PermissionError(13, "Permission denied", path)
        return real_scandir(path)

    def boom(errors):
        raise raise_in_scan

    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\r\n")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\r\n")
    try:
        sys.stdout, sys.stderr = out, err
        os.scandir = fake_scandir
        if raise_in_scan is not None:
            globals()["scan"] = boom
        rc = main([ws])
        out.flush()
        err.flush()
    finally:
        sys.stdout, sys.stderr, os.scandir, cwd, globals()["scan"] = saved
        os.chdir(cwd)
    return rc, out.buffer.getvalue(), err.buffer.getvalue()


def selftest(argv):
    import tempfile
    here = os.path.dirname(os.path.realpath(__file__))
    fixtures = os.path.join(here, "fixtures")
    tmp_parent = None
    if "--tmpdir" in argv:
        i = argv.index("--tmpdir")
        tmp_parent = argv[i + 1] if i + 1 < len(argv) else None
    have_git = shutil.which("git") is not None
    root = tempfile.mkdtemp(prefix="scan-selftest-", dir=tmp_parent)
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = root  # temp cases never see an enclosing repo
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    me = os.path.realpath(__file__)
    failures, checks, skipped = [], 0, 0

    def scan_in(cwd, args=(), extra_env=None):
        e = dict(env)
        if extra_env:
            e.update(extra_env)
        p = subprocess.run([sys.executable, "-I", me] + list(args), cwd=cwd, env=e,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout, p.stderr

    def check(label, got, want):
        nonlocal checks
        checks += 1
        if got != want:
            failures.append("%s: got %r, want %r" % (label, got, want))

    try:
        for n, (case, use_git, want) in enumerate(SELFTEST_CASES):
            ws = os.path.join(root, "%d-%s" % (n, case))
            _materialize(os.path.join(fixtures, case), ws)
            if use_git:
                if not have_git:
                    skipped += 1
                    continue
                subprocess.run(["git", "init", "-q", ws], env=env, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            label = "%s%s" % (case, " (git)" if use_git else "")
            rc, out, err = scan_in(ws)
            check(label + " stdout", out, want)
            check(label + " exit", rc, 0)
            if case == "parity":
                rc, out, _ = scan_in(root, [ws])
                check("parity via argument stdout", out, want)
                check("parity via argument exit", rc, 0)
            if case == "gitrepo" and use_git:
                rc, out, err = scan_in(ws, extra_env={"GIT_DIR": os.path.join(root, "no-such-git-dir")})
                check("gitrepo rev-parse-failure fallback stdout", out, GITREPO_FALLBACK)
                check("gitrepo rev-parse-failure fallback exit", rc, 0)
                check("gitrepo rev-parse-failure fallback note", err,
                      _note("git rev-parse failed"))
                rc, out, err = scan_in(ws, extra_env={"PATH": ""})
                check("gitrepo git-missing fallback stdout", out, GITREPO_FALLBACK)
                check("gitrepo git-missing fallback exit", rc, 0)
                check("gitrepo git-missing fallback note", err, _note("git not found in a folder with .git"))
                # Inside .git: rev-parse prints "false" with exit 0 (R14).
                with open(os.path.join(ws, ".git", "AGENTS.md"), "wb") as fh:
                    fh.write(b"x\n")
                rc, out, err = scan_in(os.path.join(ws, ".git"))
                check("inside .git fallback stdout", out, _lines("AGENTS.md"))
                check("inside .git fallback exit", rc, 0)
                check("inside .git fallback note", err,
                      _note("git reports no work tree here (inside a .git directory?)"))
                # Corrupt index: rev-parse succeeds, ls-files fails (R3).
                ws3 = os.path.join(root, "corrupt-index")
                _materialize(os.path.join(fixtures, "gitrepo"), ws3)
                subprocess.run(["git", "init", "-q", ws3], env=env, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                with open(os.path.join(ws3, ".git", "index"), "wb") as fh:
                    fh.write(b"garbage")
                rc, out, err = scan_in(ws3)
                check("ls-files-failure fallback stdout", out, GITREPO_FALLBACK)
                check("ls-files-failure fallback exit", rc, 0)
                check("ls-files-failure fallback note", err, _note("git ls-files failed"))
        rc, out, err = scan_in(root, [os.path.join(root, "no-such-workspace")])
        check("missing workspace exit", rc, 2)
        check("missing workspace stdout", out, b"")
        check("missing workspace stderr", err.startswith(b"scan.py: workspace not found: ")
              and err.endswith(b"no-such-workspace\n"), True)

        # Links: a junction, a symlinked directory and a symlinked file are not
        # followed or listed (find -P -type f). Skipped where they cannot be made.
        target = os.path.join(root, "link-target")
        os.makedirs(os.path.join(target, ".kiro", "steering"))
        for name in ("AGENTS.md", os.path.join(".kiro", "steering", "t.md")):
            with open(os.path.join(target, name), "wb") as fh:
                fh.write(b"x\n")

        def mk_junction(ws):
            import _winapi
            _winapi.CreateJunction(target, os.path.join(ws, "j"))

        def mk_dirlink(ws):
            os.symlink(target, os.path.join(ws, "s"), target_is_directory=True)

        def mk_filelink(ws):
            os.mkdir(os.path.join(ws, "f"))
            os.symlink(os.path.join(target, "AGENTS.md"), os.path.join(ws, "f", "AGENTS.md"))

        for label, make in (("junction", mk_junction), ("symlinked directory", mk_dirlink),
                            ("symlinked file", mk_filelink)):
            ws = os.path.join(root, "links-" + label.replace(" ", "-"))
            os.makedirs(ws)
            with open(os.path.join(ws, "AGENTS.md"), "wb") as fh:
                fh.write(b"x\n")
            try:
                make(ws)
            except (OSError, ImportError, AttributeError):
                skipped += 1
                continue
            rc, out, _ = scan_in(ws)
            check(label + " not followed stdout", out, _lines("AGENTS.md"))
            check(label + " not followed exit", rc, 0)

        # In-process cases: injected unreadable directories, unexpected error.
        saved_env = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            ws = os.path.join(root, "walk-error")
            _materialize(os.path.join(fixtures, "parity"), ws)
            os.mkdir(os.path.join(ws, "dé"))
            with open(os.path.join(ws, "dé", "AGENTS.md"), "wb") as fh:
                fh.write(b"x\n")
            rc, out, err = _in_process(ws, fail_dirs=["dé"])
            check("walk error exit", rc, 1)
            check("walk error stdout still printed", out, SELFTEST_CASES[0][2])
            check("walk error stderr (UTF-8, LF, no repr)", err,
                  "scan.py: cannot read directory: dé: Permission denied\n".encode("utf-8"))
            ws = os.path.join(root, "pruned-unreadable")
            _materialize(os.path.join(fixtures, "plain"), ws)
            rc, out, err = _in_process(ws, fail_dirs=["node_modules", os.path.join("node_modules", "x")])
            check("unreadable pruned directory exit", rc, 0)
            check("unreadable pruned directory stdout", out, SELFTEST_CASES[2][2])
            # plain/ holds a fake .git/ directory, so only the fallback note.
            check("unreadable pruned directory stderr", err,
                  _note("git rev-parse failed"))
            rc, out, err = _in_process(ws, raise_in_scan=RuntimeError("boom é"))
            check("unexpected error exit", rc, 2)
            check("unexpected error stdout", out, b"")
            check("unexpected error stderr", err,
                  "scan.py: unexpected error: RuntimeError: boom é\n".encode("utf-8"))
        finally:
            os.environ.clear()
            os.environ.update(saved_env)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for f in failures:
        print("FAIL " + f)
    print("scan selftest: %d failure(s), %d check(s), %d skipped" % (len(failures), checks, skipped))
    return 1 if failures else 0


def main(argv=None):
    _require_venv(__file__)
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--help":
        sys.stdout.write(__doc__)
        return 0
    if argv and argv[0] == "--selftest":
        return selftest(argv[1:])
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:
        _err("unexpected error: %s: %s" % (type(exc).__name__, exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
