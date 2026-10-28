// F8 — settings: accounts & keys, watchlist, strategies, risk, AI, news feeds, remote access, about.
import { S, on, h, fmt, get, post, toast, clear, confirmDialog, getToken, RULE_LABELS, emit } from '../core.js';
import { connect } from '../dialogs.js';

const SECTIONS = [
  ['accounts', 'Accounts & data'], ['watchlist', 'Watchlist'], ['rules', 'Strategies'], ['risk', 'Risk limits'],
  ['ai', 'AI models & budget'], ['feeds', 'News feeds & timing'], ['remote', 'Remote access & files'], ['about', 'About'],
];
const MODELS = [['claude-haiku-5-5', 'Haiku 5.5 (fast, cheapest)'], ['claude-sonnet-5-5', 'Sonnet 5.5'],
  ['claude-opus-5-5', 'Opus 5.5 (strong)'], ['claude-fable-5-1', 'Fable 5.1 (strongest, priciest)']];
const RULE_HELP = {
  trend_breakout: 'Buy when price makes a new 20-day high while SMA50 is above SMA200.',
  mean_reversion: 'Buy when RSI(14) drops below 30 but price stays above SMA200.',
  volume_surge: 'Buy on an up day of more than 3% with over 2.5x normal volume.',
  trend_exit: 'Sell a holding when price closes below SMA50.',
  overbought_exit: 'Sell a holding when RSI(14) rises above 78.',
};

