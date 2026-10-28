"""Demo mode: a simulated market, newsfeed and reviewer so the app can be explored without
API keys. Nothing here is real data; the UI labels it DEMO everywhere."""
from __future__ import annotations

import hashlib
import math
import random
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np

from .market import TIMEFRAMES, Candles, resample

SESSION_MIN = 390   # minutes in a demo trading session

POSITIVE = [
    ("{kw} beats quarterly estimates and raises full-year guidance",
     "Revenue and margins came in ahead of consensus; management lifted its outlook."),
    ("{kw} announces $2bn share buyback program",
     "The board approved a new repurchase authorization, larger than analysts expected."),
    ("{kw} wins major contract, shares jump in heavy trading",
     "The multi-year agreement is expected to add meaningfully to revenue."),
    ("Analysts upgrade {kw} to Buy, citing accelerating demand",
     "Two brokers raised price targets after channel checks pointed to strong orders."),
]
NEGATIVE = [
    ("{kw} cuts outlook as demand softens",
     "Management lowered revenue guidance and flagged weaker orders next quarter."),
    ("Regulator opens inquiry into {kw} accounting practices",
     "The company said it is cooperating fully; no charges have been filed."),
    ("{kw} CFO resigns unexpectedly",
     "The company named an interim replacement and reaffirmed guidance."),
]
MACRO = [
    "Treasury yields edge higher ahead of inflation data",
    "Oil steadies as traders weigh supply outlook",
    "Dollar index slips after weaker manufacturing survey",
    "European shares open mixed; banks lead gains",
    "Asian markets close higher on tech rally",
    "Fed officials signal patience on rate path",
    "Gold holds near record as investors seek safety",
    "Central bank keeps base rate unchanged, cites inflation risks",
    "Copper climbs on stronger demand expectations",
    "Volatility index falls to three-week low",
]


def _seed(ticker: str) -> int:
    return int(hashlib.sha1(ticker.encode()).hexdigest()[:8], 16)


