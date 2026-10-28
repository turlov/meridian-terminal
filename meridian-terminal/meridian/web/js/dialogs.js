// Dialogs: order ticket, decision detail, add ticker, close position, first-run welcome.
import { S, on, h, add, fmt, get, post, toast, modal, confirmDialog, select, clear, RULE_LABELS, acctLabel, heldQty, nameOf } from './core.js';
import { outcome } from './panels/decisions.js';

// ---------- order ticket ----------
export async function orderTicket({ ticker, side = 'BUY', qty, limit, stop, target } = {}) {
  ticker = (ticker || S.selected || '').toUpperCase();
  if (!ticker) { toast('Select a ticker first', 'warn'); return; }
  const acct = S.app.acct;
  if (acct === 'off') {
    toast('Execution is off (signals only). Choose Paper or Live in the Account panel to place orders.', 'warn', 7000);
    return;
  }
  let suggestion = null;
  if (side === 'BUY' && (qty === undefined || stop === undefined)) {
    try { suggestion = (await get(`/api/ticker/${encodeURIComponent(ticker)}`)).suggestion; } catch { /* optional */ }
  }
  const q = S.quotes[ticker] || {};
  const slip = ((S.settings.risk || {}).max_slippage_pct ?? 0.5) / 100;
  const live = acct === 'live';
  let curSide = side;
  const inp = (val, attrs = {}) => h('input', { class: 'inp', inputmode: 'decimal', value: val ?? '', ...attrs });
  const qtyIn = inp(qty ?? (side === 'SELL' ? heldQty(ticker) || '' : suggestion?.qty || 1));
  const limIn = inp(limit ?? defaultLimit(side));
  const stopIn = inp(stop ?? suggestion?.stop ?? '');
  const tgtIn = inp(target ?? suggestion?.target ?? '');
  const summary = h('div', { class: 'row', style: { margin: '8px 0 0', gap: '16px', flexWrap: 'wrap', color: 'var(--muted)' } });
  const err = h('div', { class: 'err-text' });
  const liveCheck = h('input', { type: 'checkbox' });
  const sideSeg = h('div', { class: 'seg' },
    ['BUY', 'SELL'].map((s) => h('button', { type: 'button', 'data-s': s, class: s === side ? 'on' : '',
      onclick: () => setSide(s) }, s === 'BUY' ? 'Buy' : 'Sell')));
  const levels = h('div', { class: 'grid2' },
    h('div', { class: 'field' }, h('label', {}, 'Stop (optional)'), stopIn),
    h('div', { class: 'field' }, h('label', {}, 'Target (optional)'), tgtIn));
  let submitBtn;

  function defaultLimit(s) {
    const px = s === 'BUY' ? (q.ask || q.last) : (q.bid || q.last);
    if (!px) return '';
    return (s === 'BUY' ? px * (1 + slip / 2) : px * (1 - slip / 2)).toFixed(2);
  }
  function setSide(s) {
    curSide = s;
    for (const b of sideSeg.children) b.classList.toggle('on', b.dataset.s === s);
    limIn.value = defaultLimit(s);
    if (s === 'SELL') qtyIn.value = heldQty(ticker) || '';
    levels.hidden = s === 'SELL';
    update();
  }
  function update() {
    const qn = +qtyIn.value, ln = +limIn.value, sn = +stopIn.value;
    const val = qn * ln;
    const parts = [['Value', fmt.money(val)]];
    if (curSide === 'BUY' && sn > 0 && sn < ln) parts.push(['Risk to stop', fmt.money((ln - sn) * qn)]);
    if (q.last) parts.push(['Last', fmt.px(q.last)]);
    parts.push(['Account', acctLabel()]);
    clear(summary);
    for (const [k, v] of parts) summary.append(h('span', {}, `${k} `, h('b', { style: { color: 'var(--text)', fontWeight: 400 } }, v)));
    if (submitBtn) {
      submitBtn.textContent = `${live ? 'Send LIVE' : 'Place ' + acctLabel().toLowerCase()} ${curSide === 'BUY' ? 'buy' : 'sell'}`;
      submitBtn.className = `btn ${live ? 'danger' : curSide === 'BUY' ? 'go' : 'sell'}`;
    }
  }
  [qtyIn, limIn, stopIn].forEach((el) => el.addEventListener('input', update));

  const close = modal({
    title: `Order ticket: ${ticker}`, code: 'TKT',
    body: (el) => {
      add(el,
        h('p', { class: 'dim', style: { fontSize: '13px' } }, `${nameOf(ticker)}  Bid ${fmt.px(q.bid)}  Ask ${fmt.px(q.ask)}  Limit orders only, valid for the day, never on margin.`),
        h('div', { class: 'row', style: { marginBottom: '10px' } }, sideSeg),
        h('div', { class: 'grid2' },
          h('div', { class: 'field' }, h('label', {}, 'Quantity (shares)'), qtyIn),
          h('div', { class: 'field' }, h('label', {}, 'Limit price'), limIn)),
        levels, summary,
        side === 'BUY' && suggestion && suggestion.qty === 0 ? h('div', { class: 'help cond', style: { marginTop: '6px', color: 'var(--key)' } },
          'Your risk settings size this at 0 shares (one share costs more than your max position size). Manual orders use the manual order cap instead.') : null,
        live ? h('label', { class: 'check', style: { marginTop: '10px', color: '#ffb3b3' } }, liveCheck,
          h('span', {}, 'I understand this sends a real order to Freedom Broker.')) : null,
        err);
      levels.hidden = side === 'SELL';
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') submit(); });
    },
    actions: [{ label: 'Cancel', kind: 'ghost' }, { label: 'Place', kind: 'go', onClick: () => submit() }],
  });
  submitBtn = [...document.querySelectorAll('.modal-f .btn')].pop();
  update();

  async function submit() {
    err.textContent = '';
    if (live && !liveCheck.checked) { err.textContent = 'Tick the confirmation box to send a live order.'; return; }
    submitBtn.disabled = true;
    try {
      const res = await post('/api/order', { ticker, side: curSide, qty: +qtyIn.value, limit: +limIn.value,
        stop: curSide === 'BUY' ? (stopIn.value || null) : null, target: curSide === 'BUY' ? (tgtIn.value || null) : null });
      const o = res.order || {};
      toast(`${curSide} ${qtyIn.value} ${ticker} @ ${limIn.value}: ${o.status || 'sent'}`, live ? 'live' : 'fill');
      close();
    } catch (e) {
      err.textContent = e.message;
      submitBtn.disabled = false;
    }
  }
}

