'use strict';
// Runs the userscript against the mock Seller Central / Pricetar pages in Chromium.
//   node userscripts/test/run.cjs                 # check the current script
//   node userscripts/test/run.cjs --nested        # same, with the script pasted into itself
//   node userscripts/test/run.cjs --script old.user.js --report   # just print results
//   node userscripts/test/run.cjs --only normal,lag
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const argv = process.argv.slice(2);
const option = name => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : null; };
const scriptPath = path.resolve(option('--script') || path.join(__dirname, '..', 'pricetar-max30.user.js'));
const nested = argv.includes('--nested');
const reportOnly = argv.includes('--report');
const only = option('--only')?.split(',');

let source = fs.readFileSync(scriptPath, 'utf8');
if (nested) {
  // The broken install seen in the wild: the whole script pasted again inside hostInput().
  const marker = '  function hostInput(doc, id, label) {\n';
  const at = source.indexOf(marker) + marker.length;
  source = source.slice(0, at) + source + '\n' + source.slice(at);
}
const VERSION = source.match(/const VERSION = '([^']+)'/)[1];
const PREFIX = 'pricetar.max30.v1.';
const SELLER = 'https://sellercentral.amazon.co.jp';
const PRICETAR = 'https://jp3.pricetar.com';
const ITEMS = {
  first: { sku: '20250910-B0C26NK8KD', asin: 'B0C26NK8KD' },
  second: { sku: '20250922-B0972C7BM9', asin: 'B0972C7BM9' },
};
const sellerHtml = fs.readFileSync(path.join(__dirname, 'mock-seller.html'), 'utf8');
const pricetarHtml = fs.readFileSync(path.join(__dirname, 'mock-pricetar.html'), 'utf8');
const blank = '<!doctype html><meta charset="utf-8"><title>seed</title>';

// Tampermonkey runs the script at document-idle with GM_* in scope. GM storage
// lives in each origin's localStorage; tests copy it between the two sites.
const GM = `
const GM_getValue = (k, d) => { const v = localStorage.getItem('gm:' + k); return v === null ? d : JSON.parse(v); };
const GM_setValue = (k, v) => localStorage.setItem('gm:' + k, JSON.stringify(v));
const GM_deleteValue = k => localStorage.removeItem('gm:' + k);
const GM_openInTab = url => window.__pm30Open(url);
const GM_getTab = cb => setTimeout(() => cb(JSON.parse(sessionStorage.getItem('gm:tab') || '{}')), 5);
const GM_saveTab = tab => sessionStorage.setItem('gm:tab', JSON.stringify(tab));
`;
const userscript = "document.addEventListener('DOMContentLoaded', () => setTimeout(() => {\n" + GM + source + '\n}, 0));';
// Records every status message the script shows; "E" marks the error colour.
const recorder = `document.addEventListener('DOMContentLoaded', () => {
  let last = '';
  new MutationObserver(() => {
    const box = document.getElementById('pm30-status');
    if (!box) return;
    const entry = (box.style.color === 'rgb(138, 35, 23)' ? 'E ' : 'I ') + box.textContent.replace(/^×/, '').replace(/\\n/g, ' / ');
    if (entry === last) return;
    last = entry;
    const list = JSON.parse(sessionStorage.getItem('test.panels') || '[]');
    list.push(entry);
    sessionStorage.setItem('test.panels', JSON.stringify(list));
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
});`;

const terminal = s => ['verified', 'failed', 'pending'].includes(s);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function newContext(browser, opened) {
  const context = await browser.newContext();
  const serve = html => route => {
    const seed = new URL(route.request().url()).pathname === '/seed';
    return route.fulfill({ contentType: 'text/html; charset=utf-8', body: seed ? blank : html });
  };
  await context.route(SELLER + '/**', serve(sellerHtml));
  await context.route(PRICETAR + '/**', serve(pricetarHtml));
  await context.exposeFunction('__pm30Open', url => { opened.push(url); });
  await context.addInitScript(recorder);
  await context.addInitScript(userscript);
  return context;
}
const dumpGm = page => page.evaluate(() => Object.fromEntries(Object.keys(localStorage)
  .filter(k => k.startsWith('gm:')).map(k => [k, localStorage.getItem(k)])));
const loadGm = (page, data) => page.evaluate(d => {
  for (const k of Object.keys(localStorage)) if (k.startsWith('gm:')) localStorage.removeItem(k);
  for (const [k, v] of Object.entries(d)) localStorage.setItem(k, v);
}, data);
const gmKey = k => 'gm:' + PREFIX + k;

