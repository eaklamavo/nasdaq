"""Claude tool-use loop over the MCP server, ending in a validated Recommendation."""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field

from .. import config
from ..models import Evidence, Recommendation, RiskPlan
from .prompts import SYSTEM_PROMPT

MAX_TOOL_RESULT_CHARS = 14000
SUBMIT_TOOL = "submit_recommendation"


class RecommendationDraft(BaseModel):
    """What the model submits. Risk plan and disclaimer are attached by code, not typed by the model."""

    action: str = Field(pattern="^(BUY|SELL|HOLD)$")
    confidence: float = Field(ge=0, le=1)
    summary: str
    evidence: list[Evidence]
    risks: list[str]


@asynccontextmanager
async def mcp_session():
    params = StdioServerParameters(command=sys.executable, args=["-m", "ndx_agent.mcp_server"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield session


def _to_anthropic_tools(mcp_tools) -> list[dict]:
    tools = [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
             for t in mcp_tools]
    tools.append({
        "name": SUBMIT_TOOL,
        "description": "Submit the final recommendation. Call exactly once, after gathering evidence "
                       "(and after compute_risk_levels if action is BUY or SELL).",
        "input_schema": RecommendationDraft.model_json_schema(),
    })
    return tools


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + f"\n...[truncated {len(text) - MAX_TOOL_RESULT_CHARS} chars]"


async def run_agent(
    account_size: float = 10000.0,
    risk_pct: float = 1.0,
    leverage: float = 20.0,
    extra_instructions: str = "",
    max_turns: int = 25,
    on_event: Optional[Callable[[dict], None]] = None,
    client: Optional[anthropic.AsyncAnthropic] = None,
) -> tuple[Recommendation, list[dict]]:
    """Run the agent. Returns (recommendation, tool_trace). `on_event` receives progress dicts."""
    emit = on_event or (lambda e: None)
    if client is None:
        if not config.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set (see .env.example)")
        client = anthropic.AsyncAnthropic()

    user = (
        f"Produce a recommendation for the Nasdaq-100 CFD now. Account size: {account_size:,.2f}, "
        f"risk per trade: {risk_pct}% of account, leverage: {leverage}x. {extra_instructions}".strip()
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    trace: list[dict] = []
    risk_plan: Optional[dict] = None

    async with mcp_session() as session:
        tools = _to_anthropic_tools((await session.list_tools()).tools)

        for turn in range(max_turns):
            resp = await client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})
            for block in resp.content:
                if block.type == "text" and block.text.strip():
                    emit({"type": "thinking", "text": block.text})

            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                messages.append({"role": "user", "content": f"Finish by calling {SUBMIT_TOOL}."})
                continue

            results = []
            final: Optional[Recommendation] = None
            for call in calls:
                if call.name == SUBMIT_TOOL:
                    try:
                        draft = RecommendationDraft.model_validate(call.input)
                        plan = None
                        if draft.action in ("BUY", "SELL") and risk_plan and risk_plan["action"] == draft.action:
                            plan = RiskPlan(**{k: v for k, v in risk_plan.items() if k in RiskPlan.model_fields})
                        elif draft.action in ("BUY", "SELL"):
                            raise ValueError(
                                f"call compute_risk_levels with action={draft.action} before submitting")
                        final = Recommendation(**draft.model_dump(), risk_plan=plan)
                        results.append({"type": "tool_result", "tool_use_id": call.id, "content": "accepted"})
                    except Exception as e:  # noqa: BLE001 - feed validation errors back to the model
                        results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                        "content": f"Rejected: {e}"})
                    continue

                emit({"type": "tool_call", "name": call.name, "input": call.input})
                try:
                    res = await session.call_tool(call.name, call.input)
                    text = "".join(c.text for c in res.content if getattr(c, "text", None))
                    is_err = bool(res.isError)
                except Exception as e:  # noqa: BLE001
                    text, is_err = f"tool call failed: {e}", True
                if call.name == "compute_risk_levels" and not is_err:
                    try:
                        parsed = json.loads(text)
                        if "error" not in parsed:
                            parsed["action"] = str(call.input.get("action", "")).upper()
                            risk_plan = parsed
                    except json.JSONDecodeError:
                        pass
                trace.append({"tool": call.name, "input": call.input, "output": text, "error": is_err})
                emit({"type": "tool_result", "name": call.name, "chars": len(text), "error": is_err})
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": _truncate(text),
                                **({"is_error": True} if is_err else {})})

            messages.append({"role": "user", "content": results})
            if final is not None:
                emit({"type": "done"})
                return final, trace

    raise RuntimeError(f"Agent did not submit a recommendation within {max_turns} turns")
