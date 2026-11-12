#!/usr/bin/env python3
"""run-checks.py -- run every /qconfig-sync Step 3 guard and selftest, in parallel, and print one table.

Python only, no sh/ps1 twin (like verify-stores.py), so it is outside test-parity.sh's tally. Stdlib only,
Python 3.8+. It may run under any interpreter: every Python check it starts runs under the playbook venv
(<repo>/.venv-agent-playbook, with -I), never a `python` from PATH, and a venv that is missing or fails to
start makes each Python check COULD-NOT-RUN (exit 2), never a pass. A check still running after 15 minutes
is stopped with every process under it (its job object on Windows, its process group elsewhere) and reported
TIMEOUT. It writes only its work folder.

Usage:
  run-checks.py [<repo>] [--work DIR] [--only NAME]... [--jobs N] [--list]

  <repo>       The config repo (default: the repo this script lives in).
  --work DIR   Where each check's output is kept (default: a new folder in the system temp directory).
  --only NAME  Run only the named check (repeatable); `--only verify-deployment` is Step 5's re-verify.
  --jobs N     Worker processes for the dream-write and dream-sweep selftests (default 8).
  --list       Print the check names and exit.
  --ci         CI's exit rule: PARTIAL (a platform-specific case or parity assertion skipped on this OS)
               counts as passing; FAIL, COULD-NOT-RUN and TIMEOUT still fail. The verdicts printed are
               unchanged. A human sync never passes --ci: there PARTIAL stays never-green.

What it runs: the checks SKILL.md Step 3 lists, with the invocations it documents, from the repo root.
Every guard and selftest runs under the venv python. On Windows the launcher test runs first and alone, through `pwsh` (never `powershell`)
(its cases wait on wall-clock timeouts, which a loaded machine could trip), and test-parity.sh runs through
Git Bash, found from git.exe's install folder and accepted only when `uname -o` prints Msys -- the `bash`
on PATH can be WSL's, where every PowerShell assertion SKIPs. Every other check runs in parallel. Exit codes are read from the child process itself, never through a
shell wrapper, so the `2>&1` false-exit trap cannot occur.

Output: one line per check, in a fixed order --
  <name>  <exit>  <seconds>  <flagged>  <verdict>
<flagged> counts output lines (stdout and stderr) carrying a status token the skill says to surface:
FAIL, FAILED, SKIP, SKIPPED, DRIFT, DRIFTED, MISSING, MISSING_PATH, MISSING_ANCHOR, OVER, WARN, WARNING,
INACTIVE, ORPHAN, WRONG_TARGET, NOT_SYMLINK, AMBIGUOUS_SKILL (upper case, as whole words), except a line that starts
with its own pass status (OK, ok, PASS), such as an OK line naming a step ID. A non-zero count on a
passing check is still to be read: SKIP, WARN and ORPHAN lines never change an exit code.
<verdict> is PASS (exit 0), FAIL (exit 1, or any other non-zero exit), COULD-NOT-RUN (exit 2: the check
did not run, which is not the same as finding nothing), TIMEOUT, or PARTIAL: test-parity.sh exited 0 but
printed its "N of M parity assertions SKIPPED" warning, or a selftest exited 0 with a SKIP case line.
PARTIAL is never green. Then the claude-settings check's own lines, whatever its verdict, because that check
always exits 0 and is always reported. Then the work folder, and the wall time.

Exit: 0 when every check is PASS; 1 otherwise; 2 when the runner itself cannot run (unknown --only
name, the repo root not found).
"""
import argparse
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(os.path.realpath(__file__)).parent
DEFAULT_REPO = HERE.parents[3]  # scripts -> qconfig-sync -> skills -> shared -> repo
WINDOWS = os.name == "nt"
TIMEOUT_S = 900
FLAG_RE = re.compile(r"\b(FAIL(ED)?|SKIP(PED)?|DRIFT(ED)?|MISSING(_PATH|_ANCHOR)?|OVER|WARN(ING)?|INACTIVE|ORPHAN"
                     r"|WRONG_TARGET|NOT_SYMLINK|AMBIGUOUS_SKILL)\b")
