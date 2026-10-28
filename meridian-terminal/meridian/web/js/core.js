// Shared state, events, API client, formatting and DOM helpers.

export const S = {
  app: {}, status: {}, settings: {}, quotes: {}, snapshots: {}, positions: [], orders: [],
  account: {}, broker: {}, decisions: [], news: [], trades: [], usage: {}, log: [], jobs: [],
  selected: null, connected: false, ready: false,
};

// ---------- events ----------
const listeners = {};
export function on(type, fn) { (listeners[type] ||= []).push(fn); }
export function emit(type, data) {
  for (const fn of listeners[type] || []) {
    try { fn(data); } catch (e) { console.error(`[${type}]`, e); }
  }
}

// ---------- API ----------
let TOKEN = '';
export function setToken(t) { TOKEN = t; }
export function getToken() { return TOKEN; }

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { 'X-Token': TOKEN, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (res.status === 401) emit('unauthorized');
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}
export const get = (p) => api(p);
export const post = (p, body = {}) => api(p, { method: 'POST', body });

// ---------- formatting ----------
const nf = (d) => new Intl.NumberFormat('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const NF = { 0: nf(0), 1: nf(1), 2: nf(2), 3: nf(3), 4: nf(4) };
const ok = (n) => n !== null && n !== undefined && Number.isFinite(+n);

export const fmt = {
  num(n, d = 2) { return ok(n) ? (NF[d] || nf(d)).format(+n) : '—'; },
  px(n) {
    if (!ok(n)) return '—';
    const a = Math.abs(+n);
    return NF[a >= 1000 ? 2 : a >= 1 ? 2 : 4].format(+n);
  },
  signed(n, d = 2) { return ok(n) ? (n > 0 ? '+' : '') + (NF[d] || nf(d)).format(+n) : '—'; },
  pct(n, d = 2) { return ok(n) ? (n > 0 ? '+' : '') + (NF[d] || nf(d)).format(+n) + '%' : '—'; },
  frac(n, d = 1) { return ok(n) ? fmt.pct(n * 100, d) : '—'; },
  money(n, d = 2) { return ok(n) ? (n < 0 ? '-' : '') + '$' + (NF[d] || nf(d)).format(Math.abs(+n)) : '—'; },
  compact(n) {
    if (!ok(n)) return '—';
    const a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e8 ? 0 : 1) + 'M';
    if (a >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return NF[0].format(n);
  },
  time(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleTimeString('en-GB', { hour12: false });
  },
  hm(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    const today = new Date();
    if (d.toDateString() === today.toDateString())
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
  },
  date(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  },
  ago(ts) {
    if (!ts) return 'never';
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 5) return 'just now';
    if (s < 60) return `${Math.floor(s)}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  },
  dur(s) {
    if (!ok(s)) return '—';
    s = Math.max(0, Math.round(s));
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
    return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
  },
  cls(n) { return !ok(n) || +n === 0 ? '' : n > 0 ? 'up' : 'down'; },
};

export const RULE_LABELS = {
  trend_breakout: 'Trend breakout', mean_reversion: 'Oversold bounce', volume_surge: 'Volume surge',
  trend_exit: 'Trend exit', overbought_exit: 'Overbought exit', news: 'News',
};
export const RULE_SHORT = {
  trend_breakout: 'BRK', mean_reversion: 'OVS', volume_surge: 'VOL', trend_exit: 'XTR',
  overbought_exit: 'XOB', news: 'NEWS',
};

// ---------- DOM ----------
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function add(el, ...kids) {
  el.append(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  return el;
}
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
export function setText(el, text) { if (el.textContent !== text) el.textContent = text; }

export function panel(area, code, title, tools = []) {
  const titleEl = h('h2', {}, title);
  const sub = h('span', { class: 'sub' });
  const toolsEl = h('div', { class: 'tools' }, ...tools,
    h('button', { class: 'tbtn icon', title: 'Maximize (double-click the title bar)', 'aria-label': 'Maximize panel',
      onclick: () => toggleMax(el) }, '⤢'));
  const head = h('header', { class: 'ph', ondblclick: (e) => { if (!e.target.closest('button,input,select')) toggleMax(el); } },
    h('span', { class: 'fn' }, code), titleEl, sub, toolsEl);
  const body = h('div', { class: 'pb' });
  const el = h('section', { class: 'panel', 'data-area': area, style: { gridArea: area } }, head, body);
  return { el, body, titleEl, sub, toolsEl };
}

export function toggleMax(panelEl, force) {
  const grid = panelEl.parentElement;
  const isMax = panelEl.classList.contains('max');
  const want = force === undefined ? !isMax : force;
  grid.querySelectorAll('.panel.max').forEach((p) => p.classList.remove('max'));
  grid.classList.toggle('has-max', want);
  if (want) panelEl.classList.add('max');
  window.dispatchEvent(new Event('resize'));
  emit('layout');
}

// ---------- toasts ----------
export function toast(text, level = 'info', ms = 5000) {
  const box = $('#toasts');
  const el = h('div', { class: `toast ${level}`, role: 'status' }, text);
  box.append(el);
  while (box.children.length > 5) box.firstChild.remove();
  setTimeout(() => el.remove(), level === 'error' || level === 'live' ? ms * 2 : ms);
}

// ---------- modals ----------
let openModals = 0;
export function modalOpen() { return openModals > 0; }

export function modal({ title, code = '', body, actions = [], wide = false, onClose }) {
  const root = $('#modal-root');
  const content = h('div', { class: 'modal-b' });
  const footer = h('div', { class: 'modal-f' });
  const box = h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('div', { class: 'modal-h' }, code ? h('span', { class: 'fn' }, code) : null, h('h3', {}, title),
      h('button', { class: 'tbtn icon', 'aria-label': 'Close', onclick: () => close() }, '✕')),
    content, footer);
  const back = h('div', { class: 'modal-back', onmousedown: (e) => { if (e.target === back) close(); } }, box);
  let closed = false;
  function close(result) {
    if (closed) return;
    closed = true;
    openModals--;
    back.remove();
    document.removeEventListener('keydown', onKey, true);
    onClose && onClose(result);
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  }
  document.addEventListener('keydown', onKey, true);
  openModals++;
  if (typeof body === 'function') body(content, close);
  else if (body) content.append(body);
  for (const a of actions) {
    footer.append(h('button', { class: `btn ${a.kind || ''}`, type: 'button',
      onclick: () => a.onClick ? a.onClick(close) : close() }, a.label));
  }
  if (!actions.length) footer.remove();
  root.append(back);
  setTimeout(() => (box.querySelector('input:not([type=checkbox]),select,textarea') || box.querySelector('.modal-f .btn:last-child') || box).focus?.(), 30);
  return close;
}

export function confirmDialog({ title, text, confirmLabel = 'Confirm', danger = false, typeToConfirm = '' }) {
  return new Promise((resolve) => {
    let input = null;
    const err = h('div', { class: 'err-text' });
    const submit = () => {
      if (typeToConfirm && input.value.trim() !== typeToConfirm) {
        err.textContent = `Type ${typeToConfirm} exactly to continue.`;
        input.classList.add('err');
        return;
      }
      closeFn(true);
    };
    const closeFn = modal({
      title, code: '!', onClose: (r) => resolve(r === true),
      body: (el) => {
        el.append(h('p', {}, text));
        if (typeToConfirm) {
          input = h('input', { class: 'inp', placeholder: `Type ${typeToConfirm} to confirm`, style: { width: '100%' },
            onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } } });
          el.append(input, err);
        }
      },
      actions: [
        { label: 'Cancel', kind: 'ghost' },
        { label: confirmLabel, kind: danger ? 'danger' : 'primary', onClick: () => submit() },
      ],
    });
  });
}

// ---------- selection ----------
export function select(ticker) {
  if (!ticker || S.selected === ticker) return;
  S.selected = ticker;
  try { localStorage.setItem('meridian.selected', ticker); } catch { /* storage unavailable */ }
  emit('select', ticker);
}

export function watchlist() {
  return (S.settings.watchlist || []).map((w) => w.ticker);
}

export function nameOf(t) {
  const q = S.quotes[t];
  if (q && q.name) return q.name;
  const w = (S.settings.watchlist || []).find((x) => x.ticker === t);
  return (w && w.keywords && w.keywords[0]) || '';
}

export function heldQty(t) {
  const p = (S.positions || []).find((x) => x.ticker === t);
  return p ? p.qty : 0;
}

export async function openUrl(url) {
  if (!url) return;
  if (S.app.shell === 'desktop') {
    try { await post('/api/open-url', { url }); return; } catch (e) { toast(e.message, 'error'); }
  }
  window.open(url, '_blank', 'noopener');
}

export function acctLabel() {
  return { demo: 'DEMO', paper: 'PAPER', live: 'LIVE', off: 'SIGNALS ONLY' }[S.app.acct] || '—';
}
