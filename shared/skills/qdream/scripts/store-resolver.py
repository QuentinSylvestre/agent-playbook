#!/usr/bin/env python3
"""store-resolver.py -- find or create the workspace store for a folder.

One resolver for every playbook script, skill and external consumer. Stdlib only,
Python 3.8+, runs no child process, no network. Library calls never raise: every call
returns a Result that unpacks as (status, path), with status one of

    found    a store exists; path is its directory
    created  find_or_create made the store; path is its directory
    none     no store, and none may be created (reason says why)
    failed   the scan or a read could not complete; never leads to creation

Result also carries .reason (text) and .notice (a near-match notice on creation, or the
note that `at` was ignored).
`path` is the store directory, the folder that holds memory/, plans/, plans/done/,
plans/tests/, explanations/ and artifacts/. `kind` (memory, plans, explanations,
artifacts) selects only what folder_fallback looks for: the config repo has a store like
any workspace (its plans live there too), but its own memory/ is the user tier, so it
is never offered as project memory. The config repo is recognised from the folder's own
git toplevel (it holds shared/AGENTS.md and shared/skills/qdream/scripts/store-resolver.py),
never from where this module file lives, so a copy of the module elsewhere (the Kiro
deploy) behaves the same. Callers append <kind>/ themselves. For identity(), `path` is an Identity, not a path.

Identity of a folder: the normalized git remote plus the folder's path within the
repo, or "local <normalized path>" when there is no usable remote. The store repo
(AGENT_PLAYBOOK_STORES, else ~/.agent-playbook/stores) holds flat directories
named <name>-<hex>, each with a STORE file. The hex part has at least 6 digits; a
collision with a different identity extends it by 2 digits at a time. Resolution
scans STORE files and never derives a directory name to look something up. The
resolver never creates the store repo root and runs no git. A missing store root,
or one without .git, is `failed`; so is a store root on a network (UNC) path.

Remote normalization percent-decodes the path (so %20 becomes a space and %2F a
separator). A decoded path holding a control character (below 0x20, or 0x7f), for
example from %0A, makes the remote unusable: it counts as no remote, like a non-URL
remote, so the identity is "local <folder path>". Invalid byte sequences (%ff, %fe)
decode to U+FFFD, so two such remotes can collide on one identity; that is an
accepted limitation. Creation re-parses the STORE text it is about to write and
returns `failed` (writing nothing) when it would not read back as the same identity.

Comparing identities: identity() and scan_stores() return Identity tuples that
compare unequal under == (they differ in keyname and toplevel, which a STORE file does
not hold). Use same_identity(a, b), which compares kind, value and subpath case-folded
(id_key(i) is that key). Never compare Identity values with ==.

Behaviours worth knowing:
  - find_or_create(folder, at=...) always looks up from `folder`. If a store serves
    it, that store is returned (the notice says `at` was ignored, and `at` is not
    validated at all). A store is created at `at` only when none was found AND `at`
    is the folder or one of its ancestors in the same git toplevel (outside git: in
    the same non-git walk find uses), so a later find(folder) reaches it. Any other
    `at` gives `none`, pointing to the "use a parent's store" steps in
    memory-rules.md § Workspace Store. An empty, non-string or UNC `at` is rejected
    only on this creation path.
  - find runs before the no-create gate, so an existing store under a no-create root
    is returned. find_or_create and would_create_path create nothing there.
  - create() (migration only) bypasses the no-create roots.
  - would_create_path takes no `at`: it previews find_or_create(folder) only. Callers
    must not use it to preview an `at=` creation, which can land in another directory.
    It returns status `created` for a directory that does not exist yet.
  - A UNC path (\\\\server\\share, //server/share, \\\\?\\UNC\\...) returns `none` at once
    without touching the filesystem, so a dead host cannot stall a caller. The same
    guard covers a UNC store root (`failed`) and a UNC `gitdir:` or `commondir` target
    (`failed`). Mapped network drives (Z:\\) are not detected and can still stall. An
    empty or non-string folder is `failed`. Creation needs the folder (and `at`) to be
    an existing directory; find on a missing folder still compares lexically.
  - Repository discovery follows git's own rule. A `.git` directory counts only when it
    passes git's is_git_directory test: a valid HEAD, plus objects/ and refs/ (in the
    commondir target when there is one). One that fails it (for example only objects/, left
    over from a half-deleted repo) is treated as absent, so the walk goes on upward, to an
    enclosing repo or to a `local` identity, exactly as `git rev-parse` does.
  - A `.git` directory that passes that test but has no config file, a gitdir (or
    commondir) that does not exist or is not a git directory (git itself dies on these), a
    WSL-style "gitdir: /mnt/c/..." written by Linux git (Linux and WSL are out of
    scope) and an unreadable config are all `failed`, never creation.
  - An empty STORE is a creation in progress: reads wait up to EMPTY_WAIT_SECONDS if
    the file is younger than EMPTY_ABANDONED_SECONDS, otherwise it is invalid at once.
    An empty STORE with a modification time in the future (clock skew, OneDrive sync)
    is abandoned too: this module publishes a STORE atomically after fsync, so it never
    leaves an empty one.
  - find and resolve_artifact reuse one scan of the store root for up to SCAN_CACHE_SECONDS while the
    root's fingerprint (the .git marker, and the time and size of the root, each store directory and
    each STORE file) is unchanged, so a consumer resolving many folders reads the STORE files once. A
    store created or replaced by any process is seen at once; only a rewrite that keeps a STORE file's
    size and modification time waits for the time-to-live. find_or_create and would_create_path scan
    fresh; create and scan_stores do not use the cache. The CLI's find and resolve use it
    like any caller, but the cache lives in the process, so one CLI call per process never hits it. A
    failed scan is never cached.
  - A successful 8.3/case expansion of a path (the GetLongPathNameW call behind every comparison key) is
    remembered for EXPAND_CACHE_SECONDS in the process, keyed by the exact input string, so a caller that
    resolves many folders does not repeat the slow call for the same home, temp and workspace paths. A
    failed expansion is never remembered. A folder renamed within that window (a case change, a new 8.3
    alias) is seen once it passes.
  - PermissionError / sharing-violation reads are retried 3 times at 50 ms. A scan
    stops at its first failed entry, so a store repo that cannot be read at all costs
    one entry's retries, not one per store.
  - A leftover STORE.tmp-* file (a temp file that could not be deleted after publish)
    is never read as a store: resolution reads only <dir>/STORE. Stale ones are
    deleted when creation (or create()) targets the directory. The store repo's
    .gitignore should list STORE.tmp-*.

Reading an artifact class: find, find_or_create and would_create_path name a store whether or not it
holds content. A consumer that READS an artifact class calls resolve_artifact(folder, kind),
which returns an Artifact (source, path) -- source store-repo, in-workspace (only the config repo's own
plans/), none or failed -- and reads, per level from the folder up to the repo toplevel, the first store
that holds content for the kind. It never raises and skips an unreadable store repo (reason says so). The
CLI `resolve` prints `<source>\t<path>`: exit 0 found, 3 none (reason on stderr), 2 failed or a missing or
unreadable store repo (nothing printed on stdout).

CLI: store-resolver.py {find,find-or-create,would-create,identity,list,resolve} ...
     store-resolver.py --selftest
Prints the path (identity: the STORE lines). For none it prints nothing on stdout,
the reason as one line on stderr, and exits 3. For failed, an unexpected error or
could not run it exits 2 (the reason on stderr).
"""
from __future__ import annotations

import argparse
import collections
import functools
import hashlib
import os
import re
import stat
import sys
import threading
import time
import urllib.parse
from pathlib import Path

STORE_FILE = "STORE"
KINDS = ("memory", "plans", "explanations", "artifacts")
# Reserved top-level directory of the store repo holding user-tier state (user/memory/); never a store.
USER_DIR = "user"
STATUSES = ("found", "created", "none", "failed")

# How long find waits for an empty (creation in progress) STORE before treating it as invalid,
# and the age after which an empty STORE is abandoned and is invalid at once (no wait).
EMPTY_WAIT_SECONDS = 2.0
EMPTY_ABANDONED_SECONDS = 5.0

# Transient read errors (PermissionError, sharing violation): retries and the pause between them.
READ_RETRIES = 3
READ_RETRY_SECONDS = 0.05

# A leftover STORE.tmp-* file older than this is deleted when a store directory is created.
STALE_TMP_SECONDS = 60.0

MISSING_ROOT = "store repo missing \u2014 clone it (see providers/claude/README.md)"

# Test overrides (selftest only): home, temp (list), downloads (list), config_repo (a path, or "" to disable).
_TEST: dict = {}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class Result(tuple):
    """(status, path) with .reason and .notice attributes."""

    def __new__(cls, status, path=None, reason="", notice=""):
        self = tuple.__new__(cls, (status, path))
        self.reason = reason
        self.notice = notice
        return self

    @property
    def status(self):
        return self[0]

    @property
    def path(self):
        return self[1]

    def __repr__(self):
        return "Result(%r, %r, reason=%r)" % (self[0], self[1], self.reason)


