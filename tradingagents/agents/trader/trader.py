"""Trader: convert the investment plan into a deterministic proposal."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.deterministic_decisions import build_trader_proposal_text


def create_trader(llm):
    def trader_node(state, name):
        trader_plan = build_trader_proposal_text(state)

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
