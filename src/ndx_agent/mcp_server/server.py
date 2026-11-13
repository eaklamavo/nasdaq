"""MCP server exposing Nasdaq-100 market-data and analysis tools over stdio.

Run:  python -m ndx_agent.mcp_server.server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .. import aggregation, risk
from ..data import constituents, cot, filings, fundamentals, macro, news, options, prices

mcp = FastMCP("ndx-data")

TOOLS = [
    # constituents
    constituents.get_constituents,
    constituents.get_top_weights,
    # prices / technicals
    prices.get_ohlcv,
    prices.get_index_snapshot,
    prices.compute_indicators,
    prices.get_breadth,
    # fundamentals
    fundamentals.get_eps_history,
    fundamentals.get_estimates_revisions,
    fundamentals.get_earnings_calendar,
    fundamentals.get_upcoming_earnings,
    # news
    news.get_news,
    news.get_news_sentiment,
    # macro
    macro.get_macro_series,
    macro.get_macro_dashboard,
    # options / positioning
    options.get_put_call_ratio,
    options.get_iv_skew,
    cot.get_cot_positioning,
    # filings
    filings.get_recent_filings,
    filings.get_filing_excerpt,
    # analysis
    aggregation.compute_index_earnings_impact,
    risk.compute_risk_levels,
]

for _fn in TOOLS:
    mcp.tool()(_fn)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
