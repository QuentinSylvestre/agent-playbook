#!/usr/bin/env python3
"""settings-entries.py -- report, add and remove the playbook's entries in Claude Code's settings files.

Setup symlinks the Claude Code scripts, but they only run once ~/.claude/settings.json points at them.
Claude Code rewrites that file itself, so it is not tracked and is never rendered from a template.

Usage:
  settings-entries.py check [--home DIR]   Report three groups. Read-only. /qconfig-sync Step 3 runs this.
  settings-entries.py offer --home DIR     Ask once per missing group, then merge the accepted ones.
                                           Setup runs this at a terminal. Writes nothing without a person.
  settings-entries.py remove --home DIR    Remove the playbook's entries. Setup's uninstall runs this.
  settings-entries.py --selftest

The writing actions take --home explicitly, so a sandboxed setup can never reach the real home through an
environment variable it did not override.

Groups, and what `check` says when one is missing:
  memory-hook  SessionStart runs memory-load-hook   WARN: session memory silently disappears without it
  status-line  statusLine runs statusline-command   INFO: a personal choice
  sounds       Notification or Stop runs notify     INFO: a personal choice

An entry counts as present when its command names the script, whatever its form, so an older form or a
dropped matcher is not flagged. remove is stricter: it takes only a command naming a playbook script by its
exact filename under a .claude folder, so a similarly named script of the user's survives. Both settings.json
and settings.local.json are read. No choice is stored, so a declined group is asked about again on the next
manual setup run. A home where setup did not deploy for Claude Code reports SKIP, whatever its settings hold.

check output, one tab-separated line per group: OK|INFO|WARN|SKIP <TAB> group <TAB> state. Only group names
and states are printed, never a value from the settings files: they can hold credentials, and the runner
keeps this output in its work folder. Exit 0 whatever is found (a WARN never fails a sync); 2 on a usage
error or when the venv is missing.

offer merges on Windows only. The README marks the other platforms' forms unsupported or unverified, so
there it points to the README. It adds to settings.json only, keeps everything else, never replaces a
statusLine, takes a backup first, writes atomically, and refuses when the file changed since it was read
or does not parse.

Stdlib only, Python 3.8+.
"""
import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"
MEMORY_MARK = "memory-load-hook"
STATUS_MARK = "statusline-command"
SOUND_MARK = "notify-command"
OURS_RE = re.compile(r"\.claude[\\/](memory-load-hook\.(ps1|py)|statusline-command\.sh|notify-command\.ps1)(?=$|[\"'\s])")
DEPLOYED_FILES = ("memory-load-hook.ps1", "memory-load-hook.py", "statusline-command.sh", "notify-command.ps1")
MEMORY_MATCHER = "startup|resume|clear|compact"
README = "providers/claude/README.md"


# --- venv guard stub: same text as the qdream scripts', except the one line naming where venv-selfcheck.py is ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "shared", "skills", "qdream", "scripts", "venv-selfcheck.py")
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


class Refused(Exception):
    """The file cannot be changed safely. The message names no value from the file."""


def default_home():
    """verify-deployment.py's order on Windows; HOME elsewhere."""
    if IS_WINDOWS:
        return Path(os.environ.get("USERPROFILE") or Path.home())
    return Path(os.environ.get("HOME") or Path.home())


def load(path):
    """-> (data or None, raw bytes or None, problem or None). An absent file is no problem."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, None, None
    except OSError as exc:
        return None, None, "cannot be read (%s)" % type(exc).__name__
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError:  # the exception's message could quote the file: name only the fact
        return None, raw, "does not parse as JSON"
    if not isinstance(data, dict):
        return None, raw, "is not a JSON object"
    return data, raw, None


def hook_text(hook):
    """A hook's command and its args as one string, for looking up a script name."""
    if not isinstance(hook, dict):
        return ""
    args = hook.get("args")
    parts = [hook.get("command")] + (args if isinstance(args, list) else [])
    return " ".join(p for p in parts if isinstance(p, str))