function editUrl(item, token) {
  const url = new URL(SELLER + '/interactive/listing/workflow/edit/offer');
  url.search = new URLSearchParams({ sku: item.sku, asin: item.asin, marketplaceID: 'A1VC38T7YXB528', isVariationParent: 'false' });
  url.hash = 'pricetar-max30=' + token;
  return url.href;
}
function makeJob(item, state, extra = {}) {
  const now = Date.now();
  return { ...item, title: 'テスト商品', channel: 'MFN', token: crypto.randomUUID(), createdAt: now,
    version: VERSION, mode: 'set', state, message: '', updatedAt: now, ...extra };
}
function seedJob(job) {
  return { [gmKey('job.' + job.token)]: JSON.stringify(job),
    [gmKey('lock')]: JSON.stringify({ token: job.token, at: job.createdAt }) };
}

// Opens the Seller Central tab for a job and waits until the job ends.
async function runSeller(context, url, cfg, gm, person = null, timeout = 300000) {
  const page = await context.newPage();
  await page.goto(SELLER + '/seed');
  await page.evaluate(c => { localStorage.clear(); localStorage.setItem('mock.cfg', JSON.stringify(c)); }, cfg);
  await loadGm(page, gm);
  await page.goto(url);
  const token = new URL(url).hash.split('=')[1];
  let personDone = false;
  const acting = person ? person.act(page).catch(e => ({ error: e.message })).finally(() => { personDone = true; }) : null;
  const end = Date.now() + timeout;
  let job = null;
  while (Date.now() < end) {
    if (person?.endWhenDone && personDone) break;
    try {
      job = JSON.parse(await page.evaluate(k => localStorage.getItem(k), gmKey('job.' + token)));
      if (job && terminal(job.state)) break;
    } catch { /* page is reloading */ }
    await sleep(500);
  }
  await sleep(3000); // let late messages (for example from a second copy of the script) arrive
  const read = () => page.evaluate(() => ({
    log: JSON.parse(localStorage.getItem('mock.log') || '[]'),
    server: JSON.parse(localStorage.getItem('mock.server') || '{}'),
    panels: JSON.parse(sessionStorage.getItem('test.panels') || '[]'),
  }));
  let seen;
  for (let i = 0; i < 10 && !seen; i++) seen = await read().catch(() => sleep(500).then(() => null));
  return { page, job, ...seen, gm: await dumpGm(page), person: acting ? await acting : null };
}

// A person on the Amazon tab: types into the highlighted box and presses
// 保存 / 変更を送信 when the script says so.
const said = (page, words, timeout) => page.waitForFunction(w => document.getElementById('pm30-status')?.textContent.includes(w), words, { timeout });
async function personRound(page, { value = null, price = null, waitPrompt = 240000 } = {}) {
  // Waits for the script's guidance; types only when asked (or when the test
  // wants a specific value), then presses 保存 and 変更を送信.
  await page.waitForFunction(() => /30 と打って|「保存」を押して|「変更を送信」を押して/
    .test(document.getElementById('pm30-status')?.textContent || ''), null, { timeout: waitPrompt });
  const asked = await page.evaluate(() => document.getElementById('pm30-status').textContent.includes('30 と打って'));
  const typed = asked || value !== null || price !== null;
  if (typed) {
    const box = page.locator('kat-input#max_order_quantity-0-value input');
    await box.fill('');
    await box.pressSequentially(value ?? '30');
    if (price) await page.locator('kat-input#purchasable_offer-0-our_price input').fill(price);
    await page.mouse.click(5, 5);
    await page.waitForTimeout(800);
  }
  const how = typed ? 'typed' : 'auto';
  await page.locator('kat-button[data-testid="kat-button-save"]').click();
  if ((value ?? '30') !== '30' || price) {
    return said(page, 'この操作は止めました', 5000).then(() => how + '-save-blocked', () => how + '-save-allowed');
  }
  const ready = await said(page, '「変更を送信」を押して', 30000).then(() => true, () => false);
  await page.locator('#form-submit-button').click();
  // Let the guidance move on, so a next round does not act on this one's text.
  await page.waitForFunction(() => !(document.getElementById('pm30-status')?.textContent || '').includes('「変更を送信」を押して'),
    null, { timeout: 60000 }).catch(() => {});
  return how + (ready ? '-sent' : '-forced');
}
const person = (...rounds) => ({ act: async page => { const out = []; for (const r of rounds) out.push(await personRound(page, r)); return out; } });
const typesThenStops = (round, extra = async () => {}) => ({ endWhenDone: true, act: async page => {
  const out = await personRound(page, round);
  await extra(page);
  await page.waitForTimeout(2000);
  return out;
} });