# A line whose own status is a pass is never flagged, whatever it names: verify-citations prints
# "OK<TAB>GAT-DRIFT<TAB>..." for the stable step ID GAT-DRIFT.
PASS_LINE_RE = re.compile(r"^\s*(OK|ok|PASS)\b")
PARITY_SKIPPED_RE = re.compile(r"^WARNING: \d+ of \d+ parity assertions SKIPPED", re.M)
# A selftest SKIP case: SKIP as a word on a line that is not itself a pass line, wherever it sits
# ("SKIP name -- why", "SKIP: why", "verify-stores selftest: SKIP: git cannot run").
SELFTEST_SKIP_RE = re.compile(r"\bSKIP\b")


def venv_python(repo):
    rel = ("Scripts", "python.exe") if WINDOWS else ("bin", "python")
    return repo.joinpath(".venv-agent-playbook", *rel)


def git_bash():
    """-> (path to Git Bash, None) or (None, why). Never the WSL bash."""
    if not WINDOWS:
        b = shutil.which("bash")
        return (b, None) if b else (None, "no bash on PATH")
    git = shutil.which("git")
    if not git:
        return None, "no git.exe on PATH, so Git Bash cannot be located"
    root = Path(os.path.realpath(git)).parent
    for _ in range(3):  # <root>\cmd\git.exe, <root>\bin\git.exe or <root>\mingw64\bin\git.exe
        for cand in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                try:
                    out = subprocess.run([str(cand), "-c", "uname -o"], capture_output=True, text=True,
                                         timeout=60).stdout.strip()
                except (OSError, subprocess.SubprocessError) as exc:
                    return None, "%s did not start (%s)" % (cand, exc)
                if out == "Msys":
                    return str(cand), None
                return None, "%s reports `uname -o` = %r, not Msys" % (cand, out)
        root = root.parent
    return None, "no bash.exe beside git.exe (%s)" % git


