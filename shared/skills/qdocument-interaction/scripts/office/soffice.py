"""Cross-platform LibreOffice headless wrapper.

Finds the soffice binary via known paths (registry on Windows, standard paths
on macOS/Linux) and invokes it in headless mode.

Usage:
    python soffice.py --check
    python soffice.py --convert-to <format> <input_file> [--outdir <dir>]
    python soffice.py --macro <macro_url> <input_file>

Exit codes: 0 = success, 1 = failure, 2 = LibreOffice not found
"""
import json
import os
import platform
import shutil
import subprocess
import sys


def _find_soffice_windows():
    """Find soffice on Windows via registry then common paths."""
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(root, r"SOFTWARE\LibreOffice\UNO\InstallPath")
                path, _ = winreg.QueryValueEx(key, "")
                winreg.CloseKey(key)
                exe = os.path.join(path, "soffice.exe")
                if os.path.isfile(exe):
                    return exe
            except OSError:
                continue
    except ImportError:
        pass
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\LibreOffice\program\soffice.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\LibreOffice\program\soffice.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _find_soffice_macos():
    """Find soffice on macOS."""
    candidates = [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _find_soffice_linux():
    """Find soffice on Linux."""
    found = shutil.which("soffice")
    if found:
        return found
    candidates = [
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
        "/snap/bin/libreoffice.soffice",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def find_soffice():
    """Return path to soffice binary or None."""
    system = platform.system()
    if system == "Windows":
        return _find_soffice_windows()
    elif system == "Darwin":
        return _find_soffice_macos()
    else:
        return _find_soffice_linux()


def main():
    if len(sys.argv) < 2:
        print("Usage: soffice.py --check | --convert-to <fmt> <file> [--outdir <dir>] | --macro <url> <file>", file=sys.stderr)
        sys.exit(1)

    soffice = find_soffice()

    if sys.argv[1] == "--check":
        if soffice:
            print(json.dumps({"found": True, "path": soffice}))
            sys.exit(0)
        else:
            print(json.dumps({"found": False, "path": None}))
            print("LibreOffice not found. Install from https://www.libreoffice.org/download/", file=sys.stderr)
            sys.exit(2)

    if not soffice:
        print("LibreOffice not found.", file=sys.stderr)
        sys.exit(2)

    env = os.environ.copy()
    env["HOME"] = env.get("HOME", os.path.expanduser("~"))

    if sys.argv[1] == "--convert-to":
        if len(sys.argv) < 4:
            print("Usage: soffice.py --convert-to <format> <input_file> [--outdir <dir>]", file=sys.stderr)
            sys.exit(1)
        fmt = sys.argv[2]
        input_file = sys.argv[3]
        outdir = "."
        if len(sys.argv) >= 6 and sys.argv[4] == "--outdir":
            outdir = sys.argv[5]
        cmd = [soffice, "--headless", "--convert-to", fmt, "--outdir", outdir, input_file]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    elif sys.argv[1] == "--macro":
        if len(sys.argv) < 4:
            print("Usage: soffice.py --macro <macro_url> <input_file>", file=sys.stderr)
            sys.exit(1)
        macro_url = sys.argv[2]
        input_file = sys.argv[3]
        cmd = [soffice, "--headless", "--invisible", "macro:///" + macro_url, input_file]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    else:
        print("Unknown option: " + sys.argv[1], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
