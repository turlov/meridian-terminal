// GP — price chart (TradingView Lightweight Charts): candles, volume, SMAs, trades, levels.
import { S, on, h, add, fmt, panel, get, nameOf, toast } from '../core.js';

const LWC = window.LightweightCharts;
const TFS = ['1m', '5m', '15m', '1h', '1D', '1W'];
const TF_SEC = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '1D': 86400, '1W': 604800 };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MA = [[20, '#f0c24b'], [50, '#5aa9ff'], [200, '#c77dff']];
const UP = '#2bd964', DOWN = '#ff4747';

function pref(key, fallback) {
  try { const v = localStorage.getItem(`meridian.chart.${key}`); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
}
function savePref(key, v) { try { localStorage.setItem(`meridian.chart.${key}`, JSON.stringify(v)); } catch { /* ignore */ } }

export function mountChart(grid) {
  let tf = pref('tf', '1D');
  const show = { ma: pref('ma', true), vol: pref('vol', true), lvl: pref('lvl', true), trd: pref('trd', true) };
  const tfBtns = TFS.map((t) => h('button', { class: `tbtn ${t === tf ? 'on' : ''}`, title: `Timeframe ${t}`,
    onclick: () => setTf(t) }, t));
  const toggle = (key, label, title) => h('button', { class: `tbtn ${show[key] ? 'on' : ''}`, title,
    onclick: (e) => { show[key] = !show[key]; savePref(key, show[key]); e.currentTarget.classList.toggle('on', show[key]); applyVisibility(); } }, label);
  const sep = h('span', { class: 'faint', style: { padding: '0 4px' } }, '|');
  const p = panel('chart', 'GP', 'Chart', [...tfBtns, sep,
    toggle('ma', 'MA', 'Moving averages 20 / 50 / 200'), toggle('vol', 'VOL', 'Volume'),
    toggle('lvl', 'LVL', 'Position entry, stop and target'), toggle('trd', 'TRD', 'Your trades')]);
  grid.append(p.el);

  const host = h('div', { class: 'chart-host' });
  const legend = h('div', { class: 'legend' });
  const watermark = h('div', { class: 'watermark' }, 'DEMO DATA');
  const msg = h('div', { class: 'chart-msg' }, 'Select a ticker');
  p.body.append(h('div', { class: 'chart-wrap' }, host, legend, watermark, msg));

  if (!LWC) {
    msg.textContent = 'Chart library failed to load.';
    return p;
  }
  const intraday = () => !['1D', '1W'].includes(tf);
  const chart = LWC.createChart(host, {
    autoSize: true,
    layout: { background: { type: 'solid', color: '#000000' }, textColor: '#8a93a3',
      fontFamily: '"Plex Mono", ui-monospace, monospace', fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: '#0d131c' }, horzLines: { color: '#0d131c' } },
    rightPriceScale: { borderColor: '#1b2433' },
    timeScale: { borderColor: '#1b2433', timeVisible: true, secondsVisible: false, rightOffset: 4,
      tickMarkFormatter: (t, type) => tickFmt(t, type) },
    crosshair: { mode: 0, vertLine: { color: '#3b4658', labelBackgroundColor: '#12233d' },
      horzLine: { color: '#3b4658', labelBackgroundColor: '#12233d' } },
    localization: { timeFormatter: (t) => timeFmt(t), priceFormatter: (p) => fmt.px(p) },
  });
  const candle = chart.addSeries(LWC.CandlestickSeries, { upColor: UP, downColor: DOWN, borderVisible: false,
    wickUpColor: UP, wickDownColor: DOWN, priceLineColor: '#ffa31a', priceLineWidth: 1 });
  candle.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.24 } });
  const vol = chart.addSeries(LWC.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol',
    lastValueVisible: false, priceLineVisible: false });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  const mas = MA.map(([n, color]) => chart.addSeries(LWC.LineSeries, { color, lineWidth: 1, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false, title: '' }));
  const markers = LWC.createSeriesMarkers(candle, []);
  let lines = [];
  let bars = [];
  let maMaps = MA.map(() => new Map());
  let ticker = null;
  let req = 0;
  let lastData = null;

  function tickFmt(t, type) {
    const d = new Date(t * 1000);
    if (!intraday()) {
      if (type === 0) return String(d.getUTCFullYear());
      if (type === 1) return MONTHS[d.getUTCMonth()];
      return String(d.getUTCDate());
    }
    if (type === 0) return String(d.getFullYear());
    if (type === 1) return MONTHS[d.getMonth()];
    if (type === 2) return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
  }
  function timeFmt(t) {
    const d = new Date(t * 1000);
    if (!intraday()) return `${String(d.getUTCDate()).padStart(2, '0')} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false })}`;
  }

  function setTf(t) {
    tf = t;
    savePref('tf', t);
    tfBtns.forEach((b) => b.classList.toggle('on', b.textContent === t));
    load(true);
  }

  async function load(fit = true) {
    if (!ticker) return;
    const id = ++req;
    msg.textContent = 'Loading…';
    msg.hidden = false;
    try {
      const data = await get(`/api/chart?ticker=${encodeURIComponent(ticker)}&tf=${tf}`);
      if (id !== req) return;
      setData(data, fit);
    } catch (e) {
      if (id !== req) return;
      bars = [];
      candle.setData([]); vol.setData([]); mas.forEach((m) => m.setData([]));
      msg.textContent = `No chart data: ${e.message}`;
    }
  }

  function setData(d, fit) {
    lastData = d;
    bars = d.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }));
    msg.hidden = bars.length > 0;
    if (!bars.length) msg.textContent = 'No price data for this timeframe';
    candle.setData(bars.map(({ volume, ...b }) => b));
    vol.setData(bars.map((b) => ({ time: b.time, value: b.volume,
      color: b.close >= b.open ? 'rgba(43,217,100,.32)' : 'rgba(255,71,71,.32)' })));
    maMaps = MA.map(([n], i) => {
      const map = new Map();
      const pts = [];
      let sum = 0;
      for (let k = 0; k < bars.length; k++) {
        sum += bars[k].close;
        if (k >= n) sum -= bars[k - n].close;
        if (k >= n - 1) { const v = sum / n; pts.push({ time: bars[k].time, value: v }); map.set(bars[k].time, v); }
      }
      mas[i].setData(pts);
      return map;
    });
    setMarkers(d.trades || []);
    setLevels(d.position);
    applyVisibility();
    watermark.hidden = !d.demo;
    if (fit) {
      const n = bars.length;
      const visible = intraday() ? 160 : tf === '1W' ? 156 : 180;
      if (n > visible) chart.timeScale().setVisibleLogicalRange({ from: n - visible, to: n + 3 });
      else chart.timeScale().fitContent();
    }
    renderLegend();
  }

  function barTimeFor(ts) {
    let lo = 0, hi = bars.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (bars[mid].time <= ts) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans >= 0 ? bars[ans].time : null;
  }

  function setMarkers(trades) {
    if (!show.trd) { markers.setMarkers([]); return; }
    const out = [];
    for (const t of trades) {
      const time = barTimeFor(t.ts);
      if (time === null) continue;
      out.push({ time, position: t.side === 'BUY' ? 'belowBar' : 'aboveBar', color: t.side === 'BUY' ? UP : DOWN,
        shape: t.side === 'BUY' ? 'arrowUp' : 'arrowDown', text: `${t.side === 'BUY' ? 'B' : 'S'} ${fmt.num(t.qty, 0)} @ ${fmt.px(t.price)}` });
    }
    out.sort((a, b) => a.time - b.time);
    markers.setMarkers(out);
  }

  function setLevels(pos) {
    lines.forEach((l) => candle.removePriceLine(l));
    lines = [];
    if (!pos || !show.lvl) return;
    const add = (price, color, title, style = 2) => { if (price) lines.push(candle.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title })); };
    add(pos.entry, '#ffa31a', 'Entry', 0);
    add(pos.stop, DOWN, 'Stop');
    add(pos.target, UP, 'Target');
  }

  function applyVisibility() {
    mas.forEach((m) => m.applyOptions({ visible: show.ma }));
    vol.applyOptions({ visible: show.vol });
    if (lastData) { setMarkers(lastData.trades || []); setLevels(lastData.position); }
  }

  function renderLegend(param) {
    let b = null;
    if (param && param.time !== undefined) {
      const c = param.seriesData.get(candle);
      if (c) b = { ...c, time: param.time };
    }
    if (!b && bars.length) b = bars[bars.length - 1];
    legend.replaceChildren();
    legend.append(h('span', { class: 'tkr' }, ticker || ''), h('span', {}, tf));
    if (!b) return;
    const idx = bars.findIndex((x) => x.time === b.time);
    const prev = idx > 0 ? bars[idx - 1].close : null;
    const chg = prev ? (b.close / prev - 1) * 100 : null;
    add(legend,
      h('span', {}, 'O ', h('b', {}, fmt.px(b.open))), h('span', {}, 'H ', h('b', {}, fmt.px(b.high))),
      h('span', {}, 'L ', h('b', {}, fmt.px(b.low))), h('span', {}, 'C ', h('b', { class: fmt.cls(chg) }, fmt.px(b.close))),
      chg !== null ? h('span', { class: fmt.cls(chg) }, fmt.pct(chg)) : null);
    if (show.ma) {
      MA.forEach(([n], i) => {
        const v = maMaps[i].get(b.time);
        if (v !== undefined) legend.append(h('span', { class: `ma${n}` }, `MA${n} ${fmt.px(v)}`));
      });
    }
  }
  chart.subscribeCrosshairMove(renderLegend);

  function liveTick(q) {
    if (!bars.length || !q || !q.last) return;
    const px = q.last;
    const last = bars[bars.length - 1];
    if (intraday()) {
      const sec = TF_SEC[tf];
      const bucket = Math.floor(Date.now() / 1000 / sec) * sec;
      if (bucket > last.time) {
        const nb = { time: bucket, open: last.close, high: Math.max(last.close, px), low: Math.min(last.close, px), close: px, volume: 0 };
        bars.push(nb);
        candle.update({ time: nb.time, open: nb.open, high: nb.high, low: nb.low, close: nb.close });
        return;
      }
    }
    last.close = px;
    last.high = Math.max(last.high, px);
    last.low = Math.min(last.low, px);
    try { candle.update({ time: last.time, open: last.open, high: last.high, low: last.low, close: last.close }); } catch { /* out-of-order */ }
  }

  on('select', (t) => {
    ticker = t;
    p.titleEl.textContent = t;
    p.sub.textContent = nameOf(t);
    load(true);
  });
  on('quotes', (q) => { if (ticker && q[ticker]) { liveTick(q[ticker]); renderLegend(); } });
  on('trade', (t) => { if (t.ticker === ticker) load(false); });
  on('positions', () => {
    if (!lastData || !ticker) return;
    lastData.position = (S.positions || []).find((x) => x.ticker === ticker) || null;
    setLevels(lastData.position);
  });
  on('app', () => { if (lastData) watermark.hidden = !S.app.demo; });
  setInterval(() => { if (ticker && intraday() && !document.hidden) load(false); }, 120000);
  on('cmd:tf', (t) => { if (TFS.includes(t)) setTf(t); else toast(`Timeframes: ${TFS.join(' ')}`, 'warn'); });
  return p;
}
