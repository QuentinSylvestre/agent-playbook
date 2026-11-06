#!/usr/bin/env node
/*
 * Visual check for a /qexplain artifact built from assets/template.html.
 *
 * The static validator cannot see whether Cytoscape drew a graph, Mermaid parsed a
 * diagram, or the diff review behaves. This script opens the artifact in a real
 * browser, exercises it, prints one OK/BAD line per check, and saves screenshots
 * for you to look at.
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
 * not resolvable). Without them, run the same checks by hand through a Playwright MCP:
 *   1. Narrative loads. Each map view renders: graphs have nodes on screen, sequence
 *      views have an SVG and no Mermaid syntax error.
 *   2. Every tour step changes the caption and highlights something.
 *   3. `#maps/<view>` and `#diff` hashes open the right part on load.
 *   4. Mermaid note text stays inside its box.
 *   5. The theme toggle re-themes the page and persists.
 *   6. Diff review: sidebar lists every file; Mark reviewed collapses the card and
 *      counts; state survives a reload under qexplain-diff-<slug>; j and m work; a
 *      type filter narrows the list; added rows are coloured; clicking a cell wraps
 *      and unwraps it; tree view shows directories; the sidebar resizes, persists,
 *      and resets on double-click; both hash pills copy; Copy notes exports a note with
 *      its file path; every file left out is named; the verified section exists.
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
const out = opt('--out') || fs.mkdtempSync(path.join(os.tmpdir(), 'qexplain-shots-'));
fs.mkdirSync(out, { recursive: true });
const libs = opt('--libs');
const url = require('url').pathToFileURL(path.resolve(file)).href;
const stem = path.basename(file).replace(/\.html?$/i, '');
const storeKey = 'qexplain-diff-' + stem.toLowerCase().replace(/_/g, '-');

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
  await page.goto(url); await wait(800);
  await page.screenshot({ path: path.join(out, '1-narrative.png') });

  const QX = await page.evaluate(() => ({ views: QX.views.map(v => ({ key: v.key, kind: v.kind, tour: v.tour || [] })), files: (QX.rawDiff.match(/^diff --git /gm) || []).length }));

  // 1-2. Maps and tours
  await page.click('[data-part="maps"]'); await wait(1500);
  for (const v of QX.views) {
    await page.click(`[data-view="${v.key}"]`); await wait(v.kind === 'sequence' ? 2500 : 1200);
    if (v.kind === 'graph') {
      const drawn = await page.evaluate(k => { const cy = window._cy[k]; if (!cy || !cy.nodes().length) return false;
        const bb = cy.nodes().renderedBoundingBox(), w = cy.width(), h = cy.height();
        return bb.w > 0 && bb.x1 < w && bb.x2 > 0 && bb.y1 < h && bb.y2 > 0; }, v.key);
      log(drawn, `map ${v.key}: graph drawn on screen`);
    } else if (v.kind === 'sequence') {
      const ok = await page.evaluate(k => { const s = document.querySelector('#mermaid-' + k + ' svg'); return !!s && !/Syntax error/i.test(s.textContent); }, v.key);
      log(ok, `map ${v.key}: sequence diagram rendered`);
    }
    await page.screenshot({ path: path.join(out, `2-map-${v.key}.png`) });
    if (v.tour.length) {
      let ok = true;
      for (let i = 0; i < v.tour.length; i++) {
        if (i) { await page.click(`#view-${v.key} .tour-box button:last-child`); await wait(400); }
        const caption = await page.textContent('#tour-caption-' + v.key);
        const lit = await page.evaluate(k => {
          const cy = window._cy[k];
          if (cy) return cy.$('.highlighted').length;
          return document.querySelectorAll('#view-' + k + ' .highlighted, #view-' + k + ' .seq-highlight').length;
        }, v.key);
        const step = v.tour[i];
        const wants = (step.highlight && step.highlight.length) || step.scrollTo;
        if (caption !== step.caption || (wants && !lit)) { ok = false; log(false, `map ${v.key}: tour step ${i + 1} (caption "${caption}", highlighted ${lit})`); }
      }
      if (ok) log(true, `map ${v.key}: all ${v.tour.length} tour steps caption and highlight`);
    }
  }

  // 3. Hash routing
  const seq = QX.views.find(v => v.kind === 'sequence') || QX.views[QX.views.length - 1];
  if (seq) {
    const p2 = await ctx.newPage(); watch(p2);
    await p2.goto(url + '#maps/' + seq.key); await wait(3000);
    log(await p2.$eval(`[data-view="${seq.key}"]`, b => b.classList.contains('active')), `#maps/${seq.key} opens that view on load`);
    await p2.close();
  }

  // 4. Mermaid notes, summary part
  await page.click('[data-part="summary"]'); await wait(2500);
  await page.screenshot({ path: path.join(out, '3-summary.png'), fullPage: true });
  const notes = await page.$$eval('rect.note', rs => rs.map(r => {
    const rb = r.getBBox();
    return Array.from(r.parentElement.querySelectorAll('text.noteText')).every(t => { const b = t.getBBox();
      return b.x >= rb.x - 1 && b.x + b.width <= rb.x + rb.width + 1 && b.y >= rb.y - 1 && b.y + b.height <= rb.y + rb.height + 1; });
  }));
  log(notes.every(Boolean), `Mermaid note text inside its box (${notes.length} notes)`);

  // 5. Theme
  const bg0 = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.click('#theme-toggle'); await wait(300);
  const bg1 = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const stored = await page.evaluate(() => localStorage.getItem('qexplain-theme'));
  log(bg0 !== bg1 && !!stored, `theme toggle re-themes and persists (${stored})`);

  // 6. Diff review
  await page.evaluate(k => { localStorage.removeItem(k); localStorage.removeItem('nav-w'); }, storeKey);
  await page.goto(url + '#diff'); await wait(1000);
  log(await page.$eval('#part-diff', p => p.classList.contains('active')), '#diff opens Diff review on load');
  const listed = await page.$$eval('#nav-inner .ni', n => n.length);
  log(listed === QX.files, `sidebar lists ${listed} of ${QX.files} files`);
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
    log(vis > 0 && vis < QX.files, `type filter narrows ${QX.files} files to ${vis}`);
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
  log(await page.$$eval('.tdir', d => d.length) > 0 || QX.files === 1, 'tree view shows directories');
  await page.screenshot({ path: path.join(out, '4-diff.png') });
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
  log(await page.$('#verified') !== null, 'Narrative part has the verified section');

  // 7. Phone width
  const phone = await browser.newPage({ viewport: { width: 390, height: 800 } }); watch(phone);
  await routeLibs(phone);
  for (const part of ['narrative', 'maps', 'summary', 'diff']) {
    await phone.goto(url + '#' + part); await wait(1500);
    const sw = await phone.evaluate(() => document.documentElement.scrollWidth);
    log(sw <= 391, `no sideways page scroll at 390px on ${part} (${sw}px)`);
  }
  await phone.screenshot({ path: path.join(out, '5-phone.png') });
  log(errors.length === 0, 'no page errors' + (errors.length ? ': ' + errors.slice(0, 4).join(' | ') : ''));
  await browser.close();
  console.log(`\nScreenshots in ${out}. Look at them: a check can pass while the page still looks wrong.`);
  process.exit(bad ? 1 : 0);
})().catch(e => { console.error('ERROR\t' + e.message); process.exit(2); });
