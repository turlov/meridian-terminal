// ACCT — account & risk: equity, day P&L vs limit, exposure, AI budget, and the controls
// (execution mode, AI review, kill switch).
import { S, on, h, fmt, panel, clear, setText, post, toast, confirmDialog, acctLabel } from '../core.js';

export async function setExecution(mode) {
  if (mode === S.app.execution_mode) return;
  let confirm = '';
  if (mode === 'live') {
    const ok = await confirmDialog({
      title: 'Switch to live trading',
      text: 'Approved trades and your manual orders will be sent to Freedom Broker as real orders with real money. Stops and targets are attached after fills. Make sure you have paper-traded this setup first.',
      confirmLabel: 'Enable live trading', danger: true, typeToConfirm: 'LIVE' });
    if (!ok) return;
    confirm = 'LIVE';
  }
  try {
    await post('/api/control', { action: 'execution', mode, confirm });
    toast(mode === 'live' ? 'LIVE trading enabled' : mode === 'paper' ? 'Paper trading enabled' : 'Execution off: signals only',
      mode === 'live' ? 'live' : 'info');
  } catch (e) { toast(e.message, 'error'); }
}

export async function toggleHalt() {
  if (S.app.halted) {
    try { await post('/api/control', { action: 'resume' }); toast('Trading resumed'); } catch (e) { toast(e.message, 'error'); }
    return;
  }
  const ok = await confirmDialog({ title: 'Halt trading',
    text: 'Stops all new orders and cancels working orders. Open positions and their stops stay in place. You can resume any time.',
    confirmLabel: 'Halt trading', danger: true });
  if (!ok) return;
  try { await post('/api/control', { action: 'halt' }); } catch (e) { toast(e.message, 'error'); }
}

export function mountAccount(grid) {
  const p = panel('acct', 'ACCT', 'Account & risk');
  grid.append(p.el);
  const big = {
    eq: h('b'), day: h('b'), cash: h('b'), inv: h('b'),
  };
  const bigBox = h('div', { class: 'acct-big' },
    h('div', {}, h('span', {}, 'Equity'), big.eq), h('div', {}, h('span', {}, 'Day P&L'), big.day),
    h('div', {}, h('span', {}, 'Cash'), big.cash), h('div', {}, h('span', {}, 'Invested'), big.inv));
  const gauges = h('div');
  const execSeg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Execution mode' },
    ['off', 'paper', 'live'].map((m) => h('button', { 'data-m': m, title: {
      off: 'Signals only: nothing is executed', paper: 'Simulated fills against market prices', live: 'Real orders at Freedom Broker' }[m],
      onclick: () => setExecution(m) }, { off: 'Off', paper: 'Paper', live: 'Live' }[m])));
  const aiSeg = h('div', { class: 'seg', role: 'group', 'aria-label': 'AI review' },
    h('button', { 'data-v': 'on', onclick: () => post('/api/control', { action: 'ai_on' }).catch((e) => toast(e.message, 'error')) }, 'On'),
    h('button', { 'data-v': 'off', onclick: () => post('/api/control', { action: 'ai_off' }).catch((e) => toast(e.message, 'error')) }, 'Off'));
  const haltBtn = h('button', { class: 'halt-btn', onclick: toggleHalt });
  const brokerLine = h('div', { class: 'broker-line' });
  const controls = h('div', { class: 'controls' },
    h('div', { class: 'ctl-row' }, h('span', {}, 'Orders'), execSeg, h('span', { style: { marginLeft: '6px' } }, 'AI'), aiSeg),
    h('div', { class: 'ctl-row' }, haltBtn,
      h('button', { class: 'btn sm ghost', title: 'Run the rule scan now',
        onclick: () => post('/api/control', { action: 'scan' }).then(() => toast('Scanning the watchlist')).catch((e) => toast(e.message, 'error')) }, 'Scan now')));
  p.body.append(bigBox, gauges, controls, brokerLine);

  function gauge(label, valueText, frac, level) {
    return h('div', { class: 'gauge' },
      h('div', { class: 'lbl' }, h('span', {}, label), h('b', {}, valueText)),
      h('div', { class: 'bar' }, h('i', { class: level, style: { width: `${Math.max(0, Math.min(1, frac)) * 100}%` } })));
  }

  function render() {
    const a = S.account || {};
    const app = S.app || {};
    const risk = (S.settings.risk) || {};
    setText(p.sub, acctLabel());
    const m = (n) => fmt.money(n, Math.abs(n || 0) >= 10000 ? 0 : 2);
    setText(big.eq, m(a.equity));
    setText(big.day, fmt.signed(a.day_pnl)); big.day.className = fmt.cls(a.day_pnl);
    setText(big.cash, m(a.cash_total));
    setText(big.inv, m(a.invested));
    const lossUsed = a.day_pnl < 0 ? -a.day_pnl / (risk.max_daily_loss_usd || 1) : 0;
    const posFrac = (a.open_positions || 0) / (risk.max_open_positions || 1);
    const u = S.usage || {};
    const aiFrac = u.demo ? 0 : (u.cost || 0) / (u.budget || 1);
    clear(gauges).append(
      gauge('Daily loss limit', `${fmt.money(Math.max(0, -(a.day_pnl || 0)))} of ${fmt.money(risk.max_daily_loss_usd, 0)}`,
        lossUsed, lossUsed >= 1 ? 'bad' : lossUsed > 0.6 ? 'warn' : ''),
      gauge('Open positions', `${a.open_positions || 0} of ${risk.max_open_positions ?? '—'}`, posFrac, posFrac >= 1 ? 'warn' : ''),
      gauge('AI spend today', u.demo ? 'demo, no cost' : `${fmt.money(u.cost || 0)} of ${fmt.money(u.budget || 0)}`,
        aiFrac, aiFrac >= 1 ? 'bad' : aiFrac > 0.75 ? 'warn' : ''),
    );
    for (const b of execSeg.children) {
      const m = b.dataset.m;
      b.classList.toggle('on', app.execution_mode === m);
      b.classList.toggle('live', m === 'live');
      b.disabled = m === 'live' && app.demo;
      if (m === 'live' && app.demo) b.title = 'Live trading needs Tradernet data (Settings > Accounts)';
    }
    for (const b of aiSeg.children) b.classList.toggle('on', (b.dataset.v === 'on') === !!app.ai_enabled);
    haltBtn.textContent = app.halted ? 'Trading halted: resume' : 'Halt trading';
    haltBtn.classList.toggle('halted', !!app.halted);
    const br = S.broker || {};
    if (!app.demo) {
      setText(brokerLine, br.ok === false ? 'Freedom Broker account: sync error (see System panel)'
        : br.equity !== undefined && br.equity !== null ? `Freedom Broker account ${fmt.money(br.equity)}  synced ${fmt.ago(br.last)}` : 'Freedom Broker account: syncing…');
    } else {
      setText(brokerLine, a.total_return !== undefined ? `Demo account since reset: ${fmt.frac(a.total_return, 2)}` : '');
    }
  }
  ['state', 'account', 'app', 'settings', 'usage', 'broker'].forEach((ev) => on(ev, render));
  return p;
}
