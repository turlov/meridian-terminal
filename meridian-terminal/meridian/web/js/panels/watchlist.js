// WL — watchlist monitor: live quotes, day range, RSI, trend, firing rules, position.
import { S, on, h, fmt, panel, select, clear, setText, RULE_SHORT, RULE_LABELS, nameOf, heldQty, post, toast, watchlist, emit } from '../core.js';

const COLS = [
  ['Ticker', ''], ['Last', 'num'], ['Net', 'num c-net'], ['%Chg', 'num'], ['Bid', 'num c-bid'],
  ['Ask', 'num c-ask'], ['Volume', 'num c-vol'], ['Day range', 'c-rng'], ['RSI', 'num'],
  ['Tr', 'c-trend'], ['Signals', ''], ['Pos', 'num'],
];

export function mountWatchlist(grid) {
  const p = panel('watch', 'WL', 'Monitor', [
    h('button', { class: 'tbtn', title: 'Add a ticker', onclick: () => emit('dialog:add') }, '+ Add'),
    h('button', { class: 'tbtn', title: 'Re-run the rule scan now', onclick: async () => {
      try { await post('/api/control', { action: 'scan' }); toast('Scanning the watchlist'); } catch (e) { toast(e.message, 'error'); }
    } }, 'Scan now'),
  ]);
  grid.append(p.el);
  const tbody = h('tbody');
  const table = h('table', { class: 't' },
    h('thead', {}, h('tr', {}, COLS.map(([t, c]) => h('th', { class: c }, t)))), tbody);
  const wrap = h('div', { class: 'wl-wrap' }, table);
  p.body.append(wrap);
  const rows = new Map();

  function build() {
    const list = watchlist();
    clear(tbody);
    rows.clear();
    if (!list.length) {
      tbody.append(h('tr', {}, h('td', { colspan: COLS.length, class: 'wrap' },
        h('div', { class: 'empty' }, 'Your watchlist is empty. Type a ticker in the command line, e.g. ', h('b', {}, 'ADD NVDA.US')))));
      return;
    }
    for (const t of list) {
      const cells = {};
      const mk = (key, cls = '') => (cells[key] = h('td', { class: cls }));
      const tr = h('tr', { class: 'clickable', 'data-t': t, onclick: () => select(t),
        ondblclick: () => emit('dialog:ticket', { ticker: t, side: 'BUY' }) },
        mk('tk', 'tk'), mk('last', 'num'), mk('net', 'num c-net'), mk('pct', 'num'), mk('bid', 'num c-bid'),
        mk('ask', 'num c-ask'), mk('vol', 'num c-vol'), mk('rng', 'c-rng'), mk('rsi', 'num'),
        mk('trend', 'c-trend'), mk('sig'), mk('pos', 'num'));
      cells.tk.append(h('span', {}, t), h('span', { class: 'nm' }));
      cells.rngBar = h('span', { class: 'rng' }, h('i'));
      cells.rng.append(cells.rngBar);
      rows.set(t, { tr, cells, last: null });
      tbody.append(tr);
      update(t);
    }
    highlight();
  }

  function update(t) {
    const r = rows.get(t);
    if (!r) return;
    const c = r.cells;
    const q = S.quotes[t] || {};
    const snapEntry = S.snapshots[t];
    const snap = snapEntry && snapEntry.snap;
    setText(c.tk.lastChild, nameOf(t));
    c.tk.title = `${t} ${nameOf(t)}`;
    if (q.last !== undefined) {
      if (r.last !== null && q.last !== r.last) {
        c.last.classList.remove('flash-up', 'flash-down');
        void c.last.offsetWidth;
        c.last.classList.add(q.last > r.last ? 'flash-up' : 'flash-down');
      }
      r.last = q.last;
    }
    setText(c.last, fmt.px(q.last));
    setText(c.net, fmt.signed(q.chg));
    c.net.className = `num c-net ${fmt.cls(q.chg)}`;
    setText(c.pct, fmt.pct(q.chg_pct));
    c.pct.className = `num ${fmt.cls(q.chg_pct)}`;
    setText(c.bid, fmt.px(q.bid));
    setText(c.ask, fmt.px(q.ask));
    setText(c.vol, fmt.compact(q.volume));
    if (q.high > q.low) {
      const pos = Math.min(1, Math.max(0, (q.last - q.low) / (q.high - q.low)));
      c.rngBar.firstChild.style.left = `calc(${(pos * 100).toFixed(1)}% - 1px)`;
      c.rng.title = `Low ${fmt.px(q.low)}  High ${fmt.px(q.high)}`;
    }
    if (snap) {
      setText(c.rsi, fmt.num(snap.rsi14, 0));
      c.rsi.className = `num ${snap.rsi14 >= 70 ? 'down' : snap.rsi14 <= 30 ? 'up' : ''}`;
      const last = q.last || snap.last;
      const up = last > snap.sma50 && snap.sma50 > snap.sma200;
      const down = last < snap.sma50 && snap.sma50 < snap.sma200;
      setText(c.trend, up ? '▲' : down ? '▼' : '◆');
      c.trend.className = `c-trend ${up ? 'trend-up' : down ? 'trend-down' : 'trend-mix'}`;
      c.trend.title = `${up ? 'Uptrend' : down ? 'Downtrend' : 'Mixed'}: SMA50 ${fmt.px(snap.sma50)}, SMA200 ${fmt.px(snap.sma200)}`;
    }
    clear(c.sig);
    for (const s of (snapEntry && snapEntry.signals) || []) {
      c.sig.append(h('span', { class: `sig ${s.includes('exit') ? 'exit' : ''}`, title: RULE_LABELS[s] || s }, RULE_SHORT[s] || s));
    }
    if (hasMaterialNews(t)) c.sig.append(h('span', { class: 'sig news', title: 'Material news in the last hour' }, 'NEWS'));
    const qty = heldQty(t);
    setText(c.pos, qty ? fmt.num(qty, 0) : '');
    c.pos.className = `num ${qty > 0 ? 'up' : ''}`;
  }

  function hasMaterialNews(t) {
    const min = (S.settings.ai || {}).min_triage_score ?? 6;
    const since = Date.now() / 1000 - 3600;
    return S.news.some((n) => n.published > since && n.score >= min && (n.tickers || []).includes(t));
  }

  function highlight() {
    for (const [t, r] of rows) r.tr.classList.toggle('sel', t === S.selected);
    const sel = rows.get(S.selected);
    if (sel) sel.tr.scrollIntoView({ block: 'nearest' });
  }

  on('state', build);
  on('settings', () => {
    const list = watchlist();
    if (list.length !== rows.size || list.some((t) => !rows.has(t))) build();
  });
  on('quotes', (q) => Object.keys(q).forEach(update));
  on('snapshot', (e) => update(e.ticker));
  on('positions', () => rows.forEach((_, t) => update(t)));
  on('news_score', () => rows.forEach((_, t) => update(t)));
  on('select', highlight);
  return p;
}

export function moveSelection(delta) {
  const list = watchlist();
  if (!list.length) return;
  const i = Math.max(0, list.indexOf(S.selected));
  select(list[(i + delta + list.length) % list.length]);
}