def build_checks(repo, jobs):
    """-> ordered list of (name, argv or None, kind, why-not). kind: guard | selftest | parity | launcher."""
    py = venv_python(repo)
    qs = "shared/skills/qconfig-sync/scripts/"
    qd = "shared/skills/qdream/scripts/"
    pwsh = shutil.which("pwsh") if WINDOWS else None
    checks = []


    venv_why = None
    if not py.is_file():
        venv_why = "venv missing at %s -- run setup.ps1 / setup.sh" % py.parent.parent
    else:
        try:
            if subprocess.run([str(py), "-I", "-c", "pass"], capture_output=True, timeout=120).returncode != 0:
                venv_why = "venv python at %s fails to start -- run setup.ps1 / setup.sh" % py
        except (OSError, subprocess.SubprocessError) as exc:
            venv_why = "venv python at %s fails to start (%s) -- run setup.ps1 / setup.sh" % (py, exc)

    def python(name, kind, *args):
        if venv_why:
            checks.append((name, None, kind, venv_why))
        else:
            checks.append((name, [str(py), "-I", *args], kind, None))

    python("verify-deployment", "guard", qs + "verify-deployment.py")
    python("verify-citations", "guard", qs + "verify-citations.py")
    python("verify-mass", "guard", qs + "verify-mass.py", str(repo))
    python("verify-links", "guard", qs + "verify-links.py")
    python("verify-skills", "guard", qs + "verify-skills.py", str(repo))
    python("verify-client-load", "guard", qs + "verify-client-load.py", str(repo))
    python("leak-scan", "guard", qs + "leak-scan.py", str(repo))
    python("leak-scan-selftest", "selftest", qs + "leak-scan.py", "--selftest")
    python("verify-stores", "guard", qs + "verify-stores.py", str(repo))
    python("verify-memory", "guard", qs + "verify-memory.py", str(repo))
    python("dream-check-budget", "guard", qd + "dream-check.py", "budget", "--repo", str(repo))
    python("dream-manifest-selftest", "selftest", qd + "dream-manifest.py", "--selftest")
    python("dream-check-selftest", "selftest", qd + "dream-check.py", "--selftest")
    python("dream-sweep-selftest", "selftest", qd + "dream-sweep.py", "--selftest", "--jobs", str(jobs))
    python("dream-write-selftest", "selftest", qd + "dream-write.py", "--selftest", "--jobs", str(jobs))
    python("qmemory-eval-selftest", "selftest", qd + "qmemory-eval.py", "--selftest")
    python("store-resolver-selftest", "selftest", qd + "store-resolver.py", "--selftest")
    python("memory-entries-selftest", "selftest", qd + "memory-entries.py", "--selftest")
    python("venv-selfcheck-selftest", "selftest", qd + "venv-selfcheck.py", "--selftest")
    python("verify-stores-selftest", "selftest", qs + "verify-stores.py", "--selftest")
    python("verify-memory-selftest", "selftest", qs + "verify-memory.py", "--selftest")
    python("verify-citations-selftest", "selftest", qs + "verify-citations.py", "--selftest")
    python("verify-mass-selftest", "selftest", qs + "verify-mass.py", "--selftest")
    python("verify-links-selftest", "selftest", qs + "verify-links.py", "--selftest")
    python("verify-skills-selftest", "selftest", qs + "verify-skills.py", "--selftest")
    python("verify-client-load-selftest", "selftest", qs + "verify-client-load.py", "--selftest")
    python("verify-dream-journal-selftest", "selftest", qd + "verify-dream-journal.py", "--selftest")
    python("verify-dream-state-selftest", "selftest", qd + "verify-dream-state.py", "--selftest")
    python("verify-deployment-selftest", "selftest", qs + "verify-deployment.py", "--selftest")
    python("qvalidate-selftest", "selftest", "shared/skills/qvalidate/scripts/qvalidate.py", "--selftest")
    python("close-plan-selftest", "selftest", "shared/skills/qclose/scripts/close-plan.py", "--selftest")
    python("scan-selftest", "selftest", "providers/kiro/skills/qwire-governance/scripts/scan.py", "--selftest")
    python("qmigrate-store-rewrite-selftest", "selftest", "shared/skills/qmigrate-workspace/scripts/test_store_rewrite.py")
    python("memory-load-hook-selftest", "selftest", "providers/claude/memory-load-hook.py", "--selftest")
    python("qdream-phase-hook-selftest", "selftest", "providers/claude/qdream-phase-hook.py", "--selftest")
    python("context-filename-selftest", "selftest", "providers/gemini/context-filename.py", "--selftest")
    python("claude-settings", "guard", "providers/claude/settings-entries.py", "check")
    python("claude-settings-selftest", "selftest", "providers/claude/settings-entries.py", "--selftest")
    python("render-selftest", "selftest", "shared/skills/qvisualize/scripts/render.py", "--selftest")

    if WINDOWS:
        if not pwsh:
            checks.append(("launcher-test", None, "launcher", "pwsh not found"))
        else:
            checks.append(("launcher-test", [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                             "providers/claude/memory-load-hook.launcher-test.ps1"],
                           "launcher", None))

    bash, why = git_bash()
    checks.append(("test-parity", [bash, qs + "test-parity.sh"] if bash else None, "parity", why))
    return checks


