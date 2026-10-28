// AI — the decision desk: every rule/news idea, Claude's verdict, and what the risk gate did.
import { S, on, h, fmt, panel, clear, setText, emit, post, toast, RULE_LABELS } from '../core.js';

export function outcome(d) {
  const r = d.reason || '';
  if (r.startsWith('order failed') || r.startsWith('review failed')) return ['error', 'ERROR', r];
  if (d.approved && r.includes('execution is off')) return ['signal', 'SIGNAL', 'Approved; execution is off (signals only)'];
  if (d.approved && d.order) return ['placed', 'ORDER', `${d.order.side} ${d.order.qty} @ ${fmt.px(d.order.limit)}`];
  if (!d.verdict) return ['rejected', 'SKIPPED', r];
  return ['rejected', 'NO TRADE', r];
}

export function mountDecisions(grid) {
  const aiBtn = h('button', { class: 'tbtn', title: 'Turn AI review on or off', onclick: async () => {
    const on_ = !S.app.ai_enabled;
    try { await post('/api/control', { action: on_ ? 'ai_on' : 'ai_off' }); } catch (e) { toast(e.message, 'error'); }
  } }, 'AI');
  const p = panel('ai', 'AI', 'AI desk', [aiBtn]);
  grid.append(p.el);
  const tbody = h('tbody');
  p.body.append(h('table', { class: 't fixed' },
    h('thead', {}, h('tr', {}, h('th', { style: { width: '60px' } }, 'Time'), h('th', { style: { width: '74px' } }, 'Ticker'),
      h('th', { style: { width: '112px' } }, 'Trigger'), h('th', { style: { width: '46px' } }, 'Call'),
      h('th', { style: { width: '74px' } }, 'Conf'), h('th', {}, 'Result'))), tbody));

  function row(d, fresh = false) {
    const v = d.verdict;
    const [cls, label, text] = outcome(d);
    const trig = (d.candidates || []).map((c) => RULE_LABELS[c.strategy] || c.strategy).join(', ');
    return h('tr', { class: `clickable ${fresh ? 'fresh' : ''}`, onclick: () => emit('dialog:decision', d.id), title: 'Open the full reasoning' },
      h('td', { class: 'dim' }, fmt.time(d.ts).slice(0, 5)),
      h('td', { class: 'tk' }, d.ticker),
      h('td', { title: d.trigger }, trig),
      h('td', {}, v ? h('span', { class: `verdict ${v.action}` }, v.action) : h('span', { class: 'faint' }, '—')),
      h('td', {}, v ? h('span', { class: 'conf' }, h('span', { class: 'track' }, h('i', { style: { width: `${Math.round(v.confidence * 38)}px` } })), fmt.num(v.confidence * 100, 0)) : ''),
      h('td', { title: text }, h('span', { class: `res ${cls}` }, label), ' ', h('span', { class: 'dim' }, text)));
  }

  function header() {
    const st = S.status.ai || {};
    const u = S.usage || {};
    aiBtn.textContent = S.app.ai_enabled ? 'AI on' : 'AI off';
    aiBtn.classList.toggle('on', !!S.app.ai_enabled);
    const model = (S.settings.models || {}).review || '';
    const spend = u.demo ? 'demo reviewer, no cost' : `${u.calls || 0} calls  ${fmt.money(u.cost || 0)} of ${fmt.money(u.budget || 0)} today`;
    setText(p.sub, st.available === false ? 'Add an Anthropic key in Settings to enable reviews' :
      `${st.demo ? 'Simulated' : model.replace('claude-', '')}  ${spend}`);
  }

  function render() {
    clear(tbody);
    if (!S.decisions.length) {
      tbody.append(h('tr', {}, h('td', { colspan: 6, class: 'wrap' }, h('div', { class: 'empty' },
        'No trade ideas yet. Rules scan the watchlist on a timer and material news triggers a review; every idea and verdict lands here.'))));
    }
    for (const d of S.decisions.slice(0, 200)) tbody.append(row(d));
    header();
  }

  on('state', render);
  on('decision', (d) => {
    const first = tbody.firstChild;
    if (first && first.querySelector('.empty')) clear(tbody);
    tbody.prepend(row(d, true));
    while (tbody.children.length > 210) tbody.lastChild.remove();
  });
  on('usage', header);
  on('status', header);
  on('app', header);
  on('settings', header);
  return p;
}
