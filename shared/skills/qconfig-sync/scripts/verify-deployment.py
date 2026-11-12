#!/usr/bin/env python3
"""verify-deployment.py -- read-only deployment integrity check for the
agent-playbook config repo.

Enumerates expected provider symlinks (Claude, Codex, Gemini) and Kiro
copies/symlinks against the live filesystem, emitting one tab-separated
structured line per result. Called by /qconfig-sync Step 3. One script for
every platform: it replaces the verify-deployment.sh / verify-deployment.ps1
twins. On Windows (os.name == 'nt') it reproduces the .ps1's verdicts; on a
POSIX host it reproduces the .sh's (see "Platform model" below).

Inventory sources:
  - Top-level entries (CLAUDE.md, AGENTS.md, GEMINI.md, kiro/agents/kiro_default.md, ...)
    are loaded from `inventory.tsv` (see manifest at repo root) -- they do not
    grow with skill additions.
  - Per-skill Claude Code, Codex and Gemini entries (one link per shared skill inside
    the provider's own skills/ folder, never the whole folder) are enumerated dynamically
    from the subdirs of <repo>/shared/skills/. Another entry there (the user's own skill,
    a provider's built-ins) is never reported; only a stray link is an ORPHAN.
  - Only the providers setup deployed are checked: `providers=` of the pointer file
    (~/.agent-playbook/config, or AGENT_PLAYBOOK_CONFIG); the rest are SKIP not-selected.
  - Kiro skills are enumerated dynamically from BOTH <repo>/shared/skills/
    and <repo>/providers/kiro/skills/: plain skills as symlink-dir,
    overlay-bearing skills as copy-dir-recursive plus one merge-file row per
    merged target. Steering is symlinked on every platform (mode `kiro`);
    Windows copy mode was retired 2026-09-20.
  - The Claude memory rows (~/.claude/rules/playbook-user-memory.md and
    playbook-higher-order.md) link to <repo>/memory/MEMORY.md and HIGHER_ORDER.md,
    behind the repo's gitignored memory link. While that source is absent (no
    user memory in the store repo yet) setup makes no link, and the row is
    SKIP no-source=<path>; a link into the repo left there (dangling) is
    MISSING target=<link text> dangling-no-source=<path>, which setup removes.

Co-existence (lockstep with setup's "Co-existence" section): a file of the user's own
at ~/.claude/CLAUDE.md or ~/.gemini/GEMINI.md is accepted in place of the link when the
playbook loads beside it. A file of the user's own is setup's rule (is_user_file): a
regular file, or a link outside the repo to a file, that the deploy lock does not name
and that is not a byte copy of the source. For Claude Code that is the link
~/.claude/rules/agent-playbook.md to shared/AGENTS.md; for Gemini CLI the link
~/.gemini/AGENT-PLAYBOOK.md plus that name in `context.fileName` of
~/.gemini/settings.json. Each part gets its own line (the settings line is
OK|MISSING <settings.json> context.fileName...), and the instruction file is
OK <path> user-file-kept playbook-via=<side link> when every part is there, else
NOT_SYMLINK <path> user-file-kept-without-the-playbook. A byte copy of the source is
not the user's own file (setup replaces it), so it stays NOT_SYMLINK. Codex has
no such mechanism: its row is checked as a plain link. When the instruction file is
the link into the repo, a co-existence link left beside it is
DRIFTED <side link> leftover-side-link=<instruction file>, with a double-load detail
when the client loads it too (Claude Code always; Gemini CLI when context.fileName
lists its name): setup removes it. A settings.json that is not plain JSON (Gemini CLI
accepts comments; setup then leaves it alone) is MISSING ... context.fileName-lacks=,
the line to add by hand.

A folder of the user's own at a skill's name (lockstep with setup's KEPT rule) is
OK <path> user-folder-kept playbook-skill-not-deployed, which does not fail the run: setup
never replaces it, so the skill is not deployed there until the user renames or removes
it. For Claude Code, Codex and Gemini CLI that is anything at the skill's path that is not
a link. For Kiro it is a folder that holds a file and of which the deploy lock names no
file; at an overlay-bearing skill it must also hold a file at a path setup does not write
there (a folder holding only such paths is an older copy of setup's, checked as usual).

Overlay-merge awareness (lockstep with setup.sh / setup.ps1):
  setup MERGES a kiro overlay (`OVERLAY.md` for SKILL.md, `<stem>.OVERLAY.md`
  for an aux file) into the deployed target rather than copying the overlay
  standalone. This verifier mirrors that model: for an overlay-bearing skill it
  recomputes the expected merged content (see _merged_bytes / _has_any_overlay,
  which duplicate setup's merge_overlay / has_any_overlay byte-for-byte) and
  byte-compares the DEPLOYED file against the COMPUTED merge -- so a correct merge
  verifies OK and a stale/corrupt merge still reports DRIFTED. The overlay fragments
  themselves are merge INPUTS, never standalone deploy targets, so they are never
  reported MISSING. Overlay-bearing skills are generated copies in BOTH kiro modes
  (copy on Windows, generated-copy on Linux symlink profile); plain skills stay
  symlink/copy as before. Merge byte contract (must match setup): strip trailing
  newlines, join shared + "\\n\\n" + overlay + single "\\n" (empty/whitespace-only
  overlay -> shared + single "\\n"); no BOM. POSIX (setup.sh, `cat`): bytes as read,
  only trailing LF stripped (interior CRLF preserved). Windows (setup.ps1,
  ReadAllText): BOM dropped, trailing CR/LF stripped, re-encoded as no-BOM UTF-8.
  Correctness depends on the repo's `.gitattributes eol=lf` (sources are LF; the
  merge emits LF seam/trailing). The former source-driven-walk blind spot is
  now covered: a destination-side walk reports ORPHAN for a deployed file or
  skill dir whose source is gone (report-only, narrow scope -- see below).

Platform model:
  Windows: home = %USERPROFILE%, else the profile known folder, else %HOME%; the Kiro
  IDE dir = %APPDATA%\\Kiro\\User; paths are joined the way Join-Path joins them
  (backslashes); symlink targets are compared lexically and case-insensitively
  (Resolve-Path does not follow links); a Junction counts as a link; walks follow
  Get-ChildItem order and skip linked (symlink, junction, hard-linked) source files.
  That order is the directory listing's own (os.scandir, as Get-ChildItem used): NTFS
  returns names sorted, so a walk is name-ordered there, files before subdirectories;
  another filesystem (FAT, a network share) may return a different order.
  Both twins render C:/... roots; a template-file also verifies OK when it equals the
  render an older setup.sh produced under Git Bash (/c/... roots), so a deploy made
  before that change is not reported DRIFTED.
  POSIX: home = $HOME; the Kiro IDE dir = $APPDATA via cygpath when both exist,
  else ${XDG_CONFIG_HOME:-$HOME/.config}/Kiro/User; targets compared after
  realpath (readlink -f); walks follow find order.
  Both: a relative symlink target is resolved against the link's own folder, never
  the cwd. A provider top folder (~/.claude, ~/.codex, ~/.gemini, ~/.kiro) that does
  not exist is SKIP (not installed); one that is a dangling symlink is MISSING
  target=<link text> (a broken install, so it fails the run) and its entries are
  not checked one by one.

Reference: shared/skills/qconfig-sync/SKILL.md Step 3 mirrors this
inventory in human-readable form. The script is authoritative for
verification; setup.sh / setup.ps1 are authoritative for provisioning.
`test-parity.sh` cross-checks `verify-deployment.py --list` against the
entries created by `setup.sh`.

Output schema (tab-separated):
  <STATUS>\\t<path>\\t[target=<resolved>]\\t[expected=<expected>]
Where STATUS in {OK, MISSING, WRONG_TARGET, NOT_SYMLINK, DRIFTED, SKIP,
ORPHAN, AMBIGUOUS_SKILL}.
  ORPHAN           a deployed file or skill directory whose source is gone.
                   Emitted by the destination-side walk; REPORT-ONLY, never
                   fails the run, because the deployed tree also holds files
                   the manifest does not claim to own. Its last field says whose
                   it is, read from setup's deploy lock
                   (~/.agent-playbook/deploy-lock.tsv): owned-by-setup (a file the
                   lock names, a folder holding only such files, or a link into the
                   repo), mixed (a folder holding files the lock names and files it
                   does not) or foreign (anything else, a .bak setup made included).
                   A missing or unreadable lock makes every file and folder foreign.
  AMBIGUOUS_SKILL  a providers/kiro/skills/<name>/ setup cannot deploy
                   coherently. Two shapes, different fixes -- read the detail
                   field: (a) SKILL.md AND an overlay, so setup deploys the
                   overlay and drops the SKILL.md; (b) an overlay with NO
                   SKILL.md and no same-named shared skill, so setup deploys
                   nothing at all. Both DO fail the run.
The run ends with a SUMMARY line (counts per status) and, when it fails, a
REMEDIATION line.

Usage:
  verify-deployment.py [<repo-root>] [--list] | --help | -h | --selftest
  The optional positional <repo-root> overrides the repo root derived from this
  script's own location (never the cwd). --list prints the inventory instead:
  <kind>\\t<destination>\\t<source>\\t<mode>.

Exit codes:
  0 -- every line is OK, SKIP or ORPHAN.
  1 -- one or more MISSING/WRONG_TARGET/NOT_SYMLINK/DRIFTED/AMBIGUOUS_SKILL
       lines emitted.
  2 -- script-internal precondition failure (e.g., not in a recognizable
       agent-playbook repo, or a home directory that resolves empty), the venv
       guard, a directory the guard must walk that cannot be listed ("guard did
       not run: cannot list <path>: <error>" -- a permission or I/O error, never
       "does not exist"), or an unexpected error. The lines already printed are
       kept; no SUMMARY line is printed.

Tab-separated output is space-in-path-safe; paths with spaces work
transparently because tabs are not valid in path separators.

Stdlib only, Python 3.8+. Runs only under the playbook venv (see the venv guard stub).
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

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

NAME = "verify-deployment.py"

# --list wire-protocol kind vocabulary: the string VALUES are shared with setup.sh,
# setup.ps1 and test-parity.sh and must stay byte-identical.
KIND_SYMLINK_FILE = "symlink-file"
KIND_SYMLINK_DIR = "symlink-dir"
KIND_COPY_FILE = "copy-file"
KIND_COPY_DIR_RECURSIVE = "copy-dir-recursive"
KIND_MERGE_FILE = "merge-file"
KIND_TEMPLATE_FILE = "template-file"
KIND_SEED_FILE = "seed-file"
VALID_KINDS = (KIND_SYMLINK_FILE, KIND_SYMLINK_DIR, KIND_COPY_FILE, KIND_COPY_DIR_RECURSIVE,
               KIND_MERGE_FILE, KIND_TEMPLATE_FILE, KIND_SEED_FILE)
FILE_KINDS = (KIND_COPY_FILE, KIND_SYMLINK_FILE, KIND_TEMPLATE_FILE, KIND_SEED_FILE, KIND_MERGE_FILE)
DIR_KINDS = (KIND_COPY_DIR_RECURSIVE, KIND_SYMLINK_DIR)

# A folder never copied into a generated Kiro copy, like __pycache__ (setup.sh gen_expected and
# deploy_generated_copy, setup.ps1 Get-FilesNoFollow): fixtures/ holds selftest data, which the
# selftests read only from the repo. The orphan walk still reports a leftover one in a copy.
COPY_SKIP_DIR = "fixtures"


def _in_skipped_dir(rel):
    """True when a relative path (/ or \\ separated) lies under a fixtures/ folder."""
    return COPY_SKIP_DIR in re.split(r"[\\/]", rel)[:-1]

# The deploy lock setup writes (setup.sh "Deploy lock" section): read only for the ORPHAN owner field.
LOCK_HEADER = "# agent-playbook deploy lock v1 (written by setup; kind<TAB>path<TAB>sha256)"
LOCK_FILE_KINDS = ("copy-dir-recursive", "merge-file", "copy-file", "template-file")
LOCK_SETTING_KEY = "kiro-cli/chat.defaultAgent"
LOCK_GEMINI_KEY = "gemini/context.fileName"
OWNED, FOREIGN, MIXED = "owned-by-setup", "foreign", "mixed"
USER_FOLDER_KEPT = ("user-folder-kept", "playbook-skill-not-deployed")


def read_lock_keys(path):
    """-> the set of path keys of the lock's file rows, or an empty set for a missing or invalid lock.
    Untrusted input, read exactly as setup reads it: one bad row means no lock."""
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]
    if not lines or lines[0] != LOCK_HEADER:
        return set()
    keys = set()
    for line in lines[1:]:
        c = line.split("\t")
        if len(c) != 3:
            return set()
        kind, key, val = c
        if kind == "setting":
            if key not in (LOCK_SETTING_KEY, LOCK_GEMINI_KEY) or not val:
                return set()
            continue
        if (kind not in LOCK_FILE_KINDS + ("backup",) or not key.startswith("~/") or "/../" in "/" + key + "/"
                or "\\" in key or ":" in key):
            return set()
        if not (kind == "backup" and val == "-") and not re.match(r"^[0-9a-f]{64}$", val):
            return set()
        if kind != "backup":
            keys.add(key)
    return keys


# Co-existence: the instruction file (manifest dest) -> the side link setup makes beside a user's own file.
SIDE_LINKS = {"~/.claude/CLAUDE.md": ".claude/rules/agent-playbook.md",
              "~/.gemini/GEMINI.md": ".gemini/AGENT-PLAYBOOK.md"}
GEMINI_INSTRUCTIONS = "~/.gemini/GEMINI.md"
GEMINI_SIDE_NAME = "AGENT-PLAYBOOK.md"


STATUSES = ("OK", "MISSING", "WRONG_TARGET", "NOT_SYMLINK", "DRIFTED", "SKIP", "ORPHAN", "AMBIGUOUS_SKILL")
FAILING = ("MISSING", "WRONG_TARGET", "NOT_SYMLINK", "DRIFTED", "AMBIGUOUS_SKILL")

TEMPLATE_SKIP_REASON = ("reason=template-file render not checkable from an MSYS shell; "
                        "run this script with native Windows Python to verify it")
AMBIG_BOTH = "SKILL.md and an overlay in one directory; setup deploys the overlay and silently drops the SKILL.md"
AMBIG_NONE = ("overlay with no SKILL.md and no shared/skills/%s to merge into; "
              "setup deploys nothing for this directory")
REMEDIATION = (
    "Re-run setup for the affected provider (setup.ps1 on Windows, setup.sh elsewhere) to redeploy from "
    "source. Never hand-edit the deployed copy to match the source: the repo is the source of truth and the "
    "deployed file is a build artifact, so the next deploy silently reverts the edit. For AMBIGUOUS_SKILL, "
    "read the detail field first -- it has two shapes with different fixes. SKILL.md beside an overlay: "
    "decide what the directory is, deleting the SKILL.md if it is an overlay for a shared skill, or the "
    "overlay files if it is a standalone kiro skill. Overlay with no SKILL.md and no shared skill: there is "
    "nothing to delete and removing the overlay discards its only content -- create the shared skill it "
    "extends, rename the directory to match one, or promote the overlay to a standalone SKILL.md. For "
    "ORPHAN, delete the deployed file only after confirming its source was removed deliberately; an "
    "ORPHAN with not-deployed=fixtures is a test fixture an older setup copied, safe to delete (setup "
    "removes the ones it wrote unchanged).")

# Windows file attributes / reparse tags (stat.* names exist only on Windows builds).
_ATTR_HIDDEN = 0x2
_ATTR_SYSTEM = 0x4
_ATTR_DIRECTORY = 0x10
_ATTR_REPARSE = 0x400
_TAG_SYMLINK = 0xA000000C
_TAG_MOUNT_POINT = 0xA0000003

# .NET Char.IsWhiteSpace -- what String.Trim() strips (setup.ps1's blank-overlay test).
_NET_WS = ("\t\n\x0b\x0c\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007"
           "\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000")
_POSIX_SPACE = b" \t\n\r\x0b\x0c"   # tr -d '[:space:]'


class Precondition(Exception):
    """Exit 2 with these stderr lines (a twin's `exit 2` precondition)."""

    def __init__(self, *lines):
        Exception.__init__(self, lines[0] if lines else "")
        self.lines = lines


# --- byte helpers -----------------------------------------------------------

def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _net_read_text(path):
    """[IO.File]::ReadAllText: BOM-detected decode (UTF-8 without BOM by default)."""
    data = _read_bytes(path)
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    if data[:4] == b"\xff\xfe\x00\x00":
        return data[4:].decode("utf-32-le", "replace")
    if data[:2] == b"\xff\xfe":
        return data[2:].decode("utf-16-le", "replace")
    if data[:2] == b"\xfe\xff":
        return data[2:].decode("utf-16-be", "replace")
    if data[:4] == b"\x00\x00\xfe\xff":
        return data[4:].decode("utf-32-be", "replace")
    return data.decode("utf-8", "replace")


def _bash_cat(path):
    """"$(cat path)": the bytes, NULs dropped, trailing newlines (LF only) stripped."""
    return _read_bytes(path).replace(b"\0", b"").rstrip(b"\n")


def _merged_bytes(shared_file, overlay_file, windows):
    """The bytes setup writes for a merged target (setup.ps1 Merge-Overlay on Windows,
    setup.sh merge_overlay elsewhere). LOCKSTEP with both setup twins."""
    if windows:
        shared = _net_read_text(shared_file).rstrip("\r\n")
        overlay = _net_read_text(overlay_file)
        if overlay.strip(_NET_WS):
            return (shared + "\n\n" + overlay.rstrip("\r\n") + "\n").encode("utf-8")
        return (shared + "\n").encode("utf-8")
    shared = _bash_cat(shared_file)
    overlay = _bash_cat(overlay_file)
    if any(b not in _POSIX_SPACE for b in overlay):
        return shared + b"\n\n" + overlay + b"\n"
    return shared + b"\n"


def _msys_path(path):
    """C:\\Users\\X -> /c/Users/X (the form $HOME / $REPO_ROOT take under Git Bash)."""
    p = path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", p):
        p = "/" + p[0].lower() + p[2:]
    return p


def _files_equal(a, b):
    try:
        return _read_bytes(a) == _read_bytes(b)
    except OSError:
        return False


def _file_is(path, data):
    try:
        return _read_bytes(path) == data
    except OSError:
        return False


def _c_key(s):
    return s.encode("utf-8", "surrogateescape")


# --- Windows (.ps1 semantics) filesystem helpers ------------------------------

def _winjoin(base, child):
    """Join-Path: both sides' '/' become '\\', one separator at the seam."""
    base = base.replace("/", "\\")
    child = child.replace("/", "\\")
    if not base:
        return child
    return base.rstrip("\\") + "\\" + child.lstrip("\\")


def _lstat(path):
    try:
        return os.lstat(path)
    except (OSError, ValueError):
        return None


def _list_entries(path):
    """The one directory-listing primitive: os.scandir entries in enumeration order.
    Raises OSError. The selftest replaces it to inject a listing failure."""
    with os.scandir(path) as it:
        return list(it)


def _cannot_list(path, exc):
    return Precondition("%s: guard did not run: cannot list %s: %s" % (NAME, path, exc))


def _entries(path):
    """_list_entries, a failure stopping the run with exit 2: an unlistable directory must
    never read as an empty one, or part of the inventory is silently not checked."""
    try:
        return _list_entries(path)
    except OSError as exc:
        raise _cannot_list(path, exc)


def _dir_exists(path):
    """True for a directory (links followed); False when nothing is there, a dangling link,
    or a non-directory. A permission or I/O error stops the run (exit 2) instead of reading
    as 'not there'."""
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError, ValueError):
        return False
    except OSError as exc:
        raise _cannot_list(path, exc)
    return stat.S_ISDIR(st.st_mode)


