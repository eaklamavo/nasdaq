"""Nasdaq-100 constituents and weights (Invesco QQQ holdings, Wikipedia fallback)."""
from __future__ import annotations

import io

import httpx
import pandas as pd

from ..cache import ttl_cache
from ._util import safe

INVESCO_URL = (
    "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/QQQ/holdings/fund"
    "?idType=ticker&interval=monthly&productType=ETF"
)
HEADERS = {"User-Agent": "Mozilla/5.0 ndx-agent"}


def _from_invesco() -> dict:
    r = httpx.get(INVESCO_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    rows = [
        {"ticker": h["ticker"], "name": h["issuerName"], "weight_pct": h["percentageOfTotalNetAssets"]}
        for h in data["holdings"]
        if h.get("securityTypeCode") == "COM" and h.get("ticker")
    ]
    return {"source": "invesco_qqq", "as_of": data.get("effectiveBusinessDate"), "holdings": rows}


def _from_wikipedia() -> dict:
    r = httpx.get("https://en.wikipedia.org/wiki/Nasdaq-100", headers=HEADERS, timeout=30, follow_redirects=True)
    r.raise_for_status()
    for t in pd.read_html(io.StringIO(r.text)):
        if "Ticker" in t.columns:
            rows = [{"ticker": row["Ticker"], "name": row["Company"], "weight_pct": None} for _, row in t.iterrows()]
            return {"source": "wikipedia (no weights)", "as_of": None, "holdings": rows}
    raise ValueError("constituents table not found")


@ttl_cache(6 * 3600)
def _load() -> dict:
    try:
        d = _from_invesco()
    except Exception:
        d = _from_wikipedia()
    d["holdings"].sort(key=lambda x: x["weight_pct"] or 0, reverse=True)
    return d


@safe
def get_constituents() -> dict:
    """All Nasdaq-100 constituents with index-proxy weights (QQQ holdings), largest first."""
    d = _load()
    return {**d, "count": len(d["holdings"])}


@safe
def get_top_weights(n: int = 20) -> dict:
    """Top-N constituents by weight and their combined share of the index."""
    d = _load()
    top = d["holdings"][:n]
    return {
        "source": d["source"],
        "as_of": d["as_of"],
        "top": top,
        "combined_weight_pct": round(sum(h["weight_pct"] or 0 for h in top), 2),
    }


def top_holdings(n: int) -> list[dict]:
    """Internal (non-tool) accessor used by aggregation."""
    return _load()["holdings"][:n]
