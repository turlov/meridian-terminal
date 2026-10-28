"""Settings: JSON file in the data folder, merged over defaults, validated on update."""
from __future__ import annotations

import copy
import json
import threading
from typing import Any

from . import paths

RULES = ["trend_breakout", "mean_reversion", "volume_surge", "trend_exit", "overbought_exit"]
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "onboarded": False,
    "data_mode": "demo",          # demo | live  (live = Tradernet market data)
    "execution_mode": "paper",    # off | paper | live
    "halted": False,              # kill switch; persists across restarts
    "ai_enabled": True,
    "models": {"triage": "claude-haiku-5-5", "review": "claude-opus-5-5"},
    "ai": {
        "min_triage_score": 6,      # 0-10; below this the review model is never called
        "min_confidence": 0.75,     # reviewer confidence needed to trade
        "daily_budget_usd": 5.0,    # AI pauses for the day once estimated spend reaches this
    },
    # USD per million tokens [input, output]. Estimates — check anthropic.com/pricing.
    "pricing": {
        "claude-haiku-5-5": [1.0, 5.0],
        "claude-sonnet-5-5": [3.0, 15.0],
        "claude-opus-5-5": [4.0, 20.0],
        "claude-fable-5-1": [10.0, 50.0],
    },
    "watchlist": [
        {"ticker": "AAPL.US", "keywords": ["Apple"]},
        {"ticker": "NVDA.US", "keywords": ["Nvidia"]},
        {"ticker": "FRHC.US", "keywords": ["Freedom Holding", "Freedom Broker", "Turlov"]},
        {"ticker": "KSPI.US", "keywords": ["Kaspi"]},
        {"ticker": "KZAP.KZ", "keywords": ["Kazatomprom"]},
    ],
    "rules": {"enabled": list(RULES)},
    "risk": {
        "risk_per_trade_usd": 20.0,   # loss if the stop is hit
        "atr_stop_mult": 2.0,
        "atr_target_mult": 4.0,
        "max_usd_per_trade": 200.0,   # cap on position size
        "max_open_positions": 3,
        "max_daily_loss_usd": 100.0,
        "ticker_cooldown_min": 120,
        "max_slippage_pct": 0.5,
        "max_news_age_min": 15,
        "manual_max_usd": 1000.0,     # cap on manual order size
    },
    "intervals": {"quotes_sec": 5, "news_sec": 30, "scan_min": 15, "account_sec": 20},
    "feeds": {"tradernet": True, "finnhub": True, "sec_8k": True, "rss": []},
    "sec_user_agent": "",
    "paper": {"starting_cash": 10000.0},
    "server": {"host": "127.0.0.1", "port": 8765},
}

# (min, max) for numeric settings, by dotted path
BOUNDS = {
    "ai.min_triage_score": (0, 10),
    "ai.min_confidence": (0.0, 1.0),
    "ai.daily_budget_usd": (0.0, 1000.0),
    "risk.risk_per_trade_usd": (1.0, 100000.0),
    "risk.atr_stop_mult": (0.5, 10.0),
    "risk.atr_target_mult": (0.5, 20.0),
    "risk.max_usd_per_trade": (1.0, 10_000_000.0),
    "risk.max_open_positions": (1, 100),
    "risk.max_daily_loss_usd": (1.0, 10_000_000.0),
    "risk.ticker_cooldown_min": (0, 10080),
    "risk.max_slippage_pct": (0.0, 5.0),
    "risk.max_news_age_min": (1, 1440),
    "risk.manual_max_usd": (1.0, 10_000_000.0),
    "intervals.quotes_sec": (1, 300),
    "intervals.news_sec": (5, 3600),
    "intervals.scan_min": (1, 1440),
    "intervals.account_sec": (5, 3600),
    "paper.starting_cash": (100.0, 100_000_000.0),
    "server.port": (1024, 65535),
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class SettingsError(ValueError):
    pass


class Settings:
    def __init__(self, path=None):
        self.path = path or paths.settings_file()
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    # ---- persistence -------------------------------------------------------
    def load(self):
        with self._lock:
            if self.path.exists():
                try:
                    self.data = _merge(DEFAULTS, json.loads(self.path.read_text("utf-8")))
                except (OSError, json.JSONDecodeError):
                    backup = self.path.with_suffix(".broken.json")
                    self.path.replace(backup)
                    self.data = copy.deepcopy(DEFAULTS)
            return self.data

    def save(self):
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), "utf-8")
            tmp.replace(self.path)

    # ---- access ------------------------------------------------------------
    def __getitem__(self, key):
        with self._lock:
            return self.data[key]

    def get(self, dotted: str, default=None):
        with self._lock:
            node = self.data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    @property
    def tickers(self) -> list[str]:
        return [w["ticker"] for w in self.get("watchlist", [])]

    def keywords(self) -> dict[str, list[str]]:
        return {w["ticker"]: list(w.get("keywords", [])) for w in self.get("watchlist", [])}

    # ---- updates -----------------------------------------------------------
    def update(self, patch: dict) -> dict:
        """Validate and apply a partial update. Live execution can't be enabled here."""
        if "execution_mode" in patch and patch["execution_mode"] == "live":
            raise SettingsError("Live trading must be enabled with explicit confirmation.")
        with self._lock:
            new = _merge(self.data, patch)
            self._validate(new)
            self.data = new
            self.save()
            return self.snapshot()

    def set_path(self, dotted: str, value):
        """Internal setter that bypasses the live-mode guard (used by confirmed actions)."""
        with self._lock:
            node = self.data
            parts = dotted.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            self.save()

    @staticmethod
    def _validate(d: dict):
        if d["data_mode"] not in ("demo", "live"):
            raise SettingsError("data_mode must be demo or live")
        if d["execution_mode"] not in ("off", "paper", "live"):
            raise SettingsError("execution_mode must be off, paper or live")
        for role in ("triage", "review"):
            m = d["models"].get(role, "")
            if not isinstance(m, str) or not m.startswith("claude-"):
                raise SettingsError(f"Unknown model for {role}: {m!r}")
        for dotted, (lo, hi) in BOUNDS.items():
            sect, key = dotted.split(".")
            v = d[sect][key]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise SettingsError(f"{dotted} must be a number")
            if not lo <= v <= hi:
                raise SettingsError(f"{dotted} must be between {lo} and {hi}")
        wl = d["watchlist"]
        if not isinstance(wl, list) or not wl:
            raise SettingsError("Watchlist needs at least one ticker")
        seen = set()
        for w in wl:
            t = str(w.get("ticker", "")).strip().upper()
            if not t or len(t) > 32 or t in seen:
                raise SettingsError(f"Invalid or duplicate ticker: {t!r}")
            seen.add(t)
            w["ticker"] = t
            w["keywords"] = [str(k).strip() for k in w.get("keywords", []) if str(k).strip()][:10]
        for r in d["rules"]["enabled"]:
            if r not in RULES:
                raise SettingsError(f"Unknown rule {r}")
        for feed in d["feeds"].get("rss", []):
            if not str(feed.get("url", "")).startswith(("http://", "https://")):
                raise SettingsError("RSS feed URLs must start with http:// or https://")
        for model, price in d["pricing"].items():
            if (not isinstance(price, list) or len(price) != 2
                    or not all(isinstance(x, (int, float)) and x >= 0 for x in price)):
                raise SettingsError(f"Pricing for {model} must be [input, output] USD per MTok")
