"""Portfolio Manager: produce a deterministic final decision."""

from __future__ import annotations

from tradingagents.agents.utils.deterministic_decisions import build_portfolio_decision_text


def create_portfolio_manager(llm):
    def portfolio_manager_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        final_trade_decision = build_portfolio_decision_text(state)

        new_risk_debate_state = {
            "judge_decision": final_trade_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
