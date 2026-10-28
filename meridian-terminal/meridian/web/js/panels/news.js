// TOP — news feed with Claude materiality scores. Click a headline to expand it.
import { S, on, h, fmt, panel, clear, setText, openUrl, select, post, toast } from '../core.js';

const FILTERS = [['watch', 'Watchlist'], ['sel', 'Selected'], ['material', 'Material'], ['all', 'All']];

export function mountNews(grid) {
  let filter = 'watch';
  try { filter = localStorage.getItem('meridian.newsFilter') || 'watch'; } catch { /* ignore */ }
  const chips = FILTERS.map(([k, label]) => h('button', { class: `tbtn ${k === filter ? 'on' : ''}`, 'data-k': k,
    onclick: () => setFilter(k) }, label));
  const p = panel('news', 'TOP', 'News', [h('div', { class: 'chips' }, chips),
    h('button', { class: 'tbtn', title: 'Poll all news sources now', onclick: async () => {
      try { await post('/api/control', { action: 'news' }); toast('Polling news sources'); } catch (e) { toast(e.message, 'error'); }
    } }, '↻')]);
  grid.append(p.el);
  const tbody = h('tbody');
  p.body.append(h('table', { class: 't fixed' },
    h('thead', {}, h('tr', {}, h('th', { style: { width: '50px' } }, 'Time'), h('th', { style: { width: '74px' } }, 'Source'),
      h('th', { style: { width: '78px' } }, 'Tickers'), h('th', { style: { width: '34px' }, title: 'Claude materiality score 0–10' }, 'AI'),
      h('th', {}, 'Headline'))), tbody));
  const rowById = new Map();
  let open = null;

  const minScore = () => (S.settings.ai || {}).min_triage_score ?? 6;
  function passes(n) {
    const tk = n.tickers || [];
    if (filter === 'all') return true;
    if (filter === 'sel') return tk.includes(S.selected);
    if (filter === 'material') return n.score >= minScore();
    return tk.length > 0;
  }

  function scoreEl(n) {
    if (n.score === null || n.score === undefined) return h('span', { class: 'score', title: 'Not scored (no watchlist ticker, too old, or AI off)' }, '·');
    const cls = n.score >= minScore() ? 'hi' : n.score >= 4 ? 'mid' : '';
    return h('span', { class: `score ${cls}`, title: `Materiality ${n.score}/10${n.scored_ticker ? ' for ' + n.scored_ticker : ''}` }, String(n.score));
  }

  function row(n, fresh = false) {
    const tr = h('tr', { class: `clickable news-row ${n.score >= minScore() ? 'material' : ''} ${fresh ? 'fresh' : ''}`,
      onclick: () => toggle(n, tr) },
      h('td', { class: 'dim' }, fmt.hm(n.published)),
      h('td', { class: 'src', title: n.source }, n.source),
      h('td', { class: 'tks', title: (n.tickers || []).join(' ') }, (n.tickers || []).map((t) => t.split('.')[0]).join(' ')),
      h('td', {}, scoreEl(n)),
      h('td', { class: 'hl', title: n.headline }, n.headline));
    rowById.set(n.id, tr);
    return tr;
  }

  function toggle(n, tr) {
    if (open) { open.remove(); const same = open._for === n.id; open = null; if (same) return; }
    const actions = h('div', { class: 'row', style: { marginTop: '6px' } },
      n.url ? h('button', { class: 'btn sm', onclick: (e) => { e.stopPropagation(); openUrl(n.url); } }, 'Open article') : null,
      ...(n.tickers || []).map((t) => h('button', { class: 'btn sm ghost', onclick: (e) => { e.stopPropagation(); select(t); } }, `Show ${t}`)));
    open = h('tr', { class: 'news-detail' }, h('td', { colspan: 5 },
      h('div', {}, n.summary || h('span', { class: 'dim' }, 'No summary from the source.')),
      h('div', { class: 'dim', style: { marginTop: '4px', fontSize: '12px' } },
        `${fmt.date(n.published)} ${fmt.time(n.published)}  from ${n.source}`), actions));
    open._for = n.id;
    tr.after(open);
  }

  function render() {
    clear(tbody);
    rowById.clear();
    open = null;
    const items = S.news.filter(passes).slice(0, 250);
    if (!items.length) {
      tbody.append(h('tr', {}, h('td', { colspan: 5, class: 'wrap' }, h('div', { class: 'empty' },
        filter === 'sel' ? `No recent headlines for ${S.selected || 'the selected ticker'}.` :
        filter === 'material' ? 'No material stories yet. Claude scores fresh watchlist headlines as they arrive.' :
        'Waiting for news. Sources are polled every few seconds in demo mode and every 30–120 seconds on live data.'))));
    }
    for (const n of items) tbody.append(row(n));
    count();
  }

  function count() {
    const n = S.news.filter(passes).length;
    setText(p.sub, `${n} ${n === 1 ? 'story' : 'stories'}`);
  }

  function setFilter(k) {
    filter = k;
    try { localStorage.setItem('meridian.newsFilter', k); } catch { /* ignore */ }
    chips.forEach((c) => c.classList.toggle('on', c.dataset.k === k));
    render();
  }

  on('state', render);
  on('news', (n) => {
    if (!passes(n)) return;
    const first = tbody.firstChild;
    if (first && first.querySelector('.empty')) clear(tbody);
    tbody.prepend(row(n, true));
    while (tbody.children.length > 260) tbody.lastChild.remove();
    count();
  });
  on('news_score', (u) => {
    const tr = rowById.get(u.id);
    if (!tr) { if (filter === 'material') render(); return; }
    const n = S.news.find((x) => x.id === u.id);
    if (!n) return;
    tr.children[3].replaceChildren(scoreEl(n));
    tr.classList.toggle('material', n.score >= minScore());
  });
  on('select', () => { if (filter === 'sel') render(); });
  on('cmd:news', (t) => { if (t) { select(t); setFilter('sel'); } });
  return p;
}
