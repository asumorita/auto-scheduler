// ==UserScript==
// @name         プライスター・購入上限30個
// @namespace    morit-pricetar-max30
// @version      1.0.6
// @description  押した行のSKUだけ、Amazon日本の最大注文可能個数を30に設定・再確認します。
// @match        https://jp3.pricetar.com/seller/product/*
// @match        https://sellercentral.amazon.co.jp/interactive/listing/workflow/edit/offer*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_deleteValue
// @grant        GM_openInTab
// @grant        GM_getTab
// @grant        GM_saveTab
// @noframes
// @run-at       document-idle
// ==/UserScript==

(() => {
  'use strict';
  const VERSION = '1.0.6';
  const MAX_ID = 'max_order_quantity-0-value';
  const MAX_LABEL = '最大注文可能個数';
  const MARKET = 'A1VC38T7YXB528';
  const ACCOUNT = 'ASU@USA日本';
  const TTL = 20 * 60 * 1000;          // a job never acts after this
  const STALE = 90 * 1000;             // no heartbeat for this long: the Amazon tab has stopped
  const MAX_ATTEMPTS = 3;              // fresh page loads per click before giving up (nothing sent)
  const MAX_SUBMITS = 2;               // 変更を送信 per click while 30 does not show up
  const VERIFY_WAITS = [5000, 15000, 30000, 60000]; // pause before each read-back reload
  const PREFIX = 'pricetar.max30.v1.';
  const clean = x => String(x ?? '').normalize('NFKC').replace(/\s+/g, '').trim();
  const text = e => e?.textContent?.trim() || '';
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const terminal = s => ['verified', 'failed', 'pending'].includes(s);

  function deepAll(root, selector) {
    const result = [...root.querySelectorAll(selector)];
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) result.push(...deepAll(el.shadowRoot, selector));
    }
    return result;
  }
  function shown(el) {
    return !!el && !el.hidden && el.getAttribute('aria-hidden') !== 'true'
      && el.getClientRects().length > 0;
  }
  function unique(items, why) { assert(items.length === 1, why); return items[0]; }
  function hostInput(doc, id, label) {
    const host = unique([...doc.querySelectorAll('kat-input')].filter(x => x.id === id),
      `${label}の入力欄を一意に確認できません。保存を中止しました。`);
    assert(host.getAttribute('name') === id && host.getAttribute('kat-aria-label') === label,
      `${label}の項目名が変わっています。保存を中止しました。`);
    const input = host.shadowRoot?.querySelector('input');
    assert(input && input.name === id && input.getAttribute('aria-label') === label && shown(host),
      `${label}の入力欄が確認できません。`);
    return { host, input };
  }
  function maxField(doc) {
    const field = hostInput(doc, MAX_ID, MAX_LABEL);
    assert(field.input.type === 'number' && !field.input.disabled && !field.input.readOnly,
      '購入上限の欄を編集できません。');
    return field;
  }
  function readRow(row) {
    const cells = [...row.querySelectorAll(':scope > td')];
    assert(cells.length >= 8, '商品行の形式が変わっています。');
    const skuText = text(cells[4].querySelector('p'));
    const skuAttr = cells[0].querySelector('input.productSelect[data-sku]')?.dataset.sku;
    const asinLinks = [...cells[3].querySelectorAll('a')].filter(a => /^[A-Z0-9]{10}$/.test(text(a)));
    const asin = text(unique(asinLinks, 'ASINを確認できません。'));
    assert(skuText && skuText === skuAttr && skuText.length <= 200, '表示SKUと行のSKUが一致しません。');
    const channelText = text(cells[7]);
    assert(channelText.includes('自己発送') || channelText.includes('FBA'), '発送方法を確認できません。');
    const title = text(cells[4].querySelector('a'));
    assert(title, '商品名を確認できません。');
    return { sku: skuText, asin, title, channel: channelText.includes('自己発送') ? 'MFN' : 'FBA' };
  }
  function editUrl(item, token) {
    const url = new URL('https://sellercentral.amazon.co.jp/interactive/listing/workflow/edit/offer');
    url.search = new URLSearchParams({ sku: item.sku, asin: item.asin,
      marketplaceID: MARKET, isVariationParent: 'false' }).toString();
    url.hash = 'pricetar-max30=' + token;
    return url.href;
  }
  function checkPageIdentity(doc, urlString, job) {
    const url = new URL(urlString);
    assert(url.origin === 'https://sellercentral.amazon.co.jp'
      && url.pathname === '/interactive/listing/workflow/edit/offer'
      && url.searchParams.get('sku') === job.sku
      && url.searchParams.get('asin') === job.asin
      && url.searchParams.get('marketplaceID') === MARKET, 'Amazonの対象SKU・ASIN・国が一致しません。');
    const pageSku = unique([...doc.querySelectorAll('[data-testid="page-title-sku"]')], '画面見出しのSKUを確認できません。');
    assert(text(pageSku) === 'SKU：' + job.sku || text(pageSku) === 'SKU: ' + job.sku,
      'Amazon画面見出しのSKUが一致しません。');
    const banner = doc.getElementById('product-details-banner');
    assert(banner && clean(text(banner)).includes('ASIN:' + job.asin), 'Amazon画面のASINが一致しません。');
    const header = doc.getElementById('ngstrim-header');
    assert(header && deepAll(header, 'button,[role="button"]').some(x => clean(x.getAttribute('aria-label') || text(x)) === ACCOUNT),
      'AmazonのアカウントがASU＠USA・日本であることを確認できません。');
  }
  function checkIdentity(doc, urlString, job) {
    checkPageIdentity(doc, urlString, job);
    const sku = hostInput(doc, 'contribution_sku-0-value', 'SKU');
    assert(sku.input.value === job.sku && sku.input.disabled, 'Amazon画面のSKUが一致しません。');
    const radios = deepAll(doc.getElementById('desktopMainSection'), 'input[type="radio"]');
    const selected = radios.filter(x => x.checked).map(x => x.getAttribute('aria-label') || text(x.parentElement)).join(' ');
    // The disabled fulfilment controls are evidence, never edited by this script.
    const channelHost = [...doc.querySelectorAll('kat-radiobutton')].filter(x => x.hasAttribute('checked'));
    const channelLabel = selected + ' ' + channelHost.map(x => x.getAttribute('label') || text(x)).join(' ');
    if (job.channel === 'MFN') assert(channelLabel.includes('出品者自身で発送'), '自己発送SKUとの一致を確認できません。');
    if (job.channel === 'FBA') assert(channelLabel.includes('Amazonから出荷(FBA)'), 'FBA SKUとの一致を確認できません。');
  }
  function editCounts(doc) {
    const boxes = [...doc.querySelectorAll('[id^="hub-item-box-"]')];
    assert(boxes.length >= 5, 'Amazonの編集件数を確認できません。');
    return boxes.map(box => {
      const label = box.querySelector('[data-testid="hub-nav-item-state-label"]');
      const value = label?.getAttribute('text') ?? text(label);
      if (value === '編集はありません') return [box.id, 0];
      assert(/^\d+$/.test(value), 'Amazonの編集状態を確認できません。');
      return [box.id, Number(value)];
    });
  }
  function onlyExpectedEdit(counts, expected) {
    assert(counts.every(([id, count]) => count === (id === 'hub-item-box-offer' ? expected : 0)),
      '購入上限以外の編集が含まれる可能性があるため、保存を中止しました。');
  }
  function withinPanel(el) {
    for (let node = el; node; node = node.parentElement || node.getRootNode?.().host) {
      if (node.tagName === 'KAT-PANEL-WRAPPER') return true;
    }
    return false;
  }
  function protectedSnapshot(doc, excludePanels = false) {
    const root = doc.getElementById('desktopMainSection');
    assert(root, 'Amazonの商品編集画面を確認できません。');
    const result = [];
    for (const el of deepAll(root, 'input,textarea,select')) {
      if (el.hidden || el.type === 'hidden' || el.name === MAX_ID
        || ['AttributeFilter', 'losg-attribute-filter'].includes(el.name)
        || (excludePanels && withinPanel(el))) continue;
      // Amazon regenerates katal-id-* when its panel is reopened. Semantic
      // names and labels still identify every field; values remain exact.
      const key = [el.tagName, el.name, /^katal-id-/.test(el.id) ? '' : el.id, el.type, el.getAttribute('aria-label')];
      result.push([key, el.value, !!el.checked, !!el.disabled]);
    }
    for (const el of root.querySelectorAll('kat-input,kat-textarea,kat-dropdown,kat-radiobutton,kat-checkbox,kat-datepicker,kat-toggle')) {
      if (el.id === MAX_ID || ['AttributeFilter', 'losg-attribute-filter'].includes(el.getAttribute('name'))
        || (excludePanels && withinPanel(el))) continue;
      result.push([[el.tagName, el.id, el.getAttribute('name')], el.getAttribute('value'),
        el.getAttribute('checked'), el.getAttribute('disabled')]);
    }
    assert(excludePanels || result.length >= 8, '価格・在庫などの確認が完了していません。');
    return JSON.stringify(result.map(x => JSON.stringify(x)).sort());
  }
  function sourceEditButton(doc) {
    const cards = [...doc.querySelectorAll('#losg-source-marketplace-card [data-testid="source-marketplace-card"]')];
    if (!cards.length) return null;
    const card = unique(cards, 'メインの出品が複数あるため中止しました。');
    const flag = unique([...card.querySelectorAll('kat-flag[data-testid="country-flag"]')], '出品先の国を確認できません。');
    const label = unique([...card.querySelectorAll('[data-testid="card-display-name"]')], '出品先の表示を確認できません。');
    assert(flag.getAttribute('country') === 'jp' && label.getAttribute('text') === '日本'
      && card.querySelector('#card-price-details-slot-' + MARKET), '日本のメイン出品を確認できません。');
    const button = unique([...card.querySelectorAll('kat-button[data-testid="card-edit-action"]')], '日本の編集ボタンを確認できません。');
    assert(button.getAttribute('label') === '編集' && button.getAttribute('type') === 'button', '日本の編集ボタンの形式が異なります。');
    return button;
  }
  function offerPanel(doc) {
    const wrappers = [...doc.querySelectorAll('kat-panel-wrapper[data-testid="attributeFormPanelWrapper"][panel-visible]')];
    if (!wrappers.length) return null;
    const wrapper = unique(wrappers, '編集パネルが複数あるため中止しました。');
    const panel = unique([...wrapper.querySelectorAll('kat-panel[visible]')], '編集パネルを一意に確認できません。');
    const flags = [...panel.querySelectorAll('[slot="header"] kat-flag[country="jp"]')];
    const labels = [...panel.querySelectorAll('[slot="header"] [data-testid="card-display-name"]')];
    assert(flags.length === 1 && labels.length === 1 && labels[0].getAttribute('text') === '日本',
      '日本の編集パネルではないため中止しました。');
    return panel;
  }
  function panelAction(panel, action) {
    assert(panel, '編集パネルが閉じたため中止しました。');
    assert(['save', 'cancel'].includes(action), 'パネル操作が不明です。');
    const button = unique([...panel.querySelectorAll('kat-button[data-testid="kat-button-' + action + '"]')], 'パネルの操作ボタンを確認できません。');
    assert(button.getAttribute('label') === (action === 'save' ? '保存' : 'キャンセル')
      && button.getAttribute('type') === 'button', 'パネルの操作ボタンの形式が異なります。');
    return button;
  }
  function readyPanelAction(panel, action) {
    assert(['save', 'cancel'].includes(action), 'パネル操作が不明です。');
    if (!panel) return null;
    const buttons = [...panel.querySelectorAll('kat-button[data-testid="kat-button-' + action + '"]')];
    if (!buttons.length) return null;
    const button = unique(buttons, 'パネルの操作ボタンが複数あるため中止しました。');
    // Amazon can replace its button after an input event. The custom element
    // adds its type and final localized label asynchronously. A different
    // label/type must never be clicked; wait for the EXACT expected values.
    const label = button.getAttribute('label');
    const type = button.getAttribute('type');
    if (label !== (action === 'save' ? '保存' : 'キャンセル') || type !== 'button'
      || !shown(button) || button.hasAttribute('disabled')) return null;
    const natives = button.shadowRoot?.querySelectorAll('button');
    if (!natives?.length) return null;
    const native = unique([...natives], 'パネルの操作ボタンを一意に確認できません。');
    if (native.type !== 'button' || native.disabled) return null;
    return panelAction(panel, action);
  }
  function outsidePanelSnapshot(doc) {
    const button = sourceEditButton(doc);
    assert(button, '日本のメイン出品カードが見つかりません。');
    const card = button.closest('[data-testid="source-marketplace-card"]');
    return JSON.stringify({ controls: protectedSnapshot(doc, true),
      price: text(card.querySelector('#card-price-details-slot-' + MARKET)),
      fulfillment: text(card.querySelector('[data-testid="card-fulfillment-by-amazon-' + MARKET + '"]')) });
  }
  function snapshotDiff(before, after) {
    // Names the fields that differ, so a stop can be traced to a real field.
    const entries = s => {
      try {
        const v = JSON.parse(s);
        return Array.isArray(v) ? v : [...JSON.parse(v.controls),
          JSON.stringify([['カード価格'], v.price]), JSON.stringify([['カード配送'], v.fulfillment])];
      } catch { return []; }
    };
    const a = new Set(entries(before)), b = new Set(entries(after));
    const changed = [...a].filter(x => !b.has(x)).concat([...b].filter(x => !a.has(x))).map(x => {
      try { const [key, value] = JSON.parse(x); return key.filter(Boolean).join('/') + '=' + String(value).slice(0, 30); }
      catch { return x.slice(0, 60); }
    });
    return [...new Set(changed)].slice(0, 4).join('、');
  }
  function sameProtected(before, after) {
    if (before === after) return;
    const changed = snapshotDiff(before, after);
    throw new Error('購入上限以外の入力欄に変化を検出したため、保存を中止しました。' + (changed ? '\n変化：' + changed : ''));
  }
  function setOnlyMax(doc) {
    const { host, input } = maxField(doc);
    input.focus();
    const setter = Object.getOwnPropertyDescriptor(input.ownerDocument.defaultView.HTMLInputElement.prototype, 'value').set;
    setter.call(input, '30');
    input.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
    input.dispatchEvent(new Event('change', { bubbles: true, composed: true }));
    input.blur();
    assert(input.value === '30', '購入上限の入力に失敗しました。');
    return host;
  }
  function clickKat(host) {
    assert(host && shown(host) && !host.hasAttribute('disabled'), '操作ボタンを確認できません。');
    const button = host.shadowRoot?.querySelector('button');
    assert(button && !button.disabled, '操作ボタンが利用できません。');
    button.click();
  }
  function readySubmit(doc) {
    const host = doc.getElementById('form-submit-button');
    if (!host || host.tagName !== 'KAT-BUTTON'
      || host.getAttribute('data-testid') !== 'submit-button'
      || host.getAttribute('type') !== 'button'
      || host.getAttribute('data-cy') !== 'submit-button-ready'
      || host.getAttribute('data-ready-to-submit') !== 'true'
      || clean(text(host)) !== '変更を送信'
      || !shown(host) || host.hasAttribute('disabled')) return null;
    const native = host.shadowRoot?.querySelector('button');
    return native && !native.disabled ? host : null;
  }
  async function waitSubmitReady(doc, guard, timeout = 45000, stableMs = 1200) {
    const end = Date.now() + timeout;
    let previous = null, since = 0, last = null;
    while (Date.now() < end) {
      // Closing Amazon's verification panel can briefly leave a stale ready
      // button, then trigger a new validation cycle. Require stable readiness
      // with every guard passing for the whole period. A guard that fails only
      // while Amazon re-renders restarts the period; the caller repeats the
      // guard strictly right before clicking.
      let button = null;
      try { guard(); button = readySubmit(doc); last = null; } catch (e) { last = e; }
      if (button && button === previous) {
        if (Date.now() - since >= stableMs) return button;
      } else {
        since = Date.now();
      }
      previous = button;
      await sleep(400);
    }
    const host = doc.getElementById('form-submit-button');
    throw new Error('Amazonの送信準備が45秒以内に安定しませんでした。送信はしていません。\n'
      + '送信ボタンの表示：' + (text(host) || '未表示') + (last ? '\n' + last.message : ''));
  }
  async function until(fn, timeout = 45000, what = '画面の読み込み・確認') {
    // Amazon re-renders its custom elements while loading, so a check that
    // throws here only means "not yet". Clicks always follow strict re-checks.
    const end = Date.now() + timeout;
    let last = null;
    while (Date.now() < end) {
      try {
        const result = fn();
        if (result) return result;
        last = null;
      } catch (e) { last = e; }
      await sleep(400);
    }
    throw new Error(`${what}が${Math.round(timeout / 1000)}秒以内に完了しませんでした。` + (last ? '\n' + last.message : ''));
  }
  async function settled(read, what, quietMs = 1500, timeout = 20000) {
    // A baseline taken while Amazon is still filling in fields would make a
    // later, unchanged screen look edited. Wait until the value stops moving.
    const end = Date.now() + timeout;
    let previous = null, since = 0, last = null;
    while (Date.now() < end) {
      let value = null;
      try { value = read(); last = null; } catch (e) { last = e; }
      if (value !== null && value === previous) {
        if (Date.now() - since >= quietMs) return value;
      } else {
        previous = value;
        since = Date.now();
      }
      await sleep(300);
    }
    throw new Error(`${what}が${Math.round(timeout / 1000)}秒以内に安定しませんでした。` + (last ? '\n' + last.message : ''));
  }

  // CommonJS export supports offline checks. In a normal userscript this branch is absent.
  const api = { VERSION, MAX_ID, clean, readRow, editUrl, checkPageIdentity, checkIdentity, editCounts,
    onlyExpectedEdit, protectedSnapshot, sameProtected, snapshotDiff, maxField, setOnlyMax, deepAll, readySubmit,
    until, settled, sourceEditButton, offerPanel, panelAction, readyPanelAction, outsidePanelSnapshot, withinPanel,
    waitSubmitReady };
  if (typeof module === 'object' && module.exports) { module.exports = api; return; }

  // Run once per page, even if the script was pasted into itself or installed
  // twice. A second copy reported "別の購入上限処理が進行中です" on every check.
  if (document.documentElement.hasAttribute('data-pm30')) return;
  document.documentElement.setAttribute('data-pm30', VERSION);

  const getJob = token => GM_getValue(PREFIX + 'job.' + token, null);
  const getResult = sku => GM_getValue(PREFIX + 'result.' + sku, null);
  function writeJob(job, state, message, extra = {}) {
    Object.assign(job, extra, { state, message, updatedAt: Date.now() });
    GM_setValue(PREFIX + 'job.' + job.token, job);
    GM_setValue(PREFIX + 'result.' + job.sku, {
      state, message, at: job.updatedAt, token: job.token, sku: job.sku, title: job.title,
      submittedAt: job.submittedAt || null
    });
    if (terminal(state)) {
      if (GM_getValue(PREFIX + 'lock', null)?.token === job.token) GM_deleteValue(PREFIX + 'lock');
      GM_deleteValue(PREFIX + 'beat.' + job.token);
      const recent = GM_getValue(PREFIX + 'recent', []);
      const next = [job.token, ...recent.filter(t => t !== job.token)];
      for (const old of next.slice(40)) { GM_deleteValue(PREFIX + 'job.' + old); GM_deleteValue(PREFIX + 'beat.' + old); }
      GM_setValue(PREFIX + 'recent', next.slice(0, 40));
    }
    return job;
  }
  function heartbeat(token) {
    // Lets the Pricetar tab tell a running job from one whose tab was closed.
    const beat = () => GM_setValue(PREFIX + 'beat.' + token, Date.now());
    beat();
    const id = setInterval(beat, 3000);
    return () => clearInterval(id);
  }
  function liveJob(token) {
    const job = token ? getJob(token) : null;
    if (!job || terminal(job.state)) return null;
    const last = Math.max(GM_getValue(PREFIX + 'beat.' + token, 0), job.updatedAt || 0);
    return Date.now() - last < STALE ? job : null;
  }
  function panel(message, error = false) {
    let box = document.getElementById('pm30-status');
    if (!box) {
      box = document.createElement('div'); box.id = 'pm30-status'; box.setAttribute('role', 'status');
      box.style.cssText = 'position:fixed;right:16px;bottom:18px;z-index:2147483647;max-width:380px;padding:15px 18px;border-radius:10px;box-shadow:0 3px 18px #0003;font:14px/1.65 sans-serif;white-space:pre-wrap;pointer-events:none;';
      document.body.append(box);
    }
    box.style.background = error ? '#fff0ed' : '#f0faf9';
    box.style.color = error ? '#8a2317' : '#143e43';
    box.style.border = '2px solid ' + (error ? '#ca5c43' : '#2d8584');
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '×';
    close.style.cssText = 'float:right;border:0;background:transparent;font-size:20px;cursor:pointer;margin-left:12px;pointer-events:auto;';
    close.onclick = () => box.remove();
    box.replaceChildren(close, document.createTextNode(`購入上限30個 v${VERSION}\n${message}`));
  }
  function shortStatus(result) {
    if (!result) return ['購入上限30個', '#137e83'];
    if (result.state === 'verified') return ['30個 確認済 ✓', '#276c42'];
    if (!terminal(result.state)) return liveJob(result.token) ? ['確認・設定中…', '#586d79'] : ['中断／押して再開', '#a23f31'];
    if (result.state === 'pending') return ['反映待ち／押して再確認', '#946718'];
    return ['エラー／押して再実行', '#a23f31'];
  }
  function addButtons() {
    for (const row of document.querySelectorAll('tr[id^="itemInputDataTr_"]')) {
      let item;
      try { item = readRow(row); } catch { continue; }
      let button = row.querySelector('.pm30-button');
      if (!button) {
        button = document.createElement('button'); button.type = 'button'; button.className = 'pm30-button';
        button.style.cssText = 'display:block;width:100%;min-width:62px;max-width:100px;margin:8px auto 0;padding:6px 3px;color:#fff;border:0;border-radius:5px;font:bold 11px/1.45 sans-serif;white-space:normal;cursor:pointer;';
        button.addEventListener('click', async event => {
          event.preventDefault(); event.stopPropagation();
          try {
            const target = readRow(row);
            // Only a job whose Amazon tab is still alive blocks a new one; a
            // closed or crashed tab stops counting after STALE.
            const running = liveJob(GM_getValue(PREFIX + 'lock', null)?.token);
            if (running) {
              panel((running.sku === target.sku ? 'この商品は処理中です。' : '別の商品の処理中です。')
                + 'Amazonのタブで結果を確認してください。\n' + running.sku);
              return;
            }
            // Every click reads the value first and sets 30 only when it is not
            // already 30, so a yellow or red row is simply run again.
            const token = crypto.randomUUID();
            const job = { ...target, token, createdAt: Date.now(), version: VERSION,
              mode: 'set', state: 'queued', attempt: 1, submits: 0, checks: 0 };
            GM_setValue(PREFIX + 'lock', { token, at: Date.now() });
            writeJob(job, 'queued', 'AmazonのSKUを確認しています。');
            GM_openInTab(editUrl(target, token), { active: true, insert: true, setParent: true });
            panel(`${target.title}\nSKU：${target.sku}\nAmazonで購入上限30個を確認・設定します。`);
            addButtons();
          } catch (e) { panel(e.message, true); }
        });
        row.querySelectorAll(':scope > td')[1].append(button);
      }
      const result = getResult(item.sku);
      const [label, color] = shortStatus(result);
      if (button.textContent !== label) button.textContent = label;
      if (button.dataset.color !== color) { button.style.background = color; button.dataset.color = color; }
      button.title = `購入上限30個 v${VERSION}\n` + (result ? `${result.message}\n${new Date(result.at).toLocaleString('ja-JP')}\nSKU：${item.sku}`
        : `このSKUの最大注文可能個数を30に設定\n${item.sku}`);
    }
  }
  async function allFields(job, expectedEdits = 0) {
    await until(() => document.querySelector('[data-testid="page-title-sku"]')
      && document.getElementById('product-details-banner') && document.getElementById('attribute-filter-button'),
    45000, 'Amazon編集画面の読み込み');
    await until(() => {
      checkPageIdentity(document, location.href, job);
      onlyExpectedEdit(editCounts(document), expectedEdits);
      return true;
    }, 20000, 'SKU・ASIN・アカウント・編集件数の確認');
    // The regular form can flash briefly before Amazon replaces it with cards,
    // and the cards can arrive a few seconds late.
    await sleep(1800);
    await until(() => sourceEditButton(document), 8000, 'メイン出品カードの表示').catch(() => null);
    const edit = sourceEditButton(document);
    if (edit) {
      const outside = await settled(() => outsidePanelSnapshot(document), 'メイン出品カードの表示');
      const editor = await openOfferPanel();
      const filter = unique([...editor.querySelectorAll('kat-dropdown[data-testid="losg-attribute-filter"]')], 'パネルの項目フィルターを確認できません。');
      if (filter.getAttribute('value') !== 'All') {
        const header = filter.shadowRoot?.querySelector('[part="dropdown-header"]');
        assert(header && shown(header), 'パネルの項目フィルターを開けません。');
        header.click();
        const option = await until(() => deepAll(filter.shadowRoot, 'kat-option[role="option"][value="All"]')
          .find(x => shown(x) && text(x) === 'すべて'), 15000, '項目フィルター「すべて」の表示');
        option.click();
      }
      await until(() => offerPanel(document)?.querySelector('kat-input#' + MAX_ID)?.shadowRoot?.querySelector('input'),
        20000, '最大注文可能個数の欄の表示');
      await sleep(700);
      await until(() => {
        checkIdentity(document, location.href, job);
        onlyExpectedEdit(editCounts(document), expectedEdits);
        return true;
      }, 15000, 'パネル内のSKU・発送方法の確認');
      return { panel: true, outside };
    }
    await until(() => document.querySelector('kat-input#contribution_sku-0-value'), 45000, '入力欄の表示');
    if (!document.querySelector('kat-input#' + MAX_ID)) {
      clickKat(document.getElementById('attribute-filter-button'));
      const option = await until(() => deepAll(document, 'kat-option[role="option"][value="All"]')
        .find(x => shown(x) && text(x) === 'すべて'), 15000, '項目フィルター「すべて」の表示');
      option.click();
    }
    await until(() => document.querySelector('kat-input#' + MAX_ID)?.shadowRoot?.querySelector('input'),
      20000, '最大注文可能個数の欄の表示');
    await sleep(900);
    // Do not act on a disappearing inline form. Switch to the observed card UI.
    if (sourceEditButton(document)) return allFields(job, expectedEdits);
    return { panel: false };
  }
  async function openOfferPanel() {
    // An edit click made while Amazon is still wiring up the card can be lost.
    // Clicking again is harmless: opening the panel changes nothing.
    for (let i = 1; ; i++) {
      if (!offerPanel(document)) clickKat(sourceEditButton(document));
      try {
        return await until(() => {
          const p = offerPanel(document);
          return p && p.querySelector('kat-input#contribution_sku-0-value') && p;
        }, 10000, '日本の編集パネルの表示');
      } catch (e) {
        if (i >= 3) throw e;
      }
    }
  }
  async function savePanelAndVerify(job, before, outside) {
    const checkPanel = edits => {
      checkIdentity(document, location.href, job);
      onlyExpectedEdit(editCounts(document), edits);
      sameProtected(before, protectedSnapshot(document));
      sameProtected(outside, outsidePanelSnapshot(document));
      checkNoErrors();
      assert(maxField(document).input.value === '30', '購入上限の値が30ではありません。');
    };
    await waitPanelAction('save', () => checkPanel(0));
    checkPanel(0);
    const save = readyPanelAction(offerPanel(document), 'save');
    assert(save, 'パネルの保存ボタンが切り替わったため中止しました。');
    clickKat(save);
    await until(() => {
      if (offerPanel(document)) return false;
      const counts = editCounts(document);
      if (counts.some(([id, count]) => id === 'hub-item-box-offer' && count === 0)) return false;
      onlyExpectedEdit(counts, 1);
      return true;
    }, 30000, 'パネル保存の反映');
    await until(() => { sameProtected(outside, outsidePanelSnapshot(document)); return true; }, 10000, 'メイン出品カードの照合');
    await until(() => readySubmit(document), 45000, '送信ボタンの準備');
    // Panel Save only stages the edit. Reopen it to validate the staged values,
    // then close with Cancel (no local edits) before the final submission.
    await allFields(job, 1);
    await waitPanelAction('cancel', () => checkPanel(1));
    checkPanel(1);
    const cancel = readyPanelAction(offerPanel(document), 'cancel');
    assert(cancel, 'パネルのキャンセルボタンが切り替わったため中止しました。');
    clickKat(cancel);
    await until(() => !offerPanel(document), 20000, '編集パネルを閉じる操作');
  }
  async function waitPanelAction(action, check) {
    // Waits until the button is ready AND every check passes at the same time.
    let observed = 'ボタン未表示';
    try {
      return await until(() => {
        const p = offerPanel(document);
        const b = p?.querySelector('kat-button[data-testid="kat-button-' + action + '"]');
        observed = b ? `表示=${JSON.stringify(b.getAttribute('label'))}、種類=${JSON.stringify(b.getAttribute('type'))}` : 'ボタン未表示';
        check();
        return readyPanelAction(p, action);
      }, 20000, `パネルの${action === 'save' ? '保存' : 'キャンセル'}前の照合`);
    } catch (e) {
      throw new Error(`${e.message}\nパネルの${action === 'save' ? '保存' : 'キャンセル'}準備：${observed}`);
    }
  }
  function checkNoErrors() {
    const errors = [...document.querySelectorAll('[data-testid="fieldError"]')].filter(x => text(x));
    assert(errors.length === 0, 'Amazonの入力エラーがあるため、保存を中止しました。');
  }
  async function tabId() {
    return new Promise(resolve => GM_getTab(tab => {
      if (!tab.pm30Id) { tab.pm30Id = crypto.randomUUID(); GM_saveTab(tab); }
      resolve(tab.pm30Id);
    }));
  }
  async function runSeller() {
    const match = location.hash.match(/^#pricetar-max30=([a-f0-9-]{36})$/);
    if (!match) return; // Never act on an ordinary user-opened Seller Central page.
    const token = match[1];
    const first = getJob(token);
    if (!first) return;
    if (first.version !== VERSION) {
      panel(`プライスターの画面が別の版（v${first.version}）のままです。プライスターのページを再読み込みしてから、もう一度ボタンを押してください。`, true);
      return;
    }
    if (terminal(first.state)) {
      panel(first.message + '\nSKU：' + first.sku, first.state !== 'verified');
      return;
    }
    if (Date.now() - first.createdAt >= TTL) {
      writeJob(first, 'failed', '処理の有効時間を過ぎたため自動操作を止めました。ボタンをもう一度押してください。');
      panel(first.message + '\nSKU：' + first.sku, true);
      return;
    }
    const owner = await tabId();
    if (first.owner && first.owner !== owner) {
      panel('同じ処理が別タブで開かれています。こちらでは保存しません。', true);
      return;
    }
    if (!navigator.locks) {
      writeJob(first, 'failed', '重複保存防止機能を利用できません。');
      panel(first.message, true);
      return;
    }
    // Browser-origin Web Lock serializes competing copies before either can edit.
    await navigator.locks.request(PREFIX + 'seller-save', { ifAvailable: true }, async lock => {
      if (!lock) { panel('別の購入上限処理が進行中です。このタブでは保存しません。', true); return; }
      const job = getJob(token);
      if (!job || (job.owner && job.owner !== owner) || terminal(job.state)) {
        panel('この処理は別タブで進行中、または完了しています。こちらでは保存しません。', true); return;
      }
      job.owner = owner;
      const stop = heartbeat(token);
      try {
        await work(job);
      } catch (e) {
        await recover(job, e);
      } finally {
        stop();
      }
    });
  }
  const tries = job => job.attempt > 1 ? `（${job.attempt}/${MAX_ATTEMPTS}回目）` : '';
  async function work(job) {
    job.attempt = job.attempt || 1;
    if (['opening', 'editing'].includes(job.state)) {
      // The previous load stopped before anything was sent. Unsent staged
      // edits vanish with the reload, so starting over is safe.
      job.attempt += 1;
      job.step = '';
      assert(job.attempt <= MAX_ATTEMPTS, '入力途中での再読み込みが続いたため中止しました。');
    }
    const sent = ['submitting', 'submitted'].includes(job.state);
    if (sent) writeJob(job, job.state, job.message);
    else writeJob(job, 'opening', 'AmazonのSKUと入力欄を確認しています。' + tries(job));
    panel((sent ? '送信した値を確認しています。' : '購入上限30個：確認中' + tries(job)) + '\nSKU：' + job.sku);
    job.step = 'Amazon画面の確認';
    const layout = await allFields(job);
    checkIdentity(document, location.href, job);
    onlyExpectedEdit(editCounts(document), 0);
    checkNoErrors();
    const field = maxField(document);
    if (field.input.value === '30') {
      writeJob(job, 'verified', 'Amazon編集画面を開き、最大注文可能個数30を確認しました。');
      panel('購入上限30個：確認完了 ✓\n' + job.title + '\nSKU：' + job.sku);
      field.input.scrollIntoView({ block: 'center' });
      return;
    }
    if (sent) {
      // Amazon can take a while before the edit page shows a submitted value.
      const now = field.input.value || '空欄';
      job.checks = (job.checks || 0) + 1;
      if (job.checks < VERIFY_WAITS.length) {
        writeJob(job, 'submitted', `送信済みです。Amazonの反映を待って開き直します（${job.checks}/${VERIFY_WAITS.length - 1}、現在の値：${now}）。`);
        panel(job.message + '\nSKU：' + job.sku);
        return reloadAfter(VERIFY_WAITS[job.checks]);
      }
      if ((job.submits || 0) >= MAX_SUBMITS) {
        writeJob(job, 'pending', `${job.submits}回送信しましたが、Amazon画面ではまだ30になっていません（現在の値：${now}）。`
          + 'Amazon側の反映待ちの可能性があります。時間をおいてボタンを押すと、もう一度確認します。');
        panel(job.message + '\nSKU：' + job.sku, true);
        return;
      }
      // Sending 30 again is harmless (same value), and every guard still applies.
      job.attempt = 1;
    }
    await setAndSubmit(job, layout);
  }
  async function setAndSubmit(job, layout) {
    job.step = '入力前の状態の記録';
    const before = await settled(() => protectedSnapshot(document), '入力欄の表示');
    checkIdentity(document, location.href, job);
    onlyExpectedEdit(editCounts(document), 0);
    checkNoErrors();
    const oldMax = maxField(document).input.value;
    writeJob(job, 'editing', '最大注文可能個数だけを30に入力しています。' + tries(job), { oldMax });
    job.step = '購入上限の入力';
    setOnlyMax(document);
    await until(() => maxField(document).host.getAttribute('value') === '30'
      && (layout.panel || editCounts(document).some(([id, n]) => id === 'hub-item-box-offer' && n === 1)), 12000, '購入上限30の入力反映');
    if (layout.panel) {
      job.step = 'パネルの保存と照合';
      panel('日本の編集パネルで購入上限だけを保存・照合しています。\nSKU：' + job.sku);
      await savePanelAndVerify(job, before, layout.outside);
    }
    // Amazon validates asynchronously: the edit count becomes 1 before
    // the button changes from 送信 to 変更を送信 and sets its ready flag.
    // Wait for that state, then repeat ALL protection checks immediately
    // before clicking. Never weaken the guard or click the initial button.
    job.step = '送信ボタンの準備待ち';
    panel('Amazonの保存準備が完了するのを待っています。\nSKU：' + job.sku);
    const validateBeforeSubmit = () => {
      if (layout.panel) {
        checkPageIdentity(document, location.href, job);
        assert(!offerPanel(document), '編集パネルが開いたため送信を中止しました。');
        sameProtected(layout.outside, outsidePanelSnapshot(document));
      } else {
        checkIdentity(document, location.href, job);
        sameProtected(before, protectedSnapshot(document));
        assert(maxField(document).input.value === '30', '購入上限の値が30ではありません。');
      }
      onlyExpectedEdit(editCounts(document), 1);
      checkNoErrors();
    };
    const submit = await waitSubmitReady(document, validateBeforeSubmit);
    validateBeforeSubmit();
    assert(readySubmit(document) === submit, '保存ボタンの状態が変わったため中止しました。');
    // Persist BEFORE click; after a crash the next load only reads the value back.
    writeJob(job, 'submitting', '購入上限30個だけを送信しています。',
      { submittedAt: Date.now(), submits: (job.submits || 0) + 1, checks: 0 });
    clickKat(submit);
    job.step = '送信結果の確認';
    // The read-back after reloading is the real proof, so a missing or reworded
    // completion dialog is not an error.
    const accepted = await until(() => deepAll(document, '[role="dialog"],kat-modal')
      .some(d => text(d).includes('編集内容が送信されました') && text(d).includes('すべて完了しました。')),
    45000, 'Amazonの送信完了表示').then(() => true, () => false);
    writeJob(job, 'submitted', accepted ? 'Amazonが変更を受け付けました。画面を開き直して30を確認します。'
      : '送信しました（完了表示は確認できませんでした）。画面を開き直して30になったか確認します。');
    panel(job.message + '\nSKU：' + job.sku);
    return reloadAfter(VERIFY_WAITS[0]);
  }
  async function recover(job, e) {
    // No rollback. Protected fields are never written, even on failure. Before
    // sending, a fresh page load discards everything; after sending, only the
    // value is read back (a new send happens only in work(), after read-backs).
    const detail = (job.step ? `［${job.step}］` : '') + e.message;
    const expired = Date.now() - job.createdAt >= TTL;
    if (['submitting', 'submitted'].includes(job.state)) {
      job.checks = (job.checks || 0) + 1;
      if (job.checks < VERIFY_WAITS.length && !expired) {
        writeJob(job, 'submitted', '送信済みです。確認中に画面がうまく動かなかったため、開き直して確認します。\n' + detail);
        panel(job.message + '\nSKU：' + job.sku);
        return reloadAfter(VERIFY_WAITS[job.checks]);
      }
      writeJob(job, 'pending', '送信済みですが、30になったことを確認できませんでした。'
        + 'ボタンをもう一度押すと確認し、30でなければ設定し直します。\n' + detail);
      panel(job.message + '\nSKU：' + job.sku, true);
      return;
    }
    const unsent = job.submits ? '再送信はしていません。' : '送信はしていません。';
    if (job.attempt < MAX_ATTEMPTS && !expired) {
      job.attempt += 1;
      writeJob(job, 'retrying', `うまく進まなかったため、画面を開き直してやり直します（${job.attempt}/${MAX_ATTEMPTS}回目）。${unsent}\n` + detail);
      panel(job.message + '\nSKU：' + job.sku);
      return reloadAfter(2500);
    }
    writeJob(job, 'failed', `${job.attempt}回試しましたが設定できませんでした。${unsent}`
      + 'ボタンをもう一度押すとやり直します。\n' + detail);
    panel(job.message + '\nSKU：' + job.sku, true);
  }
  async function reloadAfter(ms) {
    await sleep(ms);
    location.reload();
    await sleep(60000); // keep the lock and heartbeat until the page goes away
  }
  if (location.hostname === 'jp3.pricetar.com') {
    addButtons();
    let timer;
    new MutationObserver(changes => {
      if (!changes.some(change => [...change.addedNodes].some(n => n.nodeType === 1 && !n.classList?.contains('pm30-button')))) return;
      clearTimeout(timer); timer = setTimeout(addButtons, 300);
    }).observe(document.body, { childList: true, subtree: true });
    setInterval(addButtons, 2500);
  } else if (location.hostname === 'sellercentral.amazon.co.jp') {
    runSeller().catch(e => panel(e.message, true));
  }
})();
