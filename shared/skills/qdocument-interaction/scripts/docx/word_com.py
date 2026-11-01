"""Tracked-change editing of an existing .docx through Microsoft Word (COM).

Windows only: needs Microsoft Word and pywin32. Word writes the revision markup
itself, which avoids the hand-written w:ins/w:del mistakes that make Word reject
a file. The helpers encode the object-model traps listed in docx.md,
"Editing through Word (COM)".

Usage (as a library, on a scratch copy of the user's file):

    from word_com import WordSession, H2
    with WordSession("in.docx", "out.docx", log=print) as ws:
        ws.replace("old wording", "new wording")
        h = ws.para("Some heading", level=1)
        ws.insert_before(h, ws.template(["A plain body paragraph"]), "New section", style=H2)
    # Saved to out.docx on a clean exit (REF fields refreshed); discarded on any error.

Then check the result with verify_docx.py and copy it over the user's file with
safe_replace.py.

Run the calling script with `python -u` inside a timeout, and log every step:
a Word call that hangs shows no error, only silence.
"""
import contextlib
import os
import time

# Built-in style ids (WdBuiltinStyle); locale-independent, unlike style names.
NORMAL, H1, H2, H3 = -1, -2, -3, -4
CAPTION = -35
TOC_STYLES = list(range(-20, -29, -1)) + [-36]  # TOC 1..9, Table of Figures

WD_REVISION_DELETE = 2
WD_FIELD_EMPTY = -1
WD_FIELD_REF = 3
WD_COLLAPSE_END = 0
WD_FORMAT_DOCX = 12
MAX_FIND_LOOPS = 300


def lock_file(path):
    """Return the Word owner file (~$...) next to path if it exists, else None.

    Word names it after the document with its first two characters replaced by
    '~$' (first character only for short names).
    """
    folder, name = os.path.split(os.path.abspath(path))
    for cut in (2, 1):
        cand = os.path.join(folder, "~$" + name[cut:])
        if os.path.exists(cand):
            return cand
    return None


