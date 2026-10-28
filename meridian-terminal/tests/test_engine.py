import time

import pytest

from meridian.config import Settings
from meridian.engine.bus import EventBus
from meridian.engine.core import Engine, EngineError
from meridian.engine.store import Store
from meridian.secrets_store import Secrets


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path))
    for k in ("ANTHROPIC_API_KEY", "TRADERNET_PUBLIC_KEY", "TRADERNET_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    eng = Engine(Settings(), Secrets(use_keyring=False), Store(tmp_path / "db.sqlite"), EventBus())
    eng.start()
    deadline = time.time() + 10
    while not eng.quotes and time.time() < deadline:
        time.sleep(0.2)
    yield eng
    eng.stop()


def test_demo_manual_trade_cycle(engine):
    t = "NVDA.US"
    q = engine.quotes[t]
    row = engine.manual_order(t, "BUY", 1, round(q["ask"] * 1.002, 2))
    assert row["status"] == "filled"
    assert engine.positions()[t] == 1
    view = engine.positions_view()
    assert view[0]["ticker"] == t and view[0]["mode"] == "demo"
    with pytest.raises(EngineError, match="short"):
        engine.manual_order(t, "SELL", 5, q["last"])
    engine.close_position(t)
    deadline = time.time() + 5
    while engine.positions().get(t) and time.time() < deadline:
        time.sleep(0.3)        # sell may rest a moment until the bid crosses
    assert not engine.positions().get(t)


def test_halt_blocks_orders_and_resume(engine):
    engine.halt("test")
    assert engine.halted and engine.app_view()["halted"]
    with pytest.raises(EngineError, match="halted"):
        engine.manual_order("AAPL.US", "BUY", 1, engine.quotes["AAPL.US"]["last"])
    engine.resume()
    assert not engine.halted


def test_live_mode_is_guarded(engine):
    with pytest.raises(EngineError, match="live data"):
        engine.set_execution("live", "LIVE")
    engine.set_execution("off")
    assert engine.acct() == "off"
    with pytest.raises(EngineError, match="Execution is off"):
        engine.manual_order("AAPL.US", "BUY", 1, engine.quotes["AAPL.US"]["last"])
    engine.set_execution("paper")
    assert engine.acct() == "demo"


def test_views_and_detail(engine):
    engine.scan()
    d = engine.ticker_detail("AAPL.US")
    assert d["snapshot"] and d["suggestion"] and len(d["diagnostics"]) == 5
    ch = engine.chart("AAPL.US", "15m")
    assert ch["bars"] and ch["bars"][-1]["time"] > ch["bars"][0]["time"]
    st = engine.ui_state()
    assert st["app"]["demo"] and st["account"]["equity"] > 0


def test_backtest_job(engine):
    job_id = engine.start_backtest(["AAPL.US"], 2, 10, None)
    deadline = time.time() + 60
    while engine.jobs[job_id]["status"] == "running" and time.time() < deadline:
        time.sleep(0.2)
    job = engine.jobs[job_id]
    assert job["status"] == "done" and job["results"][0]["results"]
