import asyncio
import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from meridian.config import Settings
from meridian.engine.bus import EventBus
from meridian.engine.core import Engine
from meridian.engine.store import Store
from meridian.secrets_store import Secrets
from meridian.server import Server

TOKEN = "test-token"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path))
    for k in ("ANTHROPIC_API_KEY", "TRADERNET_PUBLIC_KEY", "TRADERNET_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "web").mkdir()
    eng = Engine(Settings(), Secrets(use_keyring=False), Store(tmp_path / "db.sqlite"), EventBus())
    eng.start()
    t0 = time.time()
    while not eng.quotes and time.time() - t0 < 10:
        time.sleep(0.1)
    yield eng
    eng.stop()


def run(engine, fn):
    async def main():
        async with TestClient(TestServer(Server(engine, TOKEN).app)) as c:
            await fn(c)
    asyncio.run(main())


H = {"X-Token": TOKEN}


def test_auth_required(engine):
    async def go(c):
        r = await c.get("/api/state")
        assert r.status == 401
        r = await c.get("/api/state", headers={"X-Token": "wrong"})
        assert r.status == 401
        r = await c.get("/api/state", headers=H)
        assert r.status == 200
        data = await r.json()
        assert data["app"]["demo"] is True
        assert "Content-Security-Policy" in r.headers
    run(engine, go)


def test_order_flow_and_errors(engine):
    async def go(c):
        q = engine.quotes["AAPL.US"]
        r = await c.post("/api/order", headers=H, json={"ticker": "AAPL.US", "side": "BUY",
                                                         "qty": 1, "limit": q["ask"] * 1.003})
        assert r.status == 200, await r.text()
        r = await c.post("/api/order", headers=H, json={"ticker": "AAPL.US", "side": "BUY",
                                                         "qty": 100, "limit": q["last"]})
        assert r.status == 400 and "manual order limit" in (await r.json())["error"]
        r = await c.post("/api/order", headers=H, json={"ticker": "AAPL.US", "side": "BUY",
                                                         "qty": 1, "limit": q["last"] * 0.5})
        assert r.status == 400 and "10%" in (await r.json())["error"]
        r = await c.post("/api/control", headers=H, json={"action": "execution", "mode": "live",
                                                           "confirm": "LIVE"})
        assert r.status == 400
        r = await c.post("/api/settings", headers=H, json={"risk": {"max_open_positions": -1}})
        assert r.status == 400
        r = await c.post("/api/settings", headers=H,
                         json={"risk": {"max_open_positions": 5}, "execution_mode": "live"})
        assert r.status == 200
        assert (await r.json())["risk"]["max_open_positions"] == 5
        assert engine.settings["execution_mode"] == "paper"
        r = await c.get("/api/chart?ticker=AAPL.US&tf=1D", headers=H)
        assert len((await r.json())["bars"]) > 1000
        r = await c.get("/api/export/trades.csv", headers=H)
        assert "AAPL.US" in await r.text()
    run(engine, go)


def test_websocket_pushes_state_and_events(engine):
    async def go(c):
        ws = await c.ws_connect(f"/ws?token={TOKEN}")
        first = json.loads((await ws.receive(timeout=10)).data)
        assert first["type"] == "state" and "quotes" in first["data"]
        types = set()
        t0 = time.time()
        while time.time() - t0 < 4:
            msg = await ws.receive(timeout=5)
            types.add(json.loads(msg.data)["type"])
        assert "quotes" in types and "account" in types
        await ws.close()
    run(engine, go)