def win_job_for(proc):
    """Windows: put a just-started check into a new job object; -> the job handle, or None.

    Every process the check starts stays in the job whatever its Windows parent, so the job reaches
    msys descendants that `taskkill /T` misses: msys emulates fork and exec with fresh Windows
    processes, which breaks the parent chain /T follows (measured: a Git Bash `sleep & sleep & wait`
    left both sleeps running after taskkill /T). A process the check starts before this call is not
    in the job; bash, pwsh and python start nothing that early."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                    "OtherOperationCount", "ReadTransferCount",
                                                    "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: a runner that dies (Ctrl-C, a crash) still takes the check's tree with it
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000
    k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    if k32.AssignProcessToJobObject(job, int(proc._handle)):
        return job
    return None


def close_job(job, terminate):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    if terminate:
        k32.TerminateJobObject(job, 1)
    k32.CloseHandle(job)


def kill_tree(proc, job=None):
    """Stop a timed-out check and every process under it, then reap it."""
    if WINDOWS:
        if job:
            close_job(job, terminate=True)
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        pass


def run_one(repo, work, name, argv):
    """-> (exit code or 'timeout', seconds, combined text)."""
    out_path, err_path = work / (name + ".out"), work / (name + ".err")
    start = time.monotonic()
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        try:
            # Own process group (POSIX) so a timeout can stop the check's whole tree: test-parity's
            # section jobs and the selftests' worker pools outlive a kill of the direct child alone.
            proc = subprocess.Popen(argv, cwd=str(repo), stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                    start_new_session=not WINDOWS)
        except OSError as exc:
            err.write(("run-checks: could not start: %s\n" % exc).encode("utf-8"))
            code = 2
        else:
            job = win_job_for(proc) if WINDOWS else None
            try:
                code = proc.wait(timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                kill_tree(proc, job)
                code = "timeout"
            else:
                if job:
                    # A check that exited may still leave a grandchild running (a worker, a git daemon of
                    # a fixture repo): ending the job stops it too, so nothing outlives the runner.
                    close_job(job, terminate=True)
    secs = time.monotonic() - start
    text = (out_path.read_bytes() + b"\n" + err_path.read_bytes()).decode("utf-8", "replace")
    return code, secs, text


def verdict(kind, code, text):
    if code == "timeout":
        return "TIMEOUT"
    if code == 2:
        return "COULD-NOT-RUN"
    if code != 0:
        return "FAIL"
    if kind == "parity" and PARITY_SKIPPED_RE.search(text):
        return "PARTIAL"
    if kind in ("selftest", "launcher") and any(
            SELFTEST_SKIP_RE.search(line) and not PASS_LINE_RE.match(line) for line in text.splitlines()):
        return "PARTIAL"
    return "PASS"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the /qconfig-sync Step 3 checks in parallel.")
    ap.add_argument("repo", nargs="?", default=str(DEFAULT_REPO))
    ap.add_argument("--work")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--ci", action="store_true")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not (repo / "shared" / "skills").is_dir() or not (repo / "inventory.tsv").is_file():
        print("run-checks: not an agent-playbook repo root: %s" % repo, file=sys.stderr)
        return 2
    checks = build_checks(repo, args.jobs)
    names = [c[0] for c in checks]
    if args.list:
        print("\n".join(names))
        return 0
    unknown = [n for n in args.only if n not in names]
    if unknown:
        print("run-checks: unknown check name(s): %s (see --list)" % ", ".join(unknown), file=sys.stderr)
        return 2
    if args.only:
        checks = [c for c in checks if c[0] in args.only]

    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="qconfig-sync-checks-"))
    work.mkdir(parents=True, exist_ok=True)
    wall = time.monotonic()
    results = {}
    for name, argv, kind, why in checks:
        if argv is None:
            (work / (name + ".err")).write_text("run-checks: did not run: %s\n" % why, encoding="utf-8")
            results[name] = (2, 0.0, why, kind)
    # The launcher test first and alone, then everything else at once, longest first.
    for name, argv, kind, _ in checks:
        if argv is not None and kind == "launcher":
            code, secs, text = run_one(repo, work, name, argv)
            results[name] = (code, secs, text, kind)
    rest = [c for c in checks if c[1] is not None and c[2] != "launcher"]
    longest_first = {"test-parity": 0, "dream-write-selftest": 1, "dream-sweep-selftest": 2,
                     "dream-manifest-selftest": 3}
    rest.sort(key=lambda c: longest_first.get(c[0], 9))
    if rest:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(rest)) as pool:
            futs = {pool.submit(run_one, repo, work, name, argv): (name, kind) for name, argv, kind, _ in rest}
            for fut in concurrent.futures.as_completed(futs):
                name, kind = futs[fut]
                code, secs, text = fut.result()
                results[name] = (code, secs, text, kind)
    wall = time.monotonic() - wall

    width = max(len(n) for n in results)
    print("%-*s  %4s  %7s  %7s  %s" % (width, "check", "exit", "seconds", "flagged", "verdict"))
    all_pass = True
    for name, _, _, _ in checks:
        code, secs, text, kind = results[name]
        v = verdict(kind, code, text)
        flagged = sum(1 for line in text.splitlines() if FLAG_RE.search(line) and not PASS_LINE_RE.match(line))
        print("%-*s  %4s  %7.1f  %7d  %s" % (width, name, code, secs, flagged, v))
        all_pass = all_pass and (v == "PASS" or (args.ci and v == "PARTIAL"))
    # This check always exits 0 and is always reported, so its lines print whatever the verdict.
    if "claude-settings" in results:
        print("".join("claude-settings: %s\n" % line for line in results["claude-settings"][2].splitlines() if line.strip()), end="")
    print("work folder: %s" % work)
    print("wall time: %.1f s" % wall)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
