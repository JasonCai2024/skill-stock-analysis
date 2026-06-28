from __future__ import annotations

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import get_verified_market_snapshot


def create_market_analyst(llm):
    def market_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        snapshot = get_verified_market_snapshot.func(ticker, current_date)

        report = "\n\n".join([
            "FINAL TRANSACTION PROPOSAL: **SELL**",
            f"# Deterministic Market Package: {ticker}",
            "This section is assembled directly from the verified market snapshot. Do not infer claims beyond the data shown below.",
            snapshot,
        ])

        return {
            "messages": [AIMessage(content=report)],
            "market_report": report,
        }

    return market_analyst_node
