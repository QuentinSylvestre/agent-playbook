#!/usr/bin/env python3
"""leak-scan.py -- refuse personal paths, email addresses and credential-shaped strings in the repo.

The public engine must carry nobody's machine paths, addresses or secrets: those belong in the
user's own store repo. This guard scans every tracked file (`git ls-files`; or, with --tree, every
file under a folder that is not a git checkout, such as an export about to be published) for:

  home-path   a Windows (`C:\\Users\\<name>`), macOS (`/Users/<name>`) or Linux (`/home/<name>`)
              home path whose user name is not a placeholder (PLACEHOLDER_USERS below, or a
              `<...>`, `%...%`, `$...` or `...` form)
  email       an address outside the documentation domains (ALLOWED_EMAIL_DOMAINS)
  credential  an API-key shape (sk-, ghp_/gho_/ghs_, github_pat_, AKIA, xox?-, AIza), a private key
              header, or an https URL with a long hex or base64url path segment (an embedded token)

Stdlib only, Python 3.8+. Reads files, writes nothing, never prints a matched credential (only its
kind and location). A line can opt out with `leak-scan: ignore` when the match is deliberate test
data; the selftest of this script is the one place that needs it.

Usage:
  leak-scan.py [<repo>]          scan the tracked files of <repo> (default: this script's repo)
  leak-scan.py --tree <folder>   scan every file under <folder>
  leak-scan.py --selftest
Output: one `LEAK<TAB>kind<TAB>path:line` line per hit, then `SUMMARY<TAB>files=N<TAB>leaks=M`.
Exit 0 (clean), 1 (a leak), 2 (could not run).
"""
import os
import re
import subprocess
import sys
import tempfile

PLACEHOLDER_USERS = {
    "alice", "bob", "carol", "user", "username", "you", "me", "name", "x", "u", "test", "tester",
    "example", "example-user", "someone", "runner", "runneradmin", "public", "default", "all users",
    "ubuntu", "admin", "root", "c", "transcripts", "dev", "jdoe", "test.user",
}
# An address is allowed when its domain is a documentation or test domain (any `example` label, or a
# reserved TLD), a git host in an SSH remote (`git@github.com`), or a vendor no-reply address.
ALLOWED_EMAIL_DOMAINS = (
    "users.noreply.github.com", "anthropic.com", "github.com", "ssh.github.com", "dev.azure.com",
    "ssh.dev.azure.com", "gitlab.com", "bitbucket.org", "localhost",
)
RESERVED_TLDS = ("invalid", "test", "example", "internal", "local", "localhost")
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".zip", ".gz",
                 ".pyc", ".docx", ".xlsx", ".pptx", ".vsdx")
IGNORE_MARK = "leak-scan: ignore"

