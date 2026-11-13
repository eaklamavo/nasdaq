# Nasdaq-100 CFD recommendation agent

Claude (Anthropic) agent that gathers data through a custom **MCP server** and returns a swing-horizon (days to weeks) **BUY / SELL / HOLD** for a Nasdaq-100 CFD, with confidence, evidence, risks, and an entry / stop / target / position-size plan. Streamlit UI.

> Advisory output only, not financial advice. CFDs are leveraged and can lose money rapidly. There is no order execution.

```
Streamlit UI -> agent loop (Claude tool use) -> MCP client -> MCP server (stdio) -> data providers (disk cache)
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env   # then fill in keys
```

Keys (see `.env.example`): `ANTHROPIC_API_KEY` is required for the agent. `FINNHUB_API_KEY`, `NEWSAPI_KEY`, `FMP_API_KEY` are optional; tools that need a missing key fall back (e.g. Yahoo RSS, yfinance) or return `source_unavailable`. FRED, CFTC and EDGAR need no key (set `SEC_USER_AGENT` to your contact details for EDGAR).

## Run

```powershell
.\.venv\Scripts\streamlit.exe run app\streamlit_app.py     # web UI
.\.venv\Scripts\python.exe -m ndx_agent.agent --account 10000 --risk 1 --leverage 20   # CLI
.\.venv\Scripts\python.exe -m ndx_agent.mcp_server          # MCP server alone (stdio)
```

The MCP server can also be used from other MCP clients (Copilot CLI, VS Code), e.g. command `.venv\Scripts\python.exe`, args `-m ndx_agent.mcp_server`.

## MCP tools

| Area | Tools | Source |
|---|---|---|
| Constituents | `get_constituents`, `get_top_weights` | Invesco QQQ holdings (Wikipedia fallback, no weights) |
| Prices / technicals | `get_ohlcv`, `get_index_snapshot`, `compute_indicators`, `get_breadth` | yfinance, computed locally |
| Fundamentals | `get_eps_history`, `get_estimates_revisions`, `get_earnings_calendar`, `get_upcoming_earnings` | yfinance, Finnhub |
| News | `get_news`, `get_news_sentiment` | Finnhub, NewsAPI, Yahoo RSS |
| Macro | `get_macro_series`, `get_macro_dashboard` | FRED |
| Options / positioning | `get_put_call_ratio`, `get_iv_skew`, `get_cot_positioning` | yfinance QQQ chain, CFTC TFF |
| Filings | `get_recent_filings`, `get_filing_excerpt` | SEC EDGAR |
| Analysis | `compute_index_earnings_impact`, `compute_risk_levels` | deterministic code |

## How the numbers are produced

- **Index signal** ([aggregation.py](src/ndx_agent/aggregation.py)): per constituent, `0.35*EPS-surprise + 0.35*30d-estimate-revisions + 0.30*momentum`, each in [-1, 1]; then weight-averaged by QQQ weight over the top N. Missing components are renormalised away and coverage is reported.
- **Risk plan** ([risk.py](src/ndx_agent/risk.py)): stop = 2 x ATR14, target = 2R, units = account x risk% / stop distance (rounded down). The model cannot set these itself; the loop rejects a BUY/SELL submission without a matching `compute_risk_levels` result and attaches the code-computed plan.

## Known limitations

- yfinance is unofficial and may break or rate-limit; results are cached under `.cache\` (15 min to 24 h).
- Option IV is computed locally from prices. Outside US hours quotes are empty, so it uses last trades and reports `data_quality: last_trade_stale`.
- News sentiment is a crude keyword score. COT is weekly (Tuesday data, published Friday).
- Entry uses the last `^NDX` daily close, not the live CFD quote; margin is notional / leverage, not your broker's real rate.
- `mcp` is pinned `<2` because 2.x renamed `FastMCP`.
- The signal logic is not backtested.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest              # unit tests + live-data agent-loop tests (need network, no keys)
.\.venv\Scripts\python.exe -m pytest -m "not live"  # offline only
```
