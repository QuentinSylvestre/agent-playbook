#!/usr/bin/env python3
"""Scenario test for setup/setup.py (and the setup.ps1 / setup.sh bootstraps).

Run from the repo root with the playbook venv's Python, in isolated mode:

    .venv-agent-playbook/Scripts/python.exe -I setup/test_setup.py [--jobs N] [--setup PATH] [--only NAME]
                                                   [--bootstraps DIR] [--venv DIR]

--jobs N     scenarios run in parallel (default 6).
--setup PATH the setup script to test (default setup/setup.py beside this file); a mutant copy.
--venv DIR   the playbook venv folder (default: .venv-agent-playbook in the repo).
--bootstraps DIR  the folder holding the setup.ps1 and setup.sh to test (default: the repo root).
--only NAME  run only the scenarios whose name is NAME or starts with NAME (e.g. coexist, ownership).

Stdlib only, Python 3.8+. Exit 0 when no case failed, 1 when one did, 2 when the test could not run.
It prints one PASS / FAIL / SKIP line per case and a final `setup scenario test: N cases, F failed,
S skipped`.

Every scenario gets a fresh sandbox (tempfile.mkdtemp, removed at the end even on failure) and runs setup
as `[python, -X utf8, -I, <setup>, ...flags]` with HOME, USERPROFILE, APPDATA, XDG_CONFIG_HOME,
AGENT_PLAYBOOK_CONFIG and AGENT_PLAYBOOK_STORES in the sandbox (Python on Windows reads USERPROFILE, not
HOME), stdin from DEVNULL, and AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (or the kiro-cli stub on PATH). The venv
is the repo's own (AGENT_PLAYBOOK_TEST_VENV_DIR) except in the co-existence fixture g. After every run
the real profile is checked read-only (the real deploy lock, pointer file and journal, the top level of
~/.kiro/skills, the repo's memory link) and a change fails the test loudly.

Scenarios and the shared/skills/qconfig-sync/scripts/test-parity.sh section each came from. Setup runs
only in Python here: where a bash check compared the setup.sh leg with the setup.ps1 leg, only the
per-run assertions are kept. The twin comparisons (setup-parity, merge, render and the byte-equal lock
checks) are not ported: deploy_model.py's golden files replace merge and render.

  deploy       parity_sec_setup_verify (SETUP-VERIFY: a fresh deploy verifies clean under
               verify-deployment.py, no MISSING/WRONG_TARGET/NOT_SYMLINK/DRIFTED/AMBIGUOUS_SKILL; the
               all-OK case; NO-REWRITE: a second run, started through the repo's 8.3 short path when it
               has one, rewrites nothing) and the inventory check at the top of the script, replaced:
               every path `verify-deployment.py --list` names exists after a fresh deploy, and the
               deployed tree holds nothing setup made that --list does not name.
  dry-run      the dry runs of the co-existence checks, run on a bare sandbox: nothing written.
  ownership    parity_sec_ownership steps 1-6 as one chain (own_plant, own_check_deploy, own_check_rerun,
               own_plant_hold, own_check_hold, own_plant_uninstall, own_check_uninstall,
               own_check_revert, own_plant_nolock, own_check_nolock), with the kiro-cli stub.
  ownership-memlink  step 7 (a sandboxed HOME never writes the repo's memory link).
  coexist-a..g cx_all runs 1-3 per fixture: cx_plant, cx_check_deploy, cx_verify, the second run writes
               nothing (c: cx_check_dry_c and cx_check_transition), cx_interrupt (b), cx_check_uninstall;
               g adds cx_check_dry_g and the first run with no venv.
  coexist-h    cx_fixture_h (a folder at the lock path, a file at ~/.gemini/skills, the journal).
  coexist-i    cx_fixture_i (a helper that prints a success line then exits 1).
  boot-ps1-*, boot-sh-*  new: the repo's real setup.ps1 and setup.sh with each flag observable in a dry
               run, --help without Python, and the no-Python case (setup.sh / setup.ps1 only once it is a
               bootstrap, i.e. holds `setup/setup.py`).

  behaviors    cases for rules added after the bash suite (no bash counterpart): a dry run over conflicting
               files, --uninstall never creating a missing venv folder, a decoy HOME (Windows), a read-only
               deploy lock (Windows), a .bak edited after setup made it, a folder .bak never replaced, an
               existing deploy-lock.tsv.bak kept, a dangling seed link not written through, a sandboxed
               --purge never touching the repo's memory link, an existing <stores>/.gitignore kept, and a
               journal with one garbage line.

Not ported from test-parity.sh, on purpose:
  - parity_sec_setup_parity, TWIN-OWNERSHIP, TWIN-COEXIST and every byte-equal lock or settings.json
    comparison between the two shells: they compared setup.sh with setup.ps1, and there is one setup now.
  - parity_sec_merge and parity_sec_render: the shells' merge and render shapes no longer exist twice;
    deploy_model.py's golden files pin the merge and the render.
  - the inventory diff against a bash re-implementation of the deploy model: replaced by the `deploy`
    checks that every path `verify-deployment.py --list` names exists and that nothing unnamed is deployed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

WIN = os.name == "nt"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "shared", "skills", "qconfig-sync", "scripts")
VERIFY = os.path.join(SCRIPTS, "verify-deployment.py")
VENV_DIR = os.path.join(REPO, ".venv-agent-playbook")
VENV_PY = os.path.join(VENV_DIR, "Scripts", "python.exe") if WIN else os.path.join(VENV_DIR, "bin", "python")
BOOT_DIR = REPO   # replaced by --bootstraps
SETUP = os.path.join(HERE, "setup.py")   # replaced by --setup
PROVIDERS3 = "claude,codex,gemini"
BAD_VERIFY = re.compile(r"^(MISSING|WRONG_TARGET|NOT_SYMLINK|DRIFTED|AMBIGUOUS_SKILL)\t", re.M)


# --- results ---------------------------------------------------------------------------------

class Cases(object):
    """The checks of one scenario: (status, name, why)."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.rows = []

    def check(self, name, cond, why=""):
        if cond:
            self.rows.append(("PASS", "%s/%s" % (self.scenario, name), ""))
        else:
            if callable(why):
                why = why()
            self.rows.append(("FAIL", "%s/%s" % (self.scenario, name), why or "check failed"))

    def skip(self, name, why):
        self.rows.append(("SKIP", "%s/%s" % (self.scenario, name), why))

    def fail(self, name, why):
        self.rows.append(("FAIL", "%s/%s" % (self.scenario, name), why))


class ProfileTouched(Exception):
    pass


# --- the real profile guard (read-only) ---------------------------------------------------------

def _stat_sig(p):
    try:
        st = os.lstat(p)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def real_profile_snapshot():
    home = os.path.expanduser("~")
    snap = {}
    for rel in (".agent-playbook/deploy-lock.tsv", ".agent-playbook/deploy-lock.journal.tsv", ".agent-playbook/config"):
        snap[rel] = _stat_sig(os.path.join(home, *rel.split("/")))
    skills = os.path.join(home, ".kiro", "skills")
    try:
        snap["kiro-skills-top"] = (sorted(os.listdir(skills)), os.lstat(skills).st_mtime_ns)
    except OSError:
        snap["kiro-skills-top"] = None
    mem = os.path.join(REPO, "memory")
    try:
        snap["repo-memory-link"] = (os.path.islink(mem), os.readlink(mem) if os.path.islink(mem) else None)
    except OSError:
        snap["repo-memory-link"] = None
    return snap


_BASELINE = {}
_PROFILE_BAD = []
_PROFILE_LOCK = threading.Lock()


def check_real_profile(where):
    now = real_profile_snapshot()
    if now != _BASELINE:
        changed = [k for k in now if now[k] != _BASELINE.get(k)]
        with _PROFILE_LOCK:
            _PROFILE_BAD.append("%s: %s" % (where, ", ".join(changed)))
        raise ProfileTouched("the real profile changed (%s) after %s" % (", ".join(changed), where))


# --- small file helpers (tolerant: a missing file reads as None) ------------------------------------

def F(s):
    return s.lower() if WIN else s


