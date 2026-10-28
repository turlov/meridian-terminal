// F1 — help: commands, keys, panels, safety.
import { S, h } from '../core.js';

export const COMMANDS = [
  ['NVDA  or  NVDA.US', 'Show a ticker (chart, detail, news filter)'],
  ['BUY NVDA 5 @ 182.40', 'Open the order ticket; quantity and price optional'],
  ['SELL NVDA', 'Open a sell ticket for your holding'],
  ['CLOSE NVDA', 'Close a position'],
  ['ADD MSFT.US', 'Add a ticker to the watchlist'],
  ['DEL MSFT.US', 'Remove a ticker from the watchlist'],
  ['BT NVDA AAPL', 'Backtest the rules on one or more tickers'],
  ['TF 15m', 'Chart timeframe: 1m 5m 15m 1h 1D 1W'],
  ['NEWS NVDA', 'Show headlines for a ticker'],
  ['SCAN', 'Run the rule scan now'],
  ['POLL', 'Poll all news sources now'],
  ['AI ON  /  AI OFF', 'Turn Claude review on or off'],
  ['MODE OFF / PAPER / LIVE', 'Where orders go: nowhere, paper, or Freedom Broker'],
  ['HALT', 'Kill switch: stop new orders, cancel working ones'],
  ['RESUME', 'Allow trading again'],
  ['KEYS', 'Add or change API keys'],
  ['SET', 'Settings'],
  ['QUIT', 'Close the app (desktop)'],
];

export const KEYS = [
  ['F1', 'Help'], ['F2', 'Monitor (all panels)'], ['F3', 'News, full screen'], ['F4', 'AI desk, full screen'],
  ['F5', 'Portfolio, full screen'], ['F6', 'Backtest'], ['F7', 'Chart, full screen'], ['F8', 'Settings'], ['F9', 'Order ticket'],
  ['/  or  Ctrl+K', 'Jump to the command line (or just start typing)'], ['↑ ↓', 'Move through the watchlist'],
  ['Esc', 'Close a dialog or restore a full-screen panel'], ['Double-click a title bar', 'Full-screen that panel'],
];

const PANELS = [
  ['WL Monitor', 'Watchlist prices, day range, RSI, trend, firing rules (BRK breakout, OVS oversold, VOL volume, XTR/XOB exits) and your holdings. Double-click a row to trade.'],
  ['GP Chart', 'Candles with volume, 20/50/200 moving averages, your fills, and the entry/stop/target of an open position.'],
  ['DES Security', 'Key statistics, how close each rule is to firing, a risk-sized trade plan, recent AI verdicts and headlines.'],
  ['TOP News', 'Every headline with Claude’s materiality score (0–10). Amber scores reached the reviewer.'],
  ['AI AI desk', 'Every trade idea, Claude’s call and confidence, and what the risk gate did. Click a row for the full reasoning.'],
  ['PORT Portfolio', 'Positions with live P&L, orders, and fills for the active account.'],
  ['ACCT Account & risk', 'Equity, day P&L against your loss limit, AI spend, execution mode, and the kill switch.'],
  ['SYS System', 'Health of every feed and the event log.'],
];

export function mountHelp(root) {
  const table = (rows) => h('table', { class: 't' }, h('tbody', {}, rows.map(([a, b]) => h('tr', {}, h('td', {}, a), h('td', { class: 'cond' }, b)))));
  root.append(h('div', { style: { height: '100%', overflow: 'auto' } },
    h('div', { class: 'page-h' }, h('span', { class: 'fn' }, 'HELP'), h('h2', {}, 'How to use Meridian')),
    h('div', { class: 'page-body help-grid' },
      h('div', {}, h('h3', {}, 'Commands'), table(COMMANDS)),
      h('div', {}, h('h3', {}, 'Keys'), table(KEYS),
        h('h3', { style: { marginTop: '18px' } }, 'How a trade happens'),
        h('div', { class: 'note' },
          h('p', {}, '1. A rule fires on the price scan, or a fresh headline about a watchlist stock scores high enough.'),
          h('p', {}, '2. Claude reviews the idea with the chart numbers, recent headlines and your position. It can confirm or say hold, never reverse the idea.'),
          h('p', {}, '3. The risk gate (plain code) checks confidence, position limits, daily loss, cooldown and the kill switch, then sizes the order from your risk per trade.'),
          h('p', {}, '4. A limit order goes to the active account. Stops and targets are attached after the fill.'))),
      h('div', {}, h('h3', {}, 'Panels'), table(PANELS)),
      h('div', {}, h('h3', {}, 'Safety'),
        h('div', { class: 'note' },
          h('p', {}, 'Orders go to the paper account until you choose Live and type LIVE to confirm. Demo data can never trade live.'),
          h('p', {}, 'Kill switch: type HALT, press the button in the Account panel, run ', h('code', {}, 'meridian halt'), ` in a terminal, or create a file named STOP in ${S.app.home || 'the data folder'}.`),
          h('p', {}, 'Headlines are treated as untrusted text; Claude is told to ignore instructions inside them, and the risk gate rejects tickers a story does not mention.'),
          h('p', {}, 'Margin and short selling are always off. Every order is a day limit order.'))))));
}
