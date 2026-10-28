"""The engine: background loops for quotes, news, rule scans and account sync, plus the
decision pipeline  candidates -> Claude review -> risk gate -> order.

Account modes ('acct'):  demo  = paper trading on simulated prices
                         paper = paper trading on real Tradernet prices
                         live  = real orders on Tradernet
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone

from .. import APP_NAME, __version__, paths
from . import backtest as bt
from . import risk, strategies
from .analyst import BudgetExceeded, ClaudeAnalyst, DemoAnalyst
from .demo import DemoMarket
from .market import TIMEFRAMES, Candles, snapshot
from .news import NewsItem, build_sources
from .paper import PaperBroker
from .store import Store
from .strategies import Candidate
from .tradernet_api import TradernetData

log = logging.getLogger("meridian.engine")

DEMO_INTERVALS = {"quotes_sec": 1, "news_sec": 3, "scan_min": 1, "account_sec": 30}


class EngineError(Exception):
    """User-facing error (message is shown in the UI as is)."""


class Engine:
    def __init__(self, settings, secrets, store: Store, bus, shell: str = "browser"):
        self.settings = settings
        self.secrets = secrets
        self.store = store
        self.bus = bus
        self.shell = shell            # desktop | browser | headless
        self.started = time.time()
        self.on_quit = None
        self._lock = threading.RLock()
        self._eval_lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = {"scan": threading.Event(), "news": threading.Event(),
                      "account": threading.Event()}
        self._threads: list[threading.Thread] = []
        self._last_review: dict[tuple, float] = {}
        self._daily: dict[str, tuple[float, Candles]] = {}
        self._chart_cache: dict[tuple, tuple[float, Candles]] = {}
        self._err_logged: dict[str, float] = {}
        self.quotes: dict[str, dict] = {}
        self.snaps: dict[str, dict] = {}
        self.broker_account: dict = {}
        self.broker_orders: list[dict] = []
        self.jobs: dict[str, dict] = {}
        self.market = None
        self.data = None
        self.analyst = None
        self.paper = None
        self.sources = []
        self.status = {
            "market": {"ok": None, "last": None, "error": "", "label": ""},
            "account": {"ok": None, "last": None, "error": ""},
            "scan": {"last": None, "next": None, "running": False, "error": ""},
            "news": {"last": None, "next": None},
            "notice": "",
        }

    # ---- lifecycle ----------------------------------------------------------------------
    @property
    def demo(self) -> bool:
        return self.market is not None

    def acct(self) -> str:
        """Which account orders go to right now: demo | paper | live | off."""
        mode = self.settings["execution_mode"]
        if mode == "off":
            return "off"
        if self.demo:
            return "demo"
        return mode

    def book_mode(self) -> str:
        a = self.acct()
        if a == "off":
            return "demo" if self.demo else "paper"
        return a

    def intervals(self) -> dict:
        return dict(DEMO_INTERVALS) if self.demo else self.settings.get("intervals")

    def start(self):
        self._stop.clear()
        self._build()
        loops = [("quotes", self._quotes_loop), ("news", self._news_loop),
                 ("scan", self._scan_loop)]
        if not self.demo:
            loops.append(("account", self._account_loop))
        self._threads = []
        for name, fn in loops:
            th = threading.Thread(target=self._guard(name, fn), name=f"meridian-{name}",
                                  daemon=True)
            th.start()
            self._threads.append(th)
        log.info("%s %s started: %s data, %s account, AI %s", APP_NAME, __version__,
                 "demo" if self.demo else "Tradernet", self.acct(),
                 "on" if self.settings["ai_enabled"] else "off")
        self.publish_all()

    def stop(self):
        self._stop.set()
        for e in self._wake.values():
            e.set()
        for th in self._threads:
            th.join(timeout=8)
        self._threads = []

    def restart(self):
        log.info("Restarting engine with new settings")
        self.stop()
        with self._lock:
            self.quotes, self.snaps, self._daily, self._chart_cache = {}, {}, {}, {}
            self.broker_account, self.broker_orders = {}, []
        self.start()
        self.bus.publish("reset")      # tell open dashboards to reload their full state

    def _build(self):
        s, sec = self.settings, self.secrets
        want_live = s["data_mode"] == "live"
        has_tn = sec.has("tradernet_public_key") and sec.has("tradernet_private_key")
        self.status["notice"] = ""
        if want_live and not has_tn:
            self.status["notice"] = ("Live data needs Tradernet API keys; running on demo data. "
                                     "Add keys in Settings > Accounts.")
        if want_live and has_tn:
            self.market = None
            self.data = TradernetData(sec.get("tradernet_public_key"),
                                      sec.get("tradernet_private_key"))
            self.status["market"]["label"] = "Tradernet"
        else:
            self.data = None
            self.market = DemoMarket()
            self.market.sync(s.keywords())
            self.status["market"]["label"] = "Demo market"
        if self.settings["execution_mode"] == "live" and (self.demo or not has_tn):
            self.settings.set_path("execution_mode", "paper")
        self.sources = build_sources(s, sec, data=self.data, demo_market=self.market)
        mode = "demo" if self.demo else "paper"
        self.paper = PaperBroker(self.store, s.get("paper.starting_cash"), mode=mode)
        key = sec.get("anthropic_api_key")
        if self.demo:
            self.analyst = DemoAnalyst()
        elif key:
            self.analyst = ClaudeAnalyst(key, s, self.store,
                                         on_usage=lambda: self.bus.publish("usage", self.usage()))
        else:
            self.analyst = None

    def _guard(self, name, fn):
        def run():
            while not self._stop.is_set():
                try:
                    fn()
                    return
                except Exception:
                    log.exception("%s loop crashed; restarting it in 5s", name)
                    self._stop.wait(5)
        return run

    def _sleep(self, seconds: float, wake: str | None = None):
        ev = self._wake.get(wake) if wake else None
        if ev:
            ev.wait(timeout=max(0.05, seconds))
            ev.clear()
        else:
            self._stop.wait(timeout=max(0.05, seconds))

    def _log_err(self, key: str, msg: str, *args):
        """Log a recurring error at most once a minute."""
        now = time.time()
        if now - self._err_logged.get(key, 0) > 60:
            self._err_logged[key] = now
            log.warning(msg, *args)

    def wake(self, what: str):
        if what in self._wake:
            self._wake[what].set()

    # ---- loops ---------------------------------------------------------------------------
    def _quotes_loop(self):
        last_status = 0.0
        while not self._stop.is_set():
            t0 = time.time()
            try:
                tickers = self.settings.tickers
                if self.demo:
                    self.market.sync(self.settings.keywords())
                    self.market.step()
                    q = self.market.quotes(tickers)
                else:
                    q = self.data.quotes(tickers)
                with self._lock:
                    self.quotes.update(q)
                self.status["market"].update(ok=True, last=time.time(), error="")
                self.bus.publish("quotes", q)
                for snap in self.snaps.values():   # keep snapshot prices live
                    qq = q.get(snap["ticker"])
                    if qq and qq.get("last"):
                        snap["live"] = qq["last"]
                fills = self.paper.on_quotes(q) if self.paper else []
                for f in fills:
                    self._on_trade(f)
                self.bus.publish("account", self.account())
                if fills:
                    self.bus.publish("positions", self.positions_view())
                    self.bus.publish("orders", self.orders_view())
            except Exception as e:
                self.status["market"].update(ok=False, last=time.time(), error=str(e)[:200])
                self._log_err("quotes", "Market data error: %s", e)
            if time.time() - last_status > 3:
                self.bus.publish("status", self.status_view())
                last_status = time.time()
            self._sleep(self.intervals()["quotes_sec"] - (time.time() - t0))

    def _news_loop(self):
        while not self._stop.is_set():
            keywords = self.settings.keywords()
            for src in list(self.sources):
                if self._stop.is_set() or not src.due():
                    continue
                for item in src.poll(keywords):
                    if not self.store.add_news(item):
                        continue
                    self.bus.publish("news", item.to_dict())
                    self._maybe_triage(item)
            self.status["news"].update(last=time.time(),
                                       next=time.time() + self.intervals()["news_sec"])
            self._sleep(self.intervals()["news_sec"], "news")

    def _maybe_triage(self, item: NewsItem):
        age_min = (datetime.now(timezone.utc) - item.published).total_seconds() / 60
        if (not item.tickers or age_min > self.settings.get("risk.max_news_age_min")
                or not self.settings["ai_enabled"] or self.analyst is None):
            return
        try:
            score, ticker = self.analyst.triage(item, self.settings.tickers)
        except BudgetExceeded:
            self._log_err("budget", "Daily AI budget reached; news triage paused until tomorrow")
            return
        except Exception as e:
            self._log_err("triage", "News triage failed: %s", e)
            return
        self.store.set_news_score(item.id, score, ticker)
        self.bus.publish("news_score", {"id": item.id, "score": score, "ticker": ticker})
        if score >= self.settings.get("ai.min_triage_score") and ticker in item.tickers:
            cand = Candidate(ticker, "EITHER", "news", score / 10, item.headline)
            self.evaluate(ticker, [cand], trigger=item)

    def _scan_loop(self):
        self._stop.wait(2 if self.demo else 5)   # let quotes arrive first
        while not self._stop.is_set():
            self.scan()
            self._sleep(self.intervals()["scan_min"] * 60, "scan")

    def scan(self):
        st = self.status["scan"]
        st.update(running=True, error="")
        self.bus.publish("status", self.status_view())
        enabled = self.settings.get("rules.enabled")
        positions = self.positions()
        for ticker in self.settings.tickers:
            if self._stop.is_set():
                break
            try:
                snap = self.snapshot(ticker, fresh=True)
                if snap is None:
                    continue
                held = positions.get(ticker, 0) > 0
                cands = strategies.scan(snap, held, enabled)
                entry = {"ticker": ticker, "snap": snap.to_dict(), "at": time.time(),
                         "diag": strategies.diagnose(snap, held, enabled),
                         "signals": [c.strategy for c in cands], "live": snap.last}
                with self._lock:
                    self.snaps[ticker] = entry
                self.bus.publish("snapshot", entry)
                if cands:
                    self.evaluate(ticker, cands)
            except Exception as e:
                st["error"] = f"{ticker}: {e}"[:200]
                self._log_err(f"scan-{ticker}", "Scan failed for %s: %s", ticker, e)
        st.update(running=False, last=time.time(),
                  next=time.time() + self.intervals()["scan_min"] * 60)
        self.bus.publish("status", self.status_view())

    def _account_loop(self):
        while not self._stop.is_set():
            try:
                acct = self.data.account()
                orders = self.data.open_orders()
                with self._lock:
                    self.broker_account, self.broker_orders = acct, orders
                self.status["account"].update(ok=True, last=time.time(), error="")
                if self.acct() == "live":
                    self._protect_live(acct)
                    self.bus.publish("positions", self.positions_view())
                    self.bus.publish("orders", self.orders_view())
                self.bus.publish("broker", self.broker_view())
            except Exception as e:
                self.status["account"].update(ok=False, last=time.time(), error=str(e)[:200])
                self._log_err("account", "Account sync error: %s", e)
            self._sleep(self.intervals()["account_sec"], "account")

    def _protect_live(self, acct: dict):
        held = {p["ticker"]: p["qty"] for p in acct.get("positions", [])}
        for t, b in self.store.book("live").items():
            if t not in held:
                continue   # entry not filled yet (or already closed)
            if not b["protected"] and (b["stop"] or b["target"]):
                try:
                    self.data.protect(t, b["stop"], b["target"])
                    self.store.book_mark_protected(t, "live")
                    log.info("Attached stop %s / target %s to %s", b["stop"], b["target"], t)
                except Exception as e:
                    self._log_err(f"protect-{t}", "Could not attach stop/target to %s: %s", t, e)
        for t in list(self.store.book("live")):
            if t not in held and time.time() - self.store.book("live")[t]["opened"] > 86400:
                self.store.book_remove(t, "live")   # entry never filled or position closed

    # ---- market data helpers ---------------------------------------------------------------
    def daily(self, ticker: str, fresh: bool = False) -> Candles:
        if self.demo:
            return self.market.candles(ticker, "1D")
        cached = self._daily.get(ticker)
        if cached and not fresh and time.time() - cached[0] < 900:
            return cached[1]
        if cached and fresh and time.time() - cached[0] < 300:
            return cached[1]
        d = self.data.candles(ticker, "1D", days=450)
        self._daily[ticker] = (time.time(), d)
        return d

    def snapshot(self, ticker: str, fresh: bool = False):
        last = (self.quotes.get(ticker) or {}).get("last")
        return snapshot(ticker, self.daily(ticker, fresh=fresh), last=last)

    def candles(self, ticker: str, tf: str) -> Candles:
        if tf not in TIMEFRAMES:
            raise EngineError(f"Unknown timeframe {tf}")
        if self.demo:
            return self.market.candles(ticker, tf)
        key = (ticker, tf)
        cached = self._chart_cache.get(key)
        if cached and time.time() - cached[0] < 30:
            return cached[1]
        c = self.data.candles(ticker, tf)
        self._chart_cache[key] = (time.time(), c)
        return c

    # ---- decision pipeline -------------------------------------------------------------------
    def evaluate(self, ticker: str, cands: list[Candidate], trigger: NewsItem | None = None):
        sig_key = (ticker, tuple(sorted(c.strategy for c in cands)))
        cooldown = self.settings.get("risk.ticker_cooldown_min") * 60
        if trigger is None and time.time() - self._last_review.get(sig_key, 0) < cooldown:
            return   # same rule signal reviewed recently; don't pay for it again
        with self._eval_lock:
            self._last_review[sig_key] = time.time()
            snap = self.snapshot(ticker)
            acct = self.acct()
            dec = {"ts": time.time(), "ticker": ticker,
                   "trigger": f"news: {trigger.headline}" if trigger else "rules",
                   "candidates": [c.to_dict() for c in cands],
                   "snapshot": snap.to_dict() if snap else None,
                   "headlines": [], "verdict": None, "approved": False, "reason": "",
                   "order": None,
                   "mode": acct if acct != "off" else ("demo-off" if self.demo else "off")}
            order = None
            if snap is None:
                dec["reason"] = "not enough price history"
            elif self.analyst is None:
                dec["reason"] = "AI review unavailable: add your Anthropic API key in Settings"
            elif not self.settings["ai_enabled"]:
                dec["reason"] = "AI review is off"
            elif self.halted:
                dec["reason"] = "trading halted (kill switch); idea not reviewed"
            else:
                positions = self.positions()
                headlines = self.store.headlines_for(ticker, demo=self.demo)
                dec["headlines"] = headlines
                try:
                    sig = self.analyst.review(ticker, cands, snap, positions.get(ticker, 0),
                                              headlines, trigger)
                    dec["verdict"] = sig.to_dict()
                    order, reason = risk.check(
                        sig, cands, snap, positions, risk=self.settings.get("risk"),
                        min_confidence=self.settings.get("ai.min_confidence"),
                        watchlist=self.settings.tickers, day_pnl=self.account()["day_pnl"],
                        last_trade_ts=self.store.last_trade_time(ticker),
                        halted=self.halted, mentioned=trigger.tickers if trigger else ())
                    dec["reason"] = reason
                    if order is not None:
                        dec["order"] = order.to_dict()
                        dec["approved"] = True
                        if acct == "off":
                            dec["reason"] = "approved, but execution is off (signals only)"
                except BudgetExceeded:
                    dec["reason"] = "daily AI budget reached"
                except Exception as e:
                    dec["reason"] = f"review failed: {str(e)[:160]}"
                    log.warning("Review failed for %s: %s", ticker, e)
            dec["id"] = self.store.add_decision(dec)
            log.info("%s %s via %s: %s (%s)", "APPROVED" if dec["approved"] else "Rejected",
                     ticker, ",".join(c.strategy for c in cands),
                     (dec["verdict"] or {}).get("action", "-"), dec["reason"])
            if order is not None and acct != "off":
                try:
                    self._submit(order, "auto")
                except Exception as e:
                    dec["reason"] = f"order failed: {str(e)[:160]}"
                    self.store.set_decision_order(dec["id"], dec["order"], dec["reason"])
                    log.error("Order for %s failed: %s", ticker, e)
            self.bus.publish("decision", self._decision_view(dec))

    def _submit(self, order: risk.Order, source: str) -> dict:
        acct = self.acct()
        if acct == "off":
            raise EngineError("Execution is off. Choose Paper or Live in the Account panel.")
        quote = self.quotes.get(order.ticker)
        if acct in ("demo", "paper"):
            row, fills = self.paper.place(order.ticker, order.side, order.qty, order.limit,
                                          source, order.stop, order.target, quote=quote)
            if row["status"] == "rejected":
                raise EngineError(f"Paper order rejected: {row['note']}")
            for f in fills:
                self._on_trade(f)
            if not fills:
                self.toast("info", f"{order.side} {order.qty} {order.ticker} @ {order.limit} "
                                   f"working ({acct})")
        else:  # live
            res = self.data.place(order.ticker, order.side, order.qty, order.limit)
            ref = ""
            if isinstance(res, dict):
                inner = res.get("result") if isinstance(res.get("result"), dict) else {}
                ref = str(res.get("order_id") or inner.get("order_id") or "")
            row = {"ticker": order.ticker, "side": order.side, "qty": order.qty,
                   "limit": order.limit, "status": "submitted", "source": source,
                   "stop": order.stop, "target": order.target, "mode": "live",
                   "broker_ref": ref}
            row["id"] = self.store.add_order(row)
            if order.side == "BUY":
                self.store.book_add(order.ticker, "live", order.qty, order.limit,
                                    order.stop, order.target)
            else:
                self.store.book_remove(order.ticker, "live")
            log.warning("LIVE order sent: %s %s %s @ %s (ref %s)", order.side, order.qty,
                        order.ticker, order.limit, ref or "?")
            self.toast("live", f"LIVE {order.side} {order.qty} {order.ticker} @ {order.limit} sent")
            self.wake("account")
        self.bus.publish("orders", self.orders_view())
        self.bus.publish("positions", self.positions_view())
        return row

    def _on_trade(self, t: dict):
        self.bus.publish("trade", t)
        pnl = f" P&L {t['realized_pnl']:+,.2f}" if t["side"] == "SELL" else ""
        label = {"stop": "Stop hit: ", "target": "Target hit: "}.get(t["source"], "")
        self.toast("fill", f"{label}{t['side']} {t['qty']:g} {t['ticker']} @ {t['price']:,.2f} "
                           f"({t['mode']}){pnl}")
        log.info("Fill %s %s %s @ %s [%s/%s]%s", t["side"], t["qty"], t["ticker"], t["price"],
                 t["mode"], t["source"], pnl)

    def toast(self, level: str, text: str):
        self.bus.publish("toast", {"level": level, "text": text})

    # ---- user actions ------------------------------------------------------------------------
    @property
    def halted(self) -> bool:
        return bool(self.settings["halted"]) or paths.kill_file().exists()

    def manual_order(self, ticker: str, side: str, qty, limit, stop=None, target=None) -> dict:
        ticker = ticker.upper().strip()
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise EngineError("Side must be BUY or SELL.")
        try:
            qty, limit = float(qty), float(limit)
        except (TypeError, ValueError):
            raise EngineError("Quantity and limit price must be numbers.")
        last = (self.quotes.get(ticker) or {}).get("last")
        err = risk.check_manual(ticker, side, qty, limit, last, self.positions(),
                                risk=self.settings.get("risk"), halted=self.halted)
        if err:
            raise EngineError(err)
        stop = float(stop) if stop not in (None, "", 0) else None
        target = float(target) if target not in (None, "", 0) else None
        if side == "BUY" and stop is not None and stop >= limit:
            raise EngineError("Stop must be below the limit price for a buy.")
        if side == "BUY" and target is not None and target <= limit:
            raise EngineError("Target must be above the limit price for a buy.")
        order = risk.Order(ticker, side, int(qty), round(limit, 4), stop, target)
        log.info("Manual order: %s %s %s @ %s", side, int(qty), ticker, limit)
        return self._submit(order, "manual")

    def close_position(self, ticker: str) -> dict:
        qty = self.positions().get(ticker, 0)
        if qty <= 0:
            raise EngineError(f"No open position in {ticker}.")
        q = self.quotes.get(ticker) or {}
        px = q.get("bid") or q.get("last")
        if not px:
            raise EngineError(f"No price for {ticker} yet.")
        slip = self.settings.get("risk.max_slippage_pct") / 100
        order = risk.Order(ticker, "SELL", int(qty), round(px * (1 - slip), 2))
        return self._submit(order, "manual")

    def cancel_order(self, order_id) -> bool:
        acct = self.acct()
        if acct in ("demo", "paper"):
            ok = self.paper.cancel(int(order_id))
        elif acct == "live":
            self.data.cancel(order_id)
            ok = True
            self.wake("account")
        else:
            ok = False
        self.bus.publish("orders", self.orders_view())
        return ok

    def halt(self, reason: str = "kill switch") -> str:
        self.settings.set_path("halted", True)
        n = 0
        try:
            if self.paper:
                n += self.paper.cancel_all()
            if self.acct() == "live" and self.data:
                self.data.cancel_all()
        except Exception as e:
            log.error("Cancelling orders during halt failed: %s", e)
        log.warning("Trading HALTED (%s); %d working orders cancelled", reason, n)
        self.toast("warn", "Trading halted. Working orders cancelled; positions kept.")
        self.publish_all()
        return "halted"

    def resume(self) -> str:
        if paths.kill_file().exists():
            raise EngineError(f"Remove the STOP file in {paths.home()} to resume.")
        self.settings.set_path("halted", False)
        log.info("Trading resumed")
        self.publish_all()
        return "resumed"

    def set_ai(self, on: bool):
        self.settings.set_path("ai_enabled", bool(on))
        log.info("AI review %s", "enabled" if on else "disabled")
        self.publish_all()

    def set_execution(self, mode: str, confirm: str = ""):
        if mode not in ("off", "paper", "live"):
            raise EngineError("Unknown execution mode.")
        if mode == "live":
            if self.demo:
                raise EngineError("Live trading needs live data. Switch Data to Tradernet first.")
            if not (self.secrets.has("tradernet_public_key")
                    and self.secrets.has("tradernet_private_key")):
                raise EngineError("Add your Tradernet API keys first.")
            if confirm != "LIVE":
                raise EngineError("Type LIVE to confirm real-money trading.")
        self.settings.set_path("execution_mode", mode)
        (log.warning if mode == "live" else log.info)("Execution mode set to %s", mode.upper())
        self.publish_all()

    def reset_paper(self):
        mode = "demo" if self.demo else "paper"
        self.store.reset_paper(mode, self.settings.get("paper.starting_cash"))
        log.info("%s account reset to %.2f", mode, self.settings.get("paper.starting_cash"))
        self.publish_all()

    def search(self, q: str) -> list[dict]:
        if self.demo:
            return self.market.search(q)
        return self.data.search(q)

    def test_service(self, service: str) -> str:
        if service == "tradernet":
            pub, priv = (self.secrets.get("tradernet_public_key"),
                         self.secrets.get("tradernet_private_key"))
            if not (pub and priv):
                raise EngineError("Enter both Tradernet keys first.")
            return TradernetData(pub, priv).test()
        if service == "anthropic":
            key = self.secrets.get("anthropic_api_key")
            if not key:
                raise EngineError("Enter your Anthropic API key first.")
            return ClaudeAnalyst(key, self.settings, self.store).test()
        if service == "finnhub":
            import requests
            key = self.secrets.get("finnhub_api_key")
            if not key:
                raise EngineError("Enter your Finnhub key first.")
            r = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": "AAPL",
                                                                         "token": key}, timeout=10)
            if r.status_code != 200:
                raise EngineError(f"Finnhub answered {r.status_code}")
            return "Connected to Finnhub"
        raise EngineError(f"Unknown service {service}")

    # ---- backtests --------------------------------------------------------------------------------
    def start_backtest(self, tickers: list[str], years: float, cost_bps: float,
                       rules: list[str] | None) -> str:
        job_id = uuid.uuid4().hex[:8]
        job = {"id": job_id, "status": "running", "progress": 0, "tickers": tickers,
               "years": years, "cost_bps": cost_bps, "rules": rules, "results": [],
               "started": time.time(), "demo": self.demo, "error": ""}
        self.jobs[job_id] = job

        def work():
            risk_cfg = self.settings.get("risk")
            for i, t in enumerate(tickers):
                try:
                    if self.demo:
                        d = self.market.candles(t, "1D") if t in self.market.symbols else None
                        if d is None:
                            self.market.sync({**self.settings.keywords(), t: [t]})
                            d = self.market.candles(t, "1D")
                        n = int(years * 252) + 260
                        d = d.tail(n)
                    else:
                        d = self.data.candles(t, "1D", days=int(years * 365) + 400)
                    job["results"].append(bt.run(t, d, rules, risk_cfg, cost_bps / 10000))
                except Exception as e:
                    job["results"].append({"ticker": t, "error": str(e)[:200]})
                job["progress"] = (i + 1) / len(tickers)
                self.bus.publish("backtest", job)
            job["status"] = "done"
            job["finished"] = time.time()
            self.bus.publish("backtest", job)

        threading.Thread(target=work, name=f"backtest-{job_id}", daemon=True).start()
        self.bus.publish("backtest", job)
        return job_id

    # ---- views for the UI ---------------------------------------------------------------------
    def positions(self) -> dict[str, float]:
        mode = self.book_mode()
        if mode == "live":
            return {p["ticker"]: p["qty"] for p in self.broker_account.get("positions", [])}
        return {t: b["qty"] for t, b in self.store.book(mode).items()}

    def positions_view(self) -> list[dict]:
        mode = self.book_mode()
        book = self.store.book(mode)
        out = []
        if mode == "live":
            for p in self.broker_account.get("positions", []):
                b = book.get(p["ticker"], {})
                out.append({"ticker": p["ticker"], "qty": p["qty"], "entry": p["avg_price"],
                            "stop": b.get("stop"), "target": b.get("target"),
                            "opened": b.get("opened"), "protected": bool(b.get("protected")),
                            "broker_last": p["last"], "broker_pnl": p["pnl"],
                            "currency": p.get("currency"), "mode": "live"})
        else:
            for t, b in book.items():
                out.append({"ticker": t, "qty": b["qty"], "entry": b["entry"], "stop": b["stop"],
                            "target": b["target"], "opened": b["opened"],
                            "protected": True, "mode": mode})
        return out

    def orders_view(self) -> list[dict]:
        mode = self.book_mode()
        rows = [o for o in self.store.recent_orders(100) if o["mode"] == mode]
        if mode == "live":
            working = [dict(o, id=o["id"], cancel_ref=o["id"], status=o["status"])
                       for o in self.broker_orders]
            return working + [o for o in rows if o["status"] != "working"]
        return rows

    def account(self) -> dict:
        mode = self.book_mode()
        if mode == "live":
            a = dict(self.broker_account) or {"equity": 0.0, "cash_total": 0.0, "invested": 0.0,
                                              "unrealized": 0.0}
            a.pop("positions", None)
        else:
            a = self.paper.account(self.quotes) if self.paper else {}
        eq = a.get("equity") or 0.0
        start = self.store.day_start_equity(mode, eq) if eq else eq
        a["day_pnl"] = eq - start if eq else 0.0
        a["mode"] = mode
        a["open_positions"] = sum(1 for q in self.positions().values() if q > 0)
        return a

    def broker_view(self) -> dict:
        a = dict(self.broker_account)
        return {"ok": self.status["account"]["ok"], "equity": a.get("equity"),
                "cash": a.get("cash", []), "positions": a.get("positions", []),
                "orders": self.broker_orders, "last": self.status["account"]["last"]}

    def usage(self) -> dict:
        u = self.store.usage_today()
        u["budget"] = self.settings.get("ai.daily_budget_usd")
        u["demo"] = self.demo
        u["history"] = self.store.usage_days(30)
        return u

    def status_view(self) -> dict:
        intervals = self.intervals()
        return {
            **{k: v for k, v in self.status.items()},
            "sources": [{"name": s.name, "label": s.label, **s.status} for s in self.sources],
            "ai": {"available": self.analyst is not None,
                   "demo": bool(self.analyst and self.analyst.demo),
                   "models": self.settings.get("models"),
                   **(self.analyst.status if self.analyst else {"ok": None, "error":
                                                                 "No Anthropic API key"})},
            "intervals": intervals,
            "uptime": time.time() - self.started,
        }

    def app_view(self) -> dict:
        return {"name": APP_NAME, "version": __version__, "shell": self.shell,
                "demo": self.demo, "data_mode": self.settings["data_mode"],
                "execution_mode": self.settings["execution_mode"], "acct": self.acct(),
                "book_mode": self.book_mode(), "halted": self.halted,
                "kill_file": str(paths.kill_file()), "ai_enabled": self.settings["ai_enabled"],
                "onboarded": self.settings["onboarded"], "home": str(paths.home()),
                "secrets_backend": self.secrets.backend, "started": self.started}

    @staticmethod
    def _decision_view(d: dict) -> dict:
        d = dict(d)
        d.pop("headlines", None)
        return d

    def ticker_detail(self, ticker: str) -> dict:
        snap_entry = self.snaps.get(ticker)
        snap = None
        try:
            snap = self.snapshot(ticker)
        except Exception as e:
            self._log_err(f"detail-{ticker}", "Snapshot for %s failed: %s", ticker, e)
        held = self.positions().get(ticker, 0)
        enabled = self.settings.get("rules.enabled")
        suggestion = None
        if snap:
            qty, stop, target = risk.size_entry(snap.last, snap.atr14, self.settings.get("risk"))
            suggestion = {"qty": qty, "stop": stop, "target": target,
                          "risk_usd": round(qty * (snap.last - stop), 2) if qty else 0,
                          "value": round(qty * snap.last, 2)}
        decisions = [self._decision_view(d) for d in self.store.recent_decisions(300, demo=self.demo)
                     if d["ticker"] == ticker][:8]
        pos = next((p for p in self.positions_view() if p["ticker"] == ticker), None)
        return {
            "ticker": ticker, "quote": self.quotes.get(ticker),
            "snapshot": snap.to_dict() if snap else None,
            "diagnostics": strategies.diagnose(snap, held > 0, enabled) if snap else [],
            "signals": (snap_entry or {}).get("signals", []),
            "suggestion": suggestion, "position": pos, "decisions": decisions,
            "headlines": self.store.headlines_for(ticker, hours=24 * 7, limit=12, demo=self.demo),
            "trades": [t for t in self.store.trades_for(ticker) if t["mode"] == self.book_mode()],
        }

    def chart(self, ticker: str, tf: str) -> dict:
        c = self.candles(ticker, tf)
        trades = [t for t in self.store.trades_for(ticker, 500) if t["mode"] == self.book_mode()]
        pos = next((p for p in self.positions_view() if p["ticker"] == ticker), None)
        return {"ticker": ticker, "tf": tf, "bars": c.to_rows()[-1500:], "trades": trades,
                "position": pos, "demo": self.demo}

    def ui_state(self) -> dict:
        with self._lock:
            quotes = dict(self.quotes)
            snaps = dict(self.snaps)
        from .. import logs
        return {
            "app": self.app_view(), "status": self.status_view(),
            "settings": self.settings_view(), "quotes": quotes, "snapshots": snaps,
            "positions": self.positions_view(), "orders": self.orders_view(),
            "account": self.account(), "broker": self.broker_view(),
            "decisions": [self._decision_view(d) for d in
                          self.store.recent_decisions(150, demo=self.demo)],
            "news": self.store.recent_news(200, demo=self.demo),
            "trades": [t for t in self.store.recent_trades(200) if t["mode"] == self.book_mode()],
            "usage": self.usage(), "log": logs.RING.tail(400),
            "jobs": list(self.jobs.values())[-5:],
        }

    def settings_view(self) -> dict:
        s = self.settings.snapshot()
        s["secrets"] = self.secrets.status()
        s["secrets_backend"] = self.secrets.backend
        return s

    def publish_all(self):
        self.bus.publish("app", self.app_view())
        self.bus.publish("status", self.status_view())
        self.bus.publish("account", self.account())
        self.bus.publish("positions", self.positions_view())
        self.bus.publish("orders", self.orders_view())
        self.bus.publish("settings", self.settings_view())