Identity = collections.namedtuple("Identity", "kind value subpath keyname toplevel")


def id_line(i) -> str:
    return "%s %s" % (i.kind, i.value)


def id_sub_line(i) -> str:
    return ("path " + i.subpath.casefold()) if i.subpath else ""


def id_key(i):
    """The comparison key of an Identity: (kind, value, subpath), case-folded."""
    return (i.kind, i.value.casefold(), i.subpath.casefold())


def same_identity(a, b) -> bool:
    """True when two Identity values name the same store key. Never compare Identity with ==."""
    if a is None or b is None:
        return False
    return id_key(a) == id_key(b)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # library calls never raise
            return Result("failed", None, reason="internal error: %s: %s" % (type(exc).__name__, exc))
    return wrapper


# ---------------------------------------------------------------------------
# Path normalization (memory-rules.md § Path normalization)
# ---------------------------------------------------------------------------

_LONG_FN = None


def _long_fn():
    global _LONG_FN
    if _LONG_FN is None:
        _LONG_FN = False
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                fn = ctypes.WinDLL("kernel32", use_last_error=True).GetLongPathNameW
                fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
                fn.restype = wintypes.DWORD
                _LONG_FN = (fn, ctypes)
            except Exception:
                _LONG_FN = False
    return _LONG_FN


def _expand_raw(p: str):
    """One GetLongPathNameW call: the expanded path, or None when it fails (a missing path, no Windows API)."""
    lf = _long_fn()
    if not lf:
        return None
    fn, ctypes = lf
    size = 1024
    for _ in range(2):
        buf = ctypes.create_unicode_buffer(size)
        n = fn(p, buf, size)
        if n == 0:
            return None
        if n < size:
            return buf.value
        size = n + 1
    return None


# A successful expansion is remembered for EXPAND_CACHE_SECONDS, per process, keyed by the exact input
# string. One GetLongPathNameW call costs ~2.7 ms on a OneDrive-redirected tree, and one resolution makes
# ~20 of them for a handful of distinct paths (the home folder, the temp folders, each workspace
# path), so a caller resolving many folders paid seconds. A failed expansion (None) is never stored: a
# path that does not exist yet may be created a moment later, and a stored failure would read as "this
# path cannot be expanded". What a stored success can get wrong is a folder renamed (a case change, a new
# 8.3 alias) within the window; it is seen after it.
EXPAND_CACHE_SECONDS = 10.0
_EXPAND_CACHE_MAX = 512
_EXPAND_CACHE = {}  # exact input path -> (monotonic time the call started, expansion)
_EXPAND_LOCK = threading.Lock()


def _invalidate_expand_cache():
    with _EXPAND_LOCK:
        _EXPAND_CACHE.clear()


def _expand_exact(p: str):
    ttl = EXPAND_CACHE_SECONDS
    if ttl <= 0:
        return _expand_raw(p)
    started = time.monotonic()
    with _EXPAND_LOCK:
        hit = _EXPAND_CACHE.get(p)
    if hit is not None and started - hit[0] < ttl:
        return hit[1]
    got = _expand_raw(p)
    if got is not None:
        with _EXPAND_LOCK:
            if len(_EXPAND_CACHE) >= _EXPAND_CACHE_MAX and p not in _EXPAND_CACHE:
                for key in [k for k, (at, _v) in _EXPAND_CACHE.items() if started - at >= ttl]:
                    del _EXPAND_CACHE[key]
                if len(_EXPAND_CACHE) >= _EXPAND_CACHE_MAX:
                    _EXPAND_CACHE.clear()
            _EXPAND_CACHE[p] = (started, got)
    return got



def _long(p: str) -> str:
    """Step 1: expand 8.3 short names and casing. Links are not followed.

    Non-existent tails are kept lexically; the longest existing ancestor is expanded.
    """
    if os.name != "nt":
        return p
    cur, tail = p, []
    while True:
        got = _expand_exact(cur)
        if got is not None:
            out = got
            for part in reversed(tail):
                out = os.path.join(out, part)
            return out
        par = os.path.dirname(cur)
        if not par or par == cur:
            return p
        tail.append(os.path.basename(cur))
        cur = par


def _verbatim(p) -> str:
    """Absolute, 8.3-expanded path with the extended-length prefix removed; case kept."""
    s = os.fspath(p)
    if s[:4] in ("\\\\.\\", "//./"):
        # the \\.\ device prefix names the same path as \\?\; without this it would dodge every root check
        s = ("\\\\" + s[8:]) if s[4:8].upper() == "UNC\\" else s[4:]
    s = os.path.abspath(s)
    s = _long(s)
    if s.startswith("\\\\?\\UNC\\"):
        s = "\\\\" + s[8:]
    elif s.startswith("\\\\?\\"):
        s = s[4:]
    return s


def _cmp(s: str) -> str:
    """Steps 2-4: strip \\\\?\\ (and \\\\.\\), use '/', drop a trailing separator (keep roots), case-fold."""
    if s[:4] in ("\\\\?\\", "\\\\.\\") and s[4:8].upper() == "UNC\\":
        s = "//" + s[8:]
    elif s[:4] in ("\\\\?\\", "\\\\.\\"):
        s = s[4:]
    s = s.replace("\\", "/")
    if s != "/" and not re.match(r"^[A-Za-z]:/$", s):
        s = s.rstrip("/") or "/"
    return s.casefold()


def _norm_path(p) -> str:
    return _cmp(_verbatim(p))


def _is_drive_root(c: str) -> bool:
    return c == "/" or bool(re.match(r"^[a-z]:/$", c)) or bool(re.match(r"^//[^/]+/[^/]+$", c))


def _under(c: str, root: str) -> bool:
    if c == root:
        return True
    return c.startswith(root if root.endswith("/") else root + "/")


# ---------------------------------------------------------------------------
# Machine-derived values (all overridable for tests)
# ---------------------------------------------------------------------------

def _home_verbatim() -> str:
    h = _TEST.get("home")
    return _verbatim(h if h is not None else os.path.expanduser("~"))


def _home_cmp() -> str:
    return _cmp(_home_verbatim())


_KNOWN_DOWNLOADS = None


