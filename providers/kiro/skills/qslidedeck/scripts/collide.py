"""Run the deck shell's ?check mode on one slide in headless Chrome and return what it found.

    python collide.py <built-deck.html> [slide numbers]      (prints findings; all slides by default)

Each finding: {kind, x, y, w, h, what}, coordinates in slide pixels (1600x900). Kinds:
  text-overlap   two pieces of text touch
  line-on-text   a diagram line or arrow crosses visible text
  text-overflow  text sticks out of the card, pill or chip that holds it, or out of the slide
  text-covered   an opaque box is painted over text
  box-overlap    two boxes partly overlap (neither contains the other)
  title-mark     (title slide) the info record of the brand mark box, used by shoot.py
"""
import json, os, re, shutil, subprocess, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def check(chrome, html: Path, k: int):
    """List of findings, or None when the check did not run (deck not built with this skill's shell)."""
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1600,900",
                        "--virtual-time-budget=3000", "--dump-dom", html.as_uri() + f"?noanim&check#{k}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ms = re.findall(r'<pre id="qsd-check">(.*?)</pre>', r.stdout, re.S)
    if not ms:
        return None
    txt = ms[-1].replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    return json.loads(txt)


if __name__ == "__main__":
    chrome = find_chrome()
    if not chrome:
        sys.exit("FAIL: Chrome not found. Install Google Chrome, or tell the user the checks cannot run.")
    html = Path(sys.argv[1]).resolve()
    n = len(re.findall(r'<section\s+class="slide[\s"]', html.read_text(encoding="utf-8")))
    ks = [int(a) for a in sys.argv[2:]] or range(1, n + 1)
    for k in ks:
        res = check(chrome, html, k)
        if res is None:
            print(f"slide {k}: CHECK DID NOT RUN - rebuild the deck with build.py, then retry")
            continue
        res = [f for f in res if f["kind"] != "title-mark"]
        print(f"slide {k}: {len(res)} finding(s)")
        for f in res:
            print(f"   {f['kind']:13} at ({f['x']:.0f},{f['y']:.0f},{f['w']:.0f}x{f['h']:.0f})  {f['what']}")
