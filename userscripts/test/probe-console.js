// Paste into the browser console on the Seller Central edit page (where the
// 最大注文可能個数 box is visible), then type 30 into the box by hand and click
// outside it. Records how Amazon's box reacts to real typing. Saves nothing.
(async () => {
  const host = [...document.querySelectorAll('kat-input')].find(x => x.id === 'max_order_quantity-0-value');
  if (!host) { console.log('最大注文可能個数の欄が見つかりません。欄が見えている画面で実行してください。'); return; }
  const input = host.shadowRoot?.querySelector('input');
  const lines = [];
  const add = (...a) => lines.push(a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' '));
  const label = () => {
    const l = document.querySelector('#hub-item-box-offer [data-testid="hub-nav-item-state-label"]');
    return l ? (l.getAttribute('text') ?? l.textContent.trim()) : 'なし';
  };
  const now = () => ({ 表示: input?.value, 属性: host.getAttribute('value'), プロパティ: String(host.value),
    出品情報: label(), 送信ボタン: document.getElementById('form-submit-button')?.textContent.trim() });
  add('host', host.tagName, [...host.attributes].map(a => `${a.name}=${a.value.slice(0, 30)}`).join(' | '));
  add('hostのキー', Object.keys(host).join(','));
  add('inputのキー', input ? Object.keys(input).join(',') : 'inputなし');
  add('inputの数', host.shadowRoot?.querySelectorAll('input').length, 'type', input?.type);
  add('shadow', host.shadowRoot ? host.shadowRoot.innerHTML.replace(/\s+/g, ' ').slice(0, 500) : 'なし');
  try {
    add('hostの監視', Object.keys(getEventListeners(host)).join(','));
    add('inputの監視', Object.keys(getEventListeners(input)).join(','));
  } catch { add('監視の一覧は取得できません'); }
  for (const node of [host, input]) {
    const key = Object.keys(node || {}).find(x => x.startsWith('__reactProps'));
    if (key) add(node === host ? 'hostのReact' : 'inputのReact', Object.keys(node[key]).join(','));
  }
  add('開始時', now());
  const t0 = performance.now();
  let typed = false, done = false;
  const seen = (where, e) => {
    const detail = e.detail !== undefined && e.detail !== 0 ? JSON.stringify(e.detail)?.slice(0, 80) : '';
    add(`${Math.round(performance.now() - t0)}ms`, where, e.type, e.isTrusted ? '本物' : 'スクリプト', detail, `表示=${input.value}`, `属性=${host.getAttribute('value')}`);
    if (e.isTrusted && e.type === 'input') typed = true;
    if (typed && e.isTrusted && ['focusout', 'blur'].includes(e.type)) done = true;
  };
  const types = ['keydown', 'beforeinput', 'input', 'keyup', 'change', 'focusin', 'focusout', 'blur'];
  const onInput = e => seen('input欄', e);
  const onHost = e => { if (e.composedPath()[0] === host) seen('host', e); };
  for (const t of types) { input.addEventListener(t, onInput, true); host.addEventListener(t, onHost, true); }
  // Katal may announce the edit with its own event on the host; log those too.
  const original = EventTarget.prototype.dispatchEvent;
  EventTarget.prototype.dispatchEvent = function (e) {
    if ((this === host || this === input) && !types.includes(e.type)) seen(this === host ? 'host発行' : 'input発行', e);
    return original.call(this, e);
  };
  console.log('%c準備できました。「最大注文可能個数」の欄をクリックし、中身を消して 30 と手で入力してから、欄の外をクリックしてください。', 'font-size:16px;color:#c00');
  const end = Date.now() + 60000;
  while (Date.now() < end && !done) await new Promise(r => setTimeout(r, 300));
  await new Promise(r => setTimeout(r, 3000));
  EventTarget.prototype.dispatchEvent = original;
  for (const t of types) { input.removeEventListener(t, onInput, true); host.removeEventListener(t, onHost, true); }
  add('終了時', now());
  const report = lines.join('\n');
  console.log(report);
  try { copy(report); console.log('%c結果をコピーしました。チャットに貼り付けて送ってください。', 'font-size:16px;color:#060'); }
  catch { console.log('%c上の結果をスクリーンショットで送ってください。', 'font-size:16px;color:#060'); }
})();
