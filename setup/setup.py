#!/usr/bin/env python3
"""agent-playbook setup: deploys the playbook into the AI providers you choose.

Run through setup.ps1 (Windows) or setup.sh (elsewhere): each finds Python 3.8+ and runs this file
with the system interpreter in isolated mode (-I), passing its flags through. One implementation for
every platform; the deploy model (manifest, overlay merge, template render, generated-copy list, lock
grammar) lives in shared/skills/qconfig-sync/scripts/deploy_model.py, which verify-deployment.py
checks a deployment against.

It links each provider's config to this repo, and prepares what the playbook needs around it: the
Python venv (.venv-agent-playbook, built here, never under --dry-run or --uninstall), the store repo,
the pointer file and the engine branch.

Modes:
  interactive -- a console and no --yes: detects installed providers, asks before replacing a file of
                 yours, offers the store repo and engine branch.
  --yes       -- the same defaults with no questions (a new local store repo when none).
  neither     -- no console (redirected input or output, as in a test): every provider, a file of yours
                 is backed up and replaced, and the store repo, engine branch and memory link are only
                 reported, never created.
In every mode your own ~/.claude/CLAUDE.md or ~/.gemini/GEMINI.md stays where it is and the playbook
loads beside it (Claude Code reads every ~/.claude/rules/*.md, measured with Claude Code 2.1.322 on
2026-11-12; Gemini CLI reads every name in context.fileName from ~/.gemini/, source-read in Gemini CLI
0.28.2 config.js:312 and memoryDiscovery.js:93-100). Codex has no such mechanism, so a file of yours
there gets the single .bak. A file of yours is a regular file, or a link outside this repo to a file;
never a file the deploy lock names, and never a byte copy of shared/AGENTS.md.

Home: %USERPROFILE% on Windows (Python ignores HOME there), $HOME elsewhere. A test sandbox sets both,
plus APPDATA and XDG_CONFIG_HOME.

Kiro overlay merge: for a shared skill, kiro deltas under providers/kiro/skills/<name>/ are appended to
the deployed copy (OVERLAY.md to SKILL.md, <stem>.OVERLAY.md to <stem>.md; SKILL.OVERLAY.md is
forbidden). Any overlay makes the skill a generated copy, since one file inside a linked folder cannot
be overwritten.

Deploy lock (~/.agent-playbook/deploy-lock.tsv): names every regular file setup wrote, seed files
excepted, so a re-run can tell its own unedited files from yours. UTF-8, LF, no BOM; line 1 the
header; rows kind<TAB>path<TAB>value sorted by code point, one per path and kind class (backup,
setting, file). Kinds: copy-dir-recursive and merge-file (files of a generated Kiro copy), copy-file and
template-file (manifest rows), backup (a .bak setup made; value the sha256 of the .bak, - for a
folder), setting (kiro-cli/chat.defaultAgent with the value it replaced, - for none; or
gemini/context.fileName with the prior list). Paths are ~/ with forward slashes. Untrusted input: a
wrong header or one malformed row means no lock (a first run), and the unreadable file is kept as
<lock>.bak. backup rows and the Gemini setting row are also appended at once to
deploy-lock.journal.tsv, so a run stopped before it wrote its lock leaves them for the next run.

Ownership rule, for every file setup writes: absent -> write; equal to what setup writes -> keep; equal
to what the lock says setup wrote -> replace; anything else -> move it to <path>.bak first (one
backup per path). An existing .bak is replaced only when the lock shows setup made it (and, for a
file, that it is unchanged); otherwise nothing moves and a WARN says what to do. A backup that cannot
be made leaves that path unchanged and ends the run with exit 1.

Exit codes: 0 done; 1 a path could not be backed up, a lock that could not be written, or an
unexpected error; 2 a usage error, a missing prerequisite or a precondition (a file where a folder
goes, a venv folder that is not a venv, an unknown provider, a bad manifest).

Environment: AGENT_PLAYBOOK_STORES (store repo path), AGENT_PLAYBOOK_CONFIG (pointer file path),
AGENT_PLAYBOOK_SKIP_KIRO_CLI=1 (do not change kiro-cli's global settings). Test seams:
AGENT_PLAYBOOK_TEST_VENV_DIR (the venv folder instead of the repo's) and
AGENT_PLAYBOOK_TEST_GEMINI_HELPER (a script run instead of providers/gemini/context-filename.py).
AGENT_PLAYBOOK_SETUP_NAME is set by the bootstraps (setup.ps1 or setup.sh) so messages name the
command and flag spelling you ran.

Stdlib only, Python 3.8+.
"""

import hashlib
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

WIN = os.name == "nt"
SEP = "\\" if WIN else "/"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WIN:
    REPO = REPO.replace("/", "\\")
SHARED_DIR = REPO + SEP + "shared"
ALL_PROVIDERS = ("claude", "codex", "gemini", "kiro")


