#!/usr/bin/env python3
"""verify-citations.py -- enforce the canonical-section lockstep rule:
every cited site must contain a live reference to the canonical section,
else the canonical-source-of-truth section's rename-guard is provably false.

Checks that every cited site for each rename-guarded canonical section (and
each cross-file-cited stable step-ID tag) still contains a live reference to
it. The checks are data-driven: each row of citation-checks.tsv (same
directory as this script) names a canonical section/tag, the literal pattern
that proves a citation, and the sites that must contain it -- the
un-retireable heading set the /qdream governance-retirement pass must never
propose retiring. See Usage/Output/Exit codes below for the contract.

Run with the playbook venv (<repo>/.venv-agent-playbook); any other
interpreter exits 2 ("guard did not run: venv missing"). Stdlib only,
Python 3.8+. A guard run reads files only: it writes nothing, runs no git
and touches no network. --selftest writes small fixture trees in a fresh
folder under ~/.agent-playbook (or VERIFY_CITATIONS_SELFTEST_DIR), never the
system temp folder, and removes them afterwards.

Usage:
  verify-citations.py [--help] [<repo-root>]
  verify-citations.py --selftest
The optional <repo-root> defaults to the repo that holds this script (it
sits at shared/skills/qconfig-sync/scripts/), never the cwd: a session
whose cwd is another git repo must still check agent-playbook. An explicit
<repo-root> is used as given (relative to the cwd). Any convention change must update qconfig-sync/SKILL.md's documented
invocations in the same commit.

Output (stdout, UTF-8, LF): one tab-separated line per cited site:
  <STATUS>\t<canonical-section>\t<cited-site>\t<hit-count>
STATUS in {OK, MISSING}. <hit-count> is the number of LINES of the site that
contain the literal pattern (case-sensitive). Trailing SUMMARY line records
totals.

Two later blocks emit rows on the same channel with DIFFERENT column meanings
-- parse on the first field, never on position alone:
  OK|MISSING\tmarker:<section>\t<file>:<line>\t<0|1>
      Marker-subset check. Column 2 carries a `marker:` prefix; column 3 is a
      file:line, not a plain path. Counted in the SUMMARY totals and in the
      exit code, like any other OK/MISSING row.
  COVERAGE\t<heading>\t<citing-file-count>\t0
      Citation-traffic advisory. Column 3 is a COUNT, not a cited site.
      ADVISORY ONLY: never counted in SUMMARY, never affects the exit code.
When anything is MISSING, a REMEDIATION line follows SUMMARY. A site under memory/ in a tree with no
memory/ at all, or naming a memory file this user's memory does not hold (user memory is each user's own,
in their store repo), prints SKIPPED, not MISSING.

Table format (citation-checks.tsv): comment (#) and empty lines are skipped;
every other line is label<TAB>pattern<TAB>site1<TAB>site2... Runs of tabs
count as one separator (the field split of the former sh guard). A row with
no pattern field, or with a pattern but no site, is malformed and exits 2
when the run reaches it.

Line reading: the table and the scanned markdown are read as UTF-8 with a
leading BOM dropped. Markdown lines drop one trailing CR (a CRLF file scans
like its LF copy); table lines keep it, so a CRLF table puts a CR on each
row's last site and that site reports MISSING. Cited sites are matched as
bytes, line by line.

Exit codes:
  0   all cited sites contain at least one reference to their canonical section.
  1   one or more cited sites are missing references (rename-guard violation).
  2   precondition failure: repo path invalid, target does not look like an
      agent-playbook repo, checks table missing or malformed, a file
      unreadable, source enumeration failed, an unbalanced code fence, the
      venv guard, or any unexpected error (stderr line
      "verify-citations.py: guard did not run: <reason>"). Rows already
      printed stay on stdout; no SUMMARY follows.
"""
import os
import re
import sys

