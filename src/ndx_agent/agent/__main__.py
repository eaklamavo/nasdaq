"""CLI: python -m ndx_agent.agent [--account 10000 --risk 1 --leverage 20]"""
import argparse
import asyncio

from .loop import run_agent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=float, default=10000)
    ap.add_argument("--risk", type=float, default=1.0)
    ap.add_argument("--leverage", type=float, default=20)
    a = ap.parse_args()

    def show(e):
        if e["type"] == "tool_call":
            print(f"-> {e['name']} {e['input']}")

    rec, _ = asyncio.run(run_agent(a.account, a.risk, a.leverage, on_event=show))
    print(rec.model_dump_json(indent=2))


main()
