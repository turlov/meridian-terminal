// F6 — backtest the rule strategies against buy-and-hold, with equity curves and trades.
import { S, on, h, fmt, get, post, toast, clear, watchlist, RULE_LABELS } from '../core.js';

const ENTRY = ['trend_breakout', 'mean_reversion', 'volume_surge'];
const LWC = window.LightweightCharts;
const COLORS = { trend_breakout: '#ffa31a', mean_reversion: '#5aa9ff', volume_surge: '#c77dff', buy_hold: '#8a93a3' };

export function mountBacktest(root) {
  const chosen = new Set();
  const rules = new Set(ENTRY);
  const tickChips = h('div', { class: 'tick-chips' });
  const extra = h('input', { class: 'inp', placeholder: 'Other tickers, e.g. MSFT.US TSLA.US' });
  const years = h('select', { class: 'inp' }, [1, 2, 3, 5, 8, 10].map((y) => h('option', { value: y, selected: y === 3 }, `${y} year${y > 1 ? 's' : ''}`)));
  const cost = h('input', { class: 'inp', value: '10', inputmode: 'decimal' });
  const runBtn = h('button', { class: 'btn go', style: { width: '100%' }, onclick: () => run() }, 'Run backtest');
  const progress = h('div', { class: 'progress', hidden: true }, h('i', { style: { width: '0%' } }));
  const results = h('div');
  let job = null;
  let selTicker = null;
  let selRule = null;
  let btChart = null;

  const form = h('aside', {},
    h('div', { class: 'page-h' }, h('span', { class: 'fn' }, 'BT'), h('h2', {}, 'Backtest')),
    h('div', { class: 'page-body' },
      h('div', { class: 'field' }, h('label', {}, 'Tickers'), tickChips, extra),
      h('div', { class: 'grid2' },
        h('div', { class: 'field' }, h('label', {}, 'History'), years),
        h('div', { class: 'field' }, h('label', {}, 'Cost per side (bps)'), cost)),
      h('div', { class: 'field' }, h('label', {}, 'Entry rules to test'),
        ENTRY.map((r) => h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: true,
          onchange: (e) => (e.target.checked ? rules.add(r) : rules.delete(r)) }), h('span', {}, RULE_LABELS[r])))),
      runBtn, progress,
      h('div', { class: 'note', style: { marginTop: '14px' } },
        h('p', {}, 'Each rule trades alone: signal at the close, buy at the next open, exit on the ATR stop or target from your risk settings, or when an exit rule fires. Every trade uses the whole account and pays the cost on entry and exit.'),
        h('p', {}, 'Claude is not part of the backtest. It has read about past prices and news during training, so a test on old dates would flatter it. Judge the reviewer by paper trading instead.'),
        h('p', {}, 'Keep a rule switched on only if it beats buy-and-hold after costs across several tickers, with a drawdown you could live with.'))));
  const main = h('section', {}, h('div', { class: 'page-h' }, h('h2', { style: { paddingLeft: '10px' } }, 'Results')),
    h('div', { class: 'page-body' }, results));
  root.append(h('div', { class: 'page' }, form, main));

  function renderChips() {
    clear(tickChips);
    for (const t of watchlist()) {
      tickChips.append(h('button', { class: `tchip ${chosen.has(t) ? 'on' : ''}`, onclick: () => { chosen.has(t) ? chosen.delete(t) : chosen.add(t); renderChips(); } }, t));
    }
  }

  async function run(tickersOverride) {
    const tickers = tickersOverride || [...chosen, ...extra.value.toUpperCase().split(/[\s,]+/).filter(Boolean)];
    if (!tickers.length) { toast('Pick at least one ticker', 'warn'); return; }
    if (!rules.size) { toast('Pick at least one rule', 'warn'); return; }
    runBtn.disabled = true;
    progress.hidden = false;
    progress.firstChild.style.width = '3%';
    try {
      const r = await post('/api/backtest', { tickers, years: +years.value, cost_bps: +cost.value, rules: [...rules] });
      job = { id: r.id, results: [], status: 'running' };
      clear(results).append(h('div', { class: 'empty' }, `Testing ${tickers.join(', ')}…`));
    } catch (e) {
      toast(e.message, 'error');
      runBtn.disabled = false;
      progress.hidden = true;
    }
  }

  function render() {
    if (btChart) { btChart.remove(); btChart = null; }
    clear(results);
    if (!job) {
      results.append(h('div', { class: 'empty' }, 'Choose tickers on the left and run a backtest.'));
      return;
    }
    if (job.demo) results.append(h('div', { class: 'banner info', style: { marginBottom: '10px' } }, 'Demo mode: these are simulated prices, so the numbers only show how the tool works.'));
    const ok = job.results.filter((r) => !r.error);
    for (const r of job.results.filter((x) => x.error)) results.append(h('div', { class: 'err-text' }, `${r.ticker}: ${r.error}`));
    if (!ok.length) return;
    if (!selTicker || !ok.some((r) => r.ticker === selTicker)) selTicker = ok[0].ticker;
    const tabs = h('div', { class: 'tabs', style: { marginBottom: '6px' } }, ok.map((r) =>
      h('button', { class: `tab ${r.ticker === selTicker ? 'on' : ''}`, onclick: () => { selTicker = r.ticker; render(); } }, r.ticker)));
    results.append(tabs);
    const res = ok.find((r) => r.ticker === selTicker);
    const best = Math.max(...res.results.map((x) => x.total));
    results.append(h('div', { class: 'bt-title' }, h('b', {}, res.ticker),
      h('span', { class: 'dim' }, `${fmt.date(res.from)} to ${fmt.date(res.to)}  ${res.bars} trading days`)));
    const rows = res.results.map((x) => h('tr', { class: `clickable ${x.total === best && best > res.buy_hold.total ? 'best' : ''} ${selRule === x.rule ? 'sel' : ''}`,
      onclick: () => { selRule = x.rule; render(); } },
      h('td', {}, h('span', { style: { color: COLORS[x.rule] } }, '■ '), RULE_LABELS[x.rule] || x.rule),
      h('td', { class: 'num' }, x.trades), h('td', { class: 'num' }, `${fmt.num(x.win_rate * 100, 0)}%`),
      h('td', { class: `num ${fmt.cls(x.avg_trade)}` }, fmt.frac(x.avg_trade, 2)),
      h('td', { class: `num ${fmt.cls(x.total)}` }, fmt.frac(x.total)),
      h('td', { class: 'num down' }, fmt.frac(x.max_dd)),
      h('td', { class: 'num' }, `${fmt.num(x.exposure * 100, 0)}%`),
      h('td', { class: `num ${fmt.cls(x.total - res.buy_hold.total)}` }, fmt.frac(x.total - res.buy_hold.total))));
    rows.push(h('tr', {}, h('td', {}, h('span', { style: { color: COLORS.buy_hold } }, '■ '), 'Buy and hold'),
      h('td', { class: 'num dim' }, '1'), h('td', {}), h('td', {}),
      h('td', { class: `num ${fmt.cls(res.buy_hold.total)}` }, fmt.frac(res.buy_hold.total)),
      h('td', { class: 'num down' }, fmt.frac(res.buy_hold.max_dd)), h('td', { class: 'num' }, '100%'), h('td', {})));
    results.append(h('table', { class: 't' }, h('thead', {}, h('tr', {},
      ['Strategy', 'Trades', 'Win rate', 'Avg trade', 'Total return', 'Max drawdown', 'In market', 'vs hold']
        .map((c, i) => h('th', { class: i ? 'num' : '' }, c)))), h('tbody', {}, rows)));

    const chartBox = h('div', { class: 'bt-chart' });
    results.append(h('div', { class: 'section-h', style: { padding: '12px 0 0' } }, 'Equity curves (start = 1.0)'), chartBox);
    if (LWC) {
      const chart = btChart = LWC.createChart(chartBox, { autoSize: true,
        layout: { background: { type: 'solid', color: '#000' }, textColor: '#8a93a3', fontFamily: '"Plex Mono", monospace', fontSize: 11, attributionLogo: false },
        grid: { vertLines: { color: '#0d131c' }, horzLines: { color: '#0d131c' } },
        rightPriceScale: { borderColor: '#1b2433' }, timeScale: { borderColor: '#1b2433' } });
      const bh = chart.addSeries(LWC.LineSeries, { color: COLORS.buy_hold, lineWidth: 1, lineStyle: 2, priceLineVisible: false });
      bh.setData(res.buy_hold.curve);
      for (const x of res.results) {
        const s = chart.addSeries(LWC.LineSeries, { color: COLORS[x.rule], lineWidth: x.rule === selRule ? 3 : 2, priceLineVisible: false });
        s.setData(x.curve);
      }
      chart.timeScale().fitContent();
    }
    const rr = res.results.find((x) => x.rule === selRule) || res.results[0];
    results.append(h('div', { class: 'section-h', style: { padding: '12px 0 4px' } }, `Trades: ${RULE_LABELS[rr.rule]} (${rr.trade_list.length})`));
    if (!rr.trade_list.length) results.append(h('div', { class: 'empty' }, 'This rule never fired in the period.'));
    else results.append(h('table', { class: 't' }, h('thead', {}, h('tr', {},
      ['Entry', 'Exit', 'Buy', 'Sell', 'Return', 'Exit reason'].map((c, i) => h('th', { class: [2, 3, 4].includes(i) ? 'num' : '' }, c)))),
      h('tbody', {}, rr.trade_list.slice().reverse().map((t) => h('tr', {},
        h('td', {}, fmt.date(t.t_in)), h('td', {}, fmt.date(t.t_out)), h('td', { class: 'num' }, fmt.px(t.entry)),
        h('td', { class: 'num' }, fmt.px(t.exit)), h('td', { class: `num ${fmt.cls(t.ret)}` }, fmt.frac(t.ret, 2)),
        h('td', { class: 'dim' }, { stop: 'stop hit', target: 'target hit', signal: 'exit rule', open: 'still open' }[t.why] || t.why))))));
  }

  on('backtest', (j) => {
    if (!job || j.id !== job.id) return;
    job = j;
    progress.firstChild.style.width = `${Math.max(3, j.progress * 100)}%`;
    if (j.status === 'done') {
      runBtn.disabled = false;
      setTimeout(() => (progress.hidden = true), 600);
      render();
    }
  });
  on('state', () => { renderChips(); if (!job) render(); });
  on('settings', renderChips);
  on('cmd:bt', (tickers) => {
    if (tickers && tickers.length) { tickers.forEach((t) => chosen.add(t)); renderChips(); run(tickers); }
  });
  renderChips();
  render();
}