// ---------- close a position ----------
export async function closePosition(ticker) {
  const qty = heldQty(ticker);
  const live = S.app.acct === 'live';
  const ok = await confirmDialog({ title: `Close ${ticker}`,
    text: `Sell all ${fmt.num(qty, 0)} shares of ${ticker} with a limit just under the bid (${acctLabel().toLowerCase()} account).`,
    confirmLabel: live ? 'Send LIVE sell' : 'Close position', danger: live });
  if (!ok) return;
  try {
    const r = await post('/api/position/close', { ticker });
    toast(`Close ${ticker}: ${(r.order || {}).status || 'sent'}`, live ? 'live' : 'fill');
  } catch (e) { toast(e.message, 'error'); }
}

// ---------- decision detail ----------
export async function decisionDetail(id) {
  let d;
  try { d = await get(`/api/decision/${id}`); } catch (e) { toast(e.message, 'error'); return; }
  const v = d.verdict;
  const [cls, label, text] = outcome(d);
  const s = d.snapshot;
  modal({
    title: `${d.ticker}  ${fmt.date(d.ts)} ${fmt.time(d.ts)}`, code: 'AI', wide: true,
    body: (el) => {
      el.append(h('div', { class: 'section-h', style: { padding: '0 0 4px' } }, 'Proposed by'));
      for (const c of d.candidates || []) {
        el.append(h('div', { class: 'prose', style: { marginBottom: '4px' } },
          h('span', { class: 'amber' }, `${RULE_LABELS[c.strategy] || c.strategy} `),
          h('span', { class: 'dim' }, `${c.action} strength ${fmt.num(c.strength, 2)}  `), c.evidence));
      }
      el.append(h('div', { class: 'section-h', style: { padding: '10px 0 4px' } }, 'Reviewer'));
      if (v) {
        el.append(h('div', { style: { marginBottom: '6px' } },
          h('span', { class: `verdict ${v.action}` }, v.action), `  confidence ${fmt.num(v.confidence * 100, 0)}%  horizon ${v.horizon}  `,
          h('span', { class: 'dim' }, `${v.model || ''}${v.latency ? `  ${v.latency}s` : ''}`)),
          h('p', {}, v.reasoning),
          h('p', {}, h('span', { class: 'dim' }, 'Against: '), v.conflicts || 'none'));
      } else {
        el.append(h('p', { class: 'dim' }, 'Not reviewed.'));
      }
      el.append(h('div', { class: 'section-h', style: { padding: '6px 0 4px' } }, 'Risk gate'),
        h('div', { style: { marginBottom: '8px' } }, h('span', { class: `res ${cls}` }, label), '  ', text,
          d.order ? h('div', { class: 'dim', style: { marginTop: '4px' } },
            `${d.order.side} ${d.order.qty} @ ${fmt.px(d.order.limit)}${d.order.stop ? `  stop ${fmt.px(d.order.stop)}` : ''}${d.order.target ? `  target ${fmt.px(d.order.target)}` : ''}  (${d.mode} account)`) : null));
      if (s) {
        el.append(h('div', { class: 'section-h', style: { padding: '6px 0 4px' } }, 'Chart at decision time'),
          h('div', { class: 'kv', style: { padding: 0 } },
            ...[['Last', fmt.px(s.last)], ['1d', fmt.frac(s.ret1)], ['20d', fmt.frac(s.ret20)], ['RSI 14', fmt.num(s.rsi14, 1)],
              ['ATR 14', fmt.px(s.atr14)], ['Vol / 20d', `${fmt.num(s.vol_ratio, 1)}x`], ['SMA 50', fmt.px(s.sma50)],
              ['SMA 200', fmt.px(s.sma200)], ['20d high', fmt.px(s.high20_prev)]]
              .map(([k, val]) => h('div', {}, h('span', {}, k), h('b', {}, val)))));
      }
      if ((d.headlines || []).length) {
        el.append(h('div', { class: 'section-h', style: { padding: '10px 0 4px' } }, 'Headlines the reviewer saw'),
          h('div', { class: 'mini-list', style: { padding: 0 } }, d.headlines.map((x) => h('div', { title: x }, x))));
      }
    },
    actions: [
      { label: `Show ${d.ticker}`, kind: 'ghost', onClick: (close) => { select(d.ticker); close(); } },
      { label: 'Close', kind: 'primary' },
    ],
  });
}