function verdict(name, result, expect) {
  const problems = [];
  const state = result.job?.state ?? 'none';
  const submits = result.server?.submits ?? 0;
  const errors = (result.panels || []).filter(p => p.startsWith('E '));
  if (expect.state && state !== expect.state) problems.push(`state=${state} (expected ${expect.state})`);
  if (expect.submits !== undefined && submits !== expect.submits) problems.push(`submits=${submits} (expected ${expect.submits})`);
  if (expect.clean && errors.length) problems.push('error message shown: ' + errors[0].slice(0, 160));
  if (!expect.personTypesPrice && (result.log || []).some(l => l.startsWith('PRICE-INPUT'))) problems.push('the price field was typed into');
  if (expect.blocked && !(result.panels || []).some(p => p.includes('この操作は止めました'))) problems.push('the unsafe click was not stopped');
  if (expect.noPanelSave && (result.log || []).some(l => l.startsWith('panel-save'))) problems.push('Amazon received 保存 although it should have been stopped');
  for (const line of (result.log || []).filter(l => l.startsWith('SUBMIT '))) {
    if (line !== 'SUBMIT {"max":"30"}' && !expect.tamper) problems.push('unexpected submission ' + line);
  }
  if (expect.tamper && submits) problems.push('submitted although another field changed');
  if (expect.opened !== undefined && result.opened !== expect.opened) problems.push(`opened=${result.opened} (expected ${expect.opened})`);
  if (expect.label && result.label !== expect.label) problems.push(`button="${result.label}" (expected "${expect.label}")`);
  const first = Array.isArray(result.person) ? result.person[0] : result.person;
  if (expect.typed !== undefined && !String(first).startsWith(expect.typed ? 'typed' : 'auto')) problems.push(`person=${first} (expected ${expect.typed ? 'typed' : 'auto'})`);
  if (expect.diag && !(result.job?.message || '').includes(expect.diag)) problems.push(`diagnosis lacks "${expect.diag}"`);
  return { name, ok: problems.length === 0, state, submits, errors: errors.length, problems,
    message: (result.job?.message || '').replace(/\n/g, ' / '), label: result.label, panels: result.panels };
}

const P = person({});
const sellerScenarios = [
  { name: 'normal', cfg: {}, person: P, expect: { state: 'verified', submits: 1, clean: true, typed: false } },
  { name: 'already-30', cfg: { initialMax: '30' }, expect: { state: 'verified', submits: 0, clean: true } },
  { name: 'no-success-dialog', cfg: { noDialog: true }, person: P, expect: { state: 'verified', submits: 1, clean: true } },
  { name: 'slow-to-reflect', cfg: { lagLoads: 2 }, person: P, expect: { state: 'verified', submits: 1, clean: true } },
  { name: 'first-submit-lost', cfg: { loseSubmits: 1, lagLoads: 0 }, person: person({}, {}), expect: { state: 'verified', submits: 2, clean: true } },
  { name: 'edit-click-lost', cfg: { deadEditClicks: 1 }, person: P, expect: { state: 'verified', submits: 1, clean: true } },
  { name: 'lazy-field', cfg: { lazyField: 1200 }, person: P, expect: { state: 'verified', submits: 1, clean: true } },
  { name: 'late-cards', cfg: { lateCards: 3000 }, person: P, expect: { state: 'verified', submits: 1, clean: true } },
  { name: 'reloaded-while-editing', cfg: {}, state: 'editing', person: P, expect: { state: 'verified', submits: 1, clean: true } },
  // Amazon ignores input made by scripts: the person's typing still works.
  { name: 'script-input-ignored', cfg: { trustedOnly: true }, person: P, expect: { state: 'verified', submits: 1, clean: true, typed: false } },
  { name: 'value-not-reflected', cfg: { noReflect: true }, person: P,
    expect: { state: 'verified', submits: 1, clean: true, typed: true, diag: '（★なし）' } },
  // Only real key presses are taken: the script's entry fails, the person types, the diagnosis records it.
  { name: 'needs-real-keys', cfg: { needsKeys: true }, person: P,
    expect: { state: 'verified', submits: 1, clean: true, typed: true, diag: '★' } },
  // Guards: wrong value, another field typed into, Amazon changing another field.
  { name: 'person-types-31-first', cfg: {}, person: person({ value: '31' }, { value: '30' }), expect: { state: 'verified', submits: 1, blocked: true } },
  { name: 'person-changes-price', cfg: {}, person: typesThenStops({ price: '999' }),
    expect: { submits: 0, blocked: true, noPanelSave: true, personTypesPrice: true } },
  { name: 'other-field-changes', cfg: { tamper: true }, person: typesThenStops({}),
    expect: { submits: 0, blocked: true, tamper: true } },
  { name: 'input-never-taken', cfg: { rejectInput: true }, person: typesThenStops({}), expect: { submits: 0, blocked: true } },
];

