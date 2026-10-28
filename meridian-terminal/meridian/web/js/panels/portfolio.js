// PORT — positions (live P&L), orders and trade history for the active account.
import { S, on, h, fmt, panel, clear, setText, select, post, toast, emit, getToken, acctLabel } from '../core.js';

const TABS = [['pos', 'Positions'], ['ord', 'Orders'], ['trd', 'Trades']];

export function mountPortfolio(grid) {
  let tab = 'pos';
  const tabBtns = TABS.map(([k, label]) => h('button', { class: `tab ${k === tab ? 'on' : ''}`, 'data-k': k,
    onclick: () => { tab = k; tabBtns.forEach((b) => b.classList.toggle('on', b.dataset.k === k)); render(); } }, label));
  const exportBtn = h('button', { class: 'tbtn', title: 'Download as CSV', onclick: () => {
    const kind = tab === 'ord' ? 'orders' : 'trades';
    const a = h('a', { href: `/api/export/${kind}.csv?token=${encodeURIComponent(getToken())}`, download: `meridian-${kind}.csv` });
    document.body.append(a); a.click(); a.remove();
  } }, 'CSV');
  const p = panel('port', 'PORT', '', [h('div', { class: 'tabs' }, tabBtns), exportBtn]);
  p.el.querySelector('.ph .tools').style.marginLeft = '0';
  grid.append(p.el);
  const body = h('div', { class: 'port-wrap' });
  p.body.append(body);
  let posCells = new Map();

  function closePos(t) { emit('dialog:close', t); }

  async function cancel(o) {
    try { await post('/api/order/cancel', { id: o.cancel_ref ?? o.id }); toast(`Cancelled order ${o.id}`); }
    catch (e) { toast(e.message, 'error'); }
  }

  function positions() {
    posCells = new Map();
    const rows = S.positions || [];
    if (!rows.length) {
      return h('div', { class: 'empty' }, `No open positions in the ${acctLabel().toLowerCase()} account. Approved trades and your manual orders appear here.`);
    }
    const tbody = h('tbody');
    for (const r of rows) {
      const c = { last: h('td', { class: 'num' }), val: h('td', { class: 'num c-val' }), pnl: h('td', { class: 'num' }), pct: h('td', { class: 'num c-pctp' }) };
      posCells.set(r.ticker, { r, c });
      tbody.append(h('tr', { class: 'clickable', onclick: () => select(r.ticker) },
        h('td', { class: 'tk' }, r.ticker), h('td', { class: 'num' }, fmt.num(r.qty, 0)), h('td', { class: 'num' }, fmt.px(r.entry)),
        c.last, c.val, c.pnl, c.pct,
        h('td', { class: 'num down' }, fmt.px(r.stop)), h('td', { class: 'num up' }, fmt.px(r.target)),
        h('td', {}, h('button', { class: 'xbtn', title: `Close ${r.ticker}`, onclick: (e) => { e.stopPropagation(); closePos(r.ticker); } }, '✕'))));
    }
    const totals = { val: h('td', { class: 'num c-val' }), pnl: h('td', { class: 'num' }) };
    posCells.set('__tot', totals);
    tbody.append(h('tr', { class: 'totals' }, h('td', { colspan: 4 }, 'Total'), totals.val, totals.pnl, h('td', { class: 'c-pctp' }), h('td', { colspan: 3 })));
    updatePnl();
    return h('table', { class: 't' }, h('thead', {}, h('tr', {},
      ['Ticker', 'Qty', 'Avg', 'Last', 'Value', 'P&L', 'P&L %', 'Stop', 'Target', ''].map((x, i) => h('th', { class: `${i && i < 9 ? 'num' : ''} ${i === 4 ? 'c-val' : i === 6 ? 'c-pctp' : ''}` }, x)))), tbody);
  }

  function updatePnl() {
    let tv = 0, tp = 0;
    for (const [t, v] of posCells) {
      if (t === '__tot') continue;
      const { r, c } = v;
      const last = (S.quotes[t] || {}).last || r.broker_last || r.entry;
      const pnl = (last - r.entry) * r.qty;
      tv += last * r.qty; tp += pnl;
      setText(c.last, fmt.px(last));
      setText(c.val, fmt.num(last * r.qty));
      setText(c.pnl, fmt.signed(pnl)); c.pnl.className = `num ${fmt.cls(pnl)}`;
      setText(c.pct, fmt.pct((last / r.entry - 1) * 100)); c.pct.className = `num c-pctp ${fmt.cls(pnl)}`;
    }
    const tot = posCells.get('__tot');
    if (tot) { setText(tot.val, fmt.num(tv)); setText(tot.pnl, fmt.signed(tp)); tot.pnl.className = `num ${fmt.cls(tp)}`; }
  }

  function orders() {
    const rows = S.orders || [];
    if (!rows.length) return h('div', { class: 'empty' }, 'No orders yet.');
    return h('table', { class: 't' }, h('thead', {}, h('tr', {},
      ['Time', 'Ticker', 'Side', 'Qty', 'Limit', 'Status', 'Source', ''].map((x, i) => h('th', { class: [3, 4].includes(i) ? 'num' : '' }, x)))),
      h('tbody', {}, rows.slice(0, 150).map((o) => h('tr', {},
        h('td', { class: 'dim' }, typeof o.ts === 'number' ? fmt.hm(o.ts) : String(o.ts || '').slice(11, 16)),
        h('td', { class: 'tk' }, o.ticker), h('td', { class: o.side === 'BUY' ? 'up' : 'down' }, o.side),
        h('td', { class: 'num' }, fmt.num(o.qty, 0)), h('td', { class: 'num' }, fmt.px(o.limit_price ?? o.limit)),
        h('td', { class: o.status === 'filled' ? 'up' : o.status === 'working' ? 'amber' : 'dim', title: o.note || '' },
          o.status + (o.filled_price ? ` @ ${fmt.px(o.filled_price)}` : '')),
        h('td', { class: 'dim' }, o.source || ''),
        h('td', {}, o.status === 'working' || (o.mode === 'live' && !['filled', 'cancelled', 'rejected', 'expired'].includes(o.status) && o.cancel_ref !== undefined)
          ? h('button', { class: 'xbtn', title: 'Cancel order', onclick: () => cancel(o) }, '✕') : '')))));
  }

  function trades() {
    const rows = S.trades || [];
    if (!rows.length) return h('div', { class: 'empty' }, 'No fills yet.');
    let realized = 0;
    rows.forEach((t) => { realized += t.realized_pnl || 0; });
    return h('div', {},
      h('div', { class: 'broker-line' }, 'Realized P&L (shown trades): ', h('span', { class: fmt.cls(realized) }, fmt.signed(realized))),
      h('table', { class: 't' }, h('thead', {}, h('tr', {},
        ['Time', 'Ticker', 'Side', 'Qty', 'Price', 'P&L', 'Source'].map((x, i) => h('th', { class: [3, 4, 5].includes(i) ? 'num' : '' }, x)))),
        h('tbody', {}, rows.slice(0, 200).map((t) => h('tr', { class: 'clickable', onclick: () => select(t.ticker) },
          h('td', { class: 'dim' }, fmt.hm(t.ts)), h('td', { class: 'tk' }, t.ticker),
          h('td', { class: t.side === 'BUY' ? 'up' : 'down' }, t.side), h('td', { class: 'num' }, fmt.num(t.qty, 0)),
          h('td', { class: 'num' }, fmt.px(t.price)),
          h('td', { class: `num ${fmt.cls(t.realized_pnl)}` }, t.side === 'SELL' ? fmt.signed(t.realized_pnl) : ''),
          h('td', { class: 'dim' }, t.source))))));
  }

  function render() {
    clear(body);
    tabBtns[0].textContent = `Positions ${(S.positions || []).length || ''}`.trim();
    const working = (S.orders || []).filter((o) => o.status === 'working').length;
    tabBtns[1].textContent = working ? `Orders ${working}` : 'Orders';
    body.append(tab === 'pos' ? positions() : tab === 'ord' ? orders() : trades());
  }

  on('state', render);
  on('positions', render);
  on('orders', render);
  on('app', render);
  on('trade', () => { if (tab !== 'pos') render(); });
  on('quotes', () => { if (tab === 'pos') updatePnl(); });
  on('cmd:port', (k) => { const b = tabBtns.find((x) => x.dataset.k === k); if (b) b.click(); });
  return p;
}