// ---------- add ticker ----------
export function addTicker(prefill = '') {
  const input = h('input', { class: 'inp', placeholder: 'Ticker or company, e.g. MSFT.US or Microsoft', value: prefill, style: { width: '100%' } });
  const kw = h('input', { class: 'inp', placeholder: 'Words that identify it in headlines, comma separated', style: { width: '100%' } });
  const pop = h('div', { class: 'search-pop', hidden: true });
  const err = h('div', { class: 'err-text' });
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const qv = input.value.trim();
    if (qv.length < 2) { pop.hidden = true; return; }
    timer = setTimeout(async () => {
      try {
        const res = await get(`/api/search?q=${encodeURIComponent(qv)}`);
        clear(pop);
        for (const r of res) {
          pop.append(h('div', { onclick: () => { input.value = r.ticker; if (!kw.value && r.name) kw.value = r.name; pop.hidden = true; } },
            h('span', { class: 'amber' }, r.ticker), h('span', { class: 'dim' }, `${r.name || ''} ${r.exchange || ''}`)));
        }
        pop.hidden = !res.length;
      } catch { pop.hidden = true; }
    }, 250);
  });
  const close = modal({
    title: 'Add to watchlist', code: 'ADD',
    body: (el) => el.append(
      h('div', { class: 'field', style: { position: 'relative' } }, h('label', {}, 'Tradernet ticker'), input, pop),
      h('div', { class: 'field' }, h('label', {}, 'Headline keywords'), kw,
        h('span', { class: 'help' }, 'Used to match news to this ticker. The company name is usually enough.')),
      err),
    actions: [{ label: 'Cancel', kind: 'ghost' }, { label: 'Add ticker', kind: 'primary', onClick: () => save() }],
  });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  async function save() {
    let t = input.value.trim().toUpperCase();
    if (!t) { err.textContent = 'Enter a ticker.'; return; }
    if (!t.includes('.')) t += '.US';
    const wl = S.settings.watchlist || [];
    if (wl.some((w) => w.ticker === t)) { err.textContent = `${t} is already on the watchlist.`; return; }
    const keywords = kw.value.split(',').map((x) => x.trim()).filter(Boolean);
    try {
      await post('/api/settings', { watchlist: [...wl, { ticker: t, keywords }] });
      toast(`Added ${t}`);
      close();
      setTimeout(() => select(t), 400);
    } catch (e) { err.textContent = e.message; }
  }
}

export async function removeTicker(t) {
  const wl = (S.settings.watchlist || []).filter((w) => w.ticker !== t);
  if (wl.length === (S.settings.watchlist || []).length) { toast(`${t} is not on the watchlist`, 'warn'); return; }
  try { await post('/api/settings', { watchlist: wl }); toast(`Removed ${t}`); } catch (e) { toast(e.message, 'error'); }
}

