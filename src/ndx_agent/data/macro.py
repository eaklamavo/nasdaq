"""Macro series from FRED (public CSV endpoint; no API key required)."""
from __future__ import annotations

import io

import httpx
import pandas as pd

from ..cache import ttl_cache
from ._util import safe

SERIES = {
    "DGS10": "10Y Treasury yield (%)",
    "DGS2": "2Y Treasury yield (%)",
    "T10Y2Y": "10Y-2Y spread (%)",
    "VIXCLS": "CBOE VIX",
    "FEDFUNDS": "Effective fed funds rate (%)",
    "CPIAUCSL": "CPI all urban consumers (index)",
    "UNRATE": "Unemployment rate (%)",
    "DTWEXBGS": "Broad USD index",
}


@ttl_cache(3600)
def _series(series_id: str) -> pd.Series:
    r = httpx.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id}, timeout=30,
                  follow_redirects=True)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna()


@safe
def get_macro_series(series_id: str, last_n: int = 10) -> dict:
    """Recent values and changes for a FRED series. Known ids: DGS10, DGS2, T10Y2Y, VIXCLS, FEDFUNDS, CPIAUCSL, UNRATE, DTWEXBGS."""
    s = _series(series_id.upper())
    return {
        "series_id": series_id.upper(),
        "description": SERIES.get(series_id.upper(), ""),
        "latest": float(s.iloc[-1]),
        "latest_date": s.index[-1],
        "change_5_obs": float(s.iloc[-1] - s.iloc[-6]) if len(s) > 5 else None,
        "change_20_obs": float(s.iloc[-1] - s.iloc[-21]) if len(s) > 20 else None,
        "recent": [{"date": d.date().isoformat(), "value": float(v)} for d, v in s.tail(last_n).items()],
    }


@safe
def get_macro_dashboard() -> dict:
    """One-call macro summary: yields, curve, VIX, policy rate, CPI YoY and unemployment."""
    out: dict = {}
    for sid in ("DGS10", "DGS2", "T10Y2Y", "VIXCLS", "FEDFUNDS", "UNRATE", "DTWEXBGS"):
        s = _series(sid)
        out[sid] = {"latest": float(s.iloc[-1]), "date": s.index[-1].date().isoformat(),
                    "chg_20_obs": float(s.iloc[-1] - s.iloc[-21]) if len(s) > 20 else None}
    cpi = _series("CPIAUCSL")
    out["CPI_YoY_pct"] = float((cpi.iloc[-1] / cpi.iloc[-13] - 1) * 100) if len(cpi) > 12 else None
    return out
