from __future__ import annotations

import re

from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import get_verified_market_snapshot, is_chinese_output


_TABLE_METRIC_RE = re.compile(
    r"\|\s*(?P<label>[A-Za-z0-9_ ]+)\s*\|\s*(?P<value>-?[0-9]+(?:\.[0-9]+)?)\s*\|"
)


def _extract_market_metrics(snapshot: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for match in _TABLE_METRIC_RE.finditer(snapshot or ""):
        label = match.group("label").strip().lower().replace(" ", "_")
        try:
            metrics[label] = float(match.group("value"))
        except (TypeError, ValueError):
            continue
    return metrics


def _compute_market_rating(snapshot: str) -> tuple[str, str]:
    metrics = _extract_market_metrics(snapshot)
    close = metrics.get("close")
    ema10 = metrics.get("close_10_ema")
    sma50 = metrics.get("close_50_sma")
    sma200 = metrics.get("close_200_sma")
    rsi = metrics.get("rsi")
    macd = metrics.get("macd")
    macd_signal = metrics.get("macds")
    boll_ub = metrics.get("boll_ub")
    boll_lb = metrics.get("boll_lb")

    score = 0.0

    if close is not None and ema10 is not None:
        score += 1.0 if close > ema10 else -1.0
    if close is not None and sma50 is not None:
        score += 1.0 if close > sma50 else -1.0
    if close is not None and sma200 is not None:
        score += 1.0 if close > sma200 else -1.0

    if rsi is not None:
        if rsi >= 75:
            score -= 1.0
        elif rsi >= 60:
            score += 0.5
        elif rsi <= 25:
            score += 0.5
        elif rsi <= 40:
            score -= 0.5

    if macd is not None:
        score += 0.5 if macd > 0 else -0.5
    if macd is not None and macd_signal is not None:
        score += 0.5 if macd > macd_signal else -0.5

    if close is not None and boll_ub is not None and close >= boll_ub * 0.985:
        score -= 0.5
    if close is not None and boll_lb is not None and close <= boll_lb * 1.015:
        score += 0.5

    if score >= 3.0:
        return "Buy", "BUY"
    if score >= 1.5:
        return "Overweight", "BUY"
    if score <= -3.0:
        return "Sell", "SELL"
    if score <= -1.5:
        return "Underweight", "SELL"
    return "Hold", "HOLD"


def create_market_analyst(llm):
    def market_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]
        snapshot = get_verified_market_snapshot.func(ticker, current_date)
        rating, action = _compute_market_rating(snapshot)

        if is_chinese_output():
            report = "\n\n".join([
                f"FINAL TRANSACTION PROPOSAL: **{action}**",
                f"**Rating**: {rating}",
                f"# 确定性市场数据包: {ticker}",
                "本节内容直接基于已验证市场快照生成。除下方明确给出的价格、指标和日期外，不要补充额外推断。",
                f"基于最新收盘价、均线结构、RSI、MACD 与布林区间的确定性打分后，当前技术面评级为 `{rating}`，对应交易动作为 `{action}`。",
                snapshot,
            ])
        else:
            report = "\n\n".join([
                f"FINAL TRANSACTION PROPOSAL: **{action}**",
                f"**Rating**: {rating}",
                f"# Deterministic Market Package: {ticker}",
                "This section is assembled directly from the verified market snapshot. Do not infer claims beyond the data shown below.",
                f"A deterministic technical score based on the latest close, moving averages, RSI, MACD, and Bollinger bands maps the market view to `{rating}` and the trade action to `{action}`.",
                snapshot,
            ])

        return {
            "messages": [AIMessage(content=report)],
            "market_report": report,
        }

    return market_analyst_node
