"""Path matching and rewriting for qmigrate-workspace. Windows paths, raw bytes only.

One OLD -> NEW mapping, matched in every form the agent stores were seen to use
(2026-10-02): plain backslashes, JSON-escaped (2 or 4 backslashes), forward
slashes, URL-encoded (`c%3A`, `%20`), either drive-letter case, any letter case
in the rest of the path, and a `~/` home-relative form. The replacement keeps the
separator, drive-letter case and encoding of each match. A match must end at a
path boundary, so `...\\Repo` never matches `...\\Repos`.

Nothing here parses JSON: depth-limited parsers silently truncate deeply nested
session files, and a round trip can add a BOM or reorder keys.
"""
import os
import re

SEP = rb"(?:\\{1,4}|/)"
SPACE = rb"(?: |%20)"
COLON = rb"(?::|%3[Aa])"
# A match must not run on into a longer sibling name: `Repo` must not match `Repos`, `Repo-old`,
# `Repo.bak`, `Repo(2)` or `Repo~1`. A space cannot be excluded (it also ends a path in prose), so a
# sibling like `Repo Old` or `Repo (copy)` is caught by ambiguous_siblings() instead.
BOUNDARY_CHARS = r"A-Za-z0-9_\-.(~"
BOUNDARY = ("(?![" + BOUNDARY_CHARS + "])").encode()


def segments(path):
    """'C:\\a\\b c' -> ['C:', 'a', 'b c']"""
    return [s for s in re.split(r"[\\/]+", path.strip()) if s]


