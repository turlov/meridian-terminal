"""Rule-based trade ideas. Rules only PROPOSE; Claude reviews and risk.py decides.

To add a rule: write `def my_rule(s: Snapshot, held: bool) -> Candidate | None`, add it to
RULES and to config.RULES, and give it a line in diagnose().
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .market import Snapshot

RSI_OVERSOLD = 30
RSI_OVERBOUGHT_EXIT = 78
VOL_SURGE_RATIO = 2.5
VOL_SURGE_MOVE = 0.03


@dataclass
class Candidate:
    ticker: str
    action: str        # BUY, SELL, or EITHER (news: direction left to the reviewer)
    strategy: str
    strength: float    # 0-1, rough
    evidence: str

    def to_dict(self):
        return asdict(self)


def trend_breakout(s: Snapshot, held: bool):
    """New 20-day high while the long-term trend is up."""
    if held or not (s.last > s.high20_prev and s.last > s.sma50 > s.sma200):
        return None
    return Candidate(s.ticker, "BUY", "trend_breakout",
                     min(1.0, 0.5 + (s.last / s.high20_prev - 1) * 20),
                     f"Broke 20-day high {s.high20_prev:.2f}; SMA50 {s.sma50:.2f} > "
                     f"SMA200 {s.sma200:.2f}")


def mean_reversion(s: Snapshot, held: bool):
    """Short-term oversold inside a long-term uptrend."""
    if held or not (s.rsi14 < RSI_OVERSOLD and s.last > s.sma200):
        return None
    return Candidate(s.ticker, "BUY", "mean_reversion",
                     min(1.0, (RSI_OVERSOLD - s.rsi14) / 30 + 0.4),
                     f"RSI14 {s.rsi14:.0f} (oversold) while price holds above SMA200 "
                     f"{s.sma200:.2f}")


def volume_surge(s: Snapshot, held: bool):
    """Big up day on unusually heavy volume."""
    if held or not (s.vol_ratio > VOL_SURGE_RATIO and s.ret1 > VOL_SURGE_MOVE):
        return None
    return Candidate(s.ticker, "BUY", "volume_surge", min(1.0, s.vol_ratio / 5),
                     f"Up {s.ret1 * 100:.1f}% today on {s.vol_ratio:.1f}x normal volume")


def trend_exit(s: Snapshot, held: bool):
    if not held or s.last >= s.sma50:
        return None
    return Candidate(s.ticker, "SELL", "trend_exit", 0.7,
                     f"Price {s.last:.2f} fell below SMA50 {s.sma50:.2f}: trend broken")


def overbought_exit(s: Snapshot, held: bool):
    if not held or s.rsi14 <= RSI_OVERBOUGHT_EXIT:
        return None
    return Candidate(s.ticker, "SELL", "overbought_exit", 0.5,
                     f"RSI14 {s.rsi14:.0f}: extended, take profit")


RULES = {f.__name__: f for f in
         (trend_breakout, mean_reversion, volume_surge, trend_exit, overbought_exit)}
ENTRY_RULES = ["trend_breakout", "mean_reversion", "volume_surge"]
EXIT_RULES = ["trend_exit", "overbought_exit"]

LABELS = {
    "trend_breakout": "Trend breakout",
    "mean_reversion": "Oversold bounce",
    "volume_surge": "Volume surge",
    "trend_exit": "Trend exit",
    "overbought_exit": "Overbought exit",
    "news": "News",
}


def scan(s: Snapshot, held: bool, enabled: list[str]) -> list[Candidate]:
    return [c for name in enabled if name in RULES and (c := RULES[name](s, held))]


def diagnose(s: Snapshot, held: bool, enabled: list[str]) -> list[dict]:
    """How close each rule is to firing, in plain words, for the security detail panel."""
    out = []

    def add(rule, status, note):
        out.append({"rule": rule, "label": LABELS[rule], "status": status,
                    "enabled": rule in enabled, "note": note})

    uptrend = s.last > s.sma50 > s.sma200
    gap = (s.high20_prev / s.last - 1) * 100
    if held:
        add("trend_breakout", "n/a", "Holding a position")
    elif trend_breakout(s, held):
        add("trend_breakout", "firing", f"Broke 20-day high {s.high20_prev:.2f}")
    elif not uptrend:
        add("trend_breakout", "idle", "Needs price > SMA50 > SMA200")
    else:
        add("trend_breakout", "near" if gap < 2 else "idle",
            f"Needs +{gap:.1f}% to clear 20-day high {s.high20_prev:.2f}")

    if held:
        add("mean_reversion", "n/a", "Holding a position")
    elif mean_reversion(s, held):
        add("mean_reversion", "firing", f"RSI {s.rsi14:.0f} above SMA200")
    elif s.last <= s.sma200:
        add("mean_reversion", "idle", "Price below SMA200 (no long-term uptrend)")
    else:
        add("mean_reversion", "near" if s.rsi14 < RSI_OVERSOLD + 7 else "idle",
            f"RSI {s.rsi14:.0f}, fires below {RSI_OVERSOLD}")

    if held:
        add("volume_surge", "n/a", "Holding a position")
    elif volume_surge(s, held):
        add("volume_surge", "firing", f"{s.vol_ratio:.1f}x volume, {s.ret1 * 100:+.1f}%")
    else:
        near = s.vol_ratio > VOL_SURGE_RATIO * 0.7 and s.ret1 > 0.015
        add("volume_surge", "near" if near else "idle",
            f"Volume {s.vol_ratio:.1f}x (needs {VOL_SURGE_RATIO}x), day {s.ret1 * 100:+.1f}% "
            f"(needs +{VOL_SURGE_MOVE * 100:.0f}%)")

    if not held:
        add("trend_exit", "n/a", "Only when holding")
        add("overbought_exit", "n/a", "Only when holding")
    else:
        cushion = (s.last / s.sma50 - 1) * 100
        add("trend_exit", "firing" if cushion < 0 else ("near" if cushion < 1.5 else "idle"),
            f"{cushion:+.1f}% vs SMA50 {s.sma50:.2f}")
        add("overbought_exit", "firing" if s.rsi14 > RSI_OVERBOUGHT_EXIT else
            ("near" if s.rsi14 > RSI_OVERBOUGHT_EXIT - 6 else "idle"),
            f"RSI {s.rsi14:.0f}, fires above {RSI_OVERBOUGHT_EXIT}")
    return out