NAME = "verify-citations.py"
FIXTURES_PREFIX = "shared/skills/qdream/scripts/fixtures/"
SECT = "§"
REMEDIATION = ("Reconcile the canonical section with its callers: restore the citation in the caller, "
               "or extend the section if the caller is right. If a site was deliberately dropped, remove it "
               "from its row in citation-checks.tsv in the same commit. Never delete the row to silence the "
               "guard, and never plant a decorative mention -- the check counts strings, so an unused mention "
               "is a false green.")
HEADING_RE = re.compile(r"^#{1,6} ")
HEADING_STRIP_RE = re.compile(r"^#+ +")
FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
MARKER_RE = re.compile(r"renaming (this|that|the) (heading|section)")


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


class CouldNotRun(Exception):
    """The guard cannot give a verdict (exit 2); the text is the stderr reason."""


def _enc(s):
    return s.encode("utf-8", "surrogateescape")


def _split_lines(text):
    """Lines split on LF only; a final empty piece (after a trailing LF) is not a line."""
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _read_bytes(path):
    """The one file reader (the selftest replaces it to inject a failing read)."""
    with open(path, "rb") as fh:
        return fh.read()


def _read_text(path, what):
    try:
        data = _read_bytes(path)
    except OSError as exc:
        raise CouldNotRun("cannot read %s %s; guard did not run (%s)" % (what, path, exc))
    return data.decode("utf-8-sig", "surrogateescape")


def load_table(tsv_path):
    """-> list of raw row strings (comment and empty lines skipped, CR kept)."""
    if not os.path.isfile(tsv_path):
        raise CouldNotRun("checks table not found: %s" % tsv_path)
    rows = []
    for line in _split_lines(_read_text(tsv_path, "checks table")):
        if line == "" or line.startswith("#"):
            continue
        rows.append(line)
    return rows


def count_hit_lines(path, pattern):
    """Number of lines of the file holding the literal pattern (grep -c -F semantics, bytes)."""
    try:
        data = _read_bytes(path)
    except OSError as exc:
        raise CouldNotRun("cannot read cited site %s; guard did not run (%s)" % (path, exc))
    pat = _enc(pattern)
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return sum(1 for ln in lines if pat in ln)


def list_sources(root):
    """Repo-relative forward-slash paths of every regular *.md (any case) under shared/ and providers/,
    minus the qdream script fixtures, in byte order."""
    out = []

    def onerror(exc):
        raise exc

    for top in ("shared", "providers"):
        top_abs = os.path.join(root, top)
        if not os.path.isdir(top_abs):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(top_abs, onerror=onerror):
                rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
                for fn in filenames:
                    if not fn.lower().endswith(".md"):
                        continue
                    if os.path.islink(os.path.join(dirpath, fn)):
                        continue
                    rel = rel_dir + "/" + fn
                    if rel.startswith(FIXTURES_PREFIX):
                        continue
                    out.append(rel)
        except OSError as exc:
            raise CouldNotRun("could not enumerate source markdown; marker and coverage checks did not run (%s)" % exc)
    out.sort(key=_enc)
    return out


def scan_file(lines):
    """One markdown file -> (marker hits [(line_no, enclosing heading)], headings set, cited segments set,
    unbalanced fence?)."""
    cur = ""
    infence = False
    fencechar = ""
    fencelen = 0
    markers = []
    headings = set()
    segs = set()
    for no, raw in enumerate(lines, 1):
        line = raw[:-1] if raw.endswith("\r") else raw
        if FENCE_RE.match(line):
            fl = line.lstrip(" \t")
            fc = fl[0]
            fn = 0
            while fn < len(fl) and fl[fn] == fc:
                fn += 1
            if not infence:
                infence, fencechar, fencelen = True, fc, fn
            elif fc == fencechar and fn >= fencelen:
                infence = False
            continue
        if infence:
            continue
        if HEADING_RE.match(line):
            cur = HEADING_STRIP_RE.sub("", line, count=1).rstrip(" \t")
            headings.add(cur)
        if MARKER_RE.search(line.lower()) and cur != "":
            markers.append((no, cur))
        rest = line
        while True:
            si = rest.find(SECT)
            if si < 0:
                break
            rest = rest[si + 1:]
            stop = rest.find("`")
            nxt = rest.find(SECT)
            if nxt >= 0 and (stop < 0 or nxt < stop):
                stop = nxt
            seg = rest[:stop] if stop >= 0 else rest
            rest = rest[stop:] if stop >= 0 else ""
            seg = seg.lstrip(" \t").rstrip(".,);:*_ \t")
            if seg:
                segs.add(seg)
    return markers, headings, segs, infence


