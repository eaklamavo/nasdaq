"""News (Finnhub, NewsAPI, Yahoo RSS) and a simple local headline sentiment score."""
from __future__ import annotations

import datetime as dt
import re

import feedparser
import httpx

from .. import config
from ..cache import ttl_cache
from ._util import safe

POS = {"beat", "beats", "surge", "surges", "soar", "rally", "record", "upgrade", "upgrades", "growth", "strong",
       "raises", "raised", "bullish", "gain", "gains", "jump", "jumps", "outperform", "profit", "boost", "wins"}
NEG = {"miss", "misses", "plunge", "plunges", "fall", "falls", "drop", "drops", "downgrade", "downgrades", "weak",
       "cuts", "cut", "lawsuit", "probe", "investigation", "bearish", "loss", "losses", "slump", "tumble", "fear",
       "recall", "ban", "tariff", "tariffs", "warning", "warns", "layoffs", "sell-off", "selloff"}


def score_headline(text: str) -> float:
    words = re.findall(r"[a-z\-]+", text.lower())
    p = sum(w in POS for w in words)
    n = sum(w in NEG for w in words)
    return (p - n) / (p + n) if (p + n) else 0.0


@ttl_cache(1800)
def _rss(ticker: str) -> list[dict]:
    feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
    return [{"title": e.get("title", ""), "published": e.get("published", ""), "url": e.get("link", ""),
             "source": "yahoo_rss"} for e in feed.entries[:20]]


@ttl_cache(1800)
def _finnhub(ticker: str, days: int) -> list[dict]:
    to = dt.date.today()
    r = httpx.get("https://finnhub.io/api/v1/company-news",
                  params={"symbol": ticker, "from": (to - dt.timedelta(days=days)).isoformat(),
                          "to": to.isoformat(), "token": config.get("FINNHUB_API_KEY")}, timeout=30)
    r.raise_for_status()
    return [{"title": a["headline"], "published": dt.datetime.utcfromtimestamp(a["datetime"]).isoformat(),
             "url": a["url"], "source": f"finnhub:{a.get('source', '')}"} for a in r.json()[:30]]


@ttl_cache(1800)
def _newsapi(query: str, days: int) -> list[dict]:
    frm = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    r = httpx.get("https://newsapi.org/v2/everything",
                  params={"q": query, "from": frm, "sortBy": "publishedAt", "language": "en", "pageSize": 30,
                          "apiKey": config.get("NEWSAPI_KEY")}, timeout=30)
    r.raise_for_status()
    return [{"title": a["title"], "published": a["publishedAt"], "url": a["url"],
             "source": f"newsapi:{a['source']['name']}"} for a in r.json().get("articles", [])]


def _collect(ticker: str, days: int) -> list[dict]:
    items: list[dict] = []
    if ticker.upper() in ("NDX", "^NDX", "NASDAQ100", "MARKET"):
        if config.get("NEWSAPI_KEY"):
            items += _newsapi('"Nasdaq 100" OR "Nasdaq-100" OR "Nasdaq composite"', days)
        items += _rss("QQQ")
    else:
        if config.get("FINNHUB_API_KEY"):
            try:
                items += _finnhub(ticker, days)
            except Exception:
                pass
        items += _rss(ticker)
    seen, out = set(), []
    for i in items:
        k = i["title"].strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(i)
    return out


@safe
def get_news(ticker: str = "NDX", days: int = 3, limit: int = 15) -> dict:
    """Recent headlines for a ticker, or for the Nasdaq-100 overall when ticker is NDX/MARKET."""
    items = _collect(ticker, days)[:limit]
    return {"ticker": ticker, "count": len(items), "headlines": items}


@safe
def get_news_sentiment(ticker: str = "NDX", days: int = 3) -> dict:
    """Keyword-based sentiment (-1..+1) over recent headlines. Crude: use as a hint, read the headlines too."""
    items = _collect(ticker, days)
    scores = [score_headline(i["title"]) for i in items]
    avg = sum(scores) / len(scores) if scores else None
    return {
        "ticker": ticker,
        "headlines_scored": len(scores),
        "avg_sentiment": avg,
        "positive": sum(s > 0 for s in scores),
        "negative": sum(s < 0 for s in scores),
        "method": "keyword lexicon on headlines",
    }