// ---------- first run ----------
export function welcome() {
  const close = modal({
    title: 'Welcome to Meridian Terminal', code: 'HI', wide: true,
    body: (el) => {
      el.append(
        h('p', {}, 'Meridian watches your stocks, scores the news with Claude, proposes trades from simple rules, and lets Claude veto the weak ones before a hard-coded risk gate decides. Orders go to a paper account until you choose otherwise.'),
        h('div', { class: 'choice' },
          h('button', { onclick: async () => { await finish('demo'); close(); } },
            h('b', {}, 'Explore with demo data'), 'Simulated prices, headlines and a simulated reviewer. No keys needed, nothing real happens.'),
          h('button', { onclick: () => { close(); connect(); } },
            h('b', {}, 'Connect Freedom Broker and Claude'), 'Add your Tradernet and Anthropic API keys to use live market data. Trading stays on paper.')));
    },
  });
}

async function finish(mode) {
  try { await post('/api/settings', { onboarded: true, data_mode: mode }); } catch (e) { toast(e.message, 'error'); }
}

export function connect() {
  const fields = [
    ['anthropic_api_key', 'Anthropic API key', 'From console.anthropic.com > API keys', 'anthropic'],
    ['tradernet_public_key', 'Tradernet public key', 'Freedom Broker / Tradernet > profile > API keys', null],
    ['tradernet_private_key', 'Tradernet private key', '', 'tradernet'],
    ['finnhub_api_key', 'Finnhub key (optional)', 'Extra US company news, free at finnhub.io', 'finnhub'],
  ];
  const inputs = {};
  const status = {};
  const err = h('div', { class: 'err-text' });
  const close = modal({
    title: 'Connect your accounts', code: 'KEY', wide: true,
    body: (el) => {
      const where = S.settings.secrets_backend === 'file' ? 'a protected file in the data folder' : S.settings.secrets_backend;
      el.append(h('p', {}, `Keys are stored in ${where || 'your system keychain'} on this computer and only sent to Anthropic and Freedom Broker.`));
      for (const [k, label, help, test] of fields) {
        const sec = (S.settings.secrets || {})[k] || {};
        inputs[k] = h('input', { class: 'inp', type: 'password', placeholder: sec.set ? `saved: ${sec.masked}` : '', autocomplete: 'off', spellcheck: 'false' });
        status[k] = h('span', { class: 'keystat' });
        el.append(h('div', { class: 'keyrow' }, h('label', {}, label), inputs[k],
          test ? h('button', { class: 'btn sm', onclick: () => testKey(test, k) }, 'Test') : h('span')),
          h('div', { class: 'keyhelp' }, h('span', {}, help), status[k]));
      }
      el.append(err);
    },
    actions: [{ label: 'Use demo data for now', kind: 'ghost', onClick: async (c) => { await saveKeys(); await finish('demo'); c(); } },
      { label: 'Save and use live data', kind: 'primary', onClick: async (c) => {
        if (!(await saveKeys())) return;
        const sec = S.settings.secrets || {};
        if (!(sec.tradernet_public_key || {}).set || !(sec.tradernet_private_key || {}).set) {
          err.textContent = 'Live data needs both Tradernet keys.'; return;
        }
        await finish('live'); c(); toast('Switching to live Tradernet data. Execution stays on paper.');
      } }],
  });

  async function saveKeys() {
    const body = {};
    for (const k of Object.keys(inputs)) if (inputs[k].value.trim()) body[k] = inputs[k].value.trim();
    if (!Object.keys(body).length) return true;
    try {
      S.settings = await post('/api/secrets', body);
      for (const k of Object.keys(body)) { inputs[k].value = ''; inputs[k].placeholder = `saved: ${S.settings.secrets[k].masked}`; }
      return true;
    } catch (e) { err.textContent = e.message; return false; }
  }
  async function testKey(service, k) {
    if (!(await saveKeys())) return;
    const el = status[k];
    el.className = 'keystat dim'; el.textContent = 'Testing…';
    try {
      const r = await post(`/api/test/${service}`);
      el.className = 'keystat up'; el.textContent = '✓ ' + r.message;
    } catch (e) { el.className = 'keystat down'; el.textContent = '✕ ' + e.message; }
  }
  return close;
}

on('dialog:ticket', (o) => orderTicket(o));
on('dialog:close', (t) => closePosition(t));
on('dialog:decision', (id) => decisionDetail(id));
on('dialog:add', (t) => addTicker(t || ''));
