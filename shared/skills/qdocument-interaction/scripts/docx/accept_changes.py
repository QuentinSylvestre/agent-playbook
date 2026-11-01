"""Accept all tracked changes in a .docx file via LibreOffice macro.

Uses LibreOffice headless mode with a Basic macro that dispatches
.uno:AcceptAllTrackedChanges, then saves and closes the document.

Usage:
    python accept_changes.py <input_file> [<output_file>]

If output_file is omitted, the input file is overwritten.

Exit codes: 0 = success, 1 = failure, 2 = LibreOffice not found
"""
import os
import shutil
import subprocess
import sys
import tempfile


def _find_soffice():
    """Find LibreOffice soffice binary (standalone, no imports from office/)."""
    import platform
    system = platform.system()
    if system == "Windows":
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
    elif system == "Darwin":
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        ]
    else:
        found = shutil.which("soffice")
        if found:
            return found
        candidates = ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice"]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _write_macro(user_basic_dir, file_url, save_url):
    """Write a LibreOffice Basic macro that accepts changes and saves."""
    module_dir = os.path.join(user_basic_dir, "Standard")
    os.makedirs(module_dir, exist_ok=True)

    macro_code = f'''\
Sub AcceptAllChanges()
    Dim sUrl As String
    Dim oDoc As Object
    Dim oDispatcher As Object
    Dim oFrame As Object
    Dim aArgs(0) As New com.sun.star.beans.PropertyValue

    sUrl = "{file_url}"
    aArgs(0).Name = "Hidden"
    aArgs(0).Value = True

    oDoc = StarDesktop.loadComponentFromURL(sUrl, "_blank", 0, aArgs())
    If IsNull(oDoc) Or IsEmpty(oDoc) Then
        MsgBox "Failed to open document"
        Exit Sub
    End If

    oFrame = oDoc.getCurrentController().getFrame()
    oDispatcher = createUnoService("com.sun.star.frame.DispatchHelper")
    oDispatcher.executeDispatch(oFrame, ".uno:AcceptAllTrackedChanges", "", 0, Array())

    Dim aSaveArgs(0) As New com.sun.star.beans.PropertyValue
    aSaveArgs(0).Name = "FilterName"
    aSaveArgs(0).Value = "MS Word 2007 XML"

    oDoc.storeToURL("{save_url}", aSaveArgs())
    oDoc.close(True)
End Sub
'''
    macro_path = os.path.join(module_dir, "AcceptChanges.xba")
    with open(macro_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">\n')
        f.write('<script:module xmlns:script="http://openoffice.org/2000/script" ')
        f.write('script:name="AcceptChanges" script:language="StarBasic">\n')
        f.write(macro_code)
        f.write('</script:module>\n')

    # Ensure script.xlb lists our module
    xlb_path = os.path.join(module_dir, "script.xlb")
    xlb_content = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false">
 <library:element library:name="AcceptChanges"/>
</library:library>
'''
    with open(xlb_path, "w", encoding="utf-8") as f:
        f.write(xlb_content)

    return macro_path


def _path_to_url(path):
    """Convert a file path to a file:// URL for LibreOffice."""
    import pathlib
    return pathlib.Path(path).as_uri()


def main():
    if len(sys.argv) < 2:
        print("Usage: accept_changes.py <input_file> [<output_file>]", file=sys.stderr)
        sys.exit(1)

    input_file = os.path.abspath(sys.argv[1])
    output_file = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else input_file

    if not os.path.isfile(input_file):
        print("Error: input file not found: " + input_file, file=sys.stderr)
        sys.exit(1)

    soffice = _find_soffice()
    if not soffice:
        print("Error: LibreOffice not found. Install from https://www.libreoffice.org/download/", file=sys.stderr)
        sys.exit(2)

    # Set up a temporary user profile for LibreOffice with our macro
    tmpdir = tempfile.mkdtemp(prefix="lo_accept_")
    try:
        user_profile = os.path.join(tmpdir, "user")
        basic_dir = os.path.join(user_profile, "basic")
        os.makedirs(basic_dir, exist_ok=True)

        file_url = _path_to_url(input_file)
        save_url = _path_to_url(output_file)

        _write_macro(basic_dir, file_url, save_url)

        env = os.environ.copy()
        env["HOME"] = tmpdir  # Unix profile isolation

        cmd = [
            soffice, "--headless", "--norestore", "--nofirststartwizard",
            "-env:UserInstallation=" + _path_to_url(user_profile),
            "macro:///Standard.AcceptChanges.AcceptAllChanges"
        ]

        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print("LibreOffice macro error: " + result.stderr, file=sys.stderr)
            sys.exit(1)

        if not os.path.isfile(output_file):
            print("Error: output file was not created", file=sys.stderr)
            sys.exit(1)

    except subprocess.TimeoutExpired:
        print("Error: LibreOffice timed out after 60s", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
