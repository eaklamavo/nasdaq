import math

import numpy as np
import pandas as pd
import pytest

from ndx_agent import aggregation as agg
from ndx_agent.data import options, prices
from ndx_agent.data._util import clean
from ndx_agent.data.news import score_headline
from ndx_agent.risk import build_risk_plan


def test_risk_plan_buy():
    p = build_risk_plan("BUY", entry=20000, atr=300, account_size=10000, risk_pct=1, leverage=20)
    assert p.stop_loss == 19400 and p.take_profit == 21200
    assert p.risk_amount == 100
    assert p.position_size_units == pytest.approx(100 / 600, abs=1e-4)
    # stopping out loses the planned risk
    loss = (p.entry - p.stop_loss) * p.position_size_units
    assert 99.9 <= loss <= 100  # rounded down, never above planned risk
    assert p.margin_required == pytest.approx(p.notional / 20, abs=0.01)


def test_risk_plan_sell_mirrors_buy():
    p = build_risk_plan("SELL", entry=20000, atr=300, account_size=10000)
    assert p.stop_loss == 20600 and p.take_profit == 18800


@pytest.mark.parametrize("kwargs", [{"action": "HOLD"}, {"atr": 0}, {"account_size": -1}, {"risk_pct": 0}])
def test_risk_plan_rejects_bad_input(kwargs):
    base = dict(action="BUY", entry=100.0, atr=2.0, account_size=1000.0)
    with pytest.raises(ValueError):
        build_risk_plan(**{**base, **kwargs})


def test_scores_saturate_and_handle_missing():
    assert agg.surprise_score([0.5, 0.5]) == 1.0
    assert agg.surprise_score([]) is None
    assert agg.revisions_score(3, 1) == 0.5 and agg.revisions_score(0, 0) is None
    assert -1 <= agg.momentum_score(-0.5, False) <= 1


def test_combine_renormalises_over_available_components():
    assert agg.combine({"surprise": None, "revisions": None, "momentum": None}) is None
    assert agg.combine({"surprise": 1.0, "revisions": None, "momentum": None}) == 1.0
    full = agg.combine({"surprise": 1.0, "revisions": 0.0, "momentum": -1.0})
    assert full == pytest.approx(0.35 - 0.30)


def test_index_score_is_weight_average_and_skips_unscored():
    rows = [
        {"weight_pct": 30, "score": 1.0},
        {"weight_pct": 10, "score": -1.0},
        {"weight_pct": 60, "score": None},
    ]
    out = agg.index_score(rows)
    assert out["index_score"] == pytest.approx(0.5)
    assert out["coverage_weight_pct"] == 40
    assert agg.label(0.5) == "bullish" and agg.label(-0.5) == "bearish" and agg.label(0.0) == "neutral"


def _ohlc(n=300, drift=0.001):
    close = pd.Series(100 * np.cumprod(1 + np.full(n, drift)))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1})


def test_indicators_uptrend():
    ind = prices.indicators_from_df(_ohlc())
    assert ind["trend_vs_ma"] == "up" and ind["rsi14"] > 90
    assert ind["atr14"] > 0 and ind["sma"][200] < ind["sma"][50] < ind["sma"][20]


def test_indicators_short_history_has_unknown_trend():
    assert prices.indicators_from_df(_ohlc(60))["trend_vs_ma"] == "unknown"


def test_implied_vol_round_trip_and_bounds():
    price = options._bs_price("put", 100, 95, 0.25, 0.045, 0.3)
    assert options.implied_vol("put", price, 100, 95, 0.25) == pytest.approx(0.3, abs=1e-4)
    assert options.implied_vol("call", 0.0, 100, 100, 0.25) is None
    assert options.implied_vol("call", 150, 100, 100, 0.25) is None  # above spot: impossible


def test_headline_sentiment_and_clean():
    assert score_headline("Nvidia beats estimates, shares surge") > 0
    assert score_headline("Company misses and cuts outlook") < 0
    assert score_headline("Company announces event") == 0
    out = clean({"a": float("nan"), "b": np.float64(1.5), "c": pd.Timestamp("2026-01-01")})
    assert out == {"a": None, "b": 1.5, "c": "2026-01-01T00:00:00"}
    assert not math.isnan(out["b"])
