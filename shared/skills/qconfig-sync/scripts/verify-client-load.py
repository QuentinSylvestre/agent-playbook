#!/usr/bin/env python3
"""verify-client-load.py -- report which deployed skills each selected, installed client lists as loaded.

Run with the playbook venv (<repo>/.venv-agent-playbook); any other interpreter exits 2 ("guard did not run:
venv missing"). Stdlib only, Python 3.8+. It writes nothing of its own, runs no git and touches no network.
It never spends a model call: the only client commands it runs are `--version` and the one listing command
in the ledger below, and it runs them from a neutral folder (the system temp folder), never the cwd.

verify-deployment answers "is the file on disk where setup put it". This guard answers the next question:
"does the client list the skill". A skill can be deployed and still absent from a client's listing (a
frontmatter the client rejects, a client-side disabled list, a stale cache).

Clients checked: those the pointer file `~/.agent-playbook/config` names in `providers=` (override the file
with --pointer). A client is checked only when its binary is on PATH. Expected skills, per client: every
shared/skills/*/SKILL.md folder (not `synced`, not a dot or `.bucket-` folder), plus for Kiro every
providers/kiro/skills/* folder that has a SKILL.md and no OVERLAY.md (a standalone Kiro skill). This is the
set verify-skills.py checks and the set setup deploys.

Statuses, one tab-separated line each:
  LOADED       <client>  <skill>  <evidence>   the client's listing shows the skill enabled.
  INACTIVE     <client>  <skill>  <evidence>   deployed but absent from the listing, or listed [Disabled].
  UNOBSERVABLE <client>  <detail>  <evidence>  the client has no listing surface without a model call. One
                                               line per client, not per skill.
  SKIP         <client>  <reason>  [evidence]  client not selected, not installed, command failed or timed
                                               out, or output that does not parse. One line per client.
Then SUMMARY\\tloaded=N\\tinactive=N\\tunobservable=N\\tskip=N\\tinactive_skills=<client>:<skill>,... (or
`none`): the SUMMARY names every INACTIVE skill, because report-only lines go unread.

Evidence names the surface, the client version (from `<binary> --version`) and the date of the observation,
per shared/AUTHORING.md section Measured Claims: `gemini skills list; gemini 0.28.2; 2026-11-12`. When the
installed version differs from the ledger's, the evidence adds `ledger measured <version> on <date>; the
parser may no longer fit` and the run still tries to parse.

Exit codes: 0 always for findings. INACTIVE and SKIP are warnings and never fail a sync. 1 only for a
failed --selftest. 2 for a precondition failure (repo-root argument missing, repo path invalid or not a
playbook, no skill found), the venv guard, or an unexpected error: "verify-client-load.py: guard did not
run: <reason>" on stderr, after any rows already printed. A missing pointer file, a pointer without
`providers=` and absent client binaries are SKIP lines (exit 0), so the guard runs cleanly in CI, where no
client is installed.

Usage:
  verify-client-load.py [--help] <repo-root> [--pointer FILE]
  verify-client-load.py --selftest

The repo-root argument is MANDATORY -- exit 2 when absent. Repo context is never derived from the ambient
cwd, a recorded footgun (memory/topics/playbook-authoring.md, the ambient-cwd lesson).

CAPABILITY LEDGER. The LEDGER table below is the single record of what each client lets this guard observe.
Add a row, or change a surface, only after running the command on the client and recording its version and
the date. A listing command that spends a model call is never a surface: that client stays UNOBSERVABLE.
Fixtures for the two parsers are captures of the real output with descriptions, paths and instruction text
stripped: fixtures/verify-client-load/.

Selftest: `verify-client-load.py --selftest` parses each fixture and checks LOADED, INACTIVE (a skill
removed from a fixture copy), a [Disabled] entry, unparseable output, a missing binary, a client that is not
selected, a timed-out or failing command, a version mismatch note, the UNOBSERVABLE clients (whose only
command is `--version`), the pointer-file SKIP lines, the expected-skill discovery, and the SUMMARY naming
INACTIVE skills. It also breaks each parser in turn (a mutation) and requires the cases to catch it. The
command runner is injected, so the selftest never executes a client.
"""
import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