def rb(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def rt(p):
    b = rb(p)
    return None if b is None else b.decode("utf-8", "replace")


def wb(p, data):
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(data)


def wt(p, text):
    wb(p, text.encode("utf-8"))


def ab(p, data):
    with open(p, "ab") as fh:
        fh.write(data)


def cp(src, dst):
    d = os.path.dirname(dst)
    if d:
        os.makedirs(d, exist_ok=True)
    shutil.copyfile(src, dst)


def sha(p):
    b = rb(p)
    return None if b is None else hashlib.sha256(b).hexdigest()


def same(a, b):
    x = rb(a)
    return x is not None and x == rb(b)


def absent(p):
    return not os.path.lexists(p)


def is_link(p):
    return os.path.islink(p)


def link_text(p):
    try:
        t = os.readlink(p)
    except OSError:
        return None
    if WIN and (t.startswith("\\\\?\\") or t.startswith("\\??\\")):
        t = t[4:]
    return t.replace("\\", "/")


def link_to(link, rel):
    t = link_text(link)
    return t is not None and t.endswith(rel)


def own_is(p, text):
    """A regular file (not a link) holding exactly text plus a newline."""
    if os.path.islink(p) or not os.path.isfile(p):
        return False
    t = rt(p)
    return t is not None and t.rstrip("\n") == text


def make_link(target, link, is_dir):
    d = os.path.dirname(link)
    if d:
        os.makedirs(d, exist_ok=True)
    os.symlink(target, link, target_is_directory=is_dir)


def remove_link(p):
    if os.path.isdir(p) and WIN:
        os.rmdir(p)
    else:
        os.unlink(p)


def assert_real_dir_chain(p, top):
    """Refuse a write or delete under top when a folder on the way (or p) is a link: the fixture would
    reach into the repo."""
    cur = p
    while len(cur) > len(top) and F(cur) != F(top):
        if os.path.islink(cur):
            raise RuntimeError("fixture assumption broken: %s is a link (expected a generated copy)" % cur)
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt


def rmtree_safe(p):
    """Delete a folder and everything in it, never entering a link."""
    if not os.path.lexists(p):
        return
    if os.path.islink(p):
        remove_link(p)
        return
    for e in os.scandir(p):
        full = os.path.join(p, e.name)
        if os.path.islink(full):
            try:
                remove_link(full)
            except OSError:
                os.unlink(full)
        elif e.is_dir(follow_symlinks=False):
            rmtree_safe(full)
        else:
            try:
                os.chmod(full, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            os.unlink(full)
    try:
        os.chmod(p, stat.S_IRWXU)
    except OSError:
        pass
    os.rmdir(p)


def count_entries(root):
    """What `find root | wc -l` counts."""
    n = 1
    for _d, dirs, files in os.walk(root):
        n += len(dirs) + len(files)
    return n


def list_files(root):
    out = []
    for d, _dirs, files in os.walk(root):
        for f in files:
            out.append(os.path.join(d, f))
    return out


def snapshot(home):
    """Every entry under home: relpath, type, mtime ns, inode (nr_snapshot / cx_snapshot of test-parity.sh;
    the PowerShell startup cache pwsh writes under a sandbox USERPROFILE is left out)."""
    out = []
    for d, dirs, files in os.walk(home):
        for n in dirs + files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, home).replace(os.sep, "/")
            if re.match(r"^AppData(/Local(/Microsoft(/PowerShell(/.*)?)?)?)?$", rel):
                continue
            st = os.lstat(p)
            kind = "link" if os.path.islink(p) else ("dir" if os.path.isdir(p) else "file")
            out.append("%s\t%s\t%d\t%d" % (rel, kind, st.st_mtime_ns, st.st_ino))
    return sorted(out)


def rx(text, pattern):
    return text is not None and re.search(pattern, text, re.M) is not None


# --- the lock -------------------------------------------------------------------------------------

def lock_path(home):
    return os.path.join(home, ".agent-playbook", "deploy-lock.tsv")


def journal_path(home):
    return os.path.join(home, ".agent-playbook", "deploy-lock.journal.tsv")


def lock_text(home):
    return rt(lock_path(home)) or ""


def lock_has(home, kind, path, value=None):
    pat = "^%s\t%s\t" % (re.escape(kind), re.escape(path))
    if value is not None:
        pat += re.escape(value) + "$"
    return rx(lock_text(home), pat)


def lock_add(home, kind, key, value):
    ab(lock_path(home), ("%s\t%s\t%s\n" % (kind, key, value)).encode("utf-8"))


def lock_drop_prefix(home, prefix):
    lines = (rt(lock_path(home)) or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    keep = [l for l in lines if not (len(l.split("\t")) > 1 and l.split("\t")[1].startswith(prefix))]
    wt(lock_path(home), "".join(l + "\n" for l in keep))


def lock_drop_line(home, needle):
    lines = (rt(lock_path(home)) or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    keep = [l for l in lines if needle not in l]
    wt(lock_path(home), "".join(l + "\n" for l in keep))


# --- run result -----------------------------------------------------------------------------------------

class Run(object):
    def __init__(self, rc, out, secs):
        self.rc = rc
        self.out = out
        self.secs = secs

    def has(self, pattern):
        return rx(self.out, pattern)

    def tail(self, n=12):
        lines = self.out.rstrip("\n").split("\n")[-n:]
        return "exit=%s; log tail: %s" % (self.rc, " | ".join(l.strip() for l in lines)[:900])


def path_without(names_ok):
    """PATH minus every folder where names_ok(entry name) holds for some entry."""
    out = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        try:
            names = os.listdir(d)
        except OSError:
            out.append(d)
            continue
        if any(names_ok(n) for n in names):
            continue
        out.append(d)
    return os.pathsep.join(out)


def no_kiro_path():
    return path_without(lambda n: n.lower() in ("kiro-cli", "kiro-cli.exe", "kiro-cli.cmd", "kiro-cli.bat"))


def no_python_path():
    def py(n):
        n = n.lower()
        return n.startswith("python") or n in ("py", "py.exe", "pyw.exe", "pythonw.exe")
    return path_without(py)


# --- the sandbox --------------------------------------------------------------------------------------

STUB_PY = '''import json, os, sys
d = os.environ["KIRO_STUB_DIR"]
a = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a", encoding="utf-8") as f:
    f.write(" ".join(a) + "\\n")
mode = open(os.path.join(d, "mode"), encoding="utf-8").read().strip()
val = os.path.join(d, "value.json")
if a == ["settings", "-f", "json", "--global", "chat.defaultAgent"]:
    if mode == "fail-read":
        sys.exit(1)
    print(open(val, encoding="utf-8").read().strip() if os.path.exists(val) else "null")
elif a == ["settings", "--global", "--delete", "chat.defaultAgent"]:
    if os.path.exists(val):
        os.remove(val)
elif len(a) == 4 and a[:3] == ["settings", "--global", "chat.defaultAgent"]:
    open(val, "w", encoding="utf-8").write(json.dumps(a[3]))
else:
    sys.exit(2)
'''


class Stub(object):
    """A kiro-cli stub beside the sandbox (never inside the home): logs each call, answers
    `settings -f json --global chat.defaultAgent` from value.json (null when absent, exit 1 in mode
    fail-read) and sets or deletes the value (own_stub of test-parity.sh)."""

    def __init__(self, root):
        self.dir = os.path.join(root, "kiro-stub")
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        wt(os.path.join(self.dir, "stub.py"), STUB_PY)
        py = os.path.join(self.dir, "stub.py")
        if WIN:
            self.exe = os.path.join(self.bin, "kiro-cli.cmd")
            wb(self.exe, ('@"%s" -I "%s" %%*\r\n' % (VENV_PY, py)).encode("utf-8"))
        else:
            self.exe = os.path.join(self.bin, "kiro-cli")
            wt(self.exe, '#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (VENV_PY, py))
            os.chmod(self.exe, 0o755)
        self.path = self.bin + os.pathsep + no_kiro_path()
        got = shutil.which("kiro-cli", path=self.path)
        self.used = got is not None and os.path.normcase(os.path.abspath(got)) == os.path.normcase(os.path.abspath(self.exe))
        self.got = got
        self.state("", "ok")

    def state(self, value, mode):
        if value:
            wt(os.path.join(self.dir, "value.json"), value)
        wt(os.path.join(self.dir, "mode"), mode + "\n")
        wt(os.path.join(self.dir, "calls.log"), "")

    def calls(self):
        return (rt(os.path.join(self.dir, "calls.log")) or "").replace("\r\n", "\n")

    def value(self):
        v = rt(os.path.join(self.dir, "value.json"))
        return None if v is None else v.strip()


class Box(object):
    """One scenario's sandbox: root/home is the home; setup runs against it."""

    def __init__(self, c):
        self.c = c
        self.root = tempfile.mkdtemp(prefix="apb-setup-test-")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.stub = None

    def close(self):
        try:
            rmtree_safe(self.root)
        except OSError:
            shutil.rmtree(self.root, ignore_errors=True)

    def aux(self, name):
        return os.path.join(self.root, name)

    def env(self, venv=None, helper=None, use_stub=False, path=None, extra=None):
        env = dict((k, v) for k, v in os.environ.items() if not k.upper().startswith("AGENT_PLAYBOOK_"))
        env.update({
            "HOME": self.home, "USERPROFILE": self.home,
            "APPDATA": os.path.join(self.home, "AppData", "Roaming"),
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "AGENT_PLAYBOOK_CONFIG": os.path.join(self.home, ".agent-playbook", "config"),
            "AGENT_PLAYBOOK_STORES": os.path.join(self.root, "stores"),
            "AGENT_PLAYBOOK_TEST_VENV_DIR": venv or VENV_DIR,
        })
        if helper:
            env["AGENT_PLAYBOOK_TEST_GEMINI_HELPER"] = helper
        if use_stub and self.stub is not None and self.stub.used:
            env["PATH"] = self.stub.path
            env["KIRO_STUB_DIR"] = self.stub.dir
        else:
            env["AGENT_PLAYBOOK_SKIP_KIRO_CLI"] = "1"
            if path is not None:
                env["PATH"] = path
        if extra:
            env.update(extra)
        return env

    def _go(self, argv, env, what):
        t0 = time.time()
        r = subprocess.run(argv, env=env, cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=600)
        out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        check_real_profile(what)
        return Run(r.returncode, out, time.time() - t0)

    def run(self, *args, **kw):
        """setup.py with the flags, in the sandbox. kw: setup (script path), venv, helper, use_stub."""
        setup = kw.pop("setup", None) or SETUP
        env = self.env(venv=kw.pop("venv", None), helper=kw.pop("helper", None), use_stub=kw.pop("use_stub", False),
                       extra=kw.pop("extra", None))
        assert not kw, kw
        return self._go([sys.executable, "-X", "utf8", "-I", setup] + list(args), env, "setup " + " ".join(args))

    def verify(self, *args):
        """verify-deployment.py under the venv Python and the sandbox env."""
        return self._go([VENV_PY, "-I", VERIFY] + list(args), self.env(), "verify-deployment " + " ".join(args))

    def raw(self, argv, path=None):
        return self._go(argv, self.env(path=path), " ".join(argv[:3]))

    def no_python_path(self):
        """A PATH with no Python. Off Windows: a shim folder holding links to only the tools the
        bootstraps call (bash, dirname, cat, env, uname), so nothing else on the host is found. On
        Windows: the host PATH minus every folder that holds a python or py launcher."""
        if WIN:
            return no_python_path()
        shim = self.aux("no-python-shim")
        os.makedirs(shim, exist_ok=True)
        for tool in ("bash", "dirname", "cat", "env", "uname"):
            real = shutil.which(tool)
            if real and not os.path.lexists(os.path.join(shim, tool)):
                os.symlink(real, os.path.join(shim, tool))
        return shim


# --- scenario: deploy (SETUP-VERIFY, NO-REWRITE, inventory) ------------------------------------------------------

def short_path_of(p):
    if not WIN:
        return None
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
    return buf.value if 0 < n < 1024 else None


def inventory_rows(v):
    rows = []
    for line in v.out.split("\n"):
        c = line.split("\t")
        if len(c) == 4:
            rows.append(c)
    return rows


def scenario_deploy(c):
    box = Box(c)
    try:
        r1 = box.run()
        c.check("deploy-exit0", r1.rc == 0, r1.tail)
        v = box.verify()
        bad = BAD_VERIFY.findall(v.out)
        c.check("verify-clean", v.rc == 0 and not bad and "SUMMARY\t" in v.out,
                lambda: "verify exit=%s bad=%s %s" % (v.rc, bad[:5], v.tail(4)))
        # all-OK: every status line is OK, SKIP or ORPHAN
        statuses = set(l.split("\t")[0] for l in v.out.split("\n") if "\t" in l and not l.startswith("SUMMARY"))
        c.check("all-ok-statuses", statuses <= set(["OK", "SKIP", "ORPHAN"]) and "OK" in statuses,
                lambda: "statuses: %s" % sorted(statuses))

        # inventory: --list against the deployed tree
        lst = box.verify("--list")
        rows = inventory_rows(lst)
        c.check("list-runs", lst.rc == 0 and len(rows) > 50, lambda: "--list: %s rows, exit %s" % (len(rows), lst.rc))
        missing = []
        for kind, dest, source, _mode in rows:
            if not os.path.exists(source):
                continue   # a source the checkout lacks (gitignored memory/) is not deployed
            if not os.path.lexists(dest):
                missing.append(dest)
        c.check("list-paths-exist", rows and not missing, lambda: "named by --list, absent after deploy: %s" % missing[:5])
        norm = lambda p: os.path.normcase(os.path.normpath(p))
        dests = set(norm(r[1]) for r in rows)
        dir_rows = [norm(r[1]) for r in rows if r[0] in ("symlink-dir", "copy-dir-recursive")]
        ancestors = set()
        for _k, dest, _s, _m in rows:
            d = os.path.dirname(dest)
            while len(norm(d)) > len(norm(box.home)):
                ancestors.add(norm(d))
                nd = os.path.dirname(d)
                if nd == d:
                    break
                d = nd
        extra = []
        for d, dirs, files in os.walk(box.home):
            for n in dirs + files:
                p = os.path.join(d, n)
                rel = os.path.relpath(p, box.home).replace(os.sep, "/")
                if rel == ".agent-playbook" or rel in (".agent-playbook/config", ".agent-playbook/deploy-lock.tsv"):
                    continue
                np_ = norm(p)
                if np_ in dests or np_ in ancestors:
                    continue
                if any(np_.startswith(dr + os.sep) for dr in dir_rows):
                    continue
                extra.append(rel)
        c.check("tree-has-nothing-unnamed", not extra, lambda: "setup made, --list does not name: %s" % extra[:8])
        c.check("lock-written", os.path.isfile(lock_path(box.home)) and lock_text(box.home).startswith("# agent-playbook deploy lock"),
                "no deploy lock after a fresh deploy")

        # NO-REWRITE: a second run, through the 8.3 short path of the repo when there is one
        setup2 = SETUP
        short = short_path_of(REPO)
        if short and F(short) != F(REPO) and F(os.path.abspath(SETUP)).startswith(F(REPO) + os.sep):
            setup2 = os.path.join(short, os.path.relpath(os.path.abspath(SETUP), REPO))
        else:
            c.skip("no-rewrite-short-path", "the repo has no 8.3 short path here; run 2 uses the long path")
        s1 = snapshot(box.home)
        r2 = box.run(setup=setup2)
        s2 = snapshot(box.home)
        diff = sorted(set(s1) ^ set(s2))
        c.check("no-rewrite", r2.rc == 0 and s1 and s1 == s2 and os.path.isfile(lock_path(box.home)),
                lambda: "second run changed the sandbox: %s; %s" % ([d.split("\t")[0] for d in diff[:8]], r2.tail(4)))
        c.check("no-backups-after-rerun", not [f for f in list_files(box.home) if f.endswith(".bak")],
                "a .bak exists after a clean re-run")
    finally:
        box.close()


# --- scenario: dry-run -------------------------------------------------------------------------------------

def scenario_dry_run(c):
    box = Box(c)
    try:
        r = box.run("--dry-run")
        c.check("dry-run-exit0", r.rc == 0, r.tail)
        c.check("dry-run-says-so", r.has(r"DRY RUN: nothing will be changed") and r.has(r"DRY: "), r.tail)
        c.check("dry-run-writes-nothing", not snapshot(box.home), lambda: "written: %s" % snapshot(box.home)[:5])
        r = box.run("--dry-run", "--uninstall", "--purge")
        c.check("dry-uninstall-purge", r.rc == 0 and r.has(r"=== Uninstall: ") and not snapshot(box.home), r.tail)
        r = box.run("--providers", "nope")
        c.check("unknown-provider-exit2", r.rc == 2 and r.has("unknown provider"), r.tail)
        r = box.run("--purge")
        c.check("purge-without-uninstall-exit2", r.rc == 2, r.tail)
    finally:
        box.close()


# --- scenario: ownership (the chain) -----------------------------------------------------------------------

def own_plant(box):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    for name in ("qdev", "qreview", "qexplore", "qplan", "qdream", "qextract", "qtest", "qqa"):
        assert_real_dir_chain(os.path.join(sk, name), k)
        if os.path.islink(os.path.join(sk, name)):
            raise RuntimeError("%s is a link, not a generated copy" % name)
    # 1. a file of yours inside a generated copy
    wt(os.path.join(sk, "qdev", "my-notes.md"), "mine\n")
    # 2. a file of a generated copy, edited
    cp(os.path.join(sk, "qdev", "SKILL.md"), box.aux("qdev-skill.orig"))
    ab(os.path.join(sk, "qdev", "SKILL.md"), b"edited qdev\n")
    cp(os.path.join(sk, "qdev", "SKILL.md"), box.aux("qdev-skill.edited"))
    # 3. a folder of yours at an overlay-bearing skill's name, with no lock rows
    rmtree_safe(os.path.join(sk, "qreview"))
    wt(os.path.join(sk, "qreview", "SKILL.md"), "user qreview\n")
    wt(os.path.join(sk, "qreview", "my-own.md"), "my own\n")
    cp(os.path.join(REPO, "shared", "skills", "qreview", "full-effort.md"), os.path.join(sk, "qreview", "full-effort.md"))
    lock_drop_prefix(sb, "~/.kiro/skills/qreview/")
    # 4. a copy-file row, edited
    wt(os.path.join(k, "AUTHORING.md"), "edited authoring\n")
    # 5. a foreign symlink at a link path
    wt(os.path.join(sb, "foreign-target.md"), "foreign\n")
    agents_md = os.path.join(k, "steering", "agents.md")
    if os.path.lexists(agents_md):
        os.unlink(agents_md)
    make_link(os.path.join(sb, "foreign-target.md"), agents_md, False)
    # 6. a locked, unedited file whose source is gone (a deleted skill), and a fixtures/ file of it
    wt(os.path.join(sk, "qgone", "SKILL.md"), "gone\n")
    lock_add(sb, "copy-dir-recursive", "~/.kiro/skills/qgone/SKILL.md", sha(os.path.join(sk, "qgone", "SKILL.md")))
    fx = os.path.join(sk, "qgone", "scripts", "fixtures", "case.json")
    wt(fx, "gone fixture\n")
    lock_add(sb, "copy-dir-recursive", "~/.kiro/skills/qgone/scripts/fixtures/case.json", sha(fx))
    # 7. a locked file whose source is gone, edited since setup wrote it
    wt(os.path.join(sk, "qgone2", "SKILL.md"), "edited gone\n")
    lock_add(sb, "merge-file", "~/.kiro/skills/qgone2/SKILL.md", sha(os.path.join(sk, "qgone", "SKILL.md")))
    # 8. a locked file setup wrote in an older version, unedited: replaced, no backup
    cp(os.path.join(sk, "qexplore", "SKILL.md"), box.aux("qexplore-skill.orig"))
    wt(os.path.join(sk, "qexplore", "SKILL.md"), "an older merge\n")
    lock_drop_line(sb, "\t~/.kiro/skills/qexplore/SKILL.md\t")
    lock_add(sb, "merge-file", "~/.kiro/skills/qexplore/SKILL.md", sha(os.path.join(sk, "qexplore", "SKILL.md")))
    # 9. a folder of yours with a SKILL.md at a plain skill's name (a link there before)
    p = os.path.join(sk, "qcouncil")
    if os.path.islink(p):
        remove_link(p)
    wt(os.path.join(p, "SKILL.md"), "user qcouncil\n")
    # 10. an older generated copy the lock names no file of, every file at a path setup writes, one edited
    cp(os.path.join(sk, "qplan", "SKILL.md"), box.aux("qplan-skill.orig"))
    wt(os.path.join(sk, "qplan", "SKILL.md"), "an older qplan\n")
    lock_drop_prefix(sb, "~/.kiro/skills/qplan/")
    # 11. a plain skill's folder holding a file setup wrote, unchanged, beside a file of yours
    p = os.path.join(sk, "qhandoff")
    if os.path.islink(p):
        remove_link(p)
    cp(os.path.join(REPO, "shared", "skills", "qhandoff", "SKILL.md"), os.path.join(p, "SKILL.md"))
    wt(os.path.join(p, "mine.md"), "mine\n")
    lock_add(sb, "copy-dir-recursive", "~/.kiro/skills/qhandoff/SKILL.md", sha(os.path.join(p, "SKILL.md")))
    #     the same with the file setup wrote edited since
    p = os.path.join(sk, "qclose")
    if os.path.islink(p):
        remove_link(p)
    shared_close = rb(os.path.join(REPO, "shared", "skills", "qclose", "SKILL.md"))
    wb(os.path.join(p, "SKILL.md"), shared_close + b"edited qclose\n")
    cp(os.path.join(p, "SKILL.md"), box.aux("qclose-skill.edited"))
    wt(os.path.join(p, "mine.md"), "mine\n")
    lock_add(sb, "copy-dir-recursive", "~/.kiro/skills/qclose/SKILL.md", hashlib.sha256(shared_close).hexdigest())
    # 12. a file of a generated copy whose name and lock row differ from the source only in letter case
    if WIN:
        f = os.path.join(sk, "qtest", "plan-process.md")
        os.rename(f, os.path.join(sk, "qtest", "x.tmp"))
        os.rename(os.path.join(sk, "qtest", "x.tmp"), os.path.join(sk, "qtest", "PLAN-process.md"))
        lock_drop_line(sb, "\t~/.kiro/skills/qtest/plan-process.md\t")
        lock_add(sb, "copy-dir-recursive", "~/.kiro/skills/qtest/PLAN-process.md", sha(os.path.join(sk, "qtest", "PLAN-process.md")))
    # 13. an edited template-file row
    cp(os.path.join(k, "agents", "kiro_default.md"), box.aux("kiro-default.orig"))
    ab(os.path.join(k, "agents", "kiro_default.md"), b"edited template\n")
    cp(os.path.join(k, "agents", "kiro_default.md"), box.aux("kiro-default.edited"))
    # 14. a folder above a generated copy's file is a link: that file is skipped
    os.makedirs(box.aux("linked-refs"))
    refs = os.path.join(sk, "qextract", "references")
    rmtree_safe(refs)
    make_link(box.aux("linked-refs"), refs, True)
    # 15. a lock row for a seed file (setup never writes one): never retired
    lock_add(sb, "copy-file", "~/.kiro/settings/mcp.json", sha(os.path.join(k, "settings", "mcp.json")))
    # 16. a retired playbook name (the frozen stale list) holding a file of yours: backed up
    wt(os.path.join(k, "agents", "kiro_default.json"), "my json\n")
    # 17. an older copy's fixtures/ files with lock rows: the unchanged ones go, an edited one to .bak
    fxr = os.path.join("scripts", "fixtures", "dream-check", "budget")
    for f in ("cases.json", "tree/memory/MEMORY.md", "tree/memory/HIGHER_ORDER.md"):
        dst = os.path.join(sk, "qdream", fxr, *f.split("/"))
        cp(os.path.join(REPO, "shared", "skills", "qdream", fxr, *f.split("/")), dst)
        lock_add(sb, "copy-dir-recursive", "~/.kiro/skills/qdream/%s/%s" % (fxr.replace(os.sep, "/"), f), sha(dst))
    ab(os.path.join(sk, "qdream", fxr, "cases.json"), b"edited fixture\n")
    cp(os.path.join(sk, "qdream", fxr, "cases.json"), box.aux("fixture.edited"))
    # 18. an older copy of setup's the lock names no file of, plus a file of yours under fixtures/
    lock_drop_prefix(sb, "~/.kiro/skills/qqa/")
    wt(os.path.join(sk, "qqa", "fixtures", "mine.json"), "mine\n")


FXD = os.path.join("scripts", "fixtures", "dream-check", "budget")


def own_check_deploy(c, box, R, stub):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    c.check("collision-run-exit0", R.rc == 0, R.tail)
    c.check("your-file-in-generated-copy-left", own_is(os.path.join(sk, "qdev", "my-notes.md"), "mine")
            and absent(os.path.join(sk, "qdev", "my-notes.md.bak")), "a file of yours inside a generated copy is left in place")
    c.check("edited-generated-file-to-bak", same(os.path.join(sk, "qdev", "SKILL.md.bak"), box.aux("qdev-skill.edited"))
            and same(os.path.join(sk, "qdev", "SKILL.md"), box.aux("qdev-skill.orig")),
            "an edited file of a generated copy goes to .bak and is rewritten")
    c.check("your-folder-at-overlay-skill-KEPT", own_is(os.path.join(sk, "qreview", "SKILL.md"), "user qreview")
            and own_is(os.path.join(sk, "qreview", "my-own.md"), "my own") and count_entries(os.path.join(sk, "qreview")) == 4
            and R.has(r"KEPT: .*qreview"), "a folder of yours at an overlay skill's name is KEPT, untouched, though one file equals setup's")
    c.check("edited-copy-file-to-bak", own_is(os.path.join(k, "AUTHORING.md.bak"), "edited authoring")
            and same(os.path.join(k, "AUTHORING.md"), os.path.join(REPO, "shared", "AUTHORING.md")),
            "an edited copy-file row goes to .bak and is rewritten")
    am = os.path.join(k, "steering", "agents.md")
    c.check("foreign-symlink-to-bak", is_link(am + ".bak") and (link_text(am + ".bak") or "").endswith("foreign-target.md")
            and is_link(am) and (link_text(am) or "").endswith("shared/AGENTS.md"),
            "a foreign symlink goes to .bak before the link is made")
    c.check("locked-unedited-gone-source-removed", absent(os.path.join(sk, "qgone")),
            "a locked unedited file whose source is gone is removed, with its folder")
    c.check("deleted-skill-fixtures-retired-as-source-gone", R.has(r"REMOVED: .*qgone.scripts.fixtures.case.json \(its source is gone\)"),
            "a deleted skill's fixtures/ file is retired as one whose source is gone")
    c.check("edited-gone-source-to-bak", absent(os.path.join(sk, "qgone2", "SKILL.md"))
            and own_is(os.path.join(sk, "qgone2", "SKILL.md.bak"), "edited gone"), "an edited file whose source is gone goes to .bak")
    c.check("locked-unedited-replaced-no-backup", same(os.path.join(sk, "qexplore", "SKILL.md"), box.aux("qexplore-skill.orig"))
            and absent(os.path.join(sk, "qexplore", "SKILL.md.bak")), "a locked unedited file is replaced with no backup")
    qc = os.path.join(sk, "qcouncil")
    c.check("your-kiro-skill-folder-KEPT", os.path.isdir(qc) and not is_link(qc) and own_is(os.path.join(qc, "SKILL.md"), "user qcouncil")
            and R.has(r"KEPT: .*qcouncil"), "a Kiro skill folder of yours with a SKILL.md is KEPT")
    c.check("older-copy-no-lock-rows-is-setups", own_is(os.path.join(sk, "qplan", "SKILL.md.bak"), "an older qplan")
            and same(os.path.join(sk, "qplan", "SKILL.md"), box.aux("qplan-skill.orig"))
            and lock_has(sb, "merge-file", "~/.kiro/skills/qplan/SKILL.md"),
            "an older copy with no lock rows and only setup's paths is setup's: the edited file goes to .bak")
    qh = os.path.join(sk, "qhandoff")
    c.check("plain-skill-setup-file-beside-yours-kept-whole",
            same(os.path.join(qh, "SKILL.md"), os.path.join(REPO, "shared", "skills", "qhandoff", "SKILL.md"))
            and own_is(os.path.join(qh, "mine.md"), "mine") and not is_link(qh) and R.has(r"WARN: .*qhandoff.*no longer updated there")
            and lock_has(sb, "copy-dir-recursive", "~/.kiro/skills/qhandoff/SKILL.md"),
            "a plain skill's folder with setup's file beside yours is kept whole, with a warning and its lock row")
    qcl = os.path.join(sk, "qclose")
    c.check("plain-skill-edited-setup-file-kept-no-backup", same(os.path.join(qcl, "SKILL.md"), box.aux("qclose-skill.edited"))
            and absent(os.path.join(qcl, "SKILL.md.bak")) and own_is(os.path.join(qcl, "mine.md"), "mine")
            and R.has(r"WARN: .*qclose.*no longer updated there"),
            "a plain skill's folder with an edited file of setup's beside yours is kept whole, nothing backed up")
    if WIN:
        c.check("letter-case-only-name-difference", os.path.isfile(os.path.join(sk, "qtest", "PLAN-process.md"))
                and same(os.path.join(sk, "qtest", "PLAN-process.md"), os.path.join(REPO, "shared", "skills", "qtest", "plan-process.md"))
                and absent(os.path.join(sk, "qtest", "plan-process.md.bak")) and absent(os.path.join(sk, "qtest", "PLAN-process.md.bak")),
                "a file whose name differs from its source only in letter case is neither backed up nor retired")
    else:
        c.skip("letter-case-only-name-difference", "NTFS only: elsewhere letter case makes another file")
    c.check("edited-template-to-bak", same(os.path.join(k, "agents", "kiro_default.md.bak"), box.aux("kiro-default.edited"))
            and same(os.path.join(k, "agents", "kiro_default.md"), box.aux("kiro-default.orig")),
            "an edited template-file row goes to .bak and is rendered again")
    c.check("file-under-linked-folder-skipped", not os.listdir(box.aux("linked-refs"))
            and R.has(r"SKIPPED: .*references.*a folder above it is a link"),
            "a file under a linked folder of a generated copy is skipped, never written through the link")
    c.check("seed-lock-row-never-retires-seed", os.path.isfile(os.path.join(k, "settings", "mcp.json"))
            and "settings/mcp.json" not in lock_text(sb), "a lock row for a seed file never retires the seed (and is not kept)")
    c.check("retired-name-with-your-file-to-bak", own_is(os.path.join(k, "agents", "kiro_default.json.bak"), "my json")
            and absent(os.path.join(k, "agents", "kiro_default.json"))
            and lock_has(sb, "backup", "~/.kiro/agents/kiro_default.json"), "a retired playbook name holding a file of yours goes to .bak")
    fxd = os.path.join(sk, "qdream", FXD)
    fx_root = os.path.join(sk, "qdream", "scripts", "fixtures")
    c.check("older-copy-locked-fixtures-files", same(os.path.join(fxd, "cases.json.bak"), box.aux("fixture.edited"))
            and absent(os.path.join(fxd, "cases.json")) and absent(os.path.join(fxd, "tree"))
            and len(list_files(fx_root)) == 1 and R.has(r"REMOVED: 2 unchanged file\(s\) under fixtures/ folders in ")
            and R.has(r"NOTE: .*cases.json changed since setup wrote it and setup no longer deploys fixtures/ folders")
            and not R.has(r"qdream.scripts.fixtures.*\(its source is gone\)")
            and lock_has(sb, "backup", "~/.kiro/skills/qdream/scripts/fixtures/dream-check/budget/cases.json")
            and not rx(lock_text(sb), r"^(copy-dir-recursive|merge-file)\t~/\.kiro/skills/qdream/scripts/fixtures/"),
            "an older copy's locked fixtures/ files: the unchanged ones go on one summary line, an edited one to .bak")
    stray = []
    for f in list_files(sk):
        rel = f[len(sk) + 1:].replace(os.sep, "/")
        if "/fixtures/" in "/" + rel and not f.endswith(".bak") and rel != "qqa/fixtures/mine.json":
            stray.append(rel)
    c.check("no-generated-copy-holds-a-fixtures-file", not stray, lambda: "fixtures/ files setup wrote: %s" % stray[:5])
    c.check("your-fixtures-file-folder-KEPT", own_is(os.path.join(sk, "qqa", "fixtures", "mine.json"), "mine")
            and R.has(r"KEPT: .*qqa") and "\t~/.kiro/skills/qqa/" not in lock_text(sb),
            "a folder the lock names nothing of, with a fixtures/ file of yours, is KEPT")
    c.check("lock-records-backups-drops-retired-and-KEPT",
            lock_has(sb, "backup", "~/.kiro/AUTHORING.md") and lock_has(sb, "backup", "~/.kiro/steering/agents.md", "-")
            and "qgone/" not in lock_text(sb) and "\t~/.kiro/skills/qreview/" not in lock_text(sb)
            and absent(journal_path(sb)),
            "the lock records the backups and drops the retired and KEPT paths, and the journal is gone")
    if stub.used:
        c.check("chat-defaultagent-set-and-prior-recorded",
                rx(stub.calls(), r"^settings --global chat\.defaultAgent kiro_default$")
                and lock_has(sb, "setting", "kiro-cli/chat.defaultAgent", '"my_agent"'),
                "chat.defaultAgent is set to kiro_default and the value it replaced is recorded")
    else:
        c.skip("chat-defaultagent-set-and-prior-recorded", "kiro-cli does not resolve to the stub here (got %r)" % (stub.got,))


def own_plant_hold(box):
    """Edits for the failed-backup step, then the file held open. Returns (release, skip_reason)."""
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    ab(os.path.join(sk, "qexplore-other", "SKILL.md"), b"edited held\n")
    cp(os.path.join(sk, "qexplore-other", "SKILL.md"), box.aux("held.edited"))
    ab(os.path.join(sk, "qbrowser-test", "SKILL.md"), b"edited browser\n")
    cp(os.path.join(sk, "qbrowser-test", "SKILL.md"), box.aux("browser.edited"))
    wt(os.path.join(sk, "qbrowser-test", "SKILL.md.bak"), "my own backup\n")
    wt(os.path.join(k, "AUTHORING.md"), "edited2 authoring\n")
    try:
        os.unlink(os.path.join(sk, "qdream", FXD, "cases.json.bak"))
    except OSError:
        pass
    lock_drop_prefix(sb, "~/.kiro/skills/qdream/")
    for f in ("cases.json", "tree/memory/MEMORY.md"):
        cp(os.path.join(REPO, "shared", "skills", "qdream", FXD, *f.split("/")), os.path.join(sk, "qdream", FXD, *f.split("/")))
    target = os.path.join(sk, "qexplore-other", "SKILL.md")
    if WIN:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.CreateFileW(target, 0x80000000, 1, None, 3, 0x80, None)   # read, share read only: no delete
        if h in (None, ctypes.c_void_p(-1).value):
            return (lambda: None), "the file holder did not start"
        return (lambda: k32.CloseHandle(h)), None
    folder = os.path.dirname(target)
    os.chmod(folder, 0o555)
    try:
        with open(os.path.join(folder, ".probe"), "wb"):
            pass
        os.unlink(os.path.join(folder, ".probe"))
        os.chmod(folder, 0o755)
        return (lambda: None), "a file cannot be made unmovable here (a read-only folder is still writable: root?)"
    except OSError:
        return (lambda: os.chmod(folder, 0o755)), None


def own_check_hold(c, box, R, stub, held_skip):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    if held_skip:
        c.skip("failed-backup", held_skip + "; the failed-backup checks are skipped")
    else:
        c.check("failed-backup-is-an-error-and-nonzero", R.rc not in (0, None)
                and R.has(r"ERROR: could not back up .*qexplore-other.SKILL.md; left unchanged"), R.tail)
        c.check("unbackupable-file-left-unchanged", same(os.path.join(sk, "qexplore-other", "SKILL.md"), box.aux("held.edited"))
                and absent(os.path.join(sk, "qexplore-other", "SKILL.md.bak"))
                and "\t~/.kiro/skills/qexplore-other/SKILL.md\t" not in lock_text(sb),
                "a file that cannot be backed up is left unchanged, with no .bak and no lock row")
    c.check("foreign-bak-left-alone", same(os.path.join(sk, "qbrowser-test", "SKILL.md"), box.aux("browser.edited"))
            and own_is(os.path.join(sk, "qbrowser-test", "SKILL.md.bak"), "my own backup")
            and R.has(r"WARN: .*qbrowser-test.SKILL.md.bak is not a backup setup made")
            and "\t~/.kiro/skills/qbrowser-test/SKILL.md\t" not in lock_text(sb),
            "a .bak that is not setup's is left alone, and so is the file beside it")
    c.check("later-backup-replaces-earlier", own_is(os.path.join(k, "AUTHORING.md.bak"), "edited2 authoring")
            and same(os.path.join(k, "AUTHORING.md"), os.path.join(REPO, "shared", "AUTHORING.md")),
            "a later backup replaces the earlier one setup made")
    c.check("older-copy-fixtures-equal-source-deployed", not R.has(r"KEPT: .*qdream")
            and absent(os.path.join(sk, "qdream", "scripts", "fixtures"))
            and R.has(r"REMOVED: 2 unchanged file\(s\) under fixtures/ folders in .*qdream")
            and lock_has(sb, "merge-file", "~/.kiro/skills/qdream/SKILL.md"),
            "an older copy with no lock rows whose fixtures/ files equal their source is deployed, and those files go")
    c.check("journal-gone-after-lock-written", absent(journal_path(sb)), "the journal is gone once the lock is written")
    if stub.used:
        c.check("unreadable-setting-not-set-row-kept", "chat.defaultAgent kiro_default" not in stub.calls()
                and lock_has(sb, "setting", "kiro-cli/chat.defaultAgent", '"my_agent"'),
                "a chat.defaultAgent that cannot be read is not set, and the row is not replaced by -")


def own_plant_uninstall(box, stub):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    ab(os.path.join(sk, "qtest", "SKILL.md"), b"edited qtest\n")
    cp(os.path.join(sk, "qtest", "SKILL.md"), box.aux("qtest-skill.edited"))
    wt(os.path.join(k, "steering", "kiro-guidelines.md.bak"), "stray\n")
    ab(os.path.join(k, "agents", "kiro_default.md.bak"), b"edited bak\n")
    bak = os.path.join(k, "agents", "qdream_child.md.bak")
    wt(bak, "my child\n")
    wt(journal_path(sb), "backup\t~/.kiro/agents/qdream_child.md\t%s\n" % sha(bak))
    stub.state("", "fail-read")


def own_check_uninstall(c, box, R, stub):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    c.check("uninstall-exit0", R.rc == 0, R.tail)
    c.check("uninstall-keeps-edited-generated-file", same(os.path.join(sk, "qtest", "SKILL.md"), box.aux("qtest-skill.edited")),
            "uninstall keeps an edited generated file")
    c.check("uninstall-removes-unedited-restores-bak", same(os.path.join(sk, "qdev", "SKILL.md"), box.aux("qdev-skill.edited"))
            and absent(os.path.join(sk, "qdev", "SKILL.md.bak")) and own_is(os.path.join(sk, "qdev", "my-notes.md"), "mine")
            and len(list_files(os.path.join(sk, "qdev"))) == 2,
            "uninstall removes unedited generated files and restores the .bak setup made")
    c.check("uninstall-removes-unedited-copy-folder", absent(os.path.join(sk, "qexplore")),
            "uninstall removes a generated copy left unedited, folder included")
    c.check("uninstall-copy-file-restores-bak", own_is(os.path.join(k, "AUTHORING.md"), "edited2 authoring")
            and absent(os.path.join(k, "AUTHORING.md.bak")), "uninstall removes an unedited copy-file row and restores its .bak")
    am = os.path.join(k, "steering", "agents.md")
    c.check("uninstall-restores-foreign-symlink", is_link(am) and (link_text(am) or "").endswith("foreign-target.md")
            and absent(am + ".bak"), "uninstall restores a backed-up foreign symlink")
    c.check("uninstall-never-restores-foreign-bak", own_is(os.path.join(k, "steering", "kiro-guidelines.md.bak"), "stray")
            and absent(os.path.join(k, "steering", "kiro-guidelines.md")), "uninstall never restores a .bak setup did not make")
    c.check("uninstall-keeps-bak-edited-since", absent(os.path.join(k, "agents", "kiro_default.md"))
            and os.path.isfile(os.path.join(k, "agents", "kiro_default.md.bak"))
            and R.has(r"KEPT: .*kiro_default.md.bak \(changed since setup made it\)"), "uninstall keeps a .bak edited since setup made it")
    c.check("uninstall-restores-journal-only-backup", own_is(os.path.join(k, "agents", "qdream_child.md"), "my child")
            and absent(os.path.join(k, "agents", "qdream_child.md.bak")),
            "uninstall restores a backup an interrupted run recorded only in the journal")
    c.check("uninstall-leaves-your-skill-folders", own_is(os.path.join(sk, "qreview", "SKILL.md"), "user qreview")
            and own_is(os.path.join(sk, "qcouncil", "SKILL.md"), "user qcouncil") and own_is(os.path.join(sk, "qhandoff", "mine.md"), "mine")
            and absent(os.path.join(sk, "qhandoff", "SKILL.md")),
            "uninstall leaves your own skill folders alone, and takes setup's file out of a mixed one")
    c.check("uninstall-drops-kiro-rows-and-journal", (not os.path.isfile(lock_path(sb)) or "\t~/.kiro/" not in lock_text(sb))
            and absent(journal_path(sb)), "uninstall drops the Kiro rows from the lock, and the journal")
    if stub.used:
        c.check("uninstall-unreadable-setting-not-reverted-row-kept",
                lock_has(sb, "setting", "kiro-cli/chat.defaultAgent", '"my_agent"') and "chat.defaultAgent my_agent" not in stub.calls(),
                "an uninstall that cannot read chat.defaultAgent does not revert it and keeps its lock row")


def own_check_revert(c, box, R, stub):
    c.check("second-uninstall-exit0", R.rc == 0, R.tail)
    if stub.used:
        c.check("later-uninstall-reverts-setting-and-lock-goes",
                rx(stub.calls(), r"^settings --global chat\.defaultAgent my_agent$") and stub.value() == '"my_agent"'
                and not os.path.isfile(lock_path(box.home)),
                "a later uninstall reverts chat.defaultAgent to the value setup replaced, and the lock goes")


def own_plant_nolock(box):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    os.makedirs(os.path.join(sb, ".agent-playbook"), exist_ok=True)
    wt(lock_path(sb), "# agent-playbook deploy lock v1 (written by setup; kind<TAB>path<TAB>sha256)\n"
                      "copy-file\t~/.kiro/..\\..\\Documents\\x\t%s\n" % ("0" * 64))
    cp(lock_path(sb), box.aux("bad-lock"))
    for n in ("plan-process.md", "run-process.md"):
        cp(os.path.join(REPO, "shared", "skills", "qtest", n), os.path.join(sk, "qtest", n))
    cp(os.path.join(REPO, "providers", "kiro", "agents", "qdream_child.md"), os.path.join(k, "agents", "qdream_child.md"))
    wb(os.path.join(k, "AUTHORING.md"), rb(os.path.join(REPO, "shared", "AUTHORING.md")).upper())
    cp(os.path.join(k, "AUTHORING.md"), box.aux("authoring.upper"))
    fxs = os.path.join(REPO, "shared", "skills", "qdream", FXD)
    fxd = os.path.join(sk, "qdream", FXD)
    cp(os.path.join(fxs, "tree", "memory", "MEMORY.md"), os.path.join(fxd, "tree", "memory", "MEMORY.md"))
    wb(os.path.join(fxd, "cases.json"), rb(os.path.join(fxs, "cases.json")) + b"edited nolock\n")


def own_check_nolock(c, box, R):
    sb, k = box.home, os.path.join(box.home, ".kiro")
    sk = os.path.join(k, "skills")
    c.check("nolock-uninstall-exit0", R.rc == 0, R.tail)
    c.check("backslash-key-lock-is-no-lock-moved-to-bak", absent(lock_path(sb)) and same(lock_path(sb) + ".bak", box.aux("bad-lock")),
            "a lock with a backslash key is no lock, and it is moved to deploy-lock.tsv.bak")
    c.check("nolock-removes-generated-files-equal-to-setups", absent(os.path.join(sk, "qtest", "plan-process.md"))
            and absent(os.path.join(sk, "qtest", "run-process.md")) and same(os.path.join(sk, "qtest", "SKILL.md"), box.aux("qtest-skill.edited")),
            "with no lock, uninstall removes a generated copy's files equal to setup's output and keeps the rest")
    c.check("nolock-removes-copy-file-equal-bytes-only", absent(os.path.join(k, "agents", "qdream_child.md"))
            and same(os.path.join(k, "AUTHORING.md"), box.aux("authoring.upper")),
            "with no lock, uninstall removes a copy-file equal to its source byte for byte, and only then")
    c.check("nolock-leaves-your-files", own_is(os.path.join(sk, "qreview", "SKILL.md"), "user qreview")
            and own_is(os.path.join(sk, "qreview", "my-own.md"), "my own"), "with no lock, uninstall leaves your own files alone")
    fxd = os.path.join(sk, "qdream", FXD)
    c.check("nolock-fixtures-equal-source-removed-edited-kept", absent(os.path.join(fxd, "tree", "memory", "MEMORY.md"))
            and os.path.isfile(os.path.join(fxd, "cases.json")) and "edited nolock" in (rt(os.path.join(fxd, "cases.json")) or ""),
            "with no lock, uninstall removes an older copy's fixtures/ file equal to its source and keeps an edited one")


def scenario_ownership(c):
    box = Box(c)
    try:
        r0 = box.run()    # the deployed sandbox (SETUP-VERIFY's), no kiro-cli setting
        c.check("deploy-exit0", r0.rc == 0, r0.tail)
        stub = Stub(box.root)
        box.stub = stub
        if not stub.used:
            c.skip("stub", "kiro-cli does not resolve to the stub here (got %r); its chat.defaultAgent checks are skipped" % (stub.got,))
        stub.state('"my_agent"', "ok")
        # 1. collisions, and chat.defaultAgent set
        own_plant(box)
        R = box.run("--providers", "kiro", use_stub=True)
        own_check_deploy(c, box, R, stub)
        # 2. a re-run writes nothing
        stub.state("", "ok")
        s1 = snapshot(box.home)
        R = box.run("--providers", "kiro", use_stub=True)
        s2 = snapshot(box.home)
        c.check("rerun-exit0", R.rc == 0, R.tail)
        c.check("rerun-writes-nothing", s1 == s2, lambda: "changed: %s" % [d.split("\t")[0] for d in sorted(set(s1) ^ set(s2))[:8]])
        if stub.used:
            c.check("rerun-setting-not-set-again-row-kept", "chat.defaultAgent kiro_default" not in stub.calls()
                    and lock_has(box.home, "setting", "kiro-cli/chat.defaultAgent", '"my_agent"'),
                    "a chat.defaultAgent that is kiro_default already is not set again, and its row is kept")
        # 3. a backup that cannot be made, a .bak that is not setup's, a later backup, an unreadable setting
        release, skip = own_plant_hold(box)
        stub.state("", "fail-read")
        try:
            R = box.run("--providers", "kiro", use_stub=True)
        finally:
            release()
        own_check_hold(c, box, R, stub, skip)
        # 4. uninstall, the setting unreadable; 5. uninstall again, the setting reverted
        own_plant_uninstall(box, stub)
        R = box.run("--uninstall", "--providers", "kiro", use_stub=True)
        own_check_uninstall(c, box, R, stub)
        stub.state("", "ok")
        R = box.run("--uninstall", "--providers", "kiro", use_stub=True)
        own_check_revert(c, box, R, stub)
        # 6. uninstall with an unreadable lock
        own_plant_nolock(box)
        R = box.run("--uninstall", "--providers", "kiro", use_stub=True)
        own_check_nolock(c, box, R)
    finally:
        box.close()


def scenario_ownership_memlink(c):
    """A sandboxed HOME never writes the repo's memory link: a --yes dry run prints the SKIPPED line."""
    box = Box(c)
    try:
        R = box.run("--dry-run", "--yes")
        m = re.search(r"^  SKIPPED: (.*) \(HOME is sandboxed; the repo.s memory link is never written from a sandbox\)$", R.out, re.M)
        lp = m.group(1) if m else None
        c.check("sandboxed-home-skips-memory-link", R.rc == 0 and lp is not None and ("LINKED: %s " % lp) not in R.out
                and ("UPDATE: %s " % lp) not in R.out, lambda: "link: %s; %s" % (lp, R.tail(4)))
    finally:
        box.close()


# --- scenario: coexist -------------------------------------------------------------------------------------

CX_C_PRIOR = '{"context": {"fileName": "Ünï-名前.md"}}'
CX_C_ADDED = '{"context": {"fileName": ["Ünï-名前.md", "AGENT-PLAYBOOK.md"]}}'
CX_JSONC = '{\n  // my own Gemini settings\n  "theme": "dark"\n}'
NAMES = ["GEMINI.md", "AGENT-PLAYBOOK.md"]


def have_memory():
    return os.path.exists(os.path.join(REPO, "memory", "MEMORY.md")) and os.path.exists(os.path.join(REPO, "memory", "HIGHER_ORDER.md"))


def jload(p):
    t = rt(p)
    try:
        return json.loads(t)
    except (TypeError, ValueError):
        return None


def jok(p, fn):
    d = jload(p)
    if d is None:
        return False
    try:
        return bool(fn(d))
    except (KeyError, TypeError, IndexError):
        return False


def cx_plant(box, fx):
    sb = box.home
    wt(os.path.join(sb, ".gemini", "GEMINI.md"), "my gemini\n")
    if fx == "a":
        wt(os.path.join(sb, ".claude", "CLAUDE.md"), "my claude\n")
        wt(os.path.join(sb, ".codex", "AGENTS.md"), "my codex\n")
        wt(os.path.join(sb, ".gemini", "settings.json"), '{\n    "context": {"fileName": "GEMINI.md"},\n    "keep": 1\n}\n')
    elif fx == "b":
        if not os.path.exists(os.path.join(REPO, "memory", "MEMORY.md")):
            # no user memory (CI): a memory rules link an earlier run made, dangling now
            try:
                make_link(os.path.join(REPO, "memory", "MEMORY.md"), os.path.join(sb, ".claude", "rules", "playbook-user-memory.md"), False)
            except OSError:
                pass
    elif fx == "c":
        wt(os.path.join(sb, ".claude", "CLAUDE.md"), "my claude\n")
        wt(os.path.join(sb, ".gemini", "settings.json"), CX_C_PRIOR + "\n")
    elif fx == "d":
        wt(os.path.join(sb, ".gemini", "settings.json"), CX_JSONC + "\n")
    elif fx == "e":
        wt(os.path.join(sb, ".gemini", "settings.json"), '{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}\n')
    elif fx == "f":
        wt(os.path.join(sb, "dotfiles", "claude.md"), "my dotfiles claude\n")
        make_link(os.path.join(sb, "dotfiles", "claude.md"), os.path.join(sb, ".claude", "CLAUDE.md"), False)
        wt(os.path.join(sb, "dotfiles", "gemini-settings.json"), '{"keep": 1}\n')
        make_link(os.path.join(sb, "dotfiles", "gemini-settings.json"), os.path.join(sb, ".gemini", "settings.json"), False)


def cx_settings_file(box, fx):
    return os.path.join(box.home, "dotfiles", "gemini-settings.json") if fx == "f" else os.path.join(box.home, ".gemini", "settings.json")


def cx_check_deploy(c, box, fx, R):
    sb = box.home
    lock = lock_text(sb)
    gs = os.path.join(sb, ".gemini", "settings.json")
    n = "%s/" % fx
    mem_ul = os.path.join(sb, ".claude", "rules", "playbook-user-memory.md")
    mem_ho = os.path.join(sb, ".claude", "rules", "playbook-higher-order.md")
    if have_memory():
        c.check(n + "memory-rules-links", link_to(mem_ul, "memory/MEMORY.md") and link_to(mem_ho, "memory/HIGHER_ORDER.md"),
                "the Claude memory rules links point to memory/MEMORY.md and memory/HIGHER_ORDER.md")
    else:
        c.check(n + "no-dangling-memory-rules-link", absent(mem_ul) and R.has(r"playbook-user-memory.md is not linked yet"),
                "with no user memory, no dangling memory rules link is made, and setup says so")
        if fx == "b":
            c.check(n + "dangling-link-removed", R.has(r"playbook-user-memory.md \(dangling: there is no"),
                    "a dangling memory rules link an earlier run made is removed, and setup says so")
    c.check(n + "your-gemini-md-stays-side-link-made", own_is(os.path.join(sb, ".gemini", "GEMINI.md"), "my gemini")
            and link_to(os.path.join(sb, ".gemini", "AGENT-PLAYBOOK.md"), "shared/AGENTS.md")
            and absent(os.path.join(sb, ".gemini", "GEMINI.md.bak")), "your GEMINI.md stays (no .bak) and AGENT-PLAYBOOK.md links beside it")
    c.check(n + "lock-write-removes-journal", absent(journal_path(sb)), "the lock write removes the journal")
    want = 1
    if fx == "a":
        c.check(n + "agent-playbook-joins-context-filename", jok(gs, lambda d: d["context"]["fileName"] == NAMES), "AGENT-PLAYBOOK.md joins context.fileName")
        c.check(n + "your-claude-md-stays-rules-link-beside", own_is(os.path.join(sb, ".claude", "CLAUDE.md"), "my claude")
                and link_to(os.path.join(sb, ".claude", "rules", "agent-playbook.md"), "shared/AGENTS.md")
                and R.has(r"CLAUDE.md is your own file"), "your CLAUDE.md stays and ~/.claude/rules/agent-playbook.md links beside it, said once")
        c.check(n + "codex-has-no-coexistence", link_to(os.path.join(sb, ".codex", "AGENTS.md"), "shared/AGENTS.md")
                and own_is(os.path.join(sb, ".codex", "AGENTS.md.bak"), "my codex")
                and R.has(r"Codex has no way to load a second global instructions file"),
                "Codex has no co-existence: your AGENTS.md goes to .bak, the link is made, and setup says so")
        c.check(n + "settings-edit-keeps-other-keys", jok(gs, lambda d: d["keep"] == 1 and len(d) == 2), "the settings.json edit keeps every other key")
        c.check(n + "lock-records-prior-and-codex-backup", lock_has(sb, "setting", "gemini/context.fileName", '"GEMINI.md"')
                and lock_has(sb, "backup", "~/.codex/AGENTS.md"), "the lock records the prior context.fileName and the Codex backup")
    elif fx in ("b", "g"):
        c.check(n + "agent-playbook-joins-context-filename", jok(gs, lambda d: d["context"]["fileName"] == NAMES), "AGENT-PLAYBOOK.md joins context.fileName")
        c.check(n + "empty-claude-md-path-linked-no-rules-link",
                link_to(os.path.join(sb, ".claude", "CLAUDE.md"), "shared/AGENTS.md")
                and absent(os.path.join(sb, ".claude", "rules", "agent-playbook.md")),
                "an empty CLAUDE.md path is linked as before, with no rules link beside it")
        c.check(n + "lock-records-plus-setup-created-settings", lock_has(sb, "setting", "gemini/context.fileName", "+"),
                "with no settings.json, the lock records + (setup created it)")
        if fx == "g":
            c.check(n + "first-run-creates-venv", R.has(r"CREATED: ") and os.path.isdir(os.path.join(box.root, "g.venv")),
                    "the first run with no venv creates it (in the test folder)")
    elif fx == "c":
        c.check(n + "agent-playbook-joins-non-ascii-filename", (rt(gs) or "").rstrip("\n") == CX_C_ADDED,
                lambda: "got %s" % rt(gs))
        c.check(n + "lock-records-non-ascii-prior", lock_has(sb, "setting", "gemini/context.fileName", '"Ünï-名前.md"'),
                "the lock records the non-ASCII prior as UTF-8 JSON")
        c.check(n + "claude-rules-link-beside-your-file", link_to(os.path.join(sb, ".claude", "rules", "agent-playbook.md"), "shared/AGENTS.md"),
                "the Claude rules link is made beside your CLAUDE.md")
    elif fx == "d":
        c.check(n + "jsonc-settings-left-as-it-was", (rt(gs) or "").rstrip("\n") == CX_JSONC, "a settings.json with comments is left as it was")
        c.check(n + "note-gives-exact-line-to-add", 'add "AGENT-PLAYBOOK.md" to context.fileName in ~/.gemini/settings.json by hand' in R.out,
                "a NOTE gives the exact line to add by hand")
        want = 0
    elif fx == "e":
        c.check(n + "list-already-holding-name-not-written",
                (rt(gs) or "").rstrip("\n") == '{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}',
                "a list that already holds the name is not written")
        want = 0
    elif fx == "f":
        c.check(n + "linked-settings-written-through-link", is_link(gs) and jok(cx_settings_file(box, "f"), lambda d: d["context"]["fileName"] == NAMES)
                and jok(cx_settings_file(box, "f"), lambda d: d["keep"] == 1), "a linked settings.json is written through the link, and the link stays")
        c.check(n + "dotfiles-claude-md-link-kept", link_to(os.path.join(sb, ".claude", "CLAUDE.md"), "dotfiles/claude.md")
                and (rt(os.path.join(sb, ".claude", "CLAUDE.md")) or "").rstrip("\n") == "my dotfiles claude"
                and absent(os.path.join(sb, ".claude", "CLAUDE.md.bak"))
                and link_to(os.path.join(sb, ".claude", "rules", "agent-playbook.md"), "shared/AGENTS.md"),
                "your CLAUDE.md linked from your dotfiles stays (no .bak), the rules link beside it")
        c.check(n + "lock-records-minus-no-value", lock_has(sb, "setting", "gemini/context.fileName", "-"), "the lock records - (the file held no value)")
    nrows = len([l for l in lock.split("\n") if l.startswith("setting\t")])
    c.check(n + "setting-row-count", nrows == want, "%d setting row(s) in the lock (got %d)" % (want, nrows))


def cx_verify(c, box, fx, tag=None):
    v = box.verify()
    n = "%s/" % (tag or fx)
    if fx == "d":
        c.check(n + "verify-missing-setting-line-no-double-load",
                v.rc == 1 and rx(v.out, r"^MISSING\t.*settings.json\tcontext.fileName-lacks=AGENT-PLAYBOOK.md")
                and rx(v.out, r"^NOT_SYMLINK\t.*GEMINI.md\tuser-file-kept-without-the-playbook") and not rx(v.out, r"^DRIFTED\t"),
                lambda: "verify exit=%s %s" % (v.rc, BAD_VERIFY.findall(v.out)[:5]))
    elif tag == "c2":
        c.check(n + "verify-clean", v.rc == 0, lambda: "verify exit=%s %s" % (v.rc, [l for l in v.out.split("\n") if BAD_VERIFY.match(l + "")][:5]))
    else:
        c.check(n + "verify-clean", v.rc == 0 and rx(v.out, r"^OK\t.*GEMINI.md\tuser-file-kept"),
                lambda: "verify exit=%s %s" % (v.rc, [l for l in v.out.split("\n") if BAD_VERIFY.match(l)][:5]))


def cx_check_uninstall(c, box, fx):
    sb = box.home
    n = "%s/" % fx
    c.check(n + "uninstall-removes-side-and-memory-links-and-empty-rules-folder",
            absent(os.path.join(sb, ".gemini", "AGENT-PLAYBOOK.md")) and absent(os.path.join(sb, ".claude", "rules", "playbook-user-memory.md"))
            and absent(os.path.join(sb, ".claude", "rules", "playbook-higher-order.md")) and absent(os.path.join(sb, ".claude", "rules")),
            "uninstall removes the side and memory rules links, and the rules folder left empty")
    if fx != "c":
        c.check(n + "uninstall-keeps-your-gemini-md", own_is(os.path.join(sb, ".gemini", "GEMINI.md"), "my gemini"), "uninstall keeps your GEMINI.md")
    c.check(n + "uninstall-drops-context-filename-row", (not os.path.isfile(lock_path(sb)) or "gemini/context.fileName" not in lock_text(sb))
            and absent(journal_path(sb)), "uninstall drops the context.fileName row from the lock and the journal")
    gs = os.path.join(sb, ".gemini", "settings.json")
    if fx == "a":
        c.check(n + "uninstall-never-touches-your-claude-md", own_is(os.path.join(sb, ".claude", "CLAUDE.md"), "my claude"), "uninstall never touches your CLAUDE.md")
        c.check(n + "uninstall-restores-codex-agents-md", own_is(os.path.join(sb, ".codex", "AGENTS.md"), "my codex")
                and absent(os.path.join(sb, ".codex", "AGENTS.md.bak")), "uninstall restores your Codex AGENTS.md from its .bak")
        c.check(n + "uninstall-restores-context-filename-string",
                jok(gs, lambda d: d == {"context": {"fileName": "GEMINI.md"}, "keep": 1}),
                "uninstall takes the playbook's name out of context.fileName and restores the string")
    elif fx in ("b", "g"):
        c.check(n + "uninstall-removes-claude-md-link", absent(os.path.join(sb, ".claude", "CLAUDE.md")), "uninstall removes the CLAUDE.md link")
        c.check(n + "uninstall-deletes-settings-setup-created", absent(gs), "uninstall deletes the settings.json setup created (b: from the journal row)")
    elif fx == "c":
        c.check(n + "uninstall-removes-claude-and-gemini-links", absent(os.path.join(sb, ".claude", "CLAUDE.md"))
                and absent(os.path.join(sb, ".gemini", "GEMINI.md")), "uninstall removes the CLAUDE.md and GEMINI.md links")
        c.check(n + "uninstall-leaves-settings-as-it-was", (rt(gs) or "").rstrip("\n") == CX_C_PRIOR, "uninstall leaves settings.json as it was")
    elif fx == "d":
        c.check(n + "uninstall-leaves-settings-as-it-was", (rt(gs) or "").rstrip("\n") == CX_JSONC, "uninstall leaves settings.json as it was")
    elif fx == "e":
        c.check(n + "uninstall-leaves-name-setup-did-not-add",
                (rt(gs) or "").rstrip("\n") == '{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}',
                "uninstall leaves a name setup did not add")
    elif fx == "f":
        c.check(n + "uninstall-restores-linked-file-keeps-link", is_link(gs)
                and (rt(os.path.join(sb, "dotfiles", "gemini-settings.json")) or "").rstrip("\n") == '{"keep": 1}',
                "uninstall restores the linked file and keeps the link")
        c.check(n + "uninstall-keeps-your-linked-claude-md", link_to(os.path.join(sb, ".claude", "CLAUDE.md"), "dotfiles/claude.md"),
                "uninstall keeps your linked CLAUDE.md")


def scenario_coexist(fx):
    def run(c):
        box = Box(c)
        try:
            n = "%s/" % fx
            cx_plant(box, fx)
            venv = os.path.join(box.root, "g.venv") if fx == "g" else None
            args = ["--providers", PROVIDERS3]
            if fx == "g":
                s0 = snapshot(box.home)
                R = box.run("--dry-run", *args, venv=venv)
                c.check(n + "dry-run-exit0", R.rc == 0, R.tail)
                c.check(n + "dry-run-no-venv-writes-nothing-says-venv-first", snapshot(box.home) == s0 and absent(venv)
                        and R.has(r"DRY: the venv is created first; then AGENT-PLAYBOOK.md is added to context.fileName"),
                        "a dry run with no venv writes nothing and says the venv is created first")
            R = box.run(*args, venv=venv)
            c.check(n + "run1-exit0", R.rc == 0, R.tail)
            cx_check_deploy(c, box, fx, R)
            cx_verify(c, box, fx)
            snap1 = snapshot(box.home)
            if fx == "c":
                # the transition: your own files go away before run 2; a dry run first prints the cleanup
                for p in (os.path.join(box.home, ".gemini", "GEMINI.md"), os.path.join(box.home, ".claude", "CLAUDE.md")):
                    if os.path.lexists(p):
                        os.unlink(p)
                sd = snapshot(box.home)
                R = box.run("--dry-run", *args, venv=venv)
                c.check(n + "dry-run-exit0", R.rc == 0, R.tail)
                c.check(n + "dry-run-prints-cleanup-writes-nothing", snapshot(box.home) == sd
                        and R.has(r"DRY: remove AGENT-PLAYBOOK.md from context.fileName") and not R.has(r"^  REMOVED: "),
                        "a dry run prints DRY for the context.fileName cleanup and writes nothing")
            R = box.run(*args, venv=venv)
            c.check(n + "run2-exit0", R.rc == 0, R.tail)
            if fx == "c":
                sb = box.home
                c.check(n + "transition-gemini-md-linked-side-link-removed", link_to(os.path.join(sb, ".gemini", "GEMINI.md"), "shared/AGENTS.md")
                        and absent(os.path.join(sb, ".gemini", "AGENT-PLAYBOOK.md")),
                        "with your GEMINI.md gone, GEMINI.md is linked and the side link removed")
                c.check(n + "transition-claude-md-linked-rules-link-removed", link_to(os.path.join(sb, ".claude", "CLAUDE.md"), "shared/AGENTS.md")
                        and absent(os.path.join(sb, ".claude", "rules", "agent-playbook.md")),
                        "with your CLAUDE.md gone, CLAUDE.md is linked and the rules link removed")
                c.check(n + "transition-context-filename-entry-taken-out",
                        (rt(os.path.join(sb, ".gemini", "settings.json")) or "").rstrip("\n") == CX_C_PRIOR,
                        lambda: "got %s" % rt(os.path.join(sb, ".gemini", "settings.json")))
                c.check(n + "transition-lock-drops-context-filename-row", "gemini/context.fileName" not in lock_text(sb),
                        "the lock drops the context.fileName row")
                cx_verify(c, box, fx, tag="c2")
            else:
                snap2 = snapshot(box.home)
                c.check(n + "second-run-writes-nothing", snap1 == snap2,
                        lambda: "a second run with co-existence active wrote: %s" % [d.split("\t")[0] for d in sorted(set(snap1) ^ set(snap2))[:8]])
            if fx == "b":
                # a run that stopped after editing settings.json, before writing its lock: the row in the journal only
                lock = lock_text(box.home)
                rows = [l for l in lock.split("\n") if l.startswith("setting\tgemini/context.fileName\t")]
                c.check(n + "lock-holds-context-filename-row-before-interruption", bool(rows),
                        "the lock holds the context.fileName row before the interruption")
                wt(journal_path(box.home), "".join(r + "\n" for r in rows))
                wt(lock_path(box.home), "".join(l + "\n" for l in lock.split("\n") if l and l not in rows))
            R = box.run("--uninstall", *args, venv=venv)
            c.check(n + "uninstall-exit0", R.rc == 0, R.tail)
            cx_check_uninstall(c, box, fx)
        finally:
            box.close()
    return run


def scenario_coexist_h(c):
    """A folder at the lock path stops the run before any change; a file at ~/.gemini/skills stops it
    after the settings edit; the next run records the journalled row."""
    box = Box(c)
    try:
        sb = box.home
        wt(os.path.join(sb, ".gemini", "GEMINI.md"), "my gemini\n")
        os.makedirs(lock_path(sb))
        R = box.run("--providers", "gemini")
        c.check("run0-nonzero-before-any-change", R.rc not in (0, None) and absent(os.path.join(sb, ".gemini", "settings.json"))
                and absent(os.path.join(sb, ".gemini", "AGENT-PLAYBOOK.md")) and not os.listdir(lock_path(sb))
                and R.has(r"deploy-lock.tsv is not a file; setup stopped before any change"),
                "a folder at the lock path stops the run before any change, with an ERROR; " + R.tail(4))
        os.rmdir(lock_path(sb))
        wt(os.path.join(sb, ".gemini", "skills"), "not a folder\n")
        R = box.run("--providers", "gemini")
        j = rt(journal_path(sb)) or ""
        c.check("run1-stops-after-settings-edit", R.rc not in (0, None) and rx(j, r"^setting\tgemini/context\.fileName\t\+$")
                and jok(os.path.join(sb, ".gemini", "settings.json"), lambda d: d["context"]["fileName"] == NAMES)
                and R.has(r"skills is a file, not a folder; setup stopped here")
                and (rt(os.path.join(sb, ".gemini", "skills")) or "").rstrip("\n") == "not a folder"
                and not [f for f in os.listdir(os.path.join(sb, ".agent-playbook")) if f.startswith("deploy-lock.tsv.tmp-")],
                "a file at ~/.gemini/skills stops the run with an ERROR, keeps the file and leaves the setting row in the lock journal; " + R.tail(4))
        os.unlink(os.path.join(sb, ".gemini", "skills"))
        R = box.run("--providers", "gemini")
        c.check("run2-records-journalled-row", R.rc == 0 and lock_has(sb, "setting", "gemini/context.fileName", "+") and absent(journal_path(sb)),
                "the next run records the journalled setting row in the lock; " + R.tail(4))
    finally:
        box.close()


def scenario_coexist_i(c):
    """A helper that prints a success line and then exits 1 is not trusted."""
    box = Box(c)
    try:
        sb = box.home
        wt(os.path.join(sb, ".gemini", "GEMINI.md"), "my gemini\n")
        stub = box.aux("crash-helper.py")
        wt(stub, 'import sys\nprint("added prior=-")\nsys.exit(1)\n')
        R = box.run("--providers", "gemini", helper=stub)
        rows = (lock_text(sb) + (rt(journal_path(sb)) or ""))
        c.check("helper-exit1-not-trusted", R.rc == 0 and own_is(os.path.join(sb, ".gemini", "GEMINI.md"), "my gemini")
                and not is_link(os.path.join(sb, ".gemini", "GEMINI.md")) and link_to(os.path.join(sb, ".gemini", "AGENT-PLAYBOOK.md"), "shared/AGENTS.md")
                and absent(os.path.join(sb, ".gemini", "settings.json")) and "setting\t" not in rows
                and 'cannot be edited (the helper failed (exit 1)); add "AGENT-PLAYBOOK.md" to context.fileName' in R.out,
                "a helper that exits 1 is not trusted: GEMINI.md kept, side link made, no setting row, the NOTE names the exit code; " + R.tail(4))
    finally:
        box.close()


# --- scenarios: the bootstraps ---------------------------------------------------------------------------------

# setup.ps1 is the Windows bootstrap: its cases run on Windows only, even where a pwsh exists (CI Linux)
PWSH = shutil.which("pwsh") if WIN else None
if WIN:
    BASH = r"C:\Program Files\Git\bin\bash.exe"
    if not os.path.isfile(BASH):
        BASH = None
else:
    BASH = shutil.which("bash")


def is_bootstrap(name):
    t = rt(os.path.join(BOOT_DIR, name)) or ""
    return "setup/setup.py" in t or "setup\\setup.py" in t


def boot_cmd(shell, args):
    if shell == "ps1":
        return [PWSH, "-NoProfile", "-NonInteractive", "-File", os.path.join(BOOT_DIR, "setup.ps1")] + list(args)
    script = os.path.join(BOOT_DIR, "setup.sh")
    return [BASH, script.replace("\\", "/") if WIN else script] + list(args)


SPELL = {
    "ps1": dict(dry=["-DryRun"], providers=["-Providers", "kiro"], nostores=["-NoStores"], url=["-StoresUrl", "https://example.invalid/stores.git"],
                yes=["-Yes"], uninstall=["-Uninstall", "-Purge"], help=["-Help"]),
    "sh": dict(dry=["--dry-run"], providers=["--providers", "kiro"], nostores=["--no-stores"], url=["--stores-url", "https://example.invalid/stores.git"],
               yes=["--yes"], uninstall=["--uninstall", "--purge"], help=["--help"]),
}
SECTIONS = ("=== Claude Code ===", "=== Codex ===", "=== Gemini CLI ===", "=== Kiro CLI ===")


def boot_scenario(shell, case):
    shell_ok = PWSH if shell == "ps1" else BASH

    def run(c):
        if not shell_ok:
            c.skip(case, ("setup.ps1 is the Windows bootstrap" if not WIN else "no pwsh here") if shell == "ps1" else "no Git Bash here")
            return
        sp = SPELL[shell]
        box = Box(c)
        try:
            def go(args, path=None):
                return box.raw(boot_cmd(shell, args), path=path)

            def nopy():
                return box.no_python_path() if shell == "sh" else no_python_path()

            def untouched():
                return not snapshot(box.home)
            if case == "dry-run":
                R = go(sp["dry"])
                c.check(case, R.rc == 0 and R.has(r"DRY RUN") and untouched(), lambda: "written: %s; %s" % (snapshot(box.home)[:3], R.tail(4)))
            elif case == "providers-kiro":
                forms = [sp["providers"]] + ([["--providers=kiro"]] if shell == "sh" else [])
                for f in forms:
                    R = go(sp["dry"] + f)
                    only_kiro = R.has(re.escape(SECTIONS[3])) and not any(s in R.out for s in SECTIONS[:3])
                    c.check("%s (%s)" % (case, " ".join(f)), R.rc == 0 and only_kiro and untouched(), R.tail)
            elif case == "no-stores":
                R = go(sp["dry"] + sp["nostores"])
                c.check(case, R.rc == 0 and R.has(r"SKIPPED: store repo") and not R.has(r"CREATE: |CLONE: "), R.tail)
            elif case == "stores-url":
                R = go(sp["dry"] + sp["url"])
                c.check(case, R.rc == 0 and R.has(r"CLONE: https://example\.invalid/stores\.git -> "), R.tail)
            elif case == "yes":
                for f in ([sp["yes"]] + ([["-y"]] if shell == "sh" else [])):
                    R = go(sp["dry"] + f)
                    c.check("%s (%s)" % (case, " ".join(f)), R.rc == 0 and R.has(r"CREATE: .* \(a new local store repo") and untouched(), R.tail)
            elif case == "uninstall-purge":
                R = go(sp["dry"] + sp["uninstall"])
                c.check(case, R.rc == 0 and R.has(r"=== Uninstall: ") and not R.has(r"KEPT: .*the memory link and the store repo")
                        and untouched(), R.tail)
            elif case == "help":
                R = go(sp["help"], path=nopy())
                c.check(case, R.rc == 0 and R.has(r"Usage:") and R.has(re.escape("-Providers" if shell == "ps1" else "--providers")), R.tail)
            elif case == "no-python":
                if not is_bootstrap("setup.ps1" if shell == "ps1" else "setup.sh"):
                    c.skip(case, "%s is not a bootstrap yet (it does not run setup/setup.py)" % ("setup.ps1" if shell == "ps1" else "setup.sh"))
                else:
                    R = go(sp["dry"], path=nopy())
                    c.check(case, R.rc == 2 and R.has(r"needs Python 3\.8\+"), R.tail)
                    c.check(case + "-names-the-deploy-lock", R.has(r"\.agent-playbook[\\/]deploy-lock\.tsv")
                            and os.path.basename(box.root) in R.out, R.tail)
                    c.check(case + "-names-the-readme-uninstall-section", R.has(r"README\.md \(Uninstall\) says how to remove it by hand"), R.tail)
        finally:
            box.close()
    return run


# --- scenarios: behaviors added after the bash suite -----------------------------------------------------------

def tree_digest(home):
    """Every entry under home with its content (a file's sha, a link's text) and mtime: a byte-for-byte
    picture of the tree."""
    out = []
    for d, dirs, files in os.walk(home):
        for n in dirs + files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, home).replace(os.sep, "/")
            st = os.lstat(p)
            if os.path.islink(p):
                what = "link:" + (link_text(p) or "")
            elif os.path.isdir(p):
                what = "dir"
            else:
                what = "file:" + (sha(p) or "")
            out.append((rel, what, st.st_mtime_ns))
    return sorted(out)


def find_baks(home):
    out = []
    for d, dirs, files in os.walk(home):
        for n in dirs + files:
            if n.endswith(".bak"):
                out.append(os.path.relpath(os.path.join(d, n), home))
    return out


def scenario_beh_uninstall_no_venv(c):
    """--uninstall never builds the venv: a venv folder that does not exist yet stays absent."""
    box = Box(c)
    try:
        venv = box.aux("nv.venv")
        R = box.run("--uninstall", venv=venv)
        c.check("uninstall-exit0", R.rc == 0, R.tail)
        c.check("uninstall-leaves-missing-venv-absent", absent(venv), "--uninstall created the venv folder %s" % venv)
        R = box.run("--dry-run", venv=venv)
        c.check("dry-run-leaves-missing-venv-absent", R.rc == 0 and absent(venv), "--dry-run created the venv folder")
    finally:
        box.close()


def scenario_beh_dry_run_conflicts(c):
    """A --dry-run over files of yours in the way moves nothing, makes no .bak and writes no lock."""
    box = Box(c)
    try:
        sb = box.home
        steer = os.path.join(sb, ".kiro", "steering", "agents.md")
        codex = os.path.join(sb, ".codex", "AGENTS.md")
        wt(steer, "mine steering\n")
        wt(codex, "mine codex\n")
        before, snap_before = tree_digest(sb), snapshot(sb)
        R = box.run("--dry-run")
        c.check("fresh-dry-run-exit0", R.rc == 0 and R.has(r"BACKUP: "), R.tail)
        c.check("fresh-dry-run-moves-nothing", tree_digest(sb) == before and snapshot(sb) == snap_before and not find_baks(sb),
                lambda: "changed: %s; baks: %s" % ([d[0] for d in sorted(set(tree_digest(sb)) ^ set(before))[:6]], find_baks(sb)))
        c.check("fresh-dry-run-writes-no-lock", absent(lock_path(sb)) and absent(journal_path(sb)), "a lock or journal was written")
        # the same over a deployed home (a lock exists) with the conflicts planted afterwards
        R = box.run()
        c.check("deploy-exit0", R.rc == 0, R.tail)
        for p in (steer, codex):
            os.unlink(p)
            wt(p, "mine again\n")
        lock_before = rb(lock_path(sb))
        baks_before = find_baks(sb)
        before, snap_before = tree_digest(sb), snapshot(sb)
        R = box.run("--dry-run")
        c.check("deployed-dry-run-exit0", R.rc == 0 and R.has(r"BACKUP: "), R.tail)
        c.check("deployed-dry-run-moves-nothing", tree_digest(sb) == before and snapshot(sb) == snap_before and find_baks(sb) == baks_before,
                lambda: "changed: %s; baks: %s" % ([d[0] for d in sorted(set(tree_digest(sb)) ^ set(before))[:6]], find_baks(sb)))
        c.check("deployed-dry-run-lock-and-journal-unchanged", rb(lock_path(sb)) == lock_before and absent(journal_path(sb)),
                "the lock changed or a journal appeared")
    finally:
        box.close()


def scenario_beh_decoy_home(c):
    """Windows: HOME names a decoy folder, USERPROFILE the sandbox; setup reads USERPROFILE."""
    if not WIN:
        c.skip("decoy-home", "Windows only: elsewhere setup reads HOME")
        return
    box = Box(c)
    try:
        decoy = box.aux("decoy-home")
        os.makedirs(decoy)
        R = box.run("--providers", "claude,codex", extra={"HOME": decoy})
        c.check("deploy-exit0", R.rc == 0, R.tail)
        c.check("deploy-landed-in-userprofile", os.path.isdir(os.path.join(box.home, ".claude")) and bool(os.listdir(os.path.join(box.home, ".claude"))),
                "nothing deployed under USERPROFILE")
        c.check("decoy-home-stays-empty", os.listdir(decoy) == [], lambda: "written into HOME: %s" % os.listdir(decoy))
    finally:
        box.close()


def scenario_beh_readonly_lock(c):
    """Windows: a read-only deploy lock ends the run with exit 1, the backup row waits in the journal, the
    next run merges it and treats the .bak as setup's."""
    if not WIN:
        c.skip("readonly-lock", "Windows only: elsewhere a read-only file is replaced by a rename")
        return
    box = Box(c)
    try:
        sb = box.home
        k = os.path.join(sb, ".kiro")
        R = box.run("--providers", "kiro")
        c.check("deploy-exit0", R.rc == 0, R.tail)
        wt(os.path.join(k, "AUTHORING.md"), "mine one\n")
        os.chmod(lock_path(sb), stat.S_IREAD)
        try:
            R = box.run("--providers", "kiro")
        finally:
            os.chmod(lock_path(sb), stat.S_IREAD | stat.S_IWRITE)
        c.check("readonly-lock-exit1-could-not-write", R.rc == 1 and R.has(r"could not write .*deploy-lock\.tsv"), R.tail)
        c.check("journal-holds-the-backup-row", rx(rt(journal_path(sb)), r"^backup\t~/\.kiro/AUTHORING\.md\t[0-9a-f]{64}$")
                and own_is(os.path.join(k, "AUTHORING.md.bak"), "mine one"), "the journal lacks the backup row")
        R = box.run("--providers", "kiro")
        c.check("next-run-merges-the-journal", R.rc == 0 and R.has(r"NOTE: merged the rows an interrupted run recorded in ")
                and lock_has(sb, "backup", "~/.kiro/AUTHORING.md") and absent(journal_path(sb)), R.tail)
        wt(os.path.join(k, "AUTHORING.md"), "mine two\n")
        R = box.run("--providers", "kiro")
        c.check("the-bak-is-treated-as-setups", R.rc == 0 and not R.has(r"is not a backup setup made")
                and own_is(os.path.join(k, "AUTHORING.md.bak"), "mine two"), R.tail)
    finally:
        box.close()


def scenario_beh_edited_bak(c):
    """A .bak edited after setup made it is not replaced: a WARN, the file beside it unchanged."""
    box = Box(c)
    try:
        sb = box.home
        k = os.path.join(sb, ".kiro")
        a = os.path.join(k, "AUTHORING.md")
        c.check("deploy-exit0", box.run("--providers", "kiro").rc == 0, "deploy failed")
        wt(a, "mine one\n")
        R = box.run("--providers", "kiro")
        c.check("first-backup", R.rc == 0 and own_is(a + ".bak", "mine one") and lock_has(sb, "backup", "~/.kiro/AUTHORING.md", sha(a + ".bak")),
                R.tail)
        ab(a + ".bak", b"edited after setup made it\n")
        wt(a, "mine two\n")
        R = box.run("--providers", "kiro")
        c.check("edited-bak-left-alone-with-warn", R.rc == 0 and R.has(r"WARN: .*AUTHORING\.md\.bak is not a backup setup made")
                and "edited after setup made it" in (rt(a + ".bak") or "") and own_is(a, "mine two"), R.tail)
    finally:
        box.close()


def scenario_beh_folder_bak(c):
    """A folder .bak setup made earlier (lock value -) is never replaced."""
    box = Box(c)
    try:
        sb = box.home
        p = os.path.join(sb, ".claude", "AUTHORING.md")
        c.check("deploy-exit0", box.run("--providers", "claude").rc == 0, "deploy failed")
        os.unlink(p)
        wt(os.path.join(p, "inside.txt"), "folder one\n")
        R = box.run("--providers", "claude")
        c.check("folder-backed-up-with-dash-row", R.rc == 0 and own_is(os.path.join(p + ".bak", "inside.txt"), "folder one")
                and lock_has(sb, "backup", "~/.claude/AUTHORING.md", "-") and is_link(p), R.tail)
        os.unlink(p)
        wt(os.path.join(p, "inside.txt"), "folder two\n")
        R = box.run("--providers", "claude")
        c.check("folder-bak-not-replaced", R.rc == 0 and R.has(r"WARN: .*AUTHORING\.md\.bak is a folder setup moved there earlier")
                and own_is(os.path.join(p + ".bak", "inside.txt"), "folder one")
                and own_is(os.path.join(p, "inside.txt"), "folder two"), R.tail)
    finally:
        box.close()


def scenario_beh_lock_bak_kept(c):
    """An unreadable lock goes to <lock>.bak-<pid> when a .bak is already there; that .bak is kept."""
    box = Box(c)
    try:
        sb = box.home
        wt(lock_path(sb), "not a lock\n")
        wt(lock_path(sb) + ".bak", "keep me\n")
        R = box.run("--providers", "claude")
        extra = [n for n in os.listdir(os.path.dirname(lock_path(sb))) if n.startswith("deploy-lock.tsv.bak-")]
        c.check("existing-lock-bak-kept", R.rc == 0 and own_is(lock_path(sb) + ".bak", "keep me"), R.tail)
        c.check("unreadable-lock-kept-as-bak-pid", len(extra) == 1
                and own_is(os.path.join(os.path.dirname(lock_path(sb)), extra[0]), "not a lock") if extra else False,
                lambda: "files: %s" % os.listdir(os.path.dirname(lock_path(sb))))
    finally:
        box.close()


def scenario_beh_dangling_seed(c):
    """A dangling link at a seed path is not written through."""
    box = Box(c)
    try:
        seed = os.path.join(box.home, ".kiro", "settings", "mcp.json")
        nowhere = box.aux("nowhere.json")
        make_link(nowhere, seed, False)
        R = box.run("--providers", "kiro")
        c.check("dangling-seed-link-not-written-through", R.rc == 0 and absent(nowhere) and is_link(seed)
                and R.has(r"NOTE: .*mcp\.json is a link to a missing file; it is not seeded"), R.tail)
    finally:
        box.close()


def scenario_beh_purge_sandbox(c):
    """--purge from a sandboxed home never touches the repo's memory link (a dry run only, always)."""
    box = Box(c)
    try:
        R = box.run("--dry-run", "--uninstall", "--purge")
        mem = os.path.join(REPO, "memory")
        c.check("purge-prints-skipped-memory-link-line", R.rc == 0
                and R.has(re.escape("SKIPPED: " + mem + " (HOME is sandboxed; the repo's memory link is never removed from a sandbox)")), R.tail)
        c.check("purge-plans-no-rmdir-of-memory", not R.has(r"rmdir .*[\\/]memory$") and not R.has(r"REMOVED: .*memory \(link"), R.tail)
    finally:
        box.close()


def scenario_beh_stores_gitignore(c):
    """An existing <stores>/.gitignore is KEPT when --yes creates the store repo."""
    br = subprocess.run(["git", "-C", REPO, "symbolic-ref", "-q", "--short", "HEAD"], stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if br.stdout.decode("utf-8", "replace").strip() != "local-improvements":
        c.skip("stores-gitignore-kept", "--yes would switch the repo's branch: the checkout is not on local-improvements")
        return
    box = Box(c)
    try:
        stores = os.path.join(box.root, "stores")
        wt(os.path.join(stores, ".gitignore"), "mine\n")
        R = box.run("--yes", "--providers", "claude")
        c.check("stores-gitignore-kept", R.rc == 0 and R.has(r"CREATE: ") and R.has(r"KEPT: .*\.gitignore")
                and own_is(os.path.join(stores, ".gitignore"), "mine"), R.tail)
    finally:
        box.close()


def scenario_beh_journal_garbage(c):
    """A journal with one valid backup row and one garbage line merges the valid row."""
    box = Box(c)
    try:
        sb = box.home
        p = os.path.join(sb, ".claude", "AUTHORING.md")
        c.check("deploy-exit0", box.run("--providers", "claude").rc == 0, "deploy failed")
        wt(p + ".bak", "an old file of yours\n")
        wt(journal_path(sb), "backup\t~/.claude/AUTHORING.md\t%s\ngarbage line\n" % sha(p + ".bak"))
        R = box.run("--providers", "claude")
        c.check("journal-valid-row-merged-garbage-dropped", R.rc == 0 and R.has(r"NOTE: merged the rows an interrupted run recorded in ")
                and lock_has(sb, "backup", "~/.claude/AUTHORING.md", sha(p + ".bak")) and absent(journal_path(sb)), R.tail)
    finally:
        box.close()


BEHAVIORS = [("behaviors-uninstall-no-venv", scenario_beh_uninstall_no_venv),
             ("behaviors-dry-run-conflicts", scenario_beh_dry_run_conflicts),
             ("behaviors-decoy-home", scenario_beh_decoy_home),
             ("behaviors-readonly-lock", scenario_beh_readonly_lock),
             ("behaviors-edited-bak", scenario_beh_edited_bak),
             ("behaviors-folder-bak", scenario_beh_folder_bak),
             ("behaviors-lock-bak-kept", scenario_beh_lock_bak_kept),
             ("behaviors-dangling-seed", scenario_beh_dangling_seed),
             ("behaviors-purge-sandbox", scenario_beh_purge_sandbox),
             ("behaviors-stores-gitignore", scenario_beh_stores_gitignore),
             ("behaviors-journal-garbage", scenario_beh_journal_garbage)]


# --- main -------------------------------------------------------------------------------------------------

def scenarios():
    out = [("deploy", scenario_deploy), ("dry-run", scenario_dry_run), ("ownership", scenario_ownership),
           ("ownership-memlink", scenario_ownership_memlink)]
    for fx in "abcdefg":
        out.append(("coexist-" + fx, scenario_coexist(fx)))
    out.append(("coexist-h", scenario_coexist_h))
    out.append(("coexist-i", scenario_coexist_i))
    for shell in ("ps1", "sh"):
        for case in ("dry-run", "providers-kiro", "no-stores", "stores-url", "yes", "uninstall-purge", "help", "no-python"):
            out.append(("boot-%s-%s" % (shell, case), boot_scenario(shell, case)))
    return out + BEHAVIORS


def run_scenario(name, fn):
    c = Cases(name)
    t0 = time.time()
    try:
        fn(c)
    except ProfileTouched as exc:
        c.fail("real-profile-guard", str(exc))
    except Exception as exc:   # a crashed scenario fails, with where
        tb = traceback.extract_tb(sys.exc_info()[2])
        where = "%s:%d" % (os.path.basename(tb[-1].filename), tb[-1].lineno) if tb else "?"
        c.fail("scenario-crashed", "%s: %s (%s)" % (type(exc).__name__, exc, where))
    if os.environ.get("APB_TEST_TIMING"):
        print("TIMING: %s %.1fs" % (name, time.time() - t0))
    return c.rows


def main(argv=None):
    global SETUP, BOOT_DIR, VENV_DIR, VENV_PY, _BASELINE
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Scenario test for setup/setup.py")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--setup", default=None, help="the setup script to test (default: setup/setup.py beside this file)")
    ap.add_argument("--bootstraps", default=None, help="the folder holding setup.ps1 and setup.sh (default: the repo root)")
    ap.add_argument("--venv", default=None, help="the playbook venv folder (default: .venv-agent-playbook in the repo)")
    ap.add_argument("--only", default=None, help="run only the scenarios named NAME or starting with NAME")
    ns = ap.parse_args(argv)
    if ns.setup:
        SETUP = os.path.abspath(ns.setup)
    if ns.venv:
        VENV_DIR = os.path.abspath(ns.venv)
        VENV_PY = os.path.join(VENV_DIR, "Scripts", "python.exe") if WIN else os.path.join(VENV_DIR, "bin", "python")
    if ns.bootstraps:
        BOOT_DIR = os.path.abspath(ns.bootstraps)
    if not os.path.isfile(SETUP):
        print("setup scenario test: cannot run: no setup script at %s" % SETUP)
        return 2
    if not os.path.isfile(VENV_PY):
        print("setup scenario test: cannot run: no venv python at %s (verify-deployment.py needs it; run setup first)" % VENV_PY)
        return 2
    if not os.path.isfile(VERIFY):
        print("setup scenario test: cannot run: no %s" % VERIFY)
        return 2
    todo = [(n, f) for n, f in scenarios() if not ns.only or n == ns.only or n.startswith(ns.only)]
    if not todo:
        print("setup scenario test: cannot run: no scenario matches --only %s" % ns.only)
        return 2
    _BASELINE = real_profile_snapshot()
    t0 = time.time()
    lock = threading.Lock()
    total = failed = skipped = 0

    def emit(rows):
        nonlocal total, failed, skipped
        with lock:
            for status, name, why in rows:
                total += 1
                if status == "FAIL":
                    failed += 1
                elif status == "SKIP":
                    skipped += 1
                print("%s: %s%s" % (status, name, (": " + why) if why else ""))
            sys.stdout.flush()

    with ThreadPoolExecutor(max_workers=max(1, ns.jobs)) as pool:
        futs = [pool.submit(run_scenario, n, f) for n, f in todo]
        for fu in futs:
            emit(fu.result())
    try:
        check_real_profile("the whole run")
    except ProfileTouched as exc:
        emit([("FAIL", "real-profile-guard", str(exc))])
    if _PROFILE_BAD and not failed:
        emit([("FAIL", "real-profile-guard", "; ".join(_PROFILE_BAD))])
    print("(wall time %.1fs)" % (time.time() - t0))
    print("setup scenario test: %d cases, %d failed, %d skipped" % (total, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
