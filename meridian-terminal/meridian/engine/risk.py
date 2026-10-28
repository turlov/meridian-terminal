"""Deterministic risk gate. Every automatic order passes through here. No AI in this file."""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

from .market import Snapshot
from .strategies import Candidate


@dataclass
class Order:
    ticker: str
    side: str
    qty: int
    limit: float
    stop: float | None = None
    target: float | None = None

    def to_dict(self):
        return asdict(self)


def size_entry(price: float, atr: float, risk: dict) -> tuple[int, float, float]:
    """Shares, stop and target for a new long so that the stop loses ~risk_per_trade_usd."""
    stop_dist = risk["atr_stop_mult"] * atr
    if price <= 0 or stop_dist <= 0:
        return 0, 0.0, 0.0
    qty = math.floor(min(risk["max_usd_per_trade"] / price, risk["risk_per_trade_usd"] / stop_dist))
    return max(qty, 0), round(price - stop_dist, 2), round(price + risk["atr_target_mult"] * atr, 2)


def check(sig, cands: list[Candidate], snap: Snapshot, positions: dict[str, float], *,
          risk: dict, min_confidence: float, watchlist: list[str], day_pnl: float,
          last_trade_ts: float | None, halted: bool, mentioned: tuple = ()) -> tuple[Order | None, str]:
    """Returns (order or None, plain-English reason)."""
    t, price = sig.ticker, snap.last
    if halted:
        return None, "trading halted (kill switch)"
    if sig.action == "HOLD":
        return None, "reviewer said hold"
    if t not in watchlist:
        return None, f"{t} is not on the watchlist"
    proposed = {c.action for c in cands}
    if sig.action not in proposed and "EITHER" not in proposed:
        return None, f"reviewer chose {sig.action} but rules proposed {'/'.join(sorted(proposed))}"
    if mentioned and t not in mentioned:
        return None, "ticker not mentioned in the triggering story"
    if sig.confidence < min_confidence:
        return None, f"confidence {sig.confidence:.2f} below {min_confidence:.2f}"
    if price <= 0 or snap.atr14 <= 0:
        return None, "no valid price or ATR"
    if day_pnl <= -risk["max_daily_loss_usd"]:
        return None, f"daily loss limit reached ({day_pnl:,.2f})"
    if last_trade_ts and time.time() - last_trade_ts < risk["ticker_cooldown_min"] * 60:
        return None, f"{t} traded less than {risk['ticker_cooldown_min']} min ago"

    held = positions.get(t, 0)
    slip = risk["max_slippage_pct"] / 100
    if sig.action == "BUY":
        if held > 0:
            return None, "already holding"
        if sum(1 for q in positions.values() if q > 0) >= risk["max_open_positions"]:
            return None, f"max open positions ({risk['max_open_positions']}) reached"
        qty, stop, target = size_entry(price, snap.atr14, risk)
        if qty < 1:
            return None, "position size below one share at current risk limits"
        return Order(t, "BUY", qty, round(price * (1 + slip), 2), stop, target), "approved"
    if held > 0:
        return Order(t, "SELL", int(held), round(price * (1 - slip), 2)), "approved"
    return None, "nothing to sell (short selling is disabled)"


def check_manual(ticker, side, qty, limit, last, positions, *, risk: dict, halted: bool) -> str | None:
    """Sanity checks for orders typed in by the user. Returns an error message or None."""
    if halted:
        return "Trading is halted. Resume trading before placing orders."
    if qty <= 0 or qty != int(qty):
        return "Quantity must be a whole number above zero."
    if limit <= 0:
        return "Limit price must be above zero."
    if qty * limit > risk["manual_max_usd"]:
        return (f"Order value {qty * limit:,.2f} exceeds the manual order limit "
                f"{risk['manual_max_usd']:,.0f} (change it in Settings > Risk).")
    if last and abs(limit / last - 1) > 0.10:
        return f"Limit {limit} is more than 10% away from the last price {last}."
    if side == "SELL" and positions.get(ticker, 0) < qty:
        return "You can only sell shares you hold (short selling is disabled)."
    return None
