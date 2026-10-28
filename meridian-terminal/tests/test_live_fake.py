"""Drive the engine in live mode against a fake Tradernet SDK (no network)."""
import time

import numpy as np
import pytest

from meridian.config import Settings
from meridian.engine import tradernet_api
from meridian.engine.bus import EventBus
from meridian.engine.core import Engine
from meridian.engine.store import Store
from meridian.secrets_store import Secrets


class FakeTradernet:
    calls: list = []

    def __init__(self, public, private):
        self.timeout = 300
        self.positions = []
        self.orders = []
        rng = np.random.default_rng(3)
        self.px = {}
        self.hist = {}
        for i, t in enumerate(["AAPL.US", "NVDA.US", "FRHC.US", "KSPI.US", "KZAP.KZ"]):
            c = 100 * np.exp(np.cumsum(rng.normal(0.0008, 0.015, 400)))
            self.hist[t] = c
            self.px[t] = float(c[-1])

    def get_quotes(self, symbols):
        FakeTradernet.calls.append(("quotes", tuple(symbols)))
        return {"result": {"q": [{"c": t, "ltp": self.px[t], "bbp": self.px[t] - 0.05, "bap": self.px[t] + 0.05,
                                  "pp": self.px[t] * 0.99, "chg": self.px[t] * 0.01, "pcp": 1.0, "op": self.px[t],
                                  "maxtp": self.px[t] * 1.01, "mintp": self.px[t] * 0.98, "vol": 123456,
                                  "name": t.split(".")[0] + " Inc", "x_curr": "USD"} for t in symbols if t in self.px]}}

    def get_candles(self, symbol, start, end, timeframe):
        c = self.hist[symbol]
        n = len(c)
        t0 = int(time.time()) - n * timeframe
        ts = [t0 + i * timeframe - 3 * 3600 for i in range(n)]
        return {"hloc": {symbol: [[x * 1.01, x * 0.99, x, x] for x in c]}, "xSeries": {symbol: ts},
                "vl": {symbol: [1_000_000] * n}}

    def find_symbol(self, q):
        return {"found": [{"t": "MSFT.US", "nm": "Microsoft Corp", "x": "NASDAQ"}]}

    def get_news(self, query, symbol=None, story_id=None, limit=30):
        return {"result": [{"id": f"n-{symbol}", "title": f"{symbol} files quarterly report",
                            "content": "<p>Body text</p>", "date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}]}

    def user_info(self):
        return {"result": {"login": "demo-user"}}

    def account_summary(self):
        return {"result": {"ps": {"acc": [{"s": 5000.0, "curr": "USD", "currval": 1}],
                                  "pos": self.positions}}}

    def get_placed(self, active=True):
        return {"result": {"orders": {"order": self.orders}}}

    def buy(self, symbol, quantity=1, price=0.0, duration="day", use_margin=True, custom_order_id=None):
        assert use_margin is False and price > 0
        FakeTradernet.calls.append(("buy", symbol, quantity, price))
        self.positions.append({"i": symbol, "q": quantity, "bal_price_a": price, "mkt_price": self.px[symbol],
                               "profit_close": 0.0, "curr": "USD", "currval": 1, "name": symbol})
        return {"order_id": 777}

    def sell(self, symbol, quantity=1, price=0.0, duration="day", use_margin=True, custom_order_id=None):
        assert use_margin is False
        FakeTradernet.calls.append(("sell", symbol, quantity, price))
        self.positions = [p for p in self.positions if p["i"] != symbol]
        return {"order_id": 778}

    def cancel(self, order_id):
        FakeTradernet.calls.append(("cancel", order_id))
        return {"result": True}

    def cancel_all(self):
        FakeTradernet.calls.append(("cancel_all",))
        return []

    def stop(self, symbol, price):
        FakeTradernet.calls.append(("stop", symbol, price))
        return {"result": True}

    def take_profit(self, symbol, price):
        FakeTradernet.calls.append(("take_profit", symbol, price))
        return {"result": True}


@pytest.fixture
def live_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path))
    for k in ("ANTHROPIC_API_KEY",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TRADERNET_PUBLIC_KEY", "pub")
    monkeypatch.setenv("TRADERNET_PRIVATE_KEY", "priv")
    import tradernet
    monkeypatch.setattr(tradernet, "Tradernet", FakeTradernet)
    FakeTradernet.calls = []
    s = Settings()
    s.update({"data_mode": "live", "feeds": {"finnhub": False, "sec_8k": False},
              "intervals": {"quotes_sec": 1, "news_sec": 5, "scan_min": 60, "account_sec": 5}})
    eng = Engine(s, Secrets(use_keyring=False), Store(tmp_path / "db.sqlite"), EventBus())
    eng.start()
    t0 = time.time()
    while not eng.quotes and time.time() - t0 < 10:
        time.sleep(0.1)
    yield eng
    eng.stop()


def test_live_data_paths(live_engine):
    e = live_engine
    assert not e.demo and e.data.tn.timeout == 20
    q = e.quotes["AAPL.US"]
    assert q["last"] > 0 and q["bid"] < q["ask"] and q["name"] == "AAPL Inc"
    d = e.daily("AAPL.US")
    assert len(d) == 400 and np.all(np.diff(d.t) > 0)
    assert e.snapshot("AAPL.US") is not None
    assert e.search("micro")[0]["ticker"] == "MSFT.US"
    assert "demo-user" in e.test_service("tradernet")
    time.sleep(1.5)
    assert e.store.recent_news(10)                     # Tradernet news parsed and stored
    st = e.status_view()
    assert st["market"]["ok"] and any(s["name"] == "tradernet" for s in st["sources"])


def test_live_order_protection_and_close(live_engine):
    e = live_engine
    e.set_execution("live", "LIVE")
    assert e.acct() == "live"
    t = "NVDA.US"
    px = e.quotes[t]["ask"]
    row = e.manual_order(t, "BUY", 2, round(px * 1.001, 2), stop=round(px * 0.95, 2), target=round(px * 1.1, 2))
    assert row["broker_ref"] == "777" and ("buy", t, 2, round(px * 1.001, 2)) in FakeTradernet.calls
    e.wake("account")
    t0 = time.time()
    while not e.store.book("live").get(t, {}).get("protected") and time.time() - t0 < 10:
        time.sleep(0.2)
    assert e.store.book("live")[t]["protected"] == 1
    kinds = [c[0] for c in FakeTradernet.calls]
    assert "stop" in kinds and "take_profit" in kinds
    assert e.positions()[t] == 2
    assert e.account()["equity"] > 5000
    pv = e.positions_view()
    assert pv[0]["stop"] and pv[0]["protected"]
    e.close_position(t)
    assert any(c[0] == "sell" and c[1] == t for c in FakeTradernet.calls)
    e.halt("test")
    assert ("cancel_all",) in FakeTradernet.calls
