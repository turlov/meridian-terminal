import time

import numpy as np
import pytest

from meridian.config import Settings, SettingsError
from meridian.engine import backtest, risk, strategies
from meridian.engine.analyst import Signal
from meridian.engine.demo import DemoMarket
from meridian.engine.market import Candles, resample, rsi, snapshot
from meridian.engine.paper import PaperBroker
from meridian.engine.store import Store
from meridian.engine.strategies import Candidate


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def store(home):
    return Store(home / "t.sqlite")


def make_candles(n=400, seed=1, drift=0.0005):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, 0.015, n)
    c = 100 * np.exp(np.cumsum(r))
    o = np.concatenate([[100], c[:-1]])
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    v = rng.lognormal(13, 0.3, n)
    t = (np.arange(n) * 86400 + 1_600_000_000).astype(np.int64)
    return Candles(t, o, h, l, c, v)


# ---- settings -----------------------------------------------------------------------------
def test_settings_validation(home):
    s = Settings()
    assert s["execution_mode"] == "paper"
    with pytest.raises(SettingsError):
        s.update({"execution_mode": "live"})          # needs the confirmed path
    with pytest.raises(SettingsError):
        s.update({"risk": {"max_open_positions": 0}})
    with pytest.raises(SettingsError):
        s.update({"watchlist": [{"ticker": "AAPL.US"}, {"ticker": "aapl.us"}]})
    s.update({"watchlist": [{"ticker": "msft.us", "keywords": ["Microsoft", " "]}]})
    assert s.tickers == ["MSFT.US"] and s.keywords()["MSFT.US"] == ["Microsoft"]
    assert Settings()["watchlist"][0]["ticker"] == "MSFT.US"   # persisted


# ---- indicators -------------------------------------------------------------------------------
def test_rsi_bounds_and_direction():
    up = np.linspace(100, 130, 100)
    down = np.linspace(130, 100, 100)
    assert rsi(up) > 95 and rsi(down) < 5


def test_resample_weekly_preserves_ohlc():
    d = make_candles(30)
    w = resample(d, 604800, anchor_monday=True)
    assert w.h.max() == pytest.approx(d.h.max())
    assert w.v.sum() == pytest.approx(d.v.sum())
    assert w.c[-1] == pytest.approx(d.c[-1])


def test_snapshot_uses_live_price():
    d = make_candles(300)
    s = snapshot("X", d, last=d.c[-1] * 1.1)
    assert s.last == pytest.approx(d.c[-1] * 1.1)
    assert s.ret1 == pytest.approx(s.last / d.c[-2] - 1)
    assert snapshot("X", d.tail(100)) is None


# ---- strategies & risk -----------------------------------------------------------------------------
def snap_with(**kw):
    base = dict(ticker="T.US", last=100.0, prev_close=99.0, ret1=0.01, ret5=0.02, ret20=0.05,
                sma20=98.0, sma50=95.0, sma200=90.0, rsi14=55.0, atr14=2.0, vol_ratio=1.0,
                high20_prev=99.0, low20_prev=90.0, high252=110.0, low252=80.0, bars=300)
    base.update(kw)
    from meridian.engine.market import Snapshot
    return Snapshot(**base)


def test_rules_and_diagnostics():
    s = snap_with()                      # above 20d high in uptrend
    cands = strategies.scan(s, False, strategies.ENTRY_RULES)
    assert [c.strategy for c in cands] == ["trend_breakout"]
    diag = {d["rule"]: d["status"] for d in strategies.diagnose(s, False, strategies.ENTRY_RULES)}
    assert diag["trend_breakout"] == "firing" and diag["trend_exit"] == "n/a"
    held = strategies.scan(snap_with(last=94.0, high20_prev=120), True, strategies.EXIT_RULES)
    assert [c.strategy for c in held] == ["trend_exit"]


RISK = {"risk_per_trade_usd": 20.0, "atr_stop_mult": 2.0, "atr_target_mult": 4.0,
        "max_usd_per_trade": 200.0, "max_open_positions": 3, "max_daily_loss_usd": 100.0,
        "ticker_cooldown_min": 120, "max_slippage_pct": 0.5, "max_news_age_min": 15,
        "manual_max_usd": 1000.0}


def check(sig, cands, snap, positions=None, **kw):
    args = dict(risk=RISK, min_confidence=0.75, watchlist=["T.US"], day_pnl=0.0,
                last_trade_ts=None, halted=False)
    args.update(kw)
    return risk.check(sig, cands, snap, positions or {}, **args)


def test_risk_gate():
    s = snap_with()
    buy = [Candidate("T.US", "BUY", "trend_breakout", 0.6, "x")]
    sig = lambda a, c=0.9: Signal("T.US", a, c, "days", "", "")
    order, why = check(sig("BUY"), buy, s)
    assert order and order.qty == 2 and order.stop == 96.0 and order.target == 108.0  # $200 cap
    assert check(sig("SELL"), buy, s)[0] is None                    # can't flip direction
    assert check(sig("BUY", 0.6), buy, s)[0] is None                 # low confidence
    assert check(sig("BUY"), buy, s, halted=True)[1].startswith("trading halted")
    assert "daily loss" in check(sig("BUY"), buy, s, day_pnl=-150)[1]
    assert "traded less" in check(sig("BUY"), buy, s, last_trade_ts=time.time())[1]
    full = {"A": 1, "B": 1, "C": 1}
    assert "max open" in check(sig("BUY"), buy, s, positions=full)[1]
    news = [Candidate("T.US", "EITHER", "news", 0.8, "x")]
    assert check(sig("BUY"), news, s, mentioned=("OTHER.US",))[0] is None
    assert check(sig("SELL"), news, s, positions={"T.US": 5})[0].qty == 5


