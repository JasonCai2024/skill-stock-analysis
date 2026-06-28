from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import get_global_news, get_news
from tradingagents.dataflows.config import get_config


def _lookback_start(current_date: str, days: int = 7) -> str:
    return (datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        config = get_config()
        look_back_days = int(config.get("global_news_lookback_days", 7))
        limit = int(config.get("global_news_article_limit", 10))
        start_date = _lookback_start(current_date, look_back_days)

        global_news = get_global_news.func(current_date, look_back_days, limit)
        company_news = get_news.func(ticker, start_date, current_date)

        report = "\n\n".join([
            f"# Deterministic News Package: {ticker}",
            "This section is assembled directly from tool outputs. Do not infer events that are not explicitly present below.",
            "## Global Macro News",
            global_news,
            "## Company-specific News",
            company_news,
        ])

        return {
            "messages": [AIMessage(content=report)],
            "news_report": report,
        }

    return news_analyst_node
