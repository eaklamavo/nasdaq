"""Runs the real agent loop against the real MCP server with a scripted fake Anthropic client.
Needs network (market data) but no Anthropic key. Select with: pytest -m live"""
from types import SimpleNamespace as NS

import pytest

from ndx_agent.agent.loop import run_agent

pytestmark = pytest.mark.live


def _use(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


class FakeClient:
    """Scripted model: replies are produced from a list of content-block lists."""

    def __init__(self, script):
        self.script = list(script)
        self.seen_results = []
        self.messages = NS(create=self._create)

    async def _create(self, **kw):
        last = kw["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], list):
            self.seen_results.append(last["content"])
        return NS(content=self.script.pop(0))


async def test_buy_flow_attaches_code_computed_risk_plan_and_rejects_early_submit():
    draft = dict(action="BUY", confidence=0.6, summary="s", risks=["r"],
                 evidence=[dict(tool="compute_indicators", finding="f", direction="bullish")])
    client = FakeClient([
        [_use("1", "get_top_weights", n=3)],
        [_use("2", "submit_recommendation", **draft)],  # no risk plan yet -> must be rejected
        [_use("3", "compute_risk_levels", action="BUY", account_size=10000)],
        [_use("4", "submit_recommendation", **draft)],
    ])
    rec, trace = await run_agent(account_size=10000, client=client)
    assert rec.action == "BUY" and rec.risk_plan is not None
    assert rec.risk_plan.stop_loss < rec.risk_plan.entry < rec.risk_plan.take_profit
    assert [t["tool"] for t in trace] == ["get_top_weights", "compute_risk_levels"]
    rejected = [r for batch in client.seen_results for r in batch if r.get("is_error")]
    assert rejected and "compute_risk_levels" in rejected[0]["content"]


async def test_hold_needs_no_risk_plan_and_tool_errors_are_reported_not_raised():
    draft = dict(action="HOLD", confidence=0.4, summary="s", risks=[], evidence=[])
    client = FakeClient([
        [_use("1", "get_eps_history", ticker="NOT_A_TICKER_XYZ")],
        [_use("2", "submit_recommendation", **draft)],
    ])
    rec, trace = await run_agent(client=client)
    assert rec.action == "HOLD" and rec.risk_plan is None
    assert len(trace) == 1
