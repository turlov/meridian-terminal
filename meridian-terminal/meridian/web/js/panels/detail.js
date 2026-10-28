// DES — security detail: price, key stats, 52-week range, rule proximity, trade plan,
// position, latest AI verdicts and headlines for the selected ticker.
import { S, on, h, fmt, panel, get, clear, setText, nameOf, emit, RULE_LABELS } from '../core.js';

export function mountDetail(grid) {
  const p = panel('detail', 'DES', 'Security', [
    h('button', { class: 'tbtn', title: 'Buy (order ticket)', onclick: () => emit('dialog:ticket', { ticker: S.selected, side: 'BUY' }) }, 'Buy'),
    h('button', { class: 'tbtn', title: 'Sell (order ticket)', onclick: () => emit('dialog:ticket', { ticker: S.selected, side: 'SELL' }) }, 'Sell'),
    h('button', { class: 'tbtn', title: 'Backtest the rules on this ticker', onclick: () => emit('cmd', `BT ${S.selected}`) }, 'Backtest'),
  ]);
  grid.append(p.el);
  const top = h('div', { class: 'des-top' });
  const pxEl = h('span', { class: 'des-px' }, '—');
  const chgEl = h('span', { class: 'des-chg' });
  const metaEl = h('span', { class: 'des-meta' });
  top.append(pxEl, chgEl, metaEl);
  const content = h('div', { class: 'des-body' });
  p.body.append(top, content);
  let detail = null;
  let ticker = null;
  let req = 0;

  async function load() {
    if (!ticker) return;
    const id = ++req;
    try {
      const d = await get(`/api/ticker/${encodeURIComponent(ticker)}`);
      if (id !== req) return;
      detail = d;
      render();
    } catch (e) {
      if (id !== req) return;
      clear(content).append(h('div', { class: 'empty' }, `Couldn't load ${ticker}: ${e.message}`));
    }
  }

  function price() {
    const q = S.quotes[ticker] || (detail && detail.quote) || {};
    setText(pxEl, fmt.px(q.last));
    setText(chgEl, `${fmt.signed(q.chg)}  ${fmt.pct(q.chg_pct)}`);
    chgEl.className = `des-chg ${fmt.cls(q.chg)}`;
    const spread = q.ask && q.bid ? q.ask - q.bid : null;
    setText(metaEl, `Bid ${fmt.px(q.bid)}  Ask ${fmt.px(q.ask)}  Spread ${fmt.px(spread)}  ${q.currency || ''}  ${q.ts ? fmt.time(q.ts) : ''}`);
  }

  function kv(label, value, cls = '') {
    return h('div', {}, h('span', {}, label), h('b', { class: cls }, value));
  }

  function render() {
    price();
    clear(content);
    if (!detail) return;
    const q = S.quotes[ticker] || detail.quote || {};
    const s = detail.snapshot;
    if (!s) {
      content.append(h('div', { class: 'empty' }, 'Not enough price history for indicators yet (needs about 210 trading days).'));
      return;
    }
    const last = q.last || s.last;
    const dist = (x) => `${fmt.px(x)} (${fmt.pct((last / x - 1) * 100, 1)})`;
    content.append(h('div', { class: 'kv' },
      kv('Open', fmt.px(q.open)), kv('High', fmt.px(q.high)), kv('Low', fmt.px(q.low)),
      kv('Prev close', fmt.px(q.prev_close || s.prev_close)), kv('Volume', fmt.compact(q.volume)),
      kv('Vol / 20d', `${fmt.num(s.vol_ratio, 1)}x`, s.vol_ratio > 2 ? 'amber' : ''),
      kv('ATR 14', `${fmt.px(s.atr14)} (${fmt.num(s.atr14 / last * 100, 1)}%)`),
      kv('RSI 14', fmt.num(s.rsi14, 1), s.rsi14 >= 70 ? 'down' : s.rsi14 <= 30 ? 'up' : ''),
      kv('5d / 20d', `${fmt.frac(s.ret5)} ${fmt.frac(s.ret20)}`),
      kv('SMA 20', dist(s.sma20), last >= s.sma20 ? 'up' : 'down'),
      kv('SMA 50', dist(s.sma50), last >= s.sma50 ? 'up' : 'down'),
      kv('SMA 200', dist(s.sma200), last >= s.sma200 ? 'up' : 'down'),
      kv('20d high', fmt.px(s.high20_prev)), kv('20d low', fmt.px(s.low20_prev)),
      kv('52w', `${fmt.frac(last / s.high252 - 1)} off high`)));
    const pos = Math.min(1, Math.max(0, (last - s.low252) / ((s.high252 - s.low252) || 1)));
    content.append(h('div', { class: 'rangebar', title: '52-week range' },
      h('div', { class: 'bar' }, h('i', { style: { left: `calc(${(pos * 100).toFixed(1)}% - 1px)` } })),
      h('div', { class: 'ends' }, h('span', {}, `52w low ${fmt.px(s.low252)}`), h('span', {}, `52w high ${fmt.px(s.high252)}`))));

    content.append(h('div', { class: 'section-h' }, 'Rules'));
    const rules = h('div', { class: 'rules' });
    for (const d of detail.diagnostics) {
      const st = d.status === 'n/a' ? 'na' : d.status;
      rules.append(h('div', { class: `rule ${d.enabled ? '' : 'off'}`, title: d.enabled ? '' : 'Rule is switched off in Settings > Strategies' },
        h('span', { class: `st ${st}` }, d.status === 'n/a' ? 'n/a' : d.status.toUpperCase()),
        h('span', {}, d.label + (d.enabled ? '' : ' (off)')),
        h('span', { class: 'note' }, d.note)));
    }
    content.append(rules);

    const pos_ = detail.position;
    if (pos_) {
      const pnl = (last - pos_.entry) * pos_.qty;
      content.append(h('div', { class: 'plan' },
        h('span', { class: 'lbl' }, 'Position'),
        h('span', {}, `${fmt.num(pos_.qty, 0)} @ ${fmt.px(pos_.entry)}`),
        h('span', { class: fmt.cls(pnl) }, `P&L ${fmt.signed(pnl)} (${fmt.pct((last / pos_.entry - 1) * 100)})`),
        h('span', { class: 'dim' }, `Stop ${fmt.px(pos_.stop)}  Target ${fmt.px(pos_.target)}`),
        h('button', { class: 'btn sm sell', onclick: () => emit('dialog:close', ticker) }, 'Close position')));
    } else if (detail.suggestion && detail.suggestion.qty === 0) {
      content.append(h('div', { class: 'plan' }, h('span', { class: 'lbl' }, 'Plan'),
        h('span', { class: 'dim' }, `One share (${fmt.money(last)}) is more than your max position size `
          + `(${fmt.money((S.settings.risk || {}).max_usd_per_trade, 0)}), so the bot won't buy it. Raise it in Settings > Risk limits.`)));
    } else if (detail.suggestion && detail.suggestion.qty > 0) {
      const g = detail.suggestion;
      content.append(h('div', { class: 'plan', title: 'Sized from your risk settings: the stop loses about your risk per trade' },
        h('span', { class: 'lbl' }, 'Plan'),
        h('span', {}, `Buy ${g.qty} ≈ ${fmt.money(g.value, 0)}`),
        h('span', { class: 'down' }, `Stop ${fmt.px(g.stop)}`),
        h('span', { class: 'up' }, `Target ${fmt.px(g.target)}`),
        h('span', { class: 'dim' }, `Risk ${fmt.money(g.risk_usd)}`),
        h('button', { class: 'btn sm buy', onclick: () => emit('dialog:ticket', { ticker, side: 'BUY', qty: g.qty, stop: g.stop, target: g.target }) }, 'Order ticket')));
    }

    if (detail.decisions.length) {
      content.append(h('div', { class: 'section-h' }, 'AI verdicts'));
      content.append(h('div', { class: 'mini-list' }, detail.decisions.slice(0, 4).map((d) => {
        const v = d.verdict;
        const rules = (d.candidates || []).map((c) => RULE_LABELS[c.strategy] || c.strategy).join(', ');
        return h('div', { class: 'clickable', style: { cursor: 'pointer' }, onclick: () => emit('dialog:decision', d.id), title: d.reason },
          h('span', { class: 'ts' }, fmt.hm(d.ts)),
          v ? h('span', { class: `verdict ${v.action}` }, `${v.action} ${fmt.num(v.confidence * 100, 0)}%  `) : h('span', { class: 'dim' }, 'not reviewed  '),
          `${rules}: ${d.reason}`);
      })));
    }
    if (detail.headlines.length) {
      content.append(h('div', { class: 'section-h' }, 'Headlines (7 days)'));
      content.append(h('div', { class: 'mini-list' }, detail.headlines.slice(0, 6).map((x) =>
        h('div', { title: x }, h('span', { class: 'ts' }, x.slice(5, 16)), x.slice(17)))));
    }
  }

  on('select', (t) => {
    ticker = t;
    p.titleEl.textContent = t;
    p.sub.textContent = nameOf(t);
    detail = null;
    clear(content);
    price();
    load();
  });
  on('quotes', (q) => { if (ticker && q[ticker]) price(); });
  const refresh = (t) => { if (!t || t === ticker) load(); };
  on('decision', (d) => refresh(d.ticker));
  on('trade', (t) => refresh(t.ticker));
  on('positions', () => refresh());
  on('snapshot', (e) => refresh(e.ticker));
  setInterval(() => { if (!document.hidden) load(); }, 20000);
  return p;
}