class DemoSymbol:
    def __init__(self, ticker: str, name: str, now: float):
        self.ticker = ticker
        self.name = name
        rng = np.random.default_rng(_seed(ticker))
        self.rng = random.Random(_seed(ticker) ^ int(now))
        self.daily_vol = float(rng.uniform(0.014, 0.028))
        price0 = float(rng.uniform(25, 320))
        self.avg_volume = float(rng.uniform(2e6, 4e7))

        # ~5 years of weekday daily bars ending yesterday
        days, d = [], datetime.fromtimestamp(now).date() - timedelta(days=1)
        while len(days) < 1300:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        days.reverse()
        n = len(days)
        drift = float(rng.uniform(-0.0002, 0.0007))
        r = rng.normal(drift, self.daily_vol, n)
        # a few regimes so trends and pullbacks exist
        for _ in range(6):
            s = int(rng.integers(0, n - 60))
            r[s:s + int(rng.integers(20, 60))] += float(rng.normal(0, 0.004))
        c = price0 * np.exp(np.cumsum(r))
        o = np.concatenate([[price0], c[:-1]]) * np.exp(rng.normal(0, self.daily_vol / 4, n))
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, self.daily_vol / 2, n)))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, self.daily_vol / 2, n)))
        v = self.avg_volume * np.exp(rng.normal(0, 0.35, n)) * (1 + 8 * np.abs(r))
        t = np.array([int(datetime(x.year, x.month, x.day, tzinfo=timezone.utc).timestamp())
                      for x in days], dtype=np.int64)
        self.daily = Candles(t, o, h, l, c, v)
        self.prev_close = float(c[-1])

        # today's session: started SESSION_MIN*0.85 minutes ago, minute bars pre-filled
        start_min = int(now // 60) - int(SESSION_MIN * 0.85)
        self.session_start = start_min * 60
        sigma_min = self.daily_vol / math.sqrt(SESSION_MIN)
        price = self.prev_close * math.exp(float(rng.normal(0, self.daily_vol / 3)))
        self.open = price
        self.m_t, self.m_o, self.m_h, self.m_l, self.m_c, self.m_v = [], [], [], [], [], []
        for i in range(int(now // 60) - start_min):
            o_ = price
            price *= math.exp(float(rng.normal(0, sigma_min)))
            hi = max(o_, price) * (1 + abs(float(rng.normal(0, sigma_min / 3))))
            lo = min(o_, price) * (1 - abs(float(rng.normal(0, sigma_min / 3))))
            self._append_minute((start_min + i) * 60, o_, hi, lo, price,
                                self.avg_volume / SESSION_MIN * float(rng.lognormal(0, 0.5)))
        self.last = price
        self.sigma_sec = self.daily_vol / math.sqrt(SESSION_MIN * 60) * 2.2  # livelier than life
        self.burst_until = 0.0
        self.burst_volume = 0.0

    def _append_minute(self, t, o, h, l, c, v):
        self.m_t.append(t); self.m_o.append(o); self.m_h.append(h)
        self.m_l.append(l); self.m_c.append(c); self.m_v.append(v)

    def tick(self, now: float, jump: float = 0.0):
        self.last *= math.exp(self.rng.gauss(0, self.sigma_sec) + jump)
        minute = int(now // 60) * 60
        vol = self.avg_volume / (SESSION_MIN * 60) * self.rng.lognormvariate(0, 0.6)
        if now < self.burst_until:
            vol += self.burst_volume
        if not self.m_t or minute > self.m_t[-1]:
            o = self.m_c[-1] if self.m_c else self.last
            self._append_minute(minute, o, max(o, self.last), min(o, self.last), self.last, vol)
        else:
            self.m_h[-1] = max(self.m_h[-1], self.last)
            self.m_l[-1] = min(self.m_l[-1], self.last)
            self.m_c[-1] = self.last
            self.m_v[-1] += vol

    def minutes(self) -> Candles:
        return Candles(np.array(self.m_t, dtype=np.int64), np.array(self.m_o), np.array(self.m_h),
                       np.array(self.m_l), np.array(self.m_c), np.array(self.m_v))

    def daily_with_today(self) -> Candles:
        m = self.minutes()
        today = int(datetime.fromtimestamp(self.session_start).replace(
            hour=0, minute=0, second=0, tzinfo=timezone.utc).timestamp())
        if today <= self.daily.t[-1]:
            today = int(self.daily.t[-1]) + 86400
        d = self.daily
        return Candles(np.append(d.t, today), np.append(d.o, m.o[0]), np.append(d.h, m.h.max()),
                       np.append(d.l, m.l.min()), np.append(d.c, m.c[-1]),
                       np.append(d.v, m.v.sum()))

    def quote(self) -> dict:
        m_h, m_l = max(self.m_h), min(self.m_l)
        spread = self.last * 0.0002
        chg = self.last - self.prev_close
        return {
            "ticker": self.ticker, "name": self.name, "last": round(self.last, 2),
            "bid": round(self.last - spread, 2), "ask": round(self.last + spread, 2),
            "open": round(self.open, 2), "high": round(m_h, 2), "low": round(m_l, 2),
            "prev_close": round(self.prev_close, 2), "chg": round(chg, 2),
            "chg_pct": round(chg / self.prev_close * 100, 2), "volume": int(sum(self.m_v)),
            "currency": "USD", "ts": time.time(),
        }


class DemoMarket:
    def __init__(self):
        self._lock = threading.Lock()
        self.symbols: dict[str, DemoSymbol] = {}
        self.events: list[dict] = []
        self.keywords: dict[str, list[str]] = {}
        self.rng = random.Random()
        now = time.time()
        self.next_event = now + self.rng.uniform(25, 45)
        self.next_macro = now + self.rng.uniform(10, 20)

    def sync(self, keywords: dict[str, list[str]]):
        with self._lock:
            self.keywords = keywords
            now = time.time()
            for t, kws in keywords.items():
                if t not in self.symbols:
                    name = kws[0] if kws else t.split(".")[0]
                    self.symbols[t] = DemoSymbol(t, name, now)

    def step(self):
        now = time.time()
        with self._lock:
            for s in self.symbols.values():
                s.tick(now)
            if now >= self.next_event and self.symbols:
                self._company_event(now)
                self.next_event = now + self.rng.uniform(70, 160)
            if now >= self.next_macro:
                self.events.append({"headline": self.rng.choice(MACRO), "summary": "",
                                    "ticker": None, "published": now})
                self.next_macro = now + self.rng.uniform(40, 90)

    def _company_event(self, now: float):
        s = self.rng.choice(list(self.symbols.values()))
        kw = (self.keywords.get(s.ticker) or [s.name])[0]
        positive = self.rng.random() < 0.65
        headline, summary = self.rng.choice(POSITIVE if positive else NEGATIVE)
        jump = self.rng.uniform(0.035, 0.065) * (1 if positive else -1)
        s.tick(now, jump=jump)
        s.burst_until = now + 240
        s.burst_volume = s.avg_volume * 2.2 / 240
        self.events.append({"headline": headline.format(kw=kw), "summary": summary,
                            "ticker": s.ticker, "published": now, "positive": positive})

    def pop_events(self) -> list[dict]:
        with self._lock:
            ev, self.events = self.events, []
            return ev

    def quotes(self, tickers) -> dict[str, dict]:
        with self._lock:
            return {t: self.symbols[t].quote() for t in tickers if t in self.symbols}

    def candles(self, ticker: str, tf: str) -> Candles:
        with self._lock:
            s = self.symbols.get(ticker)
            if not s:
                return Candles.empty()
            if tf == "1D":
                return s.daily_with_today()
            if tf == "1W":
                return resample(s.daily_with_today(), TIMEFRAMES["1W"], anchor_monday=True)
            m = s.minutes()
        return m if tf == "1m" else resample(m, TIMEFRAMES[tf])

    def search(self, q: str) -> list[dict]:
        q = q.upper().strip()
        sample = ["AAPL.US", "MSFT.US", "NVDA.US", "AMZN.US", "TSLA.US", "META.US", "GOOGL.US",
                  "FRHC.US", "KSPI.US", "KZAP.KZ", "HSBK.KZ", "KEGC.KZ", "AMD.US", "NFLX.US"]
        return [{"ticker": t, "name": t.split(".")[0], "exchange": "DEMO"}
                for t in sample if q in t][:10] or ([{"ticker": q if "." in q else q + ".US",
                                                      "name": q, "exchange": "DEMO"}] if q else [])


# ---- simulated reviewer ---------------------------------------------------------------------
POS_WORDS = ("beats", "raises", "buyback", "wins", "upgrade", "jump", "record", "strong")
NEG_WORDS = ("cuts", "inquiry", "resigns", "downgrade", "weak", "miss", "probe", "falls")


def demo_triage(headline: str, tickers) -> tuple[int, str]:
    if not tickers:
        return 2, "NONE"
    low = headline.lower()
    material = any(w in low for w in POS_WORDS + NEG_WORDS)
    return (8 if material else 4), tickers[0]


def demo_review(ticker, candidates, snap, position_qty, headlines, trigger) -> dict:
    """Plausible-looking but simulated verdict. Clearly labelled as not coming from Claude."""
    actions = {c.action for c in candidates}
    strength = sum(c.strength for c in candidates) / len(candidates)
    conflicts = []
    conf = 0.55 + 0.35 * strength
    action = next(iter(actions)) if len(actions) == 1 else "HOLD"
    if trigger is not None:
        low = trigger.headline.lower()
        pos = any(w in low for w in POS_WORDS)
        neg = any(w in low for w in NEG_WORDS)
        if "EITHER" in actions:
            action = "BUY" if pos and not neg else ("SELL" if neg and position_qty > 0 else "HOLD")
        if neg and action == "BUY":
            conf -= 0.25
            conflicts.append("headline is negative")
    if action == "BUY":
        if snap.rsi14 > 75:
            conf -= 0.2
            conflicts.append(f"RSI {snap.rsi14:.0f} already stretched")
        if snap.ret20 > 0.15:
            conf -= 0.1
            conflicts.append(f"up {snap.ret20 * 100:.0f}% in 20 days")
        if snap.last < snap.sma200:
            conf -= 0.1
            conflicts.append("below SMA200")
    conf = max(0.05, min(0.92, conf))
    if action != "HOLD" and conf < 0.6:
        action = "HOLD"
    why = ", ".join(c.evidence for c in candidates)
    return {
        "action": action, "confidence": round(conf, 2),
        "horizon": "days" if "news" not in {c.strategy for c in candidates} else "hours",
        "conflicts": "; ".join(conflicts) or "none",
        "reasoning": f"[Demo reviewer: simulated, no Claude call] Evidence: {why}. "
                     f"RSI {snap.rsi14:.0f}, price {'above' if snap.last > snap.sma50 else 'below'} "
                     f"SMA50, volume {snap.vol_ratio:.1f}x. "
                     + ("Setup is coherent." if action != "HOLD" else "Not convincing enough."),
    }
