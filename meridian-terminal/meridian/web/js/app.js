// Boot: token, WebSocket, screens, command line, keyboard.
import { S, on, emit, h, clear, setToken, getToken, get, post, toast, modalOpen, select, watchlist, toggleMax, openUrl, confirmDialog, nameOf, fmt } from './core.js';
import { mountTopbar } from './topbar.js';
import { mountWatchlist, moveSelection } from './panels/watchlist.js';
import { mountChart } from './panels/chart.js';
import { mountDetail } from './panels/detail.js';
import { mountNews } from './panels/news.js';
import { mountDecisions } from './panels/decisions.js';
import { mountPortfolio } from './panels/portfolio.js';
import { mountAccount, setExecution, toggleHalt } from './panels/account.js';
import { mountSystem } from './panels/system.js';
import { mountBacktest } from './screens/backtest.js';
import { mountSettings } from './screens/settings.js';
import { mountHelp } from './screens/help.js';
import { orderTicket, welcome, connect, addTicker, removeTicker, closePosition } from './dialogs.js';

const panels = {};
let screen = 'monitor';
let helpMounted = false;

// ---------- access token ----------
function readToken() {
  const m = location.hash.match(/token=([^&]+)/);
  if (m) {
    const t = decodeURIComponent(m[1]);
    try { localStorage.setItem('meridian.token', t); } catch { /* storage unavailable */ }
    history.replaceState(null, '', location.pathname);
    return t;
  }
  try { return localStorage.getItem('meridian.token') || ''; } catch { return ''; }
}

function showLocked() {
  document.getElementById('app').hidden = true;
  document.getElementById('locked').hidden = false;
}
document.getElementById('token-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const v = document.getElementById('token-input').value.trim();
  const m = v.match(/token=([^&\s]+)/);
  const t = m ? decodeURIComponent(m[1]) : v;
  if (!t) return;
  try { localStorage.setItem('meridian.token', t); } catch { /* ignore */ }
  location.reload();
});
on('unauthorized', showLocked);