async function sellerScenario(browser, s) {
  const context = await newContext(browser, []);
  const job = makeJob(ITEMS.first, s.state || 'queued');
  const result = await runSeller(context, editUrl(ITEMS.first, job.token), s.cfg, seedJob(job), s.person);
  await context.close();
  return verdict(s.name, result, s.expect);
}

async function pricetarPage(context, gm) {
  const page = await context.newPage();
  await page.goto(PRICETAR + '/seed');
  await loadGm(page, gm);
  await page.goto(PRICETAR + '/seller/product/list');
  await page.waitForSelector('#itemInputDataTr_1 .pm30-button');
  return page;
}
const label = (page, row) => page.$eval(`#itemInputDataTr_${row} .pm30-button`, b => b.textContent);

const pricetarScenarios = [
  {
    // Click the blue button, let the Amazon tab run, and read the button again.
    name: 'click-to-verified', expect: { opened: 1, state: 'verified', submits: 1, label: '30個 確認済 ✓', clean: true },
    async run(context, opened) {
      const page = await pricetarPage(context, {});
      await page.click('#itemInputDataTr_1 .pm30-button');
      await sleep(500);
      const result = opened.length ? await runSeller(context, opened[0], {}, await dumpGm(page), P) : {};
      if (result.gm) await loadGm(page, result.gm);
      await sleep(3000);
      return { ...result, opened: opened.length, label: await label(page, 1) };
    },
  },
  {
    // A tab that was closed mid-run must not block the next click for minutes.
    name: 'closed-tab-does-not-block', expect: { opened: 1 },
    async run(context, opened) {
      const old = makeJob(ITEMS.second, 'editing', { createdAt: Date.now() - 3 * 60000, updatedAt: Date.now() - 3 * 60000 });
      const page = await pricetarPage(context, { ...seedJob(old), [gmKey('lock')]: JSON.stringify({ token: old.token, at: old.createdAt }) });
      await page.click('#itemInputDataTr_1 .pm30-button');
      await sleep(500);
      return { opened: opened.length, label: await label(page, 1) };
    },
  },
  {
    // A job whose Amazon tab is still alive must still block a second job.
    name: 'running-job-blocks', expect: { opened: 0 },
    async run(context, opened) {
      const live = makeJob(ITEMS.second, 'editing');
      const page = await pricetarPage(context, { ...seedJob(live), [gmKey('beat.' + live.token)]: JSON.stringify(Date.now()) });
      await page.click('#itemInputDataTr_1 .pm30-button');
      await sleep(500);
      return { opened: opened.length, label: await label(page, 1) };
    },
  },
  {
    // A yellow (sent, not yet confirmed) row: one click must finish the job.
    name: 'yellow-click-finishes', expect: { opened: 1, state: 'verified', submits: 1, label: '30個 確認済 ✓', clean: true },
    async run(context, opened) {
      const result0 = { state: 'pending', message: '送信済み', at: Date.now() - 60000, token: crypto.randomUUID(), sku: ITEMS.first.sku, title: 'テスト商品' };
      const page = await pricetarPage(context, { [gmKey('result.' + ITEMS.first.sku)]: JSON.stringify(result0) });
      await page.click('#itemInputDataTr_1 .pm30-button');
      await sleep(500);
      const result = opened.length ? await runSeller(context, opened[0], {}, await dumpGm(page), P) : {};
      if (result.gm) await loadGm(page, result.gm);
      await sleep(3000);
      return { ...result, opened: opened.length, label: await label(page, 1) };
    },
  },
];

async function pricetarScenario(browser, s) {
  const opened = [];
  const context = await newContext(browser, opened);
  const result = await s.run(context, opened);
  await context.close();
  return verdict(s.name, result, s.expect);
}

(async () => {
  const browser = await chromium.launch();
  const pick = list => list.filter(s => !only || only.includes(s.name));
  const started = Date.now();
  const results = await Promise.all([
    ...pick(sellerScenarios).map(s => sellerScenario(browser, s)),
    ...pick(pricetarScenarios).map(s => pricetarScenario(browser, s)),
  ]);
  await browser.close();
  console.log(`script v${VERSION}${nested ? ' (pasted into itself)' : ''} — ${Math.round((Date.now() - started) / 1000)}s`);
  for (const r of results) {
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name.padEnd(26)} state=${r.state.padEnd(8)} submits=${r.submits} errors=${r.errors}${r.label ? ` button="${r.label}"` : ''}`);
    if (!r.ok || reportOnly) {
      for (const p of r.problems) console.log('        - ' + p);
      if (r.message) console.log('        message: ' + r.message.slice(0, 300));
      for (const p of (r.panels || []).filter(x => x.startsWith('E ')).slice(0, 3)) console.log('        shown: ' + p.slice(0, 200));
    }
  }
  if (!reportOnly && results.some(r => !r.ok)) process.exitCode = 1;
})();