NAME = "verify-client-load.py"
HERE = os.path.dirname(os.path.realpath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "verify-client-load")
TIMEOUT_S = 60
VERSION_TIMEOUT_S = 30

Row = collections.namedtuple("Row", "client binary surface parser version date note")

# One row per client, in report order. `surface` is the listing command's arguments after the binary, or
# None when the client has no listing surface without a model call (then `parser` is None and the client is
# UNOBSERVABLE). `version` and `date` are what the surface was measured on.
LEDGER = (
    Row("claude", "claude", None, None, "2.1.322", "2026-11-11",
        "the only listing is the stream-json init event of `claude -p`, which spends a model call"),
    Row("codex", "codex", ("debug", "prompt-input"), "codex-prompt-input", "0.162.0", "2026-11-12",
        "renders the model-visible input as JSON; the skills sit in its skills_instructions block; "
        "no enabled marker, a disabled skill is simply absent"),
    Row("gemini", "gemini", ("skills", "list"), "gemini-skills-list", "0.28.2", "2026-11-12",
        "prints each skill with [Enabled] or [Disabled] and its location, to stderr in a non-interactive "
        "run; works after an auth error; starts the user's configured MCP servers during discovery"),
    Row("kiro", "kiro-cli", None, None, "3.0.0", "2026-11-11",
        "the only listing is `chat --no-interactive`, which spends a model call"),
)


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


# --- parsers: (text of stdout plus stderr) -> ({skill name: "enabled" | "disabled"}, error or None) ---
GEMINI_ENTRY = re.compile(r"^(\S+) \[([^\]]+)\]\s*$")
GEMINI_HEADER = "Discovered Agent Skills:"
CODEX_ENTRY = re.compile(r"^- (\S+?): ")


def parse_gemini(text):
    """`gemini skills list`: a `Discovered Agent Skills:` header, then per skill a `<name> [Enabled]` line
    (or [Disabled]) at column 0 followed by indented Description and Location lines. The header is the
    anchor: without it the output is not a listing (an auth error alone, a changed format)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == GEMINI_HEADER:
            start = i
            break
    if start is None:
        return None, "no '%s' header in the output" % GEMINI_HEADER
    states = {}
    for line in lines[start + 1:]:
        m = GEMINI_ENTRY.match(line)
        if not m:
            continue
        tag = m.group(2).strip().lower()
        if tag not in ("enabled", "disabled"):
            return None, "unknown state tag [%s] on skill %s" % (m.group(2), m.group(1))
        # a skill listed twice counts as enabled when any entry is
        if states.get(m.group(1)) != "enabled":
            states[m.group(1)] = tag
    return states, None


def parse_codex(text):
    """`codex debug prompt-input`: a JSON list of messages whose input_text parts include one holding
    `<skills_instructions>` ... `### Available skills` ... `</skills_instructions>`, a bullet `- <name>: ...`
    per skill. Codex shows no enabled marker; a skill it does not list is not loaded."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, "output is not JSON (%s)" % exc
    if not isinstance(data, list):
        return None, "JSON output is not a list of messages"
    block = None
    for msg in data:
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for part in content:
            t = part.get("text") if isinstance(part, dict) else None
            if isinstance(t, str) and "<skills_instructions>" in t:
                block = t
                break
        if block is not None:
            break
    if block is None:
        return None, "no skills_instructions block in the rendered input"
    head, sep, rest = block.partition("### Available skills")
    if not sep:
        return None, "no '### Available skills' list in the skills_instructions block"
    states = {}
    for line in rest.split("</skills_instructions>")[0].splitlines():
        m = CODEX_ENTRY.match(line)
        if m:
            states[m.group(1)] = "enabled"
    return states, None


PARSERS = {"gemini-skills-list": parse_gemini, "codex-prompt-input": parse_codex}


# --- expected skills ---
def expected_skills(repo, client):
    """-> sorted skill names setup deploys for the client."""
    roots = [("shared/skills", False)]
    if client == "kiro":
        roots.append(("providers/kiro/skills", True))
    names = set()
    for root_rel, standalone_only in roots:
        root = os.path.join(repo, *root_rel.split("/"))
        if not os.path.isdir(root):
            continue
        for folder in os.listdir(root):
            if folder.startswith(".") or folder == "synced" or folder.startswith(".bucket-"):
                continue
            d = os.path.join(root, folder)
            if not os.path.isfile(os.path.join(d, "SKILL.md")):
                continue
            if standalone_only and os.path.exists(os.path.join(d, "OVERLAY.md")):
                continue
            names.add(folder)
    return sorted(names)


