"""SQLite persistence. One connection guarded by a lock; times are epoch seconds."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY, published REAL, received REAL, source TEXT, headline TEXT,
  summary TEXT, url TEXT, tickers TEXT, score INTEGER, scored_ticker TEXT);
CREATE INDEX IF NOT EXISTS news_pub ON news(published);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, ticker TEXT, trigger TEXT,
  candidates TEXT, snapshot TEXT, headlines TEXT, verdict TEXT, approved INTEGER,
  reason TEXT, order_json TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, ticker TEXT, side TEXT, qty REAL,
  price REAL, mode TEXT, source TEXT, ref TEXT, realized_pnl REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS book (
  ticker TEXT, mode TEXT, qty REAL, entry REAL, stop REAL, target REAL, opened REAL,
  protected INTEGER DEFAULT 0, PRIMARY KEY (ticker, mode));
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, ticker TEXT, side TEXT, qty REAL,
  limit_price REAL, status TEXT, filled_price REAL, filled_ts REAL, source TEXT,
  stop REAL, target REAL, mode TEXT, broker_ref TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS paper_account (
  mode TEXT PRIMARY KEY, cash REAL, starting_cash REAL, created REAL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS usage (
  day TEXT, model TEXT, calls INTEGER, input_tokens INTEGER, output_tokens INTEGER,
  cost REAL, PRIMARY KEY (day, model));
"""


def today_start() -> float:
    now = datetime.now()
    return datetime(now.year, now.month, now.day).timestamp()


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _row(cur, row):
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


