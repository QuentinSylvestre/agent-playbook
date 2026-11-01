#!/usr/bin/env python3
"""venv-selfcheck.py -- the qdream scripts' check that they run in the dedicated venv.

plan 261016 Phase 5 (Phase 3 defined the rule). Every qdream script calls require() at the start of
its main(), before it reads or writes anything. A process whose sys.prefix is not the playbook venv
(`<config-repo>/.venv-agent-playbook`, built by setup.ps1) prints

    guard did not run: venv missing -- run setup.ps1

on stderr and exits 2, so a wrong interpreter is loud and never a silent PATH fallback. The venv is
recognised by its fixed folder name and by being a venv (sys.prefix differs from sys.base_prefix), not by
its location: a copy of the scripts (the fixtures' frozen copies, the Kiro deploy) run by the venv's
python passes, and the system Python fails wherever the script sits. The folders are compared by their
resolved real paths, never by spelling, so an 8.3 short name or a link to the venv folder is the same venv.

Not called at import time: the SessionStart hook imports qmemory-eval.py and dream-manifest.py, and the
hook's launcher owns the "venv missing" notice for it (it must always exit 0).

Callers (plan 261016 Phases 5-15): every script in STUB_SCRIPTS below (the qdream scripts) and in
OUTSIDE_STUB_SCRIPTS (the qconfig-sync guards, qvalidate.py, close-plan.py and the Kiro scan.py) carries the
same small stub, `_require_venv(__file__)`, which loads
only this file by path. It is each script's first action as a run (dream-sweep.py, dream-write.py and
dream-check.py call it at module level when run as a script, before they load dream-manifest.py), so a broken
sibling script cannot hide the guard behind a traceback; if this file itself cannot load the stub exits 2 with
"venv self-check unavailable". The check logic lives only here. Never at import: the hook and other callers
import some of those files.

Selftest: `venv-selfcheck.py --selftest` (the venv's python accepted; another interpreter rejected with exit 2
and the message; an 8.3-spelled path to the venv accepted; the stubs of the STUB_SCRIPTS identical, and the stubs of the OUTSIDE_STUB_SCRIPTS identical to them except for the one line that
names the path to venv-selfcheck.py; a broken sibling script or a broken self-check file still yields
exit 2 under another interpreter).

Stdlib only, Python 3.8+.
"""
import os
import subprocess
import sys

VENV_NAME = ".venv-agent-playbook"
MESSAGE = "guard did not run: venv missing — run setup.ps1"


def _real(p):
    """Resolved real path, case-folded on Windows (8.3 names and links expanded when the path exists)."""
    try:
        return os.path.normcase(os.path.realpath(p))
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(p))


def in_venv(prefix=None, base_prefix=None):
    """True when `prefix` is a venv folder named .venv-agent-playbook (the dedicated venv).

    The name is read from the path as given and from its resolved real path, so a short-name spelling of
    the folder passes; the venv test (prefix differs from base_prefix) compares real paths."""
    prefix = sys.prefix if prefix is None else prefix
    base = sys.base_prefix if base_prefix is None else base_prefix
    names = {os.path.basename(os.path.normpath(prefix)).casefold(),
             os.path.basename(_real(prefix)).casefold()}
    return VENV_NAME.casefold() in names and _real(prefix) != _real(base)


def require(script=None):
    """Exit 2 with MESSAGE unless this process runs in the dedicated venv."""
    if in_venv():
        return
    name = os.path.basename(script) if script else os.path.basename(sys.argv[0] or "script")
    text = "%s: %s (running %s, prefix %s)\n" % (name, MESSAGE, sys.executable, sys.prefix)
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except (UnicodeEncodeError, ValueError, OSError):
        try:
            sys.stderr.buffer.write(text.encode("utf-8", errors="replace"))
            sys.stderr.flush()
        except Exception:
            pass
    sys.exit(2)


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _venv_python():
    """The venv's interpreter: this one when it is the venv, else <config repo>/.venv-agent-playbook's."""
    if in_venv():
        return sys.executable
    repo = os.path.realpath(__file__)
    for _ in range(5):  # scripts -> qdream -> skills -> shared -> config repo
        repo = os.path.dirname(repo)
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        cand = os.path.join(repo, VENV_NAME, *rel)
        if os.path.isfile(cand):
            return cand
    return None


