#!/usr/bin/env python3
"""Measure a change for /qexplain before anything is read or written.

Prints each file shown, the files left out and the setting names their change touches,
any credential-shaped match (path and line only, never the value), the size tier, the
plans named by commit scopes, and whether to propose a split. It prints no file content.

Standard library only; nothing to install. <python> is <config-repo>/.venv-agent-playbook/Scripts/python.exe -I.

Usage:
    <python> measure-change.py [--repo <dir>] --diff-args "<git diff arguments>" [--exclude <glob>]...
    <python> measure-change.py --diff-file <unified.diff> [--exclude <glob>]...
    <python> measure-change.py --target "<label>=<repo>::<git diff arguments>" [--target ...] [--exclude <glob>]...
    <python> measure-change.py --selftest

A --diff-args value starting with a dash needs the = form: --diff-args=--cached.

Exit codes:
    0  measured, or the selftest passed
    1  the selftest failed
    2  bad input, or git failed
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script's folder off the path
import qexplain_diff as qd  # noqa: E402

SPLIT_READING_LINES = 2500


def tier(lines):
    if lines < 75:
        return "Tiny"
    if lines < 250:
        return "Small"
    if lines <= 800:
        return "Medium"
    return "Large"


def selftest():
    """Parser, filter and scanner checks that need no repository."""
    fails = []

    def check(ok, name):
        if not ok:
            fails.append(name)

    fake = "Zq7Mv2Lp9Xk4"
    for line, want in (("export A=1", False), ("broker: a", False)):
        check(bool(qd.setting_names("c.yml", "@@ -1 +1 @@\n+" + line)[0].endswith("(line without a setting name)")) == want, f"setting name kept: {line}")
    for path, line in (("master.key", "+Zq7CanaryMv2Lp9_abc123DEF456ghi789="), ("c.yml", "+Zq7CanaryMv2Lp9_abc123DEF456ghi789: true"),
                       (".htpasswd", "+admin:" + fake), ("c.env", "+abcdefgh" + fake + "=")):
        check(qd.setting_names(path, "@@ -1 +1 @@\n" + line)[0].endswith("(line without a setting name)"), f"no name printed from: {path}")
    header = lambda p: f"diff --git a/{p} b/{p}\nindex 1..2 100644\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-old\n+new {fake}\n"
    # Filter
    for name in (".env", "conf.env", "server.pem", ".npmrc", "terraform.tfvars", "secrets/prod.yaml", "my b/.env"):
        kept, out, _ = qd.filter_files(qd.split_files(header(name)), [])
        check(not kept and len(out) == 1, f"left out by name: {name}")
    for name in ("auth/password_reset.py", "src/SecretManager.java", "docs/password-policy.md", "src/app.go"):
        kept, _, _ = qd.filter_files(qd.split_files(header(name)), [])
        check(len(kept) == 1, f"kept: {name}")
    spaced = header("my b/prod.yaml")
    check(qd.split_files(spaced)[0][0] == "my b/prod.yaml", "a directory ending in ' b' keeps its full path")
    for pat in ("my b/prod.yaml", "my b/*", "my b/", "MY B\\PROD.YAML"):
        kept, _, unused = qd.filter_files(qd.split_files(spaced), [pat])
        check(not kept and not unused, f"--exclude form matches: {pat}")
    check(qd.filter_files(qd.split_files(header("a.yaml")), ["b.yaml"])[2] == ["b.yaml"], "an unused --exclude is reported")
    renamed = "diff --git a/server.pem b/notes.txt\nsimilarity index 90%\nrename from server.pem\nrename to notes.txt\n--- a/server.pem\n+++ b/notes.txt\n@@ -1 +1 @@\n-a\n+b\n"
    check(not qd.filter_files(qd.split_files(renamed), [])[0], "a rename out of a secret name is left out")
    quoted = 'diff --git "a/cl\\303\\251.pem" "b/cl\\303\\251.pem"\n--- "a/cl\\303\\251.pem"\n+++ "b/cl\\303\\251.pem"\n@@ -1 +1 @@\n-a\n+b\n'
    check(not qd.filter_files(qd.split_files(quoted), [])[0], "a C-quoted secret name is left out")
    combined = header("a.go") + "diff --cc zz.go\nindex 1,2..3\n--- a/zz.go\n+++ b/zz.go\n@@@ -1,1 -1,1 +1,1 @@@\n- x\n -y\n++z\n"
    kept, out, _ = qd.filter_files(qd.split_files(combined), [])
    check(len(kept) == 1 and "zz.go" not in kept[0][1] and out[0]["reason"].startswith("combined"), "a combined diff is its own block and left out")
    binary = "diff --git a/b.bin b/b.bin\nindex 1..2\nGIT binary patch\nliteral 80\nabc\n"
    check(not qd.filter_files(qd.split_files(binary), [])[0], "a binary patch is left out")
    check(not qd.filter_files([(None, "diff --git weird")], [])[0], "an unreadable path is left out")
    check(qd.counts("diff --git a/q b/q\n--- a/q\n+++ b/q\n@@ -1 +1 @@\n--- old\n+++ new\n") == (1, 1), "counts look only inside hunks")
    # Classification
    for name, want in (("pkg/test_foo.py", "test"), ("src/FooTest.java", "test"), ("web/__fixtures__/x.json", "test"),
                       ("go.sum", "generated"), ("dist/app.min.js", "generated"), ("src/latest.java", "src"), ("a.go", "src")):
        check(qd.file_type(name) == want, f"{name} is {want}")
    # Scanner: each line is built here so this file holds no credential-shaped text of its own
    hits = lambda text, cfg=False: qd.line_hits(text, cfg)
    for line in ('pass' + 'word = "' + fake + '"', '{\\"pass' + 'word\\":\\"' + fake + '\\"}', '<pass' + 'word>' + fake + '</pass' + 'word>',
                 'Server=x;Pass' + 'word=' + fake + ';', 'redis://:' + fake + '@h', 'Author' + 'ization: Bear' + 'er ' + fake * 2,
                 'cfg(tok' + 'en="placeholder", pass' + 'word="' + fake + '")', 'gith' + 'ub_pat_' + fake * 2):
        check(hits(line), f"shape caught: {line[:12]}")
    check(hits('DB_PASS' + 'WORD=' + fake, True) and not hits('DB_PASS' + 'WORD=' + fake, False), "bare assignment needs a config-like file")
    check(hits('pass' + 'word: ' + fake + ' # prod', True), "bare assignment allows a trailing comment")
    for line in ('pass' + 'word = "${DB_PASS}"', 'pass' + 'word=<your-value>', 'http://host:8080/path@v2', 'tok' + 'en = "changeme"'):
        check(not hits(line, True), f"not a credential: {line[:12]}")
    check(hits('pass' + 'word = "Tr0ub<dor&3xyz"'), "a value holding a placeholder character is still caught")
    token_like = 'tok' + 'en = "test_' + fake * 3 + '"'
    check(hits(token_like) and not any(made for _, made in hits(token_like)), "a long value is not called made up for holding 'test'")
    check(any(made for _, made in hits('pass' + 'word = "testpass1"')), "a short test word is called made up")
    masked_files, missed = qd.mask_files([("a_test.go", header("a_test.go").replace("new " + fake, 'pass' + 'word = "' + fake + '" // keep'))], ["a_test.go:new:1", "a_test.go:new:9"])
    check(fake not in masked_files[0][1] and "// keep" in masked_files[0][1] and not qd.scan_files(masked_files), "masking hides the value and keeps the line")
    check(missed == ["a_test.go:new:9"], "a mask that matches nothing is reported")
    # Written content, in the forms an agent writes
    check(qd.scan_text("n", '<p>pass' + 'word=&quot;' + fake + '&quot;</p>'), "entity-encoded value in a fragment")
    check(qd.scan_text("n", '<code>DB_PASS' + 'WORD=' + fake + '</code>'), "bare value inside a tag")
    check(qd.scan_content_file("m.json", '{"a": "pass' + 'word=\\"' + fake + '\\""}'), "escaped value in JSON")
    # Git options
    for bad in ("HEAD --ext-diff", "HEAD --output=x", "HEAD --binary", "--no-prefix HEAD"):
        try:
            qd.capture(".", bad)
            check(False, f"refused: {bad}")
        except ValueError:
            pass
        except RuntimeError:
            check(False, f"refused before git runs: {bad}")
    # Commit ranges
    check(qd.log_range("main...feat")[0] == ["main..feat"], "three dots log only the branch's commits")
    check(qd.log_range("abc")[0] == ["abc..HEAD"], "a single revision logs to HEAD")
    check(qd.log_range("a..b -- p")[0] == ["a..b", "--", "p"], "a path filter reaches the log")
    check(qd.log_range("--cached")[0] is None, "staged changes have no commits")
    # Long lines stay fast
    for long_line in ("a" * 1000000, "token" * 200000, "0123456789abcdef" * 62500, 'token="' + "a" * 1000000, "a://" * 250000):
        start = time.monotonic()
        qd.line_hits(long_line, True)
        check(time.monotonic() - start < 10, f"long line scanned quickly: {long_line[:8]}")
    # Values never leave
    report = "\n".join(qd.hit_line(h) for h in qd.scan_files([("a.go", header("a.go").replace("new " + fake, 'pass' + 'word = "' + fake + '"'))]))
    check(report and fake not in report, "a report names the line without the value")
    check(fake not in "".join(qd.setting_names("c.yml", "@@ -1 +1 @@\n+pass" + "word: " + fake + "\n")), "setting names hold no value")
    # Shapes and forms added after the security re-check
    for line in ('pass' + 'word: str = "' + fake + '"', 'os.environ["DB_PASS' + 'WORD"] = "' + fake + '"', 'mysql --pass' + 'word=' + fake,
                 'setPass' + 'word("' + fake + '")', 'tok' + 'en = "' + 'a' * 300 + '"', 'pass' + 'word = "$ecret-Real99"', 'pass' + 'word = "Real(Secret)99"'):
        check(hits(line), f"shape caught: {line[:14]}")
    for line in (' ' * 30 + 'pass' + 'word: ' + fake, '- pass' + 'word: ' + fake, '{ pass' + 'word: ' + fake + ' }'):
        check(hits(line, True), f"YAML shape caught: {line.strip()[:14]}")
    check(qd.scan_text("n", '<pre>run with DB_PASS' + 'WORD=' + fake + ' now</pre>'), "an assignment mid-line in written text")
    check(qd.scan_text("n", '<pre>pass' + 'word =\n"' + fake + '"</pre>'), "an assignment split across two lines of written text")
    check(not qd.scan_text("n", "<p>The secret is stored in conf.env.</p>"), "plain prose is not flagged")
    for bad in ("HEAD --word-diff-regex=.", "HEAD --color-words=.", "HEAD -z", "HEAD --line-prefix=x"):
        try:
            qd.capture(".", bad)
            check(False, f"refused: {bad}")
        except ValueError:
            pass
        except RuntimeError:
            check(False, f"refused before git runs: {bad}")
    for name in ("tests/secrets/prod.yaml", "fixtures/credentials.yaml", "secrets-test.yaml", "secrets/prod.py", "passwords.sql"):
        check(not qd.filter_files(qd.split_files(header(name)), [])[0], f"left out despite its class: {name}")
    for pat in ("./my b/prod.yaml", "/my b/prod.yaml"):
        check(not qd.filter_files(qd.split_files(spaced), [pat])[0], f"--exclude form matches: {pat}")
    for label in ("tests", "__tests__", "__fixtures__", "vendor"):
        try:
            qd.parse_target(f"{label}=r::HEAD")
            check(False, f"label refused: {label}")
        except ValueError:
            pass
    bad_header = "diff --git a/server.pem b/notes.txt\n--- a/dev/null\n+++ b/notes.txt\n@@ -1 +1 @@\n-a\n+b\n"
    check(not qd.filter_files(qd.split_files(bad_header), [])[0], "a header with two names and no rename line is left out")
    check(not qd.filter_files(qd.split_files('diff --git "a/x\\q.py" "b/x\\q.py"\n'), [])[0], "a bad escape in a path is left out")
    check("\n" not in qd.safe_path("x\nPLAN\ty"), "a file name cannot forge a report line")
    hdr = "diff --git a/m.go b/m.go\nold mode 100644\n    pass" + 'word="' + fake + '"\n'
    check(qd.scan_files(qd.split_files(hdr)), "text before the first hunk is scanned")
    for name in fails:
        print(f"FAIL\t{name}")
    print(f"selftest: {len(fails)} failed")
    return 1 if fails else 0


def main():
    # -I ignores PYTHONIOENCODING, and a piped Windows console cannot print every file name.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--diff-args")
    src.add_argument("--diff-file")
    src.add_argument("--target", action="append")
    src.add_argument("--selftest", action="store_true")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    files, plans, skipped, repos = [], [], [], 1
    try:
        if args.target:
            targets = [qd.parse_target(t) for t in args.target]
            repos = len(targets)
            for label, repo, diff_args in targets:
                files += qd.split_files(qd.capture(repo, diff_args, label))
                found, why = qd.plans_in_range(repo, diff_args)
                plans += [(label, slug) for slug in found]
                if why:
                    skipped.append(f"{label}: {why}")
        elif args.diff_file:
            with open(args.diff_file, "r", encoding="utf-8-sig") as fh:
                files = qd.split_files(fh.read())
            skipped.append("a diff file carries no commit messages")
        else:
            files = qd.split_files(qd.capture(args.repo, args.diff_args))
            found, why = qd.plans_in_range(args.repo, args.diff_args)
            plans = [(None, slug) for slug in found]
            if why:
                skipped.append(why)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"ERROR\t{exc}", file=sys.stderr)
        return 2

    kept, left_out, unused = qd.filter_files(files, args.exclude)
    blocks = dict(files)
    by_type = {}
    for path, block in kept:
        add, rem = qd.counts(block)
        kind = qd.file_type(path)
        by_type[kind] = by_type.get(kind, 0) + add + rem
        print(f"FILE\t{qd.safe_path(path)}\t{kind}\t+{add} -{rem}")
    total = sum(by_type.values())
    not_read = by_type.get("test", 0) + by_type.get("generated", 0)
    reading = total - not_read

    for pat in unused:
        print(f"WARN\t--exclude {pat} matched nothing; fix it, because the build refuses it")
    for item in left_out:
        shown = qd.safe_path(item["path"])
        print(f"LEFT-OUT\t{shown}\t+{item['add']} -{item['del']}\t{item['reason']}")
        block = blocks.get(item["path"])
        if block is not None:
            for name in qd.setting_names(item["path"], block):
                print(f"SETTING\t{shown}\t{name}")
    for hit in qd.scan_files(kept):
        print(qd.hit_line(hit))
    print(f"FILES\t{len(kept)} shown, {len(left_out)} left out")
    print(f"LINES\t{total} changed; {reading} to read, {not_read} in tests, fixtures and generated files")
    print("TYPES\t" + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items())))
    print(f"TIER\t{tier(reading)}")
    for label, slug in plans:
        print(f"PLAN\t{slug}" + (f"\t{label}" if label else ""))
    for why in skipped:
        print(f"PLAN-SKIPPED\t{why}")

    reasons = []
    if reading > SPLIT_READING_LINES:
        reasons.append(f"{reading} lines to read, over {SPLIT_READING_LINES}")
    distinct = list(dict.fromkeys(slug for _, slug in plans))
    if len(distinct) > 1:
        reasons.append(f"{len(distinct)} plans")
    if reasons:
        print("SPLIT\tpropose a split: " + "; ".join(reasons))
    if repos > 1:
        print(f"REPOS\t{repos} repos in one artifact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
