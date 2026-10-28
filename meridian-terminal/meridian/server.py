"""Local HTTP + WebSocket server for the UI (aiohttp).

Every /api and /ws request needs the per-install token (header X-Token or ?token=), so
other apps and websites on the machine can't drive the terminal. Static files are public.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import mimetypes
import threading
import webbrowser

from aiohttp import WSMsgType, web

from . import __version__, paths
from .config import SettingsError
from .engine.bus import dumps
from .engine.core import EngineError

log = logging.getLogger("meridian.server")

for ext, typ in ((".js", "application/javascript"), (".mjs", "application/javascript"),
                 (".css", "text/css"), (".woff2", "font/woff2"), (".svg", "image/svg+xml"),
                 (".json", "application/json"), (".png", "image/png")):
    mimetypes.add_type(typ, ext)   # Windows registry can map .js to text/plain

RESTART_KEYS = ("data_mode", "feeds", "sec_user_agent")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def json_response(data, status=200):
    return web.Response(text=dumps(data), status=status, content_type="application/json")


class Server:
    def __init__(self, engine, token: str):
        self.engine = engine
        self.token = token
        self.app = web.Application(middlewares=[self.errors, self.auth], client_max_size=2**20)
        r = self.app.router
        r.add_get("/", self.index)
        r.add_get("/ws", self.ws)
        r.add_get("/api/state", self.state)
        r.add_get("/api/chart", self.chart)
        r.add_get("/api/ticker/{ticker}", self.ticker)
        r.add_get("/api/decision/{id}", self.decision)
        r.add_get("/api/search", self.search)
        r.add_get("/api/settings", self.get_settings)
        r.add_post("/api/settings", self.post_settings)
        r.add_post("/api/secrets", self.post_secrets)
        r.add_post("/api/test/{service}", self.test)
        r.add_post("/api/control", self.control)
        r.add_post("/api/order", self.order)
        r.add_post("/api/order/cancel", self.cancel)
        r.add_post("/api/position/close", self.close)
        r.add_post("/api/backtest", self.backtest)
        r.add_get("/api/backtest/{id}", self.backtest_get)
        r.add_post("/api/open-url", self.open_url)
        r.add_get("/api/export/{kind}", self.export)
        r.add_static("/static/", paths.web_root(), show_index=False, follow_symlinks=False)
        self.app.on_response_prepare.append(self._headers)
        self._sockets: set = set()
        self.app.on_shutdown.append(self._close_sockets)

    # ---- middleware ------------------------------------------------------------------------
    @web.middleware
    async def auth(self, request, handler):
        p = request.path
        if p.startswith("/api/") or p == "/ws":
            tok = request.headers.get("X-Token") or request.query.get("token", "")
            if tok != self.token:
                return json_response({"error": "Not authorized. Reopen the app, or run "
                                               "`meridian url` for a fresh link."}, 401)
        return await handler(request)

    @web.middleware
    async def errors(self, request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except (EngineError, SettingsError, ValueError, KeyError) as e:
            msg = str(e).strip("'") or e.__class__.__name__
            return json_response({"error": msg}, 400)
        except Exception as e:
            log.exception("API error on %s", request.path)
            return json_response({"error": f"{e.__class__.__name__}: {e}"}, 500)

    async def _headers(self, request, response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Referrer-Policy"] = "no-referrer"

    async def _close_sockets(self, app):
        for ws in list(self._sockets):
            await ws.close()

    @staticmethod
    async def run(fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    @staticmethod
    async def body(request) -> dict:
        try:
            data = await request.json()
        except Exception:
            raise ValueError("Request body must be JSON")
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    # ---- pages ---------------------------------------------------------------------------------
    async def index(self, request):
        html = (paths.web_root() / "index.html").read_text("utf-8")
        return web.Response(text=html.replace("{{VERSION}}", __version__),
                            content_type="text/html")

    async def ws(self, request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=2**20)
        await ws.prepare(request)
        loop = asyncio.get_running_loop()
        q = self.engine.bus.subscribe(loop)
        self._sockets.add(ws)
        try:
            state = await self.run(self.engine.ui_state)
            await ws.send_str(dumps({"type": "state", "data": state}))

            async def pump():
                while True:
                    await ws.send_str(await q.get())

            sender = asyncio.ensure_future(pump())
            async for msg in ws:          # we only read to notice the client closing
                if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
            sender.cancel()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.engine.bus.unsubscribe(q)
            self._sockets.discard(ws)
        return ws

    # ---- reads -------------------------------------------------------------------------------
    async def state(self, request):
        return json_response(await self.run(self.engine.ui_state))

    async def chart(self, request):
        t = request.query["ticker"].upper()
        tf = request.query.get("tf", "1D")
        return json_response(await self.run(self.engine.chart, t, tf))

    async def ticker(self, request):
        return json_response(await self.run(self.engine.ticker_detail,
                                            request.match_info["ticker"].upper()))

    async def decision(self, request):
        d = await self.run(self.engine.store.decision, int(request.match_info["id"]))
        if not d:
            raise EngineError("Decision not found")
        return json_response(d)

    async def search(self, request):
        q = request.query.get("q", "").strip()
        if len(q) < 1:
            return json_response([])
        return json_response(await self.run(self.engine.search, q))

    async def get_settings(self, request):
        return json_response(self.engine.settings_view())

    # ---- writes ------------------------------------------------------------------------------
    async def post_settings(self, request):
        patch = await self.body(request)
        # execution mode and the kill switch have their own guarded actions (/api/control)
        patch.pop("execution_mode", None)
        patch.pop("halted", None)
        old = self.engine.settings.snapshot()
        new = self.engine.settings.update(patch)
        if any(old.get(k) != new.get(k) for k in RESTART_KEYS):
            await self.run(self.engine.restart)
        else:
            if old["watchlist"] != new["watchlist"]:
                log.info("Watchlist updated: %s", ", ".join(self.engine.settings.tickers))
                self.engine.wake("scan")
            self.engine.publish_all()
        return json_response(self.engine.settings_view())

    async def post_secrets(self, request):
        data = await self.body(request)
        from .secrets_store import KEYS
        changed = False
        for k, v in data.items():
            if k not in KEYS:
                raise ValueError(f"Unknown key {k}")
            if v is None:
                continue
            await self.run(self.engine.secrets.set, k, str(v))
            changed = True
        if changed:
            log.info("API keys updated (%s)", ", ".join(k for k in data if k in KEYS))
            await self.run(self.engine.restart)
        return json_response(self.engine.settings_view())

    async def test(self, request):
        msg = await self.run(self.engine.test_service, request.match_info["service"])
        return json_response({"ok": True, "message": msg})

    async def control(self, request):
        d = await self.body(request)
        action = d.get("action")
        e = self.engine
        if action == "halt":
            res = await self.run(e.halt, str(d.get("reason") or "dashboard")[:40])
        elif action == "resume":
            res = await self.run(e.resume)
        elif action in ("ai_on", "ai_off"):
            res = await self.run(e.set_ai, action == "ai_on")
        elif action == "execution":
            res = await self.run(e.set_execution, d.get("mode", ""), d.get("confirm", ""))
        elif action == "scan":
            e.wake("scan")
            res = "scan requested"
        elif action == "news":
            for s in e.sources:
                s._next = 0
            e.wake("news")
            res = "news poll requested"
        elif action == "reset_paper":
            res = await self.run(e.reset_paper)
        elif action == "quit":
            if e.on_quit:
                asyncio.get_running_loop().call_later(0.3, e.on_quit)
            res = "quitting"
        else:
            raise ValueError(f"Unknown action {action!r}")
        return json_response({"ok": True, "result": res})

    async def order(self, request):
        d = await self.body(request)
        row = await self.run(lambda: self.engine.manual_order(
            d.get("ticker", ""), d.get("side", ""), d.get("qty"), d.get("limit"),
            d.get("stop"), d.get("target")))
        return json_response({"ok": True, "order": row})

    async def cancel(self, request):
        d = await self.body(request)
        ok = await self.run(self.engine.cancel_order, d.get("id"))
        return json_response({"ok": ok})

    async def close(self, request):
        d = await self.body(request)
        row = await self.run(self.engine.close_position, str(d.get("ticker", "")).upper())
        return json_response({"ok": True, "order": row})

    async def backtest(self, request):
        d = await self.body(request)
        tickers = [str(t).upper().strip() for t in d.get("tickers", []) if str(t).strip()][:12]
        if not tickers:
            raise ValueError("Pick at least one ticker")
        years = float(d.get("years", 3))
        if not 1 <= years <= 15:
            raise ValueError("Years must be between 1 and 15")
        cost = float(d.get("cost_bps", 10))
        if not 0 <= cost <= 200:
            raise ValueError("Cost must be between 0 and 200 basis points")
        job = self.engine.start_backtest(tickers, years, cost, d.get("rules") or None)
        return json_response({"id": job})

    async def backtest_get(self, request):
        job = self.engine.jobs.get(request.match_info["id"])
        if not job:
            raise EngineError("Backtest not found")
        return json_response(job)

    async def open_url(self, request):
        d = await self.body(request)
        url = str(d.get("url", ""))
        if not url.startswith(("https://", "http://")):
            raise ValueError("Only web links can be opened")
        await self.run(webbrowser.open, url)
        return json_response({"ok": True})

    async def export(self, request):
        kind = request.match_info["kind"].removesuffix(".csv")
        store = self.engine.store
        if kind == "trades":
            rows = store.recent_trades(100000)
        elif kind == "decisions":
            rows = [{k: (dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()}
                    for r in store.recent_decisions(100000)]
        elif kind == "orders":
            rows = store.recent_orders(100000)
        elif kind == "news":
            rows = store.recent_news(100000)
        else:
            raise ValueError("Unknown export")
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return web.Response(text=buf.getvalue(), content_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="meridian-{kind}.csv"'})


class ServerThread:
    """Runs the aiohttp server on its own event loop in a background thread (desktop app)."""

    def __init__(self, server: Server, host: str = "127.0.0.1", port: int = 0):
        self.server, self.host, self.port = server, host, port
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._runner = None
        self.error = None

    def start(self) -> int:
        threading.Thread(target=self._run, name="meridian-server", daemon=True).start()
        self._ready.wait(15)
        if self.error:
            raise self.error
        return self.port

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self._runner = web.AppRunner(self.server.app, access_log=None)
            self.loop.run_until_complete(self._runner.setup())
            site = web.TCPSite(self._runner, self.host, self.port)
            self.loop.run_until_complete(site.start())
            self.port = site._server.sockets[0].getsockname()[1]
        except Exception as e:
            self.error = e
            self._ready.set()
            return
        self._ready.set()
        self.loop.run_forever()

    def stop(self):
        if self._runner is None:
            return

        async def shutdown():
            await self._runner.cleanup()

        try:
            fut = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            fut.result(timeout=5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
