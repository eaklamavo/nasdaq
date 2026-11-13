"""ATR-based stop/target and CFD position sizing."""
from __future__ import annotations

import math

from .data import prices
from .data._util import safe
from .models import RiskPlan


def build_risk_plan(
    action: str,
    entry: float,
    atr: float,
    account_size: float,
    risk_pct: float = 1.0,
    leverage: float = 20.0,
    stop_atr_mult: float = 2.0,
    reward_risk: float = 2.0,
) -> RiskPlan:
    """Stop = entry -/+ stop_atr_mult*ATR; target = reward_risk x the stop distance.
    Units = (account_size * risk_pct%) / stop distance, so a stop-out loses ~risk_pct of the account
    (before gaps/slippage)."""
    if action not in ("BUY", "SELL"):
        raise ValueError("risk plan only applies to BUY or SELL")
    if min(entry, atr, account_size, leverage) <= 0 or not 0 < risk_pct <= 100:
        raise ValueError("entry, atr, account_size, leverage must be > 0 and 0 < risk_pct <= 100")
    dist = stop_atr_mult * atr
    sign = 1 if action == "BUY" else -1
    risk_amount = account_size * risk_pct / 100
    units = math.floor(risk_amount / dist * 10_000) / 10_000  # round down: never exceed planned risk
    notional = units * entry
    return RiskPlan(
        entry=round(entry, 2),
        stop_loss=round(entry - sign * dist, 2),
        take_profit=round(entry + sign * dist * reward_risk, 2),
        risk_reward=reward_risk,
        position_size_units=units,
        risk_amount=round(risk_amount, 2),
        notional=round(notional, 2),
        margin_required=round(notional / leverage, 2),
    )


@safe
def compute_risk_levels(
    action: str,
    account_size: float,
    risk_pct: float = 1.0,
    leverage: float = 20.0,
    stop_atr_mult: float = 2.0,
    reward_risk: float = 2.0,
) -> dict:
    """Entry/stop/target/position size for a BUY or SELL on the Nasdaq-100 CFD using the latest ^NDX
    close and 14-day ATR. Size is in CFD units (currency per index point)."""
    ind = prices.indicators_from_df(prices.history(prices.INDEX_TICKER, "1y"))
    plan = build_risk_plan(action.upper(), ind["last"], ind["atr14"], account_size, risk_pct, leverage,
                           stop_atr_mult, reward_risk)
    d = plan.model_dump()
    d["atr14"] = ind["atr14"]
    d["warnings"] = [
        "Entry is the last daily close; adjust to the live CFD quote.",
        "Margin shown is notional/leverage; check your broker's actual margin rate.",
        "Overnight financing accrues on swing holds; gaps can exceed the stop.",
    ]
    if plan.margin_required > account_size:
        d["warnings"].append("Required margin exceeds the account size: reduce risk_pct or stop distance.")
    return d
