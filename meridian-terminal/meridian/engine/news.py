"""News sources. Each source returns NewsItems and keeps a status record for the UI."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import requests

from .. import __version__

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    id: str
    source: str
    published: datetime
    headline: str
    summary: str = ""
    url: str = ""
    tickers: tuple[str, ...] = ()

    @staticmethod
    def make_id(*parts) -> str:
        return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {"id": self.id, "source": self.source, "published": self.published.timestamp(),
                "headline": self.headline, "summary": self.summary, "url": self.url,
                "tickers": list(self.tickers)}


def tag_tickers(text: str, keywords: dict[str, list[str]]) -> tuple[str, ...]:
    """Which watchlist tickers does this text mention (company keywords or bare symbol)?"""
    low = f" {text.lower()} "
    hits = []
    for ticker, kws in keywords.items():
        base = ticker.split(".")[0].lower()
        if any(k and k.lower() in low for k in kws) or re.search(
                rf"[\s($]{re.escape(base)}[\s),.:;]", low):
            hits.append(ticker)
    return tuple(hits)


def strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def parse_ts(v) -> datetime:
    if v in (None, ""):
        return datetime.now(timezone.utc)
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        v = float(v)
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%d.%m.%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(str(v), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@dataclass
class Source:
    name: str
    label: str
    min_interval: float = 30
    status: dict = field(default_factory=lambda: {"ok": None, "last": None, "count": 0,
                                                  "error": ""})
    _next: float = 0.0

    def due(self) -> bool:
        return time.time() >= self._next

    def poll(self, keywords: dict[str, list[str]]) -> list[NewsItem]:
        self._next = time.time() + self.min_interval
        try:
            items = self.fetch(keywords)
            self.status.update(ok=True, last=time.time(), count=len(items), error="")
            return items
        except Exception as e:
            log.warning("News source %s failed: %s", self.label, e)
            self.status.update(ok=False, last=time.time(), error=str(e)[:200])
            return []

    def fetch(self, keywords) -> list[NewsItem]:  # pragma: no cover - interface
        raise NotImplementedError


class TradernetNews(Source):
    def __init__(self, data):
        super().__init__("tradernet", "Tradernet news", min_interval=60)
        self.data = data

    def fetch(self, keywords):
        items = []
        for ticker in keywords:
            for n in self.data.news(ticker, limit=10):
                title = n.get("title") or n.get("header") or n.get("caption") or ""
                if not title:
                    continue
                body = n.get("content") or n.get("text") or n.get("description") or ""
                items.append(NewsItem(
                    id=NewsItem.make_id(self.name, n.get("id", title)), source=self.name,
                    published=parse_ts(n.get("date") or n.get("published") or n.get("time")),
                    headline=strip_html(title), summary=strip_html(body)[:1500],
                    url=n.get("url") or n.get("link") or "",
                    tickers=tuple(sorted({ticker, *tag_tickers(title, keywords)}))))
        return items


class FinnhubNews(Source):
    URL = "https://finnhub.io/api/v1/company-news"

    def __init__(self, api_key: str):
        super().__init__("finnhub", "Finnhub", min_interval=60)
        self.key = api_key

    def fetch(self, keywords):
        today = datetime.now(timezone.utc).date().isoformat()
        items = []
        for ticker in keywords:
            if not ticker.endswith(".US"):
                continue
            r = requests.get(self.URL, timeout=15, params={
                "symbol": ticker.removesuffix(".US"), "from": today, "to": today,
                "token": self.key})
            if r.status_code == 429:
                raise RuntimeError("rate limited by Finnhub")
            r.raise_for_status()
            for n in r.json()[:15]:
                items.append(NewsItem(
                    id=NewsItem.make_id(self.name, n.get("id")), source=self.name,
                    published=datetime.fromtimestamp(n.get("datetime", time.time()), timezone.utc),
                    headline=n.get("headline", ""), summary=n.get("summary", "")[:1500],
                    url=n.get("url", ""),
                    tickers=tuple(sorted({ticker, *tag_tickers(n.get("headline", ""), keywords)}))))
        return items


class RSSNews(Source):
    def __init__(self, name: str, label: str, url: str, user_agent: str, min_interval=120):
        super().__init__(name, label, min_interval=min_interval)
        self.url = url
        self.ua = user_agent

    def fetch(self, keywords):
        r = requests.get(self.url, timeout=15, headers={"User-Agent": self.ua})
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        items = []
        for e in feed.entries[:40]:
            t = e.get("published_parsed") or e.get("updated_parsed")
            ts = datetime(*t[:6], tzinfo=timezone.utc) if t else datetime.now(timezone.utc)
            title = strip_html(e.get("title", ""))
            summary = strip_html(e.get("summary", ""))[:1500]
            items.append(NewsItem(
                id=NewsItem.make_id(self.name, e.get("id") or e.get("link") or title),
                source=self.name, published=ts, headline=title, summary=summary,
                url=e.get("link", ""), tickers=tag_tickers(title + " " + summary, keywords)))
        return items


class DemoNews(Source):
    def __init__(self, market):
        super().__init__("demo", "Demo newsfeed", min_interval=2)
        self.market = market

    def fetch(self, keywords):
        items = []
        for ev in self.market.pop_events():
            pub = datetime.fromtimestamp(ev["published"], timezone.utc)
            tickers = (ev["ticker"],) if ev["ticker"] else tag_tickers(ev["headline"], keywords)
            items.append(NewsItem(id=NewsItem.make_id("demo", ev["headline"], ev["published"]),
                                  source="demo", published=pub, headline=ev["headline"],
                                  summary=ev["summary"], tickers=tickers))
        return items


def build_sources(settings, secrets, data=None, demo_market=None) -> list[Source]:
    if demo_market is not None:
        return [DemoNews(demo_market)]
    feeds = settings.get("feeds", {})
    ua = settings.get("sec_user_agent") or f"MeridianTerminal/{__version__} (personal research)"
    out: list[Source] = []
    if feeds.get("tradernet", True) and data is not None:
        out.append(TradernetNews(data))
    if feeds.get("finnhub", True) and secrets.get("finnhub_api_key"):
        out.append(FinnhubNews(secrets.get("finnhub_api_key")))
    if feeds.get("sec_8k", True):
        out.append(RSSNews("sec-8k", "SEC 8-K filings",
                           "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K"
                           "&company=&dateb=&owner=include&count=40&output=atom", ua))
    for i, f in enumerate(feeds.get("rss", []) or []):
        out.append(RSSNews(f"rss-{i}", f.get("name") or f["url"], f["url"], ua))
    return out
