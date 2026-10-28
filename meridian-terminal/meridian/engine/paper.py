"""Paper trading: orders fill against live (or demo) quotes, stops/targets simulated,
cash and P&L tracked in the local database."""
from __future__ import annotations

import logging
import threading
import time

from .store import Store

log = logging.getLogger(__name__)

ORDER_TTL = 24 * 3600  # working paper orders expire after a day


class PaperBroker:
    def __init__(self, store: Store, starting_cash: float, mode: str = "paper"):
        self.mode = mode          # 'demo' (simulated prices) or 'paper' (real prices)
        self.store = store
        self.store.paper_account(mode, starting_cash)
        self._lock = threading.RLock()  # quotes thread and decision thread both match orders

    # ---- orders -------------------------------------------------------------------
    def place(self, ticker, side, qty, limit, source, stop=None, target=None,
              quote: dict | None = None, note: str = "") -> tuple[dict, list[dict]]:
        """Returns (order row, fills)."""
        with self._lock:
            return self._place(ticker, side, qty, limit, source, stop, target, quote, note)

    def _place(self, ticker, side, qty, limit, source, stop, target, quote, note):
        acct = self.store.paper_account(self.mode)
        if side == "BUY" and qty * limit > acct["cash"] + 1e-6:
            oid = self.store.add_order({"ticker": ticker, "side": side, "qty": qty, "limit": limit,
                                        "status": "rejected", "source": source, "mode": self.mode,
                                        "note": "insufficient paper cash"})
            return self.store.order(oid), []
        if side == "SELL":
            held = self.store.book(self.mode).get(ticker, {}).get("qty", 0)
            if qty > held + 1e-9:
                oid = self.store.add_order({"ticker": ticker, "side": side, "qty": qty,
                                            "limit": limit, "status": "rejected", "source": source,
                                            "mode": self.mode, "note": "no position to sell"})
                return self.store.order(oid), []
        oid = self.store.add_order({"ticker": ticker, "side": side, "qty": qty, "limit": limit,
                                    "status": "working", "source": source, "stop": stop,
                                    "target": target, "mode": self.mode, "note": note})
        fills = self._match({ticker: quote}) if quote else []
        return self.store.order(oid), fills

    def cancel(self, order_id: int) -> bool:
        with self._lock:
            return self._cancel(order_id)

    def _cancel(self, order_id: int) -> bool:
        o = self.store.order(order_id)
        if not o or o["status"] != "working" or o["mode"] != self.mode:
            return False
        self.store.update_order(order_id, status="cancelled")
        return True

    def cancel_all(self) -> int:
        n = 0
        for o in self.store.working_orders(self.mode):
            n += self.cancel(o["id"])
        return n

    # ---- matching ---------------------------------------------------------------------
    def on_quotes(self, quotes: dict[str, dict]) -> list[dict]:
        """Fill working orders and trigger stops/targets. Returns new trade rows."""
        with self._lock:
            return self._match(quotes)

    def _match(self, quotes: dict[str, dict]) -> list[dict]:
        fills = []
        now = time.time()
        for o in self.store.working_orders(self.mode):
            q = quotes.get(o["ticker"])
            if not q:
                continue
            if now - o["ts"] > ORDER_TTL:
                self.store.update_order(o["id"], status="expired")
                continue
            ask = q.get("ask") or q.get("last")
            bid = q.get("bid") or q.get("last")
            if o["side"] == "BUY" and ask and ask <= o["limit_price"]:
                fills.append(self._fill(o, min(ask, o["limit_price"])))
            elif o["side"] == "SELL" and bid and bid >= o["limit_price"]:
                fills.append(self._fill(o, max(bid, o["limit_price"])))
        for ticker, pos in self.store.book(self.mode).items():
            q = quotes.get(ticker)
            if not q or not q.get("last"):
                continue
            px = q["last"]
            exit_ = None
            if pos["stop"] and px <= pos["stop"]:
                exit_ = ("stop", px)          # fill at market (can gap through the stop)
            elif pos["target"] and px >= pos["target"]:
                exit_ = ("target", pos["target"])
            if exit_:
                for w in self.store.working_orders(self.mode):
                    if w["ticker"] == ticker and w["side"] == "SELL":
                        self.store.update_order(w["id"], status="cancelled")
                pnl = self.store.book_reduce(ticker, self.mode, pos["qty"], exit_[1])
                self.store.paper_cash_add(self.mode, pos["qty"] * exit_[1])
                fills.append(self.store.add_trade(ticker, "SELL", pos["qty"], exit_[1], self.mode,
                                                  exit_[0], "", pnl))
        return fills

    def _fill(self, o: dict, price: float) -> dict:
        price = round(price, 4)
        self.store.update_order(o["id"], status="filled", filled_price=price,
                                filled_ts=time.time())
        if o["side"] == "BUY":
            self.store.paper_cash_add(self.mode, -o["qty"] * price)
            self.store.book_add(o["ticker"], self.mode, o["qty"], price, o["stop"], o["target"])
            pnl = 0.0
        else:
            pnl = self.store.book_reduce(o["ticker"], self.mode, o["qty"], price)
            self.store.paper_cash_add(self.mode, o["qty"] * price)
        return self.store.add_trade(o["ticker"], o["side"], o["qty"], price, self.mode,
                                    o["source"], o["id"], pnl)

    # ---- account ----------------------------------------------------------------------
    def positions(self) -> dict[str, float]:
        return {t: p["qty"] for t, p in self.store.book(self.mode).items()}

    def account(self, quotes: dict[str, dict]) -> dict:
        acct = self.store.paper_account(self.mode)
        book = self.store.book(self.mode)
        invested = unreal = 0.0
        for t, p in book.items():
            px = (quotes.get(t) or {}).get("last") or p["entry"]
            invested += p["qty"] * px
            unreal += (px - p["entry"]) * p["qty"]
        realized = self.store.realized_today(self.mode)
        return {"cash_total": acct["cash"], "invested": invested, "equity": acct["cash"] + invested,
                "unrealized": unreal, "realized_today": realized, "day_pnl": realized + unreal,
                "starting_cash": acct["starting_cash"],
                "total_return": (acct["cash"] + invested) / acct["starting_cash"] - 1}
