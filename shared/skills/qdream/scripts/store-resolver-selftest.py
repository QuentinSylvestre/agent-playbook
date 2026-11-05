"""store-resolver-selftest.py -- the fixture tests of store-resolver.py.

Not a module of its own: store-resolver.py --selftest compiles this file and runs it in the resolver's
namespace, so the cases reach the internals by name. Run it through store-resolver.py --selftest."""

def _fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "store-resolver"


def _run_selftest() -> int:
    import builtins
    import contextlib
    import importlib.util
    import io
    import random
    import shutil
    import tempfile

    results, failures = [], []

    def chk(name, cond, detail=""):
        results.append(name)
        if cond:
            print("PASS " + name)
        else:
            failures.append(name)
            print("FAIL %s %s" % (name, detail))

    def skip(name, why):
        print("SKIP %s (%s)" % (name, why))

    saved_env = os.environ.get("AGENT_PLAYBOOK_STORES")
    saved_test = dict(_TEST)
    global EMPTY_WAIT_SECONDS
    saved_wait = EMPTY_WAIT_SECONDS
    raw_root = tempfile.mkdtemp(prefix="srst-")

    def git_skeleton(gitdir, head="ref: refs/heads/main\n", objects=True, refs=True):
        """A `.git` directory as git's is_git_directory sees it: HEAD, objects/ and refs/ (each optional). No config."""
        gitdir = Path(gitdir)
        gitdir.mkdir(parents=True, exist_ok=True)
        if head is not None:
            (gitdir / "HEAD").write_text(head, encoding="utf-8")
        if objects:
            (gitdir / "objects").mkdir(exist_ok=True)
        if refs:
            (gitdir / "refs").mkdir(exist_ok=True)
        return gitdir

    class World:
        def __init__(self):
            self.raw = raw_root
            self.root = Path(_verbatim(raw_root))
            self.home = self.root / "home"
            self.systemp = self.root / "systemp"
            self.dl = self.home / "OneDrive - Test Org" / "Downloads"
            self.home.mkdir()
            self.n = 0
            self.stores = None
            self.reset_patches()
            self.new_stores()

        def reset_patches(self):
            _TEST.clear()
            _TEST.update(home=str(self.home), temp=[str(self.systemp)], downloads=[str(self.home / "Downloads"), str(self.dl)],
                         config_repo="")

        def new_stores(self):
            self.n += 1
            self.stores = self.root / ("stores%d" % self.n)
            (self.stores / ".git").mkdir(parents=True)
            os.environ["AGENT_PLAYBOOK_STORES"] = str(self.stores)
            return self.stores

        def dirs(self):
            if not self.stores.is_dir():
                return []
            return sorted(p.name for p in self.stores.iterdir() if p.is_dir() and not p.name.startswith("."))

        def area(self, name=None):
            self.n += 1
            p = self.root / ("a%d" % self.n) / (name or "x")
            p.mkdir(parents=True)
            return p

        def repo(self, path, url=None, remotes=None, extra=""):
            path.mkdir(parents=True, exist_ok=True)
            git_skeleton(path / ".git")
            text = ""
            if url:
                text += '[remote "origin"]\n\turl = %s\n' % url
            for n, u in (remotes or {}).items():
                text += '[remote "%s"]\n\turl = %s\n' % (n, u)
            (path / ".git" / "config").write_text(text + extra, encoding="utf-8")
            return path

        def store(self, dirname, text):
            d = self.stores / dirname
            d.mkdir(parents=True, exist_ok=True)
            (d / "STORE").write_bytes(text.encode("utf-8"))
            return d

        def snapshot(self):
            snap = []
            for dp, dn, fn in os.walk(str(self.root)):
                for nm in dn + fn:
                    p = os.path.join(dp, nm)
                    stt = os.lstat(p)
                    snap.append((p, stt.st_mtime_ns, stt.st_size))
            snap.sort()
            return snap

    def fill_creds(text):
        # built at run time so no credential-shaped URL sits in the repo
        return (text.replace("{CRED4}", "user:123/" + "45@").replace("{CRED5}", "u:p@" + "ss/x@")
                .replace("{QTOKEN}", "access_" + "token=abc123").replace("{CRED3}", "bob:p/" + "ss@").replace("{CRED2}", "bob:p@" + "ss@")
                .replace("{CRED}", "bob:" + "pw" + "@"))

    def exp_dir(w, base, idline, subline):
        h = hashlib.sha256((idline + "\n" + subline).encode("utf-8")).hexdigest()[:6]
        return w.stores / (re.sub(r"[^A-Za-z0-9]", "-", base) + "-" + h)

    def made(res, w):
        return res.status == "created" and (res.path / "STORE").is_file()

    @contextlib.contextmanager
    def flaky_open(w_root, target, fail_times):
        """builtins.open raises PermissionError for `target` (a path) the first `fail_times` times."""
        real = builtins.open
        state = {"n": 0}
        suffix = Path(target).relative_to(w_root).as_posix().lower()

        def fake(file, *a, **k):
            if isinstance(file, str) and file.replace("\\", "/").lower().endswith(suffix) and state["n"] < fail_times:
                state["n"] += 1
                raise PermissionError(13, "sharing violation (selftest)")
            return real(file, *a, **k)
        builtins.open = fake
        try:
            yield state
        finally:
            builtins.open = real

    def store_text(d):
        return (d / "STORE").read_text(encoding="utf-8")

    @contextlib.contextmanager
    def unc_spy():
        """Record every filesystem call whose first argument is a UNC path; none may happen. Yields the list."""
        hits, saved = [], []

        def wrap(mod, name):
            real_fn = getattr(mod, name)
            saved.append((mod, name, real_fn))

            def wrapped(*a, **k):
                if a and isinstance(a[0], (str, os.PathLike)) and _is_unc(str(a[0])):
                    hits.append(name)
                return real_fn(*a, **k)
            setattr(mod, name, wrapped)
        for mod, name in ((os, "stat"), (os, "lstat"), (os, "listdir"), (os, "makedirs"), (os.path, "isdir"), (os.path, "isfile"),
                          (os.path, "lexists"), (os.path, "exists"), (os.path, "abspath"), (builtins, "open")):
            wrap(mod, name)
        real_expand = globals()["_expand_exact"]

        def spy_expand(p_):
            if _is_unc(str(p_)):
                hits.append("_expand_exact")
            return real_expand(p_)
        globals()["_expand_exact"] = spy_expand
        try:
            yield hits
        finally:
            globals()["_expand_exact"] = real_expand
            for mod, name, real_fn in saved:
                setattr(mod, name, real_fn)

    try:
        w = World()
        fx = _fixtures_dir()

        # --- remote normalization table (hand-written expectations) ---
        for line in (fx / "normalize.tsv").read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, url, exp = line.split("\t")
            got = _normalize_remote("" if url == "EMPTY" else fill_creds(url))
            chk("normalize:" + name, got == (None if exp == "LOCAL" else exp), "got %r want %r" % (got, exp))

        # --- .git/config fixtures, end to end ---
        for line in (fx / "configs.tsv").read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            fname, exp = line.split("\t")
            repo = w.area("repo")
            git_skeleton(repo / ".git")
            (repo / ".git" / "config").write_text(fill_creds((fx / "configs" / fname).read_text(encoding="utf-8")), encoding="utf-8")
            res = identity(repo)
            if exp == "local":
                ok = res.status == "found" and res.path.kind == "local" and res.path.value == _norm_path(repo)
            else:
                ok = res.status == "found" and id_line(res.path) == exp and res.path.subpath == ""
            chk("config:" + fname, ok, repr(res))

        # --- BOM and CRLF in .git/config (utf-8-sig rule) ---
        repo = w.area("repo")
        git_skeleton(repo / ".git")
        (repo / ".git" / "config").write_bytes(b'\xef\xbb\xbf[remote "origin"]\r\n\turl = https://github.com/O/R.git\r\n')
        chk("config:bom-crlf", id_line(identity(repo).path) == "remote github.com/o/r")

        # --- app pair: bare and .git remotes share one identity and one store ---
        w.new_stores()
        a = w.repo(w.area("cloud") / "app", url="https://git.example.internal/cloud/app")
        b = w.repo(w.area("src") / "app", url="https://git.example.internal/cloud/app.git")
        ia, ib = identity(a).path, identity(b).path
        chk("app-pair:identity-equal", ia is not None and ib is not None and id_key(ia) == id_key(ib)
            and ia.value == "git.example.internal/cloud/app", "%r %r" % (ia, ib))
        ra = find_or_create(a)
        chk("app-pair:first-checkout-creates", made(ra, w), repr(ra))
        rb = find_or_create(b)
        chk("app-pair:second-checkout-finds-same-store", rb.status == "found" and rb.path == ra.path and len(w.dirs()) == 1, repr(rb))

        # --- monorepo shape: subpaths stay distinct ---
        w.new_stores()
        top = w.repo(w.area("mono") / "mono", url="https://git.example.internal/core/mono.git")
        ax, sl, zj = top / "support/TeamA/alpha", top / "support/TeamA/Beta", top / "support/TeamA/gamma"
        for p in (ax, sl, zj):
            p.mkdir(parents=True)
        d_ax = w.store("alpha-1", "remote git.example.internal/core/mono\npath support/TeamA/alpha\n")
        d_sl = w.store("beta-1", "remote git.example.internal/core/mono\npath support/TeamA/Beta\n")
        chk("monorepo:alpha-own-store", find(ax).path == d_ax)
        chk("monorepo:beta-own-store", find(sl).path == d_sl)
        chk("monorepo:sibling-without-store-none", find(zj).status == "none")
        chk("monorepo:toplevel-does-not-see-subpath-stores", find(top).status == "none")
        chk("monorepo:subpath-compared-case-folded", find(top / "support/TeamA/beta").path == d_sl)
        ident_zj = identity(zj).path
        chk("monorepo:subpath-verbatim", ident_zj.subpath == "support/TeamA/gamma" and identity(sl).path.subpath == "support/TeamA/Beta")

        # --- nested folders walking up to a store; nearest wins; never beyond the toplevel ---
        w.new_stores()
        r = w.repo(w.area("nest") / "r", url="https://github.com/o/nest.git")
        (r / "a/b/c").mkdir(parents=True)
        (r / "x/y").mkdir(parents=True)
        d_top = w.store("nest-top", "remote github.com/o/nest\n")
        d_a = w.store("nest-a", "remote github.com/o/nest\npath a\n")
        chk("nested:deep-folder-reaches-a", find(r / "a/b/c").path == d_a)
        chk("nested:store-folder-itself", find(r / "a").path == d_a)
        chk("nested:other-branch-reaches-toplevel", find(r / "x/y").path == d_top)
        chk("nested:toplevel-itself", find(r).path == d_top)
        outside = w.root / "outside-parent"
        outside.mkdir()
        w.store("outside-local", "local %s\n" % _norm_path(outside))
        r2 = w.repo(outside / "repo2", url="https://github.com/o/other.git")
        chk("nested:walk-stops-at-git-toplevel", find(r2).status == "none" and find(r2).status != "found")
        r3 = w.repo(outside / "repo3")
        (r3 / "sub").mkdir()
        d_r3 = w.store("r3-local", "local %s\n" % _norm_path(r3))
        chk("nested:local-repo-subfolder-reaches-toplevel-store", find(r3 / "sub").path == d_r3)
        r4 = w.repo(outside / "repo4")
        (r4 / "sub").mkdir()
        chk("nested:local-repo-walk-stops-at-toplevel-parent-store-unreachable", find(r4 / "sub").status == "none" and find(outside).status == "found")

        # --- new subfolder in a repo with sibling subpath stores ---
        w.new_stores()
        r = w.repo(w.area("sib") / "r", url="https://github.com/o/sib.git")
        for n in ("a", "b", "c", "a/deep"):
            (r / n).mkdir(parents=True)
        d_a = w.store("sib-a", "remote github.com/o/sib\npath a\n")
        w.store("sib-b", "remote github.com/o/sib\npath b\n")
        before = len(w.dirs())
        rc = find_or_create(r / "c")
        chk("sibling:new-subfolder-created-at-subfolder", made(rc, w) and store_text(rc.path) == "remote github.com/o/sib\npath c\n"
            and rc.path == exp_dir(w, "c", "remote github.com/o/sib", "path c") and len(w.dirs()) == before + 1, repr(rc))
        chk("sibling:deeper-folder-finds-existing", find_or_create(r / "a/deep").path == d_a and len(w.dirs()) == before + 1)
        rt = find_or_create(r)
        chk("sibling:toplevel-without-store-creates-at-toplevel", made(rt, w) and store_text(rt.path) == "remote github.com/o/sib\n"
            and rt.path == exp_dir(w, "r", "remote github.com/o/sib", ""), repr(rt))
        rt2 = find_or_create(r)
        chk("sibling:second-call-finds", rt2.status == "found" and rt2.path == rt.path)

        # --- at= (user decision 2026-10-16, "Reachable only": the lookup always starts from the session folder) ---
        w.new_stores()
        r = w.repo(w.area("atx") / "r", url="https://github.com/o/atx.git")
        (r / "a/x").mkdir(parents=True)
        d_atx = w.store("atx-a", "remote github.com/o/atx\npath a\n")
        n0 = len(w.dirs())
        ra = find_or_create(r / "a/x", at=r)
        chk("at:ancestor-while-nearer-store-exists-returns-it-with-notice",
            ra.status == "found" and ra.path == d_atx and "at=" in ra.notice and "ignored" in ra.notice and d_atx.name in ra.notice
            and len(w.dirs()) == n0, "%r %r" % (ra, ra.notice))
        chk("at:without-override-uses-nearest", find_or_create(r / "a/x").path == d_atx)
        chk("at:same-as-folder-when-store-exists-gives-no-notice", find_or_create(r / "a/x", at=r / "a/x").notice == "")

        w.new_stores()
        r5 = w.repo(w.area("atq") / "r", url="https://github.com/o/atq.git")
        (r5 / "p/q").mkdir(parents=True)
        (r5 / "p2/d").mkdir(parents=True)
        rq = find_or_create(r5 / "p/q", at=r5 / "p")
        chk("at:mid-ancestor-without-store-creates-there", made(rq, w) and store_text(rq.path) == "remote github.com/o/atq\npath p\n"
            and rq.path == exp_dir(w, "p", "remote github.com/o/atq", "path p"), repr(rq))
        chk("at:created-store-is-found-from-the-folder", find(r5 / "p/q").path == rq.path and find(r5 / "p").path == rq.path)
        chk("at:created-store-is-not-seen-from-a-sibling", find(r5 / "p2").status == "none")
        n0 = len(w.dirs())
        chk("at:descendant-of-the-folder-is-none-and-creates-nothing",
            find_or_create(r5 / "p2", at=r5 / "p2/d").status == "none" and len(w.dirs()) == n0)
        ru = find_or_create(r5 / "p2", at=r5 / "p")
        chk("at:sibling-folder-is-none-with-pointer-to-memory-rules",
            ru.status == "none" and "the steps for using a parent's store" in ru.reason and "The STORE file" in ru.reason
            and "create the store at the folder itself or at an ancestor within that walk" in ru.reason and len(w.dirs()) == n0, repr(ru))
        other_repo = w.repo(w.area("atother") / "o2", url="https://github.com/o/atother.git")
        chk("at:unrelated-folder-is-none-and-creates-nothing",
            find_or_create(r5 / "p2", at=other_repo).status == "none" and len(w.dirs()) == n0)
        chk("at:above-the-git-toplevel-is-none", find_or_create(r5 / "p2", at=r5.parent).status == "none" and len(w.dirs()) == n0)
        chk("at:missing-folder-is-none", find_or_create(r5 / "p2", at=w.root / "no-such-at").status == "none" and len(w.dirs()) == n0)
        chk("at:non-string-is-failed", find_or_create(r5 / "p2", at=123).status == "failed" and len(w.dirs()) == n0)
        rtop = find_or_create(r5 / "p2", at=r5)
        chk("at:toplevel-without-store-creates-there", made(rtop, w) and store_text(rtop.path) == "remote github.com/o/atq\n"
            and find(r5 / "p2").path == rtop.path, repr(rtop))

        ngroot = w.home / "ngat"
        (ngroot / "a/b").mkdir(parents=True)
        rng_ = find_or_create(ngroot / "a/b", at=ngroot / "a")
        chk("at:non-git-ancestor-creates-local-store-there", made(rng_, w) and store_text(rng_.path) == "local %s\n" % _norm_path(ngroot / "a")
            and find(ngroot / "a/b").path == rng_.path, repr(rng_))
        n0 = len(w.dirs())
        (ngroot / "c").mkdir()
        chk("at:non-git-home-is-none", find_or_create(ngroot / "c", at=w.home).status == "none" and len(w.dirs()) == n0)

        # the no-create roots still apply to `at`: a home folder that is itself a git repo
        hrepo = w.repo(w.area("hrepo") / "h", url="https://github.com/o/hrepo.git")
        (hrepo / "sub").mkdir()
        _TEST["home"] = str(hrepo)
        n0 = len(w.dirs())
        rh = find_or_create(hrepo / "sub", at=hrepo)
        chk("at:no-create-root-still-applies-to-at", rh.status == "none" and "home" in rh.reason and len(w.dirs()) == n0, repr(rh))
        chk("at:home-subfolder-without-at-still-creates", made(find_or_create(hrepo / "sub"), w))
        w.reset_patches()

        # --- config-repo plans carve-out ---
        w.new_stores()
        cfg = w.repo(w.area("cfgrepo") / "agent-playbook", url="https://github.com/example-user/agent-playbook.git")
        (cfg / "memory").mkdir()
        sibling_cfg = w.repo(cfg.parent / "agent-playbook-other", url="https://github.com/example-user/other.git")
        _TEST["config_repo"] = str(cfg)
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "no-such-root")
        rp = find(cfg / "memory", "plans")
        chk("config-repo:plans-need-the-store-repo-like-any-workspace", rp.status == "failed", repr(rp))
        rm = find(cfg, "memory")
        chk("carve-out:memory-kind-uses-store-resolution", rm.status == "failed")
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        rm = find_or_create(cfg, "memory")
        chk("carve-out:memory-kind-creates-store", made(rm, w) and rm.path != cfg, repr(rm))
        rp2 = find_or_create(cfg, "plans")
        chk("config-repo:plans-resolve-to-its-store", rp2.status == "found" and rp2.path == rm.path, repr(rp2))
        rs = find(sibling_cfg, "plans")
        chk("carve-out:sibling-prefix-folder-is-not-config-repo", rs.status == "none", repr(rs))
        _TEST["config_repo"] = ""
        rn = find(cfg, "plans")
        chk("carve-out:disabled-plans-uses-store", rn.status == "found" and rn.path == rm.path)

        # --- non-git folders ---
        w.new_stores()
        par = w.root / "nongit-parent"
        (par / "q/r").mkdir(parents=True)
        d_par = w.store("par-local", "local %s\n" % _norm_path(par))
        chk("non-git:subfolder-reaches-non-git-parent-store", find(par / "q/r").path == d_par)
        chk("non-git:parent-itself", find(par).path == d_par)
        proj = w.home / "proj"
        (proj / "a/b").mkdir(parents=True)
        chk("non-git:folder-under-home-without-store-none", find(proj / "a/b").status == "none")
        d_home = w.store("home-local", "local %s\n" % _norm_path(w.home))
        chk("non-git:child-of-home-does-not-reach-home-store", find(proj).status == "none" and find(proj / "a/b").status == "none")
        chk("non-git:home-itself-finds-home-store", find(w.home).path == d_home)
        rc = find_or_create(proj / "a")
        chk("non-git:creates-local-store-at-session-folder", made(rc, w) and store_text(rc.path) == "local %s\n" % _norm_path(proj / "a")
            and rc.path == exp_dir(w, "a", "local " + _norm_path(proj / "a"), ""), repr(rc))
        chk("non-git:deeper-folder-reaches-new-store", find(proj / "a").path == rc.path)
        (w.home / "proj2").mkdir()
        w.store("proj-local", "local %s\n" % _norm_path(proj))
        chk("non-git:sibling-prefix-folder-does-not-match", find(w.home / "proj2").status == "none")
        chk("non-git:local-match-case-folded", find(Path(str(par / "q/r").upper())).path == d_par)

        # --- no-create roots: both sides of each boundary; every create asserts the STORE exists ---
        w.new_stores()
        (w.systemp / "x/y").mkdir(parents=True)
        (w.root / "systemp2/x").mkdir(parents=True)
        r_in = find_or_create(w.systemp / "x/y")
        chk("no-create:temp-under", r_in.status == "none" and not w.dirs(), repr(r_in))
        chk("no-create:temp-exact", find_or_create(w.systemp).status == "none")
        r_sib = find_or_create(w.root / "systemp2/x")
        chk("no-create:temp-sibling-prefix-creates", made(r_sib, w), repr(r_sib))
        chk("no-create:system-temp-reason-names-temp", "temp" in find_or_create(w.systemp / "x").reason)

        ap = w.home / ".agent-playbook"
        (ap / "dream-work/x").mkdir(parents=True)
        (w.home / ".agent-playbook2/x").mkdir(parents=True)
        chk("no-create:agent-playbook-dream-work", find_or_create(ap / "dream-work/x").status == "none")
        chk("no-create:agent-playbook-exact", find_or_create(ap).status == "none")
        chk("no-create:agent-playbook-sibling-prefix-creates", made(find_or_create(w.home / ".agent-playbook2/x"), w))

        w.new_stores()
        chk("no-create:home-itself", find_or_create(w.home).status == "none" and not w.dirs())
        (w.home / "sub").mkdir(exist_ok=True)
        chk("no-create:home-subfolder-creates", made(find_or_create(w.home / "sub"), w))

        w.new_stores()
        anchor = Path(os.path.splitdrive(str(w.root))[0] + os.sep) if os.name == "nt" else Path("/")
        rr = find_or_create(anchor)
        chk("no-create:drive-root", rr.status == "none" and not w.dirs(), repr(rr))

        (w.home / "Downloads/pkg").mkdir(parents=True)
        (w.home / "Downloads2/pkg").mkdir(parents=True)
        (w.dl / "ring").mkdir(parents=True)
        chk("no-create:downloads-literal", find_or_create(w.home / "Downloads/pkg").status == "none")
        chk("no-create:downloads-sibling-prefix-creates", made(find_or_create(w.home / "Downloads2/pkg"), w))
        chk("no-create:downloads-redirected-known-folder", find_or_create(w.dl / "ring").status == "none" and find_or_create(w.dl).status == "none")
        chk("no-create:downloads-known-folder-parent-creates", made(find_or_create(w.dl.parent), w))

        wt_repo = w.repo(w.area("wtr") / "r", url="https://github.com/o/wtr.git")
        (wt_repo / ".claude/worktrees/agent-1").mkdir(parents=True)
        (wt_repo / ".claude/worktreesX/y").mkdir(parents=True)
        (wt_repo / ".claude/other").mkdir(parents=True)
        w.new_stores()
        chk("no-create:claude-worktrees-under", find_or_create(wt_repo / ".claude/worktrees/agent-1").status == "none" and not w.dirs())
        chk("no-create:claude-worktrees-exact", find_or_create(wt_repo / ".claude/worktrees").status == "none")
        chk("no-create:claude-worktreesX-creates", made(find_or_create(wt_repo / ".claude/worktreesX/y"), w))
        chk("no-create:claude-other-creates", made(find_or_create(wt_repo / ".claude/other"), w))

        # the real system temp directory and its 8.3 form, without the override
        _TEST.pop("temp", None)
        real_tmp = Path(tempfile.gettempdir())
        probe = real_tmp / ("srst-real-%d" % os.getpid())
        probe.mkdir(exist_ok=True)
        try:
            w.new_stores()
            chk("no-create:real-system-temp-folder", find_or_create(probe).status == "none" and not w.dirs())
            chk("no-create:fixture-root-is-under-real-temp-so-override-is-needed", bool(_no_create_reason(_norm_path(w.root))))
            chk("no-create:real-temp-is-expanded-to-long-form", all("~" not in t for t in _temp_dirs()) or os.name != "nt")
        finally:
            shutil.rmtree(str(probe), ignore_errors=True)
        w.reset_patches()
        if os.name == "nt":
            import ctypes
            longdir = w.root / "a fairly long directory name for short names"
            (longdir / "child").mkdir(parents=True)
            gs = ctypes.WinDLL("kernel32").GetShortPathNameW
            gs.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            gs.restype = ctypes.c_uint
            buf = ctypes.create_unicode_buffer(1024)
            n = gs(str(longdir), buf, 1024)
            short = buf.value if n else ""
            if short and short.lower() != str(longdir).lower():
                _TEST["temp"] = [str(longdir)]
                w.new_stores()
                chk("no-create:8.3-temp-path", find_or_create(Path(short) / "child").status == "none" and not w.dirs())
                chk("normalize:8.3-expands-to-long-form", _norm_path(short + "\\child") == _norm_path(longdir / "child"))
                w.reset_patches()
            else:
                skip("no-create:8.3-temp-path", "8.3 names unavailable on this volume")
            kd = _known_downloads()
            _TEST.pop("downloads", None)
            _TEST.pop("home", None)
            if kd:
                chk("no-create:windows-known-folder-real-api", bool(_no_create_reason(_norm_path(Path(kd) / "x"))), kd)
            else:
                skip("no-create:windows-known-folder-real-api", "SHGetKnownFolderPath unavailable")
            chk("no-create:literal-downloads-real-home", bool(_no_create_reason(_norm_path(Path(os.path.expanduser("~")) / "Downloads" / "x"))))
            w.reset_patches()
        else:
            skip("no-create:8.3-temp-path", "not Windows")

        # --- 8.3 input path resolves to the same identity and store as the long form ---
        if os.name == "nt":
            raw_short = Path(raw_root)
            if str(raw_short).lower() != str(w.root).lower():
                w.new_stores()
                rl = w.repo(w.root / "shortcase", url=None)
                a1 = identity(rl).path
                rel = Path(raw_short) / "shortcase"
                a2 = identity(rel).path
                chk("path:8.3-and-long-form-same-local-identity", a1 is not None and a2 is not None and id_key(a1) == id_key(a2), "%r %r" % (a1, a2))
            else:
                skip("path:8.3-and-long-form-same-local-identity", "temp dir is already in long form")

        # --- linked worktree, submodule, worktreeConfig ---
        w.new_stores()
        mainrepo = w.repo(w.area("wt") / "mainrepo", url="https://github.com/o/main-repo.git",
                      extra="[extensions]\n\tworktreeConfig = true\n")
        (mainrepo / ".git" / "config.worktree").write_text('[remote "origin"]\n\turl = https://evil.example/o/hijack.git\n', encoding="utf-8")
        wtmeta = mainrepo / ".git" / "worktrees" / "wt1"
        wtmeta.mkdir(parents=True)
        (wtmeta / "HEAD").write_text("ref: refs/heads/wt1\n", encoding="utf-8")
        (wtmeta / "commondir").write_text("../..\n", encoding="utf-8")
        (wtmeta / "config.worktree").write_text('[remote "origin"]\n\turl = https://evil.example/o/hijack2.git\n', encoding="utf-8")
        wt = w.root / "wt-checkout"
        (wt / "sub").mkdir(parents=True)
        (wt / ".git").write_text("gitdir: %s\n" % wtmeta, encoding="utf-8")
        iw = identity(wt).path
        chk("worktree:resolves-through-commondir-to-mainrepo-identity", iw.kind == "remote" and iw.value == "github.com/o/main-repo" and iw.subpath == "", repr(iw))
        chk("worktree:config-worktree-ignored", "evil" not in iw.value and "hijack" not in iw.value)
        chk("worktree:subfolder-subpath", identity(wt / "sub").path.subpath == "sub")
        im = identity(mainrepo).path
        d_main = w.store("mainrepo-top", "remote github.com/o/main-repo\n")
        chk("worktree:finds-main-repo-toplevel-store", im.value == iw.value and find(wt / "sub").path == d_main)
        wt_rel = w.root / "wt-rel"
        wt_rel.mkdir()
        (wt_rel / ".git").write_text("gitdir: %s\n" % os.path.relpath(str(wtmeta), str(wt_rel)), encoding="utf-8")
        chk("worktree:relative-gitdir", identity(wt_rel).path.value == "github.com/o/main-repo")
        wt_bad = w.root / "wt-dangling"
        wt_bad.mkdir()
        (wt_bad / ".git").write_text("gitdir: %s\n" % (w.root / "gone" / "worktrees" / "x"), encoding="utf-8")
        n0 = len(w.dirs())
        rb = find_or_create(wt_bad)
        chk("worktree:dangling-gitdir-failed-and-nothing-created", rb.status == "failed" and len(w.dirs()) == n0, repr(rb))

        parent = w.repo(w.area("smod") / "parent", url="https://github.com/o/parent.git")
        sm_meta = parent / ".git" / "modules" / "subm"
        git_skeleton(sm_meta)
        (sm_meta / "config").write_text('[core]\n\tworktree = ../../../subm\n[remote "origin"]\n\turl = https://github.com/o/child.git\n', encoding="utf-8")
        (parent / "subm").mkdir()
        (parent / "subm" / ".git").write_text("gitdir: ../.git/modules/subm\n", encoding="utf-8")
        (parent / "subm" / "lib").mkdir()
        (parent / "other").mkdir()
        isb = identity(parent / "subm" / "lib").path
        chk("submodule:own-remote-and-subpath", isb.value == "github.com/o/child" and isb.subpath == "lib", repr(isb))
        chk("submodule:parent-folder-keeps-parent-identity", identity(parent / "other").path.value == "github.com/o/parent"
            and identity(parent / "other").path.subpath == "other")
        d_par2 = w.store("parent-top", "remote github.com/o/parent\n")
        chk("submodule:walk-does-not-leave-submodule", find(parent / "subm" / "lib").status == "none" and find(parent / "other").path == d_par2)

        # --- filesystem-path remote counts as no remote ---
        w.new_stores()
        ln = w.repo(w.area("ln") / "github-source", url="C:/Users/alice/Documents/src/demo-app")
        iln = identity(ln).path
        chk("filesystem-remote:local-identity-of-folder", iln.kind == "local" and iln.value == _norm_path(ln), repr(iln))
        rln = find_or_create(ln)
        chk("filesystem-remote:store-is-local", made(rln, w) and store_text(rln.path) == "local %s\n" % _norm_path(ln))

        # --- creation race ---
        for rnd in range(3):
            w.new_stores()
            rc = w.repo(w.area("race") / "r", url="https://github.com/o/race%d.git" % rnd)
            outs, bar = [], threading.Barrier(8)

            def worker():
                bar.wait()
                outs.append(find_or_create(rc))
            ths = [threading.Thread(target=worker) for _ in range(8)]
            for t in ths:
                t.start()
            for t in ths:
                t.join()
            paths = {str(o.path) for o in outs}
            ncreated = sum(1 for o in outs if o.status == "created")
            leftovers = [p for p in os.listdir(str(w.stores / w.dirs()[0])) if p != "STORE"] if w.dirs() else ["?"]
            chk("race:round%d-one-store-one-creator-same-path" % rnd, len(w.dirs()) == 1 and len(paths) == 1 and ncreated == 1
                and all(o.status in ("created", "found") for o in outs) and not leftovers, "%s %s %s" % (w.dirs(), ncreated, leftovers))

        # --- empty (in-progress) and malformed STORE ---
        EMPTY_WAIT_SECONDS = 0.6
        w.new_stores()
        rc = w.repo(w.area("emp") / "r", url="https://github.com/o/empty.git")
        target = exp_dir(w, "r", "remote github.com/o/empty", "")
        target.mkdir()
        (target / "STORE").write_bytes(b"")
        threading.Timer(0.2, lambda: (target / "STORE").write_bytes(b"remote github.com/o/empty\n")).start()
        t0 = time.monotonic()
        rf = find(rc)
        chk("empty-store:find-waits-and-then-finds", rf.status == "found" and rf.path == target and time.monotonic() - t0 >= 0.15, repr(rf))
        w.new_stores()
        target = exp_dir(w, "r", "remote github.com/o/empty", "")
        target.mkdir()
        (target / "STORE").write_bytes(b"")
        rn = find(rc)
        chk("empty-store:abandoned-is-skipped-by-find", rn.status == "none", repr(rn))
        rf = find_or_create(rc)
        chk("empty-store:abandoned-blocks-creation-and-is-not-overwritten", rf.status == "failed" and (target / "STORE").read_bytes() == b"" and len(w.dirs()) == 1, repr(rf))
        EMPTY_WAIT_SECONDS = saved_wait

        w.new_stores()
        good = w.store("good-1", "remote github.com/o/good\n")
        for nm, body in (("bad-word", "bogus github.com/x\n"), ("bad-three", "remote a/b\npath c\nextra\n"), ("bad-local-path", "local c:/x\npath y\n"),
                         ("bad-path-first", "path y\nremote a/b\n"), ("bad-no-value", "remote \n"), ("bad-binary", "\x00\x01 garbage")):
            w.store(nm, body)
        (w.stores / "no-store-file").mkdir()
        gr = w.repo(w.area("mal") / "r", url="https://github.com/o/good.git")
        chk("malformed-store:valid-store-still-found", find(gr).path == good, repr(find(gr)))
        st, valid, invalid, why = scan_stores()
        chk("malformed-store:scan-lists-invalid-ones", st == "ok" and len(valid) == 1 and len(invalid) == 7
            and {d.name for d, _ in invalid} == {"bad-word", "bad-three", "bad-local-path", "bad-path-first", "bad-no-value", "bad-binary", "no-store-file"}, repr(invalid))
        chk("malformed-store:iter-stores-yields-valid-only", [d.name for d, _ in scan_stores()[1]] == ["good-1"])
        for body, ok in (("remote github.com/o/r\n", True), ("remote github.com/o/r\r\npath a/b\r\n", True), ("local c:/a b/c\n", True),
                         ("\ufeffremote github.com/o/r\n", True), ("remote github.com/o/r\n\n\n", True), ("local c:/a\npath b\n", False),
                         ("remote x/y\npath \n", False), ("", False)):
            ident, _ = _parse_store_text(body.lstrip("\ufeff")) if body else (None, "")
            chk("store-grammar:%r" % body[:30], (ident is not None) == ok)
        w.store("bom-1", "\ufeffremote github.com/o/bom\n")
        bom_repo = w.repo(w.area("bom") / "r", url="https://github.com/o/bom.git")
        chk("store-grammar:bom-prefixed-STORE-is-read", find(bom_repo).path == w.stores / "bom-1")

        # --- missing root, root without .git ---
        mr = w.repo(w.area("mr") / "r", url="https://github.com/o/mr.git")
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "never-created")
        for label, fn in (("find", find), ("find-or-create", find_or_create), ("would-create", would_create_path)):
            res = fn(mr)
            chk("missing-root:%s-failed-with-clone-notice" % label, res.status == "failed" and "clone it" in res.reason, repr(res))
        chk("missing-root:not-created", not (w.root / "never-created").exists())
        nogit = w.root / "root-no-git"
        nogit.mkdir()
        os.environ["AGENT_PLAYBOOK_STORES"] = str(nogit)
        rg = find_or_create(mr)
        chk("missing-root:without-dot-git-failed-and-nothing-written", rg.status == "failed" and not any(nogit.iterdir()), repr(rg))
        w.new_stores()

        # --- unreadable .git/config: failed, nothing created ---
        ur = w.area("unread") / "r"
        git_skeleton(ur / ".git")
        (ur / ".git" / "config").mkdir()
        n0 = len(w.dirs())
        ru = find_or_create(ur)
        chk("unreadable-config:failed-nothing-created", ru.status == "failed" and len(w.dirs()) == n0 and find(ur).status == "failed", repr(ru))

        # --- no duplicate store on a failed scan ---
        w.new_stores()
        nd = w.repo(w.area("nodup") / "r", url="https://github.com/o/nodup.git")
        bad = w.stores / "unreadable-1"
        (bad / "STORE").mkdir(parents=True)
        n0 = len(w.dirs())
        rnd_ = find_or_create(nd)
        chk("no-duplicate-on-failure:failed-status", rnd_.status == "failed", repr(rnd_))
        chk("no-duplicate-on-failure:nothing-created", len(w.dirs()) == n0 == 1)
        chk("no-duplicate-on-failure:would-create-also-failed", would_create_path(nd).status == "failed")

        # --- reads write nothing ---
        w.new_stores()
        rr = w.repo(w.area("ro") / "r", url="https://github.com/o/ro.git")
        (rr / "a").mkdir()
        w.store("ro-a", "remote github.com/o/ro\npath a\n")
        w.store("ro-bad", "junk\n")
        snap0 = w.snapshot()
        find(rr)
        find(rr / "a")
        would_create_path(rr)
        would_create_path(rr / "a")
        identity(rr)
        scan_stores()
        find(w.systemp)
        chk("read-only:find-would-create-scan-write-nothing", w.snapshot() == snap0)

        # --- would_create_path predicts find_or_create ---
        w.new_stores()
        wr = w.repo(w.area("wcp") / "r", url="https://github.com/o/wcp.git")
        (wr / "n").mkdir()
        pred = would_create_path(wr / "n")
        real = find_or_create(wr / "n")
        chk("would-create:predicts-created-path", pred.status == "created" and real.status == "created" and pred.path == real.path, "%r %r" % (pred, real))
        again = would_create_path(wr / "n")
        chk("would-create:after-creation-reports-found", again.status == "found" and again.path == real.path)
        chk("would-create:no-create-root-none", would_create_path(w.systemp).status == "none")

        # --- hash collision extension only when identities differ ---
        w.new_stores()
        cr = w.repo(w.area("col") / "r", url="https://github.com/o/col.git")
        d6 = exp_dir(w, "r", "remote github.com/o/col", "")
        w.store(d6.name, "remote github.com/o/someone-else\n")
        full = hashlib.sha256(b"remote github.com/o/col\n").hexdigest()
        want8 = w.stores / ("r-" + full[:8])
        pc = would_create_path(cr)
        chk("collision:extends-by-two-hex-chars-when-identity-differs", pc.status == "created" and pc.path == want8, repr(pc))
        rc = find_or_create(cr)
        chk("collision:creation-uses-extended-name", made(rc, w) and rc.path == want8)
        chk("collision:original-store-untouched", store_text(d6) == "remote github.com/o/someone-else\n")
        chk("collision:same-identity-is-a-hit", find_or_create(cr).path == want8 and len(w.dirs()) == 2)

        # --- near-match notice ---
        w.new_stores()
        ra_ = w.repo(w.area("nm1") / "r", url="https://github.com/o/one.git")
        rb_ = w.repo(w.area("nm2") / "r", url="https://github.com/o/two.git")
        first = find_or_create(ra_)
        chk("near-match:no-notice-when-alone", first.status == "created" and first.notice == "")
        second = find_or_create(rb_)
        chk("near-match:notice-names-existing-store", second.status == "created" and first.path.name in second.notice and "different identity" in second.notice, repr(second.notice))

        # --- create() for the migration ---
        w.new_stores()
        cm = w.repo(w.area("mig") / "mono", url="https://github.com/o/mig.git")
        c1 = create(cm, "support/TeamA/gamma")
        chk("create:explicit-subpath", c1.status == "created" and store_text(c1.path) == "remote github.com/o/mig\npath support/TeamA/gamma\n"
            and c1.path == exp_dir(w, "gamma", "remote github.com/o/mig", "path support/teama/gamma"), repr(c1))
        chk("create:second-call-is-a-hit", create(cm, "Support/TeamA/Gamma").status == "found" and len(w.dirs()) == 1)
        c3 = create(cm)
        chk("create:no-subpath-uses-folder", c3.status == "created" and store_text(c3.path) == "remote github.com/o/mig\n")
        dl_repo = w.repo(w.dl / "ring2")
        c4 = create(dl_repo)
        chk("create:bypasses-no-create-roots-for-migration", made(c4, w) and store_text(c4.path) == "local %s\n" % _norm_path(dl_repo), repr(c4))

        # --- untrusted roots (system temp, Downloads): a .git there cannot claim another workspace's store ---
        w.new_stores()
        victim = w.repo(w.area("victim") / "proj", url="https://github.com/o/victim.git")
        d_victim = w.store("victim-1", "remote github.com/o/victim\n")
        chk("untrusted:victim-resolves-normally", find(victim).path == d_victim)
        fake = w.repo(w.dl / "fake", url="https://github.com/o/victim.git")
        chk("untrusted:downloads-repo-claiming-a-remote-is-none", find(fake).status == "none", repr(find(fake)))
        chk("untrusted:downloads-repo-reads-no-store-memory", resolve_artifact(fake, "memory").store is None)
        (d_victim / "memory").mkdir(parents=True, exist_ok=True)
        (d_victim / "memory" / "MEMORY.md").write_text("# m\n", encoding="utf-8")
        chk("untrusted:downloads-repo-resolve-is-not-the-victim", resolve_artifact(fake, "memory").source != "store-repo")
        tmpfake = w.repo(w.systemp / "fake", url="https://github.com/o/victim.git")
        chk("untrusted:temp-repo-claiming-a-remote-is-none", find(tmpfake).status == "none")
        gd = w.dl / "gitdir-fake"
        gd.mkdir(parents=True)
        (gd / ".git").write_text("gitdir: %s\n" % (victim / ".git"), encoding="utf-8")
        chk("untrusted:downloads-gitdir-file-to-another-repo-is-none", find(gd).status == "none", repr(find(gd)))
        sp = w.repo(w.dl / "spoof-with-memory", url="https://github.com/o/victim.git")
        (sp / "memory").mkdir()
        (sp / "memory" / "MEMORY.md").write_text("# m\n", encoding="utf-8")
        chk("untrusted:fallback-reads-the-folder-not-the-claimed-store", folder_fallback(sp, "memory") == sp / "memory",
            repr(folder_fallback(sp, "memory")))
        chk("untrusted:none-names-the-untrusted-root", "untrusted root" in resolve_artifact(sp, "memory").reason)
        dev = "\\\\.\\" + str(fake)
        chk("untrusted:device-prefix-is-the-same-path", find(dev).status == "none" and would_create_path(dev).status == "none",
            repr((find(dev), would_create_path(dev))))
        own = w.dl / "own"
        own.mkdir(parents=True)
        d_own = w.store("own-1", "local %s\n" % _norm_path(own))
        chk("untrusted:local-store-keyed-to-the-downloads-folder-still-serves-it", find(own).path == d_own)

        # --- the one-line state key splits on the last " path " (an Azure project name may hold the word) ---
        az1 = w.store("repo-1", "remote dev.azure.com/org/critical path tools/repo\n")
        az2 = w.store("x-1", "remote dev.azure.com/org/critical path tools/repo\npath support/x\n")
        az3 = w.store("b-1", "remote github.com/o/r\npath a path b\n")
        sv = scan_stores()[1]
        chk("store-key:text-round-trips", all(store_for_key(store_key(i), sv) == d for d, i in sv), repr(sv))
        chk("store-key:path-word-in-remote-without-subpath", store_for_key("remote dev.azure.com/org/critical path tools/repo", sv) == az1)
        chk("store-key:path-word-in-remote-with-subpath", store_for_key("Remote dev.azure.com/org/Critical Path Tools/repo path support/X".replace("Remote", "remote"), sv) == az2)
        chk("store-key:path-word-in-subpath", store_for_key("remote github.com/o/r path a path b", sv) == az3)
        chk("store-key:unknown-key-is-none", store_for_key("remote github.com/o/none", sv) is None)
        cands = [(c.value, c.subpath) for c in _key_split_candidates("remote h/o/r path a path b")]
        chk("store-key:every-split-is-a-candidate", cands == [("h/o/r path a path b", ""), ("h/o/r", "a path b"), ("h/o/r path a", "b")], repr(cands))

        # --- kind validation and never-raises ---
        chk("kind:unknown-kind-failed", find(cm, "bogus").status == "failed" and find_or_create(cm, "bogus").status == "failed")
        odd = [None, 123, "\x00bad", "", "x" * 5000, b"bytes", w.root / "does" / "not" / "exist", "//", "C:", "\\\\?\\C:\\nope"]
        okr = True
        for item in odd:
            for fn in (find, find_or_create, would_create_path, identity):
                try:
                    res = fn(item)
                    okr = okr and isinstance(res, tuple) and len(res) == 2 and res[0] in STATUSES
                except Exception as exc:
                    okr = False
                    print("  raised %s for %r by %s" % (exc, item, fn.__name__))
        chk("never-raises:odd-inputs-return-results", okr)
        chk("never-raises:missing-folder-resolves-lexically", find(w.root / "ghost" / "dir").status in ("none", "found"))
        chk("result:unpacks-as-two-tuple", (lambda s, p: s == "none")(*find(w.systemp)))

        # --- golden directory names: literals derived with an independent hashlib one-liner, never by this module ---
        w.new_stores()
        gold = w.repo(w.area("gold") / "r", url="https://github.com/o/golden.git")
        g_sub = gold / "support/TeamA/Beta Lab"
        g_long = gold / "ops/AbcdefGHIJ_klmnopqrst.uvwxyz0123456789-ABCDE-xyz"
        g_sub.mkdir(parents=True)
        g_long.mkdir(parents=True)
        gs_, gl_, gt_ = find_or_create(g_sub), find_or_create(g_long), find_or_create(gold)
        chk("naming-golden:mixed-case-subpath-and-space", made(gs_, w) and gs_.path.name == "Beta-Lab-787bcc"
            and store_text(gs_.path) == "remote github.com/o/golden\npath support/TeamA/Beta Lab\n", repr(gs_))
        chk("naming-golden:40-character-basename-cap", made(gl_, w) and gl_.path.name == "AbcdefGHIJ-klmnopqrst-uvwxyz0123456789-A-4ad080", repr(gl_))
        chk("naming-golden:empty-subpath", made(gt_, w) and gt_.path.name == "r-8deb21", repr(gt_))

        # --- identity comparison: same_identity, not == ---
        w.new_stores()
        sr_ = w.repo(w.area("same") / "r", url="https://github.com/o/Same.git")
        cr_ = find_or_create(sr_)
        entry = [i for d_, i in scan_stores()[1] if d_ == cr_.path]
        ident_ = identity(sr_).path
        chk("same-identity:folder-identity-and-store-entry-are-the-same-identity", len(entry) == 1 and same_identity(ident_, entry[0]))
        chk("same-identity:the-two-tuples-differ-under-equals", len(entry) == 1 and ident_ != entry[0])
        chk("same-identity:case-is-folded", same_identity(ident_, Identity("remote", "GitHub.com/O/SAME", "", None, None)))
        chk("same-identity:subpath-kind-and-value-matter", not same_identity(ident_, Identity("remote", ident_.value, "x", None, None))
            and not same_identity(ident_, Identity("local", ident_.value, "", None, None))
            and not same_identity(ident_, Identity("remote", "github.com/o/other", "", None, None)))
        chk("same-identity:none-is-never-the-same", not same_identity(None, ident_) and not same_identity(ident_, None) and not same_identity(None, None))
        # normalize_remote is public since plan 261016 Step 9: verify-stores compares the store repo's origin with
        # the README's URL through it; store_key and store_for_key look a `store:` state key up by its text.
        chk("surface:internal-helpers-are-underscored", all(n not in globals() for n in
            ("parse_store_text", "no_create_reason", "stores_root")) and "same_identity" in globals()
            and all(callable(globals().get(n)) for n in ("norm_path", "is_under", "store_text", "parse_store_key", "folder_fallback",
                                                         "normalize_remote", "store_key", "store_for_key"))
            and "scan_stores" in globals())

        # --- config-repo carve-out from a copy of this module outside the repo (the Kiro deploy) ---
        w.new_stores()
        cfg2 = w.repo(w.area("cfgcopy") / "agent-playbook", url="https://github.com/example-user/agent-playbook.git")
        (cfg2 / "shared" / "skills" / "qdream" / "scripts").mkdir(parents=True)
        (cfg2 / "shared" / "AGENTS.md").write_text("x\n", encoding="utf-8")
        (cfg2 / "shared" / "skills" / "qdream" / "scripts" / "store-resolver.py").write_text("# marker\n", encoding="utf-8")
        (cfg2 / "plans" / "done").mkdir(parents=True)
        decoy = w.repo(w.area("decoy") / "r", url="https://github.com/o/decoy.git")
        (decoy / "shared").mkdir()
        (decoy / "shared" / "AGENTS.md").write_text("x\n", encoding="utf-8")
        copydir = w.root / "modcopy"
        copydir.mkdir()
        shutil.copy(__file__, str(copydir / "store-resolver.py"))
        spec = importlib.util.spec_from_file_location("sr_copy", str(copydir / "store-resolver.py"))
        mcopy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mcopy)
        chk("carve-out:copy-has-no-test-override", "config_repo" not in mcopy._TEST)
        rcp = mcopy.find(cfg2 / "plans" / "done", "plans")
        chk("config-repo:copy-outside-the-repo-resolves-plans-like-any-repo", rcp.status != "found" or rcp.path != cfg2, repr(rcp))
        chk("carve-out:copy-other-kinds-use-store-resolution", mcopy.find(cfg2, "memory").status == "none")
        chk("carve-out:copy-repo-with-only-shared-agents-md-is-not-the-config-repo", mcopy.find(decoy, "plans").status == "none")

        # --- error branches that used to be unpinned ---
        w.new_stores()
        n0 = len(w.dirs())
        gf = w.area("gitfile")
        (gf / ".git").write_text("gitdir: ../elsewhere\n", encoding="utf-8")
        with flaky_open(w.root, gf / ".git", 99):
            e1, e2 = find_or_create(gf), identity(gf)
        chk("error-branch:unreadable-dot-git-file-failed-nothing-created",
            e1.status == "failed" and e2.status == "failed" and "cannot read git metadata" in e1.reason and len(w.dirs()) == n0, repr(e1))
        prb = w.area("probe")
        real_lstat = os.lstat
        want_tail = (prb / ".git").relative_to(w.root).as_posix().lower()

        def bad_lstat(path, *a, **k):
            if str(path).replace("\\", "/").lower().endswith(want_tail):
                raise PermissionError(13, "denied (selftest)")
            return real_lstat(path, *a, **k)
        os.lstat = bad_lstat
        try:
            e3, e4 = find_or_create(prb), find(prb)
        finally:
            os.lstat = real_lstat
        chk("error-branch:probe-error-failed-nothing-created",
            e3.status == "failed" and e4.status == "failed" and "cannot probe" in e3.reason and len(w.dirs()) == n0, repr(e3))
        nc = w.area("noconf")
        git_skeleton(nc / ".git")
        e5 = find_or_create(nc)
        chk("git-dir-without-config:failed-not-local-nothing-created",
            e5.status == "failed" and "no config" in e5.reason and identity(nc).status == "failed" and len(w.dirs()) == n0, repr(e5))
        # --- repository discovery follows git's is_git_directory rule ---
        # Expected values come from `git rev-parse --show-toplevel` (git 2.50.1) run on trees of these shapes, not from this
        # module: only a .git directory with a valid HEAD plus objects/ and refs/ is a repository. Any other .git directory is
        # skipped as if absent, so a non-git folder is `local` and a folder inside a repo takes that repo's identity.
        w.new_stores()
        g0 = len(w.dirs())
        solo = w.area("solo")
        encl = w.repo(w.area("encl") / "E", url="https://github.com/o/encl.git")
        not_repo = (
            ("objonly", dict(head=None, refs=False)),          # a real-world shape: a lone objects/
            ("headonly", dict(objects=False, refs=False)),
            ("headobj", dict(refs=False)),
            ("headrefs", dict(objects=False)),
            ("emptygit", dict(head=None, objects=False, refs=False)),
            ("nohead", dict(head=None)),                        # objects/ and refs/ present, HEAD absent
            ("garbagehead", dict(head="garbage here\n")),
            ("shorthex", dict(head="abc123\n")),
            ("badref", dict(head="ref: heads/main\n")),
            ("headdir", dict(head=None)),                       # HEAD is a directory (made below)
        )
        bad_solo, bad_encl = [], []
        for nm, kw in not_repo:
            for base, rel in ((solo, Path(nm)), (encl, Path("x") / nm)):
                gd = git_skeleton(base / rel / ".git", **kw)
                if nm == "headdir":
                    (gd / "HEAD").mkdir()
                (base / rel / "deep").mkdir()
            f = solo / nm
            want = str(f).replace("\\", "/").casefold()
            li, ld = identity(f), identity(f / "deep")
            if not (li.status == "found" and (li.path.kind, li.path.value, li.path.subpath) == ("local", want, "")
                    and ld.status == "found" and (ld.path.kind, ld.path.value) == ("local", want + "/deep")):
                bad_solo.append((nm, li, ld))
            ei, ed = identity(encl / "x" / nm), identity(encl / "x" / nm / "deep")
            if not (ei.status == "found" and (ei.path.kind, ei.path.value, ei.path.subpath) == ("remote", "github.com/o/encl", "x/" + nm)
                    and ed.status == "found" and (ed.path.kind, ed.path.value, ed.path.subpath) == ("remote", "github.com/o/encl", "x/%s/deep" % nm)):
                bad_encl.append((nm, ei, ed))
        chk("git-discovery:non-git-dot-git-dir-outside-a-repo-is-local-identity", not bad_solo, repr(bad_solo[:2]))
        chk("git-discovery:non-git-dot-git-dir-inside-a-repo-takes-the-enclosing-repo-identity-and-subpath", not bad_encl, repr(bad_encl[:2]))
        lone = solo / "objonly"
        r_lone = find_or_create(lone)
        chk("git-discovery:lone-objects-dir-folder-gets-a-local-store",
            made(r_lone, w) and store_text(r_lone.path) == "local %s\n" % str(lone).replace("\\", "/").casefold()
            and find(lone / "deep").path == r_lone.path and len(w.dirs()) == g0 + 1, repr(r_lone))
        # A real git dir passes the test, whatever its HEAD looks like, as long as git accepts it (here a full object id).
        hexhead = git_skeleton(encl / "x" / "hexhead" / ".git", head="0123456789abcdef0123456789abcdef01234567\n")
        (hexhead / "config").write_text('[remote "origin"]\n\turl = https://github.com/o/inner.git\n', encoding="utf-8")
        ih = identity(encl / "x" / "hexhead")
        chk("git-discovery:detached-hex-head-git-dir-is-its-own-repo",
            ih.status == "found" and (ih.path.kind, ih.path.value, ih.path.subpath) == ("remote", "github.com/o/inner", ""), repr(ih))
        # Boundary: HEAD, objects/ and refs/ all present but no config is a repo with unreadable remote: failed, nothing created.
        g1 = len(w.dirs())
        fulls = []
        for base in (solo, encl / "x"):
            git_skeleton(base / "fullnocfg" / ".git")
            fulls.append((find_or_create(base / "fullnocfg"), identity(base / "fullnocfg"), find(base / "fullnocfg")))
        chk("git-discovery:full-git-dir-without-config-is-failed-not-skipped-nothing-created",
            all(x.status == "failed" and "no config" in x.reason for t in fulls for x in t) and len(w.dirs()) == g1, repr(fulls[0]))
        # A .git file naming a directory that is not a git directory is fatal in git ("not a git repository"): failed here too.
        gfs = []
        for nm, kw in (("gfempty", dict(head=None, objects=False, refs=False)), ("gfheadonly", dict(objects=False, refs=False))):
            tgt = git_skeleton(w.root / ("tgt-" + nm), **kw)
            gfo = w.area(nm)
            (gfo / ".git").write_text("gitdir: %s\n" % tgt, encoding="utf-8")
            gfs.append((nm, find_or_create(gfo), identity(gfo)))
        cm_meta = w.area("cmmeta")
        (cm_meta / "HEAD").write_text("ref: refs/heads/x\n", encoding="utf-8")
        (cm_meta / "commondir").write_text("%s\n" % git_skeleton(w.root / "tgt-bare", head=None, objects=False, refs=False), encoding="utf-8")
        cm_wt = w.area("cmwt")
        (cm_wt / ".git").write_text("gitdir: %s\n" % cm_meta, encoding="utf-8")
        gfs.append(("commondir-not-git", find_or_create(cm_wt), identity(cm_wt)))
        chk("git-discovery:gitfile-or-commondir-target-that-is-not-a-git-dir-is-failed-nothing-created",
            all(a.status == "failed" and b.status == "failed" and "not a git directory" in a.reason for _n, a, b in gfs)
            and len(w.dirs()) == g1, repr(gfs))
        w.new_stores()  # later cases compare against the store count of the original, empty store repo
        wsl = w.area("wsl")
        (wsl / ".git").write_text("gitdir: /mnt/c/Users/x/repo/.git/worktrees/w1\n", encoding="utf-8")
        chk("wsl-gitdir:failed-nothing-created", find_or_create(wsl).status == "failed" and len(w.dirs()) == n0)

        # --- transient read errors: retried 3 times, then failed ---
        tr = w.repo(w.area("trans") / "r", url="https://github.com/o/trans.git")
        t0 = time.monotonic()
        with flaky_open(w.root, tr / ".git" / "config", 3) as st3:
            i3 = identity(tr)
        with flaky_open(w.root, tr / ".git" / "config", 4) as st4:
            i4 = identity(tr)
        dt = time.monotonic() - t0
        chk("transient-read:three-failures-then-success-is-found", i3.status == "found" and i3.path.value == "github.com/o/trans" and st3["n"] == 3, repr(i3))
        chk("transient-read:four-failures-is-failed", i4.status == "failed" and st4["n"] == 4, repr(i4))
        chk("transient-read:bounded-well-under-the-hook-cap", dt < 1.0, "%.2f s" % dt)
        d_tr = w.store("trans-1", "remote github.com/o/trans\n")
        with flaky_open(w.root, d_tr / "STORE", 2) as st2:
            rs_ = find(tr)
        chk("transient-read:store-two-failures-then-found", rs_.status == "found" and rs_.path == d_tr and st2["n"] == 2, repr(rs_))
        with flaky_open(w.root, d_tr / "STORE", 99):
            rs2 = find_or_create(tr)
        chk("transient-read:store-persistent-failure-failed-nothing-created", rs2.status == "failed" and len(w.dirs()) == n0 + 1, repr(rs2))

        # --- publish: temp file cleaned up, fsync before publish, stale temp files removed in the store directory only ---
        w.new_stores()
        pc_ = w.repo(w.area("pub") / "r", url="https://github.com/o/pub.git")
        tdir = would_create_path(pc_).path
        tdir.mkdir()
        old_tmp, new_tmp, keep = tdir / "STORE.tmp-stale-1", tdir / "STORE.tmp-live-1", tdir / "notes.txt"
        other_d = w.store("pub-other", "remote github.com/o/pubother\n")
        other_tmp = other_d / "STORE.tmp-stale-2"
        for f_ in (old_tmp, new_tmp, keep, other_tmp):
            f_.write_text("x", encoding="utf-8")
        long_ago = time.time() - 600
        for f_ in (old_tmp, keep, other_tmp):
            os.utime(str(f_), (long_ago, long_ago))
        rp_ = find_or_create(pc_)
        chk("publish-cleanup:stale-tmp-removed-in-the-store-directory-only", made(rp_, w) and rp_.path == tdir and not old_tmp.exists()
            and new_tmp.exists() and keep.exists() and other_tmp.exists(), repr(rp_))
        fs_repo = w.repo(w.area("fsync") / "r", url="https://github.com/o/fsync.git")
        real_fsync, fs_calls = os.fsync, []

        def counting_fsync(fd):
            fs_calls.append(fd)
            return real_fsync(fd)
        os.fsync = counting_fsync
        try:
            rfs = find_or_create(fs_repo)
        finally:
            os.fsync = real_fsync
        chk("publish:temp-file-is-fsynced-before-publish", made(rfs, w) and len(fs_calls) >= 1, repr(rfs))
        fs2 = w.repo(w.area("fsync2") / "r", url="https://github.com/o/fsync2.git")

        def failing_fsync(fd):
            raise OSError(28, "disk full (selftest)")
        os.fsync = failing_fsync
        try:
            rff = find_or_create(fs2)
        finally:
            os.fsync = real_fsync
        left = sorted(n_ for dp, _dn, fn in os.walk(str(w.stores)) if os.sep + ".git" not in dp + os.sep for n_ in fn if n_.startswith("STORE"))
        chk("publish-cleanup:failed-write-leaves-no-temp-file-and-no-STORE", rff.status == "failed"
            and left == sorted(["STORE"] * 3 + ["STORE.tmp-live-1", "STORE.tmp-stale-2"]), "%r %r" % (rff, left))

        # --- an abandoned (old, empty) STORE is invalid at once; a young one still waits ---
        w.new_stores()
        ab_repo = w.repo(w.area("aband") / "r", url="https://github.com/o/aband.git")
        ab_dir = exp_dir(w, "r", "remote github.com/o/aband", "")
        ab_dir.mkdir()
        (ab_dir / "STORE").write_bytes(b"")
        old_ = time.time() - 60
        os.utime(str(ab_dir / "STORE"), (old_, old_))
        chk("empty-store:wait-setting-is-the-default-for-this-case", EMPTY_WAIT_SECONDS == 2.0 and EMPTY_ABANDONED_SECONDS == 5.0)
        t0 = time.monotonic()
        a_find, a_scan, a_iter = find(ab_repo), scan_stores(), scan_stores()[1]
        a_foc, a_wc = find_or_create(ab_repo), would_create_path(ab_repo)
        dt = time.monotonic() - t0
        chk("empty-store:old-empty-is-invalid-at-once-well-under-the-wait", dt < 1.0, "%.2f s" % dt)
        chk("empty-store:old-empty-reported-invalid-with-distinct-reason", a_find.status == "none" and not a_iter
            and any("abandoned" in x and "older than 5 s" in x for _d, x in a_scan[2]), repr(a_scan))
        chk("empty-store:old-empty-blocks-creation-and-is-not-overwritten", a_foc.status == "failed" and "abandoned" in a_foc.reason
            and a_wc.status == "failed" and (ab_dir / "STORE").read_bytes() == b"" and len(w.dirs()) == 1, repr(a_foc))
        chk("empty-store:abandoned-reason-names-the-STORE-file-and-the-remedy",
            os.path.join(str(ab_dir), "STORE") in a_foc.reason and "delete the directory or fix STORE" in a_foc.reason
            and os.path.join(str(ab_dir), "STORE") in a_wc.reason, repr(a_foc.reason))
        fut_ = time.time() + 3600
        os.utime(str(ab_dir / "STORE"), (fut_, fut_))
        t0 = time.monotonic()
        f_find, f_scan = find(ab_repo), scan_stores()
        dt = time.monotonic() - t0
        chk("empty-store:future-mtime-is-abandoned-at-once-not-waited-on",
            f_find.status == "none" and dt < 1.0 and any("future" in x and "abandoned" in x for _d, x in f_scan[2]), "%.2f s %r" % (dt, f_scan[2]))
        young = time.time() - 3
        os.utime(str(ab_dir / "STORE"), (young, young))
        EMPTY_WAIT_SECONDS = 0.5
        t0 = time.monotonic()
        a_young = find(ab_repo)
        dt = time.monotonic() - t0
        EMPTY_WAIT_SECONDS = saved_wait
        chk("empty-store:3-s-old-empty-still-waits", a_young.status == "none" and dt >= 0.4, "%.2f s" % dt)

        # --- UNC paths: none at once, no filesystem call ---
        if os.name == "nt":
            w.new_stores()
            spied, calls = {}, []

            def spy(mod, name):
                real_fn = getattr(mod, name)
                spied[(id(mod), name)] = (mod, name, real_fn)

                def wrapped(*a, **k):
                    calls.append(name)
                    return real_fn(*a, **k)
                setattr(mod, name, wrapped)
            real_expand = globals()["_expand_exact"]

            def spy_expand(p_):
                calls.append("_expand_exact")
                return real_expand(p_)
            uncs = ("\\\\10.255.255.1\\share\\x", "//10.255.255.1/share/x", "\\\\?\\UNC\\10.255.255.1\\share\\x", "\\\\server\\share", "\\\\.\\UNC\\h\\s\\x")
            bad, t0 = [], time.monotonic()
            for mod, name in ((os, "stat"), (os, "lstat"), (os, "listdir"), (os, "makedirs"), (os.path, "isdir"), (os.path, "isfile"),
                              (os.path, "lexists"), (os.path, "exists"), (os.path, "abspath"), (builtins, "open")):
                spy(mod, name)
            globals()["_expand_exact"] = spy_expand
            try:
                for u in uncs:
                    for fn in (find, find_or_create, would_create_path, identity, create):
                        res = fn(u)
                        if res.status != "none" or "UNC" not in res.reason:
                            bad.append((fn.__name__, u, res))
                    res = find_or_create(u, kind="plans")
                    if res.status != "none":
                        bad.append(("plans", u, res))
            finally:
                globals()["_expand_exact"] = real_expand
                for mod, name, real_fn in spied.values():
                    setattr(mod, name, real_fn)
            dt = time.monotonic() - t0
            chk("unc:every-entry-point-returns-none-with-a-reason", not bad, repr(bad[:2]))
            chk("unc:no-filesystem-call-was-made", calls == [], repr(calls[:6]))
            chk("unc:returns-fast", dt < 0.5, "%.2f s" % dt)
            chk("unc:local-extended-length-and-drive-paths-are-not-unc", not _is_unc("\\\\?\\C:\\x") and not _is_unc("C:\\x") and not _is_unc("\\x")
                and _is_unc("//srv/share") and _is_unc("\\\\srv\\share"))
        else:
            skip("unc:every-entry-point-returns-none-with-a-reason", "not Windows")

        # --- cleanup pass (2026-10-16): control characters, round trip, publish retry, UNC root/gitdir/at, bounded scan ---
        w.new_stores()
        ctl = w.repo(w.area("ctl") / "r", url="https://h.example/a%0Ab/c.git")
        ictl = identity(ctl).path
        chk("control-char-remote:identity-is-local-not-a-three-line-remote", ictl.kind == "local" and ictl.value == _norm_path(ctl), repr(ictl))
        rctl = find_or_create(ctl)
        pctl = _parse_store_text(store_text(rctl.path))[0] if rctl.status == "created" else None
        chk("control-char-remote:created-store-is-one-line-local-and-parses",
            made(rctl, w) and store_text(rctl.path) == "local %s\n" % _norm_path(ctl) and pctl is not None and same_identity(pctl, ictl), repr(rctl))
        chk("control-char-remote:find-reaches-the-store", find(ctl).path == rctl.path)

        w.new_stores()
        rt_repo = w.repo(w.area("rt") / "r", url="https://h.example/a/b%20.git")
        chk("round-trip:premise-identity-value-ends-with-a-space", identity(rt_repo).path.value == "h.example/a/b ", repr(identity(rt_repo).path))
        n0, snap0 = len(w.dirs()), w.snapshot()
        rrt, wrt = find_or_create(rt_repo), would_create_path(rt_repo)
        chk("round-trip:identity-that-does-not-read-back-is-failed-and-nothing-created",
            rrt.status == "failed" and wrt.status == "failed" and "STORE" in rrt.reason and "nothing was created" in rrt.reason
            and len(w.dirs()) == n0 and w.snapshot() == snap0, "%r %r" % (rrt, wrt))
        rt2 = w.repo(w.area("rt2") / "r", url="https://github.com/o/rtc.git")
        n0, snap0 = len(w.dirs()), w.snapshot()
        chk("round-trip:create-with-a-newline-subpath-is-failed-and-writes-nothing",
            create(rt2, "x\ny").status == "failed" and len(w.dirs()) == n0 and w.snapshot() == snap0)

        # a temp file deleted between the write and the link (a stale-temp cleanup after a long suspend) is retried
        w.new_stores()
        pr = w.repo(w.area("pubretry") / "r", url="https://github.com/o/pubretry.git")
        real_link, link_calls = os.link, []

        def vanishing_link(src, dst, *a, **k):
            link_calls.append(src)
            if len(link_calls) == 1:
                os.unlink(src)
            return real_link(src, dst, *a, **k)
        os.link = vanishing_link
        try:
            rpr = find_or_create(pr)
        finally:
            os.link = real_link
        chk("publish-retry:temp-deleted-before-link-is-retried-and-created",
            made(rpr, w) and store_text(rpr.path) == "remote github.com/o/pubretry\n" and len(link_calls) == 2
            and sorted(os.listdir(str(rpr.path))) == ["STORE"], "%r %r" % (rpr, link_calls))
        w.new_stores()
        pr2 = w.repo(w.area("pubretry2") / "r", url="https://github.com/o/pubretry2.git")
        link_calls2 = []

        def always_vanishing_link(src, dst, *a, **k):
            link_calls2.append(src)
            os.unlink(src)
            return real_link(src, dst, *a, **k)
        os.link = always_vanishing_link
        try:
            rpr2 = find_or_create(pr2)
        finally:
            os.link = real_link
        chk("publish-retry:persistent-vanishing-is-failed-bounded-not-an-internal-error",
            rpr2.status == "failed" and "internal error" not in rpr2.reason and "could not publish" in rpr2.reason and len(link_calls2) == 8
            and not any(n_.startswith("STORE") for dp_, _dn, fn_ in os.walk(str(w.stores)) if os.sep + ".git" not in dp_ + os.sep for n_ in fn_), "%r %d" % (rpr2, len(link_calls2)))

        # a temp file that cannot be deleted after a good publish is never read as a store; a stale one is cleaned on a hit
        w.new_stores()
        lo = w.repo(w.area("leftover") / "r", url="https://github.com/o/leftover.git")
        real_unlink, unlink_denied = os.unlink, []

        def deny_tmp_unlink(path, *a, **k):
            if os.path.basename(str(path)).startswith(STORE_FILE + ".tmp-"):
                unlink_denied.append(path)
                raise PermissionError(13, "locked by antivirus (selftest)")
            return real_unlink(path, *a, **k)
        os.unlink = deny_tmp_unlink
        try:
            rlo = find_or_create(lo)
        finally:
            os.unlink = real_unlink
        left_tmp = [n_ for n_ in os.listdir(str(rlo.path)) if n_ != STORE_FILE] if rlo.status == "created" else []
        sc_ = scan_stores()
        chk("leftover-tmp:publish-still-succeeds-and-the-unlink-is-retried",
            made(rlo, w) and len(left_tmp) == 1 and left_tmp[0].startswith(STORE_FILE + ".tmp-") and len(unlink_denied) == READ_RETRIES + 1, "%r %r %d" % (rlo, left_tmp, len(unlink_denied)))
        chk("leftover-tmp:never-read-as-a-store-or-reported-invalid",
            sc_[0] == "ok" and [d_ for d_, _i in sc_[1]] == [rlo.path] and sc_[2] == [] and [d_ for d_, _i in scan_stores()[1]] == [rlo.path]
            and find(lo).path == rlo.path and find_or_create(lo).path == rlo.path, repr(sc_))
        old_ = time.time() - 600
        os.utime(str(rlo.path / left_tmp[0]), (old_, old_))
        chk("leftover-tmp:stale-one-is-deleted-when-creation-targets-the-directory-again",
            create(lo).status == "found" and not (rlo.path / left_tmp[0]).exists() and (rlo.path / STORE_FILE).is_file())

        # a scan stops at its first failed entry: 40 unreadable stores cost one entry's retries, not forty
        w.new_stores()
        for k_ in range(40):
            w.store("many-%02d" % k_, "remote github.com/o/many%d\n" % k_)
        mn = w.repo(w.area("many") / "r", url="https://github.com/o/many1.git")
        real_open7, denied7 = builtins.open, [0]

        def deny_every_store(file, *a, **k):
            if isinstance(file, str) and "many-" in file and file.replace("\\", "/").endswith("/" + STORE_FILE):
                denied7[0] += 1
                raise PermissionError(13, "sharing violation (selftest)")
            return real_open7(file, *a, **k)
        builtins.open = deny_every_store
        t0 = time.monotonic()
        try:
            r7 = find(mn)
            r7b = find_or_create(mn)
        finally:
            builtins.open = real_open7
        dt = time.monotonic() - t0
        chk("scan-bound:all-stores-denied-is-failed-within-a-fraction-of-a-second", r7.status == "failed" and r7b.status == "failed" and dt < 1.5, "%.2f s %r" % (dt, r7))
        chk("scan-bound:only-the-first-entry-is-retried", denied7[0] == 2 * (READ_RETRIES + 1), "%d reads" % denied7[0])

        # at= is validated only on the creation path; a found store wins whatever `at` holds
        w.new_stores()
        r9 = w.repo(w.area("at9") / "r", url="https://github.com/o/at9.git")
        (r9 / "s").mkdir()
        bad_ats = [("empty", ""), ("blank", "   "), ("int", 123), ("nul", "a\x00b")]
        if os.name == "nt":
            bad_ats.append(("unc", "\\\\10.255.255.1\\share\\x"))
        n0 = len(w.dirs())
        with unc_spy() as unc_hits0:
            no_store = {lbl: find_or_create(r9 / "s", at=v_) for lbl, v_ in bad_ats}
        chk("at-late-validation:no-store-yet-a-bad-at-is-rejected-on-the-creation-path",
            all(x.status in ("failed", "none") for x in no_store.values()) and len(w.dirs()) == n0, repr(no_store))
        chk("at-late-validation:a-unc-at-is-rejected-without-touching-the-network-path", unc_hits0 == [], repr(unc_hits0[:3]))
        d9 = w.store("at9-top", "remote github.com/o/at9\n")
        n0 = len(w.dirs())
        with unc_spy() as unc_hits:
            found9 = {lbl: find_or_create(r9 / "s", at=v_) for lbl, v_ in bad_ats}
        chk("at-late-validation:found-store-is-returned-with-the-ignored-notice-for-every-bad-at",
            all(x.status == "found" and x.path == d9 and "at=" in x.notice and "ignored" in x.notice for x in found9.values()) and len(w.dirs()) == n0, repr(found9))
        chk("at-late-validation:a-found-store-never-touches-a-unc-at", unc_hits == [], repr(unc_hits[:3]))

        # the markers are probed only by folder_fallback (the user tier is never project memory); plans never probe them
        _TEST.pop("config_repo", None)
        chk("config-probe:plans-in-the-config-repo-are-not-the-repo-itself", find(cfg2 / "plans" / "done", "plans").path != cfg2)
        real_stat9 = os.stat

        def deny_marker_stat(path, *a, **k):
            if str(path).replace("\\", "/").lower().endswith("/shared/agents.md"):
                raise PermissionError(13, "denied (selftest)")
            return real_stat9(path, *a, **k)
        os.stat = deny_marker_stat
        try:
            rcp1, rcp2 = find(cfg2 / "plans" / "done", "plans"), find_or_create(cfg2, "plans")
            rcp3 = find(cfg2 / "plans" / "done", "memory")
        finally:
            os.stat = real_stat9
        chk("config-probe:a-marker-error-does-not-touch-kind-plans",
            rcp1.status != "failed" and rcp2.status != "failed", "%r %r" % (rcp1, rcp2))
        chk("config-probe:other-kinds-do-not-probe-the-markers", rcp3.status != "failed", repr(rcp3))
        w.reset_patches()

        if os.name == "nt":
            unc_root = "\\\\10.255.255.1\\share\\stores"
            ur_repo = w.repo(w.area("uncroot") / "r", url="https://github.com/o/uncroot.git")
            os.environ["AGENT_PLAYBOOK_STORES"] = unc_root
            t0 = time.monotonic()
            with unc_spy() as unc_hits:
                ur_res = {fn.__name__: fn(ur_repo) for fn in (find, find_or_create, would_create_path, create)}
                ur_scan = scan_stores()
            dt = time.monotonic() - t0
            w.new_stores()
            chk("unc-root:every-entry-point-is-failed-naming-the-network-path",
                all(x.status == "failed" and "network" in x.reason for x in ur_res.values()) and ur_scan[0] == "failed", repr(ur_res))
            chk("unc-root:no-filesystem-call-reached-the-network-path-and-returns-fast", unc_hits == [] and dt < 0.5, "%r %.2f s" % (unc_hits[:3], dt))
            unc_git = "\\\\10.255.255.1\\share\\x\\.git"
            gd_repo = w.area("uncgit")
            (gd_repo / ".git").write_text("gitdir: %s\n" % unc_git, encoding="utf-8")
            cd_meta = w.area("unccommon")
            (cd_meta / "commondir").write_text("\\\\10.255.255.1\\share\\x\n", encoding="utf-8")
            cd_repo = w.area("unccommon2")
            (cd_repo / ".git").write_text("gitdir: %s\n" % cd_meta, encoding="utf-8")
            n0 = len(w.dirs())
            t0 = time.monotonic()
            with unc_spy() as unc_hits:
                g1, g2, g3, g4 = identity(gd_repo), find_or_create(gd_repo), identity(cd_repo), find_or_create(cd_repo)
            dt = time.monotonic() - t0
            chk("unc-gitdir:gitdir-and-commondir-targets-on-a-network-path-are-failed-nothing-created",
                all(x.status == "failed" and "network" in x.reason for x in (g1, g2, g3, g4)) and len(w.dirs()) == n0, repr((g1, g3)))
            chk("unc-gitdir:no-filesystem-call-reached-the-network-path-and-returns-fast", unc_hits == [] and dt < 0.5, "%r %.2f s" % (unc_hits[:3], dt))
            chk("unc-root:mapped-drives-are-not-unc-by-design", not _is_unc("Z:\\stores"))
        else:
            skip("unc-root:every-entry-point-is-failed-naming-the-network-path", "not Windows")

        # --- folder validation: bad input is failed, a missing folder or a file never gets a store ---
        w.new_stores()
        vr = w.repo(w.area("val") / "r", url="https://github.com/o/val.git")
        n0, snap0 = len(w.dirs()), w.snapshot()
        bad = []
        for label, val in (("empty", ""), ("blanks", "   "), ("none", None), ("int", 123), ("bytes", b"x"), ("nul", "a\x00b")):
            for fn in (find, find_or_create, would_create_path, identity, create):
                res = fn(val)
                if res.status != "failed":
                    bad.append((label, fn.__name__, res))
        chk("validation:empty-and-non-string-input-is-failed-everywhere", not bad, repr(bad[:3]))
        chk("validation:bad-input-writes-nothing", len(w.dirs()) == n0 and w.snapshot() == snap0)
        ghost_sub = vr / "ghost-sub"
        gres = {fn.__name__: fn(ghost_sub) for fn in (find_or_create, would_create_path, create)}
        chk("validation:missing-folder-is-none-and-nothing-created", all(x.status == "none" and "does not exist" in x.reason for x in gres.values())
            and len(w.dirs()) == n0, repr(gres))
        fpath = vr / "afile.txt"
        fpath.write_text("x", encoding="utf-8")
        rf_ = find_or_create(fpath)
        chk("validation:regular-file-is-none-not-a-directory", rf_.status == "none" and "not a directory" in rf_.reason and len(w.dirs()) == n0, repr(rf_))
        chk("validation:path-below-a-file-is-none", find_or_create(fpath / "child").status == "none" and len(w.dirs()) == n0)
        chk("validation:missing-relative-folder-is-none", find_or_create("selftest-no-such-relative-dir").status == "none" and len(w.dirs()) == n0)
        chk("validation:find-and-identity-on-a-missing-folder-stay-lexical", find(ghost_sub).status == "none"
            and identity(ghost_sub).status == "found" and identity(ghost_sub).path.subpath == "ghost-sub")
        chk("validation:existing-store-is-still-found-for-a-missing-subfolder",
            (lambda d_: find(ghost_sub).path == d_)(w.store("val-top", "remote github.com/o/val\n")))

        # --- CLI ---
        w.new_stores()
        cl = w.repo(w.area("cli") / "r", url="https://github.com/o/cli.git")
        (cl / "sub").mkdir()

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(list(argv))
            return code, out.getvalue(), err.getvalue()
        code, out, err = run("find", str(cl))
        chk("cli:find-none-exits-3-prints-the-reason-on-stderr-and-nothing-on-stdout",
            code == 3 and out == "" and err.startswith("store-resolver: ") and "no store at or above" in err and err.count("\n") == 1,
            "%r %r %r" % (code, out, err))
        code, out, err = run("find-or-create", str(cl / "sub"))
        chk("cli:find-or-create-prints-path", code == 0 and Path(out.strip()).is_dir() and (Path(out.strip()) / "STORE").is_file(), out)
        code, out2, err = run("find", str(cl / "sub"))
        chk("cli:find-prints-same-path", code == 0 and out2 == out)
        code, out, err = run("identity", str(cl / "sub"))
        chk("cli:identity-prints-store-lines", code == 0 and out.splitlines() == ["remote github.com/o/cli", "path sub"], out)
        code, out, err = run("would-create", str(cl))
        chk("cli:would-create-prints-path", code == 0 and out.strip().startswith(str(w.stores)))
        code, out, err = run("list")
        chk("cli:list", code == 0 and "remote github.com/o/cli" in out and "\tsub" in out, out)
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "never-created")
        code, out, err = run("find", str(cl))
        chk("cli:failed-exits-2-with-reason-on-stderr", code == 2 and out == "" and "clone it" in err)
        w.new_stores()
        code, out, err = run("find-or-create", str(w.systemp))
        chk("cli:no-create-root-exits-3", code == 3 and out == "")
        chk("cli:no-create-root-reason-reaches-stderr", "temp" in err and err.count("\n") == 1, repr(err))
        code, out, err = run("find-or-create", str(cl / "sub"), "--at", str(w.root))
        chk("cli:unreachable-at-reason-and-pointer-reach-stderr", code == 3 and out == "" and "the steps for using a parent's store" in err and err.count("\n") == 1, repr(err))
        code, out, err = run("find-or-create", str(w.root / "no-such-folder"))
        chk("cli:missing-folder-reason-reaches-stderr", code == 3 and out == "" and "does not exist" in err, repr(err))
        code, out, err = run("find-or-create", str(cl / "sub"))
        code2, out2, err2 = run("find-or-create", str(cl / "sub"), "--at", str(cl))
        chk("cli:at-ignored-prints-notice-on-stderr", code2 == 0 and out2 == out and "ignored" in err2, err2)
        try:
            code, out, err = run("find", "--json", str(cl))
        except SystemExit as exc:
            code = exc.code
        chk("cli:json-flag-is-gone", code == 2)
        real_scan = scan_stores

        def boom(*a, **k):
            raise RuntimeError("selftest boom")
        globals()["scan_stores"] = boom
        try:
            code, out, err = run("list")
        finally:
            globals()["scan_stores"] = real_scan
        chk("cli:unexpected-exception-prints-one-line-and-exits-2", code == 2 and out == "" and err.count("\n") == 1
            and "unexpected error" in err and "selftest boom" in err, repr(err))

        # --- property test against an independent oracle ---
        rng = random.Random(20261016)
        pool = ["a", "Bb", "c c", "dd", "E"]
        prop_ok, prop_detail = True, ""
        for it in range(25):
            w.new_stores()
            top = w.repo(w.area("prop") / "r", url="https://github.com/o/prop%d.git" % it)
            subs = set()
            for _ in range(rng.randint(2, 7)):
                depth = rng.randint(1, 3)
                subs.add("/".join(rng.sample(pool, depth)))
            subs = sorted(subs)
            for s_ in subs:
                (top / s_).mkdir(parents=True, exist_ok=True)
            stored = {}
            for k, s_ in enumerate(subs):
                if rng.random() < 0.4:
                    shown = s_.swapcase() if rng.random() < 0.3 else s_
                    stored[s_] = w.store("p%d" % k, "remote github.com/o/prop%d\npath %s\n" % (it, shown))
            if rng.random() < 0.3:
                stored[""] = w.store("ptop", "remote github.com/o/prop%d\n" % it)
            for q in subs + [""]:
                parts = q.split("/") if q else []
                want = None
                for n in range(len(parts), -1, -1):
                    cand = "/".join(parts[:n])
                    if cand in stored:
                        want = stored[cand]
                        break
                got = find(top / q if q else top)
                if (got.path if got.status == "found" else None) != want:
                    prop_ok, prop_detail = False, "iter %d query %r got %r want %r" % (it, q, got, want)
            nq = top / (subs[0] if subs else "a")
            before = len(w.dirs())
            fc = find_or_create(nq)
            if fc.status == "created":
                if not (made(fc, w) and find(nq).path == fc.path and find_or_create(nq).path == fc.path and len(w.dirs()) == before + 1):
                    prop_ok, prop_detail = False, "iter %d create at %s" % (it, nq)
            elif fc.status != "found":
                prop_ok, prop_detail = False, "iter %d find_or_create %r" % (it, fc)
        chk("property:find-matches-nearest-ancestor-oracle", prop_ok, prop_detail)

        # --- resolve_artifact: reading an artifact class from the store repo ---
        def md(path, text="# m\n"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(text, encoding="utf-8")
            return Path(path)

        w.reset_patches()
        w.new_stores()
        _invalidate_scan_cache()
        tr_proj = w.repo(w.area("trproj"), "https://github.com/Org/Proj.git")
        tr_store = w.store("proj-aaaaaa", "remote github.com/org/proj\n")
        # a store of an unrelated repo with the same last segment must not match
        tr_other = w.store("proj-bbbbbb", "remote github.com/other/proj\n")
        md(tr_other / "memory" / "MEMORY.md")
        cfgs = str(w.area("trcfg"))

        md(tr_store / "memory" / "MEMORY.md")
        a = resolve_artifact(tr_proj, "memory")
        chk("resolve:store-repo-hit-at-the-folder",
            a.source == "store-repo" and a.path == tr_store / "memory" and a.store == tr_store
            and a.folder == tr_proj and a.reason == "" and a.store_repo == "ok", repr(a))
        chk("resolve:result-unpacks-as-source-path", tuple(a) == ("store-repo", tr_store / "memory"))
        chk("resolve:config-repo-argument-does-not-change-the-answer",
            tuple(resolve_artifact(tr_proj, "memory")) == tuple(a))

        # per artifact class: the store holds only artifacts/, so memory is none with the store reported
        (tr_store / "memory" / "MEMORY.md").unlink()
        (tr_store / "memory").rmdir()
        md(tr_store / "artifacts" / "run.md")
        a = resolve_artifact(tr_proj, "memory")
        chk("resolve:artifacts-only-store-memory-is-none-nearest-store-reported",
            a.source == "none" and a.path == tr_proj / "memory" and a.store == tr_store and a.folder == tr_proj, repr(a))
        a2 = resolve_artifact(tr_proj, "artifacts")
        chk("resolve:per-class-artifacts-from-store-repo",
            a2.source == "store-repo" and a2.path == tr_store / "artifacts", repr(a2))

        # a directory holding only .handoff-*.md is unpopulated; the nearest store is still reported
        md(tr_store / "memory" / ".handoff-9.md")
        a = resolve_artifact(tr_proj, "memory")
        chk("resolve:handoff-only-is-unpopulated",
            a.source == "none" and a.path == tr_proj / "memory" and a.store == tr_store, repr(a))

        # an in-workspace copy is never read: the store repo is the one source
        md(tr_proj / "memory" / "MEMORY.md")
        md(tr_proj / "plans" / "p1.md")
        a = resolve_artifact(tr_proj, "memory")
        b = resolve_artifact(tr_proj, "plans")
        chk("resolve:in-workspace-copy-is-not-read",
            a.source == "none" and a.store == tr_store and b.source == "none" and b.path == tr_proj / "plans", repr((a, b)))

        # walk-up: a nested folder reaches its toplevel's store; a nearer store with content wins
        tr_sub = tr_proj / "pkg" / "inner"
        tr_sub.mkdir(parents=True)
        md(tr_store / "memory" / "MEMORY.md")
        a = resolve_artifact(tr_sub, "memory")
        chk("resolve:walk-up-reaches-toplevel-store",
            a.source == "store-repo" and a.store == tr_store and a.folder == tr_proj, repr(a))
        tr_sub_store = w.store("proj-inner", "remote github.com/org/proj\npath pkg/inner\n")
        _invalidate_scan_cache()
        a = resolve_artifact(tr_sub, "memory")
        chk("resolve:empty-nearer-store-falls-through-to-a-populated-ancestor",
            a.source == "store-repo" and a.store == tr_store and a.folder == tr_proj, repr(a))
        (tr_store / "memory" / "MEMORY.md").unlink()
        a = resolve_artifact(tr_sub, "memory")
        chk("resolve:none-reports-the-nearest-empty-store",
            a.source == "none" and a.path == tr_sub / "memory" and a.store == tr_sub_store and a.folder == tr_sub, repr(a))
        md(tr_store / "memory" / "MEMORY.md")
        md(tr_sub_store / "memory" / "MEMORY.md")
        a = resolve_artifact(tr_sub, "memory")
        chk("resolve:nearest-level-wins",
            a.source == "store-repo" and a.path == tr_sub_store / "memory" and a.folder == tr_sub, repr(a))

        # the store repo is missing: a reader fails open on none and says so
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "no-such-store-repo")
        _invalidate_scan_cache()
        a = resolve_artifact(tr_proj, "memory")
        chk("resolve:store-repo-missing-is-none-with-reason",
            a.source == "none" and a.store is None and a.store_repo == "missing"
            and "store repo skipped" in a.reason, repr((a, a.reason)))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        _invalidate_scan_cache()

        # the store repo exists but cannot be scanned: none, unreadable, reason set
        tr_real_scan = scan_stores
        globals()["scan_stores"] = lambda *a_, **k_: ("failed", [], [], "selftest injected failure")
        try:
            _invalidate_scan_cache()
            a = resolve_artifact(tr_proj, "memory")
        finally:
            globals()["scan_stores"] = tr_real_scan
            _invalidate_scan_cache()
        chk("resolve:store-repo-unreadable-is-none-with-reason",
            a.source == "none" and a.store_repo == "unreadable" and "selftest injected failure" in a.reason, repr((a, a.reason)))

        # the config repo: memory and plans both come from its store like any repo
        _TEST["config_repo"] = str(tr_proj)
        a = resolve_artifact(tr_proj, "memory")
        chk("resolve:config-repo-memory-from-the-store-repo",
            a.source == "store-repo" and a.store == tr_store, repr(a))
        md(tr_store / "plans" / "p2.md")
        a = resolve_artifact(tr_sub, "plans")
        chk("resolve:config-repo-plans-from-the-store-repo",
            a.source == "store-repo" and a.path == tr_store / "plans" and a.store == tr_store, repr(a))
        _TEST["config_repo"] = ""

        # CLI resolve: <source>\t<path>, exit 0 found / 3 none (reason on stderr) / 2 failed
        code, out, err = run("resolve", str(tr_proj), "--kind", "memory")
        chk("cli-resolve:found-prints-source-and-path",
            code == 0 and out == "store-repo\t%s\n" % (tr_store / "memory") and err == "", repr((code, out, err)))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "no-such-store-repo")
        _invalidate_scan_cache()
        code, out, err = run("resolve", str(tr_proj))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        _invalidate_scan_cache()
        chk("cli-resolve:missing-store-repo-exits-2-reason-on-stderr",
            code == 2 and out == "" and "store repo skipped" in err, repr((code, out, err)))
        code, out, err = run("resolve", "")
        chk("cli-resolve:failed-exits-2", code == 2 and out == "", repr((code, out, err)))

        chk("resolve:unknown-kind-failed", resolve_artifact(tr_proj, "nonsense").source == "failed")
        chk("resolve:unc-is-none", resolve_artifact("\\\\no-such-host\\share\\x", "memory").source in ("none", "failed"))
        chk("resolve:never-raises", resolve_artifact(None, "memory").source == "failed")

        # an early failed answer (bad folder, unknown kind) carries the real store repo state, not "ok"
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "no-such-store-repo")
        _invalidate_scan_cache()
        ea = (resolve_artifact("", "memory"), resolve_artifact(tr_proj, "nonsense"),
              resolve_artifact("\\\\no-such-host\\share\\x", "memory"))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        _invalidate_scan_cache()
        eb = resolve_artifact(tr_proj, "nonsense")
        chk("resolve:early-answers-carry-the-real-store-repo-state",
            all(a.store_repo == "missing" for a in ea) and eb.source == "failed" and eb.store_repo == "ok",
            repr([(a, a.store_repo) for a in ea + (eb,)]))

        # --- folder_fallback: the in-workspace copy a reader may read, only in a no-create folder with no store ---
        w.reset_patches()
        w.new_stores()
        _invalidate_scan_cache()
        ff_nc = w.systemp / "ffa" / "proj"           # a no-create folder (under the patched system temp), outside git
        md(ff_nc / "memory" / "MEMORY.md")
        chk("fallback:no-create-folder-reads-its-in-workspace-memory",
            would_create_path(ff_nc).status == "none" and folder_fallback(ff_nc) == ff_nc / "memory"
            and folder_fallback(ff_nc, "plans") is None, repr(folder_fallback(ff_nc)))
        ff_empty = w.store("ffa-000001", "local %s\n" % norm_path(ff_nc.parent))   # an empty store one level up
        _invalidate_scan_cache()
        chk("fallback:any-store-at-a-level-even-empty-gives-none",
            not populated(ff_empty / "memory") and folder_fallback(ff_nc) is None, repr(folder_fallback(ff_nc)))
        shutil.rmtree(str(ff_empty))
        _invalidate_scan_cache()
        ff_norm = w.area("ffnormal")                 # a normal folder: find_or_create would create a store here
        md(ff_norm / "memory" / "MEMORY.md")
        chk("fallback:would-create-folder-gives-none",
            would_create_path(ff_norm).status == "created" and folder_fallback(ff_norm) is None, repr(folder_fallback(ff_norm)))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "no-such-store-repo")
        _invalidate_scan_cache()
        ff_missing = folder_fallback(ff_nc)
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        _invalidate_scan_cache()
        chk("fallback:missing-store-repo-gives-none", ff_missing is None and folder_fallback(ff_nc) == ff_nc / "memory",
            repr(ff_missing))
        ff_real_scan = scan_stores
        globals()["scan_stores"] = lambda *a_, **k_: ("failed", [], [], "selftest injected failure")
        try:
            _invalidate_scan_cache()
            ff_unread = folder_fallback(ff_nc)
        finally:
            globals()["scan_stores"] = ff_real_scan
            _invalidate_scan_cache()
        chk("fallback:unreadable-store-repo-gives-none", ff_unread is None, repr(ff_unread))
        ff_cfg = w.repo(w.systemp / "ffcfg" / "cfg", "https://github.com/o/ffcfg.git")
        md(ff_cfg / "memory" / "MEMORY.md")
        md(ff_cfg / "plans" / "p.md")
        ff_cfg_before = folder_fallback(ff_cfg)
        _TEST["config_repo"] = str(ff_cfg)
        chk("fallback:config-repo-memory-gives-none",
            ff_cfg_before == ff_cfg / "memory" and folder_fallback(ff_cfg) is None
            and folder_fallback(ff_cfg / "memory") is None, repr(ff_cfg_before))
        _TEST["config_repo"] = ""
        ff_top = w.repo(w.systemp / "ffgit" / "top", "https://github.com/o/ffgit.git")
        ff_deep = ff_top / "a" / "b"
        md(ff_top / "memory" / "MEMORY.md")
        md(ff_top / "a" / "memory" / "MEMORY.md")
        md(ff_deep / "memory" / ".handoff-1.md")     # handoff-only: not content
        ff_near = folder_fallback(ff_deep)
        (ff_top / "a" / "memory" / "MEMORY.md").unlink()
        ff_far = folder_fallback(ff_deep)
        md(w.systemp / "ffgit" / "memory" / "MEMORY.md")   # above the git toplevel: never reached
        chk("fallback:git-walk-up-picks-the-nearest-populated-level",
            ff_near == ff_top / "a" / "memory" and ff_far == ff_top / "memory", repr((ff_near, ff_far)))
        (ff_top / "memory" / "MEMORY.md").unlink()
        chk("fallback:git-walk-stops-at-the-toplevel", folder_fallback(ff_deep) is None, repr(folder_fallback(ff_deep)))
        ff_ng = w.systemp / "ffng" / "parent"
        (ff_ng / "child").mkdir(parents=True)
        md(ff_ng / "memory" / "MEMORY.md")
        chk("fallback:outside-git-only-the-folder-itself",
            folder_fallback(ff_ng / "child") is None and folder_fallback(ff_ng) == ff_ng / "memory",
            repr(folder_fallback(ff_ng / "child")))
        # Off Windows the UNC spelling is a relative path, read against the cwd: run it from an empty fixture
        # folder, not from wherever the selftest was started (a checkout of this repo holds a populated memory/).
        ff_cwd, ff_here = w.area("ffcwd"), os.getcwd()
        os.chdir(str(ff_cwd))
        try:
            ff_unc = folder_fallback("\\\\no-such-host\\share\\x")
        finally:
            os.chdir(ff_here)
        chk("fallback:never-raises", folder_fallback(None) is None and folder_fallback(ff_nc, "nonsense") is None
            and folder_fallback("") is None and ff_unc is None, repr(ff_unc))

        # --- the public helpers other modules call instead of underscore names ---
        ph = w.area("Pub Helpers")
        chk("public:norm-path-is-the-local-identity-form",
            norm_path(ph) == _norm_path(ph) and norm_path(norm_path(ph)) == norm_path(ph) and norm_path(None) == "",
            repr(norm_path(ph)))
        chk("public:is-under-at-a-slash-boundary",
            is_under(ph, ph) and is_under(ph / "x", ph) and is_under(str(ph / "x").upper(), str(ph).lower())
            and not is_under(str(ph) + "x", ph) and not is_under(ph.parent, ph) and not is_under(None, ph))
        pub_text = globals()["store_text"]   # the selftest's own store_text(d) reads a STORE file
        chk("public:store-text-is-what-create-writes",
            pub_text(Identity("remote", "h/o/r", "a/b", None, None)) == "remote h/o/r\npath a/b\n"
            and pub_text(Identity("local", "c:/x", "", None, None)) == "local c:/x\n" and pub_text(None) == "")
        pk = (parse_store_key("remote h/o/mono path svc/api"), parse_store_key("local c:/a b/c"),
              parse_store_key("remote h/o/r"), parse_store_key("bogus x"), parse_store_key("remote "), parse_store_key(None))
        chk("public:parse-store-key-inverts-the-key-text",
            same_identity(pk[0], Identity("remote", "h/o/mono", "svc/api", None, None))
            and same_identity(pk[1], Identity("local", "c:/a b/c", "", None, None))
            and same_identity(pk[2], Identity("remote", "h/o/r", "", None, None)) and pk[3:] == (None, None, None), repr(pk))

        # --- the short-lived scan cache (plan 261016 Phase 7 review fix) ---
        # Where a wrong cache hides: a store created or edited after a cached scan is not seen; a failed
        # scan is kept as if it had succeeded; the creation paths decide on a stale scan.
        w.new_stores()
        w.reset_patches()
        _invalidate_scan_cache()
        sc_calls = []
        sc_real = scan_stores

        def sc_counting(*a, **k):
            sc_calls.append(1)
            return sc_real(*a, **k)
        saved_ttl = SCAN_CACHE_SECONDS
        globals()["scan_stores"] = sc_counting
        try:
            sc_a = w.repo(w.area("sca") / "r", url="https://github.com/o/sca.git")
            sc_b = w.repo(w.area("scb") / "r", url="https://github.com/o/scb.git")
            d_sca = w.store("sca-1", "remote github.com/o/sca\n")
            r1 = find(sc_a)
            r2 = find(sc_a)
            chk("scan-cache:second-find-reuses-the-scan-and-gives-the-same-answer",
                len(sc_calls) == 1 and r1.status == r2.status == "found" and r1.path == r2.path == d_sca, repr((sc_calls, r1, r2)))
            n0 = len(sc_calls)
            nb1 = find(sc_b)
            d_scb = w.store("scb-1", "remote github.com/o/scb\n")
            nb2 = find(sc_b)
            chk("scan-cache:a-store-created-after-a-cached-scan-is-seen",
                nb1.status == "none" and nb2.status == "found" and nb2.path == d_scb and len(sc_calls) == n0 + 1, repr((nb1, nb2, sc_calls)))
            # the first repo's answer is still right after the second scan (no cross-talk between answers)
            chk("scan-cache:earlier-answer-unchanged-after-rescan", find(sc_a).path == d_sca)
            # a STORE rewritten in place to another size is seen (the fingerprint holds each STORE's size and time)
            sc_c = w.repo(w.area("scc") / "r", url="https://github.com/o/scc.git")
            d_scc = w.store("scc-1", "remote github.com/o/old-name-longer\n")
            nc1 = find(sc_c)
            (d_scc / "STORE").write_bytes(b"remote github.com/o/scc\n")
            nc2 = find(sc_c)
            chk("scan-cache:a-store-file-edited-in-place-is-seen", nc1.status == "none" and nc2.status == "found" and nc2.path == d_scc,
                repr((nc1, nc2)))
            # find_or_create decides on a fresh scan and leaves nothing stale behind
            sc_d = w.repo(w.area("scd") / "r", url="https://github.com/o/scd.git")
            nd1 = find(sc_d)
            cd = find_or_create(sc_d)
            nd2 = find(sc_d)
            chk("scan-cache:find-or-create-creates-after-a-cached-none-and-find-sees-it",
                nd1.status == "none" and cd.status == "created" and nd2.status == "found" and nd2.path == cd.path, repr((nd1, cd, nd2)))
            # find_or_create must not trust a cached "none" for a store another process just made
            sc_e = w.repo(w.area("sce") / "r", url="https://github.com/o/sce.git")
            find(sc_e)
            d_sce = w.store("sce-1", "remote github.com/o/sce\n")
            ce = find_or_create(sc_e)
            chk("scan-cache:find-or-create-returns-the-existing-store-not-a-second-one",
                ce.status == "found" and ce.path == d_sce and len([n for n in w.dirs() if n.startswith("sce")]) == 1, repr(ce))
            # The one change the fingerprint cannot see (same size, same modification time) is the reason the
            # creation paths bypass the cache: find may serve the old answer, find_or_create must not.
            sc_f = w.repo(w.area("scf") / "r", url="https://github.com/o/scf.git")
            d_scf = w.store("scf-1", "remote github.com/o/scq\n")
            nf1 = find(sc_f)
            old_st = os.stat(str(d_scf / "STORE"))
            (d_scf / "STORE").write_bytes(b"remote github.com/o/scf\n")
            os.utime(str(d_scf / "STORE"), ns=(old_st.st_atime_ns, old_st.st_mtime_ns))
            cf = find_or_create(sc_f)
            chk("scan-cache:find-or-create-rescans-where-the-fingerprint-is-blind",
                nf1.status == "none" and cf.status == "found" and cf.path == d_scf
                and len([n for n in w.dirs() if n.startswith("scf")]) == 1, repr((nf1, cf, w.dirs())))
            # resolve_artifact shares the cache
            _invalidate_scan_cache()
            n0 = len(sc_calls)
            sc_cfg = str(w.area("sccfg"))
            ra1 = resolve_artifact(sc_a, "memory")
            ra2 = resolve_artifact(sc_a, "memory")
            chk("scan-cache:resolve-artifact-reuses-the-scan", len(sc_calls) == n0 + 1 and ra1.store == ra2.store, repr((sc_calls, ra1, ra2)))
            # the time-to-live bounds the reuse: a hit before it, a rescan after it
            _invalidate_scan_cache()
            globals()["SCAN_CACHE_SECONDS"] = 0.4
            n0 = len(sc_calls)
            find(sc_a)
            find(sc_a)
            hit_within = len(sc_calls) == n0 + 1
            time.sleep(0.5)
            find(sc_a)
            chk("scan-cache:rescan-after-the-time-to-live", hit_within and len(sc_calls) == n0 + 2, repr((n0, sc_calls)))
            globals()["SCAN_CACHE_SECONDS"] = saved_ttl
            # a failed scan is not kept, and a vanished .git is seen at once
            _invalidate_scan_cache()
            n0 = len(sc_calls)
            gone = w.stores / ".git"
            gone.rename(w.stores / ".git-away")
            f1 = find(sc_a)
            f2 = find(sc_a)
            (w.stores / ".git-away").rename(gone)
            f3 = find(sc_a)
            chk("scan-cache:a-failed-scan-is-never-served-from-the-cache",
                f1.status == f2.status == "failed" and f3.status == "found" and f3.path == d_sca and len(sc_calls) >= n0 + 3,
                repr((f1, f2, f3, sc_calls)))
            _invalidate_scan_cache()
            find(sc_a)
            (w.stores / ".git").rename(w.stores / ".git-away")
            f4 = find(sc_a)
            (w.stores / ".git-away").rename(w.stores / ".git")
            chk("scan-cache:a-cached-ok-scan-does-not-hide-a-removed-store-repo-marker", f4.status == "failed", repr(f4))
            # a scan that fails inside scan_stores (not only a missing root) is not kept either
            _invalidate_scan_cache()
            flip = {"n": 0}

            def sc_flaky(*a, **k):
                flip["n"] += 1
                if flip["n"] == 1:
                    return ("failed", [], [], "selftest injected failure")
                return sc_real(*a, **k)
            globals()["scan_stores"] = sc_flaky
            g1 = _scan_cached()
            g2 = _scan_cached()
            g3 = _scan_cached()
            chk("scan-cache:an-injected-scan-failure-is-not-cached",
                g1[0] == "failed" and g2[0] == "ok" and g3[0] == "ok" and flip["n"] == 2, repr((g1[0], g2[0], g3[0], flip)))
            chk("scan-cache:never-raises-on-an-unreadable-root",
                _scan_cached(w.root / "no-such-root")[0] == "failed")
        finally:
            globals()["scan_stores"] = sc_real
            globals()["SCAN_CACHE_SECONDS"] = saved_ttl
            _invalidate_scan_cache()

        # --- the expansion cache (plan 261016 Phase 7 cleanup) ---
        # Where a wrong cache hides: keyed by a folded spelling (two spellings share one answer), a failed
        # expansion kept as if it were a success, no time limit (a renamed folder never seen), no size
        # limit, or a full cache dropping live entries while expired ones stay.
        ex_saved = (EXPAND_CACHE_SECONDS, _EXPAND_CACHE_MAX, _expand_raw)
        ex_calls, ex_answers = [], {}

        def ex_fake(p_):
            ex_calls.append(p_)
            return ex_answers.get(p_)
        globals()["_expand_raw"] = ex_fake
        try:
            globals()["EXPAND_CACHE_SECONDS"] = 60.0
            _invalidate_expand_cache()
            ex_answers.update({"C:\\Short~1\\A": "C:\\Longname\\A", "C:\\short~1\\a": "C:\\Other\\a"})
            e1, e2, e3 = _expand_exact("C:\\Short~1\\A"), _expand_exact("C:\\Short~1\\A"), _expand_exact("C:\\short~1\\a")
            chk("expand-cache:a-repeat-is-served-without-a-second-call-and-keys-are-exact",
                e1 == e2 == "C:\\Longname\\A" and e3 == "C:\\Other\\a" and ex_calls == ["C:\\Short~1\\A", "C:\\short~1\\a"],
                repr((e1, e2, e3, ex_calls)))
            del ex_calls[:]
            f1 = _expand_exact("C:\\gone")
            ex_answers["C:\\gone"] = "C:\\Gone"
            f2, f3 = _expand_exact("C:\\gone"), _expand_exact("C:\\gone")
            chk("expand-cache:a-failed-expansion-is-retried-and-a-later-success-is-kept",
                f1 is None and f2 == f3 == "C:\\Gone" and len(ex_calls) == 2, repr((f1, f2, f3, ex_calls)))
            # the time-to-live: a hit before it (old answer), a new call after it (new answer)
            globals()["EXPAND_CACHE_SECONDS"] = 0.3
            _invalidate_expand_cache()
            del ex_calls[:]
            ex_answers["K"] = "v1"
            t1 = _expand_exact("K")
            ex_answers["K"] = "v2"
            t2 = _expand_exact("K")
            time.sleep(0.4)
            t3 = _expand_exact("K")
            chk("expand-cache:an-answer-lives-for-the-time-to-live-and-no-longer",
                (t1, t2, t3) == ("v1", "v1", "v2") and len(ex_calls) == 2, repr((t1, t2, t3, ex_calls)))
            globals()["EXPAND_CACHE_SECONDS"] = 0
            _invalidate_expand_cache()
            del ex_calls[:]
            _expand_exact("K")
            _expand_exact("K")
            chk("expand-cache:a-zero-time-to-live-turns-it-off", len(ex_calls) == 2 and not _EXPAND_CACHE, repr(ex_calls))
            # bounded: never more than the limit, the newest entry is kept, an older one is asked again
            globals()["EXPAND_CACHE_SECONDS"] = 60.0
            globals()["_EXPAND_CACHE_MAX"] = 4
            _invalidate_expand_cache()
            del ex_calls[:]
            keys = ["B%d" % i for i in range(10)]
            for i, k in enumerate(keys):
                ex_answers[k] = "L%d" % i
            got = [_expand_exact(k) for k in keys]
            n_after_fill = len(ex_calls)
            newest = _expand_exact(keys[-1])
            oldest = _expand_exact(keys[0])
            chk("expand-cache:size-is-bounded-and-every-answer-is-still-right",
                got == ["L%d" % i for i in range(10)] and len(_EXPAND_CACHE) <= 4 and newest == "L9" and oldest == "L0"
                and len(ex_calls) == n_after_fill + 1, repr((got, len(_EXPAND_CACHE), ex_calls)))
            # a full cache drops its expired entries first and keeps the live ones
            globals()["EXPAND_CACHE_SECONDS"] = 0.3
            globals()["_EXPAND_CACHE_MAX"] = 3
            _invalidate_expand_cache()
            for k in ("X1", "X2"):
                ex_answers[k] = k.lower()
                _expand_exact(k)
            time.sleep(0.4)
            for k in ("X3", "X4"):
                ex_answers[k] = k.lower()
                _expand_exact(k)
            del ex_calls[:]
            live = _expand_exact("X3")
            chk("expand-cache:a-full-cache-drops-the-expired-and-keeps-the-live",
                live == "x3" and ex_calls == [] and sorted(_EXPAND_CACHE) == ["X3", "X4"], repr((live, ex_calls, sorted(_EXPAND_CACHE))))
        finally:
            globals()["EXPAND_CACHE_SECONDS"], globals()["_EXPAND_CACHE_MAX"], globals()["_expand_raw"] = ex_saved
            _invalidate_expand_cache()
        if os.name == "nt":
            # the real API behind it: resolving one folder twice asks Windows once per distinct path
            ex_real = _expand_raw
            ex_calls2 = []

            def ex_counting(p_):
                ex_calls2.append(p_)
                return ex_real(p_)
            globals()["_expand_raw"] = ex_counting
            try:
                _invalidate_expand_cache()
                ex_repo = w.repo(w.area("excache") / "r", url="https://github.com/o/excache.git")
                i1 = identity(ex_repo)
                n_first = len(ex_calls2)
                i2 = identity(ex_repo)
                v1 = _verbatim(str(ex_repo))
                chk("expand-cache:a-second-resolution-of-one-folder-makes-no-expansion-call",
                    i1.status == i2.status == "found" and same_identity(i1.path, i2.path) and n_first >= 1
                    and len(ex_calls2) == n_first and v1 == _verbatim(str(ex_repo)), repr((n_first, ex_calls2)))
            finally:
                globals()["_expand_raw"] = ex_real
                _invalidate_expand_cache()

        # --- a temp dir that is a link (macOS: /var/folders -> /private/var/folders) covers its real path too ---
        if hasattr(os, "symlink"):
            real_t = w.root / "real-sys-temp"
            (real_t / "scratch").mkdir(parents=True)
            link_t = w.root / "link-sys-temp"
            try:
                os.symlink(str(real_t), str(link_t), target_is_directory=True)
                linked = True
            except (OSError, NotImplementedError):
                linked = False
            if linked:
                saved_temp_env = {k: os.environ.get(k) for k in ("TMPDIR", "TEMP", "TMP")}
                saved_t = _TEST.pop("temp", None)
                try:
                    for k in ("TEMP", "TMP"):
                        os.environ.pop(k, None)
                    os.environ["TMPDIR"] = str(link_t)
                    # the real path itself is listed (not only covered by /tmp, which holds this fixture)
                    chk("temp-link:real-path-under-a-linked-temp-is-no-create",
                        _norm_path(os.path.realpath(str(link_t))) in _temp_dirs()
                        and _no_create_reason(_norm_path(real_t / "scratch")) == "the system temp directory",
                        repr(_temp_dirs()))
                finally:
                    for k, v in saved_temp_env.items():
                        if v is None:
                            os.environ.pop(k, None)
                        else:
                            os.environ[k] = v
                    if saved_t is not None:
                        _TEST["temp"] = saved_t
            else:
                skip("temp-link:real-path-under-a-linked-temp-is-no-create", "no symlink could be made")

        # --- the reserved user/ directory of the store repo is never a store, valid or invalid ---
        w.new_stores()
        (w.stores / USER_DIR / "memory").mkdir(parents=True)
        st_u, valid_u, invalid_u, _why_u = scan_stores()
        chk("user-dir:scan-skips-reserved-user", st_u == "ok" and not invalid_u
            and all(Path(d).name != USER_DIR for d, _i in valid_u), repr((st_u, valid_u, invalid_u)))

        # --- pointer file (~/.agent-playbook/config): precedence and malformed lines ---
        w.reset_patches()
        saved_cfg_env = {k: os.environ.pop(k, None) for k in ("AGENT_PLAYBOOK_CONFIG", "AGENT_PLAYBOOK_ROOT")}
        try:
            env_stores = os.environ.pop("AGENT_PLAYBOOK_STORES", None)
            cfgdir = w.home / ".agent-playbook"
            cfgdir.mkdir(exist_ok=True)
            cfile = cfgdir / "config"
            chk("config:absent-file-is-empty-and-silent", read_config() == ({}, []))
            chk("config:absent-file-stores-default",
                _cmp(str(_stores_root())) == _cmp(os.path.join(str(w.home), ".agent-playbook", "stores")))
            from_cfg = w.root / "cfg-stores"
            eng = w.root / "cfg-engine"
            cfile.write_text("# written by setup\nroot=%s\nstores=%s\n\nbogus line\nproviders=claude,codex\n"
                             % (eng, from_cfg), encoding="utf-8")
            cfg, probs = read_config()
            chk("config:keys-read", cfg.get("root") == str(eng) and cfg.get("providers") == "claude,codex", repr(cfg))
            chk("config:malformed-line-reported-with-line-number", len(probs) == 1 and ":5:" in probs[0], repr(probs))
            with contextlib.redirect_stderr(io.StringIO()):
                chk("config:stores-from-file", _cmp(str(_stores_root())) == _cmp(str(from_cfg)))
                chk("config:root-from-file", _cmp(str(playbook_root())) == _cmp(str(eng)))
                chk("config:user-memory-under-stores",
                    _cmp(str(user_memory_dir())) == _cmp(str(from_cfg / "user" / "memory")))
                chk("config:engine-branch-default", engine_branch() == "local-improvements")
                os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "env-stores")
                os.environ["AGENT_PLAYBOOK_ROOT"] = str(w.root / "env-engine")
                chk("config:env-beats-file-stores", _cmp(str(_stores_root())) == _cmp(str(w.root / "env-stores")))
                chk("config:env-beats-file-root", _cmp(str(playbook_root())) == _cmp(str(w.root / "env-engine")))
                os.environ.pop("AGENT_PLAYBOOK_ROOT")
                cfile.unlink()
                here = playbook_root()
                chk("config:root-falls-back-to-own-repo",
                    here is not None and (here / "inventory.tsv").is_file() and (here / "shared" / "AGENTS.md").is_file(),
                    repr(here))
                alt = w.root / "alt-config"
                alt.write_text("engine_branch=dev\n", encoding="utf-8")
                os.environ["AGENT_PLAYBOOK_CONFIG"] = str(alt)
                chk("config:config-env-selects-file", engine_branch() == "dev")
        finally:
            for k, v in saved_cfg_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            if env_stores is not None:
                os.environ["AGENT_PLAYBOOK_STORES"] = env_stores
            w.reset_patches()

        # --- store scratch folder: creation, the age rule, and every refusal of the delete path ---
        w.reset_patches()
        w.new_stores()
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        sc_repo = w.repo(w.area("scproj") / "r", url="https://github.com/o/scproj.git")
        rs = scratch_folder(sc_repo, "260101-probe")
        chk("scratch:creates-the-store-and-the-folder", rs.status == "created" and rs.path.is_dir()
            and rs.path.parent.name == SCRATCH_DIR and (rs.path.parent.parent / STORE_FILE).is_file(), repr(rs))
        sc_store = rs.path.parent.parent
        chk("scratch:same-name-is-the-same-folder", scratch_folder(sc_repo, "260101-probe").path == rs.path)
        for bad in ("../up", "a/b", "a\\b", "", ".hidden", "name.", "C:evil"):
            chk("scratch:refuses-name:%s" % bad, scratch_folder(sc_repo, bad).status == "failed", bad)
        rshared = scratch_folder(w.home, "260101-home")
        chk("scratch:a-no-create-folder-uses-the-shared-root", rshared.status == "found"
            and rshared.path == shared_scratch_root() / "260101-home" and rshared.path.is_dir(), repr(rshared))
        rc_sc, out_sc = None, io.StringIO()
        with contextlib.redirect_stdout(out_sc):
            rc_sc = main(["scratch", str(sc_repo), "260101-probe"])
        chk("scratch:cli-prints-the-path", rc_sc == 0 and out_sc.getvalue().strip() == str(rs.path), out_sc.getvalue())

        def sc_make(root, name, age_days, now_):
            d = Path(root) / name
            (d / "sub").mkdir(parents=True, exist_ok=True)
            f = d / "sub" / "f.txt"
            f.write_text("x" * 2048, encoding="utf-8")
            t = now_ - age_days * 86400.0
            for p in (f, d / "sub", d):
                os.utime(str(p), (t, t))
            return d

        sc_now = time.time()
        sc_root = sc_store / SCRATCH_DIR
        (sc_store / "plans").mkdir(exist_ok=True)
        (sc_store / "plans" / "260101_OPEN_PLAN.md").write_text("# open\n", encoding="utf-8")
        d_old = sc_make(sc_root, "260101-old", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        d_edge = sc_make(sc_root, "260101-edge", SCRATCH_MAX_AGE_DAYS - 0.5, sc_now)
        d_young_file = sc_make(sc_root, "260101-oldfolder-newfile", 40, sc_now)
        os.utime(str(d_young_file / "sub" / "f.txt"), (sc_now - 3600, sc_now - 3600))
        d_open = sc_make(sc_root, "260101_OPEN_PLAN", 40, sc_now)
        d_gone_plan = sc_make(sc_root, "260101_ARCHIVED_PLAN", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        d_shared = sc_make(shared_scratch_root(), "260101-shared-old", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        ronly = sc_make(sc_root, "260101-readonly", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        os.chmod(str(ronly / "sub" / "f.txt"), stat.S_IREAD)
        os.utime(str(ronly / "sub" / "f.txt"), (sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400, sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400))
        os.utime(str(ronly / "sub"), (sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400, sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400))
        os.utime(str(ronly), (sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400, sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400))
        keep_outside = w.area("outside")
        (keep_outside / "precious.txt").write_text("keep\n", encoding="utf-8")
        d_link = sc_root / "260101-link"
        linked = False
        try:
            os.symlink(str(keep_outside), str(d_link), target_is_directory=True)
            linked = True
        except (OSError, NotImplementedError):
            pass
        junction_inside = sc_make(sc_root, "260101-has-junction", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        junctioned = False
        if os.name == "nt":
            import subprocess
            made_j = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction_inside / "j"), str(keep_outside)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            junctioned = made_j.returncode == 0 and (junction_inside / "j" / "precious.txt").is_file()
            os.utime(str(junction_inside), (sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400, sc_now - (SCRATCH_MAX_AGE_DAYS + 1) * 86400))
        rows = scratch_clean(now=sc_now)
        by = {os.path.basename(r[1]): r for r in rows}
        chk("scratch-clean:old-plan-less-folder-is-deleted", "260101-old" in by and by["260101-old"][0] == "DELETED"
            and not d_old.exists() and by["260101-old"][2] == 2048, repr(rows))
        chk("scratch-clean:under-the-limit-stays", d_edge.is_dir() and "260101-edge" not in by, repr(rows))
        chk("scratch-clean:a-new-file-in-an-old-folder-keeps-it", d_young_file.is_dir()
            and "260101-oldfolder-newfile" not in by, repr(rows))
        chk("scratch-clean:an-open-plan-is-reported-and-kept", d_open.is_dir()
            and by.get("260101_OPEN_PLAN", ("",))[0] == "STALE-OPEN", repr(rows))
        chk("scratch-clean:an-archived-plans-leftover-is-plan-less", not d_gone_plan.exists()
            and by.get("260101_ARCHIVED_PLAN", ("",))[0] == "DELETED", repr(rows))
        chk("scratch-clean:the-shared-root-is-swept", not d_shared.exists()
            and by.get("260101-shared-old", ("",))[0] == "DELETED", repr(rows))
        chk("scratch-clean:read-only-files-are-deleted", not ronly.exists()
            and by.get("260101-readonly", ("",))[0] == "DELETED", repr(rows))
        if linked:
            chk("scratch-clean:a-link-entry-is-refused", by.get("260101-link", ("",))[0] == "FAILED"
                and (keep_outside / "precious.txt").is_file() and os.path.lexists(str(d_link)), repr(rows))
            os.unlink(str(d_link))
        else:
            skip("scratch-clean:a-link-entry-is-refused", "this user cannot create a symlink")
        chk("scratch-clean:nothing-left-half-renamed", not [n for n in os.listdir(str(sc_root)) if n.startswith(".deleting-")],
            repr(os.listdir(str(sc_root))))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.root / "no-such-root")
        d_shared2 = sc_make(shared_scratch_root(), "260101-shared-again", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        rows_m = scratch_clean(now=sc_now)
        chk("scratch-clean:a-missing-store-repo-still-sweeps-shared", not d_shared2.exists()
            and not [r for r in rows_m if r[0] == "FAILED"], repr(rows_m))
        os.environ["AGENT_PLAYBOOK_STORES"] = str(w.stores)
        plan_open = sc_store / "plans" / "260101_OPEN_PLAN.md"
        rows_c = scratch_close(plan_open)
        chk("scratch-close:refuses-while-the-project-file-is-there", rows_c and rows_c[0][0] == "FAILED" and d_open.is_dir(), repr(rows_c))
        plan_open.unlink()
        rows_c = scratch_close(plan_open)
        chk("scratch-close:deletes-only-that-plans-folder", rows_c and rows_c[0][0] == "DELETED" and not d_open.exists()
            and d_edge.is_dir(), repr(rows_c))
        chk("scratch-close:nothing-there-is-no-rows", scratch_close(plan_open) == [])
        outsider = w.area("notstore") / "plans" / "260101_X.md"
        outsider.parent.mkdir(parents=True, exist_ok=True)
        sc_make(outsider.parent.parent / SCRATCH_DIR, "260101_X", 1, sc_now)
        chk("scratch-close:a-plan-outside-the-store-repo-deletes-nothing", scratch_close(outsider) == []
            and (outsider.parent.parent / SCRATCH_DIR / "260101_X").is_dir())
        out_sc = io.StringIO()
        sc_make(sc_root, "260101-cli", SCRATCH_MAX_AGE_DAYS + 1, sc_now)
        with contextlib.redirect_stdout(out_sc):
            rc_sc = main(["scratch-clean"])
        chk("scratch-clean:cli-reports-the-deletion", rc_sc == 0 and "DELETED\t" in out_sc.getvalue()
            and "260101-cli" in out_sc.getvalue(), out_sc.getvalue())
        # --- every refusal of the delete path, one case each ---
        ref_now = time.time()
        for odd in ("foo\n", "CON", "nul.txt", "LPT1"):
            chk("scratch:refuses-name:%r" % odd, scratch_folder(sc_repo, odd).status == "failed", repr(odd))
        fresh_repo = w.repo(w.area("scfresh") / "r", url="https://github.com/o/scfresh.git")
        chk("scratch:reports-a-newly-created-store", scratch_folder(fresh_repo, "n").status == "created")
        reuse = scratch_folder(sc_repo, "260101-reused").path
        os.utime(str(reuse), (ref_now - 40 * 86400, ref_now - 40 * 86400))
        scratch_folder(sc_repo, "260101-reused")
        chk("scratch:reusing-a-folder-refreshes-its-time", time.time() - os.stat(str(reuse)).st_mtime < 3600)

        # A junction as an entry, and a junction inside an entry: never measured through, never followed.
        busy = w.area("busy")
        (busy / "big.txt").write_text("y" * 4096, encoding="utf-8")
        if os.name == "nt":
            import subprocess
            mk = lambda link, tgt: subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tgt)],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            top_j = sc_root / "260101-top-junction"
            if mk(top_j, busy):
                rows_t = scratch_clean(now=ref_now + 40 * 86400)
                row_t = [r for r in rows_t if os.path.basename(r[1]) == "260101-top-junction"]
                chk("scratch-clean:a-junction-entry-is-refused", row_t and row_t[0][0] == "FAILED"
                    and (busy / "big.txt").is_file() and os.path.lexists(str(top_j)), repr(rows_t))
                os.rmdir(str(top_j))
            else:
                skip("scratch-clean:a-junction-entry-is-refused", "no junction on this system")
            has_j = sc_make(sc_root, "260101-measured", 1, ref_now)
            if mk(has_j / "j", busy):
                newest_j, size_j = _scratch_measure(has_j)
                chk("scratch-measure:does-not-count-through-a-junction", size_j == 2048, repr(size_j))
                real_scandir = os.scandir
                seen_j = []

                def spying_scandir(p):
                    seen_j.append(str(p))
                    return real_scandir(p)
                os.scandir = spying_scandir
                try:
                    _scratch_measure(has_j)
                finally:
                    os.scandir = real_scandir
                chk("scratch-measure:never-enters-a-junction", not [p for p in seen_j if p.endswith(os.sep + "j")], repr(seen_j))
                os.rmdir(str(has_j / "j"))
            else:
                skip("scratch-measure:does-not-count-through-a-junction", "no junction on this system")

        # An unreadable subfolder: the age is unknown, so nothing is deleted and the row says so.
        unread = sc_make(sc_root, "260101-unreadable", 40, ref_now)
        real_scandir = os.scandir

        def denying_scandir(p):
            if str(p).endswith("sub"):
                raise PermissionError(13, "denied (selftest)")
            return real_scandir(p)
        os.scandir = denying_scandir
        try:
            rows_u = scratch_clean(now=ref_now)
        finally:
            os.scandir = real_scandir
        row_u = [r for r in rows_u if os.path.basename(r[1]) == "260101-unreadable"]
        chk("scratch-clean:an-unreadable-subfolder-fails-closed", unread.is_dir() and (unread / "sub" / "f.txt").is_file()
            and row_u and row_u[0][0] == "FAILED", repr(rows_u))
        # The same failure must not stop the entries after it, in this root or in the next.
        later = sc_make(sc_root, "260101-unreadable2", 40, ref_now)
        later_shared = sc_make(shared_scratch_root(), "260101-after-failure", 40, ref_now)
        os.scandir = lambda p: (_ for _ in ()).throw(PermissionError(13, "denied (selftest)")) if str(p).endswith(os.sep + "260101-unreadable" + os.sep + "sub") else real_scandir(p)
        try:
            rows_u = scratch_clean(now=ref_now)
        finally:
            os.scandir = real_scandir
        chk("scratch-clean:one-failure-does-not-stop-the-sweep", not later.exists() and not later_shared.exists()
            and unread.is_dir(), repr(rows_u))
        import shutil as _sc_shutil
        _sc_shutil.rmtree(str(unread))

        # A plans/ the sweep cannot read: cannot tell means left in place.
        plan_unknown = sc_make(sc_root, "260101_UNKNOWN_PLAN", 40, ref_now)
        real_stat = os.stat

        def denying_stat(p, *a, **k):
            if str(p).endswith("260101_UNKNOWN_PLAN.md"):
                raise PermissionError(13, "denied (selftest)")
            return real_stat(p, *a, **k)
        os.stat = denying_stat
        try:
            rows_p = scratch_clean(now=ref_now)
        finally:
            os.stat = real_stat
        row_p = [r for r in rows_p if os.path.basename(r[1]) == "260101_UNKNOWN_PLAN"]
        chk("scratch-clean:an-unreadable-plan-check-keeps-the-folder", plan_unknown.is_dir() and row_p and row_p[0][0] == "FAILED", repr(rows_p))
        _sc_shutil.rmtree(str(plan_unknown))

        # A rename that fails leaves the entry whole; a delete that fails leaves one named leftover.
        no_rename = sc_make(sc_root, "260101-no-rename", 40, ref_now)
        real_rename = os.rename

        def failing_rename(a, b):
            if "260101-no-rename" in str(a):
                raise PermissionError(32, "in use (selftest)")
            return real_rename(a, b)
        os.rename = failing_rename
        try:
            rows_r = scratch_clean(now=ref_now)
        finally:
            os.rename = real_rename
        row_r = [r for r in rows_r if os.path.basename(r[1]) == "260101-no-rename"]
        chk("scratch-clean:a-failed-rename-leaves-it-whole", (no_rename / "sub" / "f.txt").is_file() and row_r and row_r[0][0] == "FAILED"
            and "in use" in row_r[0][4], repr(rows_r))
        _sc_shutil.rmtree(str(no_rename))
        no_delete = sc_make(sc_root, "260101-no-delete", 40, ref_now)
        real_rmtree = _sc_shutil.rmtree

        def failing_rmtree(*a, **k):
            raise OSError(5, "cannot delete (selftest)")
        _sc_shutil.rmtree = failing_rmtree
        try:
            rows_d = scratch_clean(now=ref_now)
        finally:
            _sc_shutil.rmtree = real_rmtree
        row_d = [r for r in rows_d if os.path.basename(r[1]) == "260101-no-delete"]
        left = [n for n in os.listdir(str(sc_root)) if n.startswith(".deleting-")]
        chk("scratch-clean:a-failed-delete-names-its-leftover", row_d and row_d[0][0] == "FAILED" and len(left) == 1
            and left[0] in row_d[0][4], repr(rows_d))
        # A leftover with recent activity may be another sweep's delete: reported. An old one is retried and goes.
        os.utime(str(sc_root / left[0]))
        rows_l = scratch_clean(now=time.time())
        chk("scratch-clean:a-recent-leftover-is-reported", any(os.path.basename(r[1]) == left[0] and r[0] == "FAILED" for r in rows_l), repr(rows_l))
        rows_l = scratch_clean(now=time.time() + 2 * 86400)
        chk("scratch-clean:an-old-leftover-is-retried", not os.path.lexists(str(sc_root / left[0])), repr(rows_l))

        # A read-only file directly under a scratch root.
        ro_file = sc_root / "260101-stray.txt"
        ro_file.write_text("x\n", encoding="utf-8")
        os.chmod(str(ro_file), stat.S_IREAD)
        os.utime(str(ro_file), (ref_now - 40 * 86400, ref_now - 40 * 86400))
        rows_f = scratch_clean(now=ref_now)
        chk("scratch-clean:a-read-only-stray-file-goes", not ro_file.exists() and not [r for r in rows_f if r[0] == "FAILED"], repr(rows_f))

        # The error hook never reaches through a link.
        hook_target = w.area("hooktarget") / "t.txt"
        hook_target.write_text("x\n", encoding="utf-8")
        os.chmod(str(hook_target), stat.S_IREAD)
        hook_link = w.area("hooklink") / "l"
        try:
            os.symlink(str(hook_target), str(hook_link))
            raised = False
            try:
                _scratch_clear_and_retry(os.unlink, str(hook_link), PermissionError(13, "selftest"))
            except PermissionError:
                raised = True
            chk("scratch-hook:a-link-is-not-chmodded", raised and not os.access(str(hook_target), os.W_OK) and os.path.lexists(str(hook_link)))
            os.unlink(str(hook_link))
        except (OSError, NotImplementedError):
            skip("scratch-hook:a-link-is-not-chmodded", "this user cannot create a symlink")
        os.chmod(str(hook_target), stat.S_IWRITE)
        raised = False
        try:
            _scratch_clear_and_retry(os.open, str(hook_target), TypeError("selftest"))
        except TypeError:
            raised = True
        chk("scratch-hook:only-delete-calls-are-retried", raised)

        # A scratch root that is a link, or not a folder; a scan that fails; an invalid store.
        link_store = w.store("linkroot-abcdef", "remote example.com/o/linkroot\n")
        target_root = w.area("rootlink-target")
        sc_make(target_root, "260101-behind-a-link", 40, ref_now)
        try:
            os.symlink(str(target_root), str(link_store / SCRATCH_DIR), target_is_directory=True)
            rows_rl = scratch_clean(now=ref_now)
            chk("scratch-clean:a-root-that-is-a-link-is-refused", (target_root / "260101-behind-a-link").is_dir()
                and any(r[0] == "FAILED" and r[1] == str(link_store / SCRATCH_DIR) for r in rows_rl), repr(rows_rl))
            chk("scratch:a-root-that-is-a-link-is-refused", _scratch_root_problem(link_store / SCRATCH_DIR) is not None)
            os.unlink(str(link_store / SCRATCH_DIR))
        except (OSError, NotImplementedError):
            skip("scratch-clean:a-root-that-is-a-link-is-refused", "this user cannot create a symlink")
        (link_store / SCRATCH_DIR).write_text("a file\n", encoding="utf-8")
        rows_rf = scratch_clean(now=ref_now)
        chk("scratch-clean:a-root-that-is-a-file-is-refused", (link_store / SCRATCH_DIR).is_file()
            and any(r[0] == "FAILED" and r[1] == str(link_store / SCRATCH_DIR) for r in rows_rf), repr(rows_rf))
        (link_store / SCRATCH_DIR).unlink()
        bad_store = w.stores / "broken-abcdef"
        bad_store.mkdir()
        (bad_store / STORE_FILE).write_text("not a store line\n", encoding="utf-8")
        bad_old = sc_make(bad_store / SCRATCH_DIR, "260101-in-broken", 40, ref_now)
        rows_b = scratch_clean(now=ref_now)
        chk("scratch-clean:an-invalid-store-is-named-and-not-swept", bad_old.is_dir()
            and any(r[0] == "FAILED" and "invalid STORE" in r[4] for r in rows_b), repr(rows_b))
        _sc_shutil.rmtree(str(bad_store))
        real_scan = globals()["scan_stores"]
        globals()["scan_stores"] = lambda root=None: ("failed", [], [], "selftest scan failure")
        kept = sc_make(sc_root, "260101-scan-failed", 40, ref_now)
        shared_during = sc_make(shared_scratch_root(), "260101-scan-failed-shared", 40, ref_now)
        try:
            rows_s = scratch_clean(now=ref_now)
        finally:
            globals()["scan_stores"] = real_scan
        chk("scratch-clean:a-failed-scan-sweeps-no-store-but-still-the-shared-root", kept.is_dir() and not shared_during.exists()
            and any(r[0] == "FAILED" and "not scanned" in r[4] for r in rows_s), repr(rows_s))
        _sc_shutil.rmtree(str(kept))

        # --plan: each gate alone.
        gate_folder = sc_make(sc_root, "260101_GATE", 1, ref_now)
        plans_dir = sc_store / "plans"
        for bad_plan in (plans_dir / "260101_GATE", plans_dir / "260101_GATE.txt"):
            rows_g = scratch_close(bad_plan)
            chk("scratch-close:refuses-a-non-md-path:%s" % bad_plan.name, gate_folder.is_dir() and rows_g and rows_g[0][0] == "FAILED", repr(rows_g))
        other = w.area("otherroot")
        (other / STORE_FILE).write_text("remote example.com/o/other\n", encoding="utf-8")
        sc_make(other / SCRATCH_DIR, "260101_GATE2", 1, ref_now)
        (other / "plans").mkdir()
        chk("scratch-close:a-store-outside-the-store-repo-deletes-nothing", scratch_close(other / "plans" / "260101_GATE2.md") == []
            and (other / SCRATCH_DIR / "260101_GATE2").is_dir())
        no_id = w.stores / "noid-abcdef"
        sc_make(no_id / SCRATCH_DIR, "260101_GATE3", 1, ref_now)
        (no_id / "plans").mkdir()
        chk("scratch-close:a-folder-without-a-STORE-deletes-nothing", scratch_close(no_id / "plans" / "260101_GATE3.md") == []
            and (no_id / SCRATCH_DIR / "260101_GATE3").is_dir())
        _sc_shutil.rmtree(str(no_id))
        try:
            gate_link_target = w.area("gatelink")
            os.symlink(str(gate_link_target), str(sc_root / "260101_GATE4"), target_is_directory=True)
            rows_g = scratch_close(plans_dir / "260101_GATE4.md")
            chk("scratch-close:a-link-is-refused", rows_g and rows_g[0][0] == "FAILED" and gate_link_target.is_dir(), repr(rows_g))
            rs_l = scratch_folder(sc_repo, "260101_GATE4")
            chk("scratch:a-name-that-is-a-link-is-refused", rs_l.status == "failed", repr(rs_l))
            os.unlink(str(sc_root / "260101_GATE4"))
        except (OSError, NotImplementedError):
            skip("scratch-close:a-link-is-refused", "this user cannot create a symlink")

        # Making the junction refreshed its folder's time, so this sweep runs with a later clock.
        if junctioned:
            rows_j = scratch_clean(now=sc_now + (SCRATCH_MAX_AGE_DAYS + 6) * 86400.0)
            chk("scratch-clean:a-junction-inside-does-not-reach-its-target", (keep_outside / "precious.txt").is_file()
                and not junction_inside.exists(), repr(rows_j))
        else:
            skip("scratch-clean:a-junction-inside-does-not-reach-its-target", "no junction on this system")

        # --- the guard against a vacuous creation suite ---
        chk("meta:creation-cases-really-created", sum(1 for n in results if n.startswith(("sibling:", "non-git:creates", "race:"))) >= 5)
    except Exception:
        import traceback
        traceback.print_exc()
        failures.append("selftest-crashed")
    finally:
        EMPTY_WAIT_SECONDS = saved_wait
        _TEST.clear()
        _TEST.update(saved_test)
        if saved_env is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved_env

        def _rm(func, path, _exc):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except OSError:
                pass
        shutil.rmtree(raw_root, onerror=_rm)
    if failures:
        print("SELFTEST FAILED (%d of %d cases): %s" % (len(failures), len(results), ", ".join(failures)), file=sys.stderr)
        return 1
    print("SELFTEST PASSED (%d cases)" % len(results))
    return 0
