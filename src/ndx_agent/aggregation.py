"""Deterministic roll-up of per-constituent fundamentals/momentum into an index-level signal."""
from __future__ import annotations

from typing import Optional

import yfinance as yf

from .cache import ttl_cache
from .data import constituents, prices
from .data._util import safe

# Component weights inside each constituent's score (each component is in [-1, 1]).
W_SURPRISE, W_REVISIONS, W_MOMENTUM = 0.35, 0.35, 0.30


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def surprise_score(surprise_pcts: list[float]) -> Optional[float]:
    """Mean EPS surprise (fraction) scaled so a 10% average beat saturates at +1."""
    vals = [s for s in surprise_pcts if s is not None]
    return _clip(sum(vals) / len(vals) / 0.10) if vals else None


def revisions_score(up30: float, down30: float) -> Optional[float]:
    total = up30 + down30
    return (up30 - down30) / total if total else None


def momentum_score(ret_20d: float, above_sma50: bool) -> float:
    """20d return scaled so +/-10% saturates, nudged by position vs the 50d SMA."""
    return _clip(0.8 * _clip(ret_20d / 0.10) + (0.2 if above_sma50 else -0.2))


def combine(components: dict[str, Optional[float]]) -> Optional[float]:
    """Weighted mean over the available components (missing ones are re-normalised away)."""
    w = {"surprise": W_SURPRISE, "revisions": W_REVISIONS, "momentum": W_MOMENTUM}
    avail = {k: v for k, v in components.items() if v is not None}
    if not avail:
        return None
    return sum(w[k] * v for k, v in avail.items()) / sum(w[k] for k in avail)


def index_score(rows: list[dict]) -> dict:
    """Weight-average per-constituent scores. Rows need `weight_pct` and `score`."""
    scored = [r for r in rows if r.get("score") is not None and r.get("weight_pct")]
    wsum = sum(r["weight_pct"] for r in scored)
    if not wsum:
        return {"index_score": None, "coverage_weight_pct": 0.0}
    return {
        "index_score": sum(r["weight_pct"] * r["score"] for r in scored) / wsum,
        "coverage_weight_pct": wsum,
    }


def label(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    return "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"


@ttl_cache(6 * 3600)
def _constituent_inputs(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    surprises, up30, down30 = [], 0.0, 0.0
    try:
        surprises = [float(x) for x in t.earnings_history["surprisePercent"].dropna().tolist()]
    except Exception:
        pass
    try:
        rev = t.eps_revisions
        up30 = float(rev["upLast30days"].sum())
        down30 = float(rev["downLast30days"].sum())
    except Exception:
        pass
    return {"surprises": surprises, "up30": up30, "down30": down30}


def _score_constituent(h: dict) -> dict:
    tk = h["ticker"]
    row = {"ticker": tk, "weight_pct": h["weight_pct"]}
    comps: dict[str, Optional[float]] = {"surprise": None, "revisions": None, "momentum": None}
    try:
        inp = _constituent_inputs(tk)
        comps["surprise"] = surprise_score(inp["surprises"])
        comps["revisions"] = revisions_score(inp["up30"], inp["down30"])
        row["avg_eps_surprise_pct"] = (sum(inp["surprises"]) / len(inp["surprises"]) * 100) if inp["surprises"] else None
        row["revisions_up30"], row["revisions_down30"] = inp["up30"], inp["down30"]
    except Exception:
        pass
    try:
        c = prices.history(tk, "1y")["Close"]
        r20 = float(c.iloc[-1] / c.iloc[-21] - 1)
        comps["momentum"] = momentum_score(r20, bool(c.iloc[-1] > c.rolling(50).mean().iloc[-1]))
        row["ret_20d_pct"] = r20 * 100
    except Exception:
        pass
    row["components"] = comps
    row["score"] = combine(comps)
    return row


@safe
def compute_index_earnings_impact(top_n: int = 25) -> dict:
    """Bottom-up index signal: for the top-N weighted constituents, score EPS surprise history, analyst
    EPS revisions (30d) and 20d momentum in [-1,1], then weight-average by index weight.
    Returns the aggregate score, label, coverage, and the biggest weighted contributors/detractors."""
    rows = [_score_constituent(h) for h in constituents.top_holdings(top_n)]
    agg = index_score(rows)
    for r in rows:
        r["contribution"] = (r["score"] * r["weight_pct"] / agg["coverage_weight_pct"]) if (
            r["score"] is not None and agg["coverage_weight_pct"]) else None
    ranked = sorted((r for r in rows if r["contribution"] is not None), key=lambda r: r["contribution"])
    slim = lambda r: {k: r.get(k) for k in ("ticker", "weight_pct", "score", "contribution",  # noqa: E731
                                            "avg_eps_surprise_pct", "revisions_up30", "revisions_down30", "ret_20d_pct")}
    return {
        "top_n": top_n,
        **agg,
        "label": label(agg["index_score"]),
        "top_detractors": [slim(r) for r in ranked[:5]],
        "top_contributors": [slim(r) for r in ranked[::-1][:5]],
        "constituents": [slim(r) for r in rows],
        "method": "score = 0.35*EPS-surprise + 0.35*revisions + 0.30*momentum; index = weight-average",
    }
