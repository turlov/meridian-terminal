"""Backtest the RULE strategies on daily candles. No Claude calls.

Claude's training data covers past prices and news, so any backtest of its judgement on
historical dates would be contaminated. Rules have no such leak; the reviewer's value is
measured by paper trading instead.

Model: signal at a day's close -> enter at next open -> exit on stop/target during a day
(stop checked first, gaps fill at the open) or on an exit-rule signal at the next open.
Every trade uses 100% of equity; cost is charged per side.
"""
from __future__ import annotations

import numpy as np

from .market import MIN_BARS, Candles, snapshot
from .strategies import ENTRY_RULES, EXIT_RULES, RULES


def run_rule(ticker: str, d: Candles, snaps: dict, entry_rule: str, risk: dict,
             cost: float) -> dict:
    trades, equity_curve = [], []
    equity, pos, pending = 1.0, None, None
    days_in = 0
    for i in range(MIN_BARS, len(d)):
        o, h, l, c = d.o[i], d.h[i], d.l[i], d.c[i]
        if pending == "BUY" and pos is None:
            s = snaps[i - 1]
            pos = {"entry": o, "t_in": int(d.t[i]),
                   "stop": o - risk["atr_stop_mult"] * s.atr14,
                   "target": o + risk["atr_target_mult"] * s.atr14}
        elif pending == "SELL" and pos:
            equity = _close(trades, pos, o, int(d.t[i]), "signal", cost, equity)
            pos = None
        pending = None

        if pos:
            days_in += 1
            exit_px, why = None, ""
            if l <= pos["stop"]:
                exit_px, why = min(o, pos["stop"]), "stop"
            elif h >= pos["target"]:
                exit_px, why = max(o, pos["target"]), "target"
            if exit_px is not None:
                equity = _close(trades, pos, exit_px, int(d.t[i]), why, cost, equity)
                pos = None

        mark = equity * (c / pos["entry"] if pos else 1.0)
        equity_curve.append({"time": int(d.t[i]), "value": round(mark, 5)})
        s = snaps[i]
        if pos is None:
            if RULES[entry_rule](s, False):
                pending = "BUY"
        elif any(RULES[x](s, True) for x in EXIT_RULES):
            pending = "SELL"

    if pos:  # mark the open trade at the last close
        equity = _close(trades, pos, d.c[-1], int(d.t[-1]), "open", cost, equity)
    n = max(len(d) - MIN_BARS, 1)
    rets = np.array([t["ret"] for t in trades]) if trades else np.array([])
    curve = np.array([p["value"] for p in equity_curve]) if equity_curve else np.array([1.0])
    return {
        "rule": entry_rule, "trades": len(trades),
        "win_rate": float((rets > 0).mean()) if len(rets) else 0.0,
        "avg_trade": float(rets.mean()) if len(rets) else 0.0,
        "total": float(equity - 1),
        "max_dd": float((curve / np.maximum.accumulate(curve) - 1).min()),
        "exposure": days_in / n,
        "curve": equity_curve, "trade_list": trades,
    }


def _close(trades, pos, px, t_out, why, cost, equity) -> float:
    ret = px / pos["entry"] - 1 - 2 * cost
    trades.append({"t_in": pos["t_in"], "t_out": t_out, "entry": round(float(pos["entry"]), 4),
                   "exit": round(float(px), 4), "ret": float(ret), "why": why})
    return equity * (1 + ret)


def run(ticker: str, d: Candles, rules: list[str] | None, risk: dict, cost: float) -> dict:
    if len(d) <= MIN_BARS + 20:
        return {"ticker": ticker, "error": f"Not enough history ({len(d)} daily bars, need "
                                           f"{MIN_BARS + 21}+)"}
    rules = [r for r in (rules or ENTRY_RULES) if r in ENTRY_RULES]
    # one snapshot per bar, shared by every rule
    snaps = {i: snapshot(ticker, d.upto(i)) for i in range(MIN_BARS - 1, len(d))}
    start = d.c[MIN_BARS]
    bh_curve = [{"time": int(d.t[i]), "value": round(float(d.c[i] / start), 5)}
                for i in range(MIN_BARS, len(d))]
    bh = np.array([p["value"] for p in bh_curve])
    return {
        "ticker": ticker, "bars": len(d) - MIN_BARS,
        "from": int(d.t[MIN_BARS]), "to": int(d.t[-1]),
        "buy_hold": {"total": float(d.c[-1] / start - 1),
                     "max_dd": float((bh / np.maximum.accumulate(bh) - 1).min()),
                     "curve": bh_curve},
        "results": [run_rule(ticker, d, snaps, r, risk, cost) for r in rules],
    }