def test_manual_checks():
    m = lambda **kw: risk.check_manual(**{**dict(ticker="T.US", side="BUY", qty=5, limit=100,
                                                 last=100, positions={}, risk=RISK,
                                                 halted=False), **kw})
    assert m() is None
    assert "manual order limit" in m(qty=50)
    assert "10%" in m(limit=120)
    assert "short" in m(side="SELL")
    assert "halted" in m(halted=True)


# ---- paper broker ----------------------------------------------------------------------------------
def test_paper_fill_stop_and_pnl(store):
    pb = PaperBroker(store, 10000, mode="paper")
    q = {"last": 100.0, "bid": 99.9, "ask": 100.1}
    order, fills = pb.place("T.US", "BUY", 10, 100.5, "auto", stop=95, target=110, quote=q)
    assert order["status"] == "filled" and fills[0]["price"] == 100.1
    assert store.paper_account("paper")["cash"] == pytest.approx(10000 - 1001)
    # working order that doesn't cross
    o2, f2 = pb.place("T.US", "BUY", 1, 90, "manual", quote=q)
    assert o2["status"] == "working" and not f2
    assert pb.cancel(o2["id"]) and store.order(o2["id"])["status"] == "cancelled"
    # stop triggers on a drop
    fills = pb.on_quotes({"T.US": {"last": 94.0, "bid": 93.9, "ask": 94.1}})
    assert fills and fills[0]["source"] == "stop"
    assert fills[0]["realized_pnl"] == pytest.approx((94.0 - 100.1) * 10)
    assert pb.positions() == {}
    acct = pb.account({})
    assert acct["equity"] == pytest.approx(10000 + (94.0 - 100.1) * 10)


def test_paper_rejects(store):
    pb = PaperBroker(store, 1000, mode="demo")
    q = {"last": 100.0, "bid": 99.9, "ask": 100.1}
    o, _ = pb.place("T.US", "BUY", 50, 100.5, "manual", quote=q)
    assert o["status"] == "rejected" and "cash" in o["note"]
    o, _ = pb.place("T.US", "SELL", 1, 99, "manual", quote=q)
    assert o["status"] == "rejected"


def test_paper_accounts_are_separate(store):
    PaperBroker(store, 5000, mode="demo")
    PaperBroker(store, 7000, mode="paper")
    assert store.paper_account("demo")["cash"] == 5000
    assert store.paper_account("paper")["cash"] == 7000
    store.reset_paper("demo", 1234)
    assert store.paper_account("demo")["cash"] == 1234
    assert store.paper_account("paper")["cash"] == 7000


# ---- demo market & backtest -----------------------------------------------------------------------------
def test_demo_market_and_backtest():
    m = DemoMarket()
    m.sync({"AAA.US": ["Alpha"], "BBB.US": ["Beta"]})
    for _ in range(5):
        m.step()
    q = m.quotes(["AAA.US"])["AAA.US"]
    assert q["bid"] < q["last"] < q["ask"]
    d = m.candles("AAA.US", "1D")
    assert len(d) > 1000 and np.all(np.diff(d.t) > 0)
    for tf in ("1m", "5m", "15m", "1h", "1W"):
        c = m.candles("AAA.US", tf)
        assert len(c) > 0 and np.all(np.diff(c.t) > 0), tf
    res = backtest.run("AAA.US", d.tail(600), None, RISK, 0.001)
    assert res["bars"] == 600 - 210 and len(res["results"]) == 3
    r = res["results"][0]
    assert len(r["curve"]) == res["bars"]
    assert r["trades"] == len(r["trade_list"])
    assert -1 < r["max_dd"] <= 0


def test_backtest_too_short():
    assert "error" in backtest.run("X", make_candles(150), None, RISK, 0.001)


def test_demo_news_never_reaches_live_reviews(store):
    from datetime import datetime, timezone
    from meridian.engine.news import NewsItem
    now = datetime.now(timezone.utc)
    store.add_news(NewsItem("d1", "demo", now, "Nvidia announces buyback", tickers=("NVDA.US",)))
    store.add_news(NewsItem("r1", "finnhub", now, "Nvidia files 10-Q", tickers=("NVDA.US",)))
    live = store.headlines_for("NVDA.US", demo=False)
    assert len(live) == 1 and "10-Q" in live[0]
    assert "buyback" in store.headlines_for("NVDA.US", demo=True)[0]
    assert [n["id"] for n in store.recent_news(10, demo=False)] == ["r1"]
    store.add_decision({"ts": 1, "ticker": "NVDA.US", "trigger": "rules", "mode": "demo-off"})
    store.add_decision({"ts": 2, "ticker": "NVDA.US", "trigger": "rules", "mode": "paper"})
    assert [d["mode"] for d in store.recent_decisions(10, demo=False)] == ["paper"]
    assert [d["mode"] for d in store.recent_decisions(10, demo=True)] == ["demo-off"]
