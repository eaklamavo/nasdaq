"""CFTC Commitments of Traders (Traders in Financial Futures) for Nasdaq-100 futures."""
from __future__ import annotations

import httpx

from ..cache import ttl_cache
from ._util import safe

URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"


@ttl_cache(6 * 3600)
def _rows(limit: int) -> list[dict]:
    r = httpx.get(
        URL,
        params={
            "$where": "market_and_exchange_names like 'NASDAQ-100 Consolidated%'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": str(limit),
        },
        timeout=40,
    )
    r.raise_for_status()
    return r.json()


def _net(row: dict, prefix: str) -> int:
    return int(float(row[f"{prefix}_positions_long"])) - int(float(row[f"{prefix}_positions_short"]))


@safe
def get_cot_positioning(weeks: int = 8) -> dict:
    """Weekly net positioning in Nasdaq-100 futures for leveraged funds and asset managers, with trend.
    Data is as of Tuesday and published Friday, so it is a slow, lagging signal."""
    rows = _rows(max(weeks, 4))
    hist = [
        {
            "report_date": r["report_date_as_yyyy_mm_dd"][:10],
            "open_interest": int(float(r["open_interest_all"])),
            "lev_funds_net": _net(r, "lev_money"),
            "asset_mgr_net": _net(r, "asset_mgr"),
        }
        for r in rows[:weeks]
    ]
    latest, oldest = hist[0], hist[-1]
    return {
        "market": rows[0]["market_and_exchange_names"],
        "latest": latest,
        "lev_funds_net_change_over_window": latest["lev_funds_net"] - oldest["lev_funds_net"],
        "asset_mgr_net_change_over_window": latest["asset_mgr_net"] - oldest["asset_mgr_net"],
        "history": hist,
        "interpretation": "leveraged funds are trend/speculative; extreme net-short can fuel squeezes, "
                          "asset managers are structurally long",
    }
