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
 *   1. Provenance strip is on every part present. Brief loads; every Mermaid diagram in
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
 *      counts; state survives a reload under qexplain-change-diff-<slug>; j and m work; a
 *      type filter narrows the list; added rows are coloured; clicking a cell wraps
 *      and unwraps it; tree view shows directories; the sidebar resizes, persists,
 *      and resets on double-click; both hash pills copy; Copy notes exports a note with
 *      its file path; every file left out is named. A summary row opens its file here.
 *   7. At 390px wide no part scrolls the page sideways. No page errors.
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
const stem = path.basename(file).replace(/\.html?$/i, '');
const storeKey = 'qexplain-change-diff-' + stem.toLowerCase().replace(/_/g, '-');

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
  log(has('brief'), `parts present: ${info.parts.join(', ')}`);

  // 1. Provenance on every part, and Mermaid in the brief
  for (const p of info.parts) {
    await page.evaluate(k => switchPart(k), p); await wait(400);
    log(await page.$(`#part-${p} .prov`) !== null, `provenance strip on ${p}`);
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
    const noteText = 'visual-check note';
    await page.evaluate(() => { const b = document.querySelector('.fbtn'); if (b) b.click(); });
    const noteBox = await page.$('.fc:not(.iscol):not(.hide) .notearea');
    if (noteBox) {
      await noteBox.fill(noteText);
      await page.click('#copy-notes'); await wait(200);
      const notes = await page.evaluate(() => navigator.clipboard.readText().catch(() => ''));
      const cardPath = await noteBox.evaluate(t => t.closest('.fc').dataset.p);
      log(notes.includes(noteText) && notes.includes(cardPath), 'Copy notes exports the note with its file path');
      await noteBox.fill('');
    } else log(false, 'Copy notes: no open file card to write a note on');
    const leftOut = await page.evaluate(() => (QX.excluded || []).length);
    if (leftOut) log(await page.$$eval('#excluded-note li', n => n.length) === leftOut, `Diff review names all ${leftOut} files left out`);
  }
  log(await page.$('#verified') !== null, 'Brief has the verified section');

  // 7. Phone width, for each part present
  const phone = await browser.newPage({ viewport: { width: 390, height: 800 } }); watch(phone);
  await routeLibs(phone);
  for (const part of info.parts) {
    await phone.goto(url + '#' + part); await wait(1500);
    const sw = await phone.evaluate(() => document.documentElement.scrollWidth);
    log(sw <= 391, `no sideways page scroll at 390px on ${part} (${sw}px)`);
  }
  await phone.screenshot({ path: path.join(out, '7-phone.png') });
  log(errors.length === 0, 'no page errors' + (errors.length ? ': ' + errors.slice(0, 4).join(' | ') : ''));
  await browser.close();
  console.log(`\nScreenshots in ${out}. Look at them: a check can pass while the page still looks wrong.`);
  process.exit(bad ? 1 : 0);
})().catch(e => { console.error('ERROR\t' + e.message); process.exit(2); });
