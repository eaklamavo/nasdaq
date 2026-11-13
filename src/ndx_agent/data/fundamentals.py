"""EPS history, estimate revisions and earnings calendar (yfinance, Finnhub for the calendar)."""
from __future__ import annotations

import datetime as dt

import httpx
import yfinance as yf

from .. import config
from ..cache import ttl_cache
from ._util import safe


@ttl_cache(6 * 3600)
def _eps_history(ticker: str):
    return yf.Ticker(ticker).earnings_history


@ttl_cache(6 * 3600)
def _eps_revisions(ticker: str):
    return yf.Ticker(ticker).eps_revisions


@ttl_cache(6 * 3600)
def _eps_estimate(ticker: str):
    return yf.Ticker(ticker).earnings_estimate


@ttl_cache(6 * 3600)
def _calendar(ticker: str) -> dict:
    return yf.Ticker(ticker).calendar or {}


@safe
def get_eps_history(ticker: str) -> dict:
    """Last 4 quarters of actual vs estimated EPS and surprise % for a constituent."""
    df = _eps_history(ticker)
    return {"ticker": ticker, "quarters": df}


@safe
def get_estimates_revisions(ticker: str) -> dict:
    """Consensus EPS estimates (current/next quarter and year) plus analyst up/down revision counts."""
    return {
        "ticker": ticker,
        "estimates": _eps_estimate(ticker),
        "revisions": _eps_revisions(ticker),
    }


@safe
def get_earnings_calendar(ticker: str) -> dict:
    """Next earnings date and consensus for a constituent, with days until the report."""
    cal = _calendar(ticker)
    dates = cal.get("Earnings Date") or []
    nxt = dates[0] if dates else None
    days = (nxt - dt.date.today()).days if isinstance(nxt, dt.date) else None
    return {"ticker": ticker, "next_earnings_date": nxt, "days_until": days, "calendar": cal}


@ttl_cache(3600)
def _finnhub_calendar(frm: str, to: str):
    r = httpx.get(
        "https://finnhub.io/api/v1/calendar/earnings",
        params={"from": frm, "to": to, "token": config.get("FINNHUB_API_KEY")},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("earningsCalendar", [])


@safe
def get_upcoming_earnings(days_ahead: int = 14, top_n: int = 40) -> dict:
    """Top-N-weight constituents reporting earnings in the next `days_ahead` days (swing-horizon event risk)."""
    from .constituents import top_holdings

    holdings = top_holdings(top_n)
    today = dt.date.today()
    horizon = today + dt.timedelta(days=days_ahead)
    out = []
    if config.get("FINNHUB_API_KEY"):
        weights = {h["ticker"]: h for h in holdings}
        for e in _finnhub_calendar(today.isoformat(), horizon.isoformat()):
            h = weights.get(e.get("symbol"))
            if h:
                out.append({"ticker": h["ticker"], "weight_pct": h["weight_pct"], "date": e.get("date"),
                            "eps_estimate": e.get("epsEstimate")})
        source = "finnhub"
    else:
        for h in holdings:
            try:
                d = (_calendar(h["ticker"]).get("Earnings Date") or [None])[0]
            except Exception:
                continue
            if isinstance(d, dt.date) and today <= d <= horizon:
                out.append({"ticker": h["ticker"], "weight_pct": h["weight_pct"], "date": d})
        source = "yfinance"
    out.sort(key=lambda x: str(x["date"]))
    return {"source": source, "window_days": days_ahead,
            "reporting": out, "combined_weight_pct": round(sum(x["weight_pct"] or 0 for x in out), 2)}
