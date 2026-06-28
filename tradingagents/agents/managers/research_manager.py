"""Research Manager: produce a deterministic investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.utils.deterministic_decisions import build_research_plan_text


def create_research_manager(llm):
    def research_manager_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        investment_plan = build_research_plan_text(state)

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
