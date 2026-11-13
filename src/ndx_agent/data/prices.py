"""Prices (yfinance) and locally computed technical indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

from ..cache import ttl_cache
from ._util import safe

INDEX_TICKER = "^NDX"


@ttl_cache(900)
def _history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"no price data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Internal accessor returning a DataFrame."""
    return _history(ticker, period)


@safe
def get_ohlcv(ticker: str = INDEX_TICKER, period: str = "3mo", last_n: int = 30) -> dict:
    """Daily OHLCV for a ticker (default ^NDX). Returns the last `last_n` bars."""
    df = _history(ticker, period).tail(last_n).round(2)
    return {"ticker": ticker, "bars": df}


@safe
def get_index_snapshot() -> dict:
    """Latest level, 1d/5d/20d/60d returns, and position vs 52-week range for ^NDX."""
    df = _history(INDEX_TICKER, "1y")
    c = df["Close"]

    def ret(n: int):
        return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None

    return {
        "ticker": INDEX_TICKER,
        "as_of": df.index[-1],
        "last": float(c.iloc[-1]),
        "ret_1d": ret(1),
        "ret_5d": ret(5),
        "ret_20d": ret(20),
        "ret_60d": ret(60),
        "high_52w": float(df["High"].max()),
        "low_52w": float(df["Low"].min()),
        "pct_below_52w_high": float(c.iloc[-1] / df["High"].max() - 1),
    }


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + up / down.replace(0, np.nan))
    return out.mask((down == 0) & (up > 0), 100.0)  # no losses in window -> RSI 100


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    sig = line.ewm(span=9, adjust=False).mean()
    return line, sig, line - sig


def indicators_from_df(df: pd.DataFrame) -> dict:
    c = df["Close"]
    line, sig, hist = macd(c)
    sma = {n: float(c.rolling(n).mean().iloc[-1]) for n in (20, 50, 200) if len(c) >= n}
    last = float(c.iloc[-1])
    a = float(atr(df).iloc[-1])
    if 50 in sma and 200 in sma:
        trend = "up" if last > sma[50] > sma[200] else ("down" if last < sma[50] < sma[200] else "mixed")
    else:
        trend = "unknown"
    return {
        "last": last,
        "rsi14": float(rsi(c).iloc[-1]),
        "macd": float(line.iloc[-1]),
        "macd_signal": float(sig.iloc[-1]),
        "macd_hist": float(hist.iloc[-1]),
        "sma": sma,
        "atr14": a,
        "atr_pct": a / last,
        "trend_vs_ma": trend,
        "dist_from_sma50_pct": (last / sma[50] - 1) if 50 in sma else None,
        "realized_vol_20d_ann": float(c.pct_change().tail(20).std() * np.sqrt(252)),
    }


@safe
def compute_indicators(ticker: str = INDEX_TICKER) -> dict:
    """RSI, MACD, SMA20/50/200, ATR, trend regime and realised volatility for a ticker."""
    return {"ticker": ticker, **indicators_from_df(_history(ticker, "1y"))}


@safe
def get_breadth(top_n: int = 30) -> dict:
    """Share of the top-N constituents trading above their 50-day and 200-day SMA."""
    from .constituents import top_holdings

    tickers = [h["ticker"] for h in top_holdings(top_n)]
    above50 = above200 = n = 0
    for t in tickers:
        try:
            c = _history(t, "1y")["Close"]
        except Exception:
            continue
        n += 1
        above50 += bool(c.iloc[-1] > c.rolling(50).mean().iloc[-1])
        above200 += bool(len(c) >= 200 and c.iloc[-1] > c.rolling(200).mean().iloc[-1])
    return {"sampled": n, "pct_above_sma50": above50 / n if n else None, "pct_above_sma200": above200 / n if n else None}