def has_hook(data, event, mark):
    hooks = data.get("hooks") if isinstance(data, dict) else None
    groups = hooks.get(event) if isinstance(hooks, dict) else None
    for group in groups if isinstance(groups, list) else []:
        inner = group.get("hooks") if isinstance(group, dict) else None
        if any(mark in hook_text(h) for h in (inner if isinstance(inner, list) else [])):
            return True
    return False


def status_state(data):
    """-> 'ours', 'custom' or None."""
    entry = data.get("statusLine") if isinstance(data, dict) else None
    if entry is None:
        return None
    return "ours" if isinstance(entry, dict) and STATUS_MARK in hook_text(entry) else "custom"


def group_states(files):
    """-> {memory, status, sounds} over the settings files' parsed contents."""
    status = None
    for data in files:
        status = status_state(data) or status
    return {
        "memory": any(has_hook(d, "SessionStart", MEMORY_MARK) for d in files),
        "status": status,
        "sounds": any(has_hook(d, "Notification", SOUND_MARK) or has_hook(d, "Stop", SOUND_MARK) for d in files),
    }


def settings_paths(home):
    claude = Path(home) / ".claude"
    return claude / "settings.json", claude / "settings.local.json"


def check(home):
    main_path, local_path = settings_paths(home)
    loaded = [load(main_path), load(local_path)]
    problems = [(p.name, item[2]) for p, item in zip((main_path, local_path), loaded) if item[2]]
    if not any(os.path.lexists(str(Path(home) / ".claude" / n)) for n in DEPLOYED_FILES):
        print("SKIP\tclaude-settings\tnot deployed for Claude Code in this home")
        return 0
    for name, problem in problems:
        print("WARN\tclaude-settings\t%s %s -- fix the file; the groups below were not read" % (name, problem))
    if problems:
        return 0
    states = group_states([item[0] for item in loaded if item[0] is not None])
    if states["memory"]:
        print("OK\tmemory-hook\tpresent")
    elif IS_WINDOWS:
        print("WARN\tmemory-hook\tnot set, so sessions start without the memory index -- run setup at a terminal "
              "to add it (%s)" % README)
    else:
        print("SKIP\tmemory-hook\tnot set; its launcher is not supported on this platform (%s)" % README)
    status = {"ours": ("OK", "present"), "custom": ("OK", "your own status line")}.get(states["status"], ("INFO", "not set"))
    print("%s\tstatus-line\t%s" % (status[0], status[1]))
    print("OK\tsounds\tpresent" if states["sounds"] else "INFO\tsounds\tnot set")
    return 0


def _ps_command(home, script, suffix=""):
    return 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%s/.claude/%s"%s' % (home, script, suffix)


def _hook_group(command, matcher=None):
    group = {"matcher": matcher} if matcher else {}
    group["hooks"] = [{"type": "command", "command": command}]
    return group


def _add_hook_group(data, event, group):
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise Refused("its hooks key is not an object")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise Refused("its %s hooks are not a list" % event)
    groups.append(group)


def add_group(data, group, home):
    """Add one group to parsed settings. The README's stanzas are the same text."""
    home = str(home).replace("\\", "/")
    if group == "memory":
        _add_hook_group(data, "SessionStart", _hook_group(_ps_command(home, "memory-load-hook.ps1"), MEMORY_MATCHER))
    elif group == "status":
        data["statusLine"] = {"type": "command", "command": 'bash "%s/.claude/statusline-command.sh"' % home}
    elif group == "sounds":
        _add_hook_group(data, "Notification", _hook_group(
            _ps_command(home, "notify-command.ps1", " -Event permission"), "permission_prompt"))
        _add_hook_group(data, "Notification", _hook_group(
            _ps_command(home, "notify-command.ps1", " -Event idle"), "idle_prompt"))
        _add_hook_group(data, "Stop", _hook_group(_ps_command(home, "notify-command.ps1", " -Event done")))
    else:
        raise ValueError(group)