def _known_downloads():
    """Windows Downloads known folder (may be redirected, e.g. into OneDrive); None on failure."""
    global _KNOWN_DOWNLOADS
    if _KNOWN_DOWNLOADS is not None:
        return _KNOWN_DOWNLOADS or None
    _KNOWN_DOWNLOADS = ""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        guid = GUID(0x374DE290, 0x123F, 0x4565,
                    (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        shell32 = ctypes.WinDLL("shell32")
        fn = shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                       ctypes.POINTER(ctypes.c_void_p)]
        fn.restype = ctypes.c_long
        ptr = ctypes.c_void_p()
        if fn(ctypes.byref(guid), 0, None, ctypes.byref(ptr)) != 0 or not ptr.value:
            return None
        try:
            val = ctypes.wstring_at(ptr.value)
        finally:
            ole32 = ctypes.WinDLL("ole32")
            ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole32.CoTaskMemFree(ptr)
        _KNOWN_DOWNLOADS = val
        return val or None
    except Exception:
        return None


def _temp_dirs() -> list:
    if "temp" in _TEST:
        raw = list(_TEST["temp"] or [])
    else:
        import tempfile
        raw = [tempfile.gettempdir()]
        for var in ("TEMP", "TMP", "TMPDIR"):
            v = os.environ.get(var)
            if v:
                raw.append(v)
        if os.name != "nt":
            raw += ["/tmp", "/var/tmp"]
    out = []
    for r in raw:
        try:
            c = _norm_path(r)
        except Exception:
            continue
        if c not in out:
            out.append(c)
    return out


def _downloads_dirs() -> list:
    if "downloads" in _TEST:
        raw = list(_TEST["downloads"] or [])
    else:
        raw = [os.path.join(_home_verbatim(), "Downloads")]
        kd = _known_downloads()
        if kd:
            raw.append(kd)
    out = []
    for r in raw:
        try:
            c = _norm_path(r)
        except Exception:
            continue
        if c not in out:
            out.append(c)
    return out


CONFIG_KEYS = ("root", "stores", "stores_url", "engine_branch", "providers")


def _config_path() -> str:
    """The pointer file setup writes: AGENT_PLAYBOOK_CONFIG, else ~/.agent-playbook/config."""
    env = os.environ.get("AGENT_PLAYBOOK_CONFIG")
    return env if env else os.path.join(_home_verbatim(), ".agent-playbook", "config")


def read_config():
    """({key: value}, [problem lines]) from the pointer file; ({}, []) when it is absent. Never raises.

    Format: one `key=value` per line, `#` comments and blank lines ignored, keys from CONFIG_KEYS.
    A malformed or unknown line is reported, never silently used: callers print the problems.
    """
    if "config" in _TEST:
        return dict(_TEST["config"]), []
    path = _config_path()
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return {}, []
    except OSError as exc:
        return {}, ["cannot read %s: %s" % (path, exc)]
    out, problems = {}, []
    for n, line in enumerate(lines, 1):
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        k, sep, v = t.partition("=")
        k, v = k.strip(), v.strip()
        if not sep or k not in CONFIG_KEYS or not v:
            problems.append("%s:%d: ignored malformed line (expected one of %s=<value>)"
                            % (path, n, "/".join(CONFIG_KEYS)))
            continue
        out[k] = v
    return out, problems


def _config_value(key: str) -> str:
    cfg, problems = read_config()
    for p in problems:
        print("store-resolver: " + p, file=sys.stderr)
    return cfg.get(key, "")


def _as_root(raw: str) -> Path:
    if _is_unc(raw):
        return Path(raw)  # never normalized: _verbatim would touch the network path
    return Path(_verbatim(os.path.expanduser(raw)))


def _stores_root() -> Path:
    """AGENT_PLAYBOOK_STORES, else the pointer file's stores=, else ~/.agent-playbook/stores."""
    env = os.environ.get("AGENT_PLAYBOOK_STORES") or _config_value("stores")
    if env:
        return _as_root(env)
    return Path(os.path.join(_home_verbatim(), ".agent-playbook", "stores"))


def playbook_root() -> Path:
    """The engine (config repo) root: AGENT_PLAYBOOK_ROOT, else the pointer file's root=, else the
    repo this module sits in (found by walking up from its real path to a folder holding
    inventory.tsv and shared/AGENTS.md). A Kiro-deployed copy has no such ancestor and needs the
    pointer file. Never raises; returns None when nothing decides it."""
    raw = os.environ.get("AGENT_PLAYBOOK_ROOT") or _config_value("root")
    if raw:
        return _as_root(raw)
    d = Path(os.path.realpath(__file__)).parent
    for cand in [d] + list(d.parents):
        if (cand / "inventory.tsv").is_file() and (cand / "shared" / "AGENTS.md").is_file():
            return cand
    return None


def user_memory_dir() -> Path:
    """Where user memory lives: <store repo>/user/memory (the engine's `memory` link points here)."""
    return _stores_root() / USER_DIR / "memory"


def config_path() -> str:
    """The pointer file's path (AGENT_PLAYBOOK_CONFIG, else ~/.agent-playbook/config); nothing is read."""
    return _config_path()


def engine_branch() -> str:
    """The branch engine commits land on (pointer file engine_branch=, default local-improvements)."""
    return _config_value("engine_branch") or "local-improvements"


def _agent_playbook_cmp() -> str:
    return _cmp(os.path.join(_home_verbatim(), ".agent-playbook"))


def _is_config_repo(top):
    """(is_config_repo, error) for the git toplevel `top` (decided from the folder, not from this file).

    A marker that is missing means "not the config repo"; any other OSError is an error (the caller
    returns `failed`, so a transient fault cannot silently offer the user tier as project memory).
    """
    if "config_repo" in _TEST:
        v = _TEST["config_repo"]
        return (bool(v) and _cmp(top) == _cmp(_verbatim(v))), ""
    for rel in (("shared", "AGENTS.md"), ("shared", "skills", "qdream", "scripts", "store-resolver.py")):
        p = os.path.join(top, *rel)
        try:
            st = os.stat(p)
        except (FileNotFoundError, NotADirectoryError):
            return False, ""
        except OSError as exc:
            return False, "cannot probe %s: %s" % (p, exc)
        if not stat.S_ISREG(st.st_mode):
            return False, ""
    return True, ""


def _exact_stop_set() -> set:
    s = {_home_cmp(), _agent_playbook_cmp(), _cmp(str(_stores_root()))}
    s.update(_temp_dirs())
    s.update(_downloads_dirs())
    return s


def _no_create_reason(c: str) -> str:
    """Label of the no-create root the normalized path `c` is at or under, else ''."""
    if _is_drive_root(c):
        return "a drive root"
    if c == _home_cmp():
        return "the home folder"
    for t in _temp_dirs():
        if _under(c, t):
            return "the system temp directory"
    if _under(c, _agent_playbook_cmp()) or _under(c, _cmp(str(_stores_root()))):
        return "~/.agent-playbook"
    for d in _downloads_dirs():
        if _under(c, d):
            return "a Downloads folder"
    parts = c.split("/")
    for i in range(len(parts) - 1):
        if parts[i] == ".claude" and parts[i + 1] == "worktrees":
            return ".claude/worktrees"
    return ""


# ---------------------------------------------------------------------------
# Remote normalization and git config reading
# ---------------------------------------------------------------------------

_SSH_SCHEMES = ("ssh", "git+ssh", "ssh+git", "git")
_DEFAULT_PORTS = ("80", "443", "9418")


def _normalize_remote(url):
    """Normalize a remote URL to host/path, or None when it is not a URL (counts as no remote)."""
    s = (url or "").strip()
    if not s:
        return None
    port = ""
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", s)
    if m:
        scheme = m.group(1).lower()
        if scheme == "file":
            return None
        rest = m.group(2)
        auth, sep, path = rest.partition("/")
        at = rest.rfind("@")
        if at > 0 and "/" in rest[:at] and ":" in rest[:rest.index("/")]:
            # an unencoded "/" or "@" inside a password (RFC 3986 forbids both): the userinfo runs to the last
            # "@" that is followed by a host name and a path, so no part of the password reaches the identity
            after = rest[at + 1:]
            if "/" in after and re.match(r"^(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:\d+)?$", after.split("/", 1)[0]):
                auth, sep, path = after.partition("/")
        if not sep:
            return None
        hostport = auth.rsplit("@", 1)[-1]
        if re.search(r"[?#]", hostport):
            return None  # a query or fragment before any path: no repository is named
        hm = re.match(r"^(.*?)(?::(\d+))?$", hostport)
        host, port = hm.group(1), hm.group(2) or ""
        if scheme in _SSH_SCHEMES:
            port = ""
        elif port in _DEFAULT_PORTS:
            port = ""
    else:
        if re.match(r"^[A-Za-z]:([\\/]|$)", s) or s[0] in "/.\\~":
            return None
        sm = re.match(r"^(?:[^@/\\\s]+@)?([^:/\\\s]+):(.*)$", s)
        if not sm or len(sm.group(1)) == 1:
            return None
        host, path = sm.group(1), sm.group(2)
    host = host.lower()
    # A query string or fragment is no part of the repository (a token passed as ?access_token=... must
    # never reach a STORE file or a state key); it is dropped before and after percent-decoding.
    path = re.split(r"[?#]", path, maxsplit=1)[0]
    path = re.sub(r"/+", "/", urllib.parse.unquote(path).lower())  # %20 and the like (Azure project names)
    path = re.split(r"[?#]", path, maxsplit=1)[0]
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in host + path):
        return None  # a control character (%0A, %00, ...) cannot live in a one-line STORE: no usable remote
    if host == "ssh.github.com":
        host = "github.com"
    if host == "ssh.dev.azure.com":
        host = "dev.azure.com"
        if path.startswith("v3/"):
            path = path[3:]
    if host == "dev.azure.com":
        path = "/".join(seg for seg in path.split("/") if seg != "_git")
    path = path.strip("/")
    if path.endswith(".git"):  # GIT-SUFFIX-STRIP
        path = path[:-4]
    path = path.strip("/")
    if not host or not path:
        return None
    return "%s%s/%s" % (host, (":" + port) if port else "", path)


def normalize_remote(url):
    """The normalized `host/path` of a remote URL, as a `remote` STORE line holds it; None when `url` is not
    a usable remote (a local path, file://, a control character). Never raises."""
    try:
        return _normalize_remote(url)
    except Exception:
        return None


def _cfg_value(raw: str) -> str:
    esc = {"n": "\n", "t": "\t", "b": "\b", "\\": "\\", '"': '"'}
    out, inq, i, raw = [], False, 0, raw.strip()
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw) and raw[i + 1] in esc:
            out.append(esc[raw[i + 1]])
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif not inq and c in "#;":
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


_SECTION_RE = re.compile(r'^\[\s*([^\s\]"]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\](.*)$')
_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*(?:=\s*(.*))?$")


def _parse_git_config(text: str):
    """Return (remotes {name: [urls]}, instead_of [(base, prefix)]). Includes are not followed."""
    lines, pending = [], ""
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = pending + raw
        pending = ""
        if line.endswith("\\") and not line.endswith("\\\\"):
            pending = line[:-1]
            continue
        lines.append(line)
    remotes, inst = collections.OrderedDict(), []
    sec = sub = None
    for line in lines:
        st = line.strip()
        if not st or st[0] in "#;":
            continue
        sm = _SECTION_RE.match(st)
        if sm:
            sec = sm.group(1).lower()
            sub = re.sub(r"\\(.)", r"\1", sm.group(2)) if sm.group(2) is not None else None
            st = sm.group(3).strip()
            if not st or st[0] in "#;":
                continue
        km = _KEY_RE.match(st)
        if not km or sec is None:
            continue
        key = km.group(1).lower()
        val = _cfg_value(km.group(2)) if km.group(2) is not None else ""
        if sec == "remote" and sub is not None:
            remotes.setdefault(sub, [])
            if key == "url" and val:
                remotes[sub].append(val)
        elif sec == "url" and sub is not None and key == "insteadof" and val:
            inst.append((sub, val))
    return remotes, inst


