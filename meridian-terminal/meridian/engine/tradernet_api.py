"""Freedom Broker / Tradernet: market data, account sync and live orders (tradernet-sdk).

Response shapes are parsed defensively. If something shows up empty in the UI, open
Settings > Accounts > "Show raw response" and adjust the _norm_* helpers below.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

import numpy as np

from .market import TIMEFRAMES, Candles, resample

log = logging.getLogger(__name__)

# how much history to request per timeframe
LOOKBACK_DAYS = {"1m": 3, "5m": 10, "15m": 30, "1h": 90, "1D": 1900, "1W": 3650}


def _num(*vals, default=0.0) -> float:
    for v in vals:
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


def _find_list(res, keys=("result", "q", "quotes", "news", "found", "data", "items", "orders",
                          "order", "pos")) -> list:
    """Find the first list of dicts inside a nested response."""
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        for k in keys:
            if k in res:
                found = _find_list(res[k], keys)
                if found:
                    return found
    return []


def norm_quote(q: dict) -> dict:
    last = _num(q.get("ltp"), q.get("last"), q.get("bap"), q.get("bbp"))
    prev = _num(q.get("pp"), q.get("prev_close"), q.get("close"))
    chg = _num(q.get("chg"), default=(last - prev) if prev else 0.0)
    pct = _num(q.get("pcp"), default=(chg / prev * 100) if prev else 0.0)
    return {
        "ticker": q.get("c") or q.get("ticker") or q.get("i"),
        "name": q.get("name") or q.get("name2") or "",
        "last": last, "bid": _num(q.get("bbp")), "ask": _num(q.get("bap")),
        "open": _num(q.get("op")), "high": _num(q.get("maxtp")), "low": _num(q.get("mintp")),
        "prev_close": prev, "chg": chg, "chg_pct": pct, "volume": _num(q.get("vol")),
        "currency": q.get("x_curr") or q.get("curr") or "", "ts": time.time(),
    }


class TradernetData:
    """Read access + order placement, serialized behind one lock (requests.Session)."""

    def __init__(self, public: str, private: str):
        from tradernet import Tradernet
        self.tn = Tradernet(public, private)
        self.tn.timeout = 20
        self._lock = threading.Lock()
        self.last_raw: dict = {}

    def call(self, name: str, fn, *a, **kw):
        with self._lock:
            res = fn(*a, **kw)
        self.last_raw[name] = res
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"Tradernet {name}: {res.get('error')}")
        if isinstance(res, dict) and res.get("errMsg"):
            raise RuntimeError(f"Tradernet {name}: {res.get('errMsg')}")
        return res

    # ---- market data -----------------------------------------------------------
    def quotes(self, tickers: list[str]) -> dict[str, dict]:
        if not tickers:
            return {}
        res = self.call("quotes", self.tn.get_quotes, list(tickers))
        out = {}
        for q in _find_list(res):
            if isinstance(q, dict):
                nq = norm_quote(q)
                if nq["ticker"]:
                    out[nq["ticker"]] = nq
        return out

    def candles(self, ticker: str, tf: str = "1D", days: int | None = None) -> Candles:
        base_tf = "1D" if tf == "1W" else tf
        seconds = TIMEFRAMES[base_tf]
        lookback = days or LOOKBACK_DAYS[tf]
        res = self.call("candles", self.tn.get_candles, ticker,
                        start=datetime.now() - timedelta(days=lookback),
                        end=datetime.now() + timedelta(days=1), timeframe=seconds)
        if not isinstance(res, dict) or "hloc" not in res:
            return Candles.empty()
        hloc = np.array(res["hloc"].get(ticker) or [], dtype=float)
        if hloc.size == 0:
            return Candles.empty()
        # Same +3h adjustment the SDK applies (server timestamps are Moscow time).
        t = np.array(res["xSeries"][ticker], dtype=np.int64) + 3 * 3600
        v = np.array(res.get("vl", {}).get(ticker) or [0] * len(t), dtype=float)
        c = Candles(t, hloc[:, 2], hloc[:, 0], hloc[:, 1], hloc[:, 3], v)
        if tf == "1W":
            c = resample(c, TIMEFRAMES["1W"], anchor_monday=True)
        return c

    def search(self, query: str) -> list[dict]:
        res = self.call("search", self.tn.find_symbol, query)
        out = []
        for r in _find_list(res, ("found", "result", "data")):
            if not isinstance(r, dict):
                continue
            t = r.get("t") or r.get("ticker") or r.get("c")
            if t:
                out.append({"ticker": t, "name": r.get("nm") or r.get("n") or r.get("name", ""),
                            "exchange": r.get("x") or r.get("mkt") or r.get("exchange", "")})
        return out[:20]

    def news(self, ticker: str, limit: int = 10) -> list[dict]:
        res = self.call("news", self.tn.get_news, query=ticker, symbol=ticker, limit=limit)
        return [n for n in _find_list(res, ("result", "news", "data", "items")) if isinstance(n, dict)]

    def test(self) -> str:
        res = self.call("user_info", self.tn.user_info)
        info = res.get("result", res) if isinstance(res, dict) else {}
        name = ""
        if isinstance(info, dict):
            name = info.get("login") or info.get("email") or info.get("client_id") or ""
        return f"Connected to Tradernet{' as ' + str(name) if name else ''}"

    # ---- account -----------------------------------------------------------------
    def account(self) -> dict:
        res = self.call("positions", self.tn.account_summary)
        ps = (res.get("result", {}) or {}).get("ps", {}) if isinstance(res, dict) else {}
        positions = []
        for p in ps.get("pos", []) or []:
            qty = _num(p.get("q"))
            if not qty:
                continue
            last = _num(p.get("mkt_price"), p.get("ltp"))
            avg = _num(p.get("bal_price_a"), p.get("price_a"), p.get("open_bal"))
            rate = _num(p.get("currval"), default=1.0) or 1.0
            positions.append({
                "ticker": p.get("i"), "name": p.get("name", ""), "qty": qty, "avg_price": avg,
                "last": last, "market_value": _num(p.get("market_value"), default=qty * last),
                "pnl": _num(p.get("profit_close"), p.get("profit_price"),
                            default=(last - avg) * qty),
                "currency": p.get("curr", ""), "rate": rate,
            })
        cash = []
        for a in ps.get("acc", []) or []:
            cash.append({"currency": a.get("curr", ""), "amount": _num(a.get("s")),
                         "rate": _num(a.get("currval"), default=1.0) or 1.0})
        cash_usd = sum(c["amount"] * c["rate"] for c in cash)
        invested = sum(p["market_value"] * p["rate"] for p in positions)
        return {"positions": positions, "cash": cash, "cash_total": cash_usd,
                "invested": invested, "equity": cash_usd + invested,
                "unrealized": sum(p["pnl"] * p["rate"] for p in positions)}

    def open_orders(self) -> list[dict]:
        res = self.call("orders", self.tn.get_placed, True)
        out = []
        for o in _find_list(res, ("result", "orders", "order")):
            if not isinstance(o, dict):
                continue
            oper = int(_num(o.get("oper"), default=0))
            out.append({
                "id": o.get("id") or o.get("order_id"), "ticker": o.get("instr") or o.get("i"),
                "side": "BUY" if oper in (1, 2) else "SELL" if oper in (3, 4) else str(oper),
                "qty": _num(o.get("q"), o.get("qty")), "limit": _num(o.get("p"), o.get("price")),
                "status": o.get("stat_d") or f"status {o.get('stat', '?')}",
                "ts": o.get("date") or "", "mode": "live",
            })
        return out

    # ---- orders --------------------------------------------------------------------
    def place(self, ticker: str, side: str, qty: int, limit: float) -> dict:
        fn = self.tn.buy if side == "BUY" else self.tn.sell
        # Limit order, day duration, never on margin.
        return self.call("place", fn, ticker, quantity=int(qty), price=float(limit),
                         duration="day", use_margin=False)

    def cancel(self, order_id) -> dict:
        return self.call("cancel", self.tn.cancel, int(order_id))

    def cancel_all(self):
        return self.call("cancel_all", self.tn.cancel_all)

    def protect(self, ticker: str, stop: float | None, target: float | None):
        if stop:
            self.call("stop", self.tn.stop, ticker, float(stop))
        if target:
            self.call("take_profit", self.tn.take_profit, ticker, float(target))