def strip_ours(data):
    """Remove the playbook's entries from parsed settings. -> True when anything changed."""
    changed = False
    if OURS_RE.search(hook_text(data.get("statusLine"))):
        del data["statusLine"]
        changed = True
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return changed
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept_groups.append(group)
                continue
            kept = [h for h in inner if not OURS_RE.search(hook_text(h))]
            if len(kept) != len(inner):
                changed = True
                group["hooks"] = kept
            if kept or len(kept) == len(inner):
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    return changed


def write_settings(path, original, data):
    """Back up, then replace atomically. Refuses when the file changed since `original` was read."""
    target = Path(os.path.realpath(str(path)))
    try:
        current = target.read_bytes()
    except FileNotFoundError:
        current = None
    if current != original:
        raise Refused("it changed while this ran, so nothing was written; run again")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    payload = text.encode("utf-8")  # before the backup: a value that cannot be encoded changes nothing
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if current is not None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = target.with_name("%s.bak-playbook-%s" % (target.name, stamp))
        serial = 1
        while backup.exists():
            serial += 1
            backup = target.with_name("%s.bak-playbook-%s-%d" % (target.name, stamp, serial))
        shutil.copy2(str(target), str(backup))
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        if current is not None:
            shutil.copymode(str(target), tmp)
        os.replace(tmp, str(target))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return backup