def _interp_id(python):
    """The identity of an interpreter path: its folder resolved, its file name as given. On Linux and macOS a
    venv's bin/python is a symlink to the base interpreter, and it is the unresolved path that makes the
    process a venv (pyvenv.cfg is found next to it), so resolving the file itself would make the venv's python
    and the base python one interpreter. On Windows the venv's python.exe is a copy: no difference there."""
    return os.path.join(_real(os.path.dirname(os.path.abspath(python))), os.path.normcase(os.path.basename(python)))


def _venv_prefix(venv_py):
    """The venv folder of the venv interpreter `venv_py` (<venv>/bin/python or <venv>/Scripts/python.exe),
    links in the folder path resolved but never the interpreter file (see _interp_id)."""
    return os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(venv_py))))


def _short_path(path):
    """The 8.3 spelling of an existing path, or None (not Windows, or short names are off)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
        if n and buf.value and buf.value.casefold() != path.casefold():
            return buf.value
    except Exception:
        pass
    return None


def _run(python, args):
    r = subprocess.run([python, "-I", "-B"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=60)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


STUB_SCRIPTS = ("dream-manifest.py", "dream-sweep.py", "dream-write.py", "dream-check.py",
                "qmemory-eval.py", "store-resolver.py", "memory-entries.py", "verify-dream-journal.py", "verify-dream-state.py")
STUB_BEGIN = "# --- venv guard stub:"
STUB_END = "# --- end venv guard stub ---"
# Scripts outside qdream/scripts/ that carry the same stub (path under the skills folder). Their stub
# differs from those above only in the one line that names where venv-selfcheck.py sits.
OUTSIDE_STUB_SCRIPTS = tuple(("qconfig-sync", "scripts", n) for n in (
    "verify-stores.py", "verify-memory.py", "verify-citations.py", "verify-mass.py", "verify-links.py",
    "verify-deployment.py")) + (("qvalidate", "scripts", "qvalidate.py"), ("qclose", "scripts", "close-plan.py"),
    ("..", "..", "providers", "kiro", "skills", "qwire-governance", "scripts", "scan.py"))
PATH_LINE = "path = os.path.join("


def _without_path_line(stub):
    """-> (the stub text without its `path = os.path.join(` lines, how many such lines it had)."""
    kept, dropped = [], 0
    for line in stub.split("\n"):
        if line.strip().startswith(PATH_LINE):
            dropped += 1
        else:
            kept.append(line)
    return "\n".join(kept), dropped


def _stub_of(text):
    i = text.find(STUB_BEGIN)
    j = text.find(STUB_END)
    if i < 0 or j < i:
        return None
    return text[text.index("\n", i) + 1:j]


def _stub_and_broken_sibling_cases(me, other, venv_py):
    """-> failures. (1) The STUB_SCRIPTS stubs are one text (the loader is bootstrap, the check is only here).
    (2) Under an interpreter outside the venv, a script whose sibling (or this file) is broken still exits 2
    with the venv message, never a traceback: the guard is each script's first action."""
    import shutil
    import tempfile
    fails = []
    here = os.path.dirname(me)
    stubs = {}
    for name in STUB_SCRIPTS:
        try:
            with open(os.path.join(here, name), "r", encoding="utf-8") as fh:
                stubs[name] = _stub_of(fh.read())
        except OSError as exc:
            fails.append("cannot read %s for the stub comparison: %s" % (name, exc))
    for name, text in stubs.items():
        if text is None:
            fails.append("%s carries no venv guard stub between its markers" % name)
        elif text != stubs.get(STUB_SCRIPTS[0]):
            fails.append("%s's venv guard stub differs from %s's" % (name, STUB_SCRIPTS[0]))
    reference = stubs.get(STUB_SCRIPTS[0])
    ref_body, ref_paths = _without_path_line(reference) if reference else (None, 0)
    skills = os.path.dirname(os.path.dirname(here))
    for parts in OUTSIDE_STUB_SCRIPTS:
        label = "/".join(parts)
        try:
            with open(os.path.join(skills, *parts), "r", encoding="utf-8") as fh:
                text = _stub_of(fh.read())
        except OSError as exc:
            fails.append("cannot read %s for the stub comparison: %s" % (label, exc))
            continue
        if text is None:
            fails.append("%s carries no venv guard stub between its markers" % label)
            continue
        body, paths = _without_path_line(text)
        if paths != 1 or ref_paths != 1:
            fails.append("%s's stub has %d `%s` line(s) and the reference %d; expected exactly one each"
                         % (label, paths, PATH_LINE, ref_paths))
        elif body != ref_body:
            fails.append("%s's venv guard stub differs from %s's beyond the one line naming venv-selfcheck.py"
                         % (label, STUB_SCRIPTS[0]))
    if not other or _interp_id(other) == _interp_id(venv_py):
        return fails
    siblings = ("store-resolver.py", "qmemory-eval.py", "dream-manifest.py", "memory-entries.py",
                "venv-selfcheck.py")
    tmp = tempfile.mkdtemp(prefix="venv-selfcheck-")
    try:
        for name in STUB_SCRIPTS + ("venv-selfcheck.py",):
            shutil.copyfile(os.path.join(here, name), os.path.join(tmp, name))
        for victim in siblings:
            path = os.path.join(tmp, victim)
            with open(path, "r", encoding="utf-8") as fh:
                original = fh.read()
            # The mutation: the file raises when loaded (the reviewer's repro for the import-order regression).
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(original + "\nraise RuntimeError('planted failure')\n")
            try:
                for script in STUB_SCRIPTS:
                    if script == victim and victim != "venv-selfcheck.py":
                        continue  # the script is the broken file: its own load error is not a sibling's
                    rc, out, err = _run(other, [os.path.join(tmp, script)])
                    want = "venv self-check unavailable" if victim == "venv-selfcheck.py" \
                        else "guard did not run: venv missing"
                    if rc != 2 or want not in err or "Traceback" in err:
                        fails.append("%s with a broken %s under another interpreter: exit %s, stderr %r "
                                     "(expected exit 2 and %r)" % (script, victim, rc, err[:200], want))
            finally:
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(original)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def selftest():
    fails = []
    me = os.path.realpath(__file__)
    venv_py = _venv_python()
    if venv_py is None:
        print("venv-selfcheck selftest: FAIL: no %s next to the config repo" % VENV_NAME)
        return 1
    rc, out, err = _run(venv_py, [me])
    if rc != 0 or "venv ok" not in out:
        fails.append("the venv's python was not accepted: exit %s, stdout %r, stderr %r" % (rc, out[:80], err[:200]))
    # Another interpreter: the base python the venv was made from (never a venv itself).
    other = getattr(sys, "_base_executable", None)
    if not other or _interp_id(other) == _interp_id(venv_py):
        other = os.path.join(sys.base_prefix, "python.exe" if os.name == "nt" else os.path.join("bin", "python3"))
    if _interp_id(other) == _interp_id(venv_py):
        fails.append("selftest has no interpreter outside the venv to try (%s)" % other)
    else:
        rc, out, err = _run(other, [me])
        if rc != 2:
            fails.append("another interpreter (%s) exited %s, expected 2" % (other, rc))
        if "guard did not run: venv missing" not in err:
            fails.append("another interpreter's stderr lacks the message: %r" % err[:200])
    # The prefix of the venv, spelled other ways, is the same venv; a differently named folder is not.
    prefix = _venv_prefix(venv_py)
    if os.path.basename(prefix).casefold() != VENV_NAME.casefold():
        fails.append("the venv prefix %s is not named %s" % (prefix, VENV_NAME))
    base = os.path.realpath(getattr(sys, "base_prefix", sys.prefix))
    short = _short_path(prefix)
    if short is None:
        print("venv-selfcheck selftest: note: no 8.3 spelling available here; the short-name case is not run")
    else:
        if not in_venv(short, base):
            fails.append("the 8.3 spelling %s of the venv was rejected" % short)
        # The check must not be a basename match on the given spelling alone.
        if os.path.basename(short).casefold() == VENV_NAME.casefold():
            fails.append("the 8.3 spelling %s still carries the long name; the case proves nothing" % short)
    if in_venv(os.path.join(os.path.dirname(prefix), "other-venv"), base):
        fails.append("a folder named other-venv was accepted")
    if in_venv(prefix, prefix):
        fails.append("a prefix equal to its base_prefix was accepted")
    fails.extend(_stub_and_broken_sibling_cases(me, other, venv_py))
    for f in fails:
        print("FAIL: %s" % f)
    print("venv-selfcheck selftest: %d failure(s)" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    require(__file__)
    print("venv ok: %s" % sys.prefix)
