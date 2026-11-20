#!/usr/bin/env node
/*
 * Visual check for a /qexplain-change artifact built from assets/template.html.
 *
 * The static validator cannot see whether a D2 or Mermaid diagram drew, a tour step lit
 * anything, or the diff review behaves. This script opens the artifact in a real browser,
 * exercises every part the page has, prints one OK/BAD line per check, and saves
 * screenshots for you to look at. It checks only the parts that are present.
 *
 * Usage:
 *   node visual-check.js <artifact.html> [--out <screenshot-dir>] [--libs <dir>] [--chromium <path>]
 *
 *   --out       where screenshots go (default: a temp directory, printed at the end)
 *   --libs      offline mode: serve cdn.jsdelivr.net/npm/<pkg>@<ver>/<path> from
 *               <dir>/<pkg>-<ver>/package/<path> (the layout `npm pack` + untar produces)
 *   --chromium  browser executable, when Playwright's own download is not installed
 *
 * Needs Node and the `playwright` package (set PLAYWRIGHT_MODULE to its path if it is
 * not resolvable). Without them, run the same checklist by hand in a browser (Claude in
 * Chrome on a localhost copy works):
 *   1. The Info menu opens from every part present and shows the provenance and the page's path. Brief loads; every Mermaid diagram in
 *      it (a gantt, a fallback flowchart) has an SVG and no syntax error.
 *   2. Maps: each view shows a diagram (D2: the visible variant has an SVG; Mermaid: an
 *      SVG with no syntax error). Every tour step changes the caption and lights at least
 *      one element (data-hl on the view panel is above zero), and dims the rest.
 *   3. Sub-tabs (walkthrough, maps) switch panels. `#maps/<view>` and `#diff` hashes open
 *      the right part on load.
 *   4. D2 pages: the sketch toggle swaps the visible variant and persists under
 *      qexplain-change-sketch. The Show changes switch on the system view changes a highlighted
 *      shape's fill.
 *   5. The theme toggle re-themes the page, persists, and redraws Mermaid diagrams with
 *      the new theme.
 *   6. Diff review: sidebar lists every file; Mark reviewed collapses the card and
 *      counts; state survives a reload under qexplain-change-diff-<explanation id>; j and m work; a
 *      type filter narrows the list; added rows are coloured; clicking a cell wraps
 *      and unwraps it; tree view shows directories; the sidebar resizes, persists,
 *      and resets on double-click; both hash pills copy; there is no note box, and
 *      Copy feedback stands in the header; every file left out is named. A summary row opens its file here.
 *      A reviewed mark holds only while the file's patch is the same; the file list counts open
 *      comments. A removed line stands beside its replacement with the differing words marked; the
 *      text has syntax colours, and is plain without network. "f" searches the diff; Enter walks
 *      the matches. Hunks name their function; a file lists its changed functions and their callers.
 *      Hunks that are only a move, spacing or one word replaced carry a badge, and a button hides
 *      them. A changed picture shows before and after. The agent's notes stand under their lines,
 *      read-only.
 *   7. At 390px wide no part scrolls the page sideways. No page errors. In the written parts no text is cut
 *      off by its own box, no block runs out of its column, and no text lies under another element.
 *   8. Comments: selecting prose copies it with a location line and offers a Comment button; Enter
 *      saves, Shift+Enter adds a line, Escape keeps a box that holds text. A saved comment is
 *      highlighted and numbered, survives a reload, and reopens from its marker or its text. The
 *      pointer offers a button on a paragraph, a table cell, a table and a diff line; a file header
 *      and the tab that is showing have one too, and "/" comments on that tab. The panel lists the
 *      comments in page order; a click goes to the target; edit, resolve, reopen and delete work
 *      there, and a general comment is written there. Copy feedback copies the text the preview
 *      shows, and a save copies it too. The Annotate switch hides all of it and keeps the comments.
 *   9. Diagrams: the comment button on a diagram starts comment mode; a click comments on a part or
 *      on the whole diagram, Shift + drag boxes several parts and keeps a picture. "-", "+", "Fit"
 *      and Ctrl + wheel zoom; a click opens the full-window view, where comment mode works too.
 *      "Source" opens the source as text: a Mermaid edit redraws the diagram, a text that does not
 *      parse keeps the last drawing, a D2 edit is text only. In the source, the pointer offers a
 *      button on a line and a selection offers "Comment"; the commented text is highlighted and
 *      numbered. An edit that unseats a comment says so, and the diagram counts it as "not placed".
 *      The copied text lists the ids to keep.
 *
 * Exit codes: 0 every check OK, 1 at least one BAD, 2 could not run.
 */
const fs = require('fs'), os = require('os'), path = require('path');