def slug(path):
    """Claude Code's project-folder name: every non-alphanumeric character becomes '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path.rstrip("\\/"))


def _seg(s):
    out = b""
    for ch in s.encode("utf-8"):
        c = bytes([ch])
        out += SPACE if c == b" " else COLON if c == b":" else re.escape(c)
    return out


def _home_relative(path):
    home = os.path.expanduser("~")
    if path.lower().startswith(home.lower() + "\\"):
        return "~/" + path[len(home) + 1:].replace("\\", "/")
    return None


class PathMap:
    def __init__(self, old, new):
        self.old, self.new = old.rstrip("\\/"), new.rstrip("\\/")
        self.old_segs, self.new_segs = segments(self.old), segments(self.new)
        if not re.fullmatch(r"[A-Za-z]:", self.old_segs[0]) or not re.fullmatch(r"[A-Za-z]:", self.new_segs[0]):
            raise ValueError("both paths must be absolute Windows paths with a drive letter")
        self.regex = re.compile(SEP.join(_seg(s) for s in self.old_segs) + BOUNDARY, re.I)
        self.old_slug, self.new_slug = slug(self.old), slug(self.new)
        t_old, t_new = _home_relative(self.old), _home_relative(self.new)
        self.tilde = None
        if t_old:
            self.tilde = (re.compile(re.escape(t_old.encode("utf-8")) + BOUNDARY, re.I),
                          (t_new or self.new.replace("\\", "/")).encode("utf-8"))

    def _replace(self, m):
        text = m.group(0)
        seps = re.findall(SEP, text)
        sep = seps[0] if seps else b"\\"
        drive = self.new_segs[0][0]
        drive = drive.lower() if text[:1].islower() else drive.upper()
        colon = b"%3A" if re.search(rb"%3[Aa]", text[:6]) else b":"
        spc = b"%20" if b"%20" in text else b" "
        parts = [drive.encode() + colon] + [s.encode("utf-8").replace(b" ", spc) for s in self.new_segs[1:]]
        return sep.join(parts)

    def rewrite(self, data):
        """-> (new_bytes, number_of_replacements). Idempotent once applied."""
        new, n = self.regex.subn(self._replace, data)
        if self.tilde:
            new, k = self.tilde[0].subn(self.tilde[1], new)
            n += k
        return new, n

    def search(self, data):
        return self.regex.search(data) or (self.tilde and self.tilde[0].search(data))

    def rewrite_str(self, s):
        return self.rewrite(s.encode("utf-8"))[0].decode("utf-8")


def ambiguous_siblings(old):
    """Folders beside OLD whose name starts with OLD's name and that the regex would still match
    (e.g. `Repo Old`). Their paths would be rewritten too, so apply.py refuses while any exist."""
    old = old.rstrip("\\/")
    parent, base = os.path.dirname(old), os.path.basename(old)
    pat = re.compile(re.escape(base) + "(?![" + BOUNDARY_CHARS + "])", re.I)
    try:
        names = os.listdir(parent)
    except OSError:
        return []
    return [n for n in names if n.lower() != base.lower() and pat.match(n)]


def work_dir(old, new, base=None):
    """Per-migration work directory, so markers and venv freezes of one move never leak into another.
    cutover.ps1 and venvs.ps1 compute the same name (Get-WorkDir)."""
    import hashlib
    base = base or os.path.join(os.path.expanduser("~"), ".agent-playbook", "qmigrate-workspace")
    key = (old.rstrip("\\/").lower() + "|" + new.rstrip("\\/").lower()).encode("utf-8")
    return os.path.join(base, os.path.basename(old.rstrip("\\/")) + "-" + hashlib.sha256(key).hexdigest()[:8])


def kiro_workspace_hash(paths):
    """kiro-cli v3 session-folder name. Formula: providers/kiro/reference/kiro-cli-v3-internals.md
    (Workspace-hash derivation proof), Windows semantics (lower-cased)."""
    import hashlib
    import posixpath
    if not paths:
        return "_global"
    norm = sorted(posixpath.normpath(p.replace("\\", "/")).lower() for p in paths)
    return hashlib.sha256("\0".join(norm).encode("utf-8")).hexdigest()[:16]


def load_store_resolver():
    """The playbook's store resolver (shared/skills/qdream/scripts/store-resolver.py), loaded by path from
    this file's real location, so a deployed symlinked copy finds the config repo's resolver."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "qdream", "scripts", "store-resolver.py")
    spec = importlib.util.spec_from_file_location("store_resolver", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def store_rewrites(sr, old, new):
    """Read-only plan for the store repo: (status, rewrites, invalid, reason).

    rewrites: [(store_file, new_bytes, note, blocker)] for every `local` store whose path equals OLD or lies under it,
    re-keyed to the same relative location under NEW in the resolver's own normalized form (the text `create`
    writes). `remote` stores are never touched: a git checkout keeps its identity when it moves. Directory names
    are never changed; resolution reads STORE content only. status is the resolver's scan status (`ok`, `missing`
    for no store repo, `failed`). blocker is True when another store already holds the new line (two stores
    with one key: resolution would pick either). note is non-empty then, and also when the NEW folder would not
    resolve to the rewritten line (for example it now sits inside a git checkout, so its identity is `remote`)."""
    st, valid, invalid, why = sr.scan_stores()
    if st != "ok":
        return ("missing" if why.startswith(sr.MISSING_ROOT) else "failed"), [], invalid, why
    old_c = sr.norm_path(old)
    taken = {sr.id_key(i): d for d, i in valid}
    out = []
    for d, ident in valid:
        if ident.kind != "local" or not sr.is_under(ident.value, old_c):
            continue
        rel = ident.value[len(old_c):].strip("/")
        new_abs = os.path.join(new, rel.replace("/", os.sep)) if rel else new
        want = sr.Identity("local", sr.norm_path(new_abs), "", None, None)
        if sr.same_identity(want, ident):
            continue
        note, blocker = "", False
        holder = taken.get(sr.id_key(want))
        if holder is not None:
            note, blocker = "%s already holds %s" % (holder, sr.id_line(want)), True
        else:
            got = sr.identity(new_abs)
            if got.status != "found" or not sr.same_identity(got.path, want):
                note = "%s resolves to %s, not %s" % (
                    new_abs, sr.id_line(got.path) if got.status == "found" else got.reason, sr.id_line(want))
        out.append((os.path.join(str(d), sr.STORE_FILE), sr.store_text(want).encode("utf-8"), note, blocker))
    return "ok", out, invalid, ""
