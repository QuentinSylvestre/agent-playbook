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
  A template-file also verifies OK when it equals the render setup.sh produces under
  Git Bash (/c/... roots), so a setup.sh deploy on Windows is not reported DRIFTED.
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
                   the manifest does not claim to own.
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
    "ORPHAN, delete the deployed file only after confirming its source was removed deliberately.")

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

    # --- paths ---
    def join(self, base, child):
        if self.win:
            return _winjoin(base, child)
        return base + "/" + child

    def exists(self, p):
        return os.path.exists(p)

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

    def _posix_find_files(self, top, rel=""):
        """find . -name __pycache__ -prune -o -type f -print: relpaths in readdir order."""
        for e in _entries(top if not rel else top + "/" + rel):
            if e.name == "__pycache__":
                continue
            r = e.name if not rel else rel + "/" + e.name
            if e.is_dir(follow_symlinks=False):
                for sub in self._posix_find_files(top, r):
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
                if _ps_link_type(full, st) or re.search(r"[\\/]__pycache__[\\/]", full):
                    continue
                walk.append((full[len(source_full):].lstrip("\\/"), full))
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
            self.check_symlink(self.join(top, "skills/" + skill), self.join(self.shared_skills, skill))

    def check_all(self):
        claude_top = self.join(self.home, ".claude")
        if self.wanted("claude", claude_top):
            for _kind, dest, source in self._mode_rows("claude"):
                self.check_symlink(dest, source)
            self.check_skill_links(claude_top)

        codex_top = self.join(self.home, ".codex")
        if self.wanted("codex", codex_top):
            for _kind, dest, source in self._mode_rows("codex"):
                self.check_symlink(dest, source)
            self.check_skill_links(codex_top)

        gemini_top = self.join(self.home, ".gemini")
        if self.wanted("gemini", gemini_top):
            for kind, dest, source in self._mode_rows("gemini"):
                # The .ps1 checks only the two symlink kinds here; the .sh checks every row.
                if not self.win or kind in (KIND_SYMLINK_FILE, KIND_SYMLINK_DIR):
                    self.check_symlink(dest, source)
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
                    self.check_copy_dir_recursive(dest, src, overlay_dir)
                else:
                    self.check_symlink(dest, src)
            if _dir_exists(self.kiro_provider_skills):
                for skill in self.list_skills(self.kiro_provider_skills):
                    if self.has_any_overlay(self.join(self.kiro_overlay_root, skill)):
                        continue
                    self.check_symlink(self.join(self.kiro_top, "skills/" + skill),
                                       self.join(self.kiro_provider_skills, skill))

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
                    if os.path.exists(candidate) or full.lower() in exp_files:
                        continue
                    self.emit("ORPHAN", full, "expected-source=" + candidate)
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
                    self.emit("ORPHAN", full, "no-source-skill")
            return
        exp_files = set(r[1] for r in rows if r[0] in FILE_KINDS)
        exp_dirs = set(r[1] for r in rows if r[0] in DIR_KINDS)
        for kind, dest, src, _mode in rows:
            if kind != KIND_COPY_DIR_RECURSIVE or not _dir_exists(dest) or os.path.islink(dest):
                continue
            for rel in sorted(self._posix_find_files(dest), key=_c_key):
                deployed = dest + "/" + rel
                if os.path.exists(src + "/" + rel) or deployed in exp_files:
                    continue
                self.emit("ORPHAN", deployed, "expected-source=%s/%s" % (src, rel))
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
                self.emit("ORPHAN", full, "no-source-skill")

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
                    "symlink-file\t~/.codex/AGENTS.md\tshared/AGENTS.md\tcodex"]
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
    os.makedirs(os.path.join(home, ".kiro", "skills", "ghost"))
    os.makedirs(os.path.join(home, ".kiro", "skills", ".tool-managed"))
    rc, out, _ = _st_run(repo, env)
    check(rc == 0, "ORPHAN never fails the run (rc=%d)" % rc)
    check(has(out, "ORPHAN", ".kiro/skills/beta/stale.md", "expected-source="), "stale file in a copy -> ORPHAN")
    check(has(out, "ORPHAN", ".kiro/skills/ghost", "no-source-skill"), "skill dir with no source -> ORPHAN")
    check(not any("__pycache__" in l or ".tool-managed" in l for l in out),
          "bytecode caches and dot entries are not orphans")
    check(sum(1 for l in out if l.startswith("ORPHAN\t")) == 2, "exactly two ORPHAN lines")

    if links:
        # Coexistence: a skill of the user's own beside the playbook's per-skill links is never reported.
        repo, home, env = fresh()
        _w(os.path.join(home, ".claude", "skills", "my-own-skill", "SKILL.md"), b"# mine\n")
        rc, out, _ = _st_run(repo, env)
        check(rc == 0 and not any("my-own-skill" in l for l in out),
              "a user's own skill beside the playbook's links is not reported (rc=%d)" % rc)
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
    tmp = tempfile.mkdtemp(prefix="verify-deployment-")
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
            ("a listing failure reads as an empty directory", g, "_entries", swallow),
            ("a dangling provider top folder reads as not installed", Verifier, "provider_installed",
             old_provider_installed),
            ("a relative symlink target resolves against the cwd", g, "_link_dest", lambda link_path, raw: raw),
            ("an empty home is not rejected", g, "_require_home", lambda home: None),
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