# --- the injected environment ---
def _kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def real_run(argv, timeout):
    """-> (exit code, stdout, stderr), run from the system temp folder with no stdin. Output goes to temp
    files, not pipes: a client's grandchild (an MCP server) can hold a pipe open after a timeout kill.
    Raises subprocess.TimeoutExpired or OSError."""
    cwd = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix="verify-client-load-") as tmp:
        out_path, err_path = os.path.join(tmp, "out"), os.path.join(tmp, "err")
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=(os.name != "nt"))
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                raise
        with open(out_path, "rb") as fh:
            so = fh.read().decode("utf-8", "replace")
        with open(err_path, "rb") as fh:
            se = fh.read().decode("utf-8", "replace")
    return code, so, se


class Env(object):
    def __init__(self, which=None, run=None, today=None, pointer=None):
        self.which = which or shutil.which
        self.run = run or real_run
        self.today = today or (lambda: datetime.date.today().isoformat())
        self.pointer = pointer or os.path.join(os.path.expanduser("~"), ".agent-playbook", "config")


def read_pointer(path):
    """-> ({key: value}, None) or (None, reason)."""
    if not os.path.isfile(path):
        return None, "pointer file not found: %s" % path
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    keys = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        keys[k.strip()] = v.strip()
    return keys, None


VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def client_version(env, exe):
    try:
        code, so, se = env.run([exe, "--version"], VERSION_TIMEOUT_S)
    except Exception:
        return None
    m = VERSION_RE.search(so + "\n" + se)
    return m.group(0) if (code == 0 and m) else None


def evidence(row, version, today, detail=None):
    """The surface, client version and date of one observation (shared/AUTHORING.md section Measured Claims)."""
    surface = "%s %s" % (row.binary, " ".join(row.surface)) if row.surface else "%s --version" % row.binary
    parts = [surface, "%s %s" % (row.client, version or "version unknown"), today]
    if version and version != row.version:
        parts.append("ledger measured %s on %s; the parser may no longer fit" % (row.version, row.date))
    if detail:
        parts.insert(0, detail)
    return "; ".join(parts)