class WordSession(object):
    """Open src in a hidden Word instance, edit with tracking on, save to out.

    The document is always closed and Word always quit, even on errors
    (including SystemExit and KeyboardInterrupt). Nothing is saved unless the
    `with` block finishes cleanly.
    """

    def __init__(self, src, out, track=True, update_refs=True, log=None):
        self.src = os.path.abspath(src)
        self.out = os.path.abspath(out)
        self.track = track
        self.update_refs = update_refs
        self._log = log or (lambda msg: None)
        self._t0 = time.time()
        self.word = None
        self.doc = None

    # -- lifecycle -----------------------------------------------------------
    def __enter__(self):
        import win32com.client  # imported here so the module loads without pywin32
        if lock_file(self.src):
            raise RuntimeError("%s is open in Word (lock file %s)" % (self.src, lock_file(self.src)))
        self.word = win32com.client.DispatchEx("Word.Application")
        self.word.Visible = False
        self.word.DisplayAlerts = 0
        try:
            self.doc = self.word.Documents.Open(self.src, False, False, False)
            self.doc.Bookmarks.ShowHidden = True
            self.doc.TrackRevisions = self.track
            self.log("opened %s; revisions=%d; body starts at %d"
                     % (os.path.basename(self.src), self.doc.Revisions.Count, self.body_start))
        except BaseException:
            self._close()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                if self.update_refs:
                    self.log("updated %d REF fields" % self.update_ref_fields())
                self.log("revisions=%d" % self.doc.Revisions.Count)
                self.doc.SaveAs2(self.out, WD_FORMAT_DOCX)
                self.log("saved %s" % self.out)
        finally:
            self._close()
        return False

    def _close(self):
        if self.doc is not None:
            try:
                self.doc.Close(0)
            except Exception:
                pass
            self.doc = None
        if self.word is not None:
            try:
                self.word.Quit()
            except Exception:
                pass
            self.word = None

    def log(self, msg):
        self._log("[%6.1fs] %s" % (time.time() - self._t0, msg))

    @property
    def body_start(self):
        """End of the last TOC / table of figures, recomputed on every call.

        A cached value goes stale after any edit before the TOC (title page,
        change record), and searches would then start inside the TOC fields.
        """
        ends = [t.Range.End for t in self.doc.TablesOfContents] + \
               [t.Range.End for t in self.doc.TablesOfFigures]
        return max(ends) if ends else 0

    @contextlib.contextmanager
    def untracked(self):
        """Temporarily turn tracking off (formatting of content you just inserted)."""
        prev = self.doc.TrackRevisions
        self.doc.TrackRevisions = False
        try:
            yield
        finally:
            self.doc.TrackRevisions = prev

    # -- finding -------------------------------------------------------------
    def in_deletion(self, r):
        """True if a tracked deletion really overlaps r.

        Range.Revisions can list every revision of the paragraph, so the
        overlap must be checked explicitly.
        """
        for rev in r.Revisions:
            if rev.Type == WD_REVISION_DELETE:
                rr = rev.Range
                if rr.Start < r.End and rr.End > r.Start:
                    return True
        return False

    def find(self, text, start=None, end=None, match_case=True, nth=1, guard=True, level=None):
        """Return the nth live match of text as a Range.

        Searches start after the TOC / table of figures unless start is given.
        guard=False accepts matches Word reports as deleted; use it for live text
        that an earlier tool interleaved with tracked deletions. level restricts
        matches to paragraphs of that outline level (1-9; 10 = body text).
        Word Find special characters apply: ^l manual line break, ^p paragraph.
        """
        s = self.body_start if start is None else start
        e = self.doc.Content.End if end is None else end
        hits = loops = 0
        while True:
            loops += 1
            if loops > MAX_FIND_LOOPS:
                raise RuntimeError("find loop stuck on %r at %d" % (text[:60], s))
            r = self.doc.Range(s, e)
            f = r.Find
            f.ClearFormatting()
            if not f.Execute(text, match_case, False, False, False, False, True, 0, False):
                raise LookupError("not found: %r (nth=%d)" % (text[:80], nth))
            if r.Start < s:  # Word can report a match before the search range near fields
                s = max(r.End, s + 1)
                continue
            ok = (not guard or not self.in_deletion(r)) and \
                 (level is None or self.para_at(r.Start).OutlineLevel == level)
            if ok:
                hits += 1
                if hits == nth:
                    return r
            s = max(r.End, s + 1)

    def para_at(self, pos):
        """Paragraph containing position pos (fresh range: avoids 'Object has been deleted')."""
        return self.doc.Range(pos, pos).Paragraphs(1)

    def para(self, text, **kw):
        """Paragraph containing the nth live match of text (see find)."""
        return self.para_at(self.find(text, **kw).Start)

    def template(self, candidates):
        """First paragraph matching one of candidates that has no bookmarks and no fields.

        Copying a paragraph that carries bookmarks would steal them.
        """
        for text in candidates:
            try:
                p = self.para(text)
            except LookupError:
                continue
            if p.Range.Bookmarks.Count == 0 and p.Range.Fields.Count == 0:
                return p
        raise LookupError("no clean template paragraph among %r" % (candidates,))

    # -- editing -------------------------------------------------------------
    def replace(self, old, new, **kw):
        r = self.find(old, **kw)
        r.Text = new
        self.log("replace %r -> %r" % (old[:50], new[:50]))
        return r

    def replace_all(self, old, new, **kw):
        n = 0
        start = kw.pop("start", None)
        while True:
            try:
                r = self.find(old, start=start, **kw)
            except LookupError:
                break
            r.Text = new
            start = r.End
            n += 1
        self.log("replace_all x%d %r -> %r" % (n, old[:50], new[:50]))
        return n

    def set_text(self, p, text):
        """Replace a paragraph's text, keeping its paragraph mark and formatting."""
        r = p.Range
        r.MoveEnd(1, -1)
        r.Text = text
        return r

    def delete_para(self, p, why=""):
        self.log("delete paragraph%s: %r" % (" (%s)" % why if why else "", p.Range.Text[:50]))
        p.Range.Delete()

    def delete_range(self, start, end, why=""):
        self.log("delete range %d-%d %s" % (start, end, why))
        self.doc.Range(start, end).Delete()

    def _heading_bookmarks(self, p):
        return [b.Name for b in p.Range.Bookmarks if b.Name.startswith(("_Ref", "_Toc"))]

    def insert_before(self, target_p, template_p, text, style=None):
        """Insert a copy of template_p with text right before target_p.

        Inserting at a paragraph start moves the bookmarks that start there onto
        the new text, so REF fields would point at it. Every _Ref/_Toc bookmark
        overlapping target_p is re-attached to target_p afterwards. A bookmark
        spanning several paragraphs (Word's cross-references to text, not to
        headings) is shrunk to target_p: avoid inserting in front of those.
        """
        names = self._heading_bookmarks(target_p)
        pos = target_p.Range.Start
        r = self.doc.Range(pos, pos)
        r.FormattedText = template_p.Range.FormattedText
        newp = self.para_at(pos)
        if style is not None:
            self._apply_style(newp, style)
        self.set_text(newp, text)
        after = newp.Next(1)
        for n in names:
            self.doc.Bookmarks.Add(n, after.Range)
        return self.para_at(pos)

    def insert_after(self, anchor_p, template_p, text, style=None):
        nxt = anchor_p.Next(1)
        if nxt is not None:
            return self.insert_before(nxt, template_p, text, style)
        # anchor_p is the last paragraph of the document: append a new one.
        # The anchor object absorbs the new paragraph, so locate it by position.
        pos = anchor_p.Range.End
        anchor_p.Range.InsertParagraphAfter()
        newp = self.para_at(pos)
        if style is None:
            newp.Style = template_p.Style
            newp.Format = template_p.Format
        else:
            self._apply_style(newp, style)
        self.set_text(newp, text)
        return newp

    def _apply_style(self, p, style):
        """Set a style and drop the template's direct paragraph formatting.

        Paragraph.Reset() removes direct numbering (a bullet copied from the
        template) but keeps the numbering the style itself links to. Do not use
        ListFormat.RemoveNumbers() here: on a heading it writes numId=0 and the
        heading loses its outline number, which shifts every REF after it.
        """
        p.Style = self.doc.Styles(style)
        p.Reset()

    def bookmark(self, name, p):
        """Add (or move) a bookmark on paragraph p. Use a _Ref prefix for hidden ones."""
        self.doc.Bookmarks.Add(name, p.Range)

    def add_ref(self, pos, bookmark, switches="\\n \\h"):
        """Insert a REF field (paragraph number, hyperlinked by default) at position pos."""
        return self.doc.Fields.Add(self.doc.Range(pos, pos), WD_FIELD_EMPTY,
                                   "REF %s %s" % (bookmark, switches), False)

    def update_ref_fields(self):
        """Update REF fields only; leave the TOC and table of figures to the author."""
        n = 0
        for f in self.doc.Fields:
            if f.Type == WD_FIELD_REF:
                f.Update()
                n += 1
        return n

    def add_table(self, before_p, rows, template_p, model=None):
        """Insert a table filled with rows (lists of str, first row = header) right before before_p.

        model (a Table, or its 1-based index in doc.Tables) is cloned with its borders, header
        shading, column widths and cell styles, then trimmed or extended to len(rows) rows; it
        must have as many columns as the rows. Prefer a model from the same document: the
        house look of a table often lives in direct formatting, not in a table style, and
        copying only the style of a "Table Normal" table gives a table with no borders.
        Without a model, Word's default table gets Normal cells (not before_p's heading style)
        and single borders.

        Two tables with no paragraph between them merge into one: never insert a table
        right after another one.
        """
        ncols = max(len(r) for r in rows)
        src = None
        if model is not None:
            src = self.doc.Tables(model) if isinstance(model, int) else model
            if src.Columns.Count != ncols:
                raise ValueError("model table has %d columns, rows have %d" % (src.Columns.Count, ncols))
        holder = self.insert_before(before_p, template_p, "table")
        if src is not None:
            pos = holder.Range.Start
            self.doc.Range(pos, pos).FormattedText = src.Range.FormattedText
            tbl = self.doc.Range(pos, pos).Tables(1)
            self.para_at(tbl.Range.End).Range.Delete()  # the holder paragraph, now after the table
            while tbl.Rows.Count > len(rows):
                tbl.Rows(tbl.Rows.Count).Delete()
            while tbl.Rows.Count < len(rows):
                tbl.Rows.Add()
        else:
            tbl = self.doc.Tables.Add(holder.Range, len(rows), ncols)
            with self.untracked():
                tbl.Range.Style = self.doc.Styles(NORMAL)
                tbl.Range.ListFormat.RemoveNumbers()
                tbl.Borders.Enable = True
        for i, row in enumerate(rows, 1):
            for j, cell in enumerate(row, 1):
                tbl.Cell(i, j).Range.Text = cell
        self.log("table %dx%d added%s" % (len(rows), ncols, " from model" if model is not None else ""))
        return tbl

    def insert_picture_after(self, anchor_p, image_path, template_p, max_width=None, align=1):
        """Insert an image in its own centred paragraph after anchor_p.

        Word may downsample large images; see docx_media.py to swap them later.
        """
        p = self.insert_after(anchor_p, template_p, "x")
        p.Format.Alignment = align
        r = p.Range
        r.MoveEnd(1, -1)
        r.Text = ""
        shp = self.doc.InlineShapes.AddPicture(os.path.abspath(image_path), False, True,
                                               self.doc.Range(r.Start, r.Start))
        shp.LockAspectRatio = True
        if max_width is None:
            ps = self.doc.Sections(1).PageSetup
            max_width = ps.PageWidth - ps.LeftMargin - ps.RightMargin
        if shp.Width > max_width:
            shp.Width = max_width
        self.log("picture %s (%dx%d pt)" % (os.path.basename(image_path), shp.Width, shp.Height))
        return self.para_at(r.Start)

    def replace_picture(self, p, image_path):
        """Replace the first inline picture of paragraph p, tracked, keeping its width.

        Comments anchored on the old picture end up inside the tracked deletion: Word
        then hides them and deletes them on Accept All. Run
        `verify_docx.py OUT --fix-comment-anchors FIXED` on the saved file whenever the
        paragraph carries comments; it re-anchors them on the new picture.
        """
        old = p.Range.InlineShapes(1)
        width, start, end = old.Width, old.Range.Start, old.Range.End
        comments = sum(1 for c in self.doc.Comments if c.Scope.Start <= start and c.Scope.End >= end)
        new = self.doc.InlineShapes.AddPicture(os.path.abspath(image_path), False, True, self.doc.Range(end, end))
        new.LockAspectRatio = True
        new.Width = width
        self.doc.Range(start, end).Delete()
        self.log("picture replaced by %s (%dx%d pt)%s" % (
            os.path.basename(image_path), new.Width, new.Height,
            "; %d comment(s) on it: run verify_docx --fix-comment-anchors" % comments if comments else ""))
        return comments

    # -- comments --------------------------------------------------------------
    def reply(self, comment_text, text):
        """Add a threaded reply (current Office user as author) under the top-level
        comment whose text contains comment_text.

        An "@Name" in text stays plain text and notifies nobody: run docx_mentions.py
        on the saved file to turn it into a real mention.
        """
        found = []
        for i in range(1, self.doc.Comments.Count + 1):
            c = self.doc.Comments(i)
            if c.Ancestor is None and comment_text in c.Range.Text:
                found.append(c)
        if len(found) != 1:
            raise LookupError("%d top-level comments contain %r" % (len(found), comment_text[:60]))
        found[0].Replies.Add(found[0].Scope, text)
        self.log("reply under %s's comment %r" % (found[0].Author, comment_text[:40]))

    # -- headers, footers, properties -----------------------------------------
    def header_footer_ranges(self):
        """(label, Range) for every header/footer and every text box inside them.

        Header/footer text boxes are not part of HeaderFooter.Range. Text boxes
        are de-duplicated by shape name; Word's automatic names can repeat
        across sections, so check the labels on multi-section documents.
        """
        out, seen = [], set()
        for si, s in enumerate(self.doc.Sections, 1):
            for kind, coll in (("header", s.Headers), ("footer", s.Footers)):
                for hi, hf in enumerate(coll, 1):
                    if not hf.Exists:
                        continue
                    out.append(("section %d %s %d" % (si, kind, hi), hf.Range))
                    for i in range(1, hf.Shapes.Count + 1):
                        shp = hf.Shapes(i)
                        try:
                            has_text = shp.TextFrame.HasText
                        except Exception:
                            has_text = False
                        if has_text and shp.Name not in seen:
                            seen.add(shp.Name)
                            out.append(("text box %s" % shp.Name, shp.TextFrame.TextRange))
        return out

    def replace_in_header_footer(self, old, new):
        n = 0
        for label, rng in self.header_footer_ranges():
            r = rng.Duplicate
            if r.Find.Execute(old, True, False, False, False, False, True, 0, False):
                r.Text = new
                n += 1
                self.log("%s: %r -> %r" % (label, old, new))
        return n

    def set_property(self, name, value):
        """Set a custom document property (not tracked by Word)."""
        props = self.doc.CustomDocumentProperties
        old = props(name).Value
        props(name).Value = value
        self.log("property %r: %r -> %r" % (name, old, value))

    def refresh_header_footer_fields(self):
        """Update fields in headers, footers and their text boxes, untracked."""
        n = 0
        with self.untracked():
            for label, rng in self.header_footer_ranges():
                for f in rng.Fields:
                    f.Update()
                    n += 1
        self.log("updated %d header/footer fields" % n)
        return n