def _link_dest(link_path, raw):
    """A symlink's target text, resolved the way the OS resolves it: relative to the link's
    own folder, never the cwd. An absolute target is returned unchanged."""
    return os.path.join(os.path.dirname(link_path), raw)


def _require_home(home):
    if not home or home == "~":
        raise Precondition("%s: guard did not run: home directory could not be resolved" % NAME)


def _attrs(st):
    return getattr(st, "st_file_attributes", 0) if st is not None else 0


def _ps_link_type(path, st=None):
    """FileSystemInfo LinkType: 'SymbolicLink', 'Junction', 'HardLink' or ''."""
    st = st if st is not None else _lstat(path)
    if st is None:
        return ""
    attrs = _attrs(st)
    if attrs & _ATTR_REPARSE:
        tag = getattr(st, "st_reparse_tag", 0)
        if tag == _TAG_SYMLINK:
            return "SymbolicLink"
        if tag == _TAG_MOUNT_POINT:
            return "Junction"
        return ""
    if not attrs & _ATTR_DIRECTORY and getattr(st, "st_nlink", 1) > 1:
        return "HardLink"
    return ""


def _ps_children(dirpath, force=True):
    """Get-ChildItem -LiteralPath dirpath [-Force]: (name, full, lstat) in enumeration order."""
    out = []
    for entry in _entries(dirpath):
        try:
            st = os.lstat(entry.path)
        except FileNotFoundError:
            continue   # removed between the listing and the stat
        except OSError as exc:
            raise _cannot_list(dirpath, exc)
        if not force and _attrs(st) & (_ATTR_HIDDEN | _ATTR_SYSTEM):
            continue
        out.append((entry.name, _winjoin(dirpath, entry.name), st))
    return out


def _ps_is_dir_item(st):
    return bool(_attrs(st) & _ATTR_DIRECTORY)


def _ps_recurse_files(dirpath):
    """Get-ChildItem -File -Recurse -Force: a directory's files, then each subdirectory in
    turn; reparse-point directories are not descended into."""
    files, subdirs = [], []
    for name, full, st in _ps_children(dirpath, force=True):
        if _ps_is_dir_item(st):
            if not _attrs(st) & _ATTR_REPARSE:
                subdirs.append(full)
        else:
            files.append((full, st))
    for f in files:
        yield f
    for d in subdirs:
        for f in _ps_recurse_files(d):
            yield f


def _win_readlink(path):
    try:
        target = os.readlink(path)
    except (OSError, ValueError):
        return ""
    if target.startswith("\\\\?\\UNC\\"):
        return "\\\\" + target[8:]
    if target.startswith("\\\\?\\") or target.startswith("\\??\\"):
        return target[4:]
    return target


def _win_canon(path):
    """Resolve-Path -LiteralPath p .ProviderPath, else p: normalises, never follows links."""
    if os.path.lexists(path):
        return os.path.abspath(path)
    return path


def _win_known_profile():
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
        fid = GUID(0x5E6C858F, 0x0E22, 0x4760, (ctypes.c_ubyte * 8)(0x9A, 0xFE, 0xEA, 0x33, 0x17, 0xB6, 0x71, 0x73))
        buf = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(buf)) != 0:
            return ""
        value = buf.value or ""
        ctypes.windll.ole32.CoTaskMemFree(buf)
        return value
    except Exception:
        return ""


def _is_msys_host():
    try:
        sysname = os.uname().sysname
    except AttributeError:
        return False
    return sysname.startswith(("MINGW", "MSYS", "CYGWIN"))


# --- the verifier -------------------------------------------------------------