def _pick_remote_url(remotes):
    if remotes.get("origin"):
        return remotes["origin"][-1]
    having = [n for n, urls in remotes.items() if urls]
    if len(having) == 1:
        return remotes[having[0]][-1]
    return None


def _apply_instead_of(url: str, inst) -> str:
    best = None
    for base, prefix in inst:
        if url.startswith(prefix) and (best is None or len(prefix) > len(best[1])):
            best = (base, prefix)
    return best[0] + url[len(best[1]):] if best else url


def _read_bytes(path: str) -> bytes:
    """Read a file; retry a PermissionError or sharing violation READ_RETRIES times (not for a directory)."""
    attempt = 0
    while True:
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as exc:
            transient = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (32, 33)
            if not transient or attempt >= READ_RETRIES or os.path.isdir(path):
                raise
            attempt += 1
            time.sleep(READ_RETRY_SECONDS)


def _read_text(path: str) -> str:
    return _read_bytes(path).decode("utf-8-sig", "replace")


def _stat_kind(path: str):
    """'dir', 'file', 'link' or None when the path is absent. Any other OSError propagates (never read as absent)."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISLNK(st.st_mode):
        return "link"
    return "dir" if stat.S_ISDIR(st.st_mode) else "file"


def _head_ok(gitdir: str) -> bool:
    """git's validate_headref: HEAD is a symlink into refs/, "ref: refs/...", or a full hex object id."""
    head = os.path.join(gitdir, "HEAD")
    kind = _stat_kind(head)
    if kind == "link":
        return os.readlink(head).startswith("refs/")
    if kind != "file":
        return False
    text = _read_bytes(head)[:512].decode("utf-8", "replace").strip()
    if text.startswith("ref:"):
        return text[4:].lstrip().startswith("refs/")
    return bool(re.match(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?:\s|$)", text))


def _common_dir(gitdir: str) -> str:
    """The directory holding objects/, refs/ and config: gitdir itself, or what its commondir file names."""
    cd = os.path.join(gitdir, "commondir")
    if _stat_kind(cd) == "file":
        return os.path.normpath(os.path.join(gitdir, _read_text(cd).strip()))
    return gitdir


def _is_git_dir(gitdir: str, common: str) -> bool:
    """git's is_git_directory: a valid HEAD in gitdir, and objects/ and refs/ directories in the common dir.

    Git discovery treats a `.git` directory that fails this as absent and keeps walking upward.
    """
    if not _head_ok(gitdir):
        return False
    return _stat_kind(os.path.join(common, "objects")) == "dir" and _stat_kind(os.path.join(common, "refs")) == "dir"


def _git_remote_identity(top: str):
    """(status, remote identity or None, reason). Reads only <common>/config."""
    g = os.path.join(top, ".git")
    try:
        if os.path.isdir(g):
            gitdir = g
        else:
            first = _read_text(g).split("\n", 1)[0]
            gm = re.match(r"^\s*gitdir:\s*(.+?)\s*$", first)
            if not gm:
                return ("failed", None, "malformed .git file at %s" % g)
            gitdir = os.path.normpath(os.path.join(top, gm.group(1)))
            if _is_unc(gitdir):
                return ("failed", None, "gitdir %s named by %s is on a network path; not supported" % (gitdir, g))
            if not os.path.isdir(gitdir):
                return ("failed", None, "gitdir %s named by %s does not exist" % (gitdir, g))
        common = _common_dir(gitdir)
        if common != gitdir and _is_unc(common):
            return ("failed", None, "commondir %s named by %s is on a network path; not supported"
                    % (common, os.path.join(gitdir, "commondir")))
        if not _is_git_dir(gitdir, common):
            # Git's own answer for a .git file whose target is not a git directory is a fatal "not a git repository".
            # (A .git directory in this state never gets here: _probe_git treats it as absent.)
            return ("failed", None, "%s is not a git directory (git needs HEAD, objects/ and refs/): cannot tell its remote" % gitdir)
        cfg = os.path.join(common, "config")
        if os.path.isdir(cfg):
            return ("failed", None, "cannot read %s: it is a directory" % cfg)
        try:
            text = _read_text(cfg)
        except (FileNotFoundError, NotADirectoryError):
            return ("failed", None, "no config file in %s: not a usable git directory" % common)
        except OSError as exc:
            return ("failed", None, "cannot read %s: %s" % (cfg, exc))
        remotes, inst = _parse_git_config(text)
        url = _pick_remote_url(remotes)
        if not url:
            return ("ok", None, "")
        return ("ok", _normalize_remote(_apply_instead_of(url, inst)), "")
    except OSError as exc:
        return ("failed", None, "cannot read git metadata at %s: %s" % (top, exc))


# ---------------------------------------------------------------------------
# Locating a folder: git toplevel, per-level identities
# ---------------------------------------------------------------------------

# levels: Identity per folder from the session folder up; paths: the matching normalized paths.
_Loc = collections.namedtuple("_Loc", "status reason levels toplevel cmp paths")


def _probe_git(level: str):
    """'dir' or 'file' when `level` is a git repository root by git's own discovery rule, else None.

    A `.git` directory counts only when it passes git's is_git_directory (HEAD, objects/, refs/);
    otherwise it is treated as absent and the walk continues upward, as `git rev-parse` does.
    A `.git` directory that passes but has no config stays a repository here (_git_remote_identity
    then reports `failed`). A `.git` file is always a repository root: git treats a bad one as fatal.
    """
    g = os.path.join(level, ".git")
    try:
        st = os.lstat(g)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not stat.S_ISDIR(st.st_mode):
        return "file"
    common = _common_dir(g)
    if common != g and _is_unc(common):
        return "dir"  # never touched; _git_remote_identity reports the network path as failed
    return "dir" if _is_git_dir(g, common) else None


def _chain(verb: str) -> list:
    out = [verb]
    while True:
        par = os.path.dirname(out[-1])
        if not par or par == out[-1]:
            return out
        out.append(par)


def _keyname(level: str) -> str:
    return os.path.basename(level.rstrip("\\/"))


def _locate(folder) -> "_Loc":
    verb = _verbatim(folder)
    chain = _chain(verb)
    here = _cmp(verb)
    top = None
    for i, lvl in enumerate(chain):
        try:
            if _probe_git(lvl):
                top = i
                break
        except OSError as exc:
            return _Loc("failed", "cannot probe %s: %s" % (lvl, exc), [], None, here, [])
    if top is not None:
        st, rid, why = _git_remote_identity(chain[top])
        if st != "ok":
            return _Loc("failed", why, [], chain[top], here, [])
        levels = []
        for lvl in chain[:top + 1]:
            if rid:
                sub = lvl[len(chain[top]):].replace("\\", "/").strip("/")
                levels.append(Identity("remote", rid, sub, _keyname(lvl), chain[top]))
            else:
                levels.append(Identity("local", _cmp(lvl), "", _keyname(lvl), chain[top]))
        return _Loc("ok", "", levels, chain[top], here, [_cmp(lvl) for lvl in chain[:top + 1]])
    stops = _exact_stop_set()
    levels, paths = [], []
    for j, lvl in enumerate(chain):
        c = _cmp(lvl)
        if j > 0 and (c in stops or _is_drive_root(c) or c.endswith("/.claude/worktrees")):
            break
        levels.append(Identity("local", c, "", _keyname(lvl), None))
        paths.append(c)
    return _Loc("ok", "", levels, None, here, paths)


def _is_unc(s: str) -> bool:
    """A Windows network (UNC) path, in its two-slash or extended-length form. Never touched: a dead host stalls."""
    if os.name != "nt":
        return False
    t = s.replace("/", "\\")
    if t[:8].upper() in ("\\\\?\\UNC\\", "\\\\.\\UNC\\"):
        return True
    if t.startswith(("\\\\?\\", "\\\\.\\")):
        return False
    return t.startswith("\\\\")


def _arg(folder, what="folder"):
    """(str, None) for a usable path argument, else (None, the early Result): failed for a bad value, none for UNC."""
    try:
        if isinstance(folder, os.PathLike):
            folder = os.fspath(folder)
    except Exception:
        pass
    if not isinstance(folder, str):
        return None, Result("failed", None, reason="%s must be a path string, got %s" % (what, type(folder).__name__))
    if not folder.strip():
        return None, Result("failed", None, reason="%s is empty" % what)
    if "\x00" in folder:
        return None, Result("failed", None, reason="%s contains a NUL character" % what)
    if _is_unc(folder):
        return None, Result("none", None, reason="%s is a network (UNC) path; not resolved (no store is looked up or created there)" % what)
    return folder, None


def _dir_check(folder: str, what="folder"):
    """None when `folder` is an existing directory, else the Result (none or failed) to return."""
    try:
        st = os.stat(_verbatim(folder))
    except (FileNotFoundError, NotADirectoryError) as exc:
        why = "does not exist" if isinstance(exc, FileNotFoundError) else "is not a directory (a path component is a file)"
        return Result("none", None, reason="%s %s: no store is created" % (what, why))
    except OSError as exc:
        return Result("failed", None, reason="cannot stat %s %s: %s" % (what, folder, exc))
    if not stat.S_ISDIR(st.st_mode):
        return Result("none", None, reason="%s is not a directory: no store is created" % what)
    return None


# ---------------------------------------------------------------------------
# STORE files and the store repo
# ---------------------------------------------------------------------------

def _parse_store_text(text: str):
    """(Identity, '') for a valid STORE, else (None, reason)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1].strip() == "":
        lines.pop()
    if not lines or len(lines) > 2:
        return None, "STORE must have one or two lines"
    m = re.match(r"^(remote|local) (\S.*)$", lines[0].rstrip())
    if not m:
        return None, "line 1 must be 'remote <host/path>' or 'local <path>'"
    sub = ""
    if len(lines) == 2:
        pm = re.match(r"^path (\S.*)$", lines[1].rstrip())
        if not pm or m.group(1) != "remote":
            return None, "line 2 must be 'path <subpath>' and only follows a remote line"
        sub = pm.group(1)
    return Identity(m.group(1), m.group(2).rstrip(), sub, None, None), ""


def _read_store(d):
    """(state, Identity|None, reason); state in ok, missing, invalid, failed. Waits for an empty STORE."""
    p = os.path.join(str(d), STORE_FILE)
    deadline = None
    while True:
        try:
            raw = _read_bytes(p)
        except (FileNotFoundError, NotADirectoryError):
            return ("missing", None, "no STORE file")
        except OSError as exc:
            return ("failed", None, "cannot read %s: %s" % (p, exc))
        text = raw.decode("utf-8-sig", "replace")
        if text.strip() == "":
            try:
                age = time.time() - os.stat(p).st_mtime
            except OSError:
                age = 0.0
            if age < 0:
                # A future mtime (clock skew, OneDrive sync). This module's publish is atomic after fsync,
                # so it never leaves an empty STORE: treat it as abandoned instead of waiting on every scan.
                return ("invalid", None, "empty STORE with a modification time in the future — abandoned creation")
            if age > EMPTY_ABANDONED_SECONDS:
                return ("invalid", None, "empty STORE older than %d s — abandoned creation" % int(EMPTY_ABANDONED_SECONDS))
            now = time.monotonic()
            if deadline is None:
                deadline = now + EMPTY_WAIT_SECONDS
            if now >= deadline:
                return ("invalid", None, "empty STORE (creation in progress or abandoned)")
            time.sleep(0.05)
            continue
        ident, why = _parse_store_text(text)
        if ident is None:
            return ("invalid", None, why)
        return ("ok", ident, "")


def _check_root(root):
    if _is_unc(str(root)):
        return "store repo on a network path is not supported: %s" % root
    if not os.path.isdir(str(root)) or not os.path.lexists(os.path.join(str(root), ".git")):
        return "%s: %s" % (MISSING_ROOT, root)
    return ""


def scan_stores(root=None):
    """(status, valid [(dir, Identity)], invalid [(dir, reason)], reason). Read-only."""
    root = Path(root) if root else _stores_root()
    why = _check_root(root)
    if why:
        return ("failed", [], [], why)
    try:
        names = sorted(os.listdir(str(root)))
    except OSError as exc:
        return ("failed", [], [], "cannot list %s: %s" % (root, exc))
    valid, invalid, fail = [], [], ""
    for name in names:
        d = root / name
        if name.startswith(".") or name == USER_DIR:
            continue    # user/ holds user-tier memory, never a store
        try:
            is_dir = stat.S_ISDIR(os.stat(str(d)).st_mode)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            fail = "cannot stat %s: %s" % (d, exc)
            break  # the scan is failed whatever the rest holds; do not pay retries for every other store
        if not is_dir:
            continue
        st, ident, why = _read_store(d)
        if st == "ok":
            valid.append((d, ident))
        elif st == "failed":
            fail = why
            break
        else:
            invalid.append((d, why))
    if fail:
        return ("failed", valid, invalid, fail)
    return ("ok", valid, invalid, "")


# A short-lived cache of one store root's scan, for the two hot readers (find, resolve_artifact): a consumer
# such as PowerAtlas resolves dozens of folders a second and every call used to rescan every STORE file
# (plan 261016 Phase 7 review: 0.33 s for 70 folders against 1 store, 2.8 s against 300). scan_stores itself
# stays uncached, and so do find_or_create, would_create_path and the CLI.
# A cached answer is reused only while ALL of these hold: it is under SCAN_CACHE_SECONDS old, it was a
# successful scan, and the root's fingerprint is unchanged (.git present, the root's and every store
# directory's modification time and size, and every STORE file's modification time and size). A
# store created or replaced by any process changes the fingerprint; an edit that keeps the STORE file's
# size and modification time is seen once the time-to-live passes. A failed scan is never cached.
SCAN_CACHE_SECONDS = 3.0
_SCAN_CACHE = {}  # str(root) -> (monotonic time the scan started, fingerprint, (status, valid, invalid, reason))
_SCAN_LOCK = threading.Lock()


def _scan_fingerprint(root):
    """A tuple that changes when the store root's listing or any STORE file changes, or None when it cannot be taken."""
    try:
        r = str(root)
        sig = [os.path.lexists(os.path.join(r, ".git")), os.stat(r).st_mtime_ns]
        with os.scandir(r) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                st = e.stat()
                if not stat.S_ISDIR(st.st_mode):
                    sig.append((e.name,))
                    continue
                try:
                    sf = os.stat(os.path.join(r, e.name, STORE_FILE))
                    sig.append((e.name, st.st_mtime_ns, sf.st_mtime_ns, sf.st_size))
                except (FileNotFoundError, NotADirectoryError):
                    sig.append((e.name, st.st_mtime_ns))
        sig[2:] = sorted(sig[2:], key=lambda t: t[0])
        return tuple(sig)
    except OSError:
        return None


def _invalidate_scan_cache():
    with _SCAN_LOCK:
        _SCAN_CACHE.clear()


def _scan_cached(root=None, fresh=False):
    """scan_stores' answer, reused while the cache conditions above hold. `fresh` always rescans (and refreshes the cache)."""
    r = Path(root) if root else _stores_root()
    key = str(r)
    fp = None if _is_unc(key) else _scan_fingerprint(r)  # a network root is never touched here: scan_stores refuses it
    started = time.monotonic()
    if fp is not None and not fresh:
        with _SCAN_LOCK:
            hit = _SCAN_CACHE.get(key)
        if hit is not None and hit[1] == fp and started - hit[0] < SCAN_CACHE_SECONDS:
            st, valid, invalid, why = hit[2]
            return (st, list(valid), list(invalid), why)
    res = scan_stores() if root is None else scan_stores(root)
    # Only a clean success is kept. An empty STORE still being written is not final, so it is not kept either.
    if (fp is not None and res[0] == "ok" and not any(w.startswith("empty STORE (creation") for _d, w in res[2])
            and SCAN_CACHE_SECONDS > 0):
        with _SCAN_LOCK:
            if len(_SCAN_CACHE) >= 8:
                _SCAN_CACHE.clear()
            _SCAN_CACHE[key] = (started, fp, (res[0], list(res[1]), list(res[2]), res[3]))
    else:
        with _SCAN_LOCK:
            _SCAN_CACHE.pop(key, None)
    return res


def invalid_store_for_key(key_text, invalid):
    """-> the directory of `invalid` (scan_stores' [(dir, reason)]) that was named for the store identity written
    as `key_text` (`remote <host/path>`, then ` path <subpath>` for a monorepo store, or `local <path>`), else None.
    A store directory is `<name>-<hash prefix>` (_plan_dir), so a STORE file too broken to say whose store it is
    is still matched to its key by that suffix. Read-only; a key that is no identity matches nothing."""
    hashes = [_hash_for(i) for i in _key_split_candidates(key_text)]
    for d, _why in invalid:
        tail = os.path.basename(str(d)).rpartition("-")[2]
        if len(tail) >= 6 and any(h.startswith(tail) for h in hashes):
            return d
    return None


UNTRUSTED_REASON = ("untrusted root: under the system temp directory or a Downloads folder only a store keyed to "
                    "the folder's own path is read, never one keyed to its git remote")


def _trusted_levels(loc):
    """The levels of `loc` a store may be matched by. Under the system temp directory or a Downloads folder,
    where extracted archives and other untrusted trees land, a `.git` the folder carries (or a `gitdir:` file
    pointing at another repository) could claim any remote and so another workspace's store: only `local`
    identities match there. A store keyed to the folder's own path still serves it."""
    c = loc.cmp
    if any(_under(c, x) for x in _temp_dirs()) or any(_under(c, x) for x in _downloads_dirs()):
        return [lvl for lvl in loc.levels if lvl.kind == "local"]
    return loc.levels


def _match(valid, levels):
    index = {}
    for d, ident in valid:
        index.setdefault(id_key(ident), d)
    for lvl in levels:
        d = index.get(id_key(lvl))
        if d is not None:
            return d
    return None


def _find(folder, kind, fresh=False):
    """(Result, _Loc|None). Shared by find, find_or_create and would_create_path. The _Loc is None on an early result.
    `fresh` skips the scan cache: the two creation paths decide on an authoritative scan."""
    folder, early = _arg(folder)
    if early is not None:
        return early, None
    if kind not in KINDS:
        return Result("failed", None, reason="unknown kind %r" % (kind,)), None
    loc = _locate(folder)
    if loc.status != "ok":
        return Result("failed", None, reason=loc.reason), loc
    st, valid, _inv, why = _scan_cached(fresh=fresh)
    if st != "ok":
        return Result("failed", None, reason=why), loc  # SCAN-FAILED
    d = _match(valid, _trusted_levels(loc))
    if d is not None:
        return Result("found", d), loc
    if len(_trusted_levels(loc)) < len(loc.levels):
        return Result("none", None, reason=UNTRUSTED_REASON), loc
    return Result("none", None, reason="no store at or above %s" % loc.cmp), loc


def _store_text(i) -> str:
    return "%s %s\n" % (i.kind, i.value) + (("path %s\n" % i.subpath) if i.subpath else "")


def _writable(i) -> str:
    """'' when the STORE text for `i` reads back as the same identity, else why it cannot be stored."""
    parsed, why = _parse_store_text(_store_text(i))
    if parsed is None:
        return "the identity %r cannot be written to a STORE file (%s); nothing was created" % (id_line(i), why)
    if id_key(parsed) != id_key(i):
        return ("the identity %r (subpath %r) would not read back from its STORE file unchanged; nothing was created"
                % (id_line(i), i.subpath))
    return ""


def _name_for(i) -> str:
    base = re.sub(r"[^A-Za-z0-9]", "-", i.keyname or "")[:40]
    return base or "store"


def _hash_for(i) -> str:
    return hashlib.sha256((id_line(i) + "\n" + id_sub_line(i)).encode("utf-8")).hexdigest()


def _plan_dir(root: Path, i):
    """('new'|'hit'|'failed', dir, reason). Read-only. Extra hash digits only when identities differ.

    A candidate name is compared with the root's entries case-insensitively, as the identity it encodes is
    case-folded (id_key): on a case-sensitive file system (Linux) `Gamma-<hash>` and `gamma-<hash>` are two
    directories for one identity, where Windows and macOS see one. An existing spelling is reused."""
    h = _hash_for(i)
    name = _name_for(i)
    try:
        entries = os.listdir(str(root))
    except OSError as exc:
        return ("failed", root, "cannot list %s: %s" % (root, exc))
    for n in range(6, len(h) + 1, 2):
        want = "%s-%s" % (name, h[:n])
        same = sorted(e for e in entries if e.casefold() == want.casefold())
        if want in same:  # the exact spelling first, then any other case spelling of it
            same.remove(want)
            same.insert(0, want)
        if not same:
            return ("new", root / want, "")
        free = None
        for e in same:
            d = root / e
            st, other, why = _read_store(d)
            if st == "missing":
                free = free or d
                continue
            if st != "ok":
                sf = os.path.join(str(d), STORE_FILE)
                if st == "failed":
                    return ("failed", d, "STORE file %s is unreadable: %s" % (sf, why))
                return ("failed", d, "STORE file %s is present but invalid (%s): delete the directory or fix STORE" % (sf, why))
            if id_key(other) == id_key(i):
                return ("hit", d, "")
        if free is not None and len(same) == 1:
            return ("new", free, "")
    return ("failed", root, "no free store directory name for %s" % id_line(i))


def _unlink_temp(path: str) -> None:
    """Delete a temp file; a PermissionError (antivirus, indexer) is retried like a read. Never raises."""
    for attempt in range(READ_RETRIES + 1):
        try:
            os.unlink(path)
            return
        except PermissionError:
            if attempt >= READ_RETRIES:
                return
            time.sleep(READ_RETRY_SECONDS)
        except OSError:
            return


def _publish(d: Path, text: str) -> str:
    """Write STORE via temp file and a no-replace publish.

    Returns "published", "exists" (a STORE is already there) or "retry" (the directory or the temp file
    vanished mid-publish, for example a stale-temp cleanup after a long suspend; the caller plans again).
    """
    tmp = os.path.join(str(d), "%s.tmp-%d-%d-%d" % (STORE_FILE, os.getpid(), threading.get_ident(), time.monotonic_ns()))
    dest = os.path.join(str(d), STORE_FILE)
    try:
        with open(tmp, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, dest)
        except FileExistsError:
            return "exists"
        except FileNotFoundError:
            return "retry"
        except OSError:
            if os.name != "nt":
                raise
            try:
                os.rename(tmp, dest)
            except FileExistsError:
                return "exists"
            except FileNotFoundError:
                return "retry"
        return "published"
    except FileNotFoundError:
        return "retry"
    finally:
        _unlink_temp(tmp)


def _near_match(created: Path, i) -> str:
    st, valid, _inv, _why = scan_stores()
    if st != "ok":
        return ""
    stem = re.sub(r"-[0-9a-f]{6,}$", "", created.name)
    for d, other in valid:
        if d.name != created.name and re.sub(r"-[0-9a-f]{6,}$", "", d.name) == stem and id_key(other) != id_key(i):
            return ("near-match: store %s has the same folder name but a different identity (%s); "
                    "a moved folder or a changed remote is the usual cause" % (d.name, id_line(other)))
    return ""


def _clean_stale_tmp(d: Path) -> None:
    """Delete STORE.tmp-* files older than STALE_TMP_SECONDS in this one store directory."""
    try:
        names = os.listdir(str(d))
    except OSError:
        return
    now = time.time()
    for name in names:
        if name.startswith(STORE_FILE + ".tmp-"):
            p = os.path.join(str(d), name)
            try:
                if now - os.stat(p).st_mtime > STALE_TMP_SECONDS:
                    os.unlink(p)
            except OSError:
                pass


def _create_store(i, root: Path) -> "Result":
    bad = _writable(i)
    if bad:
        return Result("failed", None, reason=bad)
    for _ in range(8):
        state, d, why = _plan_dir(root, i)
        if state == "hit":
            _clean_stale_tmp(d)
            return Result("found", d)
        if state == "failed":
            return Result("failed", None, reason=why)
        os.makedirs(str(d), exist_ok=True)
        _clean_stale_tmp(d)
        got = _publish(d, _store_text(i))
        if got == "published":
            _invalidate_scan_cache()  # a store was just created: no cached scan may outlive that
            return Result("created", d, notice=_near_match(d, i))
    return Result("failed", None, reason="could not publish a STORE for %s" % id_line(i))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@_safe
def find(folder, kind="memory"):
    """Walk from folder up to the git toplevel (outside git: up to, not including, home) for a store."""
    return _find(folder, kind)[0]


_AT_NOT_REACHABLE = ("at=%s is outside the walk of %s (the folder and its ancestors within the same git toplevel; "
                     "outside git, the same non-git walk), so a store created there could never be found from it; "
                     "create the store at the folder itself or at an ancestor within that walk. To serve the folder "
                     "from a parent within the walk that already has a store, follow the steps for using a parent's "
                     "store (memory-rules.md \u00a7 The STORE file)")


@_safe
def find_or_create(folder, kind="memory", at=None):
    """find; when no store exists at or above the session folder, create one at that folder itself.

    The lookup always starts from `folder`. `at` (only when the user said so) moves the creation
    point to the folder itself or one of its ancestors within the same git toplevel (outside git,
    the same non-git walk); a store that already serves `folder` is returned and `at` is ignored
    with a notice. Any other `at` gives `none` and creates nothing. The folder and `at` must be
    existing directories before anything is created.
    """
    res, loc = _find(folder, kind, fresh=True)
    if res.status != "none" or loc is None:
        if res.status == "found" and at is not None and loc is not None:
            # `at` is not validated here: a store that already serves the folder wins, whatever `at` holds.
            at_ok, early = _arg(at, "at")
            if early is not None or _cmp(_verbatim(at_ok)) != loc.cmp:
                return Result("found", res.path, notice="at=%s ignored: the store %s already serves %s" % (at, res.path, folder))
        return res
    problem = _dir_check(_arg(folder)[0])
    if problem is not None:
        return problem
    idx = 0
    if at is not None:
        at_str, early = _arg(at, "at")  # validated only now, on the creation path
        if early is not None:
            return early
        at_cmp = _cmp(_verbatim(at_str))
        if at_cmp not in loc.paths:
            return Result("none", None, reason=_AT_NOT_REACHABLE % (at_str, folder))
        idx = loc.paths.index(at_cmp)
        problem = _dir_check(at_str, "at")
        if problem is not None:
            return problem
    why = _no_create_reason(loc.paths[idx])
    if why:
        return Result("none", None, reason="no store is created under %s" % why)
    return _create_store(loc.levels[idx], _stores_root())


@_safe
def would_create_path(folder, kind="memory"):
    """Read-only mirror of find_or_create (without `at`): the same (status, path), with nothing written.

    A 'created' status here means find_or_create would create that directory (it need not exist yet).
    """
    res, loc = _find(folder, kind, fresh=True)
    if res.status != "none" or loc is None:
        return res
    problem = _dir_check(_arg(folder)[0])
    if problem is not None:
        return problem
    why = _no_create_reason(loc.cmp)
    if why:
        return Result("none", None, reason="no store is created under %s" % why)
    bad = _writable(loc.levels[0])
    if bad:
        return Result("failed", None, reason=bad)
    state, d, why = _plan_dir(_stores_root(), loc.levels[0])
    if state == "failed":
        return Result("failed", None, reason=why)
    return Result("found" if state == "hit" else "created", d)


@_safe
def identity(folder):
    """Read-only. Result('found', Identity) for the folder's identity and subpath; needs no store root."""
    folder, early = _arg(folder)
    if early is not None:
        return early
    loc = _locate(folder)
    if loc.status != "ok":
        return Result("failed", None, reason=loc.reason)
    return Result("found", loc.levels[0])


def store_repo_root():
    """The store repo root (AGENT_PLAYBOOK_STORES, else the pointer file's stores=, else
    ~/.agent-playbook/stores) as a Path; nothing is touched."""
    return _stores_root()


# Public helpers, so another module never calls an underscore name of this one. Each never raises.

def norm_path(p) -> str:
    """The memory-rules.md § Path normalization form of `p` (absolute, 8.3 names expanded, `\\\\?\\`
    stripped, `/` separators, no trailing separator except on a root, case-folded): the value a `local`
    identity carries. '' when `p` is not a usable path."""
    try:
        return _norm_path(p)
    except Exception:
        return ""


def is_under(path, root) -> bool:
    """True when `path` equals `root` or lies inside it, compared on their norm_path forms at a `/`
    boundary (`c:/a/bc` is not under `c:/a/b`). False when either is not a usable path."""
    c, r = norm_path(path), norm_path(root)
    if not c or not r:
        return False
    return _under(c, r)


def store_text(i) -> str:
    """The exact STORE file text create() writes for the Identity `i` (`<kind> <value>` and, for a
    monorepo store, a `path <subpath>` line, each newline-terminated). '' when `i` is not an Identity."""
    try:
        return _store_text(i)
    except Exception:
        return ""


def store_key(i) -> str:
    """The one-line key text of the Identity `i` (the body of a dream-manifest.py `store:` key): `remote <value>`,
    plus ` path <subpath>` for a monorepo store, or `local <value>`. '' when `i` is not an Identity."""
    try:
        return id_line(i) + ((" path " + i.subpath) if i.subpath else "")
    except Exception:
        return ""


def _key_split_candidates(text):
    """Every Identity a one-line key text can name. A remote value may itself hold " path " (an Azure DevOps
    project named "Critical Path Tools"), so `remote <a> path <b> path <c>` has one reading per occurrence."""
    kind, _sp, rest = str(text).strip().partition(" ")
    if kind == "local":
        return [Identity("local", rest.strip(), "", None, None)] if rest.strip() else []
    if kind != "remote" or not rest.strip():
        return []
    out = [Identity("remote", rest.strip(), "", None, None)]
    start = 0
    while True:
        k = rest.find(" path ", start)
        if k < 0:
            return out
        value, sub = rest[:k].strip(), rest[k + len(" path "):].strip()
        if value and sub:
            out.append(Identity("remote", value, sub, None, None))
        start = k + 1


def store_for_key(key_text, valid):
    """-> the directory of `valid` (scan_stores' [(dir, Identity)]) whose one-line key equals `key_text`,
    case-folded, else None. The way to look a `store:` key up: the text cannot be parsed back unambiguously
    (see _key_split_candidates), but it can be compared."""
    want = str(key_text).strip().casefold()
    for d, ident in valid:
        if store_key(ident).casefold() == want:
            return d
    return None


def parse_store_key(text):
    """The Identity a `store:` key body most likely names: `remote <value>`, `remote <value> path <subpath>`
    (a monorepo store) or `local <value>`. None for any other text. The text is ambiguous when the remote
    value holds " path ": this reading splits on the last occurrence. To look a key up use store_for_key,
    which compares texts. The Identity's keyname and toplevel are None; compare it with same_identity or id_key."""
    try:
        kind, _sp, rest = str(text).strip().partition(" ")
        if kind == "remote":
            value, _sep, sub = rest.rpartition(" path ") if " path " in rest else (rest, "", "")
        elif kind == "local":
            value, sub = rest, ""
        else:
            return None
        value, sub = value.strip(), sub.strip()
        if not value:
            return None
        return Identity(kind, value, sub, None, None)
    except Exception:
        return None


@_safe
def create(folder, subpath=None):
    """Migration only: create (or find) the store keyed to folder's repo plus an explicit subpath.

    Bypasses the no-create roots, because the migration names its sources explicitly. Remote repos:
    `subpath` is repo-relative and replaces the derived one. Local identity: the key folder is
    folder/subpath. The folder must exist. Needs the store repo root; never creates it.
    """
    folder, early = _arg(folder)
    if early is not None:
        return early
    problem = _dir_check(folder)
    if problem is not None:
        return problem
    loc = _locate(folder)
    if loc.status != "ok":
        return Result("failed", None, reason=loc.reason)
    base = loc.levels[0]
    if subpath is not None:
        sub = str(subpath).replace("\\", "/").strip("/")
        if base.kind == "remote":
            name = sub.rsplit("/", 1)[-1] if sub else _keyname(loc.toplevel)
            base = Identity("remote", base.value, sub, name, base.toplevel)
        else:
            keyed = os.path.join(_verbatim(folder), sub) if sub else _verbatim(folder)
            keyed = _verbatim(keyed)
            base = Identity("local", _cmp(keyed), "", _keyname(keyed), None)
    root = _stores_root()
    why = _check_root(root)
    if why:
        return Result("failed", None, reason=why)
    return _create_store(base, root)


# ---------------------------------------------------------------------------
# Reading an artifact class. A consumer that READS an artifact class asks resolve_artifact(), which
# looks, per level from the folder up to the repo toplevel (the walk-up rule of find), for the store-repo
# store of that level; the first one that holds content for the kind wins. find / find_or_create /
# would_create_path name a store whether or not it holds content: this block adds a reader, never a
# second place to create stores.
# ---------------------------------------------------------------------------

class Artifact(tuple):
    """(source, path) of one artifact class, with these attributes.

    source   store-repo (a store that holds content), in-workspace (only plans inside the config repo: its
             own <config-repo>/plans), none (no store holds content: path is then <folder>/<kind>), or
             failed (path is None)
    path     the artifact directory (<store or folder>/<kind>), a Path
    store    the store directory the answer lives in (store-repo), else None. For none: the nearest store
             directory found at any level even though it holds no content (or None)
    folder   the folder the answer belongs to (the level where it was found; the session folder for none)
    reason   why the store repo was skipped (for example it is missing), '' when it was not
    store_repo  "ok", "missing" (no store repo on this machine: nothing to consult, so none is the normal
             answer) or "unreadable" (the store repo exists but could not be scanned: the answer may be
             wrong, so a reader says so and a writer refuses). Every answer carries the real state, an
             early failed one (bad folder, unknown kind, a folder that cannot be located) included;
             "unknown" only when an internal error stopped resolve_artifact before the scan
    """

    def __new__(cls, source, path=None, store=None, folder=None, reason="", store_repo="ok"):
        self = tuple.__new__(cls, (source, path))
        self.store = store
        self.folder = folder
        self.reason = reason
        self.store_repo = store_repo
        return self

    @property
    def source(self):
        return self[0]

    @property
    def path(self):
        return self[1]

    def __repr__(self):
        return "Artifact(%r, %r, store=%r)" % (self[0], self[1], self.store)


def populated(d) -> bool:
    """True when the directory `d` holds content for its artifact class: at least one `.md` file at any
    depth below it, a `.handoff-*.md` file not counting. False otherwise, and when `d` is missing or
    cannot be listed. This is the rule memory-rules.md § Resolution contract reads by: a store, or an
    in-workspace level, holds content for a kind only when this is True for its `<kind>/` directory."""
    try:
        for _dp, _dn, files in os.walk(str(d)):
            for f in files:
                if f.lower().endswith(".md") and not f.startswith(".handoff-"):
                    return True
    except OSError:
        return False
    return False


def resolve_artifact(folder, kind="memory"):
    """Where to READ `kind` for `folder`. Never raises.

    Per level from the folder up to the repo toplevel (outside git: the same walk find uses), the
    first store-repo store that holds content for the kind wins, so a nested folder's own store beats
    its toplevel's (plan 261006 P-8). When the store repo cannot be scanned (missing, unreadable) the
    answer is none and .reason says so. A none answer is never permission to read an in-workspace copy:
    a reader asks folder_fallback(). The config repo is no exception: its plans live in its store.
    """
    try:
        return _resolve_artifact(folder, kind)
    except Exception as exc:
        return Artifact("failed", None, reason="internal error: %s: %s" % (type(exc).__name__, exc),
                        store_repo="unknown")


def _repo_scan():
    """(scan status, valid stores, reason, store_repo state) of the store repo, from the cached scan."""
    st, valid, _inv, why = _scan_cached()
    if st == "ok":
        return st, valid, "", "ok"
    return st, [], "store repo skipped: %s" % why, ("missing" if why.startswith(MISSING_ROOT) else "unreadable")


def _resolve_artifact(folder, kind):
    folder, early = _arg(folder)
    if early is not None:
        _st, _valid, reason, repo_state = _repo_scan()
        return Artifact("failed" if early.status == "failed" else "none", None, reason=early.reason, store_repo=repo_state)
    if kind not in KINDS:
        return Artifact("failed", None, reason="unknown kind %r" % (kind,), store_repo=_repo_scan()[3])
    loc = _locate(folder)
    if loc.status != "ok":
        return Artifact("failed", None, reason=loc.reason, store_repo=_repo_scan()[3])
    verb = _given_chain(folder, len(loc.levels))
    st, valid, reason, repo_state = _repo_scan()
    index = {}
    for d, ident in valid:
        index.setdefault(id_key(ident), d)
    nearest_store = None
    trusted = _trusted_levels(loc)
    for i, lvl in enumerate(loc.levels):
        if lvl not in trusted:
            continue
        d = index.get(id_key(lvl))
        if d is None:
            continue
        if nearest_store is None:
            nearest_store = d
        if populated(d / kind):
            return Artifact("store-repo", d / kind, d, Path(verb[i]), reason, repo_state)
    if not reason and len(trusted) < len(loc.levels):
        reason = UNTRUSTED_REASON
    return Artifact("none", Path(verb[0]) / kind, nearest_store, Path(verb[0]), reason, repo_state)


def _given_chain(folder: str, n: int) -> list:
    """The first `n` levels of `folder`'s walk in the caller's spelling (case, 8.3 names kept); matching
    used the expanded form."""
    given = os.path.abspath(folder)
    if given.startswith("\\\\?\\") and not given.upper().startswith("\\\\?\\UNC\\"):
        given = given[4:]
    return _chain(given)[:n]


def folder_fallback(folder, kind="memory"):
    """The in-workspace `<level>/<kind>` directory (a Path) a reader may read when no store serves
    `folder`, else None. Read-only; never raises (any error gives None).

    A Path is returned only when ALL hold: the store repo scanned ok (a missing or unreadable store
    repo gives None); no store-repo store exists at any level of the folder's walk, not even one that
    holds no content; `folder` is a no-create folder (would_create_path(folder) is none: the system temp
    directory, ~/.agent-playbook, the home folder itself, a drive root, a Downloads folder,
    .claude/worktrees); for `memory`, the folder is not inside the config repo (its memory/ is the user
    tier); and a level from the folder up to its git toplevel (outside git: the folder itself only)
    holds content for the kind (populated()). The nearest such level wins. In any other folder an
    in-workspace copy is a leftover and is not read (memory-rules.md § Resolution contract).
    """
    try:
        return _folder_fallback(folder, kind)
    except Exception:
        return None


def _folder_fallback(folder, kind):
    folder, early = _arg(folder)
    if early is not None or kind not in KINDS:
        return None
    loc = _locate(folder)
    if loc.status != "ok" or not loc.levels:
        return None
    st, valid, _why, _state = _repo_scan()
    if st != "ok" or _match(valid, _trusted_levels(loc)) is not None:
        return None
    if would_create_path(folder, kind).status != "none":
        return None
    if kind == "memory" and loc.toplevel:
        is_cfg, why = _is_config_repo(loc.toplevel)
        if why or is_cfg:
            return None
    verb = _given_chain(folder, len(loc.levels))
    for lvl in (verb if loc.toplevel else verb[:1]):
        d = Path(lvl) / kind
        if populated(d):
            return d
    return None


# ---------------------------------------------------------------------------
# Fixture builders for the callers' selftests (plan 261016 Phase 5). Not part of the API: they write
# only under the path they are given, and run no git.
# ---------------------------------------------------------------------------

def fixture_repo(path, url=None):
    """A minimal git repository at `path` (HEAD, objects/, refs/, config), `origin` set to `url` when given."""
    g = Path(path) / ".git"
    for sub in ("objects", "refs"):
        (g / sub).mkdir(parents=True, exist_ok=True)
    (g / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    cfg = '[remote "origin"]\n\turl = %s\n' % url if url else ""
    (g / "config").write_text(cfg, encoding="utf-8")
    return Path(path)


def fixture_store(stores_root, dirname, text):
    """A store directory `dirname` under `stores_root` (made a store repo root if it is not one yet) holding STORE `text`."""
    root = Path(stores_root)
    (root / ".git").mkdir(parents=True, exist_ok=True)
    d = root / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / STORE_FILE).write_bytes(text.encode("utf-8"))
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_EXIT = {"found": 0, "created": 0, "none": 3, "failed": 2}


def _emit(res: Result, is_identity: bool = False) -> int:
    code = _EXIT[res.status]
    if res.notice:
        print(res.notice, file=sys.stderr)
    if res.status == "failed":
        print("store-resolver: " + (res.reason or "failed"), file=sys.stderr)
    elif res.status == "none":
        # stdout stays empty (exit 3 is the answer); the reason tells a skill caller why there is no store
        print("store-resolver: " + " ".join((res.reason or "no store").split()), file=sys.stderr)
    elif res.status in ("found", "created"):
        if is_identity:
            print(id_line(res.path))
            if res.path.subpath:
                print("path " + res.path.subpath)
        else:
            print(res.path)
    return code


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


def _main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    _require_venv(__file__)
    ap = argparse.ArgumentParser(description="Find or create the workspace store for a folder.")
    ap.add_argument("--selftest", action="store_true", help="run the fixture tests")
    sub = ap.add_subparsers(dest="cmd")
    for name, extra in (("find", "kind"), ("find-or-create", "kind-at"), ("would-create", "kind"),
                        ("identity", ""), ("list", "nofolder"), ("resolve", "kind"), ("paths", "nofolder")):
        sp = sub.add_parser(name)
        if extra != "nofolder":
            sp.add_argument("folder")
        if extra.startswith("kind"):
            sp.add_argument("--kind", default="memory", choices=KINDS)
        if extra == "kind-at":
            sp.add_argument("--at", default=None,
                            help="create at this ancestor of the folder (only when the user said so)")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.cmd is None:
        ap.print_usage(sys.stderr)
        return 2
    if args.cmd == "paths":
        # tab-separated name, value: where this machine keeps the engine, the store repo and user memory
        root = playbook_root()
        print("root\t%s" % (root if root else ""))
        print("stores\t%s" % _stores_root())
        print("user_memory\t%s" % user_memory_dir())
        print("engine_branch\t%s" % engine_branch())
        print("config\t%s" % _config_path())
        return 0 if root else 2
    if args.cmd == "list":
        st, valid, invalid, why = scan_stores()
        if st == "failed":
            return _emit(Result("failed", None, reason=why))
        for d, i in valid:
            print("%s\t%s\t%s" % (d, id_line(i), i.subpath))
        for d, w in invalid:
            print("INVALID %s: %s" % (d, w), file=sys.stderr)
        return 0
    if args.cmd == "resolve":
        # tab-separated source, path
        art = resolve_artifact(args.folder, args.kind)
        if art.reason:
            print("store-resolver: " + art.reason, file=sys.stderr)
        if art.source == "failed" or art.store_repo in ("missing", "unreadable"):
            return 2  # memory-rules.md § Resolution contract step 4: a missing or unreadable store repo is failed
        print("%s\t%s" % (art.source, art.path))
        return 0 if art.source != "none" else 3
    if args.cmd == "identity":
        return _emit(identity(args.folder), is_identity=True)
    if args.cmd == "find":
        return _emit(find(args.folder, args.kind))
    if args.cmd == "would-create":
        return _emit(would_create_path(args.folder, args.kind))
    return _emit(find_or_create(args.folder, args.kind, args.at))


def main(argv=None) -> int:
    """CLI entry. An unexpected exception prints one line and exits 2 (argparse usage errors keep their exit code)."""
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:
        print("store-resolver: unexpected error: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# Selftest: the fixture tests live in store-resolver-selftest.py, so a consumer loads a lean module
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Run store-resolver-selftest.py in this module's namespace (its cases reach the internals by name)."""
    path = Path(__file__).resolve().parent / "store-resolver-selftest.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), globals())
    return globals()["_run_selftest"]()

if __name__ == "__main__":
    sys.exit(main())