const args = process.argv.slice(2);
const opt = name => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const file = args.find((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
if (!file || !fs.existsSync(file)) { console.error('usage: node visual-check.js <artifact.html> [--out dir] [--libs dir] [--chromium path]'); process.exit(2); }
let chromium;
try { ({ chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')); }
catch (e) { console.error('ERROR\tplaywright is not installed or not resolvable (set PLAYWRIGHT_MODULE)'); process.exit(2); }
const out = opt('--out') || fs.mkdtempSync(path.join(os.tmpdir(), 'qexplain-change-shots-'));
fs.mkdirSync(out, { recursive: true });
const libs = opt('--libs');
const url = require('url').pathToFileURL(path.resolve(file)).href;
let storeKey = '';   // 'qexplain-change-diff-' + the explanation id the build wrote into the page

let bad = 0;
const log = (ok, msg) => { if (!ok) bad++; console.log((ok ? 'OK\t' : 'BAD\t') + msg); };
const wait = ms => new Promise(r => setTimeout(r, ms));

async function routeLibs(target) {
  if (!libs) return;
  await target.route('https://cdn.jsdelivr.net/npm/**', r => {
    const m = r.request().url().match(/\/npm\/((?:@[^/]+\/)?[^@/]+)@([^/]+)\/(.*)$/);
    const f = m && path.join(libs, m[1].replace('/', '-') + '-' + m[2], 'package', m[3]);
    return f && fs.existsSync(f) ? r.fulfill({ path: f, contentType: 'application/javascript' }) : r.abort();
  });
}

(async () => {
  const browser = await chromium.launch(opt('--chromium') ? { executablePath: opt('--chromium') } : {});
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
  await routeLibs(ctx);
  const errors = [];
  const watch = p => { p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); }); };
  const page = await ctx.newPage(); watch(page);
  await page.goto(url); await wait(1500);
  await page.screenshot({ path: path.join(out, '1-brief.png') });

  const info = await page.evaluate(() => ({
    parts: PART_KEYS, hasD2: !!QX.hasD2,
    views: QX.views.map(v => ({ vid: v.vid, key: v.key, kind: v.kind, seq: v.seq, tour: v.tour || [] })),
    files: (QX.rawDiff.match(/^diff --git /gm) || []).length,
  }));
  const has = p => info.parts.includes(p);
  storeKey = await page.evaluate(() => STORE_KEY);
  log(await page.evaluate(() => typeof QX.id === 'string' && QX.id.length > 0 && STORE_KEY === 'qexplain-change-diff-' + QX.id), 'state is stored under the explanation id: ' + storeKey);
  // The page path, and the copy chain down to the manual box
  await page.evaluate(() => switchPart('brief')); await wait(200);
  await page.click('#info-toggle'); await wait(150);
  const shown = await page.evaluate(() => { const r = document.querySelector('#info-pop .pagepath'); return r && !r.hidden ? r.querySelector('.pp-text').textContent : ''; });
  log(shown.length > 0 && path.resolve(shown) === path.resolve(file), 'the page shows its own path: ' + shown);
  await page.click('#info-pop .pp-copy'); await wait(300);
  log(await page.evaluate(() => navigator.clipboard.readText().catch(() => '')) === shown, 'copy path puts the path on the clipboard');
  await page.evaluate(() => { window.__w = navigator.clipboard.writeText.bind(navigator.clipboard); navigator.clipboard.writeText = () => Promise.reject(new Error('refused')); });
  await page.evaluate(() => navigator.clipboard.readText().catch(() => '')).catch(() => {});
  await page.evaluate(() => window.__w('cleared'));
  await page.click('#info-pop .pp-copy'); await wait(300);
  log(await page.evaluate(() => navigator.clipboard.readText().catch(() => '')) === shown, 'with the clipboard API refusing, the older copy command still copies');
  await page.evaluate(() => { window.__x = document.execCommand; document.execCommand = () => false; });
  await page.click('#info-pop .pp-copy'); await wait(300);
  log(await page.evaluate(v => !document.getElementById('copybox').hidden && document.getElementById('copybox-text').value === v, shown), 'with both refusing, a box shows the text selected for a manual copy');
  await page.keyboard.press('Escape'); await wait(150);
  log(await page.evaluate(() => document.getElementById('copybox').hidden && !document.getElementById('info-pop').hidden), 'Escape closes that box and leaves the Info menu open');
  await page.mouse.click(300, 400); await wait(150);
  log(await page.evaluate(() => document.getElementById('info-pop').hidden), 'a click outside closes the Info menu');
  // Comments on selected prose: offer, box keys, marker, storage, reload, edit, delete
  const cmKey = await page.evaluate(() => CM_KEY);
  await page.evaluate(k => localStorage.removeItem(k), cmKey);
  await page.reload(); await wait(1200);
  // Scrolls first and selects afterwards: a scroll hides the Comment button, as it should for a reader.
  const selectProse = async () => {
    const find = `const w = document.createTreeWalker(document.querySelector('#part-brief .page'), NodeFilter.SHOW_TEXT);
      let t; while ((t = w.nextNode())) { if (t.nodeValue.trim().length > 60 && t.parentElement.closest('p')) break; }`;
    await page.evaluate(find + ` t.parentElement.scrollIntoView({ block: 'center' });`); await wait(200);
    return page.evaluate(find + ` const r = document.createRange(); r.setStart(t, 2); r.setEnd(t, 40);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); s.toString();`);
  };
  const quoted = await selectProse(); await wait(350);
  const selCopy = (await page.evaluate(() => navigator.clipboard.readText().catch(() => ''))).replace(/\r\n/g, '\n');
  log(selCopy.startsWith('// ' + await page.evaluate(() => cmPartName(PART_KEYS[0]))) && selCopy.split('\n').length === 2 && selCopy.endsWith('\n' + quoted), `selecting prose copies it with a line saying where it is from: ${selCopy.split('\n')[0]}`);
  log(await page.evaluate(() => { const b = document.getElementById('cm-add'); return !!b && !b.hidden; }), 'selecting prose offers a Comment button');
  await page.click('#cm-add'); await wait(150);
  log(await page.evaluate(() => document.querySelectorAll('#part-brief .cm-hl.cm-pending').length > 0 && document.activeElement === document.querySelector('.cm-card textarea')), 'the Comment button opens the box, focused, and keeps the chosen text marked');
  await page.keyboard.type('first line'); await page.keyboard.press('Shift+Enter'); await page.keyboard.type('second'); await page.keyboard.press('Control+Enter'); await page.keyboard.type('third');
  log(await page.evaluate(() => document.querySelector('.cm-card textarea').value) === 'first line\nsecond\nthird', 'Shift+Enter and Ctrl+Enter each add a line');
  await page.keyboard.press('Escape'); await wait(100);
  await page.mouse.click(5, 300); await wait(100);
  log(await page.evaluate(() => !!document.querySelector('.cm-card')), 'Escape and a click outside leave a box that holds text open');
  await page.focus('.cm-card textarea'); await page.keyboard.press('Enter'); await wait(250);
  const afterSave = await page.evaluate(k => ({ card: !!document.querySelector('.cm-card') || !!document.querySelector('.cm-pending'), marks: document.querySelectorAll('#part-brief .cm-mark').length,
    hl: document.querySelectorAll('#part-brief .cm-hl').length, stored: JSON.parse(localStorage.getItem(k) || '{"items":[]}').items }), cmKey);
  log(!afterSave.card && afterSave.marks === 1 && afterSave.hl >= 1 && afterSave.stored.length === 1 && afterSave.stored[0].quote === quoted
    && afterSave.stored[0].text === 'first line\nsecond\nthird', `Enter saves: one marker, ${afterSave.hl} highlight box(es), the quote and text stored`);
  log(await page.evaluate(() => document.querySelector('#part-brief .page p').innerHTML.indexOf('<mark') < 0 && !document.querySelector('#part-brief .page p .cm-hl')), 'the page text itself is not rewritten');
  await page.reload(); await wait(1200);
  log(await page.evaluate(() => document.querySelectorAll('#part-brief .cm-mark').length === 1 && CM.items[0]._state === 'anchored'), 'after a reload the comment is re-found by its quote and marked again');
  await page.click('#part-brief .cm-mark'); await wait(150);
  log(await page.evaluate(() => { const t = document.querySelector('.cm-card textarea'); return !!t && t.value === 'first line\nsecond\nthird' && !!document.querySelector('.cm-card .cm-del'); }), 'clicking the marker reopens the comment for editing');
  await page.keyboard.press('Escape'); await wait(100);
  log(await page.evaluate(() => !document.querySelector('.cm-card')), 'Escape closes an unchanged box');
  const hlAt = await page.evaluate(() => { const h = document.querySelector('#part-brief .cm-hl'); h.scrollIntoView({ block: 'center' });
    const b = h.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
  await page.mouse.move(hlAt.x, hlAt.y); await wait(100);
  log(await page.evaluate(() => document.documentElement.classList.contains('cm-over')), 'the pointer over highlighted text shows it can be clicked');
  await page.mouse.click(hlAt.x, hlAt.y); await wait(200);
  const opened = await page.evaluate(() => { const card = document.querySelector('.cm-card'); if (!card) return null;
    const hs = [...document.querySelectorAll('#part-brief .cm-hl.cm-active')].map(h => h.getBoundingClientRect()), k = card.getBoundingClientRect();
    return { active: hs.length, mark: !!document.querySelector('.cm-mark.cm-active'), clear: hs.every(h => k.top >= h.bottom - 1 || k.bottom <= h.top + 1) }; });
  log(!!opened && opened.active >= 1 && opened.mark, 'clicking highlighted text opens its comment and marks the text it concerns');
  log(!!opened && opened.clear, 'the reopened box does not cover the text it concerns');
  await page.keyboard.type(' more'); await page.mouse.click(hlAt.x, hlAt.y); await wait(150);
  log(await page.evaluate(() => { const t = document.querySelector('.cm-card textarea'); return !!t && t.value.endsWith(' more'); }), 'a click on a highlight does not replace a box that holds unsaved text');
  await page.evaluate(() => document.querySelector('.cm-card .cm-cancel').click()); await wait(100);
  log(await page.evaluate(() => !document.querySelector('.cm-hl.cm-active')), 'closing the box returns the highlight to its resting colour');
  await page.evaluate(() => { CM.items[0].quote = 'text that is not on the page'; cmResolve(); cmDraw(); });
  log(await page.evaluate(() => CM.items[0]._state === 'notfound' && document.querySelectorAll('.cm-mark').length === 0), 'a comment whose quote is gone is not placed anywhere');
  await page.reload(); await wait(1200);
  await page.click('#part-brief .cm-mark'); await wait(150); await page.click('.cm-card .cm-del'); await wait(200);
  log(await page.evaluate(k => document.querySelectorAll('.cm-mark').length === 0 && JSON.parse(localStorage.getItem(k)).items.length === 0, cmKey), 'Delete removes the comment and its marker');
  // A comment on the part that is showing ("/"), and a comment on the whole explanation (the top-bar button)
  await page.click('.part-btn.active .cm-tadd'); await wait(200);
  log(await page.evaluate(() => { const k = document.querySelector('.cm-card .cm-k'), b = document.querySelector('.part-btn.active');
    return !!k && k.textContent === 'The whole "' + b.dataset.label + '" part' && document.querySelectorAll('.cm-tadd').length === PART_KEYS.length
      && [...document.querySelectorAll('.part-btn:not(.active) .cm-tadd')].every(x => getComputedStyle(x).display === 'none'); }),
    'the tab that is showing carries a comment button for the whole part');
  await page.evaluate(() => document.querySelector('.cm-card .cm-cancel').click()); await wait(100);
  await page.keyboard.press('/'); await wait(200);
  log(await page.evaluate(() => { const k = document.querySelector('.cm-card .cm-k'), b = document.querySelector('.part-btn.active'), c = document.querySelector('.cm-card');
    return !!k && k.textContent === 'The whole "' + b.dataset.label + '" part' && b.dataset.label.length > 2 && b.classList.contains('cm-on')
      && c.getBoundingClientRect().top >= b.getBoundingClientRect().bottom - 3 && document.activeElement === c.querySelector('textarea'); }),
    'the "/" key opens a comment on the part that is showing, under its tab');
  await page.keyboard.type('part a/b'); await wait(50);
  log(await page.evaluate(() => document.querySelector('.cm-card textarea').value) === 'part a/b', 'a "/" typed in the box is text, and does not open another box');
  await page.keyboard.press('Enter'); await wait(250);
  await selectProse(); await wait(250); await page.click('#cm-add'); await page.keyboard.type('prose'); await page.keyboard.press('Enter'); await wait(250);
  log(await page.evaluate(() => { const pt = CM.items.find(c => c.kind === 'part'), pr = CM.items.find(c => c.kind === 'text'), m = document.querySelector('.part-btn.active .cm-tmark');
    return !!pt && pt.part === PART_KEYS[0] && !!pr && pt._n === 1 && pr._n === 2 && !!m && m.textContent === '1' && !document.querySelector('#part-brief .cm-layer .cm-hl.cm-blk'); }),
    'a part comment is numbered before the comments inside its part, with its marker on the tab');
  // The panel: every comment in page order, with a general comment, jump, edit, resolve, reopen and delete
  const pAct = (kind, a) => page.evaluate(([kind, a]) => { const c = CM.items.find(x => x.kind === kind), it = document.querySelector('#cm-panel .cm-it[data-cid="' + c.id + '"]');
    (a ? it.querySelector('[data-act="' + a + '"]') : it.querySelector('.cm-it-t')).click(); }, [kind, a]);
  await page.click('#cm-panel-btn'); await wait(300);
  log(await page.evaluate(() => { const p = document.getElementById('cm-panel'), nums = [...p.querySelectorAll('.cm-pl > .cm-it .cm-num')].map(n => n.textContent);
    const wide = window.innerWidth >= 1101, pg = document.querySelector('.part-panel.active .page').getBoundingClientRect(), tools = document.getElementById('top-tools').getBoundingClientRect();
    return !p.hidden && nums.join() === '1,2' && document.querySelector('#cm-panel-btn .cm-count').textContent === '2'
      && (!wide || (pg.right <= p.getBoundingClientRect().left + 1 && tools.right <= p.getBoundingClientRect().left)); }),
    'the Comments button opens the list of comments in page order, beside the page on a wide window');
  await page.click('#cm-panel [data-act="new"]'); await wait(150);
  await page.keyboard.type('general'); await page.keyboard.press('Enter'); await wait(250);
  log(await page.evaluate(() => { const g = CM.items.find(c => c.kind === 'page'), pt = CM.items.find(c => c.kind === 'part'), pr = CM.items.find(c => c.kind === 'text'), first = document.querySelector('#cm-panel .cm-pl > .cm-it');
    return !!g && g._n === 1 && pt._n === 2 && pr._n === 3 && first.dataset.cid === g.id && first.querySelector('.cm-it-w').textContent === 'The whole explanation'; }),
    'a general comment is written from the panel and is numbered before every part');
  await page.evaluate(() => { if (PART_KEYS.length > 1) switchPart(PART_KEYS[1], false); window.scrollTo(0, 0); }); await wait(300);
  await pAct('text'); await wait(500);
  log(await page.evaluate(() => { const h = document.querySelector('#part-brief .cm-hl.cm-flash'); if (!h) return false; const b = h.getBoundingClientRect();
    return document.querySelector('.part-btn.active').dataset.part === PART_KEYS[0] && b.top >= 0 && b.bottom <= window.innerHeight; }),
    'a click on a comment in the panel goes to its part, brings its text into view and flashes it');
  await pAct('text', 'edit'); await wait(150);
  await page.keyboard.press('Control+A'); await page.keyboard.type('prose, edited'); await page.keyboard.press('Shift+Enter'); await page.keyboard.type('second line'); await page.keyboard.press('Enter'); await wait(250);
  log(await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'text'); return c.text === 'prose, edited\nsecond line' && !document.querySelector('#cm-panel textarea')
    && document.querySelector('#cm-panel .cm-it[data-cid="' + c.id + '"] .cm-it-t').textContent === c.text; }), 'a comment is edited in the panel with the same keys as in the box');
  await pAct('text', 'resolve'); await wait(250);
  log(await page.evaluate(k => { const c = CM.items.find(x => x.kind === 'text'), res = document.querySelector('#cm-panel .cm-res');
    return c.state === 'resolved' && c._n === 0 && !document.querySelector('#part-brief .cm-hl') && !!res && !res.open && res.querySelectorAll('.cm-it').length === 1
      && [...document.querySelectorAll('#cm-panel .cm-pl > .cm-it .cm-num')].map(n => n.textContent).join() === '1,2' && document.querySelector('#cm-panel-btn .cm-count').textContent === '2'
      && JSON.parse(localStorage.getItem(k)).items.find(x => x.id === c.id).state === 'resolved'; }, cmKey),
    'a resolved comment leaves the page and the numbering and waits in a closed group');
  await pAct('text', 'reopen'); await wait(250);
  log(await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'text'); return c.state === 'open' && c._n === 3 && document.querySelectorAll('#part-brief .cm-hl').length >= 1; }), 'a resolved comment can be reopened');
  await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'text'); c.quote = 'text that is not on the page'; cmChanged(); }); await wait(150);
  log(await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'text'), it = document.querySelector('#cm-panel .cm-it[data-cid="' + c.id + '"]');
    return it.classList.contains('cm-it-lost') && it.querySelector('.cm-tag').textContent === 'not found' && c._n === 3; }), 'a comment that is not found stays in the panel, marked as not found');
  await pAct('text', 'del'); await wait(250);
  log(await page.evaluate(() => !CM.items.some(x => x.kind === 'text') && document.querySelectorAll('#cm-panel .cm-pl .cm-it').length === 2), 'a comment is deleted from the panel');
  await page.reload(); await wait(1200);
  await page.evaluate(() => { if (PART_KEYS.length > 1) switchPart(PART_KEYS[1], false); }); await wait(300);
  await page.click('.part-btn .cm-tmark'); await wait(400);
  log(await page.evaluate(() => { const t = document.querySelector('.cm-card textarea'); return !!t && t.value === 'part a/b' && document.querySelector('.part-btn.active').dataset.part === PART_KEYS[0]; }),
    'after a reload the marker on a tab goes to that part and reopens its comment');
  log(await page.evaluate(() => !document.getElementById('cm-panel').hidden && !!document.querySelector('#cm-panel .cm-it.cm-it-on')), 'the panel stays open across a reload and marks the comment whose box is open');
  await page.evaluate(() => { document.querySelector('.cm-card .cm-cancel').click(); CM.items = []; cmChanged(); cmPanel(false); });
  log(await page.evaluate(() => { const tools = document.getElementById('top-tools').getBoundingClientRect(), last = [...document.querySelectorAll('.part-btn')].pop().getBoundingClientRect();
    return getComputedStyle(document.getElementById('top-tools')).position !== 'fixed' || last.right <= tools.left; }), 'the part buttons stay clear of the tools with the comment button added');
  // Comments on a D2 diagram: a node, a connection, the whole diagram; one decision path for a click
  const d2dg = await page.evaluate(() => { const dg = document.querySelector('#part-brief .dg[data-kind="d2"]'); if (!dg) return null; dg.scrollIntoView({ block: 'center' }); return dg.id; });
  if (d2dg) {
    await wait(300);
    const partAt = (edge, nth) => page.evaluate(([id, edge, nth]) => { const dg = document.getElementById(id), all = cmDgParts(dg), ps = all.filter(p => p.edge === edge);
      const p = (edge ? ps : ps.filter(q => !all.some(o => o.id.startsWith(q.id + '.'))))[nth]; if (!p) return null;
      if (edge) { const pts = cmEdgePts(p.g), m = pts[Math.floor(pts.length / 2)]; return { id: p.id, x: m[0], y: m[1] }; }
      const b = p.g.getBoundingClientRect(); return { id: p.id, x: b.left + b.width / 2, y: b.top + b.height / 2 }; }, [d2dg, edge, nth]);
    const ringFits = () => page.evaluate(id => { const dg = document.getElementById(id), c = CM.items.find(x => x.kind === 'dg' && x.tk === 'node'), r = dg.querySelector('.cm-ring:not(.cm-whole):not(.cm-hot)');
      if (!c || !r) return false; const a = r.getBoundingClientRect(), g = cmDgGroup(dg, c._did, true).getBoundingClientRect();
      return Math.abs(a.left - (g.left - 4)) < 2 && Math.abs(a.top - (g.top - 4)) < 2 && Math.abs(a.width - (g.width + 8)) < 2; }, d2dg);
    const n0 = await partAt(false, 0);
    await page.mouse.click(n0.x, n0.y); await wait(300);
    log(await page.evaluate(() => !document.getElementById('dg-overlay').hidden && !document.querySelector('.cm-card')), 'outside comment mode a click on a diagram opens it full window, and no comment box');
    await page.evaluate(() => closeOverlay());
    await page.click('#' + d2dg + ' .cm-dgbtn'); await wait(200);
    await page.mouse.move(n0.x - 3, n0.y); await page.mouse.move(n0.x, n0.y); await wait(250);
    log(await page.evaluate(id => { const dg = document.getElementById(id); const tip = dg.querySelector('.cm-dgtip'); return dg.classList.contains('cm-mode') && dg.querySelectorAll('.cm-ring.cm-hot').length === 1 && getComputedStyle(tip).display !== 'none'
      && tip.textContent.startsWith('Click a part of the diagram') && tip.getBoundingClientRect().bottom <= cmDgBox(dg).getBoundingClientRect().top + 1; }, d2dg),
      'the diagram button turns on comment mode, and the pointer rings the part under it');
    await page.mouse.click(n0.x, n0.y); await wait(300);
    const nt = await page.evaluate(() => (document.querySelector('.cm-card .cm-k') || {}).textContent || '');
    log(await page.evaluate(() => document.getElementById('dg-overlay').hidden && !!document.querySelector('.cm-card')) && nt.startsWith('Node ') && nt.includes(n0.id) && nt.includes(' in diagram "'),
      `in comment mode a click on a node opens a comment on it, and not the full-window view: ${nt}`);
    await page.keyboard.type('node comment'); await page.keyboard.press('Enter'); await wait(300);
    log(await page.evaluate(([id, did]) => { const c = CM.items.find(x => x.kind === 'dg'), dg = document.getElementById(id);
      return !!c && c.tk === 'node' && c.did === did && c.dname === dg.dataset.name && c._state === 'anchored' && dg.querySelectorAll('.cm-dgl .cm-mark').length === 1; }, [d2dg, n0.id]) && await ringFits(),
      'a node comment stores the diagram name and the D2 id, and rings the node with a numbered marker');
    const e0 = await partAt(true, 0);
    if (e0) {
      await page.mouse.click(e0.x, e0.y); await wait(300);
      const et = await page.evaluate(() => (document.querySelector('.cm-card .cm-k') || {}).textContent || '');
      await page.keyboard.type('edge comment'); await page.keyboard.press('Enter'); await wait(300);
      log(et.startsWith('Connection ') && await page.evaluate(([id, did]) => { const c = CM.items.find(x => x.kind === 'dg' && x.tk === 'edge'), dg = document.getElementById(id);
        return !!c && c.did === did && !!cmDgGroup(dg, did, true) && cmDgGroup(dg, did, true).classList.contains('cm-eg') && dg.querySelectorAll('.cm-dgl .cm-mark').length === 2; }, [d2dg, e0.id]),
        `a click on a connection's line comments on that connection: ${et}`);
    }
    const bg = await page.evaluate(id => { const dg = document.getElementById(id), b = cmDgBox(dg).getBoundingClientRect();
      for (let y = b.top + 4; y < b.bottom - 4; y += 6) for (let x = b.left + 4; x < Math.min(b.right, window.innerWidth) - 40; x += 6) if (!cmDgHit(dg, x, y) && document.elementFromPoint(x, y) && document.elementFromPoint(x, y).closest('.dgv')) return { x, y };
      return null; }, d2dg);
    if (bg) {
      await page.mouse.click(bg.x, bg.y); await wait(300);
      log(await page.evaluate(id => (document.querySelector('.cm-card .cm-k') || {}).textContent === 'The whole diagram "' + document.getElementById(id).dataset.name + '"' && !!document.querySelector('#' + id + ' .cm-ring.cm-whole.cm-pending'), d2dg),
        'a click on the background comments on the whole diagram');
      await page.keyboard.press('Escape'); await wait(150);
    }
    if (await page.evaluate(() => !document.getElementById('sketch-toggle').hidden)) {
      await page.click('#sketch-toggle'); await wait(400); const fitsOther = await ringFits();
      await page.click('#sketch-toggle'); await wait(400);
      log(fitsOther && await ringFits(), 'the ring follows its node when the diagram switches between sketch and classic');
    }
    // Zoom of a diagram on the page: Ctrl + wheel and the buttons; the plain wheel still scrolls the page
    const zc = await page.evaluate(id => { const dg = document.getElementById(id); dg.scrollIntoView({ block: 'center' }); const b = cmDgBox(dg).getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; }, d2dg);
    await wait(300); const y0 = await page.evaluate(() => window.scrollY);
    await page.mouse.move(zc.x, zc.y); await page.keyboard.down('Control'); await page.mouse.wheel(0, -300); await page.keyboard.up('Control'); await wait(300);
    const zs = await page.evaluate(id => { const dg = document.getElementById(id); return { z: dg._zoom ? dg._zoom.z : 1, cls: dg.classList.contains('dg-zoomed'), fit: !dg.querySelector('.dg-zb[data-z="fit"]').hidden, y: window.scrollY }; }, d2dg);
    log(zs.z > 1 && zs.cls && zs.fit && zs.y === y0 && await ringFits(), `Ctrl + wheel zooms a diagram on the page without scrolling it, and the rings follow (${Math.round(zs.z * 100)}%)`);
    await page.click('#' + d2dg + ' .dg-zb[data-z="in"]'); await wait(300);
    const z2 = await page.evaluate(id => document.getElementById(id)._zoom.z, d2dg);
    await page.mouse.move(zc.x, zc.y); await page.mouse.down(); await page.mouse.move(zc.x - 70, zc.y - 10, { steps: 4 }); await page.mouse.up(); await wait(300);
    log(z2 > zs.z && await ringFits() && await page.evaluate(id => document.getElementById(id)._zoom.x < 0 && !ovOpen() && !document.querySelector('.cm-card'), d2dg),
      'the "+" button zooms further and a drag moves the zoomed diagram; the end of the drag opens nothing');
    await page.click('#' + d2dg + ' .dg-zb[data-z="fit"]'); await wait(300);
    await page.mouse.move(zc.x, zc.y); await page.mouse.wheel(0, 200); await wait(300);
    log(await page.evaluate(([id, y0]) => { const dg = document.getElementById(id); return dg._zoom.z === 1 && !dg.classList.contains('dg-zoomed') && dg.querySelector('.dg-zb[data-z="fit"]').hidden && window.scrollY > y0; }, [d2dg, y0]),
      'Fit puts the diagram back, and the plain wheel over a diagram scrolls the page');
    await page.evaluate(id => document.getElementById(id).scrollIntoView({ block: 'center' }), d2dg); await wait(300);
    Object.assign(n0, await partAt(false, 0));
    // The full-window view: zoom, move, rings that stay on their parts, and comment mode
    await page.keyboard.press('Escape'); await wait(200);
    await page.mouse.click(n0.x, n0.y); await wait(400);
    const ovFits = () => page.evaluate(() => { const body = ovBody(), c = CM.items.find(x => x.kind === 'dg' && x.tk === 'node'), r = body.querySelector('.cm-ring:not(.cm-whole):not(.cm-hot)'), g = cmDgGroup(body, c._did, true);
      if (!r || !g) return false; const a = r.getBoundingClientRect(), b = g.getBoundingClientRect(); return Math.abs(a.left - (b.left - 4)) < 2 && Math.abs(a.top - (b.top - 4)) < 2 && Math.abs(a.width - (b.width + 8)) < 2; });
    const ov0 = await page.evaluate(() => ({ open: ovOpen(), z: OV.z, x: OV.x, bar: !!document.querySelector('#dg-ov-body > .cm-dgbar'), marks: document.querySelectorAll('#dg-ov-body .cm-dgl .cm-mark').length }));
    log(ov0.open && ov0.bar && ov0.marks === 2 && await ovFits(), 'the full-window view shows the comments of its diagram, with each ring on its part');
    const mid = await page.evaluate(() => { const b = ovBody().getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
    await page.mouse.move(mid.x, mid.y); await page.mouse.wheel(0, -300); await wait(300);
    const z1 = await page.evaluate(() => OV.z), fit1 = await ovFits();
    await page.mouse.down(); await page.mouse.move(mid.x - 90, mid.y - 30, { steps: 4 }); await page.mouse.up(); await wait(300);
    log(z1 > ov0.z && fit1 && await ovFits() && await page.evaluate(x0 => OV.x !== x0 && ovOpen() && !document.querySelector('.cm-card'), ov0.x),
      `the wheel zooms and a drag moves the diagram; rings follow, and the end of a drag is not a click (zoom ${Math.round(ov0.z * 100)}% to ${Math.round(z1 * 100)}%)`);
    await page.click('#dg-ov-bar [data-z="fit"]'); await wait(300);
    log(await page.evaluate(z => Math.abs(OV.z - z) < 0.001, ov0.z) && await ovFits(), 'Fit brings the whole diagram back into the window');
    await page.click('#dg-ov-body .cm-dgbtn'); await wait(200);
    log(await page.evaluate(() => { const tip = document.querySelector('#dg-ov-body > .cm-dgtip'), r = tip.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return getComputedStyle(tip).display !== 'none' && r.height > 8 && tip.contains(top); }), "the comment-mode hint, with its list of parts, is visible in the full-window view");
    const on = await page.evaluate(() => { const body = ovBody(), used = CM.items.filter(c => c.kind === 'dg').map(c => c._did), all = cmDgParts(body);
      const p = all.find(q => !q.edge && !used.includes(q.id) && !all.some(o => o.id.startsWith(q.id + '.'))); const b = p.g.getBoundingClientRect(); return { id: p.id, x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
    await page.mouse.click(on.x, on.y); await wait(300);
    const ovCard = await page.evaluate(() => { const k = document.querySelector('.cm-card'); if (!k) return null; const b = k.getBoundingClientRect(), top = document.elementFromPoint(b.left + 20, b.top + 10);
      return { title: k.querySelector('.cm-k').textContent, onTop: !!top && !!top.closest('.cm-card') }; });
    await page.keyboard.type('from the full-window view'); await page.keyboard.press('Enter'); await wait(300);
    log(!!ovCard && ovCard.onTop && ovCard.title.startsWith('Node ') && ovCard.title.includes(on.id) && await page.evaluate(([id, did]) => { const c = CM.items.find(x => x.text === 'from the full-window view'), dg = document.getElementById(id);
      return !!c && c.did === did && c._dg === dg && c.part === dg.closest('.part-panel').id.slice(5) && c._state === 'anchored' && document.querySelectorAll('#dg-ov-body .cm-dgl .cm-mark').length === 3; }, [d2dg, on.id]),
      'comment mode works in the full-window view; the box shows above the view and the comment belongs to the diagram on the page');
    await page.keyboard.press('Escape'); await wait(150); const modeOff = await page.evaluate(() => ovOpen() && !cmDgMode);
    await page.keyboard.press('Escape'); await wait(200);
    log(modeOff && await page.evaluate(id => !ovOpen() && document.querySelectorAll('#' + id + ' .cm-dgl .cm-mark').length === 3, d2dg), 'Escape leaves comment mode first and closes the view next; the new comment is marked on the page');
    await page.click('#' + d2dg + ' .cm-dgbtn'); await wait(200);
    // Shift + drag boxes several nodes: they are named, and a picture of the area is kept
    const bx = await page.evaluate(id => { const dg = document.getElementById(id), all = cmDgParts(dg), leaf = all.filter(p => !p.edge && !all.some(o => o.id.startsWith(p.id + '.')));
      const rs = leaf.map(p => ({ id: p.id, b: p.g.getBoundingClientRect() })).sort((a, b) => a.b.left - b.b.left); let best = null;
      for (let i = 0; i + 1 < rs.length; i++) { const gap = rs[i + 1].b.left - rs[i].b.right; if (gap > 0 && (!best || gap < best.gap)) best = { gap, a: rs[i], b: rs[i + 1] }; }
      if (!best) return null; const A = best.a.b, B = best.b.b;
      return { ids: [best.a.id, best.b.id], l: Math.min(A.left, B.left) - 6, t: Math.min(A.top, B.top) - 6, r: Math.max(A.right, B.right) + 6, b: Math.max(A.bottom, B.bottom) + 6 }; }, d2dg);
    if (bx) {
      await page.keyboard.down('Shift'); await page.mouse.move(bx.l, bx.b); await page.mouse.down(); await page.mouse.move((bx.l + bx.r) / 2, (bx.t + bx.b) / 2, { steps: 3 }); await wait(150);
      const live = await page.evaluate(id => document.querySelectorAll('#' + id + ' .cm-ring.cm-boxed.cm-hot').length, d2dg);
      await page.mouse.move(bx.r, bx.t, { steps: 3 }); await page.mouse.up(); await page.keyboard.up('Shift'); await wait(900);
      const bt = await page.evaluate(() => { const k = document.querySelector('.cm-card'); if (!k) return null; const i = k.querySelector('.cm-pic img'); return { title: k.querySelector('.cm-k').textContent, pic: !!i && i.naturalWidth > 40 && i.naturalHeight > 20, ov: ovOpen() }; });
      log(live === 1 && !!bt && !bt.ov && /^\d+ nodes in diagram "/.test(bt.title) && bx.ids.every(i => bt.title.includes(i)) && bt.pic, `Shift + drag draws a box and opens a comment on the nodes it covers, with a picture: ${bt && bt.title}`);
      await page.keyboard.type('box comment'); await page.keyboard.press('Enter'); await wait(300);
      const bs = await page.evaluate(async ([id, ids]) => { const c = CM.items.find(x => x.tk === 'box'), dg = document.getElementById(id); if (!c) return null;
        const img = new Image(); await new Promise(r => { img.onload = r; img.onerror = r; img.src = c.pic || ''; });
        const cv = document.createElement('canvas'); cv.width = img.naturalWidth || 1; cv.height = img.naturalHeight || 1; const g = cv.getContext('2d'); g.drawImage(img, 0, 0);
        const px = g.getImageData(0, 0, cv.width, cv.height).data, seen = new Set(); for (let i = 0; i < px.length; i += 4 * 97) seen.add(px[i] + ',' + px[i + 1] + ',' + px[i + 2]);
        const f = cmFeedback(); let types = '';
        try { cmCopyPic(c.pic); await new Promise(r => setTimeout(r, 400)); types = (await navigator.clipboard.read()).map(i => i.types.join('+')).join(); } catch (e) { types = 'unreadable: ' + e.message; }
        return { ok: ids.every(i => c.dparts.some(p => p.did === i)) && c.dbox.length === 4 && c._state === 'anchored' && String(c.pic).indexOf('data:image/png') === 0, colours: seen.size, kb: Math.round(String(c.pic).length / 1024),
          rings: dg.querySelectorAll('.cm-ring.cm-boxed').length, fitted: (() => { const a = dg.querySelector('.cm-ring.cm-boxed').getBoundingClientRect(), u = cmUnion(c._dids.map(i => cmDgGroup(dg, i, true).getBoundingClientRect()), 9);
            return Math.abs(a.left - u.left) < 2 && Math.abs(a.top - u.top) < 2 && Math.abs(a.width - u.width) < 3 && Math.abs(a.height - u.height) < 3; })(), fb: f.includes(' nodes in diagram "') && f.includes('A picture of the boxed area is kept'), types }; }, [d2dg, bx.ids]);
      log(!!bs && bs.ok && bs.rings === 1 && bs.fitted && bs.colours > 3 && bs.fb, `a box comment keeps its nodes and a drawn picture, and its frame on the diagram fits those nodes (${bs && bs.colours} colours sampled, ${bs && bs.kb} KiB), and the copied text says so`);
      log(!!bs && /image\/png/.test(bs.types), `Copy picture puts the picture on the clipboard (${bs && bs.types})`);
      log(await page.evaluate(() => { const c = CM.items.find(x => x.tk === 'box'), keep = JSON.stringify(c.dparts); c.dparts[0].did = 'gone.id'; c.dparts[0].dlabel = 'no such label'; cmResolve();
        const one = c._state + ':' + c._lost + ':' + cmDgTitle(c).includes('(1 no longer in the diagram)'); c.dparts.forEach(p => { p.did = 'gone.' + p.did; p.dlabel = 'none'; }); cmResolve(); const none = c._state;
        c.dparts = JSON.parse(keep); cmResolve(); return one === 'moved:1:true' && none === 'notfound' && c._state === 'anchored'; }),
        'a box that lost one node says so and stays; a box that lost all its nodes is not found');
      await page.evaluate(() => { CM.items = CM.items.filter(x => x.tk !== 'box'); cmChanged(); });
    }
    const outside = await page.evaluate(id => { const b = document.getElementById(id).getBoundingClientRect(); return { x: b.left + 200, y: b.bottom + 40 }; }, d2dg);
    await page.mouse.click(outside.x, outside.y); await wait(200);
    const leftByClick = await page.evaluate(id => !document.getElementById(id).classList.contains('cm-mode') && !document.querySelector('.cm-card'), d2dg);
    await page.click('#' + d2dg + ' .cm-dgbtn'); await wait(200);
    await page.click('#cm-panel-btn'); await wait(250); await page.click('#cm-panel .cm-ph strong'); await wait(150);
    log(leftByClick && await page.evaluate(id => document.getElementById(id).classList.contains('cm-mode'), d2dg), 'a click outside the diagram leaves comment mode; a click in the panel does not');
    await page.evaluate(() => cmPanel(false)); await wait(250);
    await page.keyboard.press('Escape'); await wait(200);
    await page.mouse.click(n0.x, n0.y); await wait(300);
    log(await page.evaluate(id => !document.getElementById(id).classList.contains('cm-mode') && !document.getElementById('dg-overlay').hidden && !document.querySelector('.cm-card'), d2dg),
      'Escape leaves comment mode; a click on a commented node then opens the full-window view again');
    await page.evaluate(() => closeOverlay());
    const dgFb = await page.evaluate(() => cmFeedback());
    log(dgFb.includes(' > Node ') && dgFb.includes(n0.id) && dgFb.includes(' in diagram "') && (!e0 || dgFb.includes(' > Connection ')), 'the copied text names the diagram and the node or connection, with its id');
    await page.evaluate(() => { if (PART_KEYS.length > 1) switchPart(PART_KEYS[1], true); }); await wait(300);
    await page.reload(); await wait(1500);
    log(await page.evaluate(() => { const cs = CM.items.filter(x => x.kind === 'dg'); return document.querySelector('.part-btn.active').dataset.part !== PART_KEYS[0] && cs.length >= 1 && cs.every(c => c._state === 'anchored' && c._n > 0)
      && !cmFeedback().includes('not found'); }), 'after a reload on another part the diagram comments are still in place, before their diagram is shown');
    await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'dg' && x.tk === 'node'); c.did = 'gone.id'; cmResolve(); window.__st1 = c._state + ':' + c._did; c.dlabel = 'no such label'; cmResolve(); window.__st2 = c._state; });
    log(await page.evaluate(() => window.__st1.startsWith('moved:') && window.__st1 !== 'moved:gone.id' && window.__st2 === 'notfound'), 'a node whose id changed is taken up again by its label, and is not found when the label is gone too');
    await page.evaluate(() => { switchPart(PART_KEYS[0], true); CM.items = []; cmChanged(); }); await wait(300);
  }
  // Comments on the parts of Mermaid diagrams: a sequence message, then a flowchart node and connection
  const mmPart = (sel, what) => page.evaluate(([sel, what]) => { const dg = [...document.querySelectorAll(sel)].find(d => d.offsetParent !== null && cmDgParts(d).some(p => p.what === what)); if (!dg) return null;
    dg.scrollIntoView({ block: 'center' }); const p = cmDgParts(dg).find(x => x.what === what); let x, y;
    if (p.edge) { const pts = cmEdgePts(p.g), m = pts[Math.floor(pts.length / 2)]; x = m[0]; y = m[1]; } else { const b = p.g.getBoundingClientRect(); x = b.left + b.width / 2; y = b.top + b.height / 2; }
    return { dg: dg.id, id: p.id, label: p.label, x, y }; }, [sel, what]);
  const mmComment = async (sel, what, text) => {
    let p = await mmPart(sel, what); if (!p) return null; await wait(300); p = await mmPart(sel, what);
    if (await page.evaluate(id => !document.getElementById(id).classList.contains('cm-mode'), p.dg)) { await page.click('#' + p.dg + ' .cm-dgbtn'); await wait(200); }
    await page.mouse.click(p.x, p.y); await wait(300);
    p.title = await page.evaluate(() => (document.querySelector('.cm-card .cm-k') || {}).textContent || '');
    await page.keyboard.type(text); await page.keyboard.press('Enter'); await wait(300); return p;
  };
  if (await page.evaluate(() => PART_KEYS.includes('walkthrough') && !!document.querySelector('#part-walkthrough .dg[data-kind="mermaid"]'))) {
    await page.evaluate(() => switchPart('walkthrough', true)); await wait(1800);
    const msg = await mmComment('#part-walkthrough .dg[data-kind="mermaid"]', 'message', 'message comment');
    if (msg) {
      log(msg.title === 'Message "' + msg.label + '" in diagram "' + await page.evaluate(id => document.getElementById(id).dataset.name, msg.dg) + '"'
        && await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'dg'); return !!c && c.dwhat === 'message' && c._state === 'anchored' && !!c.dsrc && /^   Source line \d+: .+/m.test(cmFeedback()); }),
        `a sequence message is commented by its text, and the copied text gives its source line: ${msg.title}`);
      const fits = () => page.evaluate(id => { const dg = document.getElementById(id), c = CM.items.find(x => x.kind === 'dg'), r = dg.querySelector('.cm-ring:not(.cm-whole):not(.cm-hot)'), g = cmDgGroup(dg, c._did, true);
        if (!r || !g) return false; const a = r.getBoundingClientRect(), b = g.getBoundingClientRect(); return Math.abs(a.left - (b.left - 4)) < 2 && Math.abs(a.top - (b.top - 4)) < 2; }, msg.dg);
      const before = await fits();
      await page.keyboard.press('Escape'); await page.click('#theme-toggle'); await wait(2600);
      const after = await fits() && await page.evaluate(() => CM.items.find(x => x.kind === 'dg')._state === 'anchored');
      await page.click('#theme-toggle'); await wait(2600);
      log(before && after, 'the ring is drawn again on its message after the diagram is redrawn for another theme');
      await page.evaluate(() => switchPart(PART_KEYS[0], true)); await wait(300); await page.reload(); await wait(1500);
      log(await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'dg'); return document.querySelector('.part-btn.active').dataset.part === PART_KEYS[0] && c._state === 'anchored' && c._n === 1; }),
        'after a reload on another part a Mermaid comment is still in place');
      // The same comment while its diagram is not drawn: the drawing is emptied for the length of the check.
      log(await page.evaluate(() => { const c = CM.items.find(x => x.kind === 'dg'), mm = cmDgOf(c).querySelector('.mmd'), kept = mm.innerHTML, src = c.dsrc, lab = c.dlabel; mm.innerHTML = '';
        cmResolve(); const same = c._state; c.dsrc = 'changed'; cmResolve(); const inSrc = c._state; c.dlabel = 'text that is in no diagram'; cmResolve(); const gone = c._state;
        c.dsrc = src; c.dlabel = lab; mm.innerHTML = kept; cmResolve(); return same === 'anchored' && inSrc === 'anchored' && gone === 'notfound' && c._state === 'anchored'; }),
        'while its diagram is not drawn, a Mermaid comment is checked against the source: unchanged source, then the part in a changed source, else not found');
    }
    await page.evaluate(() => { CM.items = []; cmChanged(); });
  }
  if (await page.evaluate(() => PART_KEYS.includes('maps'))) {
    await page.evaluate(() => switchPart('maps', true)); await wait(1500);
    for (const v of await page.evaluate(() => [...document.querySelectorAll('#part-maps .map-btn')].map(b => b.dataset.view))) {
      await page.evaluate(v => switchMap(v, false), v); await wait(1500);
      if (await page.evaluate(() => [...document.querySelectorAll('#part-maps .dg[data-kind="mermaid"]')].some(d => d.offsetParent !== null && cmDgParts(d).some(p => p.edge)))) {
        const nd = await mmComment('#part-maps .dg[data-kind="mermaid"]', 'node', 'flow node'), ed = await mmComment('#part-maps .dg[data-kind="mermaid"]', 'connection', 'flow edge');
        log(!!nd && nd.title.startsWith('Node "' + nd.label + '" (' + nd.id + ') in diagram "') && !!ed && ed.title.startsWith('Connection "') && ed.title.includes(' -> ')
          && await page.evaluate(() => { const n = CM.items.find(x => x.dwhat === 'node'), e = CM.items.find(x => x.dwhat === 'connection'), f = cmFeedback();
            return !!n && !!e && n._state === 'anchored' && e._state === 'anchored' && Array.isArray(e.dends) && (f.match(/^   Source line \d+: /mg) || []).length === 2 && !!e._dg.querySelector('.mmd .cm-eg'); }),
          `a flowchart node and a connection are commented by their Mermaid ids: ${nd && nd.title} / ${ed && ed.title}`);
        await page.keyboard.press('Escape');
        break;
      }
    }
    await page.evaluate(() => { CM.items = []; cmChanged(); switchPart(PART_KEYS[0], true); }); await wait(400);
  }
  // The source of a diagram as editable text: Mermaid redraws, a bad text keeps the last good drawing, D2 is text only
  const typeSrc = (id, text) => page.evaluate(([id, text]) => { const ta = document.querySelector('#' + id + ' > .dg-src textarea'); ta.value = text; ta.dispatchEvent(new Event('input', { bubbles: true })); }, [id, text]);
  // Points at a line of the source as a reader would, then presses the comment button that appears beside it.
  const srcAdd = async (id, ln) => {
    const pt = await page.evaluate(([id, ln]) => { const box = document.querySelector('#' + id + ' > .dg-src'), g = dgSrcGeo(box), ta = g.ta; ta.scrollTop = Math.max(0, (ln - 3) * g.lh);
      const r = ta.getBoundingClientRect(); return [r.left + 80, r.top + g.py + (ln - 0.5) * g.lh - ta.scrollTop]; }, [id, ln]);
    await page.mouse.move(pt[0] - 5, pt[1]); await page.mouse.move(pt[0], pt[1]); await wait(120);
    await page.click('#' + id + ' .dg-src-add'); await wait(300);
  };
  const srcState = id => page.evaluate(id => { const dg = document.getElementById(id), box = dg.querySelector(':scope > .dg-src'), ed = CM.edits[dg.dataset.name];
    return { open: !!box, text: box ? box.querySelector('textarea').value : null, st: box ? box.querySelector('.dg-src-st').textContent : '', ask: box ? !box.querySelector('.dg-src-ask').hidden : false,
      ed: ed ? { bad: ed.bad, kind: ed.kind } : null, marked: dg.querySelector('.dg-srcb').classList.contains('dg-edited'), drawn: (dg.querySelector('.mmd svg') || { textContent: '' }).textContent }; }, id);
  if (await page.evaluate(() => PART_KEYS.includes('walkthrough') && !!document.querySelector('#part-walkthrough .dg[data-kind="mermaid"]'))) {
    await page.evaluate(() => switchPart('walkthrough', true)); await wait(1800);
    const sq = await page.evaluate(() => { const dg = document.querySelector('#part-walkthrough .dg[data-kind="mermaid"]'); dg.scrollIntoView({ block: 'center' }); const src = QX.mermaid0[cmDgInfo(dg).mid];
      const m = /:\s*(.+)$/m.exec(src); return { id: dg.id, name: dg.dataset.name, src, msg: m ? m[1].trim() : '' }; });
    if (sq.msg) {
      await wait(300); await page.click('#' + sq.id + ' .dg-srcb'); await wait(300);
      let s = await srcState(sq.id);
      log(s.open && s.text === sq.src && s.st === 'Not edited.' && !s.marked, 'the Source button shows the diagram\'s source as text, unedited');
      const edited = sq.src.replace(sq.msg, sq.msg + ' EDITED');
      await typeSrc(sq.id, edited); await wait(2200); s = await srcState(sq.id);
      log(!!s.ed && s.ed.bad === '' && s.marked && s.drawn.includes(sq.msg + ' EDITED') && /redrawn/.test(s.st), 'editing a Mermaid source redraws the diagram and marks it as edited');
      await typeSrc(sq.id, 'this is not a diagram at all'); await wait(2200); s = await srcState(sq.id);   // Mermaid forgives much inside a diagram; this has no diagram type
      const badFb = await page.evaluate(() => cmFeedback());
      log(!!s.ed && s.ed.bad.length > 3 && s.drawn.includes(sq.msg + ' EDITED') && /^Does not parse: /.test(s.st) && badFb.includes('does not parse as Mermaid'),
        `a source that does not parse is reported and the diagram keeps its last good drawing: ${s.st.slice(0, 90)}`);
      await typeSrc(sq.id, edited); await wait(2200);
      const fb = await page.evaluate(() => cmFeedback());
      log(fb.includes('1. Diagram "' + sq.name + '" (Mermaid): the reader edited its source. Replace the source with the text below.') && edited.trim().split('\n').every(l => fb.includes('   | ' + l)) && fb.trimEnd().endsWith(await page.evaluate(() => CM_ASK)),
        'an edited source goes into the copied feedback as a numbered item, line by line');
      await page.reload(); await wait(2200);
      log(await page.evaluate(([id, t]) => (document.querySelector('#' + id + ' .mmd svg') || { textContent: '' }).textContent.includes(t) && document.getElementById(id).querySelector('.dg-srcb').classList.contains('dg-edited'), [sq.id, sq.msg + ' EDITED']),
        'after a reload the edit is still applied and the diagram is drawn from it');
      await page.evaluate(n => { CM.edits[n].base = 'an older source'; cmSave(); }, sq.name); await page.reload(); await wait(2200);
      s = await srcState(sq.id);
      const staleFb = await page.evaluate(() => cmFeedback());
      log(s.open && s.ask && !s.drawn.includes('EDITED') && s.text === edited && /not applied/.test(s.st) && staleFb.includes('source changed after this edit was written'),
        'an edit written against an older source is not applied: its diagram shows the new source and asks to keep or discard');
      await page.click('#' + sq.id + ' .dg-src [data-s="keep"]'); await wait(2200); s = await srcState(sq.id);
      const kept = !s.ask && s.drawn.includes('EDITED');
      await page.click('#' + sq.id + ' .dg-src-h [data-s="reset"]'); await wait(2200); s = await srcState(sq.id);
      log(kept && !s.ed && !s.marked && s.text === sq.src && !s.drawn.includes('EDITED') && await page.evaluate(() => cmFeedback() === ''), '"Keep my edit" applies it; Reset puts the original back and removes the edit');
      // A reworked diagram: a comment follows its part by its place, is never moved to a neighbour, and stays visible when it is lost
      const addDg = (pid, text) => page.evaluate(([id, pid, text]) => { const dg = document.getElementById(id), part = cmDgParts(dg).find(x => x.id === pid); if (!part) return false; const c = cmDgSel(dg, part);
        CM.items.push({ id: 'vc' + Date.now().toString(36) + CM.items.length, text, label: '', t: Date.now(), state: 'open', kind: 'dg', part: c.part, dname: c.dname, dn: c.dn, tk: c.tk, did: c.did, dlabel: c.dlabel, dwhat: c.dwhat, dends: c.dends, dsrc: c.dsrc, dpos: c.dpos, quote: '' });
        cmChanged(); return true; }, [sq.id, pid, text]);
      const dgC = text => page.evaluate(text => { const c = CM.items.find(x => x.text === text); return c ? { st: c._state, did: c._did || '', where: c._pieces ? cmWhere(c, true) : '' } : { st: 'none', did: '', where: '' }; }, text);
      const dropC = () => page.evaluate(() => { CM.items = CM.items.filter(x => !/^vc /.test(x.text)); cmChanged(); });
      const chipOf = () => page.evaluate(id => { const b = document.querySelector('#' + id + ' .cm-dglost'); return b && !b.hidden ? b.textContent : ''; }, sq.id);
      const lines = sq.src.split('\n'), li = lines.findIndex(l => l.includes(sq.msg) && /-[->)x]/.test(l));
      const withLine = f => lines.map((l, i) => i === li ? f(l) : l).filter(l => l !== null).join('\n');
      if (li >= 0 && await addDg('message:' + sq.msg, 'vc follows')) {
        await typeSrc(sq.id, withLine(l => l.replace(sq.msg, sq.msg + ' REWORDED'))); await wait(2200);
        let c = await dgC('vc follows'); s = await srcState(sq.id);
        log(c.st === 'moved' && c.where.includes('"' + sq.msg + ' REWORDED" (was "' + sq.msg + '")') && !/no longer/.test(s.st) && await chipOf() === '',
          `a sequence message reworded in the source keeps its comment, named as it reads now with its old wording: ${c.st} ${c.where.slice(0, 110)}`);
        await typeSrc(sq.id, withLine(() => null)); await wait(2200); c = await dgC('vc follows'); s = await srcState(sq.id);
        log(!!s.ed && s.ed.bad === '' && c.st === 'notfound' && /With this edit, 1 comment on the diagram no longer finds its part\. Reset brings it back\./.test(s.st) && await chipOf() === '1 not found',
          `an edit that removes a commented part says so in the editor, and the diagram counts the comment as not placed: ${s.st.slice(0, 120)}`);
        await page.click('#' + sq.id + ' .cm-dglost'); await wait(300);
        log(await page.evaluate(() => cmPanelOpen() && document.querySelectorAll('#cm-panel .cm-it.cm-it-lost.cm-it-flash').length === 1), 'a click on "not placed" opens the panel on the comment that lost its part');
        await page.evaluate(() => cmPanel(false)); await dropC();
        await typeSrc(sq.id, withLine(l => l + '\n' + l.replace(sq.msg, sq.msg + ' TWIN'))); await wait(2200);
        const twinOk = await addDg('message:' + sq.msg, 'vc sibling');
        await typeSrc(sq.id, withLine(l => l.replace(sq.msg, sq.msg + ' TWIN'))); await wait(2200);       // the commented message is gone, the one beside it stays
        const gone = await dgC('vc sibling');
        await typeSrc(sq.id, withLine(l => l.replace(sq.msg, sq.msg + ' REWORDED') + '\n' + l.replace(sq.msg, sq.msg + ' TWIN'))); await wait(2200);
        const back = await dgC('vc sibling');
        log(twinOk && gone.st === 'notfound' && back.st === 'moved' && back.did === 'message:' + sq.msg + ' REWORDED',
          `a deleted message is not taken for the one that stood beside it; reworded among unchanged neighbours it is found again (${gone.st}, ${back.st} ${back.did})`);
        await dropC();
        await typeSrc(sq.id, 'flowchart LR\n  a[Alpha] --> b[Beta]\n  a --> c[Gamma]'); await wait(2200);
        const nodeOk = await addDg('b', 'vc node');
        await typeSrc(sq.id, 'flowchart LR\n  a[Alpha] --> b2[Beta two]\n  a --> c[Gamma]'); await wait(2200);
        const n1 = await dgC('vc node'), keep = await page.evaluate(() => cmFeedback());
        await typeSrc(sq.id, 'flowchart LR\n  a[Alpha] --> c[Gamma]'); await wait(2200);
        const n2 = await dgC('vc node');
        log(nodeOk && n1.st === 'moved' && n1.did === 'b2' && n2.st === 'notfound',
          `a flowchart node whose id and label both changed is found by its neighbours; a deleted node is not taken for a neighbour that was already there (${n1.st} ${n1.did}, ${n2.st})`);
        log(keep.includes('keep the ids below unless a comment asks you to remove the part:\n- Diagram "' + sq.name + '" (Mermaid): b2\n') && keep.trimEnd().endsWith(await page.evaluate(() => CM_ASK)),
          'the copied text lists the ids a rework should keep, before the closing request');
        await dropC();
        await page.click('#' + sq.id + ' .dg-src-h [data-s="reset"]'); await wait(2200);
        log(await page.evaluate(() => cmFeedback() === '') && await chipOf() === '', 'after Reset and with the comments removed, nothing is left to copy and nothing is counted as not placed');
        // A comment on a message and one on its source line: deleting the line loses both, Reset brings both back
        const both = await addDg('message:' + sq.msg, 'vc both part');
        await srcAdd(sq.id, li + 1);
        await page.keyboard.type('vc both line'); await page.keyboard.press('Enter'); await wait(400);
        await typeSrc(sq.id, withLine(() => null)); await wait(2200); s = await srcState(sq.id);
        const lostChip = await chipOf();
        await page.click('#' + sq.id + ' .dg-src-h [data-s="reset"]'); await wait(2200);
        const again = await page.evaluate(id => { const dg = document.getElementById(id), cs = CM.items.filter(x => /^vc both/.test(x.text));
          return { n: cs.length, ok: cs.every(x => x._state === 'anchored'), rows: dg.querySelectorAll('.dg-src-ln').length, lines: dg.querySelector(':scope > .dg-src textarea').value.split('\n').length, marks: dg.querySelectorAll('.dg-src-g .cm-mark').length }; }, sq.id);
        log(both && /With this edit, 2 comments on the diagram and its source no longer find their place\. Reset brings them back\./.test(s.st) && lostChip === '2 not found'
          && again.n === 2 && again.ok && again.rows === again.lines && again.marks === 1 && await chipOf() === '',
          `deleting a line that carries a comment on its message and one on the line itself loses both and says so; Reset brings both back and the line numbers match the text again (${again.rows} numbers, ${again.lines} lines): ${s.st.slice(0, 110)}`);
        await dropC();
      }
      await page.click('#' + sq.id + ' .dg-src [data-s="close"]'); await wait(200);
    }
    await page.evaluate(() => switchPart(PART_KEYS[0], true)); await wait(400);
  }
  if (d2dg) {
    await page.evaluate(id => document.getElementById(id).scrollIntoView({ block: 'center' }), d2dg); await wait(300);
    await page.click('#' + d2dg + ' .dg-srcb'); await wait(300);
    const d2src = await page.evaluate(id => QX.dg[document.getElementById(id).dataset.name].src, d2dg);
    let s = await srcState(d2dg); const d2open = s.open && s.text === d2src;
    await typeSrc(d2dg, d2src + '\nextra: Added by the reader\n'); await wait(900); s = await srcState(d2dg);
    await page.click('#cm-panel-btn'); await wait(300);
    const d2fb = await page.evaluate(() => cmFeedback());
    log(d2open && !!s.ed && s.ed.kind === 'd2' && s.marked && /not redrawn/.test(s.st) && d2fb.includes('(D2): the reader edited its source. Replace the source with the text below and regenerate the diagram.') && d2fb.includes('   | extra: Added by the reader')
      && await page.evaluate(() => document.querySelector('#cm-panel-btn .cm-count').textContent === '1' && document.querySelectorAll('#cm-panel .cm-it[data-src]').length === 1),
      'a D2 source is edited as text with no redraw; the copied text asks for the diagram to be regenerated, and the panel lists the edit');
    await page.evaluate(() => document.querySelector('#cm-panel .cm-it[data-src] [data-act="srcdrop"]').click()); await wait(300); s = await srcState(d2dg);
    log(!s.ed && !s.marked && s.text === d2src && await page.evaluate(() => document.querySelectorAll('#cm-panel .cm-it[data-src]').length === 0 && cmFeedback() === ''), 'Discard in the panel removes the edit and puts the original text back');
    // Three rules that must never guess or misfire: a quote that stands twice, a diff line that stands twice, and Enter
    // pressed while an input method is still composing a character
    {
      const ng = await page.evaluate(() => {
        const part = PART_KEYS.find(k => k !== 'diff'), ix = cmIndex(document.querySelector('#part-' + part + ' .page')), text = ix.text;
        // a word of the page that stands at least twice, with different text around its two places
        let word = '', at = [];
        for (const w of (text.match(/[A-Za-z]{6,}/g) || [])) { const a = text.indexOf(w), b = text.indexOf(w, a + 1); if (b > a && text.slice(a - 32, a) !== text.slice(b - 32, b)) { word = w; at = [a, b]; break; } }
        const mk = (id, extra) => Object.assign({ id, kind: 'text', part, section: '', quote: word, text: 'vc ' + id, label: '', t: Date.now(), state: 'open' }, extra);
        if (word) CM.items.push(mk('vcng1', { prefix: 'no such text before it', suffix: 'no such text after it' }),
          mk('vcng2', { prefix: text.slice(Math.max(0, at[1] - 32), at[1]), suffix: text.slice(at[1] + word.length, at[1] + word.length + 32) }));
        // a diff line whose text stands at least twice on its side, addressed by a line number that no longer fits
        let twice = null;
        if (PART_KEYS.includes('diff')) for (const p of ordered) { const rows = cmDiffSide(p, 'new'), seen = {}; rows.forEach(r => { (seen[r.c] = seen[r.c] || []).push(r.ln); });
          const k = Object.keys(seen).find(c => seen[c].length > 1), one = Object.keys(seen).find(c => seen[c].length === 1 && c.trim());
          if (k !== undefined && one !== undefined) { twice = [p, k, one]; break; } }
        if (twice) CM.items.push({ id: 'vcng3', kind: 'line', part: 'diff', path: twice[0], side: 'new', ln: 987654, ln2: 987654, lines: [twice[1]], quote: '', text: 'vc twice', label: '', t: Date.now(), state: 'open' },
          { id: 'vcng4', kind: 'line', part: 'diff', path: twice[0], side: 'new', ln: 987654, ln2: 987654, lines: [twice[2]], quote: '', text: 'vc once', label: '', t: Date.now(), state: 'open' });
        cmChanged();
        const st = id => { const c = CM.items.find(x => x.id === id); return c ? c._state + (c._pieces ? '@' + Math.round(c._at) : '') : 'none'; };
        const r = { word, second: at[1], q1: st('vcng1'), q2: st('vcng2'), twice: !!twice, d3: st('vcng3'), d4: (CM.items.find(x => x.id === 'vcng4') || {})._state };
        CM.items = CM.items.filter(x => !/^vcng/.test(x.id)); cmChanged();
        return r;
      });
      if (ng.word) log(ng.q1 === 'notfound' && ng.q2.split('@')[1] === String(ng.second), `a quote that stands more than once is placed only where the text around it agrees, and nowhere when none does ("${ng.word}": ${ng.q1}, ${ng.q2.split('@')[0]})`);
      if (ng.twice) log(ng.d3 === 'notfound' && ng.d4 === 'moved', `a diff comment whose line number no longer fits is placed by its text only when that text stands once (stands twice: ${ng.d3}; stands once: ${ng.d4})`);
      await page.evaluate(() => cmPanel(true)); await wait(200);
      await page.click('#cm-panel [data-act="new"]'); await wait(200);
      await page.keyboard.type('vc composing');
      const mid = await page.evaluate(() => { const ta = document.querySelector('#cm-panel .cm-it-ta'); ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }));
        return { open: !!document.querySelector('#cm-panel .cm-it-ta'), saved: CM.items.some(x => x.text === 'vc composing') }; });
      await page.keyboard.press('Enter'); await wait(300);
      const end = await page.evaluate(() => { const saved = CM.items.some(x => x.text === 'vc composing'); CM.items = CM.items.filter(x => x.text !== 'vc composing'); cmChanged(); cmPanel(false); return saved; });
      log(mid.open && !mid.saved && end, 'Enter pressed while an input method is composing a character does not save the comment; the next Enter does');
      // The keyboard alone: the list of comments, a comment box and the full-window view take the focus and give it back; Escape closes a box from any of its controls
      const kb = {};
      await page.evaluate(() => { CM.items.push({ id: 'vckb', kind: 'page', part: 'page', quote: '', text: 'vc keyboard', label: '', t: Date.now(), state: 'open' }); cmChanged(); document.getElementById('cm-panel-btn').focus(); });
      await page.keyboard.press('Enter'); await wait(250);
      kb.panelIn = await page.evaluate(() => cmPanelOpen() && !!document.activeElement.closest('#cm-panel'));
      kb.go = await page.evaluate(() => { const b = document.querySelector('#cm-panel .cm-it[data-cid="vckb"] button.cm-it-w'); if (!b || b.tabIndex !== 0) return false;
        let n = 0; const real = cmJump; cmJump = c => { if (c && c.id === 'vckb') n++; }; b.click(); cmJump = real; return n === 1; });      // one jump: the button, not the button and its row
      kb.hint = await page.evaluate(() => { cmPanelAct('edit', 'vckb'); return /Enter saves/.test((document.querySelector('#cm-panel .cm-it .cm-hint') || { textContent: '' }).textContent); });
      await page.evaluate(() => { cmPanelAct('cancel', 'vckb'); document.querySelector('#cm-panel [data-act="close"]').focus(); });
      await page.keyboard.press('Enter'); await wait(250);
      kb.panelOut = await page.evaluate(() => !cmPanelOpen() && document.activeElement.id === 'cm-panel-btn');
      const dgk = await page.evaluate(() => { const dg = [...document.querySelectorAll('.part-panel.active .dg')].find(d => d.offsetParent !== null && cmDgParts(d).length); if (!dg) return null; dg.scrollIntoView({ block: 'center' }); dg.querySelector('.cm-dgbtn').focus(); return dg.id; });
      if (dgk) {
        await page.keyboard.press('Tab'); await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Enter'); await wait(250);      // the Tab keys make the focus one the browser treats as keyboard focus
        kb.pick = await page.evaluate(id => { const s = document.querySelector('#' + id + ' .cm-dgpick'); return !!s && document.activeElement === s && s.options.length > 1; }, dgk);
        await page.keyboard.press('ArrowDown'); await page.keyboard.press('Tab'); await page.keyboard.press('Enter'); await wait(300);
        kb.box = await page.evaluate(() => { const c = document.querySelector('.cm-card'); return !!c && /^(Node|Connection|Message|Participant|Note) /.test(c.querySelector('.cm-k').textContent); });
        await page.evaluate(() => (document.querySelector('.cm-card .cm-cancel') || document.body).focus());
        await page.keyboard.press('Escape'); await wait(200);
        kb.esc = await page.evaluate(() => !document.querySelector('.cm-card'));
        await page.keyboard.press('Escape'); await wait(150);
        await page.evaluate(id => document.querySelector('#' + id + ' .dg-zb[data-z="full"]').focus(), dgk);
        await page.keyboard.press('Enter'); await wait(300);
        kb.full = await page.evaluate(() => ovOpen() && document.activeElement.id === 'dg-close' && document.getElementById('dg-overlay').getAttribute('role') === 'dialog');
        const x0 = await page.evaluate(() => OV.x); await page.keyboard.press('ArrowRight'); kb.pan = (await page.evaluate(() => OV.x)) !== x0;
        await page.keyboard.press('Escape'); await wait(200);
        kb.back = await page.evaluate(id => !ovOpen() && document.activeElement === document.querySelector('#' + id + ' .dg-zb[data-z="full"]'), dgk);
      }
      await page.evaluate(() => { CM.items = CM.items.filter(x => x.id !== 'vckb'); cmChanged(); cmPanel(false); window.scrollTo(0, 0); });
      log(Object.values(kb).every(Boolean), `with the keyboard alone: the list of comments takes and returns the focus, a comment's place is a button, a diagram part is picked from a list, Escape closes a box from its buttons, and the full-window view opens, moves and closes (${Object.entries(kb).filter(e => !e[1]).map(e => e[0]).join(', ') || 'all'})`);
    }
    // A hostile file name on the page: every control of its file works and nothing it carries runs
    {
      const hf = await page.evaluate(() => (typeof ordered === 'undefined' ? null : ordered.find(p => /&#39;|[<>"']/.test(p))) || null);
      if (hf) {
        await page.evaluate(() => { window.__qxHit = 0; switchPart('diff'); }); await wait(900);
        const res = await page.evaluate(p => { const c = card(p), n = navEl(p), out = {};
          n.click(); out.nav = (document.querySelector('.ni.on') || { dataset: {} }).dataset.p === p;
          c.querySelector('.fh').click(); out.fold = c.classList.contains('iscol'); c.querySelector('.fh').click(); out.unfold = !c.classList.contains('iscol');
          c.querySelector('.rbtn').click(); out.rv = c.classList.contains('rv'); c.querySelector('.rbtn').click(); out.unrv = !c.classList.contains('rv');
          c.querySelector('.cbtn').click(); out.box = !!document.querySelector('.cm-card'); cmClose();
          out.name = c.querySelector('.ft').textContent === p; out.extra = document.querySelectorAll('#fc img[onerror], #nav-inner img').length; out.hit = window.__qxHit; return out; }, hf);
        log(res.nav && res.fold && res.unfold && res.rv && res.unrv && res.box && res.name && res.extra === 0 && res.hit === 0,
          `a file whose name holds an entity and quotes is listed under that exact name; its list entry, header, review and comment buttons all work, and nothing in the name runs (${hf.slice(0, 50)})`);
        await page.evaluate(() => { switchPart(PART_KEYS[0]); window.scrollTo(0, 0); }); await wait(300);
      } else console.log('NOTE\tno file with a hostile name on this page; the file-name check ran on the escape function only');
    }
    // A save the browser refuses is said in a message that stays, and goes when a later save works
    {
      const sv = await page.evaluate(async () => {
        const real = Storage.prototype.setItem; let refused = 0;
        Storage.prototype.setItem = function () { refused++; throw new DOMException('quota', 'QuotaExceededError'); };
        CM.items.push({ id: 'vcsv', kind: 'page', part: 'page', quote: '', text: 'vc not saved', label: '', t: Date.now(), state: 'open', pic: 'data:image/png;base64,AAAA' }); cmChanged();
        const w = document.getElementById('save-warn'), during = { shown: !!w && !w.hidden, text: w ? w.textContent : '', role: w ? w.getAttribute('role') : '', pic: (CM.items.find(x => x.id === 'vcsv') || {}).pic, stored: (localStorage.getItem(CM_KEY) || '').includes('vc not saved') };
        saveS(); const marks = !!document.getElementById('save-warn') && !document.getElementById('save-warn').hidden;
        Storage.prototype.setItem = real;
        CM.items = CM.items.filter(x => x.id !== 'vcsv'); cmChanged(); saveS();
        return { during, marks, refused, after: document.getElementById('save-warn').hidden };
      });
      log(sv.refused > 0 && sv.during.shown && sv.during.role === 'alert' && /did not save/.test(sv.during.text) && /Copy feedback/.test(sv.during.text) && !sv.during.stored && sv.during.pic === 'data:image/png;base64,AAAA' && sv.marks && sv.after,
        'when the browser refuses to save, a message that stays says so and what to do, for comments and for reviewed marks; the comment and its picture stay on the page, and the message goes once a save works');
    }
    // A file name with quotes, an entity and a tag is shown as text and runs nothing, wherever a path goes into the page
    {
      const fx = await page.evaluate(() => {
        const names = ['a&#39;);window.__qxHit=1;(&#39;.js', 'x"><img src=x onerror="window.__qxHit=2">.py', "o'brien\\dir\nline.go"]; window.__qxHit = 0;
        const box = document.createElement('div'); box.hidden = true; document.body.appendChild(box);
        const got = names.map(n => { box.innerHTML = '<a href="#" onclick="window.__qxSeen = \'' + jsq(n) + '\'; return false">x</a>'; window.__qxSeen = null; box.firstChild.click(); return window.__qxSeen === n && box.children.length === 1; });
        box.remove(); return { got, hit: window.__qxHit };
      });
      log(fx.got.every(Boolean) && fx.hit === 0, `a path with quotes, an entity, a tag, a backslash or a line end reaches its click handler as the very same text and runs nothing (${fx.got.join(', ')})`);
    }
    // Comments on the source itself, made and shown as on the text of the page; a comment is found again by the text of its lines
    await page.evaluate(() => cmPanel(false)); await wait(200);
    const sl = await page.evaluate(id => { const L = document.querySelector('#' + id + ' > .dg-src textarea').value.split('\n'), T = L.map(l => l.trim());
      const k = T.findIndex((t, i) => i > 0 && i < 6 && i < T.length - 1 && t && T[i + 1] && T.indexOf(t) === T.lastIndexOf(t));
      return { k: k + 1, line: k < 0 ? '' : L[k].replace(/\s+$/, ''), name: document.getElementById(id).dataset.name, rows: document.querySelectorAll('#' + id + ' .dg-src-ln').length, n: L.length }; }, d2dg);
    if (sl.k) {
      const srcC = () => page.evaluate(id => { const c = CM.items.find(x => x.tk === 'src'), dg = document.getElementById(id), m = dg.querySelector('.dg-src-g .cm-mark'), h = dg.querySelector('.dg-src-hi .cm-hl'), g = dgSrcGeo(dg.querySelector(':scope > .dg-src'));
        return { st: c ? c._state : 'none', ln: c && c._pieces ? c._ln : 0, at: m ? +m.dataset.ln : 0, hl: h ? Math.round((parseFloat(h.style.top) - g.py) / g.lh) + 1 : 0, look: m ? getComputedStyle(m).width + ' ' + getComputedStyle(m).backgroundColor : '', btn: dg.querySelector('.dg-srcb').textContent, where: c && c._pieces ? cmWhere(c, true) : '',
          chip: (dg.querySelector('.cm-dglost:not([hidden])') || { textContent: '' }).textContent, stt: (dg.querySelector('.dg-src-st') || { textContent: '' }).textContent, fb: cmFeedback() }; }, d2dg);
      const cardHead = () => page.evaluate(() => { const c = document.querySelector('.cm-card'); return c ? c.querySelector('.cm-k').textContent + ' | ' + c.querySelector('.cm-q').textContent : ''; });
      await srcAdd(d2dg, sl.k);
      const head = await cardHead();
      await page.keyboard.type('vc source line'); await page.keyboard.press('Enter'); await wait(400);
      let c = await srcC();
      log(sl.rows === sl.n && head === 'Source of diagram "' + sl.name + '", line ' + sl.k + ' | ' + sl.line && c.st === 'anchored' && c.at === sl.k && c.hl === sl.k && c.look === '18px rgb(178, 106, 0)' && c.btn === 'Source (1)'
        && c.fb.includes('Source of diagram "' + sl.name + '", line ' + sl.k + '\n   | ' + sl.line + '\n   Comment: vc source line') && !/Source line \d|keep the ids|reader edited/.test(c.fb),
        `the button beside a line of the source comments on that line; its text is highlighted, the usual marker stands beside it, the Source button counts it and its text is copied (${c.look}): ${head.slice(0, 90)}`);
      await typeSrc(d2dg, '# a line added above\n' + d2src); await wait(900); c = await srcC();
      log(c.st === 'anchored' && c.ln === sl.k + 1 && c.at === sl.k + 1 && c.hl === sl.k + 1 && c.where.endsWith('line ' + (sl.k + 1)) && c.fb.includes('counts in the source as the reader edited it') && !/no longer/.test(c.stt),
        `a comment on a source line follows its line when the reader adds lines above, and the copied text says which text the number counts in (${c.st}, line ${c.ln})`);
      const dl = d2src.split('\n'), one = dl[sl.k - 1];
      await typeSrc(d2dg, dl.filter((l, i) => i !== sl.k - 1).join('\n') + '\nxx\n' + one + '\nyy\n' + one + '\nzz'); await wait(900); const two = await srcC();
      await typeSrc(d2dg, d2src + '\nxx\n' + one); await wait(900); const dup = await srcC();
      log(two.st === 'notfound' && /With this edit, 1 comment on the source no longer finds its line\. Reset brings it back\./.test(two.stt) && two.chip === '1 not found' && dup.st === 'anchored' && dup.ln === sl.k,
        `a line that now stands twice, neither time between its old neighbours, is not guessed at and is counted as not placed; between its old neighbours it is found (${two.st}, ${dup.st} line ${dup.ln}): ${two.stt.slice(0, 100)}`);
      await typeSrc(d2dg, d2src); await wait(900);
      const selRows = await page.evaluate(([id, k]) => { const ta = document.querySelector('#' + id + ' > .dg-src textarea'), L = ta.value.split('\n'), a = L.slice(0, k - 1).join('\n').length + (k > 1 ? 1 : 0);
        ta.scrollTop = 0; ta.focus(); ta.setSelectionRange(a + 1, a + L[k - 1].length + 1 + L[k].length); ta.dispatchEvent(new KeyboardEvent('keyup', { key: 'ArrowDown', shiftKey: true }));
        return new Promise(r => setTimeout(() => r(!document.getElementById('cm-add').hidden && document.getSelection().isCollapsed ? 2 : 0), 80)); }, [d2dg, sl.k]);
      // the editor scrolls while text is selected in it: the Comment button is placed again, not lost
      const kept = await page.evaluate(id => { const ta = document.querySelector('#' + id + ' > .dg-src textarea'); ta.dispatchEvent(new Event('scroll')); return !document.getElementById('cm-add').hidden; }, d2dg);
      log(kept, 'a scroll of the source editor while text is selected in it leaves the Comment button in reach');
      await page.click('#cm-add'); await wait(300);
      const head2 = await cardHead(), pend = await page.evaluate(id => document.querySelectorAll('#' + id + ' .dg-src-hi .cm-hl.cm-pending').length, d2dg);
      const spent = await page.evaluate(id => { const ta = document.querySelector('#' + id + ' > .dg-src textarea'); return ta.selectionStart === ta.selectionEnd; }, d2dg);
      await page.keyboard.press('Escape'); await wait(200);
      log(selRows === 2 && pend === 2 && spent && head2.startsWith('Source of diagram "' + sl.name + '", lines ' + sl.k + ' to ' + (sl.k + 1) + ' | '), `text selected in the source brings up the page's Comment button, though the document's own selection is empty; it comments on the selected lines, which stay highlighted while the box is open: ${head2.slice(0, 80)}`);
      await page.evaluate(id => dgSrcOpen(document.getElementById(id), false), d2dg); await page.reload(); await wait(1800);
      const shut = await page.evaluate(id => { const dg = document.getElementById(id), c = CM.items.find(x => x.tk === 'src'); return !dg.querySelector(':scope > .dg-src') && dg.querySelector('.dg-srcb').textContent === 'Source (1)' && !!c && c._state === 'anchored'; }, d2dg);
      await page.evaluate(() => cmPanel(true)); await wait(300);
      await page.click('#cm-panel .cm-it[data-cid] .cm-it-t'); await wait(500);
      log(shut && await page.evaluate(([id, k]) => { const box = document.querySelector('#' + id + ' > .dg-src'); return !!box && !!box.querySelector('.dg-src-g .cm-mark.cm-flash[data-ln="' + k + '"]') && !!box.querySelector('.dg-src-hi .cm-hl.cm-flash'); }, [d2dg, sl.k]),
        'after a reload the comment is still on its line with the editor closed; from the panel a click opens the editor on that line');
      await page.evaluate(() => { CM.items = CM.items.filter(x => x.tk !== 'src'); cmChanged(); }); await wait(200);
    }
    await page.evaluate(id => { dgSrcOpen(document.getElementById(id), false); cmPanel(false); }, d2dg); await wait(200);
  }
  const looks = await page.evaluate(() => { const css = e => { const s = getComputedStyle(e); return [s.width, s.height, s.borderTopColor, s.borderTopLeftRadius, s.color].join(); };
    const mm = [...document.querySelectorAll('.dg[data-kind="mermaid"]')].find(d => !cmDgParts(d).length); let hint = null;
    if (mm) { cmDgSetMode(mm); hint = mm.querySelector(':scope > .cm-dgtip').textContent; cmDgSetMode(null); }
    const all = ['.cm-dgbtn', '.cm-tadd', '#cm-blk-add', '#cm-tbl-add'].map(s => document.querySelector(s)).filter(Boolean).map(css);
    return { hint, same: all.length >= 3 && all.every(x => x === all[0]), add: !!document.querySelector('#cm-add svg') }; });
  if (looks.hint !== null) log(looks.hint.startsWith('Click the diagram to comment on it as a whole'), 'the comment-mode hint says what the diagram allows: a diagram with no known parts is commented as a whole');
  log(looks.same && looks.add, 'every comment button on the page has the same size, border and colour, and the speech bubble');
  // The Annotate switch hides every comment button, marker and highlight, and keeps the comments
  await selectProse(); await wait(250); await page.click('#cm-add'); await page.keyboard.type('kept'); await page.keyboard.press('Enter'); await wait(250);
  await page.click('#cm-toggle'); await wait(250);
  const cmShown = sel => page.evaluate(sel => [...document.querySelectorAll(sel)].some(e => getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0), sel);
  log(await page.evaluate(() => document.body.classList.contains('cm-off') && document.getElementById('cm-toggle').getAttribute('aria-checked') === 'false' && CM.items.length === 1)
    && !(await cmShown('.cm-layer, .cm-mark, .cm-hl, #cm-panel-btn, .cm-tadd, #cm-panel')), 'Annotate off hides the highlights, markers and comment buttons, and keeps the comments');
  await page.keyboard.press('/'); await wait(150);
  await page.evaluate(() => navigator.clipboard.writeText('x')); const offSel = await selectProse(); await wait(350);
  const hov = await page.evaluate(() => { const p = [...document.querySelectorAll('#part-brief .page p')].find(x => cmBlockOf(x) === x); const b = p.getBoundingClientRect(); return { x: b.left + 40, y: b.top + 8 }; });
  await page.evaluate(() => getSelection().removeAllRanges()); await page.mouse.move(hov.x - 5, hov.y); await page.mouse.move(hov.x, hov.y); await wait(200);
  log(await page.evaluate(() => !document.querySelector('.cm-card') && document.getElementById('cm-add').hidden && document.getElementById('cm-blk-add').hidden)
    && (await page.evaluate(() => navigator.clipboard.readText().catch(() => ''))).includes(offSel), 'with Annotate off, "/", a selection and the pointer offer no comment; a selection is still copied');
  await page.reload(); await wait(1200);
  log(await page.evaluate(() => document.body.classList.contains('cm-off')), 'Annotate stays off across a reload');
  await page.click('#cm-toggle'); await wait(250);
  log(await page.evaluate(() => !document.body.classList.contains('cm-off') && document.querySelectorAll('#part-brief .cm-mark').length === 1) && await cmShown('#part-brief .cm-hl') && await cmShown('#cm-panel-btn'),
    'Annotate on brings the highlights, markers and buttons back');
  log(await page.evaluate(() => { const g = document.querySelector('.cm-grp'), b = document.getElementById('cm-panel-btn'), s = document.getElementById('cm-toggle'), t = document.getElementById('theme-toggle');
    return g.contains(b) && g.contains(s) && !!b.querySelector('svg') && s.getAttribute('role') === 'switch' && !!t.querySelector('svg') && t.textContent.trim() === '' && /^Switch to (light|dark) mode$/.test(t.title)
      && !!b.getAttribute('aria-label') && !!s.getAttribute('aria-label'); }), 'the comments button, the Annotate switch and the light/dark button are pictures with a name for screen readers');
  await page.evaluate(() => { CM.items = []; cmChanged(); });
  // Copy feedback: labels, the automatic copy, the preview, the button, and old notes turned into file comments
  const clip = async () => (await page.evaluate(() => navigator.clipboard.readText().catch(() => ''))).replace(/\r\n/g, '\n');   // Windows hands the clipboard back with CRLF
  const quotedF = await selectProse(); await wait(250); await page.click('#cm-add'); await wait(150);
  await page.click('.cm-card .cm-lab[data-lab="question"]'); await page.keyboard.type('why?'); await page.keyboard.press('Shift+Enter'); await page.keyboard.type('second'); await page.keyboard.press('Enter'); await wait(400);
  const auto = await clip();
  log(auto.startsWith('Feedback on the change explanation "') && /\nPage: .+\.html\n/.test(auto) && auto.includes('\nExplanation id: ') && /\n1\. \[Question\] \S/.test(auto) && auto.includes('\n   Quote: "' + quotedF + '"\n')
    && auto.includes('\n   Comment: why?\n   second\n') && auto.includes('\nLabels:\n- Question: ') && auto.trimEnd().endsWith(await page.evaluate(() => CM_ASK)),
    'saving a comment copies the feedback: page path, numbered comment with label, quote and text, the label instruction, the closing request');
  await page.click('#cm-panel-btn'); await wait(250); await page.click('#cm-panel [data-act="preview"]'); await wait(150);
  log(await page.evaluate(a => { const v = document.querySelector('#cm-panel .cm-prev'); return !v.hidden && v.textContent === a && v.getBoundingClientRect().height > 40; }, auto), 'the preview shows the exact text that is copied');
  await page.evaluate(() => { const c = CM.items[0]; document.querySelector('#cm-panel .cm-it[data-cid="' + c.id + '"] [data-act="edit"]').click(); }); await wait(150);
  await page.click('#cm-panel .cm-lab[data-lab="fix"]'); await page.keyboard.press('Enter'); await wait(400);
  log(await page.evaluate(() => CM.items[0].label === 'fix' && document.querySelector('#cm-panel .cm-tag-l').textContent === 'Fix' && document.querySelector('#cm-panel .cm-prev').textContent.includes('1. [Fix] ')
    && !document.querySelector('#cm-panel .cm-prev').textContent.includes('Question')) && (await clip()).includes('1. [Fix] '), 'a label changed in the panel shows on the comment, in the preview and in the copied text');
  await page.evaluate(() => navigator.clipboard.writeText('x')); await page.click('#cm-panel [data-act="copy"]'); await wait(300);
  log(await clip() === await page.evaluate(() => document.querySelector('#cm-panel .cm-prev').textContent), 'Copy feedback copies the text the preview shows');
  const lineFb = await page.evaluate(() => { const p = ordered[0], rows = cmDiffSide(p, 'new'); if (rows.length < 2) return null;
    CM.items.push({ id: 'cl', kind: 'line', part: 'diff', path: p, side: 'new', ln: rows[0].ln, ln2: rows[1].ln, lines: [rows[0].c, rows[1].c], quote: '', text: 'two lines', label: '', t: 5, state: 'open' });
    CM.items.push({ id: 'cf', kind: 'file', part: 'diff', path: p, quote: '', text: 'the file', label: '', t: 6, state: 'open' });
    CM.items.push({ id: 'cg', kind: 'text', part: PART_KEYS[0], section: '', quote: 'text that is not on the page', prefix: '', suffix: '', text: 'lost', label: '', t: 7, state: 'open' });
    cmChanged(); const f = cmFeedback();
    return { f, file: '. File ' + p + '\n   Comment: the file', line: '. ' + p + ', lines ' + rows[0].ln + ' to ' + rows[1].ln + ', new side\n   | ' + rows[0].c + '\n   | ' + rows[1].c + '\n   Comment: two lines' }; });
  if (lineFb) log(lineFb.f.includes(lineFb.file) && lineFb.f.includes(lineFb.line) && lineFb.f.indexOf(lineFb.file) < lineFb.f.indexOf(lineFb.line) && /\(not found on the page as it is now[^\n]*\n   Quote: "text that is not on the page"/.test(lineFb.f),
    'the copied text names a file, quotes diff lines with their numbers, and says when a comment is no longer found');
  await page.evaluate(() => { CM.items.forEach(c => { c.state = 'resolved'; }); cmChanged(); });
  log(await page.evaluate(() => cmFeedback() === '' && document.querySelector('#cm-panel .cm-prev').textContent.startsWith('Nothing to copy')), 'resolved comments are left out of the copied text');
  // What the store holds is untrusted: a malformed comment is left out and the rest still works; another tab's save is taken up
  await page.evaluate(() => { localStorage.setItem(CM_KEY, JSON.stringify({ v: 1, items: [{ id: 'vcok', kind: 'page', part: 'page', quote: '', text: 'vc well formed', label: '', t: 1, state: 'open' },
    { id: 'vcbad1', kind: 'line', part: 'diff', path: 'x', text: 'no lines' }, { id: 7, text: 'no id' }, null, 'text', { id: 'vcpic', kind: 'page', part: 'page', text: 'vc picture', state: 'open', t: 2, pic: 'x" onerror="window.__qxHit=3' }] })); });
  await page.reload(); await wait(1200);
  const taken = await page.evaluate(() => { cmPanel(true); return { ids: CM.items.map(c => c.id).join(','), listed: document.querySelectorAll('#cm-panel .cm-pl > .cm-it[data-cid]').length, imgs: document.querySelectorAll('#cm-panel .cm-pic img').length, hit: window.__qxHit || 0 }; });
  log(taken.ids === "vcok,vcpic" && taken.listed === 2 && taken.imgs === 0 && taken.hit === 0, `stored comments that are not well formed are left out, the others are listed, and a stored picture address that is not a picture is not drawn (${taken.ids})`);
  const other = await page.context().newPage(); await other.goto(page.url()); await other.waitForTimeout(900);
  await other.evaluate(() => { CM.items.push({ id: 'vctab', kind: 'page', part: 'page', quote: '', text: 'vc from the other tab', label: '', t: Date.now(), state: 'open' }); cmChanged(); });
  await wait(400);
  await page.evaluate(() => { const c = CM.items.find(x => x.id === 'vcok'); c.state = 'resolved'; cmChanged(); }); await wait(300);
  // while this tab holds a half-written comment in its list, the other tab marks a file reviewed and saves a diagram edit
  await page.evaluate(() => { cmPanel(true); cmPanelAct('edit', 'vcpic'); document.querySelector('#cm-panel .cm-it-ta').value = 'vc half written'; });
  await other.evaluate(() => { switchPart('diff'); toggleR(ordered[0]); CM.edits['vc-no-such-diagram'] = { text: 'graph TD; a-->b', base: 'x' }; cmSave(); });
  await wait(500);
  const live = await page.evaluate(() => ({ draft: (document.querySelector('#cm-panel .cm-it-ta') || {}).value, edit: !!CM.edits['vc-no-such-diagram'], told: /another tab/.test(document.getElementById('toast').textContent), rv: isRv(ordered[0]) }));
  await page.evaluate(() => { switchPart('diff'); }); await wait(300);
  live.card = await page.evaluate(() => { const c = document.querySelector('.fc'); return !c || (c.classList.contains('rv') && c.querySelector('.rbtn').textContent === 'Reviewed'); });
  await other.evaluate(() => { toggleR(ordered[0]); delete CM.edits['vc-no-such-diagram']; cmSave(); }); await wait(300);
  await page.evaluate(() => { cmPanelAct('cancel', 'vcpic'); switchPart('brief'); });
  log(live.draft === 'vc half written' && live.edit && live.told && live.rv && live.card, `a save in another tab keeps this tab's half-written comment, shows the file it marked reviewed, and says that a diagram edit needs a reload (${Object.entries(live).filter(e => !e[1]).map(e => e[0]).join(', ') || 'all'})`);
  const tabs = await other.evaluate(() => ({ kept: CM.items.some(x => x.id === 'vctab'), seen: (CM.items.find(x => x.id === 'vcok') || {}).state, stored: JSON.parse(localStorage.getItem(CM_KEY)).items.map(x => x.id).join(',') }));
  await other.close();
  log(tabs.kept && tabs.seen === 'resolved' && /vctab/.test(tabs.stored), `two tabs of one explanation do not write over each other: a comment made in one survives a change made in the other (${tabs.stored})`);
  await page.evaluate(() => { CM.items = []; cmChanged(); cmPanel(false); });
  // Comments on a whole paragraph or table cell, without selecting text
  const pAt = await page.evaluate(() => {
    const p = [...document.querySelectorAll('#part-brief .page p')].find(x => x.textContent.trim().length > 60 && cmBlockOf(x) === x);
    p.scrollIntoView({ block: 'center' }); window.__p = p; const b = p.getBoundingClientRect(); return { x: b.left + 40, y: b.top + b.height / 2 }; });
  await page.mouse.move(pAt.x - 5, pAt.y); await page.mouse.move(pAt.x, pAt.y); await wait(200);
  log(await page.evaluate(() => { const b = document.getElementById('cm-blk-add'); return !!b && !b.hidden && b.getBoundingClientRect().left >= window.__p.getBoundingClientRect().right; }),
    'the pointer over a paragraph offers a comment button beside it');
  await page.hover('#cm-blk-add'); await wait(150);
  log(await page.evaluate(() => { const h = document.getElementById('cm-hint'), b = document.getElementById('cm-blk-add'); if (!h || h.hidden || !b.querySelector('svg')) return false;
    const a = h.getBoundingClientRect(), p = window.__p.getBoundingClientRect(); return a.top <= p.top && a.bottom >= p.bottom && a.left <= p.left; }),
    'the pointer over the comment button lights the paragraph it would comment on');
  await page.click('#cm-blk-add'); await wait(200);
  log(await page.evaluate(() => { const k = document.querySelector('.cm-card .cm-k'); return !!k && k.textContent === 'Paragraph' && !!document.querySelector('.cm-hl.cm-blk.cm-pending'); }),
    'the comment button opens a box named for the paragraph, with the paragraph marked');
  await page.keyboard.type('whole paragraph'); await page.keyboard.press('Enter'); await wait(250);
  log(await page.evaluate(() => { const c = CM.items[CM.items.length - 1];
    return CM.items.length === 1 && c.kind === 'block' && c.quote === window.__p.textContent.trim() && c._el === window.__p
      && document.querySelectorAll('#part-brief .cm-hl.cm-blk').length === 1 && document.querySelectorAll('#part-brief .cm-mark').length === 1; }),
    'a paragraph comment stores the whole paragraph and draws one box and one marker');
  await page.reload(); await wait(1200);
  const pAgain = await page.evaluate(() => { const h = document.querySelector('#part-brief .cm-hl.cm-blk'); if (!h) return null;
    h.scrollIntoView({ block: 'center' }); const b = h.getBoundingClientRect(); return { x: b.left + 40, y: b.top + b.height / 2 }; });
  log(!!pAgain, 'after a reload the paragraph comment is placed on its paragraph again');
  if (pAgain) {
    await page.mouse.move(pAgain.x - 5, pAgain.y); await page.mouse.move(pAgain.x, pAgain.y); await wait(200);
    log(await page.evaluate(() => document.getElementById('cm-blk-add').hidden), 'a paragraph that already has a comment offers no second button');
    await page.mouse.click(pAgain.x, pAgain.y); await wait(200);
    log(await page.evaluate(() => { const t = document.querySelector('.cm-card textarea'); return !!t && t.value === 'whole paragraph'; }), 'clicking a commented paragraph opens its comment');
    await page.evaluate(() => document.querySelector('.cm-card .cm-del').click()); await wait(200);
  }
  const cell = await page.evaluate(() => {
    const td = [...document.querySelectorAll('td')].find(x => cmBlockOf(x) && x.cellIndex > 0 && !x.closest('table').querySelector('[colspan], [rowspan]') && x.closest('table').rows[0].querySelector('th'));
    if (!td) return null;
    const t = x => x.textContent.replace(/\s+/g, ' ').trim();
    return { got: cmCellLabel(td), want: t(td.parentElement.cells[0]) + ' → ' + t(td.closest('table').rows[0].cells[td.cellIndex]), name: cmBlockName(td),
      merged: (() => { const c = td.closest('table').cloneNode(true); c.rows[0].cells[0].setAttribute('colspan', '2'); return cmCellLabel(c.rows[1].cells[1]); })() };
  });
  if (cell) {
    log(cell.got === cell.want && cell.name === 'Table cell (' + cell.want + ')', `a table cell is named by its row and column: ${cell.got}`);
    log(cell.merged === '', 'a table with merged cells gets no row and column label');
  }
  const tdAt = await page.evaluate(() => { const td = [...document.querySelectorAll('#part-brief .page td')].find(x => cmBlockOf(x) === x && x.textContent.trim());
    if (!td) return null; td.scrollIntoView({ block: 'center' }); window.__td = td; const b = td.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; });
  if (tdAt) {
    await page.mouse.move(tdAt.x - 5, tdAt.y); await page.mouse.move(tdAt.x, tdAt.y); await wait(200);
    log(await page.evaluate(() => { const b = document.getElementById('cm-blk-add'), t = document.getElementById('cm-tbl-add'); if (b.hidden || t.hidden) return false;
      const k = b.getBoundingClientRect(), c = window.__td.getBoundingClientRect(), q = t.getBoundingClientRect(), tr = window.__td.closest('table').getBoundingClientRect();
      return Math.abs((k.top + k.bottom) / 2 - (c.top + c.bottom) / 2) < 1.5 && q.bottom <= tr.top + 1; }),
      'over a table cell: a button centred on the cell, and a second one above the table');
    await page.click('#cm-tbl-add'); await wait(200);
    const tk = await page.evaluate(() => document.querySelector('.cm-card .cm-k') ? document.querySelector('.cm-card .cm-k').textContent : '');
    await page.keyboard.type('whole table'); await page.keyboard.press('Enter'); await wait(250);
    await page.reload(); await wait(1200);
    log(tk === 'Table' && await page.evaluate(() => { const c = CM.items[CM.items.length - 1]; return !!c && c.tag === 'table' && !!c._el && c._el.tagName === 'TABLE' && document.querySelectorAll('#part-brief .cm-hl.cm-blk').length === 1; }),
      'a comment on a whole table is stored for the table and placed on it again after a reload');
  }
  await page.evaluate(k => { localStorage.removeItem(k); }, cmKey);
  await page.reload(); await wait(1200);
  await page.evaluate(() => { navigator.clipboard.writeText = window.__w; document.execCommand = window.__x; });
  log(has('brief'), `parts present: ${info.parts.join(', ')}`);

  // 1. Provenance on every part, and Mermaid in the brief
  for (const p of info.parts) {
    await page.evaluate(k => switchPart(k), p); await wait(400);
    await page.click('#info-toggle'); await wait(150);
    log(await page.evaluate(() => { const p = document.querySelector('#info-pop .prov'); return !!p && p.getBoundingClientRect().height > 20 && document.querySelectorAll('.prov').length === 1; }), `Info menu shows the provenance on ${p}`);
    await page.keyboard.press('Escape'); await wait(100);
    log(await page.evaluate(() => document.getElementById('info-pop').hidden), `Escape closes the Info menu on ${p}`);
  }
  await page.evaluate(() => switchPart('brief')); await wait(1500);
  const briefMermaid = await page.$$eval('#part-brief .mmd', ns => ns.map(n => !!n.querySelector('svg') && !/Syntax error/i.test(n.textContent)));
  if (briefMermaid.length) log(briefMermaid.every(Boolean), `Mermaid in the brief renders (${briefMermaid.length})`);
  const briefD2 = await page.$$eval('#part-brief .dg', ns => ns.map(n => { const v = Array.from(n.querySelectorAll('.dgv')).find(x => x.offsetParent !== null); return !!v && !!v.querySelector('svg'); }));
  if (briefD2.length) log(briefD2.every(Boolean), `D2 diagrams in the brief show one SVG variant (${briefD2.length})`);

  // Click a diagram to enlarge it; Escape closes the overlay. The diagram band stays inside the viewport.
  const firstDiagram = await page.$('#part-brief .dgv:not([style*="none"]), #part-brief .dg .mmd');
  if (firstDiagram) {
    const fits = await page.evaluate(() => Array.from(document.querySelectorAll('#part-brief .dg')).every(d => { const b = d.getBoundingClientRect(); return b.left >= 0 && b.right <= innerWidth + 1; }));
    log(fits, 'diagram band stays inside the window');
    const visible = await page.evaluate(() => { const e = Array.from(document.querySelectorAll('#part-brief .dgv, #part-brief .dg .mmd')).find(x => x.offsetParent !== null); if (e) e.click(); return !!e; });
    await wait(300);
    if (visible) {
      log(await page.$eval('#dg-overlay', o => !o.hidden && !!o.querySelector('svg')), 'clicking a diagram opens it full window');
      await page.keyboard.press('Escape'); await wait(200);
      log(await page.$eval('#dg-overlay', o => o.hidden), 'Escape closes the overlay');
    }
  }

  // 2-3. Walkthrough and Maps
  if (has('walkthrough')) {
    await page.evaluate(() => switchPart('walkthrough')); await wait(600);
    const subs = await page.$$('#part-walkthrough .sub-btn');
    if (subs.length > 1) {
      await subs[1].click(); await wait(300);
      const shown = await page.$$eval('#part-walkthrough .sub-panel', ps => ps.filter(p => p.classList.contains('active')).length);
      log(shown === 1, `walkthrough sub-tabs switch (${subs.length} tabs)`);
    }
    await page.screenshot({ path: path.join(out, '2-walkthrough.png') });
  }
  if (has('maps')) {
    await page.evaluate(() => switchPart('maps')); await wait(1500);
    for (const v of info.views) {
      await page.evaluate(id => switchMap(id), v.vid); await wait(v.kind === 'mermaid' ? 2500 : 800);
      const drawn = await page.evaluate(id => {
        const p = document.getElementById('view-' + id);
        if (p.querySelector('.mmd')) { const s = p.querySelector('.mmd svg'); return !!s && !/Syntax error/i.test(s.textContent); }
        const vis = Array.from(p.querySelectorAll('.dgv')).find(x => x.offsetParent !== null);
        return !!vis && !!vis.querySelector('svg') && vis.getBoundingClientRect().height > 20;
      }, v.vid);
      log(drawn, `map ${v.vid}: ${v.kind} diagram drawn`);
      await page.screenshot({ path: path.join(out, `3-map-${v.vid}.png`) });
      if (v.tour.length) {
        let ok = true;
        for (let i = 0; i < v.tour.length; i++) {
          if (i) { await page.click(`#view-${v.vid} .tour-box button:last-child`); await wait(400); }
          const st = await page.evaluate(id => { const p = document.getElementById('view-' + id);
            return { caption: p.querySelector('.tour-caption').textContent, hl: +p.dataset.hl,
                     dimmed: p.querySelectorAll('svg g.dim, svg path.dim').length }; }, v.vid);
          const wants = v.tour[i].highlight && v.tour[i].highlight.length;
          if (st.caption !== v.tour[i].caption || (wants && !(st.hl > 0))) { ok = false; log(false, `map ${v.vid}: tour step ${i + 1} (caption "${st.caption}", elements really lit ${st.hl}; it must be above zero)`); }
          if (v.kind === 'd2' && wants && !st.dimmed) { ok = false; log(false, `map ${v.vid}: tour step ${i + 1} dims nothing`); }
        }
        if (ok) log(true, `map ${v.vid}: all ${v.tour.length} tour steps caption, light and dim`);
      }
    }
    const mapSubs = await page.$$('#part-maps .sub-btn');
    if (mapSubs.length > 1) {
      await mapSubs[1].click(); await wait(800);
      log(await page.$eval('#part-maps .sub-panel.active', p => p.querySelector('.map-panel.active') !== null), `map sub-tabs switch (${mapSubs.length} tabs) and show a view`);
    }
    // Hash routing
    const target = info.views[info.views.length - 1];
    const p2 = await ctx.newPage(); watch(p2);
    await p2.goto(url + '#maps/' + target.vid); await wait(3000);
    log(await p2.$eval(`[data-view="${target.vid}"]`, b => b.classList.contains('active')), `#maps/${target.vid} opens that view on load`);
    await p2.close();
  }

  // 4. D2 sketch toggle and Show changes
  if (info.hasD2) {
    await page.evaluate(() => localStorage.removeItem('qexplain-change-sketch'));
    await page.evaluate(() => { applySketch(false); });
    const shownVariant = () => page.evaluate(() => { const v = Array.from(document.querySelectorAll('.dgv')).find(x => x.offsetParent !== null); return v ? (v.classList.contains('v-sketch') ? 'sketch' : 'classic') : 'none'; });
    await page.evaluate(() => switchPart('brief')); await wait(300);
    const before = await shownVariant();
    await page.click('#sketch-toggle'); await wait(200);
    const after = await shownVariant();
    const kept = await page.evaluate(() => localStorage.getItem('qexplain-change-sketch'));
    log(before === 'sketch' && after === 'classic' && kept === 'classic', `sketch toggle swaps the variant (${before} to ${after}) and persists (${kept})`);
    await page.click('#sketch-toggle'); await wait(200);
    const box = await page.$('#view-system .chg input');
    if (box) {
      await page.evaluate(() => switchPart('maps')); await wait(500);
      await page.evaluate(() => switchMap('system')); await wait(500);
      const fill = () => page.evaluate(() => { const s = document.querySelector('#view-system .dgv.v-light.v-classic g.new > .shape > *, #view-system .dgv.v-light.v-classic g.changed > .shape > *'); return s ? getComputedStyle(s).fill : ''; });
      const on = await fill();
      await page.evaluate(() => { const b = document.querySelector('#view-system .chg input'); b.checked = false; toggleChanges(b); });
      const off = await fill();
      await page.evaluate(() => { const b = document.querySelector('#view-system .chg input'); b.checked = true; toggleChanges(b); });
      log(!!on && on !== off, `Show changes switch changes a highlighted shape (${on} to ${off})`);
    }
  }

  // 5. Theme, and Mermaid redrawn with the new theme
  await page.evaluate(() => switchPart('brief')); await wait(1500);
  const bg0 = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.click('#theme-toggle'); await wait(2000);
  const bg1 = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const stored = await page.evaluate(() => localStorage.getItem('qexplain-change-theme'));
  log(bg0 !== bg1 && !!stored, `theme toggle re-themes and persists (${stored})`);
  const stale = await page.$$eval('.mmd', ns => ns.filter(n => n.offsetParent !== null && n.dataset.theme !== document.documentElement.dataset.theme.replace('light', 'default')).length);
  log(stale === 0, 'visible Mermaid diagrams were redrawn for the new theme');
  await page.screenshot({ path: path.join(out, '4-dark-brief.png') });
  await page.click('#theme-toggle'); await wait(500);

  // 6. Summary opens the diff; Diff review
  if (has('summary') && has('diff')) {
    await page.evaluate(() => switchPart('summary')); await wait(400);
    const link = await page.$('#part-summary a[data-file]');
    if (link) { await link.click(); await wait(600); log(await page.$eval('#part-diff', p => p.classList.contains('active')), 'a summary row opens Diff review'); }
    await page.screenshot({ path: path.join(out, '5-summary.png'), fullPage: true });
  }
  if (has('diff')) {
    await page.evaluate(k => { localStorage.removeItem(k); localStorage.removeItem('nav-w'); }, storeKey);
    await page.goto(url + '#diff'); await wait(1000);
    log(await page.$eval('#part-diff', p => p.classList.contains('active')), '#diff opens Diff review on load');
    const listed = await page.$$eval('#nav-inner .ni', n => n.length);
    log(listed === info.files, `sidebar lists ${listed} of ${info.files} files`);
    await page.click('.fc .rbtn'); await wait(200);
    log(await page.$eval('.fc', c => c.classList.contains('iscol')) && (await page.textContent('#rc')) === '1', 'Mark reviewed collapses the card and counts it');
    await page.reload(); await wait(1000);
    log(await page.$eval('.fc', c => c.classList.contains('iscol') && c.classList.contains('rv')) && (await page.textContent('#rc')) === '1', 'reviewed state survives a reload');
    log(await page.evaluate(k => localStorage.getItem(k) !== null, storeKey), 'state stored under ' + storeKey);
    // A reviewed mark is tied to the file's patch: it holds the patch's hash, and stops counting when the hash differs
    const rvOf = () => page.evaluate(k => { const c = document.querySelector('.fc'), p = c.dataset.p, n = document.querySelector('.ni[data-p="' + CSS.escape(p) + '"]');
      return { stored: JSON.parse(localStorage.getItem(k) || '{}')[p], hash: (QX.patch || {})[p] || '', rv: c.classList.contains('rv'), col: c.classList.contains('iscol'), tag: (c.querySelector('.fstats .bs') || { textContent: '' }).textContent,
        navRv: n.classList.contains('rv'), navStale: n.classList.contains('stale'), rc: document.getElementById('rc').textContent }; }, storeKey);
    const setRv = v => page.evaluate(([k, v]) => { const s = JSON.parse(localStorage.getItem(k) || '{}'), p = document.querySelector('.fc').dataset.p; s[p] = v; localStorage.setItem(k, JSON.stringify(s)); }, [storeKey, v]);
    let rv = await rvOf();
    if (rv.hash) {
      const tied = /^[0-9a-f]{16}$/.test(rv.hash) && rv.stored === rv.hash;
      await setRv('0123456789abcdef'); await page.reload(); await wait(1000); rv = await rvOf();
      const stale = !rv.rv && !rv.col && rv.tag === 'changed since your review' && rv.navStale && !rv.navRv && rv.rc === '0';
      await page.click('.fc .rbtn'); await wait(200); rv = await rvOf();
      log(tied && stale && rv.rv && rv.col && rv.tag === '' && !rv.navStale && rv.stored === rv.hash && rv.rc === '1',
        `a reviewed mark holds the hash of the file's patch; a mark made on another patch no longer counts, the file opens and says it changed since the review; marking it again clears that (${tied}, ${stale})`);
    }
    // The file list counts the open comments of each file
    const ncm = () => page.evaluate(() => { const p = document.querySelector('.fc').dataset.p, m = document.querySelector('.ni[data-p="' + CSS.escape(p) + '"] .ncm'), all = [...document.querySelectorAll('.ni .ncm')].filter(x => !x.hidden).length; return (m.hidden ? '' : m.textContent) + '/' + all; });
    await page.evaluate(() => { const p = document.querySelector('.fc').dataset.p; ['vc count one', 'vc count two'].forEach(text => CM.items.push({ id: 'vcn' + CM.items.length, kind: 'file', part: 'diff', path: p, quote: '', text, label: '', t: Date.now(), state: 'open' })); cmChanged(); }); await wait(200);
    const two = await ncm();
    await page.evaluate(() => { CM.items.find(x => x.text === 'vc count two').state = 'resolved'; cmChanged(); }); await wait(200);
    const one = await ncm();
    await page.evaluate(() => { CM.items = CM.items.filter(x => !/^vc count/.test(x.text)); cmChanged(); }); await wait(200);
    log(two === '2/1' && one === '1/1' && await ncm() === '/0', `the file list shows how many open comments each file has, and nothing for a file with none (${two}, ${one})`);
    await page.keyboard.press('j'); await wait(500);
    const before = await page.textContent('#rc');
    await page.keyboard.press('m'); await wait(300);
    log(await page.textContent('#rc') !== before, 'j then m marks the current file');
    const filters = await page.$$('.fbtn');
    if (filters.length > 3) {
      await filters[1].click(); await wait(200);
      const vis = await page.$$eval('.fc:not(.hide)', c => c.length);
      log(vis > 0 && vis < info.files, `type filter narrows ${info.files} files to ${vis}`);
      await filters[0].click();
    }
    // A removed line stands beside the line that replaces it, and the words that differ are marked
    const wm = await page.evaluate(() => {
      const one = wordMarks('  timeout: 30 # seconds', '  timeout: 90 # seconds'), far = wordMarks('return nil', 'x := compute(batch, now)'), grown = wordMarks('send(batch)', 'send(batch, retries)');
      const cut = (s, r) => r.map(([a, b]) => s.slice(a, b)).join('|');
      const cards = [...document.querySelectorAll('.fc')].map(c => { const P = c.querySelectorAll('.sp .pane'); return P.length === 2 ? [[...P[0].querySelectorAll('tr')], [...P[1].querySelectorAll('tr')]] : null; }).filter(Boolean);
      let pairs = 0, marked = 0, same = cards.every(([l, r]) => l.length === r.length), faithful = true, lone = 0;
      cards.forEach(([l, r]) => l.forEach((row, i) => {
        const o = r[i], lt = row.querySelector('td:not(.ln)'), rt = o.querySelector('td:not(.ln)');
        if (row.classList.contains('del') && o.classList.contains('add')) { pairs++; if (lt.querySelector('.wm') || rt.querySelector('.wm')) marked++; if (!row.dataset.ln || !o.dataset.ln) faithful = false; }
        else if (row.classList.contains('del') || row.classList.contains('add')) { lone++; if (!!row.dataset.ln === !!o.dataset.ln) faithful = false; }      // exactly one side holds a line
      }));
      const p = fmap[ordered.find(x => /@@/.test(fmap[x].lines.join('\n')))], raw = p.lines.filter(x => /^[-+ ]/.test(x) && !/^(---|\+\+\+) /.test(x)).length;
      return { one: one ? cut('  timeout: 30 # seconds', one[0]) + '>' + cut('  timeout: 90 # seconds', one[1]) : 'null', far, grown: grown ? cut('send(batch, retries)', grown[1]) : 'null', pairs, marked, same, faithful, lone };
    });
    log(wm.one === '30>90' && wm.far === null && wm.grown === ', retries', `word marks cover what differs between two lines, grow with an added argument, and are left out when the lines have little in common (${wm.one}; ${wm.grown})`);
    log(wm.pairs > 0 && wm.marked > 0 && wm.same && wm.faithful, `a removed line stands beside the line that replaces it (${wm.pairs} pairs, ${wm.marked} with marks); a line with no counterpart keeps an empty cell opposite (${wm.lone})`);
    // Print: the part that is showing, in the light colours, without bars, buttons and the comment tools
    {
      const shown = sel => page.evaluate(sel => [...document.querySelectorAll(sel)].filter(e => e.offsetParent !== null || getComputedStyle(e).position === 'fixed' && getComputedStyle(e).display !== 'none').length, sel);
      const chrome = '.part-bar, .top-tools, #header, #nav, #cm-panel, .cm-mark, .cm-dgbar, .rev-bar, .rbtn, .cbtn, .sub-bar, .map-bar';
      const parts = await page.evaluate(() => PART_KEYS.slice());
      await page.evaluate(() => { document.documentElement.setAttribute('data-theme', 'dark'); cmPanel(true);
        CM.items.push({ id: 'vcpr', kind: 'page', part: 'page', quote: '', text: 'vc print', label: '', t: Date.now(), state: 'open' }); cmChanged(); });
      const res = [];
      for (const k of parts) {
        await page.evaluate(k => switchPart(k), k); await wait(k === 'maps' || k === 'diff' ? 900 : 300);
        await page.emulateMedia({ media: 'print' }); await wait(150);
        res.push(await page.evaluate(([k, chrome]) => { const p = document.getElementById('part-' + k), vis = e => getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0;
          const text = getComputedStyle(p.querySelector('p, td, li') || p).color.match(/\d+/g).map(Number), bg = getComputedStyle(document.body).backgroundColor;
          const main = document.getElementById('main'), dark = [...p.querySelectorAll('.dgv.v-dark')].filter(vis).length, light = [...p.querySelectorAll('.dgv.v-light')].filter(vis).length;
          return { k, chrome: [...document.querySelectorAll(chrome)].filter(vis).length, others: [...document.querySelectorAll('.part-panel')].filter(x => x !== p && vis(x)).length, body: p.textContent.trim().length > 20 && vis(p),
            darkText: text[0] + text[1] + text[2] < 300, whiteBg: /255, 255, 255/.test(bg), pad: parseFloat(getComputedStyle(document.body).paddingRight), title: k === 'brief' ? 'n/a' : getComputedStyle(p, '::before').content,
            main: k === 'diff' && main ? parseFloat(getComputedStyle(main).marginLeft) : 0, wrap: k === 'diff' ? getComputedStyle(p.querySelector('table.dt td:not(.ln)')).whiteSpace : 'n/a', dark, light, wide: document.documentElement.scrollWidth > innerWidth + 2,
            mm: [...p.querySelectorAll('.mmd svg')].every(s => getComputedStyle(s).filter.includes('invert')) }; }, [k, chrome]));      // a Mermaid diagram drawn for the dark theme is turned to light
        await page.emulateMedia({ media: 'screen' }); await wait(100);
      }
      await page.evaluate(() => { document.documentElement.removeAttribute('data-theme'); CM.items = CM.items.filter(x => x.id !== 'vcpr'); cmChanged(); cmPanel(false); switchPart(PART_KEYS[0]); window.scrollTo(0, 0); }); await wait(300);
      const bad = res.filter(r => r.chrome || r.others || !r.body || !r.darkText || !r.whiteBg || r.pad || r.main || r.dark || !r.mm || (r.k !== 'brief' && !/ \/ /.test(r.title)) || (r.k === 'diff' && r.wrap !== 'pre-wrap'));
      log(!bad.length, `printed from the dark theme with the comment list open, each part (${res.map(r => r.k).join(', ')}) shows its own content in dark text on white, named at the top, with no bar, button or comment tool` + (bad.length ? ': ' + JSON.stringify(bad).slice(0, 400) : ''));
    }
    // With scripts off, the page says so and the Brief can still be read
    {
      const ctx = await page.context().browser().newContext({ javaScriptEnabled: false, viewport: { width: 1100, height: 800 } });
      const off = await ctx.newPage(); await off.goto(page.url().split('#')[0]); await off.waitForTimeout(500);
      const msg = await off.locator('.noscript').innerText().catch(() => ''), brief = await off.locator('#part-brief h2').first().isVisible().catch(() => false), box = await off.locator('.noscript').boundingBox().catch(() => null);
      await ctx.close();
      const on = await page.evaluate(() => document.querySelectorAll('.noscript').length);
      log(/Scripts are off/.test(msg) && /Brief below can be read/.test(msg) && brief && !!box && box.y < 5 && on === 0, 'with scripts off the page says so at its top and the Brief can still be read; with scripts on the message is not there');
    }
    // Blocks the agent marked as changed: a legend counts them, each says "changed" in words, and the buttons step through them
    {
      const rv = await page.evaluate(() => { const parts = cmRoots().map(({ part, root }) => ({ part, n: root.querySelectorAll('[data-changed]').length, bar: root.querySelector('.rev-bar') })).filter(x => x.n || x.bar);
        if (!parts.length) return null;
        const words = [...document.querySelectorAll('.page [data-changed]')].filter(el => /^(P|LI|TD|TH|H2|H3)$/.test(el.tagName)).every(el => getComputedStyle(el, '::after').content.includes('changed'));
        return { parts: parts.map(x => x.part), legend: parts.every(x => x.bar && x.bar.querySelector('.rev-what').textContent.includes(x.n + ' block')), total: parts.reduce((s, x) => s + x.n, 0), words, first: parts[0].part, n0: parts[0].n,
          indexed: cmRoots().some(({ root }) => cmIndex(root).text.includes('Changed in this version')) }; });
      if (rv) {
        await page.evaluate(p => switchPart(p), rv.first); await wait(300);
        // the legend floats: it stands at the same place on screen wherever the page is scrolled, and only on its own part
        const float = await page.evaluate(async p => { const bar = document.querySelector('#part-' + p + ' .rev-bar'), at = () => { const b = bar.getBoundingClientRect(); return [Math.round(b.left), Math.round(innerHeight - b.bottom)]; };
          window.scrollTo(0, 0); await new Promise(r => setTimeout(r, 80)); const a = at(); window.scrollTo(0, document.body.scrollHeight); await new Promise(r => setTimeout(r, 80)); const b = at(); window.scrollTo(0, 0);
          const other = PART_KEYS.find(k => k !== p && !document.querySelector('#part-' + k + ' .rev-bar')); let gone = true;
          if (other) { switchPart(other); gone = bar.offsetParent === null && bar.getBoundingClientRect().width === 0; switchPart(p); }
          const nb = bar.querySelector('button[data-r="1"]').getBoundingClientRect();
          return { fixed: getComputedStyle(bar).position === 'fixed', same: a.join() === b.join() && a[1] >= 0 && a[1] < 60, gone, btn: Math.round(nb.left) + ',' + Math.round(nb.top) }; }, rv.first); await wait(300);
        const seen = [];
        for (let i = 0; i < rv.n0 + 1; i++) { await page.click('#part-' + rv.first + ' .rev-bar button[data-r="1"]'); await wait(250);
          seen.push(await page.evaluate(p => { const el = document.querySelector('#part-' + p + ' .rev-on'), b = el ? el.getBoundingClientRect() : null, all = [...document.querySelectorAll('#part-' + p + ' [data-changed]')];
            const nb = document.querySelector('#part-' + p + ' .rev-bar button[data-r="1"]').getBoundingClientRect();
            return { i: el ? all.indexOf(el) : -1, ok: !!b && b.top > 0 && b.bottom < innerHeight, at: document.querySelector('#part-' + p + ' .rev-at').textContent, said: document.querySelector('#part-' + p + ' .rev-why').textContent,
              why: el ? el.dataset.changed || '' : '', btn: Math.round(nb.left) + ',' + Math.round(nb.top) }; }, rv.first)); }
        const order = seen.map(s => s.i).join(','), want = [...Array(rv.n0).keys(), 0].join(',');
        log(rv.legend && rv.words && !rv.indexed && float.fixed && float.same && float.gone && order === want && seen.every(s => s.ok && s.at === (s.i + 1) + ' of ' + rv.n0 && s.said === s.why && s.btn === float.btn),
          `blocks marked as changed (${rv.total} in ${rv.parts.join(', ')}) carry the word "changed"; the legend counts them and stays in place while the page scrolls; Next steps through them in page order and wraps around, each reason shown above the buttons, which never move; the legend is not commentable text`);
        await page.evaluate(() => { switchPart(PART_KEYS[0]); window.scrollTo(0, 0); });
      }
    }
    // Files named under Brief sections: every file of the page is reachable from the Brief, and a link opens its diff card
    {
      const sf = await page.evaluate(() => { const links = [...document.querySelectorAll('#part-brief .sec-files a[data-file]')]; if (!links.length) return null;
        const named = new Set(links.map(a => a.dataset.file)), rest = document.querySelector('#part-brief .sec-files.sec-rest'), heads = [...document.querySelectorAll('#part-brief h2[id^="change-"]')];
        const lastChange = heads[heads.length - 1], after = rest ? !!(lastChange.compareDocumentPosition(rest) & Node.DOCUMENT_POSITION_FOLLOWING) : true;
        const next = rest && rest.nextElementSibling; return { links: links.length, all: ordered.every(p => named.has(p)), extra: [...named].filter(p => !fmap[p]).length, after, endsChanges: !rest || !next || (next.tagName === 'H2' && !/^change-/.test(next.id)), go: links[0].dataset.file }; });
      if (sf) {
        await page.evaluate(() => { switchPart('brief'); const a = document.querySelector('#part-brief .sec-files a[data-file]'); a.scrollIntoView({ block: 'center' }); }); await wait(300);
        await page.click('#part-brief .sec-files a[data-file]'); await wait(900);
        const went = await page.evaluate(p => { const c = card(p), b = c.getBoundingClientRect(); return diffActive() && b.top < innerHeight && b.bottom > 0 && (document.querySelector('.ni.on') || { dataset: {} }).dataset.p === p; }, sf.go);
        log(sf.all && sf.extra === 0 && sf.after && sf.endsChanges && went,
          `the Brief names every file of the page under its sections or in one list after them (${sf.links} links), and a link opens that file's card in Diff review`);
        await page.evaluate(() => window.scrollTo(0, 0));
      }
    }
    // The agent's notes on diff lines: under their lines, read-only, both sides level, and never in the copied feedback
    {
      const an = await page.evaluate(() => {
        const N = QX.notes || {}, all = Object.entries(N).flatMap(([p, ns]) => ns.map(n => [p, n])); if (!all.length) return null;
        document.querySelectorAll('.fc.iscol').forEach(c => toggleC(c.dataset.p, false));
        let placed = 0, level = true, marked = true; const texts = [];
        all.forEach(([p, n]) => { const panes = card(p).querySelectorAll('.sp .pane'), k = n.s === 'old' ? 0 : 1, rows = [...panes[k].querySelectorAll('tr')], twin = [...panes[1 - k].querySelectorAll('tr')];
          const last = rows.findIndex(r => r.dataset.ln === String(n.b)), note = rows[last + 1], ghost = twin[last + 1];
          if (last < 0 || !note || !note.classList.contains('anote') || note.classList.contains('an-ghost') || !note.textContent.includes(n.t)) return;
          placed++; texts.push(n.t);
          if (!ghost || !ghost.classList.contains('an-ghost') || getComputedStyle(ghost.querySelector('span')).visibility !== 'hidden' || Math.abs(note.getBoundingClientRect().height - ghost.getBoundingClientRect().height) > 1.5
            || Math.abs(note.getBoundingClientRect().top - ghost.getBoundingClientRect().top) > 1.5) level = false;
          for (let ln = n.a; ln <= n.b; ln++) { const r = rows.find(x => x.dataset.ln === String(ln)); if (!r || !r.classList.contains('an-ln')) marked = false; } });
        const even = [...document.querySelectorAll('.fc .sp')].every(sp => { const [a, b] = sp.querySelectorAll('.pane'); return a.querySelectorAll('tr').length === b.querySelectorAll('tr').length && Math.abs(a.querySelector('table').offsetHeight - b.querySelector('table').offsetHeight) < 3; });
        const note = document.querySelector('tr.anote:not(.an-ghost)'), was = note.querySelector('td:not(.ln)').className;
        note.querySelector('td:not(.ln)').click();
        CM.items.push({ id: 'vcan', kind: 'file', part: 'diff', path: all[0][0], quote: '', text: 'vc beside a note', label: '', t: Date.now(), state: 'open' }); cmChanged();
        const fb = cmFeedback(); CM.items = CM.items.filter(x => x.id !== 'vcan'); cmChanged();
        return { n: all.length, placed, level, marked, even, still: note.querySelector('td:not(.ln)').className === was && !note.dataset.ln && !note.dataset.path, leak: texts.some(t => fb.includes(t)), stored: texts.some(t => (localStorage.getItem(CM_KEY) || '').includes(t)) };
      });
      if (an) {
        log(an.placed === an.n && an.marked && an.level && an.even, `each of the agent's ${an.n} notes stands under the lines it is about, which are marked; the other side holds an unseen copy, so both sides stay level`);
        log(an.still && !an.leak && !an.stored, 'a note is read-only: it is not a line that can be wrapped or commented, and it is neither in the copied feedback nor in the stored comments');
      }
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    // A changed picture is shown before and after, side by side, each with its size; a version not embedded says why
    {
      const im = await page.evaluate(async () => {
        const I = QX.images || {}, paths = Object.keys(I); if (!paths.length) return null;
        document.querySelectorAll('.fc.iscol').forEach(c => toggleC(c.dataset.p, false));
        await Promise.all([...document.querySelectorAll('.imv img')].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })));
        await new Promise(r => setTimeout(r, 100));
        let ok = true, drawn = 0, notes = 0, absent = 0; const sizes = [];
        paths.forEach(p => { const c = card(p), figs = c.querySelectorAll('.imvs .imv'); if (figs.length !== 2 || c.querySelector('.file-msg')) { ok = false; return; }
          [['before', 'Before'], ['after', 'After']].forEach(([k, name], n) => { const v = I[p][k], f = figs[n], img = f.querySelector('img'), cap = f.querySelector('figcaption').textContent;
            if (!cap.startsWith(name)) ok = false;
            if (v && v.uri) { if (!img || !img.naturalWidth || img.src !== v.uri || !/ px$/.test(cap) || getComputedStyle(img).display === 'none') ok = false; else { drawn++; sizes.push(img.naturalWidth + 'x' + img.naturalHeight); } }
            else if (v) { if (img || f.querySelector('.imv-none').textContent !== v.note) ok = false; notes++; }
            else { if (img || !f.querySelector('.imv-none')) ok = false; absent++; } });
          const b = figs[0].getBoundingClientRect(), a = figs[1].getBoundingClientRect(); if (innerWidth > 800 && !(Math.abs(a.top - b.top) < 2 && a.left > b.right)) ok = false; });
        return { n: paths.length, ok, drawn, notes, absent, sizes: sizes.join(', '), inline: document.querySelectorAll('.imvs svg').length };
      });
      if (im) log(im.ok && im.inline === 0 && im.drawn + im.notes + im.absent === im.n * 2,
        `each changed picture shows its version before and after side by side, through image elements only (${im.n} pictures: ${im.drawn} drawn at ${im.sizes}; ${im.notes} named and not shown; ${im.absent} absent on one side)`);
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    // Hunks that hold no real edit carry a label; a button hides their lines, never by default, and a jump shows them again
    {
      const hk = await page.evaluate(() => {
        const K = QX.hk || {}, want = Object.values(K).reduce((s, ks) => s + ks.filter(Boolean).length, 0), b = document.getElementById('hkbtn');
        let badges = 0, right = true, rows = 0;
        Object.keys(K).forEach(p => { const c = card(p); c.querySelectorAll('.sp .pane:first-child tr.hunk').forEach((tr, i) => { const k = K[p][i], bd = tr.querySelector('.hkb');
          if (!!k !== !!bd || (k && bd.title !== k.t)) right = false; if (bd) badges++; }); rows += c.querySelectorAll('.sp .pane:first-child tr.hkrow').length; });
        const other = document.querySelectorAll('.fc tr.hkrow').length, shown = () => [...document.querySelectorAll('.fc:not(.iscol) tr.hkrow')].filter(r => r.offsetParent !== null).length;
        const before = { hide: document.body.classList.contains('hk-hide'), shown: shown(), text: b.textContent, hidden: b.hidden };
        document.querySelectorAll('.fc.iscol').forEach(c => toggleC(c.dataset.p, false));
        const open = shown(); hkSet(); const after = { shown: shown(), text: b.textContent, plain: [...document.querySelectorAll('.fc tr[data-ln]:not(.hkrow)')].filter(r => r.offsetParent !== null).length };
        const first = document.querySelector('.fc .sp .pane:nth-child(2) tr.hkrow[data-ln]'), p = first ? first.dataset.path : '';
        return { want, badges, right, rows, other, before, open, after, kinds: Object.values(K).flat().filter(Boolean).map(k => k.k).join(','), go: first ? [p, +first.dataset.ln] : null };
      });
      if (hk.want) {
        log(hk.badges === hk.want && hk.right && hk.rows > 0 && !hk.before.hide && !hk.before.hidden && hk.before.text === 'Hide moves and reformatting (' + hk.want + ')',
          `hunks that are only a move, only spacing or one word replaced are labelled as the build found them (${hk.kinds}), and nothing is hidden to start with`);
        log(hk.open > 0 && hk.after.shown === 0 && hk.after.plain > 0 && hk.after.text === 'Show moves and reformatting (' + hk.want + ')', `the button hides the lines of those hunks and no other line (${hk.open} lines hidden, ${hk.after.plain} still shown)`);
        if (hk.go) { await page.evaluate(([p, ln]) => fnGo(p, ln), hk.go); await wait(300);
          log(await page.evaluate(([p, ln]) => { const tr = card(p).querySelector('.sp .pane:nth-child(2) tr[data-ln="' + ln + '"]'); return !document.body.classList.contains('hk-hide') && tr.offsetParent !== null; }, hk.go), 'going to a line inside a hidden hunk shows the hidden lines again'); }
        await page.evaluate(() => { hkSet(false); window.scrollTo(0, 0); });
      }
    }
    // The functions a file's hunks change, and their callers: shown as the build found them, with the limits said
    {
      const fn = await page.evaluate(() => {
        const F = QX.fns || {}, paths = Object.keys(F), want = { labels: 0, fns: 0, callers: 0 }, got = { labels: 0, fns: 0, callers: 0 }; let plain = true, notes = true, inDiff = null;
        paths.forEach(p => { const c = card(p); if (!c) return;
          want.labels += F[p].hunks.filter(Boolean).length; got.labels += c.querySelectorAll('.sp .pane:first-child tr.hunk .hfn').length;
          F[p].hunks.forEach((lab, i) => { const row = c.querySelectorAll('.sp .pane:first-child tr.hunk')[i]; if (!row) return;
            if (lab ? row.querySelector('.hfn').textContent !== lab : !/^@@ /.test(row.querySelector('td:not(.ln)').textContent)) plain = false; });
          want.fns += F[p].list.length; got.fns += c.querySelectorAll('.fnl li').length;
          F[p].list.forEach(f => { want.callers += (f.callers || []).length; (f.callers || []).forEach(([cp, ln]) => { if (!inDiff && fmap[cp] && card(cp).querySelector('.sp .pane:nth-child(2) tr[data-ln="' + ln + '"]')) inDiff = [cp, ln]; }); });
          got.callers += c.querySelectorAll('.fnl li a, .fnl li > span:not(.fn-from):not(.fn-none)').length;
          if (F[p].list.length && !/keyword and indentation/.test((c.querySelector('.fn-note') || { textContent: '' }).textContent)) notes = false;
          if (F[p].list.length && QX.callers !== /by name across the repo/.test(c.querySelector('.fn-note').textContent)) notes = false; });
        return { n: paths.length, want, got, plain, notes, inDiff, searched: !!QX.callers };
      });
      if (fn.n) {
        log(JSON.stringify(fn.want) === JSON.stringify(fn.got) && fn.plain && fn.notes,
          `hunks carry the function they change, and each file lists its changed functions with their callers and a note on the limits (${fn.got.labels} labels, ${fn.got.fns} functions, ${fn.got.callers} callers; callers searched: ${fn.searched})`);
        if (fn.inDiff) {
          await page.evaluate(([p, ln]) => { toggleC(p, true); const li = [...document.querySelectorAll('.fnl li a')].find(a => a.textContent === p + ':' + ln); li.closest('details').open = true; li.click(); }, fn.inDiff); await wait(400);
          log(await page.evaluate(([p, ln]) => { const c = card(p), tr = c.querySelector('.sp .pane:nth-child(2) tr[data-ln="' + ln + '"]'), b = tr.getBoundingClientRect(); return !c.classList.contains('iscol') && b.top > 0 && b.bottom < innerHeight && tr.classList.contains('fn-hit'); }, fn.inDiff),
            `a caller that is in this change is a link: it opens its file and goes to the line (${fn.inDiff[0]}:${fn.inDiff[1]})`);
          await page.evaluate(() => window.scrollTo(0, 0));
        }
      }
    }
    // Search inside the diff: "f" goes to the box, the count is exact, Enter walks the matches and opens a collapsed file
    {
      const word = await page.evaluate(() => { const count = q => ordered.reduce((n, p) => { let inH = false; fmap[p].lines.forEach(l => { if (l.startsWith('@@')) { inH = true; return; } if (!inH || !/^[-+ ]/.test(l)) return;
          const s = l.slice(1).toLowerCase(); for (let at = s.indexOf(q); at >= 0; at = s.indexOf(q, at + q.length)) n++; }); return n; }, 0);
        const q = ['listener', 'return', 'batch', 'the'].find(w => count(w) > 2) || ''; return { q, n: q ? count(q) : 0 }; });
      if (word.q) {
        const ctrl = await page.evaluate(() => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true, cancelable: true })) && document.activeElement.id !== 'dsearch');
        await page.evaluate(() => { document.activeElement.blur(); window.scrollTo(0, 0); }); await page.keyboard.press('f'); await wait(150);
        const focused = await page.evaluate(() => document.activeElement.id === 'dsearch');
        await page.keyboard.type(word.q.toUpperCase()); await wait(400);
        const ds = () => page.evaluate(() => { const cur = CSS.highlights.get('ds-cur'), r = cur && [...cur][0], b = r ? r.getBoundingClientRect() : null;
          return { count: document.getElementById('dcount').textContent, all: (CSS.highlights.get('ds') || { size: 0 }).size, cur: cur ? cur.size : 0, text: r ? r.toString() : '', seen: !!b && b.top > 0 && b.bottom < innerHeight && b.width > 0, at: dsAt, n: dsHits.length,
            col: dsAt >= 0 ? card(dsHits[dsAt].p).classList.contains('iscol') : null }; });
        const typed = await ds();
        await page.keyboard.press('Enter'); await wait(400); const first = await ds();
        await page.evaluate(() => toggleC(dsHits[dsHits.length - 1].p, true)); await page.keyboard.press('Shift+Enter'); await wait(400); const last = await ds();
        log(ctrl && focused && typed.count === word.n + ' matches' && typed.n === word.n && typed.all >= word.n && first.count === '1 of ' + word.n && first.cur >= 1 && first.text.toLowerCase() === word.q && first.seen,
          `Ctrl+F is left to the browser; "f" goes to the diff search; "${word.q}" in capitals finds all ${word.n} matches counted in the raw diff; Enter goes to the first and shows it (${typed.count}, ${first.count})`);
        log(last.count === word.n + ' of ' + word.n && last.col === false && last.seen && last.text.toLowerCase() === word.q, `Shift+Enter from the first match wraps to the last, and a collapsed file opens to show it (${last.count})`);
        // every match can be read once it is reached, also one that stood in the cut-off end of a long line
        let unread = 0, unfolded = 0;
        for (let i = 0; i < word.n; i++) { await page.keyboard.press('Enter'); await wait(120); const s = await page.evaluate(() => { const r = [...CSS.highlights.get('ds-cur')][0], b = r.getBoundingClientRect(), td = r.startContainer.parentElement.closest('td'), t = td.getBoundingClientRect();
          return { ok: b.width > 0 && b.left >= t.left - 1 && b.right <= t.right + 1 && b.top > 0 && b.bottom < innerHeight, open: td.classList.contains('expanded') }; }); if (!s.ok) unread++; if (s.open) unfolded++; }
        log(unread === 0, `each of the ${word.n} matches stands inside its cell and on screen when it is reached; ${unfolded} long lines were unfolded for that`);
        await page.keyboard.press('Escape'); await wait(300); const gone = await ds();
        await page.evaluate(() => { document.getElementById('dsearch').value = 'zz-no-such-text'; dsFind(); }); const none = await ds();
        await page.evaluate(() => { document.getElementById('dsearch').value = ''; dsFind(); window.scrollTo(0, 0); });
        log(gone.count === '' && gone.all === 0 && gone.cur === 0 && none.count === 'No match', 'Escape empties the search and removes its marks; a text that is not in the diff says "No match"');
      }
    }
    // Syntax colours: applied when the highlighter is there, the text and the word marks unchanged; plain without it
    await wait(1200);
    const hl = await page.evaluate(() => {
      if (!window.hljs) return null;
      document.querySelectorAll('.fc').forEach(c => hlCard(c));
      const cards = [...document.querySelectorAll('.fc')].filter(c => c.querySelector('.sp'));
      const col = cards.filter(c => c.querySelector('table.dt [class^="hljs-"]')).map(c => c.dataset.p.split('.').pop());
      let same = true, marks = true;
      cards.forEach(c => { const S = dsRows(c.dataset.p); c.querySelectorAll('.sp .pane').forEach((pane, k) => {
        const rows = (k ? S.R : S.L), trs = pane.querySelectorAll('tr');
        rows.forEach((r, i) => { if (r.t === 'h' || r.t === 'n') return; const td = trs[i].querySelector('td:not(.ln)'), txt = td.textContent === ' ' ? '' : td.textContent;
          if (txt !== r.c) same = false;
          // a mark that crosses two colours is in two pieces, so the marked text is compared as one string
          if ((r.w || []).map(([a, b]) => r.c.slice(a, b)).join('') !== [...td.querySelectorAll('.wm')].map(x => x.textContent).join('')) marks = false; }); }); });
      const kw = document.querySelector('table.dt .hljs-keyword'), plain = document.querySelector('table.dt tr:not(.hunk) td:not(.ln)');
      return { version: hljs.versionString, col, same, marks, differs: !!kw && getComputedStyle(kw).color !== getComputedStyle(plain).color, cut: hlLines('<span class="a">x\n<span class="b">y</span>\nz</span>!').join('~') };
    });
    if (hl) {
      log(hl.col.length > 0 && hl.differs && hl.same && hl.marks, `the diff has syntax colours (highlight.js ${hl.version}; files coloured: ${hl.col.join(', ')}); every line reads the same as before and keeps its word marks`);
      log(hl.cut === '<span class="a">x</span>~<span class="a"><span class="b">y</span></span>~<span class="a">z</span>!', 'a coloured stretch that runs over several lines is cut into lines that each keep its colour');
    } else console.log('NOTE\thighlight.js was not loaded (no network?); syntax colours not checked');
    {
      const off = await page.context().newPage(); const errs = [];
      off.on('pageerror', e => errs.push(String(e.message || e)));
      await off.route('**/highlight.min.js', r => r.abort());
      await off.goto(page.url().split('#')[0] + '#diff'); await off.waitForTimeout(1500);
      const plain = await off.evaluate(() => ({ hl: !!window.hljs, rows: document.querySelectorAll('.fc table.dt tr[data-ln]').length, coloured: document.querySelectorAll('table.dt [class^="hljs-"]').length, marks: document.querySelectorAll('table.dt .wm').length }));
      await off.close();
      log(!plain.hl && plain.rows > 0 && plain.coloured === 0 && plain.marks > 0 && !errs.length, `without the highlighter the diff still renders, uncoloured, with its word marks and no page error (${plain.rows} rows)`);
    }
    const addRow = await page.$('.fc:not(.iscol) tr.add td:not(.ln)');
    if (addRow) {
      const addBg = await addRow.evaluate(t => getComputedStyle(t).backgroundColor);
      const ctxBg = await page.$eval('tr:not(.add):not(.del):not(.hunk) td:not(.ln)', t => getComputedStyle(t).backgroundColor);
      log(addBg !== ctxBg, 'added rows are coloured apart from context rows');
      await addRow.click(); const on = await addRow.evaluate(t => t.classList.contains('expanded'));
      await addRow.click(); const off = await addRow.evaluate(t => !t.classList.contains('expanded'));
      log(on && off, 'clicking a cell wraps the row, clicking again truncates it');
    }
    await page.click('.nvbtn:nth-child(2)'); await wait(200);
    log(await page.$$eval('.tdir', d => d.length) > 0 || info.files === 1, 'tree view shows directories');
    await page.screenshot({ path: path.join(out, '6-diff.png') });
    const w0 = await page.$eval('#nav', n => n.getBoundingClientRect().width);
    const grip = async () => page.$eval('#nav-resizer', e => { const b = e.getBoundingClientRect(); return [b.x + 2, b.y + 100]; });
    let [x, y] = await grip();
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 120, y, { steps: 5 }); await page.mouse.up();
    const w1 = await page.$eval('#nav', n => n.getBoundingClientRect().width);
    await page.reload(); await wait(1000);
    const w2 = await page.$eval('#nav', n => n.getBoundingClientRect().width);
    [x, y] = await grip(); await page.mouse.dblclick(x, y);
    const w3 = await page.$eval('#nav', n => n.getBoundingClientRect().width);
    log(w1 > w0 && Math.abs(w2 - w1) < 2 && Math.abs(w3 - w0) < 2, `sidebar resizes (${w0} to ${w1}), persists (${w2}), resets (${w3})`);
    let copied = 0;
    for (const which of ['base', 'head']) {
      await page.click('#hcp-' + which); await wait(200);
      if ((await page.evaluate(() => navigator.clipboard.readText().catch(() => ''))).length) copied++;
    }
    log(copied === 2, `both hash pills copy (${copied}/2)`);
    // Comments on a diff line, a range of lines, and a file
    await page.evaluate(() => { CM.items = []; cmSave(); cmResolve(); cmDraw(); });
    const rowAt = await page.evaluate(() => { const r = document.querySelector('.fc:not(.iscol):not(.hide) .sp .pane:nth-child(2) tr.add[data-ln]'); if (!r) return null;
      r.scrollIntoView({ block: 'center' }); window.__r = r; return true; });
    if (rowAt) {
      await wait(300);
      const rb = await page.evaluate(() => { const b = window.__r.cells[1].getBoundingClientRect(); return { x: b.left + 30, y: b.top + b.height / 2 }; });
      await page.mouse.move(rb.x - 5, rb.y); await page.mouse.move(rb.x, rb.y); await wait(200);
      log(await page.evaluate(() => { const b = document.getElementById('cm-blk-add'); if (b.hidden) return false; const k = b.getBoundingClientRect(), r = window.__r.getBoundingClientRect();
        return Math.abs((k.top + k.bottom) / 2 - (r.top + r.bottom) / 2) < 1.5; }), 'the pointer over a diff line offers a comment button level with it');
      await page.click('#cm-blk-add'); await wait(200);
      const title = await page.evaluate(() => (document.querySelector('.cm-card .cm-k') || {}).textContent || '');
      await page.keyboard.type('line comment'); await page.keyboard.press('Enter'); await wait(250);
      const lc = await page.evaluate(() => { const c = CM.items[0], r = window.__r; return !!c && { kind: c.kind, side: c.side, okLn: c.ln === +r.dataset.ln && c.path === r.dataset.path,
        okText: c.lines.length === 1 && c.lines[0] === r.cells[1].textContent.replace(/^\u00a0$/, ''), row: r.classList.contains('cm-dl'), mark: !!r.querySelector('.cm-dmark'), table: getComputedStyle(r).display === 'table-row' && getComputedStyle(r.cells[1]).display === 'table-cell', wrapped: r.cells[1].classList.contains('expanded') }; });
      log(/, line \d+, new side$/.test(title) && lc && lc.kind === 'line' && lc.side === 'new' && lc.okLn && lc.okText && lc.row && lc.mark && lc.table,
        `a diff line comment stores file, side, line and text, and marks the line: ${title}`);
      await page.click('.cm-dmark'); await wait(200);
      log(await page.evaluate(() => { const t = document.querySelector('.cm-card textarea'); return !!t && t.value === 'line comment' && window.__r.classList.contains('cm-dl-on') && window.__r.cells[1].classList.contains('expanded') === false; }) || (lc && lc.wrapped),
        'the marker in the line-number cell reopens the comment and does not wrap the row');
      await page.keyboard.press('Escape'); await wait(100);
      const moved = await page.evaluate(() => { const c = CM.items[0], at = c.ln; c.ln = 987654; cmResolve();
        const out = { state: c._state, ln: c._ln, at }; c.lines = ['a line that is not in this diff']; cmResolve(); out.gone = c._state; return out; });
      log((moved.state === 'moved' && moved.ln === moved.at || moved.state === 'notfound') && moved.gone === 'notfound',
        `a line comment whose number is stale is re-found by its text or not placed (${moved.state}); changed text is not found`);
      await page.evaluate(() => { CM.items = []; cmSave(); cmResolve(); cmDraw(); });
      const two = await page.evaluate(() => { const rows = [...window.__r.parentElement.querySelectorAll('tr[data-ln]')], i = rows.indexOf(window.__r), n = rows[i + 1];
        if (!n || n.previousElementSibling !== window.__r) return false;
        const r = document.createRange(); r.setStart(window.__r.cells[1], 0); r.setEnd(n.cells[1], n.cells[1].childNodes.length);      // a cell may start with a marked or coloured span
        const s = getSelection(); s.removeAllRanges(); s.addRange(r); document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })); return true; });
      if (two) {
        await wait(250); await page.click('#cm-add'); await wait(200);
        log(await page.evaluate(() => / lines \d+ to \d+, new side$/.test((document.querySelector('.cm-card .cm-k') || {}).textContent || '') && document.querySelectorAll('tr.cm-dl-on').length === 2),
          'a selection across two diff lines comments on that range of lines');
        await page.evaluate(() => { document.querySelector('.cm-card .cm-cancel').click(); getSelection().removeAllRanges(); });
      }
      const across = await page.evaluate(() => { const body = [...document.querySelectorAll('.fc .sp .pane:nth-child(2) tbody')].find(x => x.querySelectorAll('tr.hunk').length > 1);
        if (!body) return null;
        const h2 = body.querySelectorAll('tr.hunk')[1]; let a = h2.previousElementSibling, z = h2.nextElementSibling;
        while (a && !a.dataset.ln) a = a.previousElementSibling; while (z && !z.dataset.ln) z = z.nextElementSibling;
        if (!a || !z) return null;
        const r = document.createRange(); r.setStart(a.cells[1].firstChild, 0); r.setEnd(z.cells[1].firstChild, 1);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r); const got = cmReadDiffSelection(s); s.removeAllRanges();
        if (!got) return { ok: false };
        const c = Object.assign({ id: 'x', text: 't', t: 1, state: 'open' }, got); delete c.el; delete c.pieces; cmResolveDiff(c);
        return { ok: got.ln === +a.dataset.ln && got.ln2 === +z.dataset.ln && got.lines.length === 2 && c._state === 'anchored' && c._ln2 === got.ln2, gap: got.ln2 - got.ln }; });
      if (across) log(across.ok && across.gap > 1, `a selection across two hunks comments on the lines of both (${across.gap} lines apart)`);
      const wasCol = await page.evaluate(() => window.__r.closest('.fc').classList.contains('iscol'));
      await page.evaluate(() => window.__r.closest('.fc').querySelector('.cbtn').click()); await wait(200);
      const ft = await page.evaluate(() => (document.querySelector('.cm-card .cm-k') || {}).textContent || '');
      await page.keyboard.type('file comment'); await page.keyboard.press('Enter'); await wait(250);
      log(await page.evaluate(([ft, wasCol]) => { const fc = window.__r.closest('.fc'), c = CM.items[0];
        return ft === 'File ' + fc.dataset.p && !!c && c.kind === 'file' && c.path === fc.dataset.p && !!fc.querySelector('.fh .cm-fmark') && fc.querySelector('.cbtn').hidden && fc.classList.contains('iscol') === wasCol; }, [ft, wasCol]),
        'the file header button comments on the file and leaves the card open');
      await page.evaluate(() => { CM.items = []; cmSave(); cmResolve(); cmDraw(); });
    }
    log(await page.evaluate(() => !document.querySelector('.notearea') && !document.getElementById('copy-notes') && !!document.getElementById('copy-feedback')), 'the per-file note box and Copy notes are replaced by Copy feedback');
    const leftOut = await page.evaluate(() => (QX.excluded || []).length);
    if (leftOut) log(await page.$$eval('#excluded-note li', n => n.length) === leftOut, `Diff review names all ${leftOut} files left out`);
  }
  log(await page.$('#verified') !== null, 'Brief has the verified section');

  // 7. Phone width, for each part present
  // Layout of the written content, part by part: text cut off by its own box, a block that runs out of the column,
  // and text that another element covers. The Diff review part is left out: it cuts long lines on purpose.
  // The detectors are first shown three planted faults, and must find exactly those.
  const installLayout = p => p.evaluate(() => { window.__qxLayout = () => {
    const chrome = '.part-bar, .top-tools, .rev-bar, #cm-panel, #toast, .cm-card, #cm-add, .cm-badd';
    const out = { clipped: [], escaped: [], covered: [], blocks: 0 };
    const name = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + ' "' + el.textContent.trim().replace(/\s+/g, ' ').slice(0, 40) + '"';
    const part = document.querySelector('.part-panel.active'), root = part.querySelector('.page') || part;
    const box = root.getBoundingClientRect(), cs0 = getComputedStyle(root), left = box.left + parseFloat(cs0.paddingLeft), right = box.right - parseFloat(cs0.paddingRight);
    // inside something that scrolls or cuts on purpose, a wide block is that container's business
    const held = el => { for (let a = el.parentElement; a && a !== root; a = a.parentElement) if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(a).overflowX)) return true; return false; };
    const blocks = [...root.querySelectorAll('p, li, td, th, h1, h2, h3, h4, pre, table, img, figcaption, blockquote, dt, dd')].filter(el => el.offsetParent !== null && !el.closest('.dg, .rev-bar, .cm-layer, svg'));
    blocks.forEach(el => {
      out.blocks++;
      const cs = getComputedStyle(el), r = el.getBoundingClientRect();
      if (el.textContent.trim() && /(hidden|clip)/.test(cs.overflowX + ' ' + cs.overflowY) && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) out.clipped.push(name(el));
      if (!held(el) && r.width > 0 && (r.right > right + 2 || r.left < left - 2)) out.escaped.push(name(el) + ' by ' + Math.round(Math.max(r.right - right, left - r.left)) + 'px');
    });
    blocks.filter(el => /^(P|LI|TD|TH|H1|H2|H3|H4|FIGCAPTION|DT|DD)$/.test(el.tagName) && el.textContent.trim()).slice(0, 400).forEach(el => {
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect(); if (r.width < 4 || r.height < 4) return;
      const pts = [[0.5, 0.5], [0.15, 0.3], [0.85, 0.3], [0.15, 0.7], [0.85, 0.7]].map(([fx, fy]) => [r.left + r.width * fx, r.top + r.height * fy]).filter(([x, y]) => x >= 0 && y >= 0 && x < innerWidth && y < innerHeight);
      const hid = pts.filter(([x, y]) => { const top = document.elementFromPoint(x, y); return top && !el.contains(top) && !top.contains(el) && !top.closest(chrome); }).length;
      if (pts.length >= 3 && hid >= pts.length - 1) out.covered.push(name(el));      // nearly all of it, not a corner
    });
    window.scrollTo(0, 0);
    return out;
  }; });
  const layoutOf = (p, key) => p.evaluate(key => { switchPart(key); return window.__qxLayout(); }, key);
  const layoutParts = (await page.evaluate(() => PART_KEYS.slice())).filter(k => k !== 'diff');
  await installLayout(page);
  {
    await page.evaluate(k => switchPart(k), layoutParts[0]); await wait(200);
    const planted = await page.evaluate(() => { const root = document.querySelector('.part-panel.active .page'), w = document.createElement('div'); w.id = 'vc-faults';
      w.innerHTML = '<p id="vc-clip" style="width:90px;overflow:hidden;white-space:nowrap">A sentence much longer than ninety pixels can hold</p><p id="vc-esc" style="width:3000px">A block far wider than the column</p>'
        + '<div style="position:relative"><p id="vc-cov">A sentence that lies under something else</p><div style="position:absolute;inset:0;background:#fff"></div></div><p id="vc-fine">A plain sentence that is fine.</p>';
      root.appendChild(w); const r = window.__qxLayout(); w.remove();
      const only = (list, id) => list.filter(x => x.includes('#vc-')).length === 1 && list.some(x => x.includes(id)); return { clip: only(r.clipped, '#vc-clip'), esc: only(r.escaped, '#vc-esc'), cov: only(r.covered, '#vc-cov') }; });
    log(planted.clip && planted.esc && planted.cov, `the three layout detectors find a planted fault each and nothing else among the planted blocks (cut-off text ${planted.clip}, block out of the column ${planted.esc}, covered text ${planted.cov})`);
    const found = [];
    for (const k of layoutParts) { const r = await layoutOf(page, k); await wait(k === 'maps' ? 500 : 100); found.push(Object.assign(k === 'maps' ? await layoutOf(page, k) : r, { k })); }
    const say = kind => found.filter(r => r[kind].length).map(r => r.k + ': ' + r[kind].slice(0, 3).join('; ')).join(' | ');
    const n = found.reduce((s, r) => s + r.blocks, 0);
    log(found.every(r => !r.clipped.length), `no text is cut off by its own box (${n} blocks in ${layoutParts.join(', ')})` + (say('clipped') ? ': ' + say('clipped') : ''));
    log(found.every(r => !r.escaped.length), 'no block runs out of its column' + (say('escaped') ? ': ' + say('escaped') : ''));
    log(found.every(r => !r.covered.length), 'no text is covered by another element' + (say('covered') ? ': ' + say('covered') : ''));
    await page.evaluate(() => { switchPart(PART_KEYS[0]); window.scrollTo(0, 0); });
  }
  const phone = await browser.newPage({ viewport: { width: 390, height: 800 } }); watch(phone);
  await routeLibs(phone);
  for (const part of info.parts) {
    await phone.goto(url + '#' + part); await wait(1500);
    const sw = await phone.evaluate(() => document.documentElement.scrollWidth);
    log(sw <= 391, `no sideways page scroll at 390px on ${part} (${sw}px)`);
  }
  await phone.screenshot({ path: path.join(out, '7-phone.png') });
  // A refusal by the content security policy is a console error, so it is among the page errors below.
  const csp = await page.evaluate(() => (document.querySelector('meta[http-equiv="Content-Security-Policy"]') || { content: '' }).content);
  log(/default-src 'none'/.test(csp) && /connect-src 'none'/.test(csp) && !/unsafe-eval/.test(csp), 'the page declares a content security policy that allows nothing by default, no network call and no evaluated code; every check above ran under it');
  log(errors.length === 0, 'no page errors' + (errors.length ? ': ' + errors.slice(0, 4).join(' | ') : ''));
  await browser.close();
  console.log(`\nScreenshots in ${out}. Look at them: a check can pass while the page still looks wrong.`);
  process.exit(bad ? 1 : 0);
})().catch(e => { console.error('ERROR\t' + e.message); process.exit(2); });