class Verifier(object):
    def __init__(self, repo_root, environ, windows, out, err):
        self.win = windows
        self.env = environ
        self.out = out
        self.err = err
        self.repo = repo_root
        self.total = 0
        self.counts = dict.fromkeys(STATUSES, 0)
        if windows:
            self.home = environ.get("USERPROFILE") or _win_known_profile() or environ.get("HOME") or ""
            _require_home(self.home)
            appdata = environ.get("APPDATA")
            if not appdata:
                raise RuntimeError("APPDATA is not set (the Kiro IDE dir is %APPDATA%\\Kiro\\User)")
            self.kiro_ide = _winjoin(_winjoin(appdata, "Kiro"), "User")
            self.render_home = environ.get("USERPROFILE") or self.home
        else:
            # An empty HOME is rejected, not resolved: expanduser("~") would turn it into "/".
            home = environ.get("HOME")
            self.home = home if home is not None else os.path.expanduser("~")
            _require_home(self.home)
            appdata = environ.get("APPDATA")
            cyg = shutil.which("cygpath") if appdata else None
            if appdata and cyg:
                conv = subprocess.run([cyg, "-u", appdata], stdout=subprocess.PIPE, check=True)
                self.kiro_ide = conv.stdout.decode("utf-8", "replace").rstrip("\n") + "/Kiro/User"
            else:
                self.kiro_ide = (environ.get("XDG_CONFIG_HOME") or self.home + "/.config") + "/Kiro/User"
        self.shared_skills = self.join(repo_root, "shared/skills")
        self.kiro_provider_skills = self.join(repo_root, "providers/kiro/skills")
        self.kiro_overlay_root = self.kiro_provider_skills
        self.kiro_top = self.join(self.home, ".kiro")
        self.manifest = []
        self._lock_keys = None

    # --- paths ---
    def join(self, base, child):
        if self.win:
            return _winjoin(base, child)
        return base + "/" + child

    def exists(self, p):
        return os.path.exists(p)

    # --- deploy lock ---
    def lock_owner(self, full):
        """owned-by-setup or foreign for an ORPHAN path (see the docstring's ORPHAN entry)."""
        if os.path.islink(full) or (self.win and _ps_link_type(full)):
            try:
                t = _win_readlink(full) if self.win else os.path.realpath(full)
            except OSError:
                t = ""
            t = (t or "").replace("\\", "/").rstrip("/")
            root = self.repo.replace("\\", "/").rstrip("/")
            if self.win:
                t, root = t.lower(), root.lower()
            return OWNED if t == root or t.startswith(root + "/") else FOREIGN
        key = self.lock_key(full)
        if key is None:
            return FOREIGN
        keys = self.locked_keys()
        if key in keys:
            return OWNED
        if any(k.startswith(key + "/") for k in keys):
            # a folder holding a locked file: setup's alone, or mixed when it also holds a file the
            # lock does not name (setup removes only its own unedited files there)
            for f in self._files_under(full):
                if self.lock_key(f) not in keys:
                    return MIXED
            return OWNED
        return FOREIGN

    def locked_keys(self):
        """The lock's file-row keys (lower case on Windows); empty for a missing or invalid lock."""
        if self._lock_keys is None:
            keys = read_lock_keys(self.join(self.home, ".agent-playbook/deploy-lock.tsv"))
            self._lock_keys = set(k.lower() for k in keys) if self.win else keys
        return self._lock_keys

    def lock_key(self, full):
        """-> the lock's ~/ spelling of a path under home (lower case on Windows), or None."""
        home = self.home.replace("\\", "/").rstrip("/")
        p = full.replace("\\", "/")
        if self.win:
            home, p = home.lower(), p.lower()
        if not p.startswith(home + "/"):
            return None
        return "~/" + p[len(home) + 1:]

    def _files_under(self, top):
        """Every entry under top that is not a folder, links included and never followed."""
        out = []
        for d, dirs, files in os.walk(top):
            keep = []
            for n in dirs:
                full = os.path.join(d, n)
                if os.path.islink(full) or (self.win and _ps_link_type(full)):
                    out.append(full)
                else:
                    keep.append(n)
            dirs[:] = keep
            out.extend(os.path.join(d, n) for n in files)
        return out

    def user_folder_kept(self, dest, expected_rels=None, any_entry=False):
        """setup's KEPT rule for a real entry at a skill's name: True when it is the user's own, so
        setup leaves it and does not deploy the skill there. Claude Code, Codex, Gemini CLI
        (any_entry): anything that is not a link. Kiro: not a link, and the lock names no file in
        it; for a generated copy (expected_rels given) it must also hold a file at a path setup does
        not write there (else it is an older copy of setup's, which setup updates)."""
        if not os.path.lexists(dest) or os.path.islink(dest) or (self.win and _ps_link_type(dest)):
            return False
        if any_entry or not os.path.isdir(dest):
            return True
        key = self.lock_key(dest)
        if key is not None and any(k.startswith(key + "/") for k in self.locked_keys()):
            return False
        # setup's KEPT test leaves __pycache__ and fixtures/ out of the files it counts
        files = [r for r in (os.path.relpath(f, dest).replace("\\", "/") for f in self._files_under(dest))
                 if "__pycache__" not in r.split("/") and not _in_skipped_dir(r)]
        if expected_rels is None:
            return bool(files)
        exp = set(r.lower() for r in expected_rels) if self.win else set(expected_rels)
        return any((f.lower() if self.win else f) not in exp for f in files)

    # --- output ---
    def emit(self, status, path, *extras):
        self.out("\t".join((status, path) + extras))
        self.total += 1
        self.counts[status] += 1

    # --- precondition and manifest ---
    def check_repo(self):
        has_skills = os.path.isdir(self.join(self.repo, "shared/skills"))
        has_sh = os.path.isfile(self.join(self.repo, "setup.sh"))
        if self.win:
            has_ps1 = os.path.isfile(self.join(self.repo, "setup.ps1"))
            if not has_skills or not (has_ps1 or has_sh):
                raise Precondition(
                    "%s: cannot resolve agent-playbook repo root (tried: %s)" % (NAME, self.repo),
                    "%s: expected <repo>/shared/skills/ and <repo>/setup.ps1 (or setup.sh) to exist" % NAME)
        elif not has_skills or not has_sh:
            raise Precondition(
                "%s: cannot resolve agent-playbook repo root (tried: %s)" % (NAME, self.repo),
                "%s: expected <repo>/shared/skills/ and <repo>/setup.sh to exist" % NAME)

    def read_manifest(self):
        path = self.join(self.repo, "inventory.tsv")
        if not os.path.isfile(path):
            raise Precondition("ERROR: manifest not found: %s" % path)
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            text = fh.read()
        if self.win:
            lines = re.split(r"\r\n|\n|\r", text)
            if lines and lines[-1] == "":
                lines.pop()
        else:
            # `while read -r line` never processes a final line without a newline.
            lines = text.split("\n")[:-1]
        entries = []
        for num, line in enumerate(lines, 1):
            if re.match(r"^\s*#", line) or re.match(r"^\s*$", line):
                continue
            cols = line.split("\t")
            if len(cols) != 4:
                raise Precondition("ERROR: manifest line %d has %d columns (expected 4): %s"
                                   % (num, len(cols), line))
            if cols[0] not in VALID_KINDS:
                raise Precondition("ERROR: manifest line %d has unknown kind '%s': %s" % (num, cols[0], line))
            entries.append(tuple(cols))
        self.err("  Manifest: %d entries loaded" % len(entries))
        self.manifest = entries

    def expand_dest(self, dest):
        prefixes = ("<KIRO_IDE_USER>/", "<KIRO_IDE_USER>\\") if self.win else ("<KIRO_IDE_USER>/",)
        if dest.startswith(prefixes):
            return self.join(self.kiro_ide, dest[16:])
        home_prefixes = ("~/", "~\\") if self.win else ("~/",)
        if dest.startswith(home_prefixes):
            return self.join(self.home, dest[2:])
        return dest

    def expand_source(self, source):
        return self.join(self.repo, source)

    # --- skill enumeration and overlays ---
    def list_skills(self, root):
        if not _dir_exists(root):
            return []
        if self.win:
            names = []
            for name, _full, st in _ps_children(root, force=True):
                if not _ps_is_dir_item(st):
                    continue
                low = name.lower()
                if low in (".system", ".trash", "synced") or low.startswith(".bucket-"):
                    continue
                names.append(name)
            return names
        names = []
        for name in sorted((e.name for e in _entries(root)), key=_c_key):
            if name.startswith("."):
                continue   # a `*/` glob never matches a dot entry
            if not _dir_exists(root + "/" + name):
                continue
            if name in ("synced",) or name.startswith(".bucket-"):
                continue
            names.append(name)
        return names

    def _aux_overlays(self, overlay_dir):
        """*.OVERLAY.md fragments except the reserved SKILL.OVERLAY.md: [(name, full)]."""
        found = []
        if self.win:
            for name, full, st in _ps_children(overlay_dir, force=False):
                if _ps_is_dir_item(st):
                    continue
                low = name.lower()
                if low.endswith(".overlay.md") and low not in ("overlay.md", "skill.overlay.md"):
                    found.append((name, full))
            return found
        for name in sorted((e.name for e in _entries(overlay_dir)), key=_c_key):
            if name.startswith(".") or not name.endswith(".OVERLAY.md") or len(name) <= len(".OVERLAY.md"):
                continue
            full = overlay_dir + "/" + name
            if not os.path.isfile(full) or name in ("OVERLAY.md", "SKILL.OVERLAY.md"):
                continue
            found.append((name, full))
        return found

    def has_any_overlay(self, overlay_dir):
        if not _dir_exists(overlay_dir):
            return False
        ov = self.join(overlay_dir, "OVERLAY.md")
        if (os.path.exists(ov) if self.win else os.path.isfile(ov)):
            return True
        return bool(self._aux_overlays(overlay_dir))

    def merge_targets(self, shared_skill_dir, overlay_dir):
        """[(target relpath, shared file, overlay file)] in --list order."""
        if not _dir_exists(overlay_dir):
            return []
        targets = {}
        skill_ov = self.join(overlay_dir, "OVERLAY.md")
        shared_md = self.join(shared_skill_dir, "SKILL.md")
        if self.win:
            if os.path.exists(skill_ov) and os.path.exists(shared_md):
                targets["skill.md"] = ("SKILL.md", shared_md, skill_ov)
            for name, full in self._aux_overlays(overlay_dir):
                target = name[:-len(".OVERLAY.md")] + ".md"
                shared_target = self.join(shared_skill_dir, target)
                if os.path.exists(shared_target):
                    targets[target.lower()] = (target, shared_target, full)
            return [targets[k] for k in sorted(targets)]
        if os.path.isfile(skill_ov) and os.path.isfile(shared_md):
            targets["SKILL.md"] = ("SKILL.md", shared_md, skill_ov)
        for name, full in self._aux_overlays(overlay_dir):
            target = name[:-len(".OVERLAY.md")] + ".md"
            shared_target = shared_skill_dir + "/" + target
            if os.path.isfile(shared_target):
                targets[target] = (target, shared_target, full)
        return [targets[k] for k in sorted(targets, key=_c_key)]

    # --- --list ---
    def inventory(self):
        rows = []
        for kind, dest, source, mode in self.manifest:
            rows.append((kind, self.expand_dest(dest), self.expand_source(source), mode))
        for mode, top in (("claude", ".claude"), ("codex", ".codex"), ("gemini", ".gemini")):
            # one link per shared skill inside the provider's own skills/ folder
            for skill in self.list_skills(self.shared_skills):
                rows.append((KIND_SYMLINK_DIR, self.join(self.home, top + "/skills/" + skill),
                             self.join(self.shared_skills, skill), mode))
        for skill in self.list_skills(self.shared_skills):
            overlay_dir = self.join(self.kiro_overlay_root, skill)
            dest = self.join(self.home, ".kiro/skills/" + skill)
            src = self.join(self.shared_skills, skill)
            if self.has_any_overlay(overlay_dir):
                rows.append((KIND_COPY_DIR_RECURSIVE, dest, src, "kiro"))
                for target, shared_file, _ov in self.merge_targets(src, overlay_dir):
                    rows.append((KIND_MERGE_FILE, self.join(dest, target), shared_file, "kiro"))
            else:
                rows.append((KIND_SYMLINK_DIR, dest, src, "kiro"))
        if _dir_exists(self.kiro_provider_skills):
            for skill in self.list_skills(self.kiro_provider_skills):
                if self.has_any_overlay(self.join(self.kiro_overlay_root, skill)):
                    continue   # overlay-only dirs are merge inputs, not standalone targets
                rows.append((KIND_SYMLINK_DIR, self.join(self.home, ".kiro/skills/" + skill),
                             self.join(self.kiro_provider_skills, skill), "kiro"))
        return rows

    # --- per-entry checkers ---
    def check_symlink(self, path, expected):
        if self.win:
            expected_canon = _win_canon(expected)
            if not os.path.lexists(path):
                self.emit("MISSING", path)
                return
            if _ps_link_type(path) not in ("SymbolicLink", "Junction"):
                self.emit("NOT_SYMLINK", path)
                return
            raw = _win_readlink(path)
            if not raw:
                self.emit("WRONG_TARGET", path, "target=", "expected=" + expected_canon)
                return
            resolved = _link_dest(path, raw)
            if not os.path.exists(resolved):
                self.emit("MISSING", path, "target=" + raw, "expected=" + expected_canon)
                return
            actual = _win_canon(resolved)
            if actual.lower() != expected_canon.lower():
                self.emit("WRONG_TARGET", path, "target=" + actual, "expected=" + expected_canon)
                return
            self.emit("OK", path)
            return
        expected_canon = os.path.realpath(expected)
        if not os.path.islink(path) and not os.path.exists(path):
            self.emit("MISSING", path)
            return
        if not os.path.islink(path):
            self.emit("NOT_SYMLINK", path)
            return
        if not os.path.exists(path):
            try:
                raw = os.readlink(path)
            except OSError:
                raw = ""
            self.emit("MISSING", path, "target=" + raw, "expected=" + expected_canon)
            return
        try:
            raw = os.readlink(path)
        except OSError:
            self.emit("WRONG_TARGET", path, "target=", "expected=" + expected_canon)
            return
        # The same resolution rule as the Windows branch (_link_dest), then realpath for the rest of the chain.
        actual = os.path.realpath(_link_dest(path, raw))
        if actual != expected_canon:
            self.emit("WRONG_TARGET", path, "target=" + actual, "expected=" + expected_canon)
            return
        self.emit("OK", path)

    def check_copy_file(self, path, source):
        if not os.path.exists(path):
            self.emit("MISSING", path)
        elif not os.path.exists(source):
            self.emit("DRIFTED", path, "expected=" + source)
        elif _files_equal(path, source):
            self.emit("OK", path)
        else:
            self.emit("DRIFTED", path, "expected=" + source)

    def check_template_file(self, path, source):
        if not os.path.exists(path):
            self.emit("MISSING", path)
            return
        if not os.path.exists(source):
            self.emit("DRIFTED", path, "expected=" + source)
            return
        if self.win:
            body = _net_read_text(source).rstrip("\r\n")
            body = body.replace("{{USER_HOME}}", self.render_home.replace("\\", "/"))
            body = body.replace("{{PLAYBOOK_ROOT}}", self.repo.replace("\\", "/"))
            if _file_is(path, (body + "\n").encode("utf-8")) or self._is_git_bash_render(path, source):
                self.emit("OK", path)
            else:
                self.emit("DRIFTED", path, "expected=" + source)
            return
        body = _bash_cat(source)
        body = body.replace(b"{{USER_HOME}}", self.home.encode("utf-8", "surrogateescape"))
        body = body.replace(b"{{PLAYBOOK_ROOT}}", self.repo.encode("utf-8", "surrogateescape"))
        try:
            same = _bash_cat(path) == body.rstrip(b"\n")
        except OSError:
            same = False
        if same:
            self.emit("OK", path)
        elif _is_msys_host():
            self.emit("SKIP", path, TEMPLATE_SKIP_REASON)
        else:
            self.emit("DRIFTED", path, "expected=" + source)

    def _is_git_bash_render(self, path, source):
        """Windows only: is `path` the render setup.sh writes under Git Bash on this machine?
        Its $HOME / $REPO_ROOT are MSYS paths: /c/... or, under a mount such as /tmp, the
        `cygpath -u` spelling. Every spelling we can derive is tried."""
        def spellings(p):
            found = [_msys_path(p)]
            cyg = shutil.which("cygpath")
            if cyg:
                try:
                    conv = subprocess.run([cyg, "-u", p], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                          check=True, timeout=30)
                    alt = conv.stdout.decode("utf-8", "replace").rstrip("\r\n")
                    if alt and alt not in found:
                        found.append(alt)
                except (OSError, subprocess.SubprocessError):
                    pass
            return found
        try:
            raw = _bash_cat(source)
            deployed = _read_bytes(path)
        except OSError:
            return False
        for home in spellings(self.home):
            for repo in spellings(self.repo):
                body = raw.replace(b"{{USER_HOME}}", home.encode("utf-8"))
                body = body.replace(b"{{PLAYBOOK_ROOT}}", repo.encode("utf-8"))
                if deployed == body + b"\n":
                    return True
        return False

    def check_seed_file(self, path, source):
        if not os.path.exists(source):
            self.emit("DRIFTED", path, "expected=" + source)
        elif os.path.exists(path):
            self.emit("OK", path)
        else:
            self.emit("MISSING", path)

    def _posix_find_files(self, top, rel="", skip_fixtures=True):
        """find . \\( -name __pycache__ -o -type d -name fixtures \\) -prune -o -type f -print: relpaths in
        readdir order. skip_fixtures=False (the orphan walk) lists fixtures/ folders too."""
        for e in _entries(top if not rel else top + "/" + rel):
            if e.name == "__pycache__":
                continue
            r = e.name if not rel else rel + "/" + e.name
            if e.is_dir(follow_symlinks=False):
                if skip_fixtures and e.name == COPY_SKIP_DIR:
                    continue
                for sub in self._posix_find_files(top, r, skip_fixtures):
                    yield sub
            elif e.is_file(follow_symlinks=False):
                yield r

    def check_copy_dir_recursive(self, dest_dir, source_dir, overlay_dir=""):
        if not _dir_exists(source_dir):
            return
        if not _dir_exists(dest_dir):
            self.emit("MISSING", dest_dir)
            return
        merge = {}
        if overlay_dir and self.has_any_overlay(overlay_dir):
            for target, shared_file, ov_file in self.merge_targets(source_dir, overlay_dir):
                merge[target.lower() if self.win else target] = (shared_file, ov_file)
        if self.win:
            source_full = os.path.abspath(source_dir)
            walk = []
            for full, st in _ps_recurse_files(source_full):
                rel = full[len(source_full):].lstrip("\\/")
                if _ps_link_type(full, st) or re.search(r"[\\/]__pycache__[\\/]", full) or _in_skipped_dir(rel):
                    continue
                walk.append((rel, full))
        else:
            walk = [(rel, source_dir + "/" + rel) for rel in self._posix_find_files(source_dir)]
        for rel, source_file in walk:
            dest_file = self.join(dest_dir, rel)
            if not os.path.exists(dest_file):
                self.emit("MISSING", dest_file)
                continue
            key = rel.lower() if self.win else rel
            if key in merge:
                shared_file, ov_file = merge[key]
                if _file_is(dest_file, _merged_bytes(shared_file, ov_file, self.win)):
                    self.emit("OK", dest_file)
                else:
                    self.emit("DRIFTED", dest_file, "expected=merge(%s)" % source_file)
                continue
            if _files_equal(dest_file, source_file):
                self.emit("OK", dest_file)
            else:
                self.emit("DRIFTED", dest_file, "expected=" + source_file)

    # --- sections ---
    def _mode_rows(self, mode):
        for kind, dest, source, m in self.manifest:
            if m == mode:
                yield kind, self.expand_dest(dest), self.expand_source(source)

    def check_link_row(self, mode):
        """The link rows of a Claude, Codex or Gemini mode, with the memory-source SKIP and co-existence."""
        for kind, raw_dest, raw_source, m in self.manifest:
            if m != mode:
                continue
            dest, source = self.expand_dest(raw_dest), self.expand_source(raw_source)
            if mode == "gemini" and self.win and kind not in (KIND_SYMLINK_FILE, KIND_SYMLINK_DIR):
                continue   # the .ps1 checks only the two symlink kinds here; the .sh checks every row
            if raw_source.startswith("memory/") and not os.path.exists(source):
                if self.engine_link(dest):
                    # setup removes a link it made once the source is gone; one still there is dangling
                    self.emit("MISSING", dest, "target=" + self._link_text(dest), "dangling-no-source=" + source)
                else:
                    self.emit("SKIP", dest, "no-source=" + source)
                continue
            side = SIDE_LINKS.get(raw_dest)
            gemini = raw_dest == GEMINI_INSTRUCTIONS
            if side and self.is_user_file(dest, source):
                self.check_coexist(dest, source, self.join(self.home, side), gemini)
                continue
            self.check_symlink(dest, source)
            if side:
                self.check_double_load(dest, self.join(self.home, side), gemini)

    def _is_link(self, path):
        return os.path.islink(path) or bool(self.win and _ps_link_type(path))

    def _link_text(self, path):
        try:
            return (_win_readlink(path) if self.win else os.readlink(path)) or ""
        except OSError:
            return ""

    def engine_link(self, path):
        """A symlink (or junction) whose target text names a path inside the repo, dangling or not. The
        text is compared, never its resolution: the repo's own memory link points out of the repo, so a
        link to memory/MEMORY.md would resolve outside it."""
        if not self._is_link(path):
            return False
        raw = self._link_text(path)
        if not raw:
            return False
        t = os.path.normpath(_link_dest(path, raw)).replace("\\", "/").rstrip("/")
        root = os.path.normpath(self.repo).replace("\\", "/").rstrip("/")
        if self.win:
            t, root = t.lower(), root.lower()
            if t.startswith("//?/"):
                t = t[4:]
        return t == root or t.startswith(root + "/")

    def is_user_file(self, path, source):
        """The user's own instruction file, setup's rule (setup.sh user_instruction_file, setup.ps1
        Test-UserInstructionFile): a regular file, or a link outside the repo to a file; not a file the
        deploy lock names; not a byte copy of its source."""
        if self._is_link(path) and self.engine_link(path):
            return False
        if not os.path.isfile(path):
            return False
        key = self.lock_key(path)
        if key is not None and key in self.locked_keys():
            return False
        try:
            return not os.path.isfile(source) or not _files_equal(path, source)
        except OSError:
            return True

    def check_double_load(self, dest, side, gemini):
        """The instruction file is the link into the repo: a co-existence link beside it is a leftover
        setup removes (and, when the client loads it too, a second copy of the playbook)."""
        if not self.engine_link(dest) or not self.engine_link(side):
            return
        extras = ["leftover-side-link=" + dest]
        if not gemini:
            extras.append("double-load")
        elif GEMINI_SIDE_NAME in (self._gemini_names() or []):
            extras += ["double-load", "context.fileName-lists=" + GEMINI_SIDE_NAME]
        self.emit("DRIFTED", side, *extras)

    def check_coexist(self, dest, source, side, gemini):
        ok_before = self.counts["OK"]
        self.check_symlink(side, source)
        ok = self.counts["OK"] > ok_before
        if gemini:
            ok = self.check_gemini_setting() and ok
        if ok:
            self.emit("OK", dest, "user-file-kept", "playbook-via=" + side)
        else:
            self.emit("NOT_SYMLINK", dest, "user-file-kept-without-the-playbook")

    def _gemini_names(self):
        """-> context.fileName of ~/.gemini/settings.json as a list, or None (absent or not plain JSON)."""
        path = self.join(self.home, ".gemini/settings.json")
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
            data = json.loads(raw.decode("utf-8")) if raw.strip() else {}
            ctx = data.get("context") if isinstance(data, dict) else None
            names = ctx.get("fileName") if isinstance(ctx, dict) else None
        except (OSError, ValueError):
            names = None
        names = [names] if isinstance(names, str) else names
        return names if isinstance(names, list) else None

    def check_gemini_setting(self):
        """-> True when context.fileName of ~/.gemini/settings.json lists the playbook's file name."""
        path = self.join(self.home, ".gemini/settings.json")
        names = self._gemini_names()
        if names is not None and GEMINI_SIDE_NAME in names:
            self.emit("OK", path, "context.fileName")
            return True
        self.emit("MISSING", path, "context.fileName-lacks=" + GEMINI_SIDE_NAME)
        return False

    def provider_installed(self, top):
        """-> True when the provider top folder is a directory. Not there at all: SKIP (not
        installed). A dangling symlink in its place: MISSING target=<link text>, a broken
        install that fails the run; its entries are not checked one by one."""
        if _dir_exists(top):
            return True
        if os.path.lexists(top) and not os.path.exists(top):
            if self.win:
                raw = _win_readlink(top)
            else:
                try:
                    raw = os.readlink(top)
                except OSError:
                    raw = ""
            self.emit("MISSING", top, "target=" + raw)
        else:
            self.emit("SKIP", top)
        return False

    def selected_providers(self):
        """The providers setup deployed (`providers=` of the pointer file), or None: check every installed one."""
        path = self.env.get("AGENT_PLAYBOOK_CONFIG") or self.join(self.home, ".agent-playbook/config")
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return None
        for line in reversed(lines):
            k, sep, v = line.strip().partition("=")
            if sep and k.strip() == "providers" and v.strip():
                return set(x.strip() for x in v.split(",") if x.strip())
        return None

    def wanted(self, provider, top):
        """-> True to check `provider`: chosen at setup (or no choice recorded) and installed."""
        chosen = self.selected_providers()
        if chosen is not None and provider not in chosen:
            self.emit("SKIP", top, "not-selected")
            return False
        return self.provider_installed(top)

    def check_skill_links(self, top):
        for skill in self.list_skills(self.shared_skills):
            dest = self.join(top, "skills/" + skill)
            if self.user_folder_kept(dest, any_entry=True):
                self.emit("OK", dest, *USER_FOLDER_KEPT)
                continue
            self.check_symlink(dest, self.join(self.shared_skills, skill))

    def _source_rels(self, source_dir):
        if self.win:
            full = os.path.abspath(source_dir)
            return [f[len(full):].lstrip("\\/").replace("\\", "/") for f, st in _ps_recurse_files(full)
                    if not _ps_link_type(f, st) and not re.search(r"[\\/]__pycache__[\\/]", f)
                    and not _in_skipped_dir(f[len(full):])]
        return list(self._posix_find_files(source_dir))

    def check_all(self):
        claude_top = self.join(self.home, ".claude")
        if self.wanted("claude", claude_top):
            self.check_link_row("claude")
            self.check_skill_links(claude_top)

        codex_top = self.join(self.home, ".codex")
        if self.wanted("codex", codex_top):
            self.check_link_row("codex")
            self.check_skill_links(codex_top)

        gemini_top = self.join(self.home, ".gemini")
        if self.wanted("gemini", gemini_top):
            self.check_link_row("gemini")
            self.check_skill_links(gemini_top)

        if self.wanted("kiro", self.kiro_top):
            for kind, dest, source in self._mode_rows("kiro-always"):
                if kind == KIND_TEMPLATE_FILE:
                    self.check_template_file(dest, source)
                elif kind == KIND_SEED_FILE:
                    self.check_seed_file(dest, source)
                else:
                    self.check_copy_file(dest, source)
            for _kind, dest, source in self._mode_rows("kiro"):
                self.check_symlink(dest, source)
            for skill in self.list_skills(self.shared_skills):
                overlay_dir = self.join(self.kiro_overlay_root, skill)
                dest = self.join(self.kiro_top, "skills/" + skill)
                src = self.join(self.shared_skills, skill)
                if self.has_any_overlay(overlay_dir):
                    if _dir_exists(src) and self.user_folder_kept(dest, self._source_rels(src)):
                        self.emit("OK", dest, *USER_FOLDER_KEPT)
                    else:
                        self.check_copy_dir_recursive(dest, src, overlay_dir)
                elif self.user_folder_kept(dest):
                    self.emit("OK", dest, *USER_FOLDER_KEPT)
                else:
                    self.check_symlink(dest, src)
            if _dir_exists(self.kiro_provider_skills):
                for skill in self.list_skills(self.kiro_provider_skills):
                    if self.has_any_overlay(self.join(self.kiro_overlay_root, skill)):
                        continue
                    dest = self.join(self.kiro_top, "skills/" + skill)
                    if self.user_folder_kept(dest):
                        self.emit("OK", dest, *USER_FOLDER_KEPT)
                    else:
                        self.check_symlink(dest, self.join(self.kiro_provider_skills, skill))

        self.orphan_walk()
        self.ambiguous_check()

    def orphan_walk(self):
        """Destination-side walk, REPORT-ONLY and deliberately narrow: a generated skill directory
        (files whose source counterpart is gone) and a skills root (entries that are no skill)."""
        rows = self.inventory()
        if self.win:
            exp_files = set(r[1].lower() for r in rows if r[0] in FILE_KINDS)
            exp_dirs_list = [r[1] for r in rows if r[0] in DIR_KINDS]
            exp_dirs = set(d.lower() for d in exp_dirs_list)
            for kind, dest, src, _mode in rows:
                if kind != KIND_COPY_DIR_RECURSIVE or not _dir_exists(dest):
                    continue
                if _ps_link_type(dest):
                    continue   # a linked dir mirrors its source by construction
                found = [full for full, _st in _ps_recurse_files(dest)
                         if not re.search(r"[\\/]__pycache__[\\/]", full)]
                for full in sorted(found, key=lambda s: s.lower()):
                    rel = full[len(dest):].lstrip("\\/")
                    candidate = _winjoin(src, rel)
                    if _in_skipped_dir(rel):
                        self.emit("ORPHAN", full, "not-deployed=" + COPY_SKIP_DIR, self.lock_owner(full))
                        continue
                    if os.path.exists(candidate) or full.lower() in exp_files:
                        continue
                    self.emit("ORPHAN", full, "expected-source=" + candidate, self.lock_owner(full))
            roots = {}
            for d in exp_dirs_list:
                parent = os.path.dirname(d)
                if os.path.basename(parent).lower() == "skills":
                    roots.setdefault(parent.lower(), parent)
            for root in sorted(roots.values(), key=lambda s: s.lower()):
                if not _dir_exists(root):
                    continue
                kiro_root = root.lower() == _winjoin(self.kiro_top, "skills").lower()
                entries = [(name, full) for name, full, st in _ps_children(root, force=True)
                           if _ps_link_type(full, st) or (kiro_root and _ps_is_dir_item(st))]
                for name, full in sorted(entries, key=lambda e: e[1].lower()):
                    if name.startswith(".") or full.lower() in exp_dirs:
                        continue
                    self.emit("ORPHAN", full, "no-source-skill", self.lock_owner(full))
            return
        exp_files = set(r[1] for r in rows if r[0] in FILE_KINDS)
        exp_dirs = set(r[1] for r in rows if r[0] in DIR_KINDS)
        for kind, dest, src, _mode in rows:
            if kind != KIND_COPY_DIR_RECURSIVE or not _dir_exists(dest) or os.path.islink(dest):
                continue
            for rel in sorted(self._posix_find_files(dest, skip_fixtures=False), key=_c_key):
                deployed = dest + "/" + rel
                if _in_skipped_dir(rel):
                    self.emit("ORPHAN", deployed, "not-deployed=" + COPY_SKIP_DIR, self.lock_owner(deployed))
                    continue
                if os.path.exists(src + "/" + rel) or deployed in exp_files:
                    continue
                self.emit("ORPHAN", deployed, "expected-source=%s/%s" % (src, rel), self.lock_owner(deployed))
        roots = set()
        for d in exp_dirs:
            parent = d.rsplit("/", 1)[0] if "/" in d else ""
            if parent.endswith("/skills"):
                roots.add(parent)
        for root in sorted(roots, key=_c_key):
            if not _dir_exists(root):
                continue
            # Outside Kiro's skills root a provider's skills/ folder also holds the user's own skills
            # (and another pack's): only a link there can be a stale playbook skill.
            kiro_root = root == self.kiro_top + "/skills"
            entries = []
            for name in (e.name for e in _entries(root)):
                full = root + "/" + name
                if os.path.islink(full) or (kiro_root and _dir_exists(full)):
                    entries.append((name, full))
            for name, full in sorted(entries, key=lambda e: _c_key(e[1])):
                if name.startswith(".") or full in exp_dirs:
                    continue
                self.emit("ORPHAN", full, "no-source-skill", self.lock_owner(full))

    def ambiguous_check(self):
        """A providers/kiro/skills/<name>/ is a standalone skill (SKILL.md) or an overlay, never both,
        and an overlay needs a shared skill to merge into. Source hygiene: runs without a Kiro deploy."""
        root = self.kiro_provider_skills
        if not _dir_exists(root):
            return
        if self.win:
            dirs = sorted([(name, full) for name, full, st in _ps_children(root, force=False) if _ps_is_dir_item(st)],
                          key=lambda e: e[1].lower())
        else:
            names = sorted((e.name for e in _entries(root)), key=_c_key)
            dirs = [(n, root + "/" + n) for n in names if not n.startswith(".") and _dir_exists(root + "/" + n)]
        for name, full in dirs:
            has_skill = os.path.isfile(self.join(full, "SKILL.md"))
            has_ov = os.path.isfile(self.join(full, "OVERLAY.md")) or bool(self._aux_overlays(full))
            if has_skill and has_ov:
                self.emit("AMBIGUOUS_SKILL", full, AMBIG_BOTH)
            elif not has_skill and has_ov and not _dir_exists(self.join(self.repo, "shared/skills/" + name)):
                self.emit("AMBIGUOUS_SKILL", full, AMBIG_NONE % name)

    def summary(self):
        c = self.counts
        self.out("SUMMARY\ttotal=%d\tok=%d\tmissing=%d\twrong_target=%d\tnot_symlink=%d\tdrifted=%d\tskip=%d"
                 "\torphan=%d\tambiguous_skill=%d" % (self.total, c["OK"], c["MISSING"], c["WRONG_TARGET"],
                                                      c["NOT_SYMLINK"], c["DRIFTED"], c["SKIP"], c["ORPHAN"],
                                                      c["AMBIGUOUS_SKILL"]))
        # ORPHAN is deliberately absent: the orphan walk is report-only.
        if sum(c[s] for s in FAILING) > 0:
            self.out("REMEDIATION\t" + REMEDIATION)
            return 1
        return 0