def offer(home, ask=None, tty=None):
    """Interactive merge. `ask` and `tty` exist for the selftest."""
    if not IS_WINDOWS:
        print("  NOTE: add the Claude Code entries by hand on this platform: see %s" % README)
        return 0
    if tty is None:
        tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not tty:
        print("  NOTE: this terminal cannot prompt, so settings.json was not changed. Run setup.ps1 from "
              "PowerShell to add the Claude Code entries, or see %s." % README)
        return 0
    main_path, local_path = settings_paths(home)
    data, raw, problem = load(main_path)
    local, _, local_problem = load(local_path)
    if problem or local_problem:
        print("  WARN: settings.json was not changed: %s %s." % (
            (main_path.name, problem) if problem else (local_path.name, local_problem)))
        return 0
    data = {} if data is None else data
    states = group_states([data] + ([local] if local is not None else []))
    questions = []
    if not states["memory"]:
        questions.append(("memory", "the SessionStart memory hook, which loads the memory index into each session", True))
    if states["status"] == "custom":
        print("  KEPT: your own statusLine")
    elif states["status"] is None:
        jq = shutil.which("jq") is not None
        what = "the status line" if jq else "the status line (it needs jq, which was not found)"
        questions.append(("status", what, jq))
    if not states["sounds"]:
        questions.append(("sounds", "the notification sounds", False))
    if not questions:
        print("  OK: the Claude Code settings.json entries are present")
        return 0
    ask = ask or input
    chosen = []
    print("Claude Code entries in ~/.claude/settings.json:")
    for group, what, default in questions:
        hint = "Y/n" if default else "y/N"
        try:
            answer = ask("  Add %s? [%s] " % (what, hint)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("")
            print("  NOTE: settings.json was not changed")
            return 0
        if answer in ("y", "yes") or (not answer and default):
            chosen.append((group, what))
    if not chosen:
        print("  NOTE: settings.json was not changed. Setup asks again next time; see %s." % README)
        return 0
    try:
        for group, _ in chosen:
            add_group(data, group, home)
        backup = write_settings(main_path, raw, data)
    except (Refused, OSError, UnicodeError) as exc:
        reason = str(exc) if isinstance(exc, Refused) else type(exc).__name__
        print("  WARN: settings.json was not changed: %s" % reason)
        return 0
    if backup:
        print("  BACKUP: ~/.claude/%s" % backup.name)
    for group, what in chosen:
        print("  ADDED: %s" % group)
    print("  NOTE: restart open Claude Code sessions, then run /hooks to confirm.")
    return 0


def remove(home):
    for path in settings_paths(home):
        data, raw, problem = load(path)
        if problem:
            print("  KEPT: ~/.claude/%s %s; remove the playbook's entries by hand" % (path.name, problem))
            continue
        if data is None or not strip_ours(data):
            continue
        try:
            backup = write_settings(path, raw, data)
        except (Refused, OSError, UnicodeError) as exc:
            reason = str(exc) if isinstance(exc, Refused) else type(exc).__name__
            print("  KEPT: ~/.claude/%s: %s" % (path.name, reason))
            continue
        print("  REMOVED: the playbook's entries from ~/.claude/%s (backup: %s)" % (path.name, backup.name))
    return 0


# --- selftest ---------------------------------------------------------------

def _capture(func, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = func(*args, **kwargs)
    return code, out.getvalue()


def _write(home, name, content):
    path = Path(home) / ".claude" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (bytes, str)):
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    else:
        path.write_text(json.dumps(content), encoding="utf-8")
    return path


def _deployed(home):
    _write(home, "memory-load-hook.ps1", "x")


def _read(home, name="settings.json"):
    return json.loads((Path(home) / ".claude" / name).read_text(encoding="utf-8"))


def _answers(*replies):
    queue = list(replies)
    return lambda prompt: queue.pop(0)


def _full_entries(home="C:/Users/alice"):
    data = {}
    for group in ("memory", "status", "sounds"):
        add_group(data, group, home)
    return data


def _case_absent_home_is_not_deployed(home):
    code, out = _capture(check, home)
    assert code == 0 and out.startswith("SKIP\tclaude-settings"), out


def _case_deployed_without_settings_warns(home):
    _write(home, "memory-load-hook.ps1", "x")
    code, out = _capture(check, home)
    assert code == 0 and "WARN\tmemory-hook" in out and "INFO\tstatus-line" in out and "INFO\tsounds" in out, out


def _case_all_groups_present(home):
    _deployed(home)
    _write(home, "settings.json", _full_entries())
    code, out = _capture(check, home)
    assert code == 0 and out.split("\n")[:3] == ["OK\tmemory-hook\tpresent", "OK\tstatus-line\tpresent", "OK\tsounds\tpresent"], out


def _case_settings_without_deployment_is_not_warned(home):
    _write(home, "settings.json", {"model": "m"})
    code, out = _capture(check, home)
    assert code == 0 and out.startswith("SKIP\tclaude-settings") and "WARN" not in out, out


def _case_older_python_form_counts(home):
    _deployed(home)
    _write(home, "settings.json", {"hooks": {"SessionStart": [{"hooks": [{"command": "C:/py/python.exe C:/h/.claude/memory-load-hook.py"}]}]}})
    assert "OK\tmemory-hook" in _capture(check, home)[1]


def _case_exec_args_form_counts(home):
    _deployed(home)
    _write(home, "settings.json", {"hooks": {"SessionStart": [{"hooks": [{"command": "python3", "args": ["/h/.claude/memory-load-hook.py"]}]}]}})
    assert "OK\tmemory-hook" in _capture(check, home)[1]


def _case_local_settings_count(home):
    _deployed(home)
    _write(home, "settings.local.json", _full_entries())
    assert "OK\tmemory-hook" in _capture(check, home)[1]


def _case_dropped_matcher_still_present(home):
    _deployed(home)
    data = _full_entries()
    del data["hooks"]["Notification"][1]
    _write(home, "settings.json", data)
    assert "OK\tsounds" in _capture(check, home)[1]


def _case_custom_status_line_is_ok(home):
    _deployed(home)
    _write(home, "settings.json", {"statusLine": {"type": "command", "command": "mine.sh"}})
    assert "OK\tstatus-line\tyour own status line" in _capture(check, home)[1]


def _case_unparseable_warns_without_content(home):
    _deployed(home)
    _write(home, "settings.json", '{"env": {"TOKEN": "secret-marker"')
    code, out = _capture(check, home)
    assert code == 0 and "WARN\tclaude-settings\tsettings.json does not parse" in out and "secret-marker" not in out, out


def _case_values_never_printed(home):
    _deployed(home)
    data = _full_entries()
    data["env"] = {"TOKEN": "secret-marker"}
    _write(home, "settings.json", data)
    assert "secret-marker" not in _capture(check, home)[1]


def _case_malformed_shapes_do_not_crash(home):
    _deployed(home)
    _write(home, "settings.json", {"hooks": {"SessionStart": "x", "Stop": [1, {"hooks": 2}]}, "statusLine": 3})
    code, out = _capture(check, home)
    assert code == 0 and "WARN\tmemory-hook" in out and "OK\tstatus-line" in out, out


def _case_offer_defaults_add_memory_only_without_jq(home):
    saved = shutil.which
    shutil.which = lambda name: None
    try:
        _write(home, "settings.json", {"model": "m"})
        _capture(offer, home, ask=_answers("", "", ""), tty=True)
    finally:
        shutil.which = saved
    data = _read(home)
    assert data["model"] == "m" and "SessionStart" in data["hooks"], data
    assert "statusLine" not in data and "Stop" not in data["hooks"], data


def _case_offer_status_default_yes_with_jq(home):
    saved = shutil.which
    shutil.which = lambda name: "jq"
    try:
        _write(home, "settings.json", {})
        _capture(offer, home, ask=_answers("", "", ""), tty=True)
    finally:
        shutil.which = saved
    assert status_state(_read(home)) == "ours"


def _case_offer_keeps_other_content_and_order(home):
    _write(home, "settings.json", {"z": 1, "hooks": {"PreToolUse": [{"hooks": [{"command": "mine"}]}]}, "a": {"é": True}})
    _capture(offer, home, ask=_answers("y", "n", "n"), tty=True)
    data = _read(home)
    assert list(data) == ["z", "hooks", "a"] and data["a"] == {"é": True}, data
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "mine", data


def _case_offer_adds_beside_foreign_stop_hook(home):
    _write(home, "settings.json", {"hooks": {"Stop": [{"hooks": [{"command": "research-stop"}]}]}})
    _capture(offer, home, ask=_answers("n", "n", "y"), tty=True)
    stops = _read(home)["hooks"]["Stop"]
    assert len(stops) == 2 and stops[0]["hooks"][0]["command"] == "research-stop", stops


def _case_offer_never_replaces_status_line(home):
    _write(home, "settings.json", {"statusLine": {"command": "mine.sh"}})
    code, out = _capture(offer, home, ask=_answers("n", "n"), tty=True)
    assert "KEPT: your own statusLine" in out and _read(home)["statusLine"] == {"command": "mine.sh"}, out


def _case_offer_second_run_changes_nothing(home):
    _write(home, "settings.json", {})
    _capture(offer, home, ask=_answers("y", "y", "y"), tty=True)
    before = (Path(home) / ".claude" / "settings.json").read_bytes()
    code, out = _capture(offer, home, ask=_answers(), tty=True)
    assert "OK: the Claude Code" in out and (Path(home) / ".claude" / "settings.json").read_bytes() == before, out


def _case_offer_creates_absent_file_without_backup(home):
    _capture(offer, home, ask=_answers("y", "n", "n"), tty=True)
    assert "SessionStart" in _read(home)["hooks"]
    assert not list((Path(home) / ".claude").glob("*.bak-playbook-*"))


def _case_offer_backs_up_exact_bytes(home):
    original = '{ "model" :  "m" }'
    _write(home, "settings.json", original)
    _capture(offer, home, ask=_answers("y", "n", "n"), tty=True)
    backups = list((Path(home) / ".claude").glob("settings.json.bak-playbook-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == original, backups


def _case_offer_without_tty_writes_nothing(home):
    path = _write(home, "settings.json", {"model": "m"})
    before = path.read_bytes()
    code, out = _capture(offer, home, ask=_answers(), tty=False)
    assert code == 0 and path.read_bytes() == before and "cannot prompt" in out, out


def _case_offer_unparseable_writes_nothing(home):
    path = _write(home, "settings.json", "{broken")
    code, out = _capture(offer, home, ask=_answers(), tty=True)
    assert path.read_bytes() == b"{broken" and "does not parse" in out, out


def _case_offer_non_object_hooks_refused(home):
    path = _write(home, "settings.json", {"hooks": 3})
    before = path.read_bytes()
    code, out = _capture(offer, home, ask=_answers("y", "n", "n"), tty=True)
    assert path.read_bytes() == before and "WARN" in out, out


def _case_offer_declined_writes_nothing(home):
    path = _write(home, "settings.json", {"model": "m"})
    before = path.read_bytes()
    _capture(offer, home, ask=_answers("n", "n", "n"), tty=True)
    assert path.read_bytes() == before and not list(path.parent.glob("*.bak-playbook-*"))


def _case_offer_interrupted_writes_nothing(home):
    path = _write(home, "settings.json", {"model": "m"})
    before = path.read_bytes()

    def interrupted(prompt):
        raise KeyboardInterrupt

    code, out = _capture(offer, home, ask=interrupted, tty=True)
    assert code == 0 and path.read_bytes() == before, out


def _case_concurrent_change_refused(home):
    path = _write(home, "settings.json", {"model": "m"})
    raw = path.read_bytes()
    path.write_text('{"model": "changed"}', encoding="utf-8")
    try:
        write_settings(path, raw, {"model": "mine"})
    except Refused:
        assert _read(home) == {"model": "changed"}
        return
    raise AssertionError("write went through")


def _case_no_temp_file_left(home):
    _write(home, "settings.json", {})
    _capture(offer, home, ask=_answers("y", "n", "n"), tty=True)
    assert not list((Path(home) / ".claude").glob("*.tmp-*"))


def _case_non_windows_offer_writes_nothing(home):
    global IS_WINDOWS
    saved = IS_WINDOWS
    IS_WINDOWS = False
    try:
        code, out = _capture(offer, home, ask=_answers(), tty=True)
    finally:
        IS_WINDOWS = saved
    assert code == 0 and README in out and not (Path(home) / ".claude" / "settings.json").exists(), out


def _case_non_windows_memory_hook_is_not_warned(home):
    global IS_WINDOWS
    saved = IS_WINDOWS
    IS_WINDOWS = False
    try:
        _write(home, "statusline-command.sh", "x")
        code, out = _capture(check, home)
    finally:
        IS_WINDOWS = saved
    assert "WARN" not in out and "memory-hook" in out, out


def _case_remove_only_ours(home):
    data = _full_entries()
    data["model"] = "m"
    _add_hook_group(data, "Stop", _hook_group("research-stop"))
    data["hooks"]["SessionStart"][0]["hooks"].append({"command": "mine"})
    _write(home, "settings.json", data)
    _capture(remove, home)
    after = _read(home)
    assert after["model"] == "m" and "statusLine" not in after and "Notification" not in after["hooks"], after
    assert after["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "research-stop"}]}], after
    assert after["hooks"]["SessionStart"][0]["hooks"] == [{"command": "mine"}], after


def _case_remove_keeps_near_miss_names(home):
    near = {"statusLine": {"command": "bash /x/.claude/ccstatusline-command.sh"},
            "hooks": {"Stop": [{"hooks": [{"command": "/x/.claude/my-notify-command.ps1"},
                                          {"command": "/x/.claude/notify-command.ps1.bak"},
                                          {"command": "/elsewhere/notify-command.ps1"}]}]}}
    path = _write(home, "settings.json", near)
    before = path.read_bytes()
    _capture(remove, home)
    assert path.read_bytes() == before and not list(path.parent.glob("*.bak-playbook-*"))


def _case_remove_handles_the_forms_setup_and_readme_write(home):
    data = _full_entries("C:/Users/alice")
    _add_hook_group(data, "SessionStart", _hook_group("C:/py/python.exe C:\\Users\\alice\\.claude\\memory-load-hook.py"))
    data["hooks"]["SessionStart"].append({"hooks": [{"command": "python3", "args": ["/h/.claude/memory-load-hook.py"]}]})
    _write(home, "settings.json", data)
    _capture(remove, home)
    assert _read(home) == {}, _read(home)


def _case_unencodable_value_changes_nothing(home):
    path = _write(home, "settings.json", {"model": "m"})
    raw = path.read_bytes()
    try:
        write_settings(path, raw, {"model": "\ud800"})
    except UnicodeError:
        assert path.read_bytes() == raw and not list(path.parent.glob("*.bak-playbook-*"))
        return
    raise AssertionError("write went through")


def _case_remove_drops_empty_hooks_key_and_backs_up(home):
    _write(home, "settings.json", _full_entries())
    code, out = _capture(remove, home)
    assert code == 0 and _read(home) == {} and "REMOVED" in out, out
    assert list((Path(home) / ".claude").glob("settings.json.bak-playbook-*"))


def _case_remove_covers_local_settings(home):
    _write(home, "settings.local.json", _full_entries())
    _capture(remove, home)
    assert _read(home, "settings.local.json") == {}


def _case_remove_keeps_custom_status_line(home):
    _write(home, "settings.json", {"statusLine": {"command": "mine.sh"}})
    path = Path(home) / ".claude" / "settings.json"
    before = path.read_bytes()
    _capture(remove, home)
    assert path.read_bytes() == before and not list(path.parent.glob("*.bak-playbook-*"))


def _case_remove_absent_or_broken_is_harmless(home):
    assert _capture(remove, home)[0] == 0
    path = _write(home, "settings.json", "{broken")
    code, out = _capture(remove, home)
    assert code == 0 and path.read_bytes() == b"{broken" and "KEPT" in out, out


def _case_write_actions_need_explicit_home(home):
    for action in ("offer", "remove"):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                main([action])
        except SystemExit as exc:
            assert exc.code == 2 and "--home" in err.getvalue(), err.getvalue()
        else:
            raise AssertionError(action + " ran without --home")


def selftest():
    global IS_WINDOWS
    cases = [(n[len("_case_"):], f) for n, f in sorted(globals().items()) if n.startswith("_case_")]
    failed = 0
    saved = IS_WINDOWS
    IS_WINDOWS = True  # the merge is Windows-only, and every OS tests it; the non_windows cases say otherwise
    try:
        for name, func in cases:
            with tempfile.TemporaryDirectory(prefix="se-") as home:
                try:
                    func(home)
                except Exception as exc:  # a selftest reports every case, whatever went wrong in one
                    failed += 1
                    print("FAIL %s -- %s: %s" % (name, type(exc).__name__, exc))
                else:
                    print("PASS %s" % name)
    finally:
        IS_WINDOWS = saved
    print("selftest: %d case(s), %d failed" % (len(cases), failed))
    return 1 if failed else 0


def main(argv=None):
    _require_venv(__file__)
    ap = argparse.ArgumentParser(description="Report, add and remove the playbook's Claude Code settings entries.")
    ap.add_argument("action", nargs="?", choices=("check", "offer", "remove"))
    ap.add_argument("--home")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.action:
        ap.error("name an action: check, offer or remove")
    if args.action == "check":
        return check(Path(args.home) if args.home else default_home())
    if not args.home:
        ap.error("%s writes, so it needs an explicit --home" % args.action)
    return (offer if args.action == "offer" else remove)(Path(args.home))


if __name__ == "__main__":
    sys.exit(main())
