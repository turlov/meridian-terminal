"""Candles, indicators and the technical snapshot. Pure numpy, no AI."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

MIN_BARS = 210  # SMA200 plus slack

TIMEFRAMES = {  # name -> seconds per bar
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1D": 86400, "1W": 604800,
}


@dataclass
class Candles:
    t: np.ndarray   # epoch seconds (bar open), int64
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    def __len__(self):
        return len(self.c)

    def tail(self, n: int) -> "Candles":
        return Candles(self.t[-n:], self.o[-n:], self.h[-n:], self.l[-n:], self.c[-n:], self.v[-n:])

    def upto(self, i: int) -> "Candles":
        """Bars [0, i] inclusive."""
        return Candles(self.t[:i + 1], self.o[:i + 1], self.h[:i + 1], self.l[:i + 1],
                       self.c[:i + 1], self.v[:i + 1])

    def to_rows(self) -> list[dict]:
        return [{"time": int(t), "open": round(float(o), 4), "high": round(float(h), 4),
                 "low": round(float(l), 4), "close": round(float(c), 4), "volume": float(v)}
                for t, o, h, l, c, v in zip(self.t, self.o, self.h, self.l, self.c, self.v)]

    @staticmethod
    def empty() -> "Candles":
        z = np.array([], dtype=float)
        return Candles(np.array([], dtype=np.int64), z, z, z, z, z)


def resample(c: Candles, seconds: int, anchor_monday: bool = False) -> Candles:
    """Aggregate bars into larger buckets (e.g. 1m -> 15m, 1D -> 1W)."""
    if len(c) == 0:
        return c
    offset = 345600 if anchor_monday else 0   # epoch day 0 was a Thursday; +4 days = Monday
    keys = (c.t - offset) // seconds
    out = {k: [] for k in ("t", "o", "h", "l", "c", "v")}
    start = 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[start]:
            out["t"].append(int(keys[start] * seconds + offset))
            out["o"].append(c.o[start])
            out["h"].append(c.h[start:i].max())
            out["l"].append(c.l[start:i].min())
            out["c"].append(c.c[i - 1])
            out["v"].append(c.v[start:i].sum())
            start = i
    return Candles(np.array(out["t"], dtype=np.int64), *(np.array(out[k], dtype=float)
                                                          for k in ("o", "h", "l", "c", "v")))


@dataclass
class Snapshot:
    ticker: str
    last: float
    prev_close: float
    ret1: float
    ret5: float
    ret20: float
    sma20: float
    sma50: float
    sma200: float
    rsi14: float
    atr14: float
    vol_ratio: float
    high20_prev: float
    low20_prev: float
    high252: float
    low252: float
    bars: int

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        p = lambda x: f"{x * 100:+.1f}%"
        return (
            f"Last {self.last:.2f} | 1d {p(self.ret1)} 5d {p(self.ret5)} 20d {p(self.ret20)}\n"
            f"SMA20 {self.sma20:.2f} SMA50 {self.sma50:.2f} SMA200 {self.sma200:.2f}\n"
            f"RSI14 {self.rsi14:.1f} | ATR14 {self.atr14:.2f} "
            f"({self.atr14 / self.last * 100:.1f}% of price)\n"
            f"Volume vs 20d avg: {self.vol_ratio:.1f}x\n"
            f"20d range (excl. today) {self.low20_prev:.2f}-{self.high20_prev:.2f} | "
            f"52w range {self.low252:.2f}-{self.high252:.2f}"
        )


def snapshot(ticker: str, d: Candles, last: float | None = None) -> Snapshot | None:
    """Daily candles (oldest first; last bar may be today's partial bar) -> Snapshot."""
    if len(d) < MIN_BARS:
        return None
    o, h, l, c, v = d.o, d.h, d.l, d.c, d.v
    last = float(last) if last else float(c[-1])
    # Use the live price for today's bar so indicators reflect the current session.
    c = c.copy()
    c[-1] = last
    avg_vol = v[-21:-1].mean()
    return Snapshot(
        ticker=ticker, last=last, prev_close=float(c[-2]),
        ret1=last / c[-2] - 1, ret5=last / c[-6] - 1, ret20=last / c[-21] - 1,
        sma20=float(c[-20:].mean()), sma50=float(c[-50:].mean()), sma200=float(c[-200:].mean()),
        rsi14=rsi(c[-300:]), atr14=atr(h[-300:], l[-300:], c[-300:]),
        vol_ratio=float(v[-1] / avg_vol) if avg_vol > 0 else 0.0,
        high20_prev=float(h[-21:-1].max()), low20_prev=float(l[-21:-1].min()),
        high252=float(max(h[-252:].max(), last)), low252=float(min(l[-252:].min(), last)),
        bars=len(d),
    )


# ---- Wilder-smoothed indicators -------------------------------------------------
def _wilder(x: np.ndarray, n: int) -> float:
    if len(x) < n:
        return float(x.mean()) if len(x) else 0.0
    avg = x[:n].mean()
    for val in x[n:]:
        avg = (avg * (n - 1) + val) / n
    return float(avg)


def rsi(c: np.ndarray, n: int = 14) -> float:
    d = np.diff(c)
    up, dn = _wilder(np.clip(d, 0, None), n), _wilder(np.clip(-d, 0, None), n)
    if dn == 0:
        return 100.0 if up > 0 else 50.0
    return 100 - 100 / (1 + up / dn)


def atr(h, l, c, n: int = 14) -> float:
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return _wilder(tr, n)