def default_repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def run(argv, environ, out, err, windows=None, default_root=None):
    """-> exit code. `out`/`err` receive lines as they are produced, so an error keeps them."""
    windows = (os.name == "nt") if windows is None else windows
    list_mode = False
    repo = default_root or default_repo_root()
    try:
        for arg in argv:
            if arg == "--list":
                list_mode = True
            elif arg in ("--help", "-h"):
                for line in __doc__.strip("\n").split("\n"):
                    out(line)
                return 0
            elif arg.startswith("--"):
                err("%s: unknown flag: %s" % (NAME, arg))
                return 2
            else:
                repo = arg
        v = Verifier(repo, environ, windows, out, err)
        v.check_repo()
        v.read_manifest()
        if list_mode:
            for row in v.inventory():
                out("\t".join(row))
            return 0
        v.check_all()
        return v.summary()
    except Precondition as exc:
        for line in exc.lines:
            err(line)
        return 2
    except Exception as exc:
        err("%s: guard did not run: unexpected error: %s: %s" % (NAME, type(exc).__name__, exc))
        return 2


def main(argv=None):
    _require_venv(__file__)
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
            except Exception:
                pass
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()

    def out(line):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def err(line):
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    return run(argv, os.environ, out, err)


# ---------------------------------------------------------------------------
# Selftest: synthetic repo + sandbox home, verifier run in process
# ---------------------------------------------------------------------------