// ---------- live connection ----------
let backoff = 800;
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(getToken())}`);
  ws.onopen = () => { S.connected = true; backoff = 800; emit('conn', true); };
  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    handle(m.type, m.data);
  };
  ws.onclose = () => {
    const was = S.connected;
    S.connected = false;
    if (was) emit('conn', false);
    get('/api/settings').catch(() => { /* 401 shows the lock screen */ });
    setTimeout(connectWS, backoff);
    backoff = Math.min(backoff * 1.6, 8000);
  };
}

const trim = (arr, n) => { if (arr.length > n) arr.length = n; };

function handle(type, data) {
  switch (type) {
    case 'state': {
      Object.assign(S, data);
      const first = !S.ready;
      S.ready = true;
      emit('state');
      if (first) onFirstState();
      else if (S.selected) emit('select-refresh', S.selected);
      break;
    }
    case 'quotes': Object.assign(S.quotes, data); emit('quotes', data); break;
    case 'snapshot': S.snapshots[data.ticker] = data; emit('snapshot', data); break;
    case 'news': S.news.unshift(data); trim(S.news, 500); emit('news', data); break;
    case 'news_score': {
      const n = S.news.find((x) => x.id === data.id);
      if (n) { n.score = data.score; n.scored_ticker = data.ticker; }
      emit('news_score', data);
      break;
    }
    case 'decision': S.decisions.unshift(data); trim(S.decisions, 300); emit('decision', data); break;
    case 'trade': S.trades.unshift(data); trim(S.trades, 300); emit('trade', data); break;
    case 'positions': S.positions = data; emit('positions'); break;
    case 'orders': S.orders = data; emit('orders'); break;
    case 'account': S.account = data; emit('account'); break;
    case 'broker': S.broker = data; emit('broker'); break;
    case 'status': S.status = data; emit('status'); break;
    case 'app': {
      const wasOnboarded = S.app.onboarded;
      S.app = data;
      emit('app');
      if (wasOnboarded === false && data.onboarded) emit('onboarded');
      break;
    }
    case 'settings': S.settings = data; emit('settings'); break;
    case 'usage': S.usage = data; emit('usage'); break;
    case 'log': S.log.push(data); if (S.log.length > 800) S.log.splice(0, S.log.length - 800); emit('log', data); break;
    case 'toast': toast(data.text, data.level); break;
    case 'backtest': emit('backtest', data); break;
    case 'reset':
      get('/api/state').then((st) => handle('state', st)).catch(() => { /* next reconnect reloads */ });
      break;
    default: break;
  }
}

function onFirstState() {
  document.getElementById('locked').hidden = true;
  document.getElementById('app').hidden = false;
  if (!helpMounted) { mountHelp(document.getElementById('scr-help')); helpMounted = true; }
  let sel = null;
  try { sel = localStorage.getItem('meridian.selected'); } catch { /* ignore */ }
  const list = watchlist();
  select(list.includes(sel) ? sel : list[0]);
  window.dispatchEvent(new Event('resize'));
  if (!S.app.onboarded) setTimeout(welcome, 300);
}
on('select-refresh', (t) => { S.selected = null; select(t); });
on('settings', () => {
  const list = watchlist();
  if (S.selected && !list.includes(S.selected) && list.length) select(list[0]);
});

// ---------- screens ----------
function show(name) {
  screen = name;
  for (const s of ['monitor', 'backtest', 'settings', 'help']) {
    document.getElementById(`scr-${s}`).hidden = s !== name;
  }
  emit('screen-changed', name);
  window.dispatchEvent(new Event('resize'));
}
function maximize(area) {
  show('monitor');
  const p = panels[area];
  if (!p) return;
  const isMax = p.el.classList.contains('max');
  toggleMax(p.el, !isMax);
  emit('screen-changed', isMax ? 'monitor' : `max:${area}`);
}
function restore() {
  const grid = document.getElementById('grid');
  if (grid.classList.contains('has-max')) {
    const p = grid.querySelector('.panel.max');
    if (p) toggleMax(p, false);
    emit('screen-changed', 'monitor');
    return true;
  }
  return false;
}
on('screen', show);
on('fkey', (action) => {
  if (action === 'ticket') { orderTicket({ ticker: S.selected, side: 'BUY' }); return; }
  if (action.startsWith('max:')) { maximize(action.slice(4)); return; }
  if (action === 'monitor') { restore(); show('monitor'); return; }
  show(action);
});
on('open-url', openUrl);

// ---------- command line ----------
const CMDS = [
  ['BUY', 'Order ticket to buy: BUY NVDA 5 @ 182.40'], ['SELL', 'Order ticket to sell'], ['CLOSE', 'Close a position'],
  ['ADD', 'Add a ticker to the watchlist'], ['DEL', 'Remove a ticker from the watchlist'], ['BT', 'Backtest rules: BT NVDA AAPL'],
  ['TF', 'Chart timeframe: TF 15m'], ['NEWS', 'Headlines, optionally for one ticker'], ['AI', 'AI desk, or AI ON / AI OFF'],
  ['PORT', 'Portfolio'], ['GP', 'Chart, full screen'], ['DES', 'Security detail, full screen'], ['SCAN', 'Run the rule scan now'],
  ['POLL', 'Poll news sources now'], ['MODE', 'Execution: MODE OFF / PAPER / LIVE'], ['HALT', 'Kill switch: stop all trading'],
  ['RESUME', 'Resume trading'], ['KEYS', 'Add or change API keys'], ['SET', 'Settings'], ['HELP', 'Commands and keys'],
  ['MON', 'Monitor: all panels'], ['QUIT', 'Close the app'],
];

const cmdInput = document.getElementById('cmd');
const suggestEl = document.getElementById('cmd-suggest');
let suggestions = [];
let active = -1;

function resolveTicker(s) {
  if (!s) return null;
  s = s.toUpperCase();
  const list = watchlist();
  if (list.includes(s)) return s;
  const base = list.find((t) => t.split('.')[0] === s);
  if (base) return base;
  return s.includes('.') ? s : null;
}

function computeSuggestions() {
  const text = cmdInput.value.trim().toUpperCase();
  suggestions = [];
  if (!text) return renderSuggestions();
  const [first, ...rest] = text.split(/\s+/);
  if (!rest.length) {
    for (const t of watchlist()) {
      const nm = nameOf(t);
      if (t.startsWith(text) || t.split('.')[0].startsWith(text) || (text.length > 1 && nm.toUpperCase().includes(text))) {
        const q = S.quotes[t] || {};
        suggestions.push({ k: t, d: `${nm}  ${fmt.px(q.last)}  ${fmt.pct(q.chg_pct)}`, value: t, run: true });
      }
    }
    for (const [c, d] of CMDS) if (c.startsWith(first)) suggestions.push({ k: c, d, value: `${c} `, run: false });
  } else if (['BUY', 'SELL', 'CLOSE', 'DEL', 'BT', 'NEWS', 'GP', 'DES'].includes(first)) {
    const last = rest[rest.length - 1];
    for (const t of watchlist()) {
      if (t.startsWith(last) || t.split('.')[0].startsWith(last)) {
        suggestions.push({ k: `${first} ${[...rest.slice(0, -1), t].join(' ')}`, d: nameOf(t), value: `${first} ${[...rest.slice(0, -1), t].join(' ')} `, run: false });
      }
    }
  } else if (first === 'TF') {
    for (const t of ['1m', '5m', '15m', '1h', '1D', '1W']) suggestions.push({ k: `TF ${t}`, d: 'Chart timeframe', value: `TF ${t}`, run: true });
  } else if (first === 'MODE') {
    for (const m of ['OFF', 'PAPER', 'LIVE']) suggestions.push({ k: `MODE ${m}`, d: { OFF: 'Signals only', PAPER: 'Simulated fills', LIVE: 'Real orders' }[m], value: `MODE ${m}`, run: true });
  } else if (first === 'AI') {
    for (const m of ['ON', 'OFF']) suggestions.push({ k: `AI ${m}`, d: `Claude review ${m.toLowerCase()}`, value: `AI ${m}`, run: true });
  }
  suggestions = suggestions.slice(0, 9);
  active = suggestions.length && cmdInput.value.trim() ? 0 : -1;
  renderSuggestions();
}

function renderSuggestions() {
  clear(suggestEl);
  suggestEl.hidden = !suggestions.length;
  suggestions.forEach((s, i) => suggestEl.append(h('li', { class: i === active ? 'active' : '', role: 'option',
    onmousedown: (e) => { e.preventDefault(); accept(i, true); } }, h('span', { class: 'k' }, s.k), h('span', { class: 'd' }, s.d))));
}

function accept(i, runIt) {
  const s = suggestions[i];
  if (!s) return;
  cmdInput.value = s.value;
  if (runIt && s.run) submit();
  else { computeSuggestions(); cmdInput.focus(); }
}

function submit() {
  const v = cmdInput.value;
  cmdInput.value = '';
  suggestions = [];
  renderSuggestions();
  cmdInput.blur();
  runCommand(v).catch((e) => toast(e.message, 'error'));
}

let navigated = false;
cmdInput.addEventListener('input', () => { navigated = false; computeSuggestions(); });
cmdInput.addEventListener('focus', computeSuggestions);
cmdInput.addEventListener('blur', () => setTimeout(() => { suggestEl.hidden = true; }, 120));
cmdInput.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown' && suggestions.length) { e.preventDefault(); navigated = true; active = (active + 1) % suggestions.length; renderSuggestions(); }
  else if (e.key === 'ArrowUp' && suggestions.length) { e.preventDefault(); navigated = true; active = (active - 1 + suggestions.length) % suggestions.length; renderSuggestions(); }
  else if (e.key === 'Tab' && suggestions.length) { e.preventDefault(); accept(Math.max(0, active), false); }
  else if (e.key === 'Escape') { cmdInput.value = ''; suggestions = []; renderSuggestions(); cmdInput.blur(); }
  else if (e.key === 'Enter') {
    const typed = cmdInput.value.trim().toUpperCase();
    const known = CMDS.some(([c]) => c === typed.split(/\s+/)[0]) || resolveTicker(typed.split(/\s+/)[0]);
    const s = suggestions[active];
    if (s && (navigated || (!known && s.run))) { e.preventDefault(); accept(active, true); }
  }
});
document.getElementById('cmd-form').addEventListener('submit', (e) => { e.preventDefault(); submit(); });

async function runCommand(raw) {
  const text = raw.trim();
  if (!text) return;
  const parts = text.toUpperCase().split(/\s+/);
  const [verb, ...args] = parts;
  const tick = (i = 0) => resolveTicker(args[i]) || S.selected;
  switch (verb) {
    case 'HELP': case 'H': case '?': show('help'); return;
    case 'MON': case 'MONITOR': case 'HOME': restore(); show('monitor'); return;
    case 'SET': case 'SETTINGS': case 'CONFIG': show('settings'); emit('cmd:settings', (args[0] || '').toLowerCase()); return;
    case 'KEYS': connect(); return;
    case 'BT': case 'BACKTEST': {
      show('backtest');
      const ts = args.map((a) => resolveTicker(a) || (a.includes('.') ? a : `${a}.US`));
      emit('cmd:bt', ts);
      return;
    }
    case 'BUY': case 'SELL': {
      const rest = args.filter((a) => a !== '@');
      const ticker = resolveTicker(rest[0]) || S.selected;
      const nums = rest.filter((a) => /^[\d.]+$/.test(a)).map(Number);
      orderTicket({ ticker, side: verb, qty: nums[0], limit: nums[1] });
      return;
    }
    case 'CLOSE': closePosition(tick()); return;
    case 'ADD': addTicker(args[0] || ''); return;
    case 'DEL': case 'REMOVE': {
      const t = resolveTicker(args[0]);
      if (!t) { toast('Usage: DEL TICKER', 'warn'); return; }
      if (await confirmDialog({ title: `Remove ${t}`, text: `Remove ${t} from the watchlist? Open positions are not touched.`, confirmLabel: 'Remove' })) removeTicker(t);
      return;
    }
    case 'TF': {
      const m = (args[0] || '').toLowerCase();
      const tf = { '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '60m': '1h', '1d': '1D', 'd': '1D', '1w': '1W', 'w': '1W' }[m];
      emit('cmd:tf', tf || m);
      restore(); show('monitor');
      return;
    }
    case 'NEWS': case 'N': case 'TOP':
      maximize('news');
      if (args[0]) emit('cmd:news', resolveTicker(args[0]));
      return;
    case 'AI':
      if (args[0] === 'ON' || args[0] === 'OFF') {
        await post('/api/control', { action: args[0] === 'ON' ? 'ai_on' : 'ai_off' });
        toast(`AI review ${args[0].toLowerCase()}`);
      } else maximize('ai');
      return;
    case 'PORT': case 'POS': case 'P': maximize('port'); return;
    case 'GP': case 'CHART': if (args[0]) select(tick()); maximize('chart'); return;
    case 'DES': if (args[0]) select(tick()); maximize('detail'); return;
    case 'SCAN': await post('/api/control', { action: 'scan' }); toast('Scanning the watchlist'); return;
    case 'POLL': await post('/api/control', { action: 'news' }); toast('Polling news sources'); return;
    case 'HALT': case 'KILL': case 'STOP': if (!S.app.halted) await toggleHalt(); else toast('Trading is already halted', 'warn'); return;
    case 'RESUME': if (S.app.halted) await toggleHalt(); else toast('Trading is not halted'); return;
    case 'MODE': {
      const m = (args[0] || '').toLowerCase();
      if (!['off', 'paper', 'live'].includes(m)) { toast('Usage: MODE OFF | PAPER | LIVE', 'warn'); return; }
      await setExecution(m);
      return;
    }
    case 'QUIT': case 'EXIT':
      if (S.app.shell !== 'desktop') { toast('Meridian keeps running on the server. Close this tab to leave.', 'warn'); return; }
      if (await confirmDialog({ title: 'Quit Meridian', text: 'The engine stops: no scans, no reviews, no orders until you open it again. Broker-side stops stay active.', confirmLabel: 'Quit' })) {
        await post('/api/control', { action: 'quit' });
      }
      return;
    default: {
      const t = resolveTicker(verb);
      if (t && watchlist().includes(t)) { select(t); restore(); show('monitor'); return; }
      const guess = t || `${verb}.US`;
      toast(`${guess} is not on your watchlist. Opening the add dialog.`, 'warn');
      addTicker(verb);
    }
  }
}
on('cmd', (c) => runCommand(c).catch((e) => toast(e.message, 'error')));

// ---------- keyboard ----------
const FKEY = { F1: 'help', F2: 'monitor', F3: 'max:news', F4: 'max:ai', F5: 'max:port', F6: 'backtest', F7: 'max:chart', F8: 'settings', F9: 'ticket' };
document.addEventListener('keydown', (e) => {
  if (modalOpen()) return;
  const k = e.key;
  if (FKEY[k]) { e.preventDefault(); emit('fkey', FKEY[k]); return; }
  const typing = e.target.closest && e.target.closest('input, textarea, select, [contenteditable]');
  if (k === 'Escape' && !typing) {
    if (!restore() && screen !== 'monitor') show('monitor');
    return;
  }
  if (typing) return;
  if ((k.toLowerCase() === 'k' && (e.ctrlKey || e.metaKey)) || k === '/') { e.preventDefault(); cmdInput.focus(); return; }
  if (screen === 'monitor' && (k === 'ArrowDown' || k === 'ArrowUp')) {
    e.preventDefault(); moveSelection(k === 'ArrowDown' ? 1 : -1); return;
  }
  if (!e.ctrlKey && !e.metaKey && !e.altKey && k.length === 1 && /[A-Za-z0-9]/.test(k)) cmdInput.focus();
});

// ---------- boot ----------
async function boot() {
  const token = readToken();
  setToken(token);
  if (!token) { showLocked(); return; }
  const grid = document.getElementById('grid');
  panels.watch = mountWatchlist(grid);
  panels.chart = mountChart(grid);
  panels.acct = mountAccount(grid);
  panels.detail = mountDetail(grid);
  panels.sys = mountSystem(grid);
  panels.news = mountNews(grid);
  panels.ai = mountDecisions(grid);
  panels.port = mountPortfolio(grid);
  mountTopbar();
  mountBacktest(document.getElementById('scr-backtest'));
  mountSettings(document.getElementById('scr-settings'));
  emit('screen-changed', 'monitor');
  try { await get('/api/settings'); } catch { return; }
  connectWS();
}
boot();