def check_client(row, repo, env):
    """-> list of output lines for one selected client."""
    exe = env.which(row.binary)
    if not exe:
        return ["SKIP\t%s\t%s is not installed (not on PATH)" % (row.client, row.binary)]
    today = env.today()
    version = client_version(env, exe)
    expected = expected_skills(repo, row.client)
    if row.surface is None:
        return ["UNOBSERVABLE\t%s\t%d deployed skills, no listing surface without a model call (%s)\t%s"
                % (row.client, len(expected), row.note, evidence(row, version, today))]
    ev = evidence(row, version, today)
    try:
        code, so, se = env.run([exe] + list(row.surface), TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return ["SKIP\t%s\tcommand timed out after %d s\t%s" % (row.client, TIMEOUT_S, ev)]
    except Exception as exc:
        return ["SKIP\t%s\tcommand did not run (%s: %s)\t%s" % (row.client, type(exc).__name__, exc, ev)]
    if code != 0:
        return ["SKIP\t%s\tcommand exited %s\t%s" % (row.client, code, ev)]
    states, err = PARSERS[row.parser](so + "\n" + se)
    if err:
        return ["SKIP\t%s\tunparseable output: %s\t%s" % (row.client, err, ev)]
    lines = []
    for skill in expected:
        state = states.get(skill)
        if state == "enabled":
            lines.append("LOADED\t%s\t%s\t%s" % (row.client, skill, ev))
        elif state == "disabled":
            lines.append("INACTIVE\t%s\t%s\t%s" % (row.client, skill, evidence(row, version, today, "listed [Disabled]")))
        else:
            lines.append("INACTIVE\t%s\t%s\t%s" % (row.client, skill,
                                                   evidence(row, version, today, "deployed but not in the client's listing")))
    return lines


def run(argv, env=None):
    """-> (exit code, stdout lines, stderr lines). Any unexpected error is exit 2, "guard did not run", with
    the rows already produced kept."""
    out, err = [], []
    try:
        return _run(argv, env or Env(), out, err)
    except Exception as exc:
        err.append("%s: guard did not run: %s: %s" % (NAME, type(exc).__name__, exc))
        return 2, out, err


def _run(argv, env, out, err):
    argv = list(argv)
    if "--pointer" in argv:
        i = argv.index("--pointer")
        if i + 1 >= len(argv):
            err.append("%s: --pointer needs a file argument" % NAME)
            return 2, out, err
        env.pointer = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        err.append("%s: repo-root argument is required (deliberately never derived from cwd)" % NAME)
        return 2, out, err
    repo = argv[0]
    if not repo or not os.path.isdir(repo):
        err.append("%s: repo path not found: %s" % (NAME, repo))
        return 2, out, err
    if not os.path.isfile(os.path.join(repo, "shared", "AGENTS.md")):
        err.append("%s: %s does not look like an agent-playbook repo" % (NAME, repo))
        return 2, out, err
    if not expected_skills(repo, "claude"):
        err.append("%s: guard did not run: no SKILL.md found under shared/skills" % NAME)
        return 2, out, err

    keys, why = read_pointer(env.pointer)
    selected = None
    if keys is None:
        out.append("SKIP\t-\t%s" % why)
    elif "providers" not in keys:
        out.append("SKIP\t-\tpointer file %s has no providers= line" % env.pointer)
    else:
        selected = [p.strip().lower() for p in keys["providers"].split(",") if p.strip()]
    if selected is not None:
        known = [r.client for r in LEDGER]
        for extra in selected:
            if extra not in known:
                out.append("SKIP\t%s\tno row in the capability ledger" % extra)
        for row in LEDGER:
            if row.client not in selected:
                out.append("SKIP\t%s\tnot selected in providers=%s" % (row.client, ",".join(selected)))
            else:
                out.extend(check_client(row, repo, env))

    counts = collections.Counter(line.split("\t", 1)[0] for line in out)
    inactive = ["%s:%s" % tuple(line.split("\t")[1:3]) for line in out if line.startswith("INACTIVE\t")]
    out.append("SUMMARY\tloaded=%d\tinactive=%d\tunobservable=%d\tskip=%d\tinactive_skills=%s"
               % (counts["LOADED"], counts["INACTIVE"], counts["UNOBSERVABLE"], counts["SKIP"],
                  ",".join(inactive) if inactive else "none"))
    return 0, out, err


# --- selftest ---
def selftest():
    fails, checks = [], [0]

    def chk(name, cond, detail=""):
        checks[0] += 1
        if not cond:
            fails.append("%s%s" % (name, (": " + detail) if detail else ""))

    def read(name):
        with open(os.path.join(FIXTURES, name), "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    gemini_text = read("gemini-skills-list.txt")
    codex_text = read("codex-prompt-input.json")
    g_states, g_err = parse_gemini(gemini_text)
    c_states, c_err = parse_codex(codex_text)
    chk("the gemini fixture parses", g_err is None and len(g_states) >= 5, "%r" % (g_err,))
    chk("the codex fixture parses", c_err is None and len(c_states) >= 5, "%r" % (c_err,))
    g_names = sorted(n for n in (g_states or {}) if n.startswith("q"))
    c_names = sorted(n for n in (c_states or {}) if n.startswith("q"))
    chk("the codex fixture also lists a non-q skill and a plugin skill",
        any(not n.startswith("q") for n in (c_states or {})) and any(":" in n for n in (c_states or {})))
    chk("both fixtures list the same q skills", g_names == c_names and bool(g_names), "%r %r" % (g_names, c_names))

    tmp = tempfile.mkdtemp(prefix="verify-client-load-")
    counter = [0]

    def write(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)

    def make_repo(shared, kiro_standalone=(), kiro_overlay=(), extra=None):
        counter[0] += 1
        root = os.path.join(tmp, "repo%d" % counter[0])
        write(os.path.join(root, "shared", "AGENTS.md"), "x\n")
        for n in shared:
            write(os.path.join(root, "shared", "skills", n, "SKILL.md"), "---\nname: %s\n---\n" % n)
        for n in kiro_standalone:
            write(os.path.join(root, "providers", "kiro", "skills", n, "SKILL.md"), "---\nname: %s\n---\n" % n)
        for n in kiro_overlay:
            write(os.path.join(root, "providers", "kiro", "skills", n, "OVERLAY.md"), "overlay\n")
            write(os.path.join(root, "providers", "kiro", "skills", n, "SKILL.md"), "---\nname: %s\n---\n" % n)
        for rel in (extra or ()):
            write(os.path.join(root, *rel.split("/")), "x\n")
        return root

    def pointer(providers):
        counter[0] += 1
        p = os.path.join(tmp, "pointer%d" % counter[0])
        write(p, "# pointer\nroot=/x\nproviders=%s\n" % providers)
        return p

    class Fake(object):
        """Injected runner: records every call; per binary, a version string and listing output."""

        def __init__(self, installed, version=None, listings=None, behavior=None):
            self.installed = set(installed)
            self.version = version or {}
            self.listings = listings or {}
            self.behavior = behavior or {}
            self.calls = []

        def which(self, binary):
            return "/fake/" + binary if binary in self.installed else None

        def run(self, argv, timeout):
            self.calls.append(list(argv))
            binary = os.path.basename(argv[0])
            if argv[1:] == ["--version"]:
                return 0, self.version.get(binary, "0.0.0") + "\n", ""
            beh = self.behavior.get(binary)
            if beh == "timeout":
                raise subprocess.TimeoutExpired(argv, timeout)
            if beh == "oserror":
                raise OSError("injected")
            if beh == "exit3":
                return 3, "", "boom"
            so, se = self.listings.get(binary, ("", ""))
            return 0, so, se

    versions = {"gemini": "0.28.2", "codex": "codex-cli 0.162.0", "claude": "2.1.322 (Claude Code)", "kiro-cli": "kiro-cli 3.0.0"}

    def go(repo, providers, fake, parsers=None, keep_unselected=False):
        env = Env(which=fake.which, run=fake.run, today=lambda: "2026-11-12", pointer=pointer(providers))
        saved = dict(PARSERS)
        if parsers:
            PARSERS.update(parsers)
        try:
            rc, out, err = run([repo], env)
            if not keep_unselected:
                out = [l for l in out if "\tnot selected in providers=" not in l]
            return rc, out, err
        finally:
            PARSERS.clear()
            PARSERS.update(saved)

    def skipl(out, client):
        return next((l for l in out if l.startswith("SKIP	%s	" % client)), "")

    def lines_of(out, status):
        return [l.split("\t") for l in out if l.startswith(status + "\t")]

    shared = sorted(set(g_names))
    repo = make_repo(shared + ["qonly-in-repo"], kiro_standalone=["qkirostd"], kiro_overlay=["qdev"],
                     extra=["shared/skills/synced/notes.md", "shared/skills/.hidden/SKILL.md",
                            "shared/skills/.bucket-x/SKILL.md", "shared/skills/qnoskill/README.md"])
    chk("discovery: shared skills with a SKILL.md only (no synced, dot, bucket or SKILL-less folder)",
        expected_skills(repo, "gemini") == sorted(shared + ["qonly-in-repo"]), "%r" % expected_skills(repo, "gemini"))
    chk("discovery: Kiro adds a standalone skill and skips an overlay folder",
        expected_skills(repo, "kiro") == sorted(shared + ["qonly-in-repo", "qkirostd"]), "%r" % expected_skills(repo, "kiro"))

    # evaluate(parsers) -> list of failed case names; used for the real parsers and for each mutant
    def evaluate(parsers):
        bad = []

        def case(name, cond):
            if not cond:
                bad.append(name)

        r = make_repo(shared)
        # gemini: all LOADED
        fake = Fake({"gemini"}, versions, {"gemini": ("", gemini_text)})
        rc, out, err = go(r, "gemini", fake, parsers)
        case("gemini all loaded", rc == 0 and not err and len(lines_of(out, "LOADED")) == len(shared)
             and not lines_of(out, "INACTIVE"))
        case("gemini only runs --version and the listing",
             sorted(c[1:] for c in fake.calls) == sorted([["--version"], ["skills", "list"]]))
        case("evidence names surface, version and date",
             all(l[3] == "gemini skills list; gemini 0.28.2; 2026-11-12" for l in lines_of(out, "LOADED")))
        case("no INACTIVE: SUMMARY says none", out[-1].endswith("inactive_skills=none") and "loaded=%d" % len(shared) in out[-1])
        # gemini on stdout instead of stderr parses the same
        fake = Fake({"gemini"}, versions, {"gemini": (gemini_text, "")})
        rc, out, err = go(r, "gemini", fake, parsers)
        case("gemini listing on stdout", len(lines_of(out, "LOADED")) == len(shared))
        # INACTIVE: qdev removed from a fixture copy
        cut = re.sub(r"^qdev \[Enabled\]\n(?:  .*\n)*", "", gemini_text, flags=re.M)
        case("fixture copy lost qdev", "qdev [" not in cut)
        fake = Fake({"gemini"}, versions, {"gemini": ("", cut)})
        rc, out, err = go(r, "gemini", fake, parsers)
        ina = lines_of(out, "INACTIVE")
        case("removed skill is INACTIVE, exit 0", rc == 0 and [l[2] for l in ina] == ["qdev"]
             and "deployed but not in the client's listing" in ina[0][3])
        case("SUMMARY names the INACTIVE skill", out[-1].endswith("inactive_skills=gemini:qdev"))
        # disabled entry
        dis = gemini_text.replace("qdev [Enabled]", "qdev [Disabled]")
        fake = Fake({"gemini"}, versions, {"gemini": ("", dis)})
        rc, out, err = go(r, "gemini", fake, parsers)
        ina = lines_of(out, "INACTIVE")
        case("disabled entry is INACTIVE", rc == 0 and [l[2] for l in ina] == ["qdev"] and "listed [Disabled]" in ina[0][3])
        # unknown tag and missing header -> SKIP
        fake = Fake({"gemini"}, versions, {"gemini": ("", gemini_text.replace("qdev [Enabled]", "qdev [Pending]"))})
        rc, out, err = go(r, "gemini", fake, parsers)
        case("unknown gemini tag is SKIP", rc == 0 and len(lines_of(out, "SKIP")) == 1 and "unparseable output" in skipl(out, "gemini")
             and not lines_of(out, "LOADED"))
        fake = Fake({"gemini"}, versions, {"gemini": ("Error authenticating: x\n", "")})
        rc, out, err = go(r, "gemini", fake, parsers)
        case("gemini output with no header is SKIP", rc == 0 and out[0].startswith("SKIP\tgemini\tunparseable output")
             and not lines_of(out, "LOADED") and not lines_of(out, "INACTIVE"))
        # codex
        fake = Fake({"codex"}, versions, {"codex": (codex_text, "")})
        rc, out, err = go(r, "codex", fake, parsers)
        case("codex all loaded", rc == 0 and len(lines_of(out, "LOADED")) == len(shared) and not lines_of(out, "INACTIVE"))
        case("codex only runs --version and the listing",
             sorted(c[1:] for c in fake.calls) == sorted([["--version"], ["debug", "prompt-input"]]))
        data = json.loads(codex_text)
        txt = data[0]["content"][0]["text"]
        data[0]["content"][0]["text"] = re.sub(r"^- qdev: .*\n", "", txt, flags=re.M)
        fake = Fake({"codex"}, versions, {"codex": (json.dumps(data), "")})
        rc, out, err = go(r, "codex", fake, parsers)
        case("codex skill absent from the list is INACTIVE", [l[2] for l in lines_of(out, "INACTIVE")] == ["qdev"]
             and out[-1].endswith("inactive_skills=codex:qdev"))
        data[0]["content"][0]["text"] = "no skills here"
        fake = Fake({"codex"}, versions, {"codex": (json.dumps(data), "")})
        rc, out, err = go(r, "codex", fake, parsers)
        case("codex without a skills block is SKIP", out[0].startswith("SKIP\tcodex\tunparseable output")
             and not lines_of(out, "INACTIVE") and not lines_of(out, "LOADED"))
        data = json.loads(codex_text)
        data[0]["content"][0]["text"] = data[0]["content"][0]["text"].replace("### Available skills", "### Other")
        fake = Fake({"codex"}, versions, {"codex": (json.dumps(data), "")})
        rc, out, err = go(r, "codex", fake, parsers)
        case("codex without an Available skills list is SKIP", out[0].startswith("SKIP\tcodex\tunparseable output")
             and not lines_of(out, "INACTIVE"))
        fake = Fake({"codex"}, versions, {"codex": ("not json at all", "")})
        rc, out, err = go(r, "codex", fake, parsers)
        case("codex non-JSON output is SKIP", out[0].startswith("SKIP\tcodex\tunparseable output") and not lines_of(out, "INACTIVE"))
        fake = Fake({"codex"}, versions, {"codex": ('{"a": 1}', "")})
        rc, out, err = go(r, "codex", fake, parsers)
        case("codex JSON that is not a message list is SKIP", out[0].startswith("SKIP\tcodex\tunparseable output"))
        return bad

    bad = evaluate(None)
    chk("every case passes with the real parsers", not bad, "failed: %s" % ", ".join(bad))

    # mutation: break each parser and require the cases to notice
    def enabled_always(text):
        states, err = parse_gemini(text)
        return ({k: "enabled" for k in states}, err) if states is not None else (states, err)

    def never_fails_gemini(text):
        return parse_gemini(text)[0] or {n: "enabled" for n in shared}, None

    def codex_everything(text):
        return {n: "enabled" for n in shared}, None

    def codex_loose(text):
        states, err = parse_codex(text)
        return (states or {n: "enabled" for n in shared}), None
    for label, mutant in (("gemini treats [Disabled] as enabled", {"gemini-skills-list": enabled_always}),
                          ("gemini never reports unparseable", {"gemini-skills-list": never_fails_gemini}),
                          ("codex lists every skill", {"codex-prompt-input": codex_everything}),
                          ("codex never reports unparseable", {"codex-prompt-input": codex_loose})):
        caught = evaluate(mutant)
        chk("mutation caught: " + label, bool(caught), "no case failed")

    # missing binary, not selected, command failures, version mismatch
    r = make_repo(shared)
    rc, out, err = go(r, "gemini,codex", Fake(set()), None)
    chk("a missing binary is SKIP, not an error",
        rc == 0 and out[0].startswith("SKIP\tcodex\tcodex is not installed") and any(
            l.startswith("SKIP\tgemini\tgemini is not installed") for l in out) and not err, "%r" % out)
    rc, out, err = go(r, "gemini", Fake({"gemini", "codex", "claude", "kiro-cli"}, versions, {"gemini": ("", gemini_text)}),
                  keep_unselected=True)
    skips = {l.split("\t")[1]: l for l in out if l.startswith("SKIP\t")}
    chk("clients outside providers= are SKIP not selected",
        set(skips) == {"claude", "codex", "kiro"} and all("not selected in providers=gemini" in v for v in skips.values()), "%r" % out)
    for beh, needle in (("timeout", "command timed out after 60 s"), ("oserror", "command did not run (OSError: injected)"),
                        ("exit3", "command exited 3")):
        rc, out, err = go(r, "gemini", Fake({"gemini"}, versions, behavior={"gemini": beh}))
        chk("a %s command is SKIP and exits 0" % beh,
            rc == 0 and out[0].startswith("SKIP\tgemini\t" + needle) and not lines_of(out, "LOADED"), "%r" % out)
    rc, out, err = go(r, "gemini", Fake({"gemini"}, {"gemini": "0.29.1"}, {"gemini": ("", gemini_text)}))
    loaded = lines_of(out, "LOADED")
    chk("a version mismatch is noted on the line and the parser still runs",
        len(loaded) == len(shared) and all("ledger measured 0.28.2 on 2026-11-12; the parser may no longer fit" in l[3]
                                           and "gemini 0.29.1" in l[3] for l in loaded), "%r" % out[:2])
    rc, out, err = go(r, "gemini", Fake({"gemini"}, {"gemini": "no digits here"}, {"gemini": ("", gemini_text)}))
    chk("an unreadable version is named, the listing still parses",
        len(lines_of(out, "LOADED")) == len(shared) and "gemini version unknown" in lines_of(out, "LOADED")[0][3], "%r" % out[:2])

    # UNOBSERVABLE clients never run anything but --version
    kr = make_repo(shared, kiro_standalone=["qkirostd"])
    fake = Fake({"claude", "kiro-cli"}, versions)
    rc, out, err = go(kr, "claude,kiro", fake)
    unob = lines_of(out, "UNOBSERVABLE")
    chk("claude and kiro are UNOBSERVABLE, one line each, with version and date",
        rc == 0 and [l[1] for l in unob] == ["claude", "kiro"] and "claude 2.1.322; 2026-11-12" in unob[0][3]
        and "kiro 3.0.0; 2026-11-12" in unob[1][3], "%r" % out)
    chk("the Kiro line counts the standalone Kiro skill",
        ("%d deployed skills" % (len(shared) + 1)) in unob[1][2] and ("%d deployed skills" % len(shared)) in unob[0][2], "%r" % unob)
    chk("an UNOBSERVABLE client's only command is --version",
        fake.calls and all(c[1:] == ["--version"] for c in fake.calls), "%r" % fake.calls)
    rc, out, err = go(kr, "claude", Fake(set()))
    chk("an uninstalled UNOBSERVABLE client is SKIP", out[0].startswith("SKIP\tclaude\tclaude is not installed"), "%r" % out)

    # pointer file
    env = Env(which=Fake(set()).which, run=Fake(set()).run, today=lambda: "2026-11-12",
              pointer=os.path.join(tmp, "no-such-pointer"))
    rc, out, err = run([r], env)
    chk("a missing pointer file is one SKIP line, exit 0",
        rc == 0 and out[0].startswith("SKIP\t-\tpointer file not found") and out[-1].startswith("SUMMARY\tloaded=0\t"), "%r" % out)
    p = os.path.join(tmp, "nokeys")
    write(p, "root=/x\n")
    env = Env(which=Fake(set()).which, run=Fake(set()).run, today=lambda: "2026-11-12", pointer=p)
    rc, out, err = run([r], env)
    chk("a pointer without providers= is SKIP", rc == 0 and "has no providers= line" in out[0], "%r" % out)
    rc, out, err = go(r, "gemini,vim", Fake(set()))
    chk("an unknown provider name is SKIP", any(l.startswith("SKIP\tvim\tno row in the capability ledger") for l in out), "%r" % out)
    rc, out, err = go(r, "GEMINI , codex", Fake(set()))
    chk("provider names are trimmed and case-folded", sum(1 for l in out if "is not installed" in l) == 2, "%r" % out)

    # exit-2 preconditions
    rc, out, err = run([], Env())
    chk("no repo argument exits 2", rc == 2 and not out and "repo-root argument is required" in err[0], "%s %r" % (rc, err))
    rc, out, err = run([os.path.join(tmp, "nope")], Env())
    chk("a nonexistent repo exits 2", rc == 2 and "repo path not found" in err[0], "%r" % err)
    bare = os.path.join(tmp, "bare")
    os.makedirs(bare)
    rc, out, err = run([bare], Env())
    chk("a folder without shared/AGENTS.md exits 2", rc == 2 and "does not look like an agent-playbook repo" in err[0], "%r" % err)
    rc, out, err = run([make_repo([])], Env())
    chk("a repo with no skill exits 2", rc == 2 and "guard did not run" in err[0], "%r" % err)
    rc, out, err = run([r, "--pointer"], Env())
    chk("--pointer without a file exits 2", rc == 2 and "--pointer needs a file" in err[0], "%r" % err)

    # an unexpected error is exit 2, not a traceback
    def boom(binary):
        raise RuntimeError("injected")
    rc, out, err = run([r], Env(which=boom, pointer=pointer("gemini")))
    chk("an unexpected error is exit 2 'guard did not run'", rc == 2 and "guard did not run: RuntimeError: injected" in err[0], "%r" % err)

    shutil.rmtree(tmp, ignore_errors=True)
    for f in fails:
        print("FAIL: %s" % f)
    print("verify-client-load selftest: %d failure(s), %d check(s), 0 skipped" % (len(fails), checks[0]))
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
    try:
        if argv[:1] == ["--help"]:
            sys.stdout.write(__doc__.strip("\n") + "\n")
            return 0
        if argv[:1] == ["--selftest"]:
            return selftest()
        rc, out, err = run(argv)
        for line in out:
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
        for line in err:
            sys.stderr.write(line + "\n")
        return rc
    except Exception as exc:
        sys.stderr.write("%s: guard did not run: %s: %s\n" % (NAME, type(exc).__name__, exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