def _w(path, data):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def _symlinks_available(tmp):
    probe_target = os.path.join(tmp, "probe-target")
    _w(probe_target, b"x")
    try:
        os.symlink(probe_target, os.path.join(tmp, "probe-link"))
        os.mkdir(os.path.join(tmp, "probe-dir"))
        os.symlink(os.path.join(tmp, "probe-dir"), os.path.join(tmp, "probe-dlink"), target_is_directory=True)
        return True, ""
    except (OSError, NotImplementedError, AttributeError) as exc:
        return False, "os.symlink unavailable (%s: %s)" % (type(exc).__name__, exc)


_ST_SHARED_SKILL = b"# Beta\n\nshared body\n"
_ST_OVERLAY = b"kiro-only delta\n\n"
_ST_MERGED = b"# Beta\n\nshared body\n\nkiro-only delta\n"     # written by hand, never by _merged_bytes
_ST_AUX_SHARED = b"aux shared\n"
_ST_AUX_OVERLAY = b"aux overlay\n"
_ST_AUX_MERGED = b"aux shared\n\naux overlay\n"
_ST_TEMPLATE = b"home={{USER_HOME}}\nroot={{PLAYBOOK_ROOT}}\n"


def _st_build(base, links):
    """A fake repo, a sandbox home and the deploy setup would make there. -> (repo, home, environ)."""
    repo = os.path.join(base, "repo")
    home = os.path.join(base, "home")
    windows = os.name == "nt"
    inv = ["# schema-version: 1", "copy-file\t~/.kiro/AUTHORING.md\tshared/AUTHORING.md\tkiro-always",
           "template-file\t~/.kiro/agents/def.md\tproviders/kiro/agents/def.md\tkiro-always",
           "seed-file\t<KIRO_IDE_USER>/mcp.json\tproviders/kiro/settings/mcp.json\tkiro-always"]
    if links:
        inv[1:1] = ["symlink-file\t~/.claude/CLAUDE.md\tshared/AGENTS.md\tclaude",
                    "symlink-file\t~/.claude/rules/playbook-user-memory.md\tmemory/MEMORY.md\tclaude",
                    "symlink-file\t~/.codex/AGENTS.md\tshared/AGENTS.md\tcodex",
                    "symlink-file\t~/.gemini/GEMINI.md\tshared/AGENTS.md\tgemini"]
        inv.append("symlink-file\t~/.kiro/steering/agents.md\tshared/AGENTS.md\tkiro")
    _w(os.path.join(repo, "inventory.tsv"), "\n".join(inv) + "\n")
    _w(os.path.join(repo, "setup.sh"), b"#!/bin/sh\n")
    _w(os.path.join(repo, "setup.ps1"), b"# stub\n")
    _w(os.path.join(repo, "shared", "AGENTS.md"), b"agents\n")
    _w(os.path.join(repo, "shared", "AUTHORING.md"), b"authoring\n")
    if links:
        _w(os.path.join(repo, "shared", "skills", "alpha", "SKILL.md"), b"# Alpha\n")
        _w(os.path.join(repo, "providers", "kiro", "skills", "gamma", "SKILL.md"), b"# Gamma\n")
    beta = os.path.join(repo, "shared", "skills", "beta")
    _w(os.path.join(beta, "SKILL.md"), _ST_SHARED_SKILL)
    _w(os.path.join(beta, "aux.md"), _ST_AUX_SHARED)
    _w(os.path.join(beta, "ref.md"), b"reference\n")
    _w(os.path.join(beta, "sub", "deep.md"), b"deep\n")
    # selftest data setup never copies (a fixtures/ folder), and a FILE named fixtures, which it does
    _w(os.path.join(beta, "scripts", "fixtures", "case", "case.json"), b"{}\n")
    _w(os.path.join(beta, "sub", "fixtures"), b"a file, not a folder\n")
    _w(os.path.join(repo, "providers", "kiro", "skills", "beta", "OVERLAY.md"), _ST_OVERLAY)
    _w(os.path.join(repo, "providers", "kiro", "skills", "beta", "aux.OVERLAY.md"), _ST_AUX_OVERLAY)
    _w(os.path.join(repo, "providers", "kiro", "agents", "def.md"), _ST_TEMPLATE)
    _w(os.path.join(repo, "providers", "kiro", "settings", "mcp.json"), b"{}\n")

    if windows:
        environ = {"USERPROFILE": home, "APPDATA": os.path.join(home, "AppData", "Roaming")}
        ide = os.path.join(home, "AppData", "Roaming", "Kiro", "User")
        rhome, rrepo = home.replace("\\", "/"), repo.replace("\\", "/")
    else:
        environ = {"HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config")}
        ide = os.path.join(home, ".config", "Kiro", "User")
        rhome, rrepo = home, repo
    kiro = os.path.join(home, ".kiro")
    _w(os.path.join(kiro, "AUTHORING.md"), b"authoring\n")
    _w(os.path.join(kiro, "agents", "def.md"), ("home=%s\nroot=%s\n" % (rhome, rrepo)).encode("utf-8"))
    _w(os.path.join(ide, "mcp.json"), b'{"edited": "in app"}\n')
    kbeta = os.path.join(kiro, "skills", "beta")
    _w(os.path.join(kbeta, "SKILL.md"), _ST_MERGED)
    _w(os.path.join(kbeta, "aux.md"), _ST_AUX_MERGED)
    _w(os.path.join(kbeta, "ref.md"), b"reference\n")
    _w(os.path.join(kbeta, "sub", "deep.md"), b"deep\n")
    _w(os.path.join(kbeta, "sub", "fixtures"), b"a file, not a folder\n")
    if links:
        def link(target, at, is_dir=False):
            d = os.path.dirname(at)
            if not os.path.isdir(d):
                os.makedirs(d)
            os.symlink(target, at, target_is_directory=is_dir)
        link(os.path.join(repo, "shared", "AGENTS.md"), os.path.join(home, ".claude", "CLAUDE.md"))
        link(os.path.join(repo, "shared", "AGENTS.md"), os.path.join(home, ".codex", "AGENTS.md"))
        for s in ("alpha", "beta"):
            # one link per skill inside each provider's own skills/ folder
            link(os.path.join(repo, "shared", "skills", s), os.path.join(home, ".claude", "skills", s), True)
            link(os.path.join(repo, "shared", "skills", s), os.path.join(home, ".codex", "skills", s), True)
        link(os.path.join(repo, "shared", "AGENTS.md"), os.path.join(kiro, "steering", "agents.md"))
        link(os.path.join(repo, "shared", "skills", "alpha"), os.path.join(kiro, "skills", "alpha"), True)
        link(os.path.join(repo, "providers", "kiro", "skills", "gamma"), os.path.join(kiro, "skills", "gamma"), True)
    return repo, home, environ