def run(root, tsv_path, out):
    """The guard. Writes stdout bytes to `out` as it goes; returns the exit code. A CouldNotRun propagates."""
    if not os.path.isdir(root):
        raise CouldNotRun("repo path not found: %s" % root)
    if not os.path.isfile(os.path.join(root, "shared", "AGENTS.md")):
        raise CouldNotRun("%s does not look like an agent-playbook repo" % root)
    rows = load_table(tsv_path)

    ok = fail = 0
    # User memory lives in the store repo behind the `memory` link; where there is no memory/ at all (a fresh
    # clone, CI) a site under it cannot be checked: SKIPPED, never MISSING.
    no_memory = not os.path.isdir(os.path.join(root, "memory"))
    for row in rows:
        fields = [f for f in row.split("\t") if f != ""]
        if len(fields) < 2:
            raise CouldNotRun("malformed checks table row (no pattern field): %r" % row)
        label, pattern, sites = fields[0], fields[1], fields[2:]
        if not sites:
            raise CouldNotRun("malformed checks table row (no site field): %r" % row)
        for site in sites:
            path = os.path.join(root, site)
            if site.startswith("memory/") and (no_memory or not os.path.isfile(path)):
                # user memory is each user's own: a memory file another user's memory lacks is not drift
                out.write(_enc("SKIPPED\t%s\t%s\t0\n" % (label, site)))
                continue
            hits = count_hit_lines(path, pattern) if os.path.isfile(path) else 0
            status = "OK" if hits > 0 else "MISSING"
            if hits > 0:
                ok += 1
            else:
                fail += 1
            out.write(_enc("%s\t%s\t%s\t%d\n" % (status, label, site, hits)))

    labels = set(row.split("\t", 1)[0] for row in rows)

    marker_rows = []
    headings = set()
    cite_files = {}
    unbalanced = []
    for rel in list_sources(root):
        lines = _split_lines(_read_text(os.path.join(root, rel), "source markdown"))
        markers, heads, segs, open_fence = scan_file(lines)
        if open_fence:
            unbalanced.append(rel)
        for no, section in markers:
            section = section.strip("\t")
            if section:
                marker_rows.append((rel, no, section))
        headings |= heads
        for seg in segs:
            cite_files[seg] = cite_files.get(seg, 0) + 1
    if unbalanced:
        raise CouldNotRun("".join("unbalanced code fence in %s; content after it was not scanned\n%s: " % (f, NAME)
                                  for f in unbalanced) + "marker scan failed; guard did not run")

    for rel, no, section in marker_rows:
        if section in labels:
            out.write(_enc("OK\tmarker:%s\t%s:%d\t1\n" % (section, rel, no)))
            ok += 1
        else:
            out.write(_enc("MISSING\tmarker:%s\t%s:%d\t0\n" % (section, rel, no)))
            fail += 1

    coverage = ["COVERAGE\t%s\t%d\t0" % (s, n) for s, n in cite_files.items()
                if n >= 2 and s in headings and s not in labels]
    for line in sorted(coverage, key=_enc):
        out.write(_enc(line + "\n"))

    out.write(_enc("SUMMARY\tok=%d\tmissing=%d\n" % (ok, fail)))
    if fail > 0:
        out.write(_enc("REMEDIATION\t%s\n" % REMEDIATION))
        return 1
    return 0


