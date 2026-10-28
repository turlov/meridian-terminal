// Top bar badges, market clocks, ticker tape, function-key footer, banners.
import { S, on, h, add, fmt, clear, setText, select, emit, watchlist, acctLabel } from './core.js';
import { setExecution, toggleHalt } from './panels/account.js';

const CLOCKS = [
  ['New York', 'America/New_York', 'NYSE', [9, 30], [16, 0]],
  ['London', 'Europe/London', 'LSE', [8, 0], [16, 30]],
  ['Almaty', 'Asia/Almaty', null],
];

function partsIn(tz) {
  const p = new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', weekday: 'short', hour12: false })
    .formatToParts(new Date());
  const get = (t) => (p.find((x) => x.type === t) || {}).value;
  return { hh: +get('hour') % 24, mm: +get('minute'), wd: get('weekday') };
}

export function mountTopbar() {
  const badges = document.getElementById('badges');
  const clocks = document.getElementById('clocks');
  const track = document.getElementById('tape-track');
  const fkeys = document.getElementById('fkeys');
  const sbRight = document.getElementById('sb-right');
  const banner = document.getElementById('banner');

  function renderBadges() {
    const a = S.app;
    clear(badges);
    add(badges,
      h('button', { class: `badge ${a.demo ? 'demo' : 'data'}`, title: a.demo ? 'Simulated market data. Switch in Settings > Accounts.' : 'Live Tradernet market data',
        onclick: () => emit('screen', 'settings') }, h('span', { class: `dot ${S.status.market && S.status.market.ok ? 'ok' : S.status.market && S.status.market.ok === false ? 'bad' : 'warn'}` }), a.demo ? 'DEMO DATA' : 'TRADERNET'),
      h('button', { class: `badge ${a.acct === 'live' ? 'live' : a.acct === 'off' ? 'off' : 'paper'}`,
        title: 'Where orders go. Click to cycle Off / Paper.', onclick: () => setExecution(a.execution_mode === 'off' ? 'paper' : 'off') }, acctLabel()),
      h('button', { class: `badge ${a.ai_enabled ? 'ai-on' : 'off'}`, title: 'Claude review', onclick: () => emit('cmd', a.ai_enabled ? 'AI OFF' : 'AI ON') }, a.ai_enabled ? 'AI ON' : 'AI OFF'),
      a.halted ? h('button', { class: 'badge halted', title: 'Trading halted. Click to resume.', onclick: toggleHalt }, 'HALTED') : null);
  }

  function renderClocks() {
    clear(clocks);
    for (const [label, tz, mkt, open, close] of CLOCKS) {
      const { hh, mm, wd } = partsIn(tz);
      let st = null;
      if (mkt) {
        const m = hh * 60 + mm;
        const isOpen = !['Sat', 'Sun'].includes(wd) && m >= open[0] * 60 + open[1] && m < close[0] * 60 + close[1];
        st = h('span', { class: `mkt ${isOpen ? 'open' : 'closed'}`, title: `${mkt} regular session (holidays not included)` }, isOpen ? `${mkt} open` : `${mkt} closed`);
      }
      clocks.append(h('span', { class: 'clock' }, `${label} `, h('b', {}, `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`), st));
    }
  }

  let tapeItems = new Map();
  function buildTape() {
    clear(track);
    tapeItems = new Map();
    const list = watchlist();
    const reps = list.length < 6 ? 3 : 2;   // repeat so the tape fills wide screens
    for (let r = 0; r < reps; r++) {
      for (const t of list) {
        const px = h('span'), ch = h('span');
        const item = h('span', { class: 'tape-item', onclick: () => select(t) }, h('span', { class: 't' }, t), px, ch);
        track.append(item);
        if (!tapeItems.has(t)) tapeItems.set(t, []);
        tapeItems.get(t).push([px, ch]);
      }
    }
    updateTape();
  }
  function updateTape() {
    for (const [t, els] of tapeItems) {
      const q = S.quotes[t] || {};
      for (const [px, ch] of els) {
        setText(px, fmt.px(q.last));
        setText(ch, `${q.chg_pct > 0 ? '▲' : q.chg_pct < 0 ? '▼' : ''} ${fmt.pct(q.chg_pct)}`);
        ch.className = fmt.cls(q.chg_pct);
      }
    }
  }

  const FKEYS = [['F1', 'Help', 'help'], ['F2', 'Monitor', 'monitor'], ['F3', 'News', 'max:news'], ['F4', 'AI desk', 'max:ai'],
    ['F5', 'Portfolio', 'max:port'], ['F6', 'Backtest', 'backtest'], ['F7', 'Chart', 'max:chart'], ['F8', 'Settings', 'settings'], ['F9', 'Order', 'ticket']];
  for (const [k, label, action] of FKEYS) {
    fkeys.append(h('button', { class: 'fkey', 'data-action': action, onclick: () => emit('fkey', action) }, h('kbd', {}, k), label));
  }

  function renderStatus() {
    clear(sbRight);
    const u = S.usage || {};
    sbRight.append(
      h('span', {}, h('span', { class: `dot ${S.connected ? 'ok' : 'bad'}` }), S.connected ? ' Connected' : ' Reconnecting'),
      h('span', {}, `Equity ${fmt.money(S.account.equity)}`),
      h('span', { class: fmt.cls(S.account.day_pnl) }, `Day ${fmt.signed(S.account.day_pnl)}`),
      h('span', {}, u.demo ? 'AI demo' : `AI ${fmt.money(u.cost || 0)} today`),
      h('span', { class: 'faint' }, S.app.shell === 'headless' ? 'Remote' : ''));
  }

  function renderBanner() {
    const a = S.app;
    const notice = S.status && S.status.notice;
    let cls = '', text = '';
    if (!S.connected && S.ready) { cls = 'warn'; text = 'Lost connection to the engine. Reconnecting…'; }
    else if (a.halted) { cls = 'danger'; text = 'Trading is halted. No new orders will be sent; open positions keep their stops.'; }
    else if (a.acct === 'live') { cls = 'danger'; text = 'LIVE TRADING: approved trades are sent to Freedom Broker with real money.'; }
    else if (notice) { cls = 'warn'; text = notice; }
    banner.hidden = !text;
    banner.className = `banner ${cls}`;
    clear(banner);
    if (text) {
      banner.append(text);
      if (a.halted) banner.append(h('button', { class: 'btn sm', onclick: toggleHalt }, 'Resume trading'));
    }
  }

  on('state', () => { renderBadges(); buildTape(); renderStatus(); renderBanner(); });
  on('app', () => { renderBadges(); renderBanner(); renderStatus(); });
  on('status', () => { renderBadges(); renderBanner(); });
  on('settings', () => { if (watchlist().join() !== [...tapeItems.keys()].join()) buildTape(); });
  on('quotes', updateTape);
  on('account', renderStatus);
  on('usage', renderStatus);
  on('conn', () => { renderStatus(); renderBanner(); });
  on('screen-changed', (name) => {
    for (const b of fkeys.children) b.classList.toggle('active', b.dataset.action === name);
  });
  renderClocks();
  setInterval(renderClocks, 15000);
}