def _st_run(repo, environ, argv=None):
    out, err = [], []
    rc = run(list(argv or []) + [repo], environ, out.append, err.append)
    return rc, out, err


def _st_cases(tmp, links, skip_reason):
    """-> (failures, checks, skipped): every case on a fresh tree."""
    fails, skipped = [], []
    checks = [0]
    n = [0]

    def check(cond, label):
        checks[0] += 1
        if not cond:
            fails.append(label)

    def fresh():
        n[0] += 1
        return _st_build(os.path.join(tmp, "case%02d" % n[0]), links)

    def has(out, status, suffix, extra=None):
        for line in out:
            parts = line.split("\t")
            if parts[0] == status and parts[1].replace("\\", "/").endswith(suffix):
                if extra is None or any(p.startswith(extra) for p in parts[2:]):
                    return True
        return False

    def bad(out):
        return [l for l in out if l.split("\t")[0] in FAILING]

    # OK: a clean deploy verifies clean, the merged targets included.
    repo, home, env = fresh()
    rc, out, err = _st_run(repo, env)
    check(rc == 0 and not bad(out), "clean deploy exits 0 with no failing line (rc=%d, %r)" % (rc, bad(out)))
    check(has(out, "OK", ".kiro/skills/beta/SKILL.md"), "merged SKILL.md verifies OK")
    check(has(out, "OK", ".kiro/skills/beta/aux.md"), "merged aux file verifies OK")
    check(has(out, "OK", ".kiro/skills/beta/sub/deep.md"), "nested plain copy verifies OK")
    check(not any("fixtures/case" in l.replace("\\", "/") for l in out),
          "a source fixtures/ folder is not expected in the generated copy")
    check(has(out, "OK", ".kiro/skills/beta/sub/fixtures"), "a FILE named fixtures is still copied and verified")
    check(has(out, "OK", ".kiro/agents/def.md"), "template render verifies OK")
    check(has(out, "OK", "Kiro/User/mcp.json"), "seed file present verifies OK despite in-app edit")
    check(out and out[-1].startswith("SUMMARY\t") and "REMEDIATION" not in "".join(out),
          "a clean run ends with SUMMARY and no REMEDIATION")
    check(any(l.startswith("  Manifest: ") for l in err), "manifest count goes to stderr")
    check(has(out, "SKIP", "home/.gemini"), "a provider top folder that does not exist -> SKIP")
    if links:
        check(has(out, "OK", ".codex/skills/alpha") and has(out, "OK", ".kiro/skills/gamma"),
              "plain and standalone skill symlinks verify OK")
        check(not any("providers/kiro/skills/beta" in l.replace("\\", "/") and l.startswith("MISSING")
                      for l in out), "overlay fragments are never reported MISSING")

    # MISSING: a copy-file and a file inside a generated copy.
    repo, home, env = fresh()
    os.remove(os.path.join(home, ".kiro", "AUTHORING.md"))
    os.remove(os.path.join(home, ".kiro", "skills", "beta", "sub", "deep.md"))
    os.remove(os.path.join(home, "AppData", "Roaming", "Kiro", "User", "mcp.json") if os.name == "nt"
              else os.path.join(home, ".config", "Kiro", "User", "mcp.json"))
    rc, out, _ = _st_run(repo, env)
    check(rc == 1, "MISSING exits 1")
    check(has(out, "MISSING", ".kiro/AUTHORING.md"), "missing copy-file -> MISSING")
    check(has(out, "MISSING", ".kiro/skills/beta/sub/deep.md"), "missing file in a generated copy -> MISSING")
    check(has(out, "MISSING", "Kiro/User/mcp.json"), "missing seed file -> MISSING")
    check(any(l.startswith("REMEDIATION\t") for l in out), "a failing run prints REMEDIATION")

    # DRIFTED, plain copy: copy-file and a non-merged file inside the generated copy.
    repo, home, env = fresh()
    _w(os.path.join(home, ".kiro", "AUTHORING.md"), b"hand edited\n")
    _w(os.path.join(home, ".kiro", "skills", "beta", "ref.md"), b"hand edited\n")
    rc, out, _ = _st_run(repo, env)
    check(rc == 1 and has(out, "DRIFTED", ".kiro/AUTHORING.md", "expected="), "drifted copy-file -> DRIFTED")
    check(has(out, "DRIFTED", ".kiro/skills/beta/ref.md", "expected="), "drifted plain file in a copy -> DRIFTED")

    # DRIFTED, merged copy: a stale merge (the bare shared file) and a corrupt seam.
    repo, home, env = fresh()
    _w(os.path.join(home, ".kiro", "skills", "beta", "SKILL.md"), _ST_SHARED_SKILL)
    _w(os.path.join(home, ".kiro", "skills", "beta", "aux.md"), b"aux shared\naux overlay\n")
    rc, out, _ = _st_run(repo, env)
    check(rc == 1 and has(out, "DRIFTED", ".kiro/skills/beta/SKILL.md", "expected=merge("),
          "stale merged SKILL.md -> DRIFTED expected=merge(...)")
    check(has(out, "DRIFTED", ".kiro/skills/beta/aux.md", "expected=merge("), "corrupt merged aux -> DRIFTED")

    # DRIFTED, template: a stale render.
    repo, home, env = fresh()
    _w(os.path.join(home, ".kiro", "agents", "def.md"), b"home=/elsewhere\nroot=/elsewhere\n")
    rc, out, _ = _st_run(repo, env)
    if os.name == "nt" or not _is_msys_host():
        check(rc == 1 and has(out, "DRIFTED", ".kiro/agents/def.md"), "stale template render -> DRIFTED")
    else:
        check(has(out, "SKIP", ".kiro/agents/def.md", "reason="), "stale template under MSYS -> SKIP")
    if os.name == "nt":
        repo, home, env = fresh()
        _w(os.path.join(home, ".kiro", "agents", "def.md"),
           ("home=%s\nroot=%s\n" % (_msys_path(home), _msys_path(repo))).encode("utf-8"))
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "OK", ".kiro/agents/def.md"), "a setup.sh (Git Bash) render verifies OK on Windows")

    if links:
        # WRONG_TARGET, NOT_SYMLINK, dangling link.
        repo, home, env = fresh()
        alpha_link = os.path.join(home, ".codex", "skills", "alpha")
        os.rmdir(alpha_link) if os.name == "nt" else os.remove(alpha_link)
        os.symlink(os.path.join(repo, "shared", "skills", "beta"), alpha_link, target_is_directory=True)
        claude_md = os.path.join(home, ".claude", "CLAUDE.md")
        os.remove(claude_md)
        _w(claude_md, b"agents\n")
        codex_md = os.path.join(home, ".codex", "AGENTS.md")
        os.remove(codex_md)
        os.symlink(os.path.join(repo, "shared", "GONE.md"), codex_md)
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "WRONG_TARGET", ".codex/skills/alpha", "target="),
              "symlink to the wrong source -> WRONG_TARGET")
        check(has(out, "NOT_SYMLINK", ".claude/CLAUDE.md"), "regular file where a symlink belongs -> NOT_SYMLINK")
        check(has(out, "MISSING", ".codex/AGENTS.md", "target="), "dangling symlink -> MISSING target=...")
    else:
        skipped.extend(["WRONG_TARGET", "NOT_SYMLINK", "dangling symlink"])
        print("  SKIP WRONG_TARGET / NOT_SYMLINK / dangling cases: %s" % skip_reason)

    # ORPHAN: report-only.
    repo, home, env = fresh()
    _w(os.path.join(home, ".kiro", "skills", "beta", "stale.md"), b"left behind\n")
    _w(os.path.join(home, ".kiro", "skills", "beta", "__pycache__", "x.pyc"), b"\0")
    # an older copy's fixture file, whose source still exists: setup no longer deploys it
    _w(os.path.join(home, ".kiro", "skills", "beta", "scripts", "fixtures", "case", "case.json"), b"{}\n")
    os.makedirs(os.path.join(home, ".kiro", "skills", "ghost"))
    os.makedirs(os.path.join(home, ".kiro", "skills", ".tool-managed"))
    rc, out, _ = _st_run(repo, env)
    check(rc == 0, "ORPHAN never fails the run (rc=%d)" % rc)
    check(has(out, "ORPHAN", ".kiro/skills/beta/stale.md", "expected-source="), "stale file in a copy -> ORPHAN")
    check(has(out, "ORPHAN", ".kiro/skills/ghost", "no-source-skill"), "skill dir with no source -> ORPHAN")
    check(not any("__pycache__" in l or ".tool-managed" in l for l in out),
          "bytecode caches and dot entries are not orphans")
    check(has(out, "ORPHAN", ".kiro/skills/beta/scripts/fixtures/case/case.json", "not-deployed=fixtures"),
          "a leftover fixtures/ file in a copy -> ORPHAN not-deployed=fixtures, though its source exists")
    check(sum(1 for l in out if l.startswith("ORPHAN\t")) == 3, "exactly three ORPHAN lines")
    check(has(out, "ORPHAN", ".kiro/skills/ghost", "foreign") and has(out, "ORPHAN", "beta/stale.md", "foreign"),
          "with no deploy lock, an ORPHAN is foreign")

    # ORPHAN owner field from the deploy lock: a locked file and a folder holding one are setup's;
    # a .bak setup made is the user's content, so foreign; an invalid lock is no lock.
    repo, home, env = fresh()
    _w(os.path.join(home, ".kiro", "skills", "beta", "stale.md"), b"left behind\n")
    _w(os.path.join(home, ".kiro", "skills", "beta", "SKILL.md.bak"), b"yours\n")
    _w(os.path.join(home, ".kiro", "skills", "gone", "SKILL.md"), b"old\n")
    os.makedirs(os.path.join(home, ".kiro", "skills", "mine"))
    sha = "0" * 64
    lock_rows = ["copy-dir-recursive\t~/.kiro/skills/beta/stale.md\t" + sha,
                 "backup\t~/.kiro/skills/beta/SKILL.md\t" + sha,
                 "copy-dir-recursive\t~/.kiro/skills/gone/SKILL.md\t" + sha]
    lock_path = os.path.join(home, ".agent-playbook", "deploy-lock.tsv")
    _w(lock_path, LOCK_HEADER + "\n" + "\n".join(lock_rows) + "\n")
    rc, out, _ = _st_run(repo, env)
    check(rc == 0, "ORPHAN with a lock never fails the run (rc=%d)" % rc)
    check(has(out, "ORPHAN", "beta/stale.md", "owned-by-setup"), "a locked file -> ORPHAN owned-by-setup")
    check(has(out, "ORPHAN", "beta/SKILL.md.bak", "foreign"), "a .bak setup made -> ORPHAN foreign")
    check(has(out, "ORPHAN", ".kiro/skills/gone", "owned-by-setup"), "a folder holding a locked file -> owned-by-setup")
    check(has(out, "ORPHAN", ".kiro/skills/mine", "foreign"), "a folder the lock does not name -> foreign")
    _w(lock_path, LOCK_HEADER + "\n" + "\n".join(lock_rows) + "\nnot a row\n")
    rc, out, _ = _st_run(repo, env)
    check(has(out, "ORPHAN", "beta/stale.md", "foreign"), "a lock with a malformed row is no lock -> foreign")
    for bad_key in ("~/.kiro/..\\..\\Documents\\x", "~/.kiro/C:x", "~/.kiro/a/../b"):
        _w(lock_path, LOCK_HEADER + "\n" + "\n".join(lock_rows + ["copy-file\t%s\t%s" % (bad_key, sha)]) + "\n")
        rc, out, _ = _st_run(repo, env)
        check(has(out, "ORPHAN", "beta/stale.md", "foreign"),
              "a lock key holding \\, : or a .. segment makes the lock no lock (%s)" % bad_key)
    # A folder holding a locked file and a file the lock does not name -> mixed.
    _w(os.path.join(home, ".kiro", "skills", "gone", "mine.md"), b"yours\n")
    _w(lock_path, LOCK_HEADER + "\n" + "\n".join(lock_rows) + "\n")
    rc, out, _ = _st_run(repo, env)
    check(has(out, "ORPHAN", ".kiro/skills/gone", "mixed"), "a folder holding locked and unlocked files -> mixed")

    # A folder of the user's own at an overlay skill's name (no locked file, a file setup does not
    # write) -> OK user-folder-kept, never failing; one holding only setup's paths is checked as usual.
    repo, home, env = fresh()
    kb = os.path.join(home, ".kiro", "skills", "beta")
    shutil.rmtree(kb)
    _w(os.path.join(kb, "SKILL.md"), b"my own beta\n")
    _w(os.path.join(kb, "notes.md"), b"mine\n")
    rc, out, _ = _st_run(repo, env)
    check(rc == 0 and has(out, "OK", ".kiro/skills/beta", "user-folder-kept") and not bad(out),
          "a user folder at an overlay skill's name -> OK user-folder-kept (rc=%d, %r)" % (rc, bad(out)))
    os.remove(os.path.join(kb, "notes.md"))
    rc, out, _ = _st_run(repo, env)
    check(rc == 1 and has(out, "DRIFTED", ".kiro/skills/beta/SKILL.md") and not has(out, "OK", ".kiro/skills/beta", "user-folder-kept"),
          "a folder holding only paths setup writes is an older copy -> checked, DRIFTED")
    _w(os.path.join(kb, "notes.md"), b"mine\n")
    _w(os.path.join(home, ".agent-playbook", "deploy-lock.tsv"),
       LOCK_HEADER + "\nmerge-file\t~/.kiro/skills/beta/SKILL.md\t" + "0" * 64 + "\n")
    rc, out, _ = _st_run(repo, env)
    check(rc == 1 and not has(out, "OK", ".kiro/skills/beta", "user-folder-kept"),
          "a folder the lock names a file of is setup's, never user-folder-kept")

    if links:
        def mklink(target, at, is_dir=False):
            if not os.path.isdir(os.path.dirname(at)):
                os.makedirs(os.path.dirname(at))
            os.symlink(target, at, target_is_directory=is_dir)

        # The memory rows: no source (no user memory yet) -> SKIP; the link to it -> OK; no link -> MISSING.
        repo, home, env = fresh()
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "SKIP", ".claude/rules/playbook-user-memory.md", "no-source="),
              "a memory row whose source is absent -> SKIP no-source=")
        _w(os.path.join(repo, "memory", "MEMORY.md"), b"# Memory\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "MISSING", ".claude/rules/playbook-user-memory.md"),
              "a memory row whose source exists but has no link -> MISSING")
        mklink(os.path.join(repo, "memory", "MEMORY.md"), os.path.join(home, ".claude", "rules", "playbook-user-memory.md"))
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "OK", ".claude/rules/playbook-user-memory.md"), "a memory rules link -> OK")
        # ... and the source gone again (no user memory): the link setup made is dangling -> MISSING, not SKIP.
        os.remove(os.path.join(repo, "memory", "MEMORY.md"))
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "MISSING", ".claude/rules/playbook-user-memory.md", "target=")
              and not has(out, "SKIP", ".claude/rules/playbook-user-memory.md"),
              "a dangling memory rules link -> MISSING, not SKIP no-source= (rc=%d)" % rc)
        # The real layout: the repo's memory is a link to the store repo's user/memory, outside the repo.
        repo, home, env = fresh()
        store_mem = os.path.join(os.path.dirname(repo), "stores", "user", "memory")
        os.makedirs(store_mem)
        mklink(store_mem, os.path.join(repo, "memory"), True)
        mklink(os.path.join(repo, "memory", "MEMORY.md"), os.path.join(home, ".claude", "rules", "playbook-user-memory.md"))
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "MISSING", ".claude/rules/playbook-user-memory.md", "target="),
              "a dangling memory rules link through the repo's linked memory folder -> MISSING (rc=%d)" % rc)

        # Co-existence, Claude Code: a file of the user's own at CLAUDE.md plus the rules link verifies OK;
        # without the rules link it fails.
        repo, home, env = fresh()
        claude_md = os.path.join(home, ".claude", "CLAUDE.md")
        os.remove(claude_md)
        _w(claude_md, b"my own instructions\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "NOT_SYMLINK", ".claude/CLAUDE.md", "user-file-kept-without")
              and has(out, "MISSING", ".claude/rules/agent-playbook.md"),
              "a user CLAUDE.md with no rules link -> NOT_SYMLINK and the side link MISSING")
        mklink(os.path.join(repo, "shared", "AGENTS.md"), os.path.join(home, ".claude", "rules", "agent-playbook.md"))
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "OK", ".claude/CLAUDE.md", "user-file-kept")
              and has(out, "OK", ".claude/rules/agent-playbook.md"),
              "a user CLAUDE.md beside the rules link -> OK user-file-kept (rc=%d)" % rc)
        # A file the deploy lock names is setup's, never the user's own (setup's rule, shared).
        _w(os.path.join(home, ".agent-playbook", "deploy-lock.tsv"),
           LOCK_HEADER + "\ncopy-file\t~/.claude/CLAUDE.md\t" + "0" * 64 + "\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "NOT_SYMLINK", ".claude/CLAUDE.md")
              and not has(out, "OK", ".claude/CLAUDE.md", "user-file-kept"),
              "a CLAUDE.md the deploy lock names is not the user's own (rc=%d)" % rc)
        os.remove(os.path.join(home, ".agent-playbook", "deploy-lock.tsv"))
        # A link of the user's own outside the repo (dotfiles) is the user's file too.
        os.remove(claude_md)
        _w(os.path.join(home, "dotfiles", "claude.md"), b"my dotfiles instructions\n")
        mklink(os.path.join(home, "dotfiles", "claude.md"), claude_md)
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "OK", ".claude/CLAUDE.md", "user-file-kept"),
              "a user CLAUDE.md linked from outside the repo -> OK user-file-kept (rc=%d)" % rc)
        # Double load: CLAUDE.md is the playbook link and the rules link is still there -> DRIFTED.
        os.remove(claude_md)
        mklink(os.path.join(repo, "shared", "AGENTS.md"), claude_md)
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "OK", ".claude/CLAUDE.md")
              and has(out, "DRIFTED", ".claude/rules/agent-playbook.md", "leftover-side-link="),
              "CLAUDE.md is the link and the rules link remains -> DRIFTED double load (rc=%d)" % rc)

        # Co-existence, Gemini CLI: the side link and the context.fileName entry are both required.
        repo, home, env = fresh()
        gem = os.path.join(home, ".gemini")
        _w(os.path.join(gem, "GEMINI.md"), b"my gemini\n")
        for s in ("alpha", "beta"):
            mklink(os.path.join(repo, "shared", "skills", s), os.path.join(gem, "skills", s), True)
        mklink(os.path.join(repo, "shared", "AGENTS.md"), os.path.join(gem, "AGENT-PLAYBOOK.md"))
        _w(os.path.join(gem, "settings.json"), b'{"context": {"fileName": "GEMINI.md"}, "keep": 1}\n')
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "MISSING", ".gemini/settings.json", "context.fileName-lacks=")
              and has(out, "NOT_SYMLINK", ".gemini/GEMINI.md", "user-file-kept-without"),
              "a user GEMINI.md with no context.fileName entry -> MISSING settings and NOT_SYMLINK")
        _w(os.path.join(gem, "settings.json"), b'{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}\n')
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "OK", ".gemini/GEMINI.md", "user-file-kept")
              and has(out, "OK", ".gemini/settings.json", "context.fileName"),
              "a user GEMINI.md beside the side link and the settings entry -> OK (rc=%d)" % rc)
        # A settings.json with comments (Gemini CLI accepts JSONC): setup cannot edit it -> MISSING settings.
        _w(os.path.join(gem, "settings.json"),
           b'{\n  // mine\n  "context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}\n}\n')
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "MISSING", ".gemini/settings.json", "context.fileName-lacks=")
              and has(out, "NOT_SYMLINK", ".gemini/GEMINI.md", "user-file-kept-without"),
              "a JSONC settings.json -> MISSING settings and NOT_SYMLINK (rc=%d)" % rc)
        # Double load: GEMINI.md is the playbook link while the side link and the entry remain -> DRIFTED.
        _w(os.path.join(gem, "settings.json"), b'{"context": {"fileName": ["GEMINI.md", "AGENT-PLAYBOOK.md"]}}\n')
        os.remove(os.path.join(gem, "GEMINI.md"))
        mklink(os.path.join(repo, "shared", "AGENTS.md"), os.path.join(gem, "GEMINI.md"))
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "OK", ".gemini/GEMINI.md")
              and has(out, "DRIFTED", ".gemini/AGENT-PLAYBOOK.md", "leftover-side-link=")
              and any(l.startswith("DRIFTED") and "context.fileName-lists=" in l for l in out),
              "GEMINI.md is the link, the side link and the entry remain -> DRIFTED double load (rc=%d)" % rc)
        os.remove(os.path.join(gem, "GEMINI.md"))
        # A byte copy of the source is not the user's own file: it stays NOT_SYMLINK, side link or not.
        _w(os.path.join(gem, "GEMINI.md"), b"agents\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "NOT_SYMLINK", ".gemini/GEMINI.md")
              and not has(out, "NOT_SYMLINK", ".gemini/GEMINI.md", "user-file-kept"),
              "a byte copy of the source at GEMINI.md -> plain NOT_SYMLINK")

        # Coexistence: a skill of the user's own beside the playbook's per-skill links is never reported.
        repo, home, env = fresh()
        _w(os.path.join(home, ".claude", "skills", "my-own-skill", "SKILL.md"), b"# mine\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and not any("my-own-skill" in l for l in out),
              "a user's own skill beside the playbook's links is not reported (rc=%d)" % rc)
        # A folder of the user's own at a playbook skill's name: setup keeps it -> OK user-folder-kept.
        alpha = os.path.join(home, ".claude", "skills", "alpha")
        try:
            os.unlink(alpha)   # the link (POSIX)
        except OSError:
            os.rmdir(alpha)    # a directory link or junction (Windows), never its target
        _w(os.path.join(alpha, "SKILL.md"), b"# my alpha\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and has(out, "OK", ".claude/skills/alpha", "user-folder-kept"),
              "a user folder at a Claude skill's name -> OK user-folder-kept (rc=%d)" % rc)
        # A provider not chosen at setup (`providers=` of the pointer file) is skipped, never checked.
        _w(os.path.join(home, ".agent-playbook", "config"), b"providers=claude,kiro\n")
        rc, out, _ = _st_run(repo, env)
        check(has(out, "SKIP", "home/.codex", "not-selected") and not has(out, "OK", ".codex/AGENTS.md"),
              "a provider not chosen at setup -> SKIP not-selected")
        check(has(out, "OK", ".claude/CLAUDE.md") and has(out, "OK", ".kiro/skills/gamma"),
              "the chosen providers are still checked")

    # AMBIGUOUS_SKILL: both shapes.
    repo, home, env = fresh()
    _w(os.path.join(repo, "providers", "kiro", "skills", "delta", "SKILL.md"), b"# Delta\n")
    _w(os.path.join(repo, "providers", "kiro", "skills", "delta", "OVERLAY.md"), b"delta overlay\n")
    _w(os.path.join(repo, "providers", "kiro", "skills", "eps", "eps.OVERLAY.md"), b"eps overlay\n")
    rc, out, _ = _st_run(repo, env)
    check(rc == 1 and has(out, "AMBIGUOUS_SKILL", "providers/kiro/skills/delta", "SKILL.md and an overlay"),
          "SKILL.md beside an overlay -> AMBIGUOUS_SKILL")
    check(has(out, "AMBIGUOUS_SKILL", "providers/kiro/skills/eps", "overlay with no SKILL.md and no shared/skills/eps"),
          "overlay with no shared skill -> AMBIGUOUS_SKILL")

    # --list
    repo, home, env = fresh()
    rc, out, _ = _st_run(repo, env, ["--list"])
    rows = set(tuple(l.replace("\\", "/").split("\t")[i] for i in (0, 3)) + (l.replace("\\", "/").split("\t")[1]
               .rsplit("/home/", 1)[-1],) for l in out)
    check(rc == 0 and all(len(l.split("\t")) == 4 for l in out), "--list prints 4-column rows and exits 0")
    check(("copy-dir-recursive", "kiro", ".kiro/skills/beta") in rows, "--list: overlay skill is copy-dir-recursive")
    check(("merge-file", "kiro", ".kiro/skills/beta/SKILL.md") in rows and
          ("merge-file", "kiro", ".kiro/skills/beta/aux.md") in rows, "--list: one merge-file row per merged target")
    check(not any(l.split("\t")[0] in STATUSES or l.startswith("SUMMARY") for l in out), "--list runs no checks")
    if links:
        check(("symlink-dir", "codex", ".codex/skills/alpha") in rows and
              ("symlink-dir", "kiro", ".kiro/skills/gamma") in rows, "--list: codex and standalone kiro skill rows")
    check(not any(r[2] == ".kiro/skills/beta" and r[0] == "symlink-dir" for r in rows),
          "--list: an overlay dir is no standalone row")

    # exit 2: no inventory, bad manifest, not a repo, unknown flag, unexpected error.
    repo, home, env = fresh()
    os.remove(os.path.join(repo, "inventory.tsv"))
    rc, out, err = _st_run(repo, env)
    check(rc == 2 and any("manifest not found" in l for l in err), "missing inventory.tsv -> exit 2")
    repo, home, env = fresh()
    _w(os.path.join(repo, "inventory.tsv"), b"copy-file\t~/x\tshared/AGENTS.md\n")
    rc, out, err = _st_run(repo, env)
    check(rc == 2 and any("has 3 columns" in l for l in err), "3-column manifest line -> exit 2")
    _w(os.path.join(repo, "inventory.tsv"), b"weird-kind\t~/x\tshared/AGENTS.md\tclaude\n")
    rc, out, err = _st_run(repo, env)
    check(rc == 2 and any("unknown kind 'weird-kind'" in l for l in err), "unknown kind -> exit 2")
    rc, out, err = _st_run(os.path.join(tmp, "not-a-repo"), env)
    check(rc == 2 and any("cannot resolve agent-playbook repo root" in l for l in err), "not a repo -> exit 2")
    out2, err2 = [], []
    rc = run(["--bogus"], env, out2.append, err2.append)
    check(rc == 2 and err2 == ["%s: unknown flag: --bogus" % NAME], "unknown flag -> exit 2")
    repo, home, env = fresh()
    saved = Verifier.ambiguous_check
    try:
        def boom(self):
            raise RuntimeError("injected")
        Verifier.ambiguous_check = boom
        rc, out, err = _st_run(repo, env)
    finally:
        Verifier.ambiguous_check = saved
    check(rc == 2 and any("unexpected error: RuntimeError: injected" in l for l in err) and
          has(out, "OK", ".kiro/skills/beta/SKILL.md") and not any(l.startswith("SUMMARY") for l in out),
          "an unexpected error exits 2 and keeps the lines already printed")
    out2, err2 = [], []
    rc = run(["--help"], env, out2.append, err2.append)
    check(rc == 0 and out2 and out2[0].startswith("verify-deployment.py --"), "--help prints the header, exit 0")

    # A directory the guard must walk that cannot be listed stops the run (exit 2); it never reads as empty.
    for label, suffix, before in (("source", "shared/skills/beta", ".kiro/AUTHORING.md"),
                                  ("deployed", ".kiro/skills/beta", ".kiro/skills/beta/SKILL.md")):
        repo, home, env = fresh()
        real_list = globals()["_list_entries"]

        def failing(path, _suffix=suffix, _real=real_list):
            if path.replace("\\", "/").rstrip("/").endswith(_suffix):
                raise PermissionError(13, "Permission denied (injected)", path)
            return _real(path)
        globals()["_list_entries"] = failing
        try:
            rc, out, err = _st_run(repo, env)
        finally:
            globals()["_list_entries"] = real_list
        check(rc == 2 and any("guard did not run: cannot list " in l and suffix in l.replace("\\", "/")
                              and "injected" in l for l in err)
              and has(out, "OK", before) and not any(l.startswith("SUMMARY") for l in out),
              "an unlistable %s directory exits 2 'cannot list', keeping the lines printed (rc=%d)" % (label, rc))

    # The resolved home is empty: exit 2 before any cwd-relative path is checked.
    repo, home, env = fresh()
    env = dict((k, v) for k, v in env.items() if k not in ("USERPROFILE", "HOME"))
    env["USERPROFILE" if os.name == "nt" else "HOME"] = ""
    real_profile, real_expand = globals()["_win_known_profile"], os.path.expanduser
    globals()["_win_known_profile"] = lambda: ""
    os.path.expanduser = lambda p: p
    try:
        rc, out, err = _st_run(repo, env)
    finally:
        globals()["_win_known_profile"], os.path.expanduser = real_profile, real_expand
    check(rc == 2 and out == [] and err == ["%s: guard did not run: home directory could not be resolved" % NAME],
          "an empty home -> exit 2 'home directory could not be resolved' (rc=%d, %r)" % (rc, err[:1]))

    if links:
        # A provider top folder that is a dangling symlink is a broken install, not "not installed".
        repo, home, env = fresh()
        os.symlink(os.path.join(home, "no-such-gemini"), os.path.join(home, ".gemini"), target_is_directory=True)
        rc, out, _ = _st_run(repo, env)
        check(rc == 1 and has(out, "MISSING", "home/.gemini", "target=") and not has(out, "SKIP", "home/.gemini"),
              "a dangling provider top-folder symlink -> MISSING target=..., not SKIP (rc=%d)" % rc)

        # A relative symlink target resolves against the link's own folder, never the cwd.
        repo, home, env = fresh()
        for s, target in (("alpha", "alpha"), ("beta", "alpha")):
            at = os.path.join(home, ".codex", "skills", s)
            os.rmdir(at) if os.name == "nt" else os.remove(at)
            os.symlink(os.path.relpath(os.path.join(repo, "shared", "skills", target), os.path.dirname(at)), at,
                       target_is_directory=True)
        rc, out, _ = _st_run(repo, env)
        check(has(out, "OK", ".codex/skills/alpha"), "a correct relative symlink -> OK")
        alpha_src = os.path.join(repo, "shared", "skills", "alpha").replace("\\", "/").lower()
        check(rc == 1 and any(l.startswith("WRONG_TARGET\t") and l.split("\t")[1].replace("\\", "/").endswith(
            ".codex/skills/beta") and l.split("\t")[2].replace("\\", "/").lower() == "target=" + alpha_src
            for l in out), "a relative symlink to the wrong source -> WRONG_TARGET target=<absolute path>")
    else:
        skipped.extend(["dangling provider top", "relative symlink"])
    return fails, checks[0], skipped