def _load_model():
    path = os.path.join(REPO, "shared", "skills", "qconfig-sync", "scripts", "deploy_model.py")
    spec = importlib.util.spec_from_file_location("deploy_model", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dm = _load_model()

SETUP_NAME = os.environ.get("AGENT_PLAYBOOK_SETUP_NAME") or ("setup.ps1" if WIN else "setup.sh")
PS_FLAGS = SETUP_NAME == "setup.ps1"
FLAG = {"yes": "-Yes" if PS_FLAGS else "--yes", "stores_url": "-StoresUrl URL" if PS_FLAGS else "--stores-url URL",
        "no_stores": "-NoStores" if PS_FLAGS else "--no-stores", "purge": "-Purge" if PS_FLAGS else "--purge",
        "uninstall": "-Uninstall" if PS_FLAGS else "--uninstall"}

USAGE = """Usage: %s [options]

Deploys agent-playbook into the AI providers you choose. Safe to re-run.

  --providers LIST   comma-separated subset of: claude,codex,gemini,kiro (or "all").
  --dry-run          print every change instead of making it; nothing is written.
  -y, --yes          accept every default without asking.
  --stores-url URL   clone the store repo from URL when it is missing.
  --no-stores        do not set up a store repo (memory is disabled until you do).
  --uninstall        remove what setup deployed for the chosen providers.
  --purge            with --uninstall: also remove ~/.agent-playbook/config and the repo's memory link.
  -h, --help         this text (the bootstraps print the full one).
""" % SETUP_NAME


# --- output ---------------------------------------------------------------------

def say(line=""):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def err(line):
    sys.stdout.flush()
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def warn(line):
    """setup.ps1's Write-Warning: a warning line on stderr."""
    err(("WARNING: " + line.lstrip()) if WIN else line)


class Stop(Exception):
    """End the run with this exit code (the message is already printed)."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def stop(code, message=None):
    if message:
        err(message)
    raise Stop(code)


# --- arguments ---------------------------------------------------------------------

class Opts(object):
    providers = ""
    dry_run = False
    yes = False
    stores_url = ""
    no_stores = False
    uninstall = False
    purge = False


def parse_args(argv):
    o = Opts()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--providers":
            if i + 1 >= len(argv):
                stop(2, "ERROR: --providers needs a value")
            o.providers = argv[i + 1]
            i += 2
            continue
        if a.startswith("--providers="):
            o.providers = a.split("=", 1)[1]
        elif a == "--dry-run":
            o.dry_run = True
        elif a in ("--yes", "-y"):
            o.yes = True
        elif a == "--stores-url":
            if i + 1 >= len(argv):
                stop(2, "ERROR: --stores-url needs a value")
            o.stores_url = argv[i + 1]
            i += 2
            continue
        elif a.startswith("--stores-url="):
            o.stores_url = a.split("=", 1)[1]
        elif a == "--no-stores":
            o.no_stores = True
        elif a == "--uninstall":
            o.uninstall = True
        elif a == "--purge":
            o.purge = True
        elif a in ("-h", "--help"):
            sys.stdout.write(USAGE)
            raise Stop(0)
        else:
            stop(2, "ERROR: unknown option: %s (see --help)" % a)
        i += 1
    if o.purge and not o.uninstall:
        stop(2, "ERROR: %s only goes with %s" % (FLAG["purge"], FLAG["uninstall"]))
    return o


O = Opts()
INTERACTIVE = False


def _isatty(stream):
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


# --- path helpers --------------------------------------------------------------------

def F(s):
    """A path or key in its comparison form: case folded on Windows (NTFS and PowerShell ignore case)."""
    return s.lower() if WIN else s


def pj(base, rel):
    return dm.native_join(base, rel, WIN)


def parent(p):
    return os.path.dirname(p)


def startswith_f(p, prefix):
    return F(p).startswith(F(prefix))


def lstat_or_none(p):
    try:
        return os.lstat(p)
    except (OSError, ValueError):
        return None


def _attrs(st):
    return getattr(st, "st_file_attributes", 0)


def path_exists(p):
    """Get-Item -Force: anything at the path, a dangling link included."""
    return lstat_or_none(p) is not None


def is_reparse(p):
    st = lstat_or_none(p)
    if st is None:
        return False
    return stat.S_ISLNK(st.st_mode) or bool(_attrs(st) & 0x400)


def is_container(p):
    """PSIsContainer: a folder, or a link to one (its own directory attribute on Windows)."""
    st = lstat_or_none(p)
    if st is None:
        return False
    if WIN:
        return bool(_attrs(st) & 0x10)
    return stat.S_ISDIR(st.st_mode) or (stat.S_ISLNK(st.st_mode) and os.path.isdir(p))


def is_dir_entry(p):
    """A real folder, not a link."""
    st = lstat_or_none(p)
    return st is not None and stat.S_ISDIR(st.st_mode) and not (_attrs(st) & 0x400)


def is_regular_file(p):
    st = lstat_or_none(p)
    if st is None:
        return False
    if WIN:
        return not (_attrs(st) & (0x10 | 0x400))
    return stat.S_ISREG(st.st_mode)


def test_leaf(p):
    """Test-Path -PathType Leaf: an existing non-folder, links followed."""
    return os.path.exists(p) and not os.path.isdir(p)


def strip_nt_prefix(t):
    if t.startswith("\\\\?\\UNC\\"):
        return "\\\\" + t[8:]
    if t.startswith("\\\\?\\") or t.startswith("\\??\\"):
        return t[4:]
    return t


def link_target(p):
    """The link's stored target ('' when it cannot be read)."""
    try:
        t = os.readlink(p)
    except (OSError, ValueError):
        return ""
    return strip_nt_prefix(t) if WIN else t


if WIN:
    import ctypes
    from ctypes import wintypes

    _GetLongPathNameW = ctypes.windll.kernel32.GetLongPathNameW
    _GetLongPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    _GetLongPathNameW.restype = wintypes.DWORD

    def _long_name(full):
        buf = ctypes.create_unicode_buffer(32768)
        n = _GetLongPathNameW(full, buf, 32768)
        return buf.value if 0 < n < 32768 else ""


def long_path(p):
    """p with every 8.3 short name (QSYLVE~1.POL) expanded to its long name on disk; a part that does
    not exist is kept as written (setup.ps1 Get-LongPath). Unchanged off Windows."""
    if not WIN:
        return p
    p = p.replace("/", "\\")
    if "~" not in p:
        return p
    parts = p.split("\\")
    out = parts[0]
    for n in parts[1:]:
        if "~" in n and out:
            full = _long_name(out + "\\" + n)
            if full:
                n = full.rstrip("\\").split("\\")[-1]
        out = out + "\\" + n
    return out


def under_root(p, root):
    return F(p) == F(root) or F(p).startswith(F(root) + F(SEP))


ENGINE_ROOT_LONG = long_path(REPO)


def engine_link(p):
    """A link (symlink or junction) whose target lies inside this repo, compared in long form, case
    ignored, on Windows; by its stored prefix elsewhere."""
    if not is_reparse(p):
        return False
    t = link_target(p)
    if not t:
        return False
    if not WIN:
        return t == REPO or t.startswith(REPO + "/")
    t = t.replace("/", "\\")
    if not (len(t) > 1 and (t[1] == ":" or t.startswith("\\\\"))):
        t = pj(parent(p), t)
    if under_root(t, REPO):
        return True
    return under_root(long_path(t), ENGINE_ROOT_LONG)


def same_target(a, b):
    if a == b:
        return True
    if not WIN:
        return False
    return F(long_path(strip_nt_prefix(a))) == F(long_path(b))


def canon(p):
    """One spelling per path for comparisons: long form, case folded, on Windows."""
    if not WIN:
        return p
    return long_path(p.replace("/", "\\")).rstrip("\\").lower()


# --- small actions ---------------------------------------------------------------------

def act(what, fn):
    """Run a filesystem change, or print what it would do under --dry-run."""
    if O.dry_run:
        say("    DRY: " + what)
        return None
    return fn()


def write_bytes(p, data):
    with open(p, "wb") as fh:
        fh.write(data)


def write_text(p, text):
    act("write " + p, lambda: write_bytes(p, text.encode("utf-8")))


def append_text(p, text):
    with open(p, "ab") as fh:
        fh.write(text.encode("utf-8"))


def confirm(question, default=True):
    if not INTERACTIVE:
        return default
    hint = "Y/n" if default else "y/N"
    try:
        ans = input("  %s [%s]: " % (question, hint))
    except EOFError:
        ans = ""
    if not ans.strip():
        return default
    return re.match(r"^(y|yes)$", ans.strip(), re.I) is not None


def ask(prompt):
    try:
        return input(prompt + ": ")
    except EOFError:
        return ""


def need_dir(p):
    """Make the folder. A file already at that path stops the run before anything is written there,
    in a dry run too."""
    st = lstat_or_none(p)
    if st is not None and not is_container(p):
        stop(1, "ERROR: %s is a file, not a folder; setup stopped here (move it away, then re-run setup)" % p)
    if st is None:
        act("mkdir " + p, lambda: os.makedirs(p, exist_ok=True))


def remove_dir_link(p):
    def go():
        try:
            if WIN:
                os.rmdir(p)
            else:
                os.unlink(p)
        except OSError:
            pass
    act("rmdir " + p, go)


def remove_file(p):
    act("remove " + p, lambda: os.unlink(p))


def remove_link(p):
    if is_container(p):
        remove_dir_link(p)
    else:
        remove_file(p)


def rmtree_no_follow(p):
    """Delete a folder and everything in it, never entering a link (a link inside is removed itself)."""
    for e in os.scandir(p):
        full = os.path.join(p, e.name)
        if is_reparse(full):
            if WIN and is_container(full):
                os.rmdir(full)
            else:
                os.unlink(full)
        elif e.is_dir(follow_symlinks=False):
            rmtree_no_follow(full)
        else:
            os.unlink(full)
    os.rmdir(p)


def remove_path_no_follow(p):
    if not path_exists(p):
        return
    if is_reparse(p):
        if is_container(p) and WIN:
            os.rmdir(p)
        else:
            os.unlink(p)
    elif is_container(p):
        rmtree_no_follow(p)
    else:
        os.unlink(p)


def move_no_follow(src, dst):
    if path_exists(dst):
        raise OSError("%s exists" % dst)
    os.rename(src, dst)


def file_sha(p):
    return dm.sha256_file(p)


def sha_map(paths):
    return dict((p, file_sha(p)) for p in paths if p)


def make_link(target, link, is_dir):
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except OSError as exc:
        err("ERROR: could not link %s -> %s (%s)" % (link, target, exc))


# --- home, lock state ------------------------------------------------------------------

HOME = ""
LOCK_FILE = LOCK_JOURNAL = ""
LOCK_READABLE = False
LOCK_UNREADABLE = False
BACKUP_FAILED = 0
LOCK_HELD = set()       # F(key) of paths this run had to leave alone: never retired
LOCK_OLD = []           # [kind, key, value] of the previous lock (journal rows first)
LOCK_OLD_VALUE = {}     # F(kind \t key) -> value, the first row winning
LOCK_NEW = []           # "kind\tkey\tvalue" rows of the lock this run writes
LOCK_SETTING_KEY = dm.LOCK_SETTING_KEY
LOCK_GEMINI_KEY = dm.LOCK_GEMINI_KEY
CHOSEN = []
MANIFEST = []
KIRO_IDE = ""


def lock_key(p):
    if startswith_f(p, HOME + SEP):
        return "~/" + p[len(HOME) + 1:].replace("\\", "/")
    return ""   # outside home: no lock spelling, never recorded


def from_lock_key(key):
    return pj(HOME, key[2:])


def key_provider(key):
    if key.startswith("~/.kiro/") or key == LOCK_SETTING_KEY:
        return "kiro"
    if key == LOCK_GEMINI_KEY:
        return "gemini"
    for p in ("claude", "codex", "gemini"):
        if key.startswith("~/.%s/" % p):
            return p
    return "none"


def wants(name):
    return name in CHOSEN


def read_deploy_lock():
    global LOCK_READABLE, LOCK_UNREADABLE
    del LOCK_OLD[:]
    LOCK_OLD_VALUE.clear()
    rows = []
    for p in (LOCK_FILE, LOCK_JOURNAL):
        if path_exists(p) and (is_container(p) or is_reparse(p)):
            stop(1, "ERROR: %s is not a file; setup stopped before any change (move it away, then re-run setup)" % p)
    if test_leaf(LOCK_FILE):
        try:
            parsed = dm.parse_lock(dm.read_lock_lines(LOCK_FILE))
        except (OSError, UnicodeDecodeError):
            parsed = None
        if parsed is not None:
            LOCK_READABLE = True
            rows = parsed
        else:
            LOCK_UNREADABLE = True
            say("  NOTE: %s is not a deploy lock this setup can read; treating this as a first run (it is kept as %s.bak)"
                % (LOCK_FILE, LOCK_FILE))
    if test_leaf(LOCK_JOURNAL):
        jrows, jok = [], True
        try:
            jlines = dm.read_lock_lines(LOCK_JOURNAL)
        except (OSError, UnicodeDecodeError):
            jlines, jok = [], False
        for line in jlines:
            c = line.split("\t")
            jkind = c[0] == "backup" or (c[0] == "setting" and len(c) == 3 and c[1] == LOCK_GEMINI_KEY)
            if not jkind or not dm.is_lock_row(c):
                jok = False
                break
            jrows.append(c)
        if jok:
            rows = jrows + rows
            say("  NOTE: merged the rows an interrupted run recorded in %s" % LOCK_JOURNAL)
        else:
            say("  NOTE: %s is not a journal this setup can read; ignored" % LOCK_JOURNAL)
    for c in rows:
        LOCK_OLD.append(c)
        k = F(c[0] + "\t" + c[1])
        if k not in LOCK_OLD_VALUE:
            LOCK_OLD_VALUE[k] = c[2]


def add_lock_row(kind, key, value):
    if kind != "setting":
        if not key.startswith("~/"):
            say("  NOTE: a path outside %s is not recorded in the deploy lock" % HOME)
            return
        if "\\" in key or ":" in key:
            say("  NOTE: %s is not recorded in the deploy lock (its name holds \\ or :)" % key)
            return
    LOCK_NEW.append("%s\t%s\t%s" % (kind, key, value))


def lock_value(kind, key):
    return LOCK_OLD_VALUE.get(F(kind + "\t" + key), "")


def complete_deploy_lock(carry, drop_empty=False):
    if O.dry_run:
        return
    rows, data = dm.lock_bytes(list(LOCK_NEW) + list(carry))
    exists = test_leaf(LOCK_FILE)
    if LOCK_UNREADABLE and exists:
        shutil.copyfile(LOCK_FILE, LOCK_FILE + ".bak")
        os.unlink(LOCK_FILE)
        exists = False
        say("  BACKUP: %s -> %s.bak (a deploy lock this setup cannot read)" % (LOCK_FILE, LOCK_FILE))

    def drop_journal():
        try:
            os.unlink(LOCK_JOURNAL)
        except OSError:
            pass
    if not rows:
        if drop_empty and exists:
            os.unlink(LOCK_FILE)
            drop_journal()
            say("  REMOVED: " + LOCK_FILE)
            return
        if not exists:
            drop_journal()
            return
    if exists and dm.sha256_bytes(data) == file_sha(LOCK_FILE):
        drop_journal()
        say("  OK: " + LOCK_FILE)
        return
    need_dir(parent(LOCK_FILE))
    tmp = "%s.tmp-%d" % (LOCK_FILE, os.getpid())
    try:
        write_bytes(tmp, data)
        os.replace(tmp, LOCK_FILE)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        stop(1, "ERROR: could not write %s: %s; the next run reads its rows from %s" % (LOCK_FILE, exc, LOCK_JOURNAL))
    drop_journal()
    say("  WROTE: " + LOCK_FILE)


def lock_carry_rows():
    """The previous lock's rows this run keeps: rows of a provider not deployed now, and backup rows
    whose .bak is still there."""
    out = []
    for c in LOCK_OLD:
        if c[0] == "backup":
            bp = from_lock_key(c[1])
            if no_link_parent(bp, HOME) and path_exists(bp + ".bak"):
                out.append("\t".join(c))
        elif not wants(key_provider(c[1])):
            out.append("\t".join(c))
    return out


def own_action(want, cur, locked):
    """The ownership rule, the one decision for every file setup writes."""
    if cur == "-":
        return "write"
    if cur == want:
        return "keep"
    if locked != "-" and cur == locked:
        return "replace"
    return "backup"


def no_link_parent(p, top):
    """No folder between top (exclusive) and p is a link."""
    d = os.path.dirname(p)
    while d and len(d) > len(top) and F(d) != F(top):
        if is_reparse(d):
            return False
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return True


def remove_empty_dirs(top):
    """Remove every empty folder under top, top included, deepest first, never entering a link."""
    if O.dry_run or not os.path.isdir(top) or is_reparse(top):
        return
    dirs, stack = [], [top]
    while stack:
        d = stack.pop()
        dirs.append(d)
        for e in os.scandir(d):
            full = os.path.join(d, e.name)
            if e.is_dir(follow_symlinks=False) and not is_reparse(full):
                stack.append(full)
    for d in reversed(dirs):
        try:
            if not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


def skill_dir_of(p):
    root = pj(HOME, ".kiro/skills")
    if not startswith_f(p, root + SEP):
        return ""
    rest = p[len(root) + 1:]
    i = rest.find(SEP)
    if i < 1:
        return ""
    return pj(root, rest[:i])


def backup_path(p):
    """Move a file, folder or link that is not setup's to <path>.bak and record it at once in the lock
    and its journal. 0 when the path is free; 2 when the .bak there is not setup's (nothing moved);
    1 when the move failed (the run then ends non-zero). On 1 or 2 the caller skips its write."""
    global BACKUP_FAILED
    key = lock_key(p)
    bak = p + ".bak"
    h = file_sha(p) if is_regular_file(p) else "-"
    if path_exists(bak):
        old = lock_value("backup", key)
        if not old or (old != "-" and (not is_regular_file(bak) or file_sha(bak) != old)):
            say("  WARN: %s is not a backup setup made, so %s is left unchanged; move %s away, then re-run setup" % (bak, p, bak))
            LOCK_HELD.add(F(key))
            return 2
    say("  BACKUP: %s -> %s" % (p, bak))
    if O.dry_run:
        say("    DRY: move %s %s" % (p, bak))
        add_lock_row("backup", key, h)
        return 0
    aside = ""
    failed = False
    try:
        if path_exists(bak):
            aside = "%s.tmp-%d" % (bak, os.getpid())
            move_no_follow(bak, aside)
        move_no_follow(p, bak)
    except OSError:
        failed = True
        if aside and path_exists(aside) and not path_exists(bak):
            try:
                move_no_follow(aside, bak)
            except OSError:
                pass
    if failed:
        err("ERROR: could not back up %s; left unchanged" % p)
        BACKUP_FAILED += 1
        LOCK_HELD.add(F(key))
        return 1
    if aside:
        remove_path_no_follow(aside)
    add_lock_row("backup", key, h)
    if key.startswith("~/"):
        need_dir(parent(LOCK_JOURNAL))
        append_text(LOCK_JOURNAL, "backup\t%s\t%s\n" % (key, h))
    return 0


# --- linking -------------------------------------------------------------------------------

def clear_way_for(p):
    """A file, folder or link of the user's sits where a link goes: True when the path is free
    afterwards (backed up), False to skip it. Only an interactive run asks."""
    if INTERACTIVE:
        say("  %s exists and is not a playbook link." % p)
        if not confirm("Back it up to %s.bak and replace it with the playbook's?" % p, True):
            say("  SKIPPED: %s (kept as is)" % p)
            return False
    return backup_path(p) == 0


def clear_link_way(link, target):
    """'free' (an outdated link into this repo removed, anything else backed up), 'skip', or 'ok' when
    the right link is there."""
    if not path_exists(link):
        return "free"
    if is_reparse(link):
        cur = link_target(link)
        if same_target(cur, target):
            say("  OK: %s -> %s" % (link, target))
            return "ok"
        if engine_link(link):
            say("  UPDATE: %s (was -> %s)" % (link, cur))
            remove_link(link)
            return "free"
    if clear_way_for(link):
        return "free"
    return "skip"


def link_file(target, link):
    if clear_link_way(link, target) != "free":
        return
    act("link %s -> %s" % (link, target), lambda: make_link(target, link, False))
    say("  LINKED: %s -> %s" % (link, target))


def link_dir(target, link):
    if clear_link_way(link, target) != "free":
        return
    act("link %s -> %s" % (link, target), lambda: make_link(target, link, True))
    say("  LINKED: %s -> %s" % (link, target))


def list_dirs(root, skip_cache=False):
    """[(name, full)] of the folders (links to folders included) in root, by name; dot names are
    skipped, and with skip_cache the Claude Code app's skill-sync cache (.trash, synced, .bucket-*)."""
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    # setup.sh's `*/` glob sorts "name/", so qexplore-other comes before qexplore there; NTFS order on Windows
    for n in sorted(names, key=lambda s: (s.lower(), s) if WIN else s + "/"):
        if n.startswith("."):
            continue
        if skip_cache and dm.is_skill_cache(n):
            continue
        full = pj(root, n)
        if os.path.isdir(full):
            out.append((n, full))
    return out


def shared_skills():
    return list_dirs(pj(SHARED_DIR, "skills"), skip_cache=True)


def link_skills(d):
    """One link per shared skill inside the provider's own skills folder, so its other skills stay. A
    folder of the user's with a playbook skill's name is never replaced: it is reported."""
    if is_reparse(d):
        if engine_link(d):
            say("  CONVERT: %s (one link per skill instead of the whole folder)" % d)
            remove_dir_link(d)
        else:
            say("  SKIPPED: %s links to %s, not to this repo; link the skills by hand" % (d, link_target(d)))
            return
    need_dir(d)
    for name, full in shared_skills():
        dest = pj(d, name)
        if path_exists(dest) and not is_reparse(dest):
            say("  KEPT: %s is your own folder; the playbook's %s skill is not linked there (rename or remove it, then re-run setup, to get the playbook's)" % (dest, name))
            continue
        link_dir(full, dest)
    if os.path.exists(d):
        try:
            names = sorted(os.listdir(d), key=lambda s: (s.lower(), s) if WIN else s)
        except OSError:
            names = []
        for n in names:
            full = pj(d, n)
            if is_reparse(full) and not os.path.exists(full) and engine_link(full):
                say("  REMOVE: %s (dangling)" % full)
                remove_dir_link(full)


# --- co-existence with your own instruction file ------------------------------------------

CLAUDE_SIDE_LINK = GEMINI_SIDE_LINK = GEMINI_SETTINGS = VENV_DIR = ""
GEMINI_SIDE_NAME = "AGENT-PLAYBOOK.md"
CLAUDE_SETTINGS_SHOWN = "~\\.claude\\settings.json" if WIN else "~/.claude/settings.json"


def playbook_python():
    py = pj(VENV_DIR, "Scripts/python.exe") if WIN else VENV_DIR.rstrip("/") + "/bin/python"
    return py


def user_instruction_file(dest, source):
    if is_reparse(dest):
        if engine_link(dest):
            return False
        if not test_leaf(dest):
            return False
    elif not is_regular_file(dest):
        return False
    key = lock_key(dest)
    for c in LOCK_OLD:
        if c[1] == key and c[0] not in ("backup", "setting"):
            return False
    try:
        return file_sha(dest) != file_sha(source)
    except OSError:
        return True   # unreadable: yours


def remove_side_link(p):
    if engine_link(p):
        say("  REMOVE: %s (the playbook loads through the instruction file itself now)" % p)
        remove_file(p)


def gemini_context(action, prior=""):
    """providers/gemini/context-filename.py on settings.json: its one line, or 'unreadable <why>'."""
    python = playbook_python()
    if not os.path.isfile(python):
        return "unreadable there is no playbook venv to edit it with"
    helper = os.environ.get("AGENT_PLAYBOOK_TEST_GEMINI_HELPER") or pj(REPO, "providers/gemini/context-filename.py")
    argv = [python, "-I", helper, action, "--settings", GEMINI_SETTINGS, "--name", GEMINI_SIDE_NAME]
    if O.dry_run:
        argv.append("--dry-run")
    env = dict(os.environ, CONTEXT_FILENAME_PRIOR=prior)
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    except OSError:
        return "unreadable the helper failed (exit 1)"
    if r.returncode not in (0, 3):
        return "unreadable the helper failed (exit %d)" % r.returncode
    lines = r.stdout.decode("utf-8", "replace").split("\n")
    if not lines or (len(lines) == 1 and lines[0] == ""):
        return "unreadable the helper printed nothing"
    return lines[0].rstrip("\r")


def gemini_journal(prior):
    if O.dry_run:
        return
    need_dir(parent(LOCK_JOURNAL))
    append_text(LOCK_JOURNAL, "setting\t%s\t%s\n" % (LOCK_GEMINI_KEY, prior))


def remove_gemini_entry(prior):
    res = gemini_context("remove", prior)
    if res == "removed":
        if O.dry_run:
            say("    DRY: remove %s from context.fileName in %s" % (GEMINI_SIDE_NAME, GEMINI_SETTINGS))
        else:
            say("  REMOVED: %s from context.fileName in %s" % (GEMINI_SIDE_NAME, GEMINI_SETTINGS))
            if not os.path.exists(GEMINI_SETTINGS):
                say("  REMOVED: %s (setup created it)" % GEMINI_SETTINGS)
    elif res != "absent":
        say("  NOTE: %s cannot be edited (%s); remove %s from its context.fileName by hand"
            % (GEMINI_SETTINGS, re.sub(r"^unreadable ", "", res), GEMINI_SIDE_NAME))
        add_lock_row("setting", LOCK_GEMINI_KEY, prior)


def deploy_claude_instructions(source, dest):
    if user_instruction_file(dest, source):
        say("  KEPT: %s is your own file; the playbook loads beside it from %s (Claude Code reads every ~/.claude/rules/*.md)"
            % (dest, CLAUDE_SIDE_LINK))
        need_dir(parent(CLAUDE_SIDE_LINK))
        link_file(source, CLAUDE_SIDE_LINK)
        return
    link_file(source, dest)
    if O.dry_run or engine_link(dest):
        remove_side_link(CLAUDE_SIDE_LINK)


def deploy_gemini_instructions(source, dest):
    old = lock_value("setting", LOCK_GEMINI_KEY)
    if user_instruction_file(dest, source):
        if O.dry_run and not os.path.exists(playbook_python()):
            say("    DRY: the venv is created first; then %s is added to context.fileName of %s" % (GEMINI_SIDE_NAME, GEMINI_SETTINGS))
        else:
            res = gemini_context("add")
            if res == "present":
                if old:
                    add_lock_row("setting", LOCK_GEMINI_KEY, old)
            elif res.startswith("added "):
                add_lock_row("setting", LOCK_GEMINI_KEY, res[6:])
                gemini_journal(res[6:])
                if O.dry_run:
                    say("    DRY: add %s to context.fileName of %s" % (GEMINI_SIDE_NAME, GEMINI_SETTINGS))
                else:
                    say("  SET: %s in context.fileName of %s" % (GEMINI_SIDE_NAME, GEMINI_SETTINGS))
            else:
                say("  NOTE: %s cannot be edited (%s); add \"%s\" to context.fileName in ~/.gemini/settings.json by hand, or Gemini CLI does not load the playbook"
                    % (GEMINI_SETTINGS, re.sub(r"^unreadable ", "", res), GEMINI_SIDE_NAME))
                if old:
                    add_lock_row("setting", LOCK_GEMINI_KEY, old)
        say("  KEPT: %s is your own file; the playbook loads beside it from %s (listed in context.fileName)" % (dest, GEMINI_SIDE_LINK))
        link_file(source, GEMINI_SIDE_LINK)
        return
    link_file(source, dest)
    if O.dry_run or engine_link(dest):
        remove_side_link(GEMINI_SIDE_LINK)
        if old:
            remove_gemini_entry(old)
    elif old:
        add_lock_row("setting", LOCK_GEMINI_KEY, old)


def deploy_codex_instructions(source, dest):
    mine = user_instruction_file(dest, source)
    link_file(source, dest)
    if mine and (O.dry_run or engine_link(dest)):
        say("  NOTE: Codex has no way to load a second global instructions file, so yours cannot stay beside the playbook's: it is kept as %s.bak" % dest)


def deploy_instruction_file(manifest_dest, source, dest):
    if manifest_dest == "~/.claude/CLAUDE.md":
        deploy_claude_instructions(source, dest)
    elif manifest_dest == "~/.gemini/GEMINI.md":
        deploy_gemini_instructions(source, dest)
    elif manifest_dest == "~/.codex/AGENTS.md":
        deploy_codex_instructions(source, dest)
    else:
        return False
    return True


def memory_source_missing(manifest_source, source, dest):
    """A row whose source lies in the gitignored memory/ and is not there yet: no dangling link is made,
    and one an earlier run made is removed."""
    if not manifest_source.startswith("memory/"):
        return False
    if os.path.exists(source):
        return False
    if engine_link(dest):
        say("  REMOVE: %s (dangling: there is no %s)" % (dest, source))
        remove_file(dest)
    say("  NOTE: %s is not linked yet: there is no %s (no user memory in the store repo yet)" % (dest, source))
    return True


# --- owned files ---------------------------------------------------------------------------

def write_owned_file(kind, dest, data):
    """A copy-file or template-file row under the ownership rule. A link at dest is removed when it
    points into this repo (the layout before copies), else backed up."""
    key = lock_key(dest)
    if is_reparse(dest):
        if engine_link(dest):
            say("  REMOVE SYMLINK: " + dest)
            remove_file(dest)
        elif backup_path(dest) != 0:
            return
    elif path_exists(dest) and is_container(dest):
        if backup_path(dest) != 0:
            return
    want = dm.sha256_bytes(data)
    cur = file_sha(dest) if is_regular_file(dest) else "-"
    locked = lock_value(kind, key) or "-"
    a = own_action(want, cur, locked)
    if a == "keep":
        say("  OK: %s (matches source)" % dest)
    elif a == "backup":
        if backup_path(dest) != 0:
            return
        act("write " + dest, lambda: write_bytes(dest, data))
        say("  WROTE: %s (yours kept as %s.bak)" % (dest, dest))
    else:
        act("write " + dest, lambda: write_bytes(dest, data))
        say("  WROTE: " + dest)
    add_lock_row(kind, key, want)


def fixture_leftovers(source_dir, dest):
    """Files under a fixtures folder of the copy at dest, which setup no longer deploys but an older
    setup did: {rel: (hash, own)}, own when equal to the source file at the same path."""
    out = {}
    if not is_dir_entry(dest):
        return out
    files, stack = [], [(dest, False)]
    while stack:
        d, in_fx = stack.pop()
        for e in os.scandir(d):
            full = pj(d, e.name)
            if is_reparse(full):
                continue
            if e.is_dir(follow_symlinks=False):
                if F(e.name) != F("__pycache__"):
                    stack.append((full, in_fx or e.name == "fixtures"))
            elif in_fx:
                files.append(full)
    if not files:
        return out
    dh = sha_map(files)
    for f in files:
        rel = f[len(dest) + 1:]
        s = pj(source_dir, rel)
        own = is_regular_file(s) and file_sha(s) == dh[f]
        out[rel.replace("\\", "/")] = (dh[f], own)
    return out


def lock_retire(prefix):
    """Rows of the previous lock under prefix that this run did not record (their source is gone):
    each file is removed when unchanged since setup wrote it, else backed up; then the empty folders
    above it go, up to the Kiro skills folder."""
    recorded = set()
    for line in LOCK_NEW:
        c = line.split("\t")
        if c[0] not in ("backup", "setting"):
            recorded.add(F(c[1]))
    recorded |= LOCK_HELD
    for e in MANIFEST:
        k = lock_key(dm.expand_dest(e.dest, HOME, KIRO_IDE, WIN))
        if k:
            recorded.add(F(k))
    done, todo = set(), []
    for c in LOCK_OLD:
        if c[0] in ("backup", "setting") or not c[1].startswith(prefix):
            continue
        if F(c[1]) in recorded or c[1] in done:
            continue
        done.add(c[1])
        p = from_lock_key(c[1])
        if is_regular_file(p) and no_link_parent(p, HOME):
            todo.append((p, c[2]))
    if not todo:
        return
    hashes = sha_map([t[0] for t in todo])
    touched, nfx = [], 0
    skills_root = pj(HOME, ".kiro/skills")
    for p, want in todo:
        is_fx = False
        if startswith_f(p, skills_root + SEP):
            r = p[len(skills_root) + 1:]
            i = r.find(SEP)
            if i > 0 and (SEP + "fixtures" + SEP) in (SEP + r[i + 1:]):
                is_fx = is_regular_file(pj(pj(SHARED_DIR, "skills"), r))
        why = "setup no longer deploys fixtures/ folders" if is_fx else "its source is gone"
        if hashes[p] == want:
            act("remove " + p, lambda p=p: os.unlink(p))
            if is_fx:
                nfx += 1
            else:
                say("  REMOVED: %s (%s)" % (p, why))
        else:
            say("  NOTE: %s changed since setup wrote it and %s" % (p, why))
            backup_path(p)
        sd = skill_dir_of(p)
        if sd and F(sd) not in [F(t) for t in touched]:
            touched.append(sd)
    if nfx:
        top = from_lock_key(prefix).rstrip("\\/")
        say("  REMOVED: %d unchanged file(s) under fixtures/ folders in %s (setup no longer deploys fixtures/ folders)" % (nfx, top))
    for sd in touched:
        remove_empty_dirs(sd)


def generated_expected(source_dir, overlay_dir, name):
    return dm.generated_expected(source_dir, overlay_dir, WIN, warn=warn,
                                 note=lambda line: say("  SKIPPED EMPTY OVERLAY: " + name))


def deploy_generated_copy(source_dir, dest, overlay_dir, name):
    prefix = "~/.kiro/skills/%s/" % name
    exp = generated_expected(source_dir, overlay_dir, name)
    return deploy_generated_copy_to(dest, name, prefix, exp, fixture_leftovers(source_dir, dest))


def deploy_generated_copy_to(dest, name, prefix, exp, fx):
    """An overlay-bearing skill as a generated copy: every expected file's bytes are known first, then
    only the files that differ are written, each under the ownership rule. A folder at dest that the
    lock names no file of is setup's when every file in it sits at a path setup writes for the skill
    (or is a fixtures file equal to its source); any other such folder is yours: KEPT."""
    cur = {}     # F(rel) -> hash
    if is_reparse(dest):
        if engine_link(dest):
            say("  REMOVE SYMLINK: %s (now a generated copy)" % dest)
            remove_dir_link(dest)
        elif not clear_way_for(dest):
            return False
    elif path_exists(dest) and not is_container(dest):
        if not clear_way_for(dest):
            return False
    elif path_exists(dest):
        for f, h in sha_map(dm.files_no_follow(dest, WIN)).items():
            cur[F(f[len(dest) + 1:].replace("\\", "/"))] = h
    locked = {}
    for c in LOCK_OLD:
        if c[0] in ("copy-dir-recursive", "merge-file") and c[1].startswith(prefix):
            locked[F(c[1][len(prefix):])] = c[2]
    plan = []
    for rel, e in exp.items():
        plan.append((own_action(e.hash, cur.get(F(rel), "-"), locked.get(F(rel), "-")), rel))
    exp_keys = set(F(r) for r in exp)
    foreign = len([k for k in cur if k not in exp_keys])
    foreign += len([v for v in fx.values() if not v[1]])
    if (len(cur) + len(fx)) > 0 and not locked and foreign > 0:
        say("  KEPT: %s is your own folder; the playbook's %s skill is not deployed there (rename or remove it, then re-run setup, to get the playbook's)" % (dest, name))
        return False
    need_dir(dest)
    n_write = n_backup = n_keep = 0
    for a, rel in plan:
        e = exp[rel]
        full = pj(dest, rel)
        if a != "keep":
            if not no_link_parent(full, dest):
                say("  SKIPPED: %s (a folder above it is a link)" % full)
                continue
            if a == "backup" or (a == "write" and path_exists(full)):
                if backup_path(full) != 0:
                    continue
                n_backup += 1

            def write(full=full, e=e):
                os.makedirs(parent(full), exist_ok=True)
                if e.src:
                    shutil.copyfile(e.src, full)
                else:
                    write_bytes(full, e.data)
            act("write " + full, write)
            n_write += 1
        else:
            n_keep += 1
        add_lock_row(e.kind, prefix + rel, e.hash)
    fx_rm = sorted(r for r, v in fx.items() if v[1] and F(r) not in locked)
    if fx_rm:
        say("  REMOVED: %d unchanged file(s) under fixtures/ folders in %s (setup no longer deploys fixtures/ folders)" % (len(fx_rm), dest))
        for rel in fx_rm:
            full = pj(dest, rel)
            act("remove " + full, lambda full=full: os.unlink(full))
        remove_empty_dirs(dest)
    if n_write == 0:
        say("  OK: %s (generated copy, %d files)" % (dest, n_keep))
    else:
        say("  UPDATED: %s (generated copy: %d written, %d backed up, %d unchanged)" % (dest, n_write, n_backup, n_keep))
    return True


def free_real_skill_dir(name):
    """A real folder at a Kiro skill name where a link goes: when every entry in it is a file setup
    wrote and left unchanged, those go and True lets the link be made; otherwise nothing there is
    touched and False keeps the folder (KEPT, or a WARN when it also holds setup's files)."""
    dest = pj(pj(HOME, ".kiro/skills"), name)
    prefix = "~/.kiro/skills/%s/" % name
    rows = [c for c in LOCK_OLD if c[0] in ("copy-dir-recursive", "merge-file") and c[1].startswith(prefix)]
    want = {}
    for c in rows:
        want[F(from_lock_key(c[1]))] = c[2]
    entries, stack = [], [dest]
    while stack:
        d = stack.pop()
        for e in os.scandir(d):
            full = pj(d, e.name)
            if is_dir_entry(full):
                stack.append(full)
            else:
                entries.append(full)
    n_locked = n_other = 0
    for f in entries:
        named = F(f) in want and is_regular_file(f)
        if named:
            n_locked += 1
        if not (named and file_sha(f) == want[F(f)]):
            n_other += 1
    if n_other == 0:
        lock_retire(prefix)
        if O.dry_run:
            return False
        remove_empty_dirs(dest)
        if not os.path.exists(dest):
            return True
    if n_locked > 0:
        say("  WARN: %s holds files of yours beside files setup wrote; the playbook's %s skill is no longer updated there (move your files out of it, then re-run setup)" % (dest, name))
        for c in rows:
            LOCK_NEW.append("\t".join(c))
    else:
        say("  KEPT: %s is your own folder; the playbook's %s skill is not linked there (rename or remove it, then re-run setup, to get the playbook's)" % (dest, name))
    return False


# --- templates and seeds --------------------------------------------------------------------

def render(source):
    return dm.render_template_bytes(source, HOME, ENGINE_ROOT_LONG)


def copy_template(source, dest):
    write_owned_file("template-file", dest, render(source))


def copy_seed(source, dest):
    """A seed is written only when the destination is absent: the app owns the live file."""
    if os.path.exists(dest):
        say("  OK: %s (present; seed not overwritten)" % dest)
        return
    data = render(source)
    act("write " + dest, lambda: write_bytes(dest, data))
    say("  SEEDED: %s -> %s" % (source, dest))


# --- uninstall -------------------------------------------------------------------------------

def restore_backup(p):
    val = lock_value("backup", lock_key(p))
    if not val:
        return
    bak = p + ".bak"
    if not no_link_parent(p, HOME):
        say("  WARN: %s is not restored: a folder above it is a link (restore it by hand if you need it)" % bak)
        return
    if not path_exists(bak):
        return
    if path_exists(p):
        say("  KEPT: %s (%s is still there)" % (bak, p))
        return
    if val != "-" and (not is_regular_file(bak) or file_sha(bak) != val):
        say("  KEPT: %s (changed since setup made it)" % bak)
        return
    act("restore " + p, lambda: os.rename(bak, p))
    say("  RESTORED: %s (from %s)" % (p, bak))


def remove_engine_link(p):
    if not engine_link(p):
        return
    remove_link(p)
    say("  REMOVED: " + p)
    restore_backup(p)


def remove_skill_links(d):
    if not os.path.exists(d):
        return
    try:
        names = sorted(os.listdir(d), key=lambda s: (s.lower(), s) if WIN else s)
    except OSError:
        return
    for n in names:
        remove_engine_link(pj(d, n))


def uninstall_owned_file(kind, dest, source):
    if is_regular_file(dest):
        locked = lock_value(kind, lock_key(dest))
        if locked:
            same = file_sha(dest) == locked
        elif kind == "template-file":
            same = file_sha(dest) == dm.sha256_bytes(render(source))
        else:
            same = file_sha(dest) == file_sha(source)
        if same:
            remove_file(dest)
            say("  REMOVED: " + dest)
        else:
            say("  KEPT: %s (changed since setup wrote it)" % dest)
    restore_backup(dest)


def uninstall_mode(mode):
    for e in MANIFEST:
        if e.mode != mode:
            continue
        dest = dm.expand_dest(e.dest, HOME, KIRO_IDE, WIN)
        source = pj(REPO, e.source)
        if e.kind in ("symlink-file", "symlink-dir"):
            remove_engine_link(dest)
        elif e.kind in ("template-file", "copy-file"):
            uninstall_owned_file(e.kind, dest, source)
        elif e.kind == "seed-file":
            if os.path.exists(dest):
                say("  KEPT: %s (the app owns it; setup only seeded it)" % dest)


def uninstall_generated_copies():
    """The files of the generated Kiro copies the lock names: each removed when unchanged since setup
    wrote it, else kept; then the empty folders go and setup's backups there are restored. With no
    readable lock, a file is removed only when it equals what setup would write there now."""
    skills_root = pj(HOME, ".kiro/skills")
    names, todo, want = [], [], []
    for c in LOCK_OLD:
        if c[0] not in ("copy-dir-recursive", "merge-file") or not c[1].startswith("~/.kiro/skills/"):
            continue
        want.append((c[1], c[2]))
    if not LOCK_READABLE:
        overlay_root = pj(REPO, "providers/kiro/skills")
        for name, full in list_dirs(pj(SHARED_DIR, "skills")):
            ov = pj(overlay_root, name)
            if not os.path.exists(pj(full, "SKILL.md")) or not dm.has_any_overlay(ov):
                continue
            exp = generated_expected(full, ov, name)
            for rel, e in exp.items():
                want.append(("~/.kiro/skills/%s/%s" % (name, rel), e.hash))
            for rel, (h, own) in fixture_leftovers(full, pj(skills_root, name)).items():
                if own:
                    want.append(("~/.kiro/skills/%s/%s" % (name, rel), h))
    for key, h in want:
        n = key.split("/")[3]
        if n not in names:
            names.append(n)
        p = from_lock_key(key)
        if is_regular_file(p) and no_link_parent(p, HOME):
            todo.append((p, h))
    existed = [n for n in sorted(names) if is_dir_entry(pj(skills_root, n))]
    hashes = sha_map([t[0] for t in todo])
    for p, h in todo:
        if hashes[p] == h:
            act("remove " + p, lambda p=p: os.unlink(p))
        else:
            say("  KEPT: %s (changed since setup wrote it)" % p)
    for n in names:
        remove_empty_dirs(pj(skills_root, n))
    for c in LOCK_OLD:
        if c[0] == "backup" and c[1].startswith("~/.kiro/skills/"):
            restore_backup(from_lock_key(c[1]))
    for n in existed:
        d = pj(skills_root, n)
        if is_dir_entry(d):
            say("  KEPT: %s (holds files that are not setup's unchanged ones)" % d)
        else:
            say("  REMOVED: %s (generated copy)" % d)


def kiro_cli():
    return shutil.which("kiro-cli")


def kiro_default_agent():
    """kiro-cli's chat.defaultAgent as JSON on one line (lines joined by a space, ends trimmed), or ''
    when the read fails or prints nothing."""
    exe = kiro_cli()
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "settings", "-f", "json", "--global", "chat.defaultAgent"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return ""
    if r.returncode != 0:
        return ""
    lines = r.stdout.decode("utf-8", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return " ".join(l.rstrip("\r") for l in lines).strip()


def run_kiro(*args):
    try:
        return subprocess.run([kiro_cli()] + list(args), stdin=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def uninstall_kiro_setting():
    """Revert chat.defaultAgent only when the lock shows setup set it and it still names kiro_default;
    when the revert cannot be tried, the lock keeps the row for a later uninstall."""
    val = lock_value("setting", LOCK_SETTING_KEY)
    if not kiro_cli():
        if val:
            say("  NOTE: no kiro-cli here, so chat.defaultAgent is not reverted; the deploy lock keeps it for a later uninstall")
            add_lock_row("setting", LOCK_SETTING_KEY, val)
        return
    if os.environ.get("AGENT_PLAYBOOK_SKIP_KIRO_CLI") == "1":
        say("  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)")
        if val:
            add_lock_row("setting", LOCK_SETTING_KEY, val)
        return
    if not val:
        say("  NOTE: setup did not set kiro-cli's chat.defaultAgent, so it is left as is")
        return
    cur = kiro_default_agent()
    if not cur:
        say("  WARN: kiro-cli's chat.defaultAgent could not be read, so it is not reverted; the deploy lock keeps it for a later uninstall")
        add_lock_row("setting", LOCK_SETTING_KEY, val)
        return
    if cur != '"kiro_default"':
        say("  NOTE: kiro-cli's chat.defaultAgent changed since setup set it, so it is left as is")
        return
    if O.dry_run:
        say("    DRY: revert kiro-cli chat.defaultAgent to " + val)
        return
    if val == "-":
        ok = run_kiro("settings", "--global", "--delete", "chat.defaultAgent")
    else:
        v = val[1:] if val.startswith('"') else val
        v = v[:-1] if v.endswith('"') else v
        ok = run_kiro("settings", "--global", "chat.defaultAgent", v)
    if ok:
        say("  RESTORED: kiro-cli chat.defaultAgent (to %s)" % val)
    else:
        say("  WARN: kiro-cli could not revert chat.defaultAgent; the deploy lock keeps it for a later uninstall")
        add_lock_row("setting", LOCK_SETTING_KEY, val)


def run_uninstall(config_file):
    say("=== Uninstall: %s ===" % ", ".join(CHOSEN))
    if wants("claude"):
        uninstall_mode("claude")
        remove_engine_link(CLAUDE_SIDE_LINK)
        remove_skill_links(pj(HOME, ".claude/skills"))
        rules = parent(CLAUDE_SIDE_LINK)
        if is_dir_entry(rules) and not os.listdir(rules):
            act("rmdir " + rules, lambda: os.rmdir(rules))
            say("  REMOVED: %s (empty)" % rules)
        python = playbook_python()
        if os.path.isfile(python):
            def remove_entries():
                try:
                    ok = subprocess.run([python, "-I", pj(REPO, "providers/claude/settings-entries.py"), "remove",
                                         "--home", HOME]).returncode == 0
                except OSError:
                    ok = False
                if not ok:
                    say("  NOTE: the venv did not run, so remove the playbook's entries from %s by hand" % CLAUDE_SETTINGS_SHOWN)
            act("remove the playbook's entries from %s" % CLAUDE_SETTINGS_SHOWN, remove_entries)
        else:
            say("  NOTE: no venv, so remove the playbook's entries from %s by hand" % CLAUDE_SETTINGS_SHOWN)
    if wants("codex"):
        uninstall_mode("codex")
        remove_skill_links(pj(HOME, ".codex/skills"))
    if wants("gemini"):
        uninstall_mode("gemini")
        remove_engine_link(GEMINI_SIDE_LINK)
        remove_skill_links(pj(HOME, ".gemini/skills"))
        old = lock_value("setting", LOCK_GEMINI_KEY)
        if old:
            remove_gemini_entry(old)
    if wants("kiro"):
        uninstall_mode("kiro-always")
        uninstall_mode("kiro")
        uninstall_generated_copies()
        remove_skill_links(pj(HOME, ".kiro/skills"))
        uninstall_kiro_setting()
    keep = ["\t".join(c) for c in LOCK_OLD if not wants(key_provider(c[1]))]
    complete_deploy_lock(keep, drop_empty=True)
    if O.purge:
        mem = pj(REPO, "memory")
        if is_reparse(mem):
            remove_dir_link(mem)
            say("  REMOVED: %s (link; the store repo is untouched)" % mem)
        if os.path.exists(config_file):
            remove_file(config_file)
            say("  REMOVED: " + config_file)
    else:
        say("  KEPT: %s, the memory link and the store repo (%s removes the first two)" % (config_file, FLAG["purge"]))
    say()
    say("Done.")
    return 0


# --- prerequisites, venv, store repo, memory link, engine branch ------------------------

def python_info(argv):
    """[exe, version] when argv runs a Python 3.8+, else None."""
    code = "import sys; print(sys.executable); print('%d.%d.%d' % sys.version_info[:3]); sys.exit(0 if sys.version_info[:2] >= (3, 8) else 3)"
    try:
        r = subprocess.run(list(argv) + ["-c", code], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
    except OSError:
        return None
    lines = r.stdout.decode("utf-8", "replace").splitlines()
    if r.returncode != 0 or len(lines) < 2:
        return None
    return [lines[0], lines[1]]


def git(*args, **kw):
    return subprocess.run(["git"] + list(args), stdin=subprocess.DEVNULL, **kw)


def git_out(*args):
    try:
        r = git(*args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return 1, ""
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def check_prereqs():
    say("=== Prerequisites ===")
    missing = False
    say("  OK: Python %d.%d.%d (%s)" % (sys.version_info[0], sys.version_info[1], sys.version_info[2], sys.executable))
    if shutil.which("git"):
        say("  OK: " + git_out("--version")[1])
    else:
        say("  MISSING: git -- install it (git-scm.com%s), then run %s again" % ("" if WIN else ", or your package manager", SETUP_NAME))
        missing = True
    probe = tempfile.mkdtemp(prefix="apb-probe-")
    link = os.path.join(probe, "link")
    try:
        os.symlink(probe, link, target_is_directory=True)
        ok = os.path.islink(link)
    except OSError:
        ok = False
    finally:
        try:
            if os.path.lexists(link):
                (os.rmdir if WIN else os.unlink)(link)
        except OSError:
            pass
        shutil.rmtree(probe, ignore_errors=True)
    if ok:
        say("  OK: symlinks can be created")
    else:
        say("  MISSING: symlink rights -- %senable Developer Mode (Settings > System > For developers) or run elevated" % ("" if WIN else "on Windows "))
        missing = True
    node = shutil.which("node")
    if node:
        try:
            v = subprocess.run([node, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL).stdout.decode("utf-8", "replace").strip()
        except OSError:
            v = "?"
        say("  OK: Node %s (optional: qdocument-interaction, Playwright)" % v)
    else:
        say("  NOTE: Node not found (optional: only qdocument-interaction's creation libraries and the Playwright MCP need it)")
    if missing:
        if O.dry_run:
            say("  (dry run: continuing to show the plan)")
        else:
            stop(2, "ERROR: a required prerequisite is missing (above); nothing was deployed.")


def venv_step():
    """One interpreter for every playbook Python script: <repo>/.venv-agent-playbook, made from this
    Python with --without-pip; nothing is ever installed into it. A working venv is left alone; a broken
    one is rebuilt."""
    say("=== Python venv ===")
    py = playbook_python()
    info = python_info([py]) if os.path.isfile(py) else None
    if info:
        say("  OK: %s (Python %s)" % (VENV_DIR, info[1]))
        return
    if os.path.exists(VENV_DIR) and not os.path.exists(os.path.join(VENV_DIR, "pyvenv.cfg")) and os.listdir(VENV_DIR):
        stop(2, "ERROR: %s exists, is not empty and is not a venv (no pyvenv.cfg). Move or delete it, then run %s again."
             % (VENV_DIR, SETUP_NAME))
    if O.dry_run:
        say("    DRY: %s -m venv --clear --without-pip %s" % (sys.executable, VENV_DIR))
        return
    r = subprocess.run([sys.executable, "-m", "venv", "--clear", "--without-pip", VENV_DIR], stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        stop(2, "ERROR: '%s -m venv' failed (exit %d) for %s. Fix the error above, then run %s again."
             % (sys.executable, r.returncode, VENV_DIR, SETUP_NAME))
    info = python_info([py])
    if not info:
        stop(2, "ERROR: %s does not run after creation. Delete %s and run %s again." % (py, VENV_DIR, SETUP_NAME))
    say("  CREATED: %s (Python %s, from %s)" % (VENV_DIR, info[1], sys.executable))


def config_value(config_file, key):
    if not os.path.exists(config_file):
        return ""
    value = ""
    rx = re.compile(r"^\s*%s\s*=\s*(.*?)\s*$" % re.escape(key), re.I if WIN else 0)
    with open(config_file, "rb") as fh:
        text = dm.decode_net(fh.read())
    for line in re.split(r"\r\n|\n|\r", text):
        m = rx.match(line)
        if m:
            value = m.group(1)
    return value


def init_user_memory(stores):
    mem = pj(stores, "user/memory")
    if os.path.exists(mem):
        return
    repo_mem = pj(REPO, "memory")
    if path_exists(repo_mem) and not is_reparse(repo_mem):
        say("  NOTE: %s is a real folder (the layout before the store repo held user memory);" % repo_mem)
        say("        move it to %s, then re-run setup to link it" % mem)
        return
    say("  SEED: %s (empty user memory from templates%smemory%s)" % (mem, SEP, SEP))
    need_dir(mem)
    tdir = pj(REPO, "templates/memory")
    for n in sorted(os.listdir(tdir)):
        f = pj(tdir, n)
        if os.path.isfile(f):
            act("copy %s -> %s" % (f, mem), lambda f=f, n=n: shutil.copyfile(f, pj(mem, n)))


def store_repo_step(stores):
    def new_store():
        say("  CREATE: %s (a new local store repo; add a remote and push it to keep it)" % stores)
        need_dir(stores)
        act("git init " + stores, lambda: git("-C", stores, "init", "-q"))
        write_text(pj(stores, ".gitignore"), "user/memory/.dream-journal.jsonl\n*/STORE.tmp-*\n*/scratch/\n")

    def clone(url):
        say("  CLONE: %s -> %s" % (url, stores))

        def go():
            r = git("clone", "-q", url, stores)
            if r.returncode != 0:
                stop(1, "ERROR: git clone failed (exit %d)" % r.returncode)
        act("git clone %s %s" % (url, stores), go)

    say("=== Store repo ===")
    ready = True
    if os.path.exists(pj(stores, ".git")):
        say("  OK: " + stores)
    elif O.no_stores:
        say("  SKIPPED: store repo (%s); memory stays off until %s exists" % (FLAG["no_stores"], stores))
        ready = False
    elif O.stores_url:
        clone(O.stores_url)
    elif INTERACTIVE:
        say("  No store repo at %s. It holds your memory, plans and artifacts (private)." % stores)
        ans = ask("  [c]lone yours from a URL, create a [n]ew local one, or [s]kip? [n]").strip() or "n"
        if ans[:1] in ("c", "C"):
            O.stores_url = ask("  Store repo URL").strip()
            if O.stores_url:
                clone(O.stores_url)
            else:
                say("  SKIPPED: no URL given")
                ready = False
        elif ans[:1] in ("n", "N"):
            new_store()
        else:
            say("  SKIPPED: store repo; memory stays off until %s exists" % stores)
            ready = False
    elif O.yes:
        new_store()
    else:
        say("  NOTE: no store repo at %s; memory is off. Re-run with %s or %s, or interactively." % (stores, FLAG["stores_url"], FLAG["yes"]))
        ready = False
    if ready:
        init_user_memory(stores)


def real_home():
    """The home the OS records for this user, whatever HOME and USERPROFILE say ('' when unknown)."""
    if WIN:
        try:
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 40, None, 0, buf) == 0:
                return buf.value
        except (OSError, AttributeError):
            pass
        return ""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_dir
    except (ImportError, KeyError, OSError):
        return ""


def home_sandboxed():
    real = real_home()
    if not real:
        return True
    a = long_path(os.path.abspath(HOME)).rstrip("\\/").lower()
    b = long_path(os.path.abspath(real)).rstrip("\\/").lower()
    return a != b


def memory_link_step(stores):
    link = pj(REPO, "memory")
    target = pj(stores, "user/memory")
    do_link = True
    if home_sandboxed():
        say("  SKIPPED: %s (HOME is sandboxed; the repo's memory link is never written from a sandbox)" % link)
        do_link = False
    elif is_reparse(link):
        cur = link_target(link)
        if canon(cur) == canon(target):
            say("  OK: %s -> %s" % (link, target))
            do_link = False
        elif not INTERACTIVE and not O.yes:
            say("  NOTE: %s points to %s, not %s; re-run with %s or interactively to repoint it" % (link, cur, target, FLAG["yes"]))
            do_link = False
        else:
            say("  UPDATE: %s (was -> %s)" % (link, cur))
            remove_dir_link(link)
    elif path_exists(link):
        say("  NOTE: %s is a real folder; memory stays there until you move it to %s" % (link, target))
        do_link = False
    if do_link:
        if not os.path.exists(target) and not O.dry_run:
            say("  NOTE: no %s yet; the memory link is made once the store repo holds user memory" % target)
        elif not INTERACTIVE and not O.yes:
            say("  NOTE: %s is not linked yet; re-run with %s or interactively to link it to %s" % (link, FLAG["yes"], target))
        else:
            # a symlink, never a junction: dream-write refuses junctions on the memory path
            act("link %s -> %s" % (link, target), lambda: make_link(target, link, True))
            say("  LINKED: %s -> %s" % (link, target))


BRANCH = "local-improvements"


def engine_branch_step():
    say("=== Engine branch ===")
    rc, _ = git_out("-C", REPO, "rev-parse", "--git-dir")
    if rc != 0:
        say("  SKIPPED: %s is not a git checkout" % REPO)
        return
    _, cur = git_out("-C", REPO, "symbolic-ref", "-q", "--short", "HEAD")
    if cur == BRANCH:
        say("  OK: on " + BRANCH)
    elif not INTERACTIVE and not O.yes:
        say("  NOTE: on %s; engine commits (/qconfig-sync, /qdream) land on %s -- re-run with %s or interactively to set it up"
            % (cur or "a detached HEAD", BRANCH, FLAG["yes"]))
    elif not confirm("Engine commits (/qconfig-sync, /qdream) land on '%s', never on main. Set it up and switch to it?" % BRANCH, True):
        say("  SKIPPED: engine branch")
    else:
        if git_out("-C", REPO, "show-ref", "-q", "--verify", "refs/heads/" + BRANCH)[0] != 0:
            act("git branch " + BRANCH, lambda: git("-C", REPO, "branch", "-q", BRANCH))
            say("  CREATED: branch " + BRANCH)
        if git_out("--no-optional-locks", "-C", REPO, "status", "--porcelain", "--untracked-files=no")[1]:
            say("  NOTE: uncommitted changes in %s; switch yourself when ready: git -C %s switch %s" % (REPO, REPO, BRANCH))
        else:
            act("git switch " + BRANCH, lambda: git("-C", REPO, "switch", "-q", BRANCH))
            say("  SWITCHED: %s is on %s" % (REPO, BRANCH))


def pointer_file_step(config_file, stores):
    say("=== Pointer file ===")
    url = O.stores_url or config_value(config_file, "stores_url")
    text = "# agent-playbook pointer file, written by setup (shared/AGENTS.md, Config Repo Locations).\n"
    text += "root=%s\n" % ENGINE_ROOT_LONG.replace("\\", "/")
    text += "stores=%s\n" % stores.replace("\\", "/")
    if url:
        text += "stores_url=%s\n" % url
    text += "engine_branch=%s\n" % BRANCH
    text += "providers=%s\n" % ",".join(CHOSEN)
    same = False
    if os.path.exists(config_file):
        try:
            same = dm.read_text(config_file) == text
        except OSError:
            same = False
    if same:
        say("  OK: " + config_file)
    else:
        need_dir(parent(config_file))
        write_text(config_file, text)
        say("  WROTE: " + config_file)


# --- providers ----------------------------------------------------------------------------

def provider_detected(name):
    top = {"claude": ".claude", "codex": ".codex", "gemini": ".gemini", "kiro": ".kiro"}[name]
    if os.path.exists(pj(HOME, top)) or shutil.which("kiro-cli" if name == "kiro" else name):
        return True
    return name == "kiro" and os.path.exists(KIRO_IDE)


def provider_list(text):
    if text.strip() == "all":
        return list(ALL_PROVIDERS)
    out = []
    for p in [x for x in re.split(r"[,\s]+", text) if x]:
        if p not in ALL_PROVIDERS:
            stop(2, "ERROR: unknown provider '%s' (one of: %s)" % (p, ", ".join(ALL_PROVIDERS)))
        if p not in out:
            out.append(p)
    return out


def choose_providers(config_file):
    if O.providers:
        return provider_list(O.providers)
    if O.uninstall and config_value(config_file, "providers"):
        return provider_list(config_value(config_file, "providers"))
    if not INTERACTIVE:
        return list(ALL_PROVIDERS)
    found = [p for p in ALL_PROVIDERS if provider_detected(p)]
    say("  Detected: " + (" ".join(found) if found else "none"))
    default = ",".join(found) if found else "all"
    ans = ask("  Deploy to which providers? (comma-separated; Enter for: %s)" % default)
    return provider_list(ans if ans.strip() else default)


def deploy_manifest_links(mode):
    for e in MANIFEST:
        if e.mode != mode:
            continue
        dest = dm.expand_dest(e.dest, HOME, KIRO_IDE, WIN)
        source = pj(REPO, e.source)
        if memory_source_missing(e.source, source, dest):
            continue
        need_dir(parent(dest))
        if e.kind == "symlink-file":
            if not deploy_instruction_file(e.dest, source, dest):
                link_file(source, dest)
        elif e.kind == "symlink-dir":
            link_dir(source, dest)


def deploy_kiro():
    say("=== Kiro CLI ===")
    agents = pj(HOME, ".kiro/agents")
    need_dir(agents)
    settings = pj(HOME, ".kiro/settings")
    need_dir(settings)
    for e in MANIFEST:
        if e.mode != "kiro-always":
            continue
        dest = dm.expand_dest(e.dest, HOME, KIRO_IDE, WIN)
        source = pj(REPO, e.source)
        need_dir(parent(dest))
        if os.path.exists(source):
            if e.kind == "template-file":
                copy_template(source, dest)
            elif e.kind == "seed-file":
                copy_seed(source, dest)
            else:
                with open(source, "rb") as fh:
                    write_owned_file("copy-file", dest, fh.read())

    # chat.defaultAgent: set only when it is not kiro_default already, and recorded in the lock with
    # the value it replaced, so that uninstall reverts only what setup set.
    old = lock_value("setting", LOCK_SETTING_KEY)
    if os.environ.get("AGENT_PLAYBOOK_SKIP_KIRO_CLI") == "1":
        say("  SKIP: kiro-cli settings (AGENT_PLAYBOOK_SKIP_KIRO_CLI=1)")
        if old:
            add_lock_row("setting", LOCK_SETTING_KEY, old)
    elif kiro_cli():
        prev = kiro_default_agent()
        if not prev:
            # a value setup cannot read is never replaced: uninstall could not put it back
            say("  WARN: kiro-cli's chat.defaultAgent could not be read, so it is left as is")
            if old:
                add_lock_row("setting", LOCK_SETTING_KEY, old)
        elif prev == '"kiro_default"':
            say("  OK: chat.defaultAgent = kiro_default (global)")
            if old:
                add_lock_row("setting", LOCK_SETTING_KEY, old)
        elif O.dry_run:
            say("    DRY: kiro-cli settings --global chat.defaultAgent kiro_default")
        elif run_kiro("settings", "--global", "chat.defaultAgent", "kiro_default"):
            say("  SET: chat.defaultAgent = kiro_default (global)")
            add_lock_row("setting", LOCK_SETTING_KEY, "-" if prev == "null" else prev)
        else:
            warn("  WARN: Failed to set chat.defaultAgent")
            if old:
                add_lock_row("setting", LOCK_SETTING_KEY, old)
    elif old:
        add_lock_row("setting", LOCK_SETTING_KEY, old)

    # Kiro IDE: steering and plain skills are links into the repo; overlay-bearing skills are generated
    # copies on every platform (the merge overwrites one file inside the skill folder).
    say("=== Kiro IDE ===")
    steering = pj(HOME, ".kiro/steering")
    skills = pj(HOME, ".kiro/skills")
    need_dir(steering)
    need_dir(skills)
    for e in MANIFEST:
        if e.mode != "kiro":
            continue
        dest = dm.expand_dest(e.dest, HOME, KIRO_IDE, WIN)
        need_dir(parent(dest))
        link_file(pj(REPO, e.source), dest)

    managed = []
    say("  Shared skills:")
    overlay_root = pj(REPO, "providers/kiro/skills")
    for name, full in list_dirs(pj(SHARED_DIR, "skills")):
        if not os.path.exists(pj(full, "SKILL.md")):
            continue
        ov = pj(overlay_root, name)
        dest = pj(skills, name)
        if dm.has_any_overlay(ov):
            deploy_generated_copy(full, dest, ov, name)
        else:
            # a real folder here: a generated copy left by an older overlay, or yours
            if is_dir_entry(dest) and not free_real_skill_dir(name):
                continue
            link_dir(full, dest)
        managed.append(name)
    if os.path.exists(overlay_root):
        say("  Kiro-specific skills:")
        for name, full in list_dirs(overlay_root):
            if not os.path.exists(pj(full, "SKILL.md")):
                continue
            if dm.has_any_overlay(pj(overlay_root, name)):
                continue   # a shared-skill overlay, merged above
            dest = pj(skills, name)
            if is_dir_entry(dest) and not free_real_skill_dir(name):
                continue
            link_dir(full, dest)
            managed.append(name)

    # A stale playbook skill is a link into this repo that no current skill owns; any other folder is
    # the user's (or another pack's) and is never removed.
    say("  Cleaning stale skills:")
    if os.path.exists(skills):
        managed_f = set(F(m) for m in managed)
        for name in sorted(os.listdir(skills), key=lambda s: (s.lower(), s) if WIN else s):
            full = pj(skills, name)
            if name.startswith(".") or dm.is_skill_cache(name) or not is_container(full):
                continue
            if F(name) not in managed_f and engine_link(full):
                remove_dir_link(full)
                say("  REMOVED: %s (stale, not in repo)" % name)

    say("  Cleaning files whose source is gone:")
    lock_retire("~/.kiro/")

    say()
    say("=== Cleanup stale files ===")
    # Frozen at these 7 entries: the deploy lock covers every later retirement. Entries are dated.
    stale_files = [pj(agents, "kiro_default.json"),                        # 2026-08-18
                   pj(steering, "claude-code-local-data.md"),              # 2026-09-20, and the rest
                   pj(steering, "v2-only/kiro-cli-local-data.md"),
                   pj(steering, "v2-only/memory-sources.md"),
                   pj(steering, "v2-only/session-resume-recovery-2.14.0.md"),
                   pj(steering, "v3/kiro-cli-local-data.md"),
                   pj(steering, "v3/memory-sources.md")]
    for st in stale_files:
        if not path_exists(st):
            continue
        lk = ""
        if is_regular_file(st):
            sk = lock_key(st)
            for c in LOCK_OLD:
                if c[1] == sk and c[0] not in ("backup", "setting"):
                    lk = c[2]
                    break
        if engine_link(st) or (lk and file_sha(st) == lk):
            remove_file(st)
            say("  REMOVED stale: " + st)
        else:
            say("  NOTE: %s is a retired playbook name, but not a file setup wrote unchanged" % st)
            backup_path(st)
    for sd in (pj(steering, "v2-only"), pj(steering, "v3")):
        if os.path.isdir(sd) and not os.listdir(sd):
            act("remove " + sd, lambda sd=sd: os.rmdir(sd))
            say("  REMOVED stale dir: " + sd)

    say()
    say("=== Verify v3 deployment ===")
    if not O.dry_run:
        expected = [pj(agents, "kiro_default.md"), pj(agents, "qdream_child.md"), pj(settings, "permissions.yaml")]
        miss = [p for p in expected if not os.path.exists(p)]
        if miss:
            warn("v3 deployment incomplete: " + ", ".join(miss))
        else:
            say("  OK: v3 agent and permissions deployed")


# --- main ---------------------------------------------------------------------------------

def run(argv):
    global O, INTERACTIVE, HOME, LOCK_FILE, LOCK_JOURNAL, CHOSEN, MANIFEST, KIRO_IDE
    global CLAUDE_SIDE_LINK, GEMINI_SIDE_LINK, GEMINI_SETTINGS, VENV_DIR
    O = parse_args(argv)
    INTERACTIVE = (not O.yes) and _isatty(sys.stdin) and _isatty(sys.stdout)
    HOME = os.environ.get("USERPROFILE" if WIN else "HOME") or ""
    if not HOME:
        stop(2, "ERROR: %s is not set; setup cannot tell your home folder" % ("USERPROFILE" if WIN else "HOME"))
    if WIN:
        HOME = HOME.replace("/", "\\").rstrip("\\") if len(HOME) > 3 else HOME
    else:
        HOME = HOME.rstrip("/") or "/"
    LOCK_FILE = pj(HOME, ".agent-playbook/deploy-lock.tsv")
    LOCK_JOURNAL = pj(HOME, ".agent-playbook/deploy-lock.journal.tsv")
    CLAUDE_SIDE_LINK = pj(HOME, ".claude/rules/agent-playbook.md")
    GEMINI_SIDE_LINK = pj(HOME, ".gemini/" + GEMINI_SIDE_NAME)
    GEMINI_SETTINGS = pj(HOME, ".gemini/settings.json")
    VENV_DIR = os.environ.get("AGENT_PLAYBOOK_TEST_VENV_DIR") or pj(REPO, ".venv-agent-playbook")

    try:
        MANIFEST = dm.read_manifest(pj(REPO, "inventory.tsv"))
    except dm.ManifestError as exc:
        stop(2, str(exc))
    say("  Manifest: %d entries loaded" % len(MANIFEST))
    if O.dry_run:
        say("  DRY RUN: nothing will be changed")
    KIRO_IDE = dm.kiro_ide_user_dir(os.environ, HOME, WIN)

    config_file = os.environ.get("AGENT_PLAYBOOK_CONFIG") or pj(HOME, ".agent-playbook/config")
    stores = os.environ.get("AGENT_PLAYBOOK_STORES") or config_value(config_file, "stores")
    if not stores:
        stores = pj(HOME, ".agent-playbook/stores")
    if WIN:
        stores = stores.replace("/", "\\")
    CHOSEN = choose_providers(config_file)

    read_deploy_lock()
    if O.uninstall:
        return run_uninstall(config_file)

    check_prereqs()
    venv_step()
    store_repo_step(stores)
    memory_link_step(stores)
    engine_branch_step()
    pointer_file_step(config_file, stores)

    for name, title, top in (("claude", "Claude Code", ".claude"), ("codex", "Codex", ".codex"),
                             ("gemini", "Gemini CLI", ".gemini")):
        if wants(name):
            say("=== %s ===" % title)
            need_dir(pj(HOME, top))
            deploy_manifest_links(name)
            say("  Skills (individual):")
            link_skills(pj(HOME, top + "/skills"))
    if wants("kiro"):
        deploy_kiro()

    say("=== Deploy lock ===")
    complete_deploy_lock(lock_carry_rows())
    failed = BACKUP_FAILED

    say()
    say("Done (providers: %s). Run '/qconfig-sync' from any agent to verify." % ", ".join(CHOSEN))
    if wants("claude"):
        # Only a person at a terminal may change settings.json: an agent-run setup never gets here.
        python = playbook_python()
        if O.dry_run:
            say("    DRY: offer the Claude Code entries in ~/.claude/settings.json")
        elif INTERACTIVE and os.path.isfile(python):
            subprocess.run([python, "-I", pj(REPO, "providers/claude/settings-entries.py"), "offer", "--home", HOME])
        else:
            say("NOTE: ~/.claude/settings.json was not changed. '/qconfig-sync' reports which Claude Code")
            say("      entries are set, and providers/claude/README.md says how to add them.")
    if failed > 0:
        stop(1, "ERROR: %d path(s) could not be backed up and were left unchanged (the ERROR lines above); close what holds them, then re-run setup" % failed)
    return 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except Stop as s:
        return s.code
    except KeyboardInterrupt:
        err("ERROR: interrupted")
        return 1
    except Exception as exc:   # an unexpected failure ends the run non-zero, as setup.ps1's Stop does
        err("ERROR: %s: %s" % (type(exc).__name__, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
