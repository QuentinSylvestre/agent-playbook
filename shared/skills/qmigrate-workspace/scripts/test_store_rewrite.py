"""Selftest for the store-repo STORE rewrite (pathmap.store_rewrites, used by apply.py).

  <venv python> -I test_store_rewrite.py

Builds a scratch store repo in a temp dir (AGENT_PLAYBOOK_STORES points at it) with a `local` store for a
scratch non-git folder OLD, one for a folder in OLD's subtree, a `local` store outside OLD, a sibling whose name
only starts with OLD's, and a `remote` store. Moves OLD to NEW, plans the rewrite, checks a dry run changes
nothing, writes the plan the way apply.py does (temp file in the same directory, then replace), and checks
`store-resolver.py find NEW` prints the store `find OLD` printed before the move. Then runs apply.py itself as a
dry run in a sandbox (a fake home through USERPROFILE/HOME/CODEX_HOME, a scratch store repo, an explicit --work,
no --config-repo): it must report the re-key and write nothing but its dry-run log. It still reads the real process
table, read-only. apply.py takes Windows paths only (the skill is Windows only, SKILL.md § Limitations), so off
Windows that case prints a SKIP line and is not run; the store-rewrite cases run everywhere. Exit 0 when every case
that ran passes; one summary line.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathmap import load_store_resolver, store_rewrites  # noqa: E402

RESOLVER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "qdream", "scripts", "store-resolver.py")
APPLY_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apply.py")
results = []
skipped = []


def chk(name, ok, detail=""):
    results.append((name, bool(ok)))
    if not ok:
        print("FAIL %s %s" % (name, detail))


def cli_find(folder):
    r = subprocess.run([sys.executable, "-I", RESOLVER, "find", folder], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def snapshot(files):
    return {f: open(f, "rb").read() for f in files}


def write_atomic(path, data):
    tmp = path + ".qmw-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def tree_state(root):
    out = {}
    for dp, _dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            out[p] = (open(p, "rb").read(), os.stat(p).st_mtime_ns)
    return out


def skip(names, why):
    skipped.extend(names)
    print("SKIP %s (%s)" % (", ".join(names), why))


APPLY_DRY_RUN_CASES = ("apply-dry-run:exit-0", "apply-dry-run:reports-store-re-key",
                       "apply-dry-run:only-its-log-is-new", "apply-dry-run:nothing-else-changed")


def case_apply_dry_run(sr, base):
    """apply.py without --apply, in a sandbox: it must report the re-key and write nothing but its dry-run log."""
    if os.name != "nt":
        # apply.py's PathMap accepts drive-letter paths only: the migration is Windows only by design.
        skip(APPLY_DRY_RUN_CASES, "not Windows: apply.py takes Windows paths with a drive letter only")
        return
    norm = sr.norm_path
    root = os.path.join(os.path.realpath(base), "dry")
    home, work, stores = os.path.join(root, "home"), os.path.join(root, "work"), os.path.join(root, "stores")
    old, new = os.path.join(root, "ws", "Old Proj"), os.path.join(root, "ws2", "New Proj")
    for d in (os.path.join(home, ".claude", "projects"), os.path.dirname(old), new):
        os.makedirs(d)
    d_old = sr.fixture_store(stores, "old-proj-aaaaaa", "local %s\n" % norm(old))
    f_old = os.path.join(str(d_old), "STORE")
    before = tree_state(root)
    env = dict(os.environ, USERPROFILE=home, HOME=home, CODEX_HOME=os.path.join(home, ".codex"),
               AGENT_PLAYBOOK_STORES=stores)
    r = subprocess.run([sys.executable, "-I", APPLY_PY, "--old", old, "--new", new, "--work", work],
                       capture_output=True, text=True, env=env, timeout=300)
    out = r.stdout + r.stderr
    chk("apply-dry-run:exit-0", r.returncode == 0, out[-1500:])
    chk("apply-dry-run:reports-store-re-key", ("%s -> local %s" % (f_old, norm(new))) in out
        and "would re-key 1 STORE file(s)" in out, out[-1500:])
    after = tree_state(root)
    logs = [p for p in after if p not in before]
    chk("apply-dry-run:only-its-log-is-new",
        len(logs) == 1 and os.path.dirname(logs[0]) == work and os.path.basename(logs[0]).startswith("dryrun-"), repr(logs))
    chk("apply-dry-run:nothing-else-changed", {p: v for p, v in after.items() if p not in logs} == before)


def main():
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    base = tempfile.mkdtemp(prefix="qmw-store-")
    try:
        sr = load_store_resolver()
        # the store root in long form (the resolver prints it so); the workspace paths keep the temp dir's
        # 8.3 form when it has one, so the STORE lines are only ever built through the resolver's normalization
        stores = os.path.join(os.path.realpath(base), "stores")
        os.environ["AGENT_PLAYBOOK_STORES"] = stores
        old, new = os.path.join(base, "ws", "Old Proj"), os.path.join(base, "ws2", "New Proj")
        sub, outside, sibling = os.path.join(old, "Sub"), os.path.join(base, "ws", "other"), os.path.join(base, "ws", "Old Proj2")
        for d in (sub, outside, sibling, os.path.dirname(new)):
            os.makedirs(d)
        d_old = sr.fixture_store(stores, "old-proj-aaaaaa", "local %s\n" % sr.norm_path(old))
        d_sub = sr.fixture_store(stores, "sub-bbbbbb", "local %s\n" % sr.norm_path(sub))
        d_out = sr.fixture_store(stores, "other-cccccc", "local %s\n" % sr.norm_path(outside))
        d_sib = sr.fixture_store(stores, "old-proj2-dddddd", "local %s\n" % sr.norm_path(sibling))
        d_rem = sr.fixture_store(stores, "repo-eeeeee", "remote github.com/o/r\npath x\n")
        files = [os.path.join(str(d), "STORE") for d in (d_old, d_sub, d_out, d_sib, d_rem)]
        f_old, f_sub = files[0], files[1]
        before = snapshot(files)
        rc_old, find_old = cli_find(old)
        rc_sub, find_sub = cli_find(sub)
        chk("setup:find-old-hits-old-store", rc_old == 0 and os.path.normcase(find_old) == os.path.normcase(str(d_old)), find_old)
        chk("setup:find-sub-hits-sub-store", rc_sub == 0 and os.path.normcase(find_sub) == os.path.normcase(str(d_sub)), find_sub)

        os.rename(old, new)
        st, rws, inv, why = store_rewrites(sr, old, new)
        plan = {p: (nb, note, blk) for p, nb, note, blk in rws}
        chk("plan:status-ok", st == "ok" and not inv, "%s %s %r" % (st, why, inv))
        chk("plan:exactly-old-and-sub", set(plan) == {f_old, f_sub}, repr(sorted(plan)))
        chk("plan:old-line-is-resolver-form-of-new",
            plan.get(f_old, (None,))[0] == ("local %s\n" % sr.norm_path(new)).encode("utf-8"), repr(plan.get(f_old)))
        chk("plan:sub-line-keeps-relative-location",
            plan.get(f_sub, (None,))[0] == ("local %s\n" % sr.norm_path(os.path.join(new, "Sub"))).encode("utf-8"), repr(plan.get(f_sub)))
        chk("plan:no-notes-no-blockers", all(not n and not b for _nb, n, b in plan.values()), repr(plan))

        # dry run: planning (what apply.py does without --apply) writes nothing
        chk("dry-run:all-stores-byte-identical", snapshot(files) == before)
        chk("dry-run:no-temp-files", not any(os.path.exists(f + ".qmw-tmp") for f in files))

        for p, (nb, _n, _b) in plan.items():
            write_atomic(p, nb)
        after = snapshot(files)
        chk("apply:old-store-names-new", after[f_old] == plan[f_old][0])
        chk("apply:others-byte-identical", all(after[f] == before[f] for f in files[2:]))
        chk("apply:no-temp-files", not any(os.path.exists(f + ".qmw-tmp") for f in files))
        chk("apply:store-dirs-not-renamed", all(os.path.isdir(str(d)) for d in (d_old, d_sub, d_out, d_sib, d_rem)))
        rc_new, find_new = cli_find(new)
        chk("apply:find-new-equals-find-old-before", rc_new == 0 and find_new == find_old, "%r vs %r" % (find_new, find_old))
        rc_ns, find_ns = cli_find(os.path.join(new, "Sub"))
        chk("apply:find-new-sub-equals-find-sub-before", rc_ns == 0 and find_ns == find_sub, "%r vs %r" % (find_ns, find_sub))
        st2, rws2, _i, _w = store_rewrites(sr, old, new)
        chk("rerun:idempotent-nothing-to-do", st2 == "ok" and rws2 == [], repr(rws2))

        # a second store already holding NEW's line is a blocker, never a silent duplicate
        shutil.copyfile(f_old, os.path.join(str(sr.fixture_store(stores, "dup-ffffff", "x")), "STORE"))
        write_atomic(f_old, before[f_old])
        _st, rws3, _i, _w = store_rewrites(sr, old, new)
        chk("collision:flagged-as-blocker", [(p, b) for p, _nb, _n, b in rws3] == [(f_old, True)], repr(rws3))

        os.environ["AGENT_PLAYBOOK_STORES"] = os.path.join(base, "no-such-root")
        st4, rws4, _i, _w = store_rewrites(sr, old, new)
        chk("missing-root:status-missing-nothing-planned", st4 == "missing" and rws4 == [], st4)

        case_apply_dry_run(sr, base)
    finally:
        if saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved
        shutil.rmtree(base, ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    print("test_store_rewrite: %d/%d cases passed%s%s" % (len(results) - len(failed), len(results),
                                                           "; %d skipped" % len(skipped) if skipped else "",
                                                           "" if not failed else "; FAILED: " + ", ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