def selftest():
    # realpath: on macOS the temp dir is a symlink (/var -> /private/var); targets are compared after realpath
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="verify-deployment-"))
    try:
        links, reason = _symlinks_available(tmp)
        fails, checks, skipped = _st_cases(os.path.join(tmp, "base"), links, reason)
        # Mutations: undo one fix at a time; the cases must catch each, and each is restored exactly.
        def swallow(path):
            try:
                return _list_entries(path)
            except OSError:
                return []

        def old_provider_installed(self, top):
            if _dir_exists(top):
                return True
            self.emit("SKIP", top)
            return False
        g = globals()
        mutations = [
            ("merge recompute returns the bare shared file", g, "_merged_bytes",
             lambda shared, overlay, windows: _read_bytes(shared)),
            ("orphan walk disabled", Verifier, "orphan_walk", lambda self: None),
            ("the ORPHAN owner field ignores the deploy lock", Verifier, "lock_owner", lambda self, full: FOREIGN),
            ("a listing failure reads as an empty directory", g, "_entries", swallow),
            ("a dangling provider top folder reads as not installed", Verifier, "provider_installed",
             old_provider_installed),
            ("a relative symlink target resolves against the cwd", g, "_link_dest", lambda link_path, raw: raw),
            ("an empty home is not rejected", g, "_require_home", lambda home: None),
            ("a user's own instruction file is never accepted", Verifier, "is_user_file",
             lambda self, path, source: False),
            ("co-existence ignores the Gemini settings entry", Verifier, "check_gemini_setting", lambda self: True),
            ("a co-existence link beside the instruction-file link is never reported", Verifier, "check_double_load",
             lambda self, dest, side, gemini: None),
            ("a dangling memory rules link reads as no source", Verifier, "engine_link", lambda self, path: False),
            ("a memory row with no source is checked anyway", Verifier, "check_link_row",
             lambda self, mode: [self.check_symlink(d, src) for _k, d, src in self._mode_rows(mode)]),
        ]
        originals = []
        for i, (label, owner, attr, replacement) in enumerate(mutations):
            original = owner[attr] if owner is g else owner.__dict__[attr]
            originals.append((owner, attr, original))
            if owner is g:
                g[attr] = replacement
            else:
                setattr(owner, attr, replacement)
            try:
                m_fails, _, _ = _st_cases(os.path.join(tmp, "mut%02d" % i), links, reason)
            finally:
                if owner is g:
                    g[attr] = original
                else:
                    setattr(owner, attr, original)
            checks += 1
            print("  mutation (%s): %d case failure(s) -> %s" % (label, len(m_fails),
                                                                 "caught" if m_fails else "NOT CAUGHT"))
            if not m_fails:
                fails.append("mutation not caught: " + label)
        checks += 1
        if any((owner[attr] if owner is g else owner.__dict__[attr]) is not original
               for owner, attr, original in originals):
            fails.append("mutations not restored")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f in fails:
        print("  FAIL: " + f)
    print("verify-deployment selftest: %d failure(s), %d check(s), %d skipped" % (len(fails), checks, len(skipped)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
