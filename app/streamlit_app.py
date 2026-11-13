"""Streamlit UI. Run: streamlit run app/streamlit_app.py"""
import asyncio
import json

import streamlit as st

from ndx_agent import config
from ndx_agent.agent.loop import run_agent
from ndx_agent.models import DISCLAIMER

st.set_page_config(page_title="NDX CFD Agent", page_icon="📈", layout="wide")
st.title("Nasdaq-100 CFD recommendation agent")
st.caption(DISCLAIMER)

with st.sidebar:
    st.header("Account")
    account = st.number_input("Account size", min_value=100.0, value=10000.0, step=500.0)
    risk_pct = st.slider("Risk per trade (%)", 0.25, 5.0, 1.0, 0.25)
    leverage = st.number_input("CFD leverage (x)", min_value=1.0, max_value=100.0, value=20.0)
    notes = st.text_area("Extra instructions (optional)", placeholder="e.g. I can't hold through NVDA earnings")
    st.divider()
    st.write("Model:", f"`{config.ANTHROPIC_MODEL}`")
    for key in ("ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "NEWSAPI_KEY", "FMP_API_KEY"):
        st.write("✅" if config.get(key) else "⚪", key)

COLORS = {"BUY": "green", "SELL": "red", "HOLD": "orange"}
ICONS = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}

if st.button("Generate recommendation", type="primary", disabled=not config.get("ANTHROPIC_API_KEY")):
    log = st.status("Agent working...", expanded=True)

    def on_event(e: dict) -> None:
        if e["type"] == "tool_call":
            log.write(f"🔧 `{e['name']}` {json.dumps(e['input'])}")
        elif e["type"] == "tool_result" and e["error"]:
            log.write(f"⚠️ `{e['name']}` returned an error")

    try:
        rec, trace = asyncio.run(run_agent(account, risk_pct, leverage, notes, on_event=on_event))
        log.update(label=f"Done: {len(trace)} tool calls", state="complete", expanded=False)
        st.session_state["result"] = (rec, trace)
    except Exception as exc:  # noqa: BLE001
        log.update(label="Failed", state="error")
        st.error(str(exc))

if not config.get("ANTHROPIC_API_KEY"):
    st.warning("Set ANTHROPIC_API_KEY in `.env` to enable the agent (see `.env.example`).")

if "result" in st.session_state:
    rec, trace = st.session_state["result"]
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"## :{COLORS[rec.action]}[{rec.action}]")
    c2.metric("Confidence", f"{rec.confidence:.0%}")
    c3.metric("Horizon", rec.horizon)
    st.write(rec.summary)

    if rec.risk_plan:
        p = rec.risk_plan
        st.subheader("Trade plan")
        cols = st.columns(5)
        cols[0].metric("Entry", f"{p.entry:,.2f}")
        cols[1].metric("Stop-loss", f"{p.stop_loss:,.2f}")
        cols[2].metric("Take-profit", f"{p.take_profit:,.2f}")
        cols[3].metric("Size (units)", f"{p.position_size_units:g}")
        cols[4].metric("Risk", f"{p.risk_amount:,.2f}")
        st.caption(f"Notional {p.notional:,.2f} · margin ≈ {p.margin_required:,.2f} · R:R {p.risk_reward:g}")

    left, right = st.columns(2)
    with left:
        st.subheader("Evidence")
        for ev in rec.evidence:
            st.markdown(f"{ICONS[ev.direction]} **{ev.tool}**: {ev.finding}")
    with right:
        st.subheader("Risks")
        for r in rec.risks:
            st.markdown(f"- {r}")

    with st.expander(f"Tool trace ({len(trace)} calls)"):
        for t in trace:
            st.markdown(f"**{t['tool']}** `{json.dumps(t['input'])}`" + (" ⚠️" if t["error"] else ""))
            st.code(t["output"][:3000], language="json")
    st.caption(rec.disclaimer)