class Store:
    def __init__(self, path):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = _row
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self.db.commit()
        self.prune()

    def _q(self, sql, args=()):
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def _x(self, sql, args=()):
        with self._lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def prune(self, days: int = 45):
        cutoff = time.time() - days * 86400
        self._x("DELETE FROM news WHERE received < ?", (cutoff,))

    # ---- news ----------------------------------------------------------------
    def add_news(self, item) -> bool:
        """Returns True if the item is new."""
        cur = self._x(
            "INSERT OR IGNORE INTO news (id, published, received, source, headline, summary,"
            " url, tickers) VALUES (?,?,?,?,?,?,?,?)",
            (item.id, item.published.timestamp(), time.time(), item.source, item.headline,
             item.summary, item.url, ("," + ",".join(item.tickers) + ",") if item.tickers else ""))
        return cur.rowcount == 1

    def set_news_score(self, news_id: str, score: int, ticker: str):
        self._x("UPDATE news SET score=?, scored_ticker=? WHERE id=?", (score, ticker, news_id))

    def recent_news(self, limit: int = 150, demo: bool = True) -> list[dict]:
        """demo=False hides the simulated demo feed (live-data mode)."""
        where = "" if demo else "WHERE source != 'demo'"
        rows = self._q(f"SELECT * FROM news {where} ORDER BY published DESC LIMIT ?", (limit,))
        for r in rows:
            r["tickers"] = [t for t in (r["tickers"] or "").split(",") if t]
        return rows

    def headlines_for(self, ticker: str, hours: int = 48, limit: int = 15,
                      demo: bool = False) -> list[str]:
        """Recent headlines for a ticker. Demo-feed stories only when demo=True, so a live
        review never sees simulated news."""
        since = time.time() - hours * 3600
        src = "source = 'demo'" if demo else "source != 'demo'"
        rows = self._q(
            f"SELECT published, source, headline FROM news WHERE tickers LIKE ? AND published > ?"
            f" AND {src} ORDER BY published DESC LIMIT ?", (f"%,{ticker},%", since, limit))
        return [f"{datetime.fromtimestamp(r['published']):%Y-%m-%d %H:%M} [{r['source']}] "
                f"{r['headline']}" for r in rows]

    # ---- decisions -------------------------------------------------------------
    def add_decision(self, d: dict) -> int:
        cur = self._x(
            "INSERT INTO decisions (ts, ticker, trigger, candidates, snapshot, headlines, verdict,"
            " approved, reason, order_json, mode) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (d["ts"], d["ticker"], d["trigger"], json.dumps(d.get("candidates")),
             json.dumps(d.get("snapshot")), json.dumps(d.get("headlines")),
             json.dumps(d.get("verdict")), int(bool(d.get("approved"))), d.get("reason", ""),
             json.dumps(d.get("order")), d.get("mode", "")))
        return cur.lastrowid

    def set_decision_order(self, decision_id: int, order: dict | None, reason: str | None = None):
        if reason is None:
            self._x("UPDATE decisions SET order_json=? WHERE id=?", (json.dumps(order), decision_id))
        else:
            self._x("UPDATE decisions SET order_json=?, reason=?, approved=? WHERE id=?",
                    (json.dumps(order), reason, int(order is not None), decision_id))

    def recent_decisions(self, limit: int = 120, demo: bool | None = None) -> list[dict]:
        """demo=True: only decisions made on simulated data; False: only real-data ones."""
        where = ""
        if demo is True:
            where = "WHERE mode LIKE 'demo%'"
        elif demo is False:
            where = "WHERE mode NOT LIKE 'demo%'"
        return [self._decode(r) for r in
                self._q(f"SELECT * FROM decisions {where} ORDER BY id DESC LIMIT ?", (limit,))]

    def decision(self, decision_id: int) -> dict | None:
        rows = self._q("SELECT * FROM decisions WHERE id=?", (decision_id,))
        return self._decode(rows[0]) if rows else None

    @staticmethod
    def _decode(r: dict) -> dict:
        for k in ("candidates", "snapshot", "headlines", "verdict", "order_json"):
            try:
                r[k] = json.loads(r[k]) if r[k] else None
            except (TypeError, json.JSONDecodeError):
                r[k] = None
        r["order"] = r.pop("order_json")
        r["approved"] = bool(r["approved"])
        return r

    # ---- trades ----------------------------------------------------------------
    def add_trade(self, ticker, side, qty, price, mode, source, ref="", pnl=0.0) -> dict:
        ts = time.time()
        cur = self._x("INSERT INTO trades (ts, ticker, side, qty, price, mode, source, ref,"
                      " realized_pnl) VALUES (?,?,?,?,?,?,?,?,?)",
                      (ts, ticker, side, qty, price, mode, source, str(ref), pnl))
        return {"id": cur.lastrowid, "ts": ts, "ticker": ticker, "side": side, "qty": qty,
                "price": price, "mode": mode, "source": source, "ref": str(ref),
                "realized_pnl": pnl}

    def recent_trades(self, limit: int = 150) -> list[dict]:
        return self._q("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    def trades_for(self, ticker: str, limit: int = 200) -> list[dict]:
        return self._q("SELECT * FROM trades WHERE ticker=? ORDER BY ts LIMIT ?", (ticker, limit))

    def realized_today(self, mode: str) -> float:
        r = self._q("SELECT COALESCE(SUM(realized_pnl),0) AS s FROM trades WHERE ts>=? AND mode=?",
                    (today_start(), mode))
        return float(r[0]["s"])

    def last_trade_time(self, ticker: str) -> float | None:
        r = self._q("SELECT MAX(ts) AS t FROM trades WHERE ticker=?", (ticker,))
        return r[0]["t"]

    # ---- book (positions with planned stop/target) ----------------------------
    def book(self, mode: str) -> dict[str, dict]:
        return {r["ticker"]: r for r in self._q("SELECT * FROM book WHERE mode=?", (mode,))}

    def book_add(self, ticker, mode, qty, price, stop=None, target=None):
        with self._lock:
            cur = self._q("SELECT * FROM book WHERE ticker=? AND mode=?", (ticker, mode))
            if cur:
                old = cur[0]
                new_qty = old["qty"] + qty
                entry = (old["entry"] * old["qty"] + price * qty) / new_qty
                self._x("UPDATE book SET qty=?, entry=?, stop=COALESCE(?, stop),"
                        " target=COALESCE(?, target), protected=0 WHERE ticker=? AND mode=?",
                        (new_qty, entry, stop, target, ticker, mode))
            else:
                self._x("INSERT INTO book VALUES (?,?,?,?,?,?,?,0)",
                        (ticker, mode, qty, price, stop, target, time.time()))

    def book_reduce(self, ticker, mode, qty, price) -> float:
        """Reduce a position; returns realized P&L."""
        with self._lock:
            cur = self._q("SELECT * FROM book WHERE ticker=? AND mode=?", (ticker, mode))
            if not cur:
                return 0.0
            pos = cur[0]
            qty = min(qty, pos["qty"])
            pnl = (price - pos["entry"]) * qty
            if pos["qty"] - qty <= 1e-9:
                self._x("DELETE FROM book WHERE ticker=? AND mode=?", (ticker, mode))
            else:
                self._x("UPDATE book SET qty=? WHERE ticker=? AND mode=?",
                        (pos["qty"] - qty, ticker, mode))
            return pnl

    def book_set_levels(self, ticker, mode, stop=None, target=None):
        self._x("UPDATE book SET stop=COALESCE(?, stop), target=COALESCE(?, target), protected=0"
                " WHERE ticker=? AND mode=?", (stop, target, ticker, mode))

    def book_mark_protected(self, ticker, mode):
        self._x("UPDATE book SET protected=1 WHERE ticker=? AND mode=?", (ticker, mode))

    def book_remove(self, ticker, mode):
        self._x("DELETE FROM book WHERE ticker=? AND mode=?", (ticker, mode))

    # ---- orders ----------------------------------------------------------------
    def add_order(self, o: dict) -> int:
        cur = self._x(
            "INSERT INTO orders (ts, ticker, side, qty, limit_price, status, source, stop, target,"
            " mode, broker_ref, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), o["ticker"], o["side"], o["qty"], o["limit"], o.get("status", "working"),
             o.get("source", "auto"), o.get("stop"), o.get("target"), o["mode"],
             str(o.get("broker_ref", "")), o.get("note", "")))
        return cur.lastrowid

    def update_order(self, order_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE orders SET {cols} WHERE id=?", (*fields.values(), order_id))

    def order(self, order_id: int) -> dict | None:
        r = self._q("SELECT * FROM orders WHERE id=?", (order_id,))
        return r[0] if r else None

    def working_orders(self, mode: str) -> list[dict]:
        return self._q("SELECT * FROM orders WHERE status='working' AND mode=? ORDER BY id",
                       (mode,))

    def recent_orders(self, limit: int = 100) -> list[dict]:
        return self._q("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))

    # ---- paper accounts ('demo' for simulated data, 'paper' for real data) ---------
    def paper_account(self, mode: str, starting_cash: float = 10000.0) -> dict:
        with self._lock:
            r = self._q("SELECT * FROM paper_account WHERE mode=?", (mode,))
            if not r:
                self._x("INSERT INTO paper_account VALUES (?, ?, ?, ?)",
                        (mode, starting_cash, starting_cash, time.time()))
                r = self._q("SELECT * FROM paper_account WHERE mode=?", (mode,))
            return r[0]

    def paper_cash_add(self, mode: str, delta: float):
        self._x("UPDATE paper_account SET cash = cash + ? WHERE mode=?", (delta, mode))

    def reset_paper(self, mode: str, starting_cash: float):
        with self._lock:
            self._x("DELETE FROM book WHERE mode=?", (mode,))
            self._x("UPDATE orders SET status='cancelled' WHERE mode=? AND status='working'",
                    (mode,))
            self._x("DELETE FROM trades WHERE mode=?", (mode,))
            self._x("DELETE FROM paper_account WHERE mode=?", (mode,))
            self._x("DELETE FROM kv WHERE k LIKE ?", (f"day_start:{mode}:%",))
            self._x("INSERT INTO paper_account VALUES (?, ?, ?, ?)",
                    (mode, starting_cash, starting_cash, time.time()))

    # ---- key/value -------------------------------------------------------------
    def kv_get(self, k: str, default=None):
        r = self._q("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(r[0]["v"]) if r else default

    def kv_set(self, k: str, v):
        self._x("INSERT INTO kv VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, json.dumps(v)))

    def day_start_equity(self, mode: str, equity: float) -> float:
        """Equity at the first observation today; day P&L = equity now - this."""
        key = f"day_start:{mode}:{today_key()}"
        v = self.kv_get(key)
        if v is None:
            self.kv_set(key, equity)
            return equity
        return float(v)

    # ---- AI usage --------------------------------------------------------------
    def add_usage(self, model: str, tin: int, tout: int, cost: float):
        self._x("INSERT INTO usage VALUES (?,?,1,?,?,?) ON CONFLICT(day, model) DO UPDATE SET"
                " calls=calls+1, input_tokens=input_tokens+excluded.input_tokens,"
                " output_tokens=output_tokens+excluded.output_tokens, cost=cost+excluded.cost",
                (today_key(), model, tin, tout, cost))

    def usage_today(self) -> dict:
        rows = self._q("SELECT * FROM usage WHERE day=?", (today_key(),))
        return {"models": rows, "cost": sum(r["cost"] for r in rows),
                "calls": sum(r["calls"] for r in rows)}

    def usage_days(self, days: int = 30) -> list[dict]:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        return self._q("SELECT day, SUM(cost) AS cost, SUM(calls) AS calls FROM usage"
                       " WHERE day>=? GROUP BY day ORDER BY day", (since,))
