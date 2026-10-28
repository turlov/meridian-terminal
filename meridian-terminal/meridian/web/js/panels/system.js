// SYS — health of every feed (market data, account sync, Claude, news sources), the rule
// scan timer, and the live event log.
import { S, on, h, fmt, panel, clear, setText } from '../core.js';

export function mountSystem(grid) {
  let level = 'all';
  const lvlBtns = [['all', 'All'], ['warn', 'Warnings']].map(([k, l]) => h('button', { class: `tbtn ${k === level ? 'on' : ''}`, 'data-k': k,
    onclick: () => { level = k; lvlBtns.forEach((b) => b.classList.toggle('on', b.dataset.k === k)); renderLog(); } }, l));
  const p = panel('sys', 'SYS', 'System', lvlBtns);
  grid.append(p.el);
  const feeds = h('tbody');
  const logEl = h('div', { class: 'log', 'aria-live': 'off' });
  p.body.append(h('table', { class: 't feeds fixed' },
    h('colgroup', {}, h('col', { style: { width: '22px' } }), h('col', { style: { width: '120px' } }), h('col', { style: { width: '72px' } }), h('col')),
    feeds), logEl);
  let stick = true;
  p.body.addEventListener('scroll', () => {
    stick = p.body.scrollTop + p.body.clientHeight >= p.body.scrollHeight - 30;
  });

  function dot(ok) { return h('span', { class: `dot ${ok === true ? 'ok' : ok === false ? 'bad' : 'warn'}` }); }
  function feedRow(ok, name, when, info, title = '') {
    return h('tr', { title }, h('td', {}, dot(ok)), h('td', { title: name }, name), h('td', { class: 'dim' }, when),
      h('td', { class: ok === false ? 'down' : 'dim' }, info));
  }

  function renderFeeds() {
    const st = S.status || {};
    const m = st.market || {};
    clear(feeds);
    feeds.append(feedRow(m.ok, 'Market data', fmt.ago(m.last),
      m.ok === false ? m.error : `${m.label || ''}, ${Object.keys(S.quotes || {}).length} quotes / ${(st.intervals || {}).quotes_sec || '?'}s`, m.error));
    if (!S.app.demo) {
      const a = st.account || {};
      feeds.append(feedRow(a.ok, 'Account sync', fmt.ago(a.last), a.ok === false ? a.error : 'Freedom Broker positions and orders', a.error));
    }
    const ai = st.ai || {};
    feeds.append(feedRow(ai.available === false ? false : ai.ok, 'AI reviewer',
      fmt.ago(ai.last), ai.available === false ? 'No Anthropic key' : ai.ok === false ? ai.error
        : ai.demo ? 'Simulated, no API calls' : `${((ai.models || {}).review || '').replace('claude-', '')}${ai.latency ? `, ${ai.latency}s` : ''}`, ai.error));
    for (const s of st.sources || []) {
      feeds.append(feedRow(s.ok, s.label, fmt.ago(s.last), s.ok === false ? s.error : `${s.count} items`, s.error));
    }
    const sc = st.scan || {};
    feeds.append(feedRow(sc.error ? false : sc.running ? null : true, 'Rule scan',
      sc.running ? 'running' : fmt.ago(sc.last), sc.error || (sc.next ? `next in ${fmt.dur(sc.next - Date.now() / 1000)}` : 'starting')));
    if (st.notice) feeds.append(feedRow(null, 'Notice', '', st.notice));
  }

  function line(e) {
    return h('div', { class: e.level }, h('span', { class: 'ts' }, fmt.time(e.ts)), e.msg);
  }
  const keep = (e) => level === 'all' || ['WARNING', 'ERROR', 'CRITICAL'].includes(e.level);
  function renderLog() {
    clear(logEl);
    for (const e of (S.log || []).filter(keep).slice(-300)) logEl.append(line(e));
    if (stick) p.body.scrollTop = p.body.scrollHeight;
  }

  on('state', () => { renderFeeds(); renderLog(); });
  on('status', renderFeeds);
  on('app', renderFeeds);
  on('log', (e) => {
    if (!keep(e)) return;
    logEl.append(line(e));
    while (logEl.children.length > 400) logEl.firstChild.remove();
    if (stick) p.body.scrollTop = p.body.scrollHeight;
  });
  setInterval(() => { if (!document.hidden) renderFeeds(); }, 5000);
  setText(p.sub, '');
  return p;
}
