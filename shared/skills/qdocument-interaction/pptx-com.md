# PowerPoint COM Safety Patterns

Reference for write-path COM operations on a currently open PowerPoint presentation on Windows. Read alongside `pptx.md` (co-located) for creation and XML editing workflows.

These patterns apply when the user has a presentation currently open in PowerPoint and the task involves modifying it via COM — distinct from read-only COM operations such as `scripts/pptx/export_slide_images.py`, which opens a closed file by path. A connection note (`## Establishing the COM connection`) precedes the 8 numbered safety patterns.

---

## Establishing the COM connection

`win32com.client.GetActiveObject("PowerPoint.Application")` connects to a running instance. `win32com.client.Dispatch("PowerPoint.Application")` creates a new invisible window — its `Presentations` collection is empty, so the **Never trust ActivePresentation** loop finds nothing.

```python
import win32com.client
app = win32com.client.GetActiveObject("PowerPoint.Application")
```

Use `GetActiveObject` for all live-open-presentation tasks; use `Dispatch` only when starting PowerPoint from a script.

---

## Snapshot before any bulk COM edit

**Hazard.** Running a script that walks all 50 slides with no backup means one bug corrupts the entire deck with no undo. PowerPoint's in-process undo stack does not survive a Python crash or a `pres.Save()` call mid-run.

**Corrective.** Copy the deck to a timestamped backup before any bulk script. Filename pattern: `<deck>.YYYYMMDD-HHMMSS.<label>.pptx`, placed beside the source file. Save as `backup_snapshot.py` in your project directory and call it at the top of every bulk run. The script accepts `--file <path> --label <label>` and refuses to overwrite an existing backup.

```python
import shutil, datetime, pathlib

def backup(path, label):
    p = pathlib.Path(path)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = p.with_name(f"{p.stem}.{ts}.{label}{p.suffix}")
    if dest.exists():
        raise FileExistsError(f"Backup already exists: {dest}")
    shutil.copy2(p, dest)
    return dest
```

> **Note:** `shutil.copy2` copies the last-saved file on disk — if the presentation has unsaved edits open in PowerPoint, those edits will not be in the backup. Save the presentation in PowerPoint before running this script. For an in-session backup via an active COM connection, use `pres.SaveCopyAs(os.path.normpath(os.path.abspath(backup_path)))` instead — Pattern 8 covers the path normalization requirement.

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Snapshot a PowerPoint file before bulk edits.")
    parser.add_argument("--file", required=True, help="Path to the .pptx file to snapshot")
    parser.add_argument("--label", required=True, help="Label suffix for the backup filename")
    args = parser.parse_args()
    result = backup(args.file, args.label)
    print(result)
```

---

## Never trust ActivePresentation

**Hazard.** `app.ActivePresentation` returns whichever deck has focus at the moment the script runs. Clicking another PowerPoint window while the script is mid-run silently redirects all edits to the wrong file.

**Corrective.** Loop over `app.Presentations` and match by name: exact match first, substring fallback. Raise an error if the target is not found.

```python
pres = next((p for p in app.Presentations if p.Name == "MyDeck.pptx"), None)
if pres is None:
    pres = next((p for p in app.Presentations if "MyDeck" in p.Name), None)
if pres is None:
    raise RuntimeError("Target presentation not found in PowerPoint")
```

Never use `app.ActivePresentation` in an unattended script.

---

## Idempotent build scripts — rebuild, don't patch

**Hazard.** Patching existing slide content leaves orphaned shapes when the slide structure changes between runs. The script becomes unpredictable after the first execution.

**Corrective.** Write one `build_slide_NN.py` per non-trivial slide. The `clear_and_bg()` helper clears all shapes and rebuilds from scratch on every run. The sentinel for "already built" must be a post-condition of the build (a named shape like `BUILT_SENTINEL`), not a phrase from source content — source phrases change; named sentinels do not.

```python
def clear_and_bg(slide, bg_color):
    for sh in list(slide.Shapes):
        sh.Delete()
    bg = slide.Shapes.AddShape(1, 0, 0, slide.Parent.PageSetup.SlideWidth, slide.Parent.PageSetup.SlideHeight)
    bg.Fill.ForeColor.RGB = bg_color  # PowerPoint COM interprets this as BGR (0xBBGGRR); pass 0x0000FF for red
    bg.Name = "BUILT_SENTINEL"
```

---

## Harvest edits before overwriting a generated deck

**Hazard.** Regenerating a deck that users also edit manually discards their work silently. The regeneration script has no way to detect which slides were touched after the last build.

**Corrective.** Fingerprint the deck against a build manifest and stash changed slides before rebuilding; restore them after. These are naming conventions for a project-specific script — they are not pre-built skill tools.

- `harvest_edits.py manifest <deck>` — run after every build to record current slide fingerprints
- `harvest_edits.py harvest <deck> --store <dir>` — run before rebuilding to stash slides that differ from the manifest
- `harvest_edits.py restore <new_deck> --store <dir> --out <final>` — run after rebuilding to reapply stashed slides

---

## HasTextFrame is not "is this a text shape"

**Hazard.** `AutoShape` rectangles return `HasTextFrame == True` even when they contain no text. Filtering by `HasTextFrame` alone incorrectly includes blank rectangles in text-shape queries.

**Corrective.** Check for an empty text frame explicitly, or filter by shape name.

```python
# CORRECT filters — alternatives to the hazardous HasTextFrame-only check:

# Option A: distinguish a text frame with no content from one with content
if sh.HasTextFrame and not sh.TextFrame.HasText:
    pass  # frame exists but is empty — treat differently from a frame with text

# Option B: filter by shape name (most reliable for named shapes):
if sh.Name == "BodyText_Slide3":
    pass

# NEVER use: if not sh.HasTextFrame:  (misses empty-frame shapes)
```

Use shape names set during build (see **Idempotent build scripts**) as the reliable filter in read and edit passes.

---

## Move text and its backing shape together

**Hazard.** A `TextBox` and its backing `AutoShape` are independent COM objects. Repositioning one via `.Left` / `.Top` leaves the other behind, visually splitting the text from its background.

**Corrective.** Either group them before moving, or update both coordinates in the same operation.

```python
# Option A: group them
slide.Shapes.Range([backing.Name, text.Name]).Group()

# Option B: update both coordinates in the same patch
backing.Left = text.Left = new_left
backing.Top = text.Top = new_top
```

Option A is safer for repeated repositioning; Option B is simpler for a one-off adjustment.

---

## Force UTF-8 stdout in COM scripts

**Hazard.** Windows Python stdout defaults to `cp1252`. A `print()` call containing a non-ASCII character — a slide title with an accent or an em dash — crashes after COM has already saved the file, producing a misleading error at the end of the run.

**Corrective.** Add the following at the top of every COM script, before any `print()` calls.

```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
```

---

## Normalise paths before SaveCopyAs / SaveAs

**Hazard.** Passing a path with mixed `/` and `\` separators to `pres.SaveCopyAs()` or `pres.SaveAs()` raises "PowerPoint can't save the file" at runtime. The error gives no indication that the path is the cause.

**Corrective.** Normalise the path with `os.path.normpath(os.path.abspath(...))` before passing it to COM.

```python
import os
path = os.path.normpath(os.path.abspath(path))
pres.SaveCopyAs(path)
```

Apply the same normalisation before `SaveAs`.
