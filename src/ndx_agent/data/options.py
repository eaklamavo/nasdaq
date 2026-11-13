"""Options-derived sentiment from the QQQ chain (put/call ratios, ATM IV, skew)."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import yfinance as yf

from ..cache import ttl_cache
from ._util import safe


@ttl_cache(900)
def _chain(symbol: str, expiry: str):
    c = yf.Ticker(symbol).option_chain(expiry)
    return c.calls, c.puts


@ttl_cache(900)
def _spot_and_expiries(symbol: str):
    t = yf.Ticker(symbol)
    return float(t.fast_info["last_price"]), list(t.options)


def _pick_expiries(expiries: list[str], min_days: int, n: int) -> list[str]:
    today = dt.date.today()
    ok = [e for e in expiries if (dt.date.fromisoformat(e) - today).days >= min_days]
    return ok[:n]


def _bs_price(kind: str, s: float, k: float, t: float, r: float, vol: float) -> float:
    d1 = (math.log(s / k) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    if kind == "call":
        return s * cdf(d1) - k * math.exp(-r * t) * cdf(d2)
    return k * math.exp(-r * t) * cdf(-d2) - s * cdf(-d1)


def implied_vol(kind: str, price: float, s: float, k: float, t: float, r: float = 0.045) -> float | None:
    """Black-Scholes implied vol by bisection; None if the price is outside no-arbitrage bounds."""
    if price <= 0 or t <= 0:
        return None
    lo, hi = 1e-4, 5.0
    if not _bs_price(kind, s, k, t, r, lo) <= price <= _bs_price(kind, s, k, t, r, hi):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if _bs_price(kind, s, k, t, r, mid) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _iv_at(df: pd.DataFrame, kind: str, strike: float, spot: float, t: float) -> tuple[float | None, str]:
    """IV of the contract nearest `strike`, from bid/ask mid when quoted, else last trade (flagged stale).
    Yahoo's own impliedVolatility field is unreliable when quotes are empty, so it is not used."""
    row = df.assign(dist=(df["strike"] - strike).abs()).sort_values("dist").iloc[0]
    if row["bid"] > 0 and row["ask"] > 0:
        return implied_vol(kind, (row["bid"] + row["ask"]) / 2, spot, row["strike"], t), "quote_mid"
    return implied_vol(kind, row["lastPrice"], spot, row["strike"], t), "last_trade_stale"


@safe
def get_put_call_ratio(symbol: str = "QQQ", expiries: int = 3) -> dict:
    """Put/call volume and open-interest ratios across the next few expiries. >1 = defensive, <0.7 = complacent."""
    spot, exps = _spot_and_expiries(symbol)
    picks = _pick_expiries(exps, 1, expiries)
    cv = pv = coi = poi = 0.0
    for e in picks:
        calls, puts = _chain(symbol, e)
        cv += calls["volume"].fillna(0).sum()
        pv += puts["volume"].fillna(0).sum()
        coi += calls["openInterest"].fillna(0).sum()
        poi += puts["openInterest"].fillna(0).sum()
    return {
        "symbol": symbol,
        "expiries": picks,
        "pc_volume_ratio": pv / cv if cv else None,
        "pc_open_interest_ratio": poi / coi if coi else None,
        "note": "volume can be near zero outside US hours; prefer the OI ratio then",
    }


@safe
def get_iv_skew(symbol: str = "QQQ") -> dict:
    """ATM implied vol and 5% OTM put-vs-call skew for the first expiry >= 14 days out.
    IV is computed locally (Black-Scholes) from OTM option prices; `data_quality` says whether
    live quotes or stale last trades were used (stale outside US market hours)."""
    spot, exps = _spot_and_expiries(symbol)
    e = _pick_expiries(exps, 14, 1)[0]
    t = max((dt.date.fromisoformat(e) - dt.date.today()).days, 1) / 365
    calls, puts = _chain(symbol, e)
    atm_c, q1 = _iv_at(calls, "call", spot, spot, t)
    atm_p, q2 = _iv_at(puts, "put", spot, spot, t)
    put_iv, q3 = _iv_at(puts, "put", spot * 0.95, spot, t)
    call_iv, q4 = _iv_at(calls, "call", spot * 1.05, spot, t)
    atm = (atm_c + atm_p) / 2 if atm_c and atm_p else (atm_c or atm_p)
    quality = "quote_mid" if {q1, q2, q3, q4} == {"quote_mid"} else "last_trade_stale"
    return {
        "symbol": symbol,
        "expiry": e,
        "spot": spot,
        "atm_iv": atm,
        "otm_put_95_iv": put_iv,
        "otm_call_105_iv": call_iv,
        "skew_put_minus_call": (put_iv - call_iv) if put_iv and call_iv else None,
        "data_quality": quality,
        "note": "higher put skew = more demand for downside protection",
    }