# A home path starts a path: at a line start or after a space, quote, bracket, `=`, `:` (file://) or `,`;
# never inside a longer path such as `{ROOT}/home/...` or `tree/home/...`.
_START = r"(?:(?<=^)|(?<=[\s\"'`(\[=:,]))"
HOME_RES = [
    re.compile(r"(?i)\b[a-z]:[\\/]{1,4}users[\\/]{1,4}([^\\/\s\"'`<>|:*?]+)"),
    re.compile(_START + r"/Users/([^/\s\"'`<>]+)"),
    re.compile(_START + r"/home/([^/\s\"'`<>]+)"),
]
# A dotted domain with an alphabetic TLD: `d3@7.9.0` (an npm spec) and `t@t` are not addresses.
EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b")
CRED_RES = [
    ("api-key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("url-token", re.compile(r"https?://[^\s\"'`<>]*/(?:[0-9a-f]{32,}|[A-Za-z0-9_-]{40,})(?:[/?#\s\"'`<>]|$)")),
]


def placeholder(user):
    u = user.strip().rstrip(").,;:'\"").lower()
    if not u or u[0] in ".([{" or "[" in u:
        return True   # a dot folder (`/home/.kiro`), a regex or a template, not a user name
    if u in PLACEHOLDER_USERS:
        return True
    return bool(re.match(r"^(<.*>|%.*%|\$.*|\.\.\.?|\{.*\}|\*|\w)$", u))


def scan_text(text):
    """-> [(line number, kind)] for one file's text."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if IGNORE_MARK in line:
            continue
        for rx in HOME_RES:
            for m in rx.finditer(line):
                if not placeholder(m.group(1)):
                    hits.append((n, "home-path"))
                    break
        for m in EMAIL_RE.finditer(line):
            dom = m.group(1).lower()
            labels = dom.split(".")
            if "example" in labels or labels[-1] in RESERVED_TLDS:
                continue
            if not any(dom == d or dom.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
                hits.append((n, "email"))
        for kind, rx in CRED_RES:
            if rx.search(line):
                hits.append((n, kind))
    return hits


def files_of(repo, tree):
    if tree:
        out = []
        for cur, dirs, names in os.walk(tree):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "node_modules", ".venv-agent-playbook")]
            for name in names:
                out.append(os.path.relpath(os.path.join(cur, name), tree).replace("\\", "/"))
        return tree, sorted(out)
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("git ls-files failed in %s: %s" % (repo, r.stderr.decode("utf-8", "replace").strip()))
    return repo, sorted(x for x in r.stdout.decode("utf-8", "replace").split("\0") if x)


def run(repo=None, tree=None, out=print):
    base, names = files_of(repo, tree)
    leaks = scanned = 0
    for rel in names:
        if rel.lower().endswith(SKIP_SUFFIXES):
            continue
        path = os.path.join(base, rel)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        scanned += 1
        for n, kind in scan_text(data.decode("utf-8", "replace")):
            leaks += 1
            out("LEAK\t%s\t%s:%d" % (kind, rel, n))
    out("SUMMARY\tfiles=%d\tleaks=%d" % (scanned, leaks))
    return 1 if leaks else 0


def selftest():
    cases = [  # leak-scan: ignore (every line below is deliberate test data)
        ("C:\\Users\\alice\\src\\x", []),  # leak-scan: ignore
        ("C:\\Users\\jsmith42\\Documents", ["home-path"]),  # leak-scan: ignore
        ("c:/users/<you>/.claude", []),  # leak-scan: ignore
        ("/Users/x/dev and /home/user/agent-playbook", []),  # leak-scan: ignore
        ("/home/mrealname/.config", ["home-path"]),  # leak-scan: ignore
        ("see noreply@anthropic.com or a@example.com", []),  # leak-scan: ignore
        ("mail me at real.person@corp-mail.io", ["email"]),  # leak-scan: ignore
        ("key=sk-" + "a" * 24, ["api-key"]),
        ("token ghp_" + "b" * 36, ["github-token"]),
        ("AKIA" + "C" * 16, ["aws-key"]),
        ("https://mcp.example.com/mcp/" + "0123456789abcdef" * 2 + "/message", ["url-token"]),
        ("https://github.com/example-user/agent-playbook/blob/main/README.md", []),
        ("-----BEGIN " + "RSA PRIVATE KEY-----", ["private-key"]),
        ("anything " + IGNORE_MARK + " C:\\Users\\jsmith42", []),  # leak-scan: ignore
    ]
    fails = []
    for text, want in cases:
        got = sorted(k for _n, k in scan_text(text))
        if got != sorted(want):
            fails.append("%r: got %s, want %s" % (text[:60], got, want))
    tmp = tempfile.mkdtemp(prefix="leak-scan-")
    try:
        with open(os.path.join(tmp, "a.md"), "w", encoding="utf-8") as fh:
            fh.write("clean line\nC:\\Users\\jsmith42\\x\n")  # leak-scan: ignore
        lines = []
        rc = run(tree=tmp, out=lines.append)
        if rc != 1 or lines != ["LEAK\thome-path\ta.md:2", "SUMMARY\tfiles=1\tleaks=1"]:
            fails.append("tree run: rc=%s %r" % (rc, lines))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    for f in fails:
        print("FAIL: " + f)
    print("leak-scan selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), len(cases) + 1))
    return 1 if fails else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--selftest"]:
        return selftest()
    try:
        if argv[:1] == ["--tree"] and len(argv) == 2:
            return run(tree=argv[1])
        if len(argv) <= 1 and not (argv and argv[0].startswith("-")):
            repo = argv[0] if argv else os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.realpath(__file__))))))
            return run(repo=repo)
    except (OSError, RuntimeError) as exc:
        print("leak-scan: could not run: %s" % exc, file=sys.stderr)
        return 2
    print(__doc__.split("Usage:")[1].split("Output:")[0].rstrip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