def run_guarded(root, tsv_path, out, err):
    """run() with CouldNotRun, and any unexpected exception, turned into exit 2 and a stderr line:
    exit 1 means a rename-guard violation, never a crash."""
    try:
        return run(root, tsv_path, out)
    except CouldNotRun as exc:
        err.write("%s: %s\n" % (NAME, exc))
        return 2
    except Exception as exc:
        err.write("%s: guard did not run: %s: %s\n" % (NAME, type(exc).__name__, exc))
        return 2


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest_dir():
    """Scratch for fixture trees: next to this script's repo, never the system temp folder."""
    import tempfile
    base = os.environ.get("VERIFY_CITATIONS_SELFTEST_DIR") or os.path.join(os.path.expanduser("~"), ".agent-playbook")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="verify-citations-selftest-", dir=base)


def _write(path, text, bom=False, crlf=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    with open(path, "wb") as fh:
        fh.write(data)


def _fixture(root, bom=False, crlf=False, drop_ref=False, fence_open=False):
    """A minimal playbook tree and its table; returns the table path."""
    agents = ("# Shared\n\n## Alpha Rules\n\nRenaming this heading breaks citations.\n\n"
              "## Beta\n\nSee `" + SECT + " Gamma` and " + SECT + " Alpha Rules.\n\n"
              "```\n# Not a heading\nrenaming this heading inside a fence is quoted\n```\n"
              "````\n```\nrenaming the section inside a nested fence is quoted\n```\n````\n")
    # SKILL.md's first line is a heading cited from two files, so a BOM left on line 1 drops a COVERAGE row.
    skill = ("## Gamma\n\nCites " + SECT + " Gamma.\nAnd `x " + SECT + " Beta`.\n"
             + ("" if drop_ref else "Uses Alpha Rules and STEP-ONE.\n")
             + ("````\nunclosed\n" if fence_open else ""))
    other = "Cites " + SECT + " Beta.\nAlso " + SECT + " Shared.\n"
    _write(os.path.join(root, "shared", "AGENTS.md"), agents, bom, crlf)
    _write(os.path.join(root, "shared", "skills", "demo", "SKILL.md"), skill, bom, crlf)
    _write(os.path.join(root, "providers", "x", "NOTE.MD"), other, bom, crlf)
    _write(os.path.join(root, "shared", "skills", "qdream", "scripts", "fixtures", "f.md"),
           "## Fixture\n\nrenaming this heading is ignored here\n")
    tsv = os.path.join(root, "citation-checks.tsv")
    _write(tsv, "# table\n\nAlpha Rules\tAlpha Rules\tshared/AGENTS.md\tshared/skills/demo/SKILL.md\n"
                "STEP-ONE\tSTEP-ONE\tshared/skills/demo/SKILL.md\n")
    return tsv


def selftest():
    import io
    import shutil
    fails = []
    checks = [0]

    def check(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s %s" % (name, detail))
            print("FAIL\t%s\t%s" % (name, detail))

    def go(root, tsv):
        out, err = io.BytesIO(), io.StringIO()
        try:
            code = run_guarded(root, tsv, out, err)
        except Exception as exc:  # an escaped exception is a selftest failure, reported as code -1
            code = -1
            err.write("ESCAPED %s: %s\n" % (type(exc).__name__, exc))
        return code, out.getvalue().decode("utf-8"), err.getvalue()

    def append(path, text):
        with open(path, "ab") as fh:
            fh.write(text.encode("utf-8"))

    def go_failing_read(root, tsv, fail_rel, exc_type):
        """go() with the module's reader raising exc_type for the one file fail_rel."""
        g = globals()
        real = g["_read_bytes"]

        def fake(path):
            if os.path.normpath(path).replace(os.sep, "/").endswith("/" + fail_rel):
                raise exc_type("injected read failure")
            return real(path)
        g["_read_bytes"] = fake
        try:
            return go(root, tsv)
        finally:
            g["_read_bytes"] = real

    base = _selftest_dir()
    try:
        ok_root = os.path.join(base, "ok")
        code, ok_out, _ = go(ok_root, _fixture(ok_root))
        expected = ("OK\tAlpha Rules\tshared/AGENTS.md\t2\n"
                    "OK\tAlpha Rules\tshared/skills/demo/SKILL.md\t1\n"
                    "OK\tSTEP-ONE\tshared/skills/demo/SKILL.md\t1\n"
                    "OK\tmarker:Alpha Rules\tshared/AGENTS.md:5\t1\n"
                    "COVERAGE\tBeta\t2\t0\n"
                    "COVERAGE\tGamma\t2\t0\n"
                    "SUMMARY\tok=4\tmissing=0\n")
        check("all-ok exit 0", code == 0, "got %d" % code)
        check("all-ok stdout", ok_out == expected, repr(ok_out))

        miss_root = os.path.join(base, "missing")
        code, out, _ = go(miss_root, _fixture(miss_root, drop_ref=True))
        check("missing exit 1", code == 1, "got %d" % code)
        check("missing rows", "MISSING\tAlpha Rules\tshared/skills/demo/SKILL.md\t0\n" in out
              and "MISSING\tSTEP-ONE\tshared/skills/demo/SKILL.md\t0\n" in out, repr(out))
        check("missing summary+remediation", "SUMMARY\tok=2\tmissing=2\nREMEDIATION\t" in out, repr(out))

        # a memory/ site: checked when user memory is there, SKIPPED when the tree has no memory/ at all
        mem_root = os.path.join(base, "memsite")
        mem_tsv = _fixture(mem_root)
        append(mem_tsv, "Mem Rule\tMem Rule\tmemory/MEMORY.md\n")
        code, out, _ = go(mem_root, mem_tsv)
        check("memory site, no memory/: skipped, exit 0", code == 0 and "SKIPPED\tMem Rule\tmemory/MEMORY.md\t0\n" in out
              and "MISSING" not in out, "%d %r" % (code, out))
        os.makedirs(os.path.join(mem_root, "memory"))
        with open(os.path.join(mem_root, "memory", "MEMORY.md"), "wb") as fh:
            fh.write(b"## Mem Rule\n")
        code, out, _ = go(mem_root, mem_tsv)
        check("memory site, memory/ present: checked", code == 0 and "OK\tMem Rule\tmemory/MEMORY.md\t1\n" in out,
              "%d %r" % (code, out))

        tbl_root = os.path.join(base, "notable")
        _fixture(tbl_root)
        code, out, err = go(tbl_root, os.path.join(tbl_root, "absent.tsv"))
        check("missing table exit 2", code == 2 and out == "" and "checks table not found" in err, "%d %r" % (code, err))

        bad_root = os.path.join(base, "malformed")
        bad_tsv = _fixture(bad_root)
        with open(bad_tsv, "ab") as fh:
            fh.write(b"LabelOnly\t\n")
        code, out, err = go(bad_root, bad_tsv)
        check("malformed row exit 2", code == 2 and "malformed" in err and "SUMMARY" not in out, "%d %r" % (code, err))

        notrepo = os.path.join(base, "notrepo")
        os.makedirs(notrepo, exist_ok=True)
        code, _, err = go(notrepo, bad_tsv)
        check("not a repo exit 2", code == 2 and "does not look like" in err, "%d" % code)

        fence_root = os.path.join(base, "fence")
        code, out, err = go(fence_root, _fixture(fence_root, fence_open=True))
        check("unbalanced fence exit 2", code == 2 and "unbalanced code fence" in err
              and "marker:" not in out and "SUMMARY" not in out, "%d %r" % (code, err))

        bom_root = os.path.join(base, "bomcrlf")
        code, out, _ = go(bom_root, _fixture(bom_root, bom=True, crlf=True))
        check("bom+crlf exit 0", code == 0, "got %d" % code)
        check("bom+crlf stdout equals LF tree", out == expected, repr(out))

        nosite_root = os.path.join(base, "nosite")
        nosite_tsv = _fixture(nosite_root)
        append(nosite_tsv, "LabelPattern\tpat\n")
        code, out, err = go(nosite_root, nosite_tsv)
        check("no-site row exit 2", code == 2 and "no site field" in err and "SUMMARY" not in out,
              "%d %r" % (code, err))

        site_root = os.path.join(base, "siteunreadable")
        site_tsv = _fixture(site_root)
        code, out, err = go_failing_read(site_root, site_tsv, "shared/skills/demo/SKILL.md", OSError)
        check("unreadable cited site exit 2", code == 2 and "cannot read cited site" in err
              and "SUMMARY" not in out, "%d %r" % (code, err))

        src_root = os.path.join(base, "srcunreadable")
        src_tsv = _fixture(src_root)
        code, out, err = go_failing_read(src_root, src_tsv, "providers/x/NOTE.MD", OSError)
        check("unreadable source markdown exit 2", code == 2 and "cannot read source markdown" in err
              and "SUMMARY" not in out, "%d %r" % (code, err))

        code, out, err = go_failing_read(src_root, src_tsv, "providers/x/NOTE.MD", RuntimeError)
        check("unexpected exception exit 2", code == 2
              and err.startswith(NAME + ": guard did not run: RuntimeError") and "SUMMARY" not in out,
              "%d %r" % (code, err))

        case_root = os.path.join(base, "case")
        case_tsv = _fixture(case_root)
        _write(os.path.join(case_root, "shared", "case.md"), "alpha rules\nALPHA RULES\n")
        append(case_tsv, "CaseRow\tAlpha Rules\tshared/case.md\n")
        code, out, _ = go(case_root, case_tsv)
        check("case-sensitive site match", code == 1 and "MISSING\tCaseRow\tshared/case.md\t0\n" in out,
              "%d %r" % (code, out))

        mark_root = os.path.join(base, "marker")
        mark_tsv = _fixture(mark_root)
        append(os.path.join(mark_root, "shared", "AGENTS.md"), "\n## Delta\n\nRenaming this heading breaks things.\n")
        code, out, _ = go(mark_root, mark_tsv)
        check("unregistered marker MISSING exit 1", code == 1
              and "MISSING\tmarker:Delta\tshared/AGENTS.md:23\t0\n" in out
              and "OK\tmarker:Alpha Rules\tshared/AGENTS.md:5\t1\n" in out, "%d %r" % (code, out))

        gone_root = os.path.join(base, "gone")
        gone_tsv = _fixture(gone_root)
        append(gone_tsv, "Ghost\tGhost\tshared/gone.md\n")
        code, out, err = go(gone_root, gone_tsv)
        check("deleted site MISSING exit 1", code == 1 and err == ""
              and "MISSING\tGhost\tshared/gone.md\t0\n" in out, "%d %r %r" % (code, out, err))

        cov_root = os.path.join(base, "coverage")
        cov_tsv = _fixture(cov_root)
        append(cov_tsv, "Beta\t" + SECT + " Beta\tshared/skills/demo/SKILL.md\n")
        code, out, _ = go(cov_root, cov_tsv)
        check("COVERAGE skips a tabled heading", code == 0 and "COVERAGE\tBeta" not in out
              and "OK\tBeta\tshared/skills/demo/SKILL.md\t1\n" in out
              and "COVERAGE\tGamma\t2\t0\n" in out, "%d %r" % (code, out))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("verify-citations selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
    return 1 if fails else 0


def main(argv=None):
    _require_venv(__file__)
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
            except Exception:
                pass
    argv = sys.argv[1:] if argv is None else argv
    first = argv[0] if argv else ""
    if first == "--help":
        sys.stdout.write(__doc__)
        return 0
    if first == "--selftest":
        return selftest()
    here = os.path.dirname(os.path.realpath(__file__))
    root = first or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
    tsv = os.path.join(here, "citation-checks.tsv")
    sys.stdout.flush()
    code = run_guarded(root, tsv, sys.stdout.buffer, sys.stderr)
    sys.stdout.buffer.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