export function mountSettings(root) {
  let section = 'accounts';
  const nav = h('div', { class: 'nav-list' });
  const body = h('div', { class: 'page-body' });
  root.append(h('div', { class: 'page' },
    h('aside', {}, h('div', { class: 'page-h' }, h('span', { class: 'fn' }, 'SET'), h('h2', {}, 'Settings')), nav),
    h('section', {}, body)));

  function renderNav() {
    clear(nav);
    for (const [k, label] of SECTIONS) {
      nav.append(h('button', { class: `nav-item ${k === section ? 'on' : ''}`, onclick: () => { section = k; render(); } }, label));
    }
  }

  const val = (path) => path.split('.').reduce((o, k) => (o ? o[k] : undefined), S.settings);
  function numField(label, path, help = '', step = 'any') {
    const input = h('input', { class: 'inp', type: 'number', step, value: val(path) ?? '', 'data-path': path });
    return h('div', { class: 'field' }, h('label', {}, label), input, help ? h('span', { class: 'help' }, help) : null);
  }
  function collect(container) {
    const patch = {};
    for (const el of container.querySelectorAll('[data-path]')) {
      const parts = el.dataset.path.split('.');
      let v = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
      if (el.type === 'number' && el.value === '') throw new Error(`${el.closest('.field')?.querySelector('label')?.textContent || 'A field'} is empty`);
      let o = patch;
      parts.slice(0, -1).forEach((k) => { o = o[k] ||= {}; });
      o[parts[parts.length - 1]] = v;
    }
    return patch;
  }
  async function save(patch, msg = 'Settings saved') {
    try { S.settings = await post('/api/settings', patch); toast(msg); emit('settings'); return true; }
    catch (e) { toast(e.message, 'error'); return false; }
  }
  const saveBtn = (container, extra = () => ({})) => h('button', { class: 'btn primary', onclick: async () => {
    let patch;
    try { patch = { ...collect(container), ...extra() }; } catch (e) { toast(e.message, 'error'); return; }
    if (await save(patch)) render();
  } }, 'Save changes');

  const views = {
    accounts() {
      const sec = S.settings.secrets || {};
      const live = S.settings.data_mode === 'live';
      const box = h('div', { class: 'set-section' },
        h('h3', {}, 'Accounts & data'),
        h('p', { class: 'lede' }, 'Meridian uses Freedom Broker (Tradernet) for prices and orders and Claude for news scoring and trade review. Keys stay on this computer.'),
        h('div', { class: 'field' }, h('label', {}, 'Market data'),
          h('div', { class: 'seg' },
            h('button', { class: !live ? 'on' : '', onclick: () => save({ data_mode: 'demo' }, 'Switched to demo data').then(render) }, 'Demo (simulated)'),
            h('button', { class: live ? 'on' : '', onclick: () => {
              if (!(sec.tradernet_public_key || {}).set) { toast('Add your Tradernet keys first', 'warn'); return; }
              save({ data_mode: 'live' }, 'Switched to live Tradernet data').then(render);
            } }, 'Tradernet (live)')),
          h('span', { class: 'help' }, 'Switching restarts the engine. Demo and paper accounts are kept separate, so simulated trades never mix with real-price paper trades.')),
        h('div', { class: 'section-h', style: { padding: '8px 0 6px' } }, 'API keys'),
        ...[['anthropic_api_key', 'Anthropic'], ['tradernet_public_key', 'Tradernet public'], ['tradernet_private_key', 'Tradernet private'], ['finnhub_api_key', 'Finnhub']]
          .map(([k, label]) => {
            const s = sec[k] || {};
            return h('div', { class: 'keyrow' }, h('label', {}, label), h('span', { class: s.set ? 'up' : 'dim' },
              s.set ? `saved ${s.masked}${s.from_env ? ' (from environment)' : ''}` : 'not set'), h('span'), h('span'));
          }),
        h('div', { class: 'row', style: { margin: '6px 0 16px' } },
          h('button', { class: 'btn primary', onclick: () => connect() }, 'Add or change keys'),
          h('span', { class: 'help dim cond' }, `Stored in ${S.settings.secrets_backend === 'file' ? 'a protected file in the data folder' : S.settings.secrets_backend}.`)),
        h('div', { class: 'field' }, h('label', {}, 'SEC contact (user agent)'),
          h('input', { class: 'inp', 'data-path': 'sec_user_agent', value: S.settings.sec_user_agent || '', placeholder: 'Your Name you@example.com' }),
          h('span', { class: 'help' }, 'The SEC asks automated readers of its filing feed to identify themselves.')));
      box.append(saveBtn(box));
      return box;
    },

    watchlist() {
      const rows = (S.settings.watchlist || []).map((w) => ({ ...w, keywords: [...(w.keywords || [])] }));
      const tbody = h('tbody');
      const draw = () => {
        clear(tbody);
        rows.forEach((w, i) => tbody.append(h('tr', {},
          h('td', { class: 'tk', style: { width: '130px' } }, w.ticker),
          h('td', {}, h('input', { class: 'inp', value: w.keywords.join(', '), oninput: (e) => { w.keywords = e.target.value.split(',').map((x) => x.trim()).filter(Boolean); } })),
          h('td', { style: { width: '90px' } },
            h('button', { class: 'xbtn', title: 'Move up', disabled: i === 0, onclick: () => { [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]]; draw(); } }, '▲'),
            h('button', { class: 'xbtn', title: 'Move down', disabled: i === rows.length - 1, onclick: () => { [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]]; draw(); } }, '▼'),
            h('button', { class: 'xbtn', title: 'Remove', onclick: () => { rows.splice(i, 1); draw(); } }, '✕')))));
      };
      draw();
      return h('div', { class: 'set-section' },
        h('h3', {}, 'Watchlist'),
        h('p', { class: 'lede' }, 'The bot only ever trades tickers on this list. Keywords match headlines to tickers, so use the names the press uses.'),
        h('table', { class: 't wl-edit' }, h('thead', {}, h('tr', {}, h('th', {}, 'Ticker'), h('th', {}, 'Headline keywords'), h('th', {}))), tbody),
        h('div', { class: 'row', style: { marginTop: '10px' } },
          h('button', { class: 'btn', onclick: () => emit('dialog:add') }, '+ Add ticker'),
          h('button', { class: 'btn primary', onclick: () => save({ watchlist: rows }, 'Watchlist saved').then(render) }, 'Save watchlist')));
    },

    rules() {
      const enabled = new Set((S.settings.rules || {}).enabled || []);
      return h('div', { class: 'set-section' },
        h('h3', {}, 'Strategies'),
        h('p', { class: 'lede' }, 'Rules propose trades; Claude reviews them; the risk gate decides. Switch off any rule that did not beat buy-and-hold in the backtest. News triggers are always on while AI review is on.'),
        ...Object.keys(RULE_HELP).map((r) => h('label', { class: 'check', style: { padding: '6px 0' } },
          h('input', { type: 'checkbox', checked: enabled.has(r), onchange: (e) => (e.target.checked ? enabled.add(r) : enabled.delete(r)) }),
          h('span', {}, h('span', { class: 'amber' }, RULE_LABELS[r]), h('br'), h('span', { class: 'help cond' }, RULE_HELP[r])))),
        h('div', { class: 'row', style: { marginTop: '10px' } },
          h('button', { class: 'btn primary', onclick: () => save({ rules: { enabled: [...enabled] } }, 'Strategies saved').then(render) }, 'Save strategies'),
          h('button', { class: 'btn ghost', onclick: () => emit('screen', 'backtest') }, 'Open backtest')));
    },

    risk() {
      const box = h('div', { class: 'set-section' },
        h('h3', {}, 'Risk limits'),
        h('p', { class: 'lede' }, 'Enforced in code on every automatic order; Claude cannot change them. Margin and short selling are always off.'),
        h('div', { class: 'grid2' },
          numField('Risk per trade (USD)', 'risk.risk_per_trade_usd', 'Loss if the stop is hit. Sets position size.'),
          numField('Max position size (USD)', 'risk.max_usd_per_trade', 'Hard cap on any one position.'),
          numField('Stop distance (x ATR)', 'risk.atr_stop_mult', 'Stop = entry minus this many ATRs.'),
          numField('Target distance (x ATR)', 'risk.atr_target_mult', 'Take-profit = entry plus this many ATRs.'),
          numField('Max open positions', 'risk.max_open_positions', '', '1'),
          numField('Max daily loss (USD)', 'risk.max_daily_loss_usd', 'No new trades once the day is down this much.'),
          numField('Ticker cooldown (minutes)', 'risk.ticker_cooldown_min', 'No repeat trade or re-review of the same signal within this time.', '1'),
          numField('Max slippage (%)', 'risk.max_slippage_pct', 'Limit price offset from the last price.'),
          numField('Max news age (minutes)', 'risk.max_news_age_min', 'Older stories are not traded.', '1'),
          numField('Manual order cap (USD)', 'risk.manual_max_usd', 'Largest order you can type in by hand.'),
          numField('Paper starting cash (USD)', 'paper.starting_cash', 'Used when the paper account is reset.')));
      box.append(h('div', { class: 'row' }, saveBtn(box),
        h('button', { class: 'btn danger', style: { marginLeft: 'auto' }, onclick: async () => {
          const ok = await confirmDialog({ title: 'Reset the paper account', text: `Deletes all ${S.app.demo ? 'demo' : 'paper'} positions, orders and trades and restarts with ${fmt.money(S.settings.paper.starting_cash, 0)}. Live data is not touched.`, confirmLabel: 'Reset paper account', danger: true });
          if (!ok) return;
          try { await post('/api/control', { action: 'reset_paper' }); toast('Paper account reset'); } catch (e) { toast(e.message, 'error'); }
        } }, 'Reset paper account')));
      return box;
    },

    ai() {
      const models = S.settings.models || {};
      const sel = (path, cur) => h('select', { class: 'inp', 'data-path': path },
        MODELS.map(([v, l]) => h('option', { value: v, selected: v === cur }, l)),
        MODELS.some(([v]) => v === cur) ? null : h('option', { value: cur, selected: true }, cur));
      const pricing = S.settings.pricing || {};
      const priceRows = Object.entries(pricing).map(([m, [pi, po]]) => {
        const a = h('input', { class: 'inp', type: 'number', step: 'any', value: pi, style: { width: '90px' } });
        const b = h('input', { class: 'inp', type: 'number', step: 'any', value: po, style: { width: '90px' } });
        return { m, a, b, tr: h('tr', {}, h('td', {}, m), h('td', {}, a), h('td', {}, b)) };
      });
      const box = h('div', { class: 'set-section' },
        h('h3', {}, 'AI models & budget'),
        h('p', { class: 'lede' }, 'A cheap model scores every fresh watchlist headline; a strong model reviews each proposed trade. Spending stops for the day at the budget.'),
        h('div', { class: 'grid2' },
          h('div', { class: 'field' }, h('label', {}, 'News triage model'), sel('models.triage', models.triage)),
          h('div', { class: 'field' }, h('label', {}, 'Trade review model'), sel('models.review', models.review)),
          numField('Daily AI budget (USD)', 'ai.daily_budget_usd'),
          numField('Minimum news score (0–10)', 'ai.min_triage_score', 'Stories below this never reach the reviewer.', '1'),
          numField('Minimum reviewer confidence (0–1)', 'ai.min_confidence', 'Trades below this are rejected.', '0.01')),
        h('div', { class: 'section-h', style: { padding: '10px 0 4px' } }, 'Prices per million tokens (USD), used for the spend estimate'),
        h('table', { class: 't', style: { maxWidth: '460px' } }, h('thead', {}, h('tr', {}, h('th', {}, 'Model'), h('th', {}, 'Input'), h('th', {}, 'Output'))),
          h('tbody', {}, priceRows.map((r) => r.tr))),
        h('p', { class: 'help cond dim', style: { margin: '6px 0 12px' } }, 'Estimates. Check anthropic.com/pricing and your invoice, and adjust.'));
      box.append(h('div', { class: 'section-h', style: { padding: '6px 0 4px' } }, 'Spend, last 30 days'),
        usageHistory());
      box.append(h('div', { style: { marginTop: '12px' } }, saveBtn(box, () => ({ pricing: Object.fromEntries(priceRows.map((r) => [r.m, [Number(r.a.value), Number(r.b.value)]])) }))));
      return box;
    },

    feeds() {
      const f = S.settings.feeds || {};
      const rss = (f.rss || []).map((x) => ({ ...x }));
      const list = h('tbody');
      const draw = () => {
        clear(list);
        rss.forEach((x, i) => list.append(h('tr', {},
          h('td', {}, h('input', { class: 'inp', value: x.name || '', placeholder: 'Name', oninput: (e) => (x.name = e.target.value) })),
          h('td', {}, h('input', { class: 'inp', value: x.url || '', placeholder: 'https://…/feed.xml', oninput: (e) => (x.url = e.target.value) })),
          h('td', { style: { width: '30px' } }, h('button', { class: 'xbtn', onclick: () => { rss.splice(i, 1); draw(); } }, '✕')))));
      };
      draw();
      const box = h('div', { class: 'set-section' },
        h('h3', {}, 'News feeds & timing'),
        h('p', { class: 'lede' }, 'Live data mode only; demo mode uses its own simulated feed and faster timers.'),
        ...[['feeds.tradernet', 'Tradernet news', 'Freedom’s own newsfeed for your tickers.'], ['feeds.finnhub', 'Finnhub company news', 'Needs a Finnhub key. US tickers only.'],
          ['feeds.sec_8k', 'SEC 8-K filings', 'Material-event filings from US-listed companies.']]
          .map(([path, label, help]) => h('label', { class: 'check' }, h('input', { type: 'checkbox', 'data-path': path, checked: !!val(path) }),
            h('span', {}, label, h('br'), h('span', { class: 'help cond' }, help)))),
        h('div', { class: 'section-h', style: { padding: '10px 0 4px' } }, 'Extra RSS feeds (company IR pages, exchange announcements)'),
        h('table', { class: 't wl-edit' }, list),
        h('button', { class: 'btn sm', style: { margin: '6px 0 14px' }, onclick: () => { rss.push({ name: '', url: '' }); draw(); } }, '+ Add feed'),
        h('div', { class: 'grid2' },
          numField('Quotes refresh (seconds)', 'intervals.quotes_sec', '', '1'),
          numField('News poll (seconds)', 'intervals.news_sec', '', '1'),
          numField('Rule scan (minutes)', 'intervals.scan_min', '', '1'),
          numField('Account sync (seconds)', 'intervals.account_sec', '', '1')));
      box.append(saveBtn(box, () => ({ feeds: { ...collect(box).feeds, rss: rss.filter((x) => x.url) } })));
      return box;
    },

    remote() {
      const link = `${location.origin}/#token=${getToken()}`;
      const box = h('div', { class: 'set-section' },
        h('h3', {}, 'Remote access & files'),
        h('p', { class: 'lede' }, 'The headless Linux version serves this same dashboard. Reach it through an SSH tunnel or a VPN; the link below includes the access token, so treat it like a password.'),
        h('div', { class: 'field' }, h('label', {}, 'Dashboard link'),
          h('div', { class: 'row' }, h('input', { class: 'inp grow', value: link, readonly: true }),
            h('button', { class: 'btn', onclick: () => navigator.clipboard.writeText(link).then(() => toast('Link copied'), () => toast('Copy failed; select the text instead', 'warn')) }, 'Copy'))),
        h('div', { class: 'grid2' },
          h('div', { class: 'field' }, h('label', {}, 'Headless listen address'), h('input', { class: 'inp', 'data-path': 'server.host', value: S.settings.server.host }),
            h('span', { class: 'help' }, '127.0.0.1 = this machine only (use an SSH tunnel).')),
          numField('Headless port', 'server.port', 'Restart the service after changing.', '1')),
        h('div', { class: 'field' }, h('label', {}, 'Data folder'), h('input', { class: 'inp', readonly: true, value: S.app.home || '' }),
          h('span', { class: 'help' }, `Settings, database and logs live here. Creating a file named STOP in it halts trading even if this window is closed.`)));
      box.append(saveBtn(box));
      return box;
    },

    about() {
      return h('div', { class: 'set-section' },
        h('h3', {}, `${S.app.name} ${S.app.version}`),
        h('p', { class: 'lede' }, 'An AI-assisted trading terminal for Freedom Broker. Rules propose, Claude reviews, a deterministic risk gate decides. Nothing here is financial advice; you are responsible for every order it sends.'),
        h('div', { class: 'note' },
          h('p', {}, 'Charts: TradingView Lightweight Charts™, Copyright © 2025 TradingView, Inc. ', h('a', { href: '#', onclick: (e) => { e.preventDefault(); emit('open-url', 'https://www.tradingview.com/'); } }, 'tradingview.com'), '. Apache License 2.0.'),
          h('p', {}, 'Fonts: IBM Plex Mono and IBM Plex Sans Condensed, SIL Open Font License 1.1.'),
          h('p', {}, 'Broker connectivity: tradernet-sdk (MIT). AI: Anthropic Claude API.')),
        h('div', { class: 'row', style: { marginTop: '10px' } },
          S.app.shell === 'desktop' ? h('button', { class: 'btn', onclick: () => emit('cmd', 'QUIT') }, 'Quit Meridian') : null));
    },
  };

  function usageHistory() {
    const hist = (S.usage || {}).history || [];
    if (!hist.length) return h('div', { class: 'help cond dim' }, 'No AI spend recorded yet.');
    const max = Math.max(...hist.map((x) => x.cost), 0.01);
    return h('div', {}, hist.slice(-30).map((x) => h('div', { class: 'gauge', style: { padding: '2px 0' } },
      h('div', { class: 'lbl' }, h('span', {}, x.day), h('b', {}, `${fmt.money(x.cost)}  ${x.calls} calls`)),
      h('div', { class: 'bar' }, h('i', { style: { width: `${(x.cost / max) * 100}%`, background: 'var(--blue)' } })))));
  }

  function render() {
    renderNav();
    clear(body);
    if (!S.settings.risk) return;
    body.append(views[section]());
  }
  on('state', render);
  on('settings', () => { if (!body.contains(document.activeElement)) render(); });
  on('cmd:settings', (s) => { if (s && views[s]) section = s; render(); });
  render();
}
