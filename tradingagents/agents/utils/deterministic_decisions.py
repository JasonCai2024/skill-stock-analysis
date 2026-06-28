"""Deterministic decision builders for manager/trader/final-PM nodes."""

from __future__ import annotations

import re
from typing import Mapping, Optional

from tradingagents.agents.schemas import (
    PortfolioDecision,
    PortfolioRating,
    ResearchPlan,
    TraderAction,
    TraderProposal,
    render_pm_decision,
    render_research_plan,
    render_trader_proposal,
)
from tradingagents.agents.utils.agent_utils import is_chinese_output
from tradingagents.agents.utils.rating import parse_rating


_SENTIMENT_HEADER_RE = re.compile(
    r"\*\*Overall Sentiment:\*\*\s*\*\*(?P<band>[^*]+)\*\*\s*\(Score:\s*(?P<score>[0-9.]+)/10\)",
    re.IGNORECASE,
)
_SENTIMENT_HEADER_CN_RE = re.compile(
    r"\*\*整体情绪\*\*:\s*\*\*(?P<band>[^*]+)\*\*\s*\(评分:\s*(?P<score>[0-9.]+)/10\)",
    re.IGNORECASE,
)
_SENTIMENT_FALLBACK_RE = re.compile(
    r"\*\*overall_band\*\*:\s*(?P<band>.+?)\s*$.*?\*\*overall_score\*\*:\s*(?P<score>[0-9.]+)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)
_TABLE_METRIC_RE = re.compile(
    r"\|\s*(?P<label>[A-Za-z0-9_ ]+)\s*\|\s*(?P<value>-?[0-9]+(?:\.[0-9]+)?)\s*\|"
)


def _extract_sentiment_band(report: str) -> tuple[Optional[str], Optional[float]]:
    text = report or ""
    match = _SENTIMENT_HEADER_RE.search(text)
    if not match:
        match = _SENTIMENT_HEADER_CN_RE.search(text)
    if not match:
        match = _SENTIMENT_FALLBACK_RE.search(text)
    if not match:
        return None, None
    try:
        score = float(match.group("score"))
    except (TypeError, ValueError):
        score = None
    return match.group("band").strip(), score


def _rating_value(rating: str) -> int:
    return {
        "Buy": 2,
        "Overweight": 1,
        "Hold": 0,
        "Underweight": -1,
        "Sell": -2,
    }.get(rating, 0)


def _value_to_rating(value: float) -> str:
    if value >= 1.25:
        return "Buy"
    if value >= 0.4:
        return "Overweight"
    if value <= -1.25:
        return "Sell"
    if value <= -0.4:
        return "Underweight"
    return "Hold"


def _sentiment_band_to_rating(band: Optional[str]) -> str:
    if not band:
        return "Hold"
    normalized = band.strip().lower()
    return {
        "bullish": "Buy",
        "mildly bullish": "Overweight",
        "neutral": "Hold",
        "mixed": "Hold",
        "mildly bearish": "Underweight",
        "bearish": "Sell",
    }.get(normalized, "Hold")


def _safe_rating_enum(rating: str) -> PortfolioRating:
    return PortfolioRating(rating)


def _extract_market_metrics(report: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for match in _TABLE_METRIC_RE.finditer(report or ""):
        label = match.group("label").strip().lower().replace(" ", "_")
        try:
            metrics[label] = float(match.group("value"))
        except (TypeError, ValueError):
            continue
    return metrics


def _round_price(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(max(value, 0.01), 2)


def _market_bias_cn(rating: str) -> str:
    return {
        "Buy": "技术偏强",
        "Overweight": "技术偏强",
        "Hold": "技术中性",
        "Underweight": "技术偏弱",
        "Sell": "技术偏弱",
    }.get(rating, "技术中性")


def _market_bias_en(rating: str) -> str:
    return {
        "Buy": "technicals are strong",
        "Overweight": "technicals are constructive",
        "Hold": "technicals are neutral",
        "Underweight": "technicals are weak",
        "Sell": "technicals are weak",
    }.get(rating, "technicals are neutral")


def _build_trade_levels(
    action: TraderAction,
    metrics: Mapping[str, float],
) -> dict[str, Optional[float]]:
    close = metrics.get("close")
    atr = metrics.get("atr")
    boll_lb = metrics.get("boll_lb")
    boll_ub = metrics.get("boll_ub")

    if close is None:
        return {"entry_price": None, "stop_loss": None, "price_target": None}

    atr_value = atr if atr and atr > 0 else max(abs(close) * 0.08, 0.01)

    if action == TraderAction.BUY:
        entry_price = close
        stop_loss = close - atr_value
        price_target = boll_ub if boll_ub and boll_ub > close else close + atr_value * 2
    elif action == TraderAction.HOLD:
        entry_price = close
        stop_loss = close - atr_value
        price_target = close + atr_value
    else:
        entry_price = None
        stop_loss = close + atr_value
        price_target = boll_lb if boll_lb and boll_lb < close else close - atr_value * 2

    return {
        "entry_price": _round_price(entry_price),
        "stop_loss": _round_price(stop_loss),
        "price_target": _round_price(price_target),
    }


def _build_signal_snapshot(state: Mapping[str, object]) -> dict[str, object]:
    market_report = str(state.get("market_report") or "")
    sentiment_report = str(state.get("sentiment_report") or "")
    news_report = str(state.get("news_report") or "")
    fundamentals_report = str(state.get("fundamentals_report") or "")

    market_rating = parse_rating(market_report, default="Hold")
    sentiment_band, sentiment_score = _extract_sentiment_band(sentiment_report)
    sentiment_rating = _sentiment_band_to_rating(sentiment_band)
    news_rating = parse_rating(news_report, default="Hold")
    market_metrics = _extract_market_metrics(market_report)

    composite = (
        _rating_value(market_rating) * 0.55
        + _rating_value(sentiment_rating) * 0.30
        + _rating_value(news_rating) * 0.15
    )
    research_rating = _value_to_rating(composite)

    return {
        "market_rating": market_rating,
        "sentiment_band": sentiment_band,
        "sentiment_score": sentiment_score,
        "sentiment_rating": sentiment_rating,
        "news_rating": news_rating,
        "research_rating": research_rating,
        "has_fundamentals": bool(fundamentals_report.strip()),
        "market_metrics": market_metrics,
    }


def build_research_plan_text(state: Mapping[str, object]) -> str:
    signals = _build_signal_snapshot(state)
    market_rating = str(signals["market_rating"])
    sentiment_band = signals["sentiment_band"]
    sentiment_score = signals["sentiment_score"]
    research_rating = str(signals["research_rating"])
    has_fundamentals = bool(signals["has_fundamentals"])

    if is_chinese_output():
        rationale_parts = [
            f"本轮最强、最明确的显式信号来自技术面，目前对应评级为 `{market_rating}`。",
        ]
        if sentiment_band:
            sentiment_text = f"情绪面为 `{sentiment_band}`"
            if sentiment_score is not None:
                sentiment_text += f"（{sentiment_score:.1f}/10）"
            rationale_parts.append(
                sentiment_text
                + f"，它对当前“{_market_bias_cn(market_rating)}”的判断形成辅助验证，但暂不足以单独改变技术主导结论。"
            )
        else:
            rationale_parts.append("本轮没有提取到稳定的情绪头部，因此情绪面按中性处理。")
        if has_fundamentals:
            rationale_parts.append("基本面部分仅保留原始报表和指标，不对未完整披露的信息做额外方向性推断。")
        rationale_parts.append(f"综合加权后，确定性结果落在 `{research_rating}`。")

        actions_map = {
            "Buy": "分批增加敞口，并在确认市场流动性和执行条件后再逐步加仓。",
            "Overweight": "可以逐步提高仓位，但不宜一次性重仓，应持续观察技术弱势是否开始修复。",
            "Hold": "保持当前敞口，等待技术面与情绪面给出更一致的方向信号。",
            "Underweight": "降低敞口或维持轻仓，在技术趋势企稳前不宜激进加仓。",
            "Sell": "当前以退出或回避为主，待技术形态明显修复后再重新评估。",
        }
    else:
        rationale_parts = [
            f"Technical market evidence is the strongest explicit signal in this run and currently maps to `{market_rating}`.",
        ]
        if sentiment_band:
            sentiment_text = f"Sentiment is `{sentiment_band}`"
            if sentiment_score is not None:
                sentiment_text += f" ({sentiment_score:.1f}/10)"
            rationale_parts.append(
                sentiment_text
                + f", which helps contextualize the fact that {_market_bias_en(market_rating)}, but does not override the market-led signal."
            )
        else:
            rationale_parts.append("No deterministic sentiment header was available, so sentiment was treated as neutral.")
        if has_fundamentals:
            rationale_parts.append(
                "Fundamentals were retained as raw statements and ratios, but no extra directional score was inferred from them to avoid over-interpreting incomplete evidence."
            )
        rationale_parts.append(f"On balance, the combined deterministic signal maps to `{research_rating}`.")

        actions_map = {
            "Buy": "Add exposure in tranches and only after confirming liquidity and execution conditions in the market report.",
            "Overweight": "Increase exposure gradually rather than all at once, while monitoring whether technical weakness starts to reverse.",
            "Hold": "Keep current exposure unchanged and wait for technical and sentiment signals to align more clearly.",
            "Underweight": "Reduce exposure or keep positions light; avoid aggressive new buying until the technical trend stabilizes.",
            "Sell": "Exit or avoid the position for now; only reassess after a clearly improved technical setup appears.",
        }

    plan = ResearchPlan(
        recommendation=_safe_rating_enum(research_rating),
        rationale=" ".join(rationale_parts),
        strategic_actions=actions_map[research_rating],
    )
    return render_research_plan(plan)


def build_trader_proposal_text(state: Mapping[str, object]) -> str:
    signals = _build_signal_snapshot(state)
    recommendation = parse_rating(
        str(state.get("investment_plan") or ""),
        default=str(signals["research_rating"]),
    )
    market_rating = str(signals["market_rating"])
    sentiment_band = signals["sentiment_band"]

    action_map = {
        "Buy": TraderAction.BUY,
        "Overweight": TraderAction.BUY,
        "Hold": TraderAction.HOLD,
        "Underweight": TraderAction.SELL,
        "Sell": TraderAction.SELL,
    }
    action = action_map.get(recommendation, TraderAction.HOLD)
    levels = _build_trade_levels(action, signals["market_metrics"])

    if is_chinese_output():
        reasoning_parts = [
            f"研究计划给出的建议为 `{recommendation}`，而技术面显式信号为 `{market_rating}`。"
        ]
        if sentiment_band:
            reasoning_parts.append(
                f"情绪面仍为 `{sentiment_band}`，执行时需要尊重“{_market_bias_cn(market_rating)}、情绪偏暖”的组合状态。"
            )
        else:
            reasoning_parts.append("本轮没有可用的稳定情绪覆盖信号。")

        sizing = {
            TraderAction.BUY: "建议分批建仓，不宜一次性满仓进入。",
            TraderAction.HOLD: "当前不建议新增仓位。",
            TraderAction.SELL: "若已持仓，应优先减仓或退出，而不是逆势补仓。",
        }[action]
    else:
        reasoning_parts = [
            f"The research plan recommendation is `{recommendation}`, while the explicit technical signal is `{market_rating}`."
        ]
        if sentiment_band:
            reasoning_parts.append(
                f"Sentiment remains `{sentiment_band}`, so execution should respect the current mix where {_market_bias_en(market_rating)} while softer qualitative support stays warmer."
            )
        else:
            reasoning_parts.append("No deterministic sentiment override was available.")

        sizing = {
            TraderAction.BUY: "Scale in gradually rather than entering full size immediately.",
            TraderAction.HOLD: "No new position sizing is recommended at this stage.",
            TraderAction.SELL: "If a position already exists, prioritize trimming or exiting rather than averaging down.",
        }[action]

    proposal = TraderProposal(
        action=action,
        reasoning=" ".join(reasoning_parts),
        entry_price=levels["entry_price"],
        stop_loss=levels["stop_loss"],
        position_sizing=sizing,
    )
    return render_trader_proposal(proposal)


def build_portfolio_decision_text(state: Mapping[str, object]) -> str:
    signals = _build_signal_snapshot(state)
    research_rating = parse_rating(
        str(state.get("investment_plan") or ""),
        default=str(signals["research_rating"]),
    )
    trader_text = str(state.get("trader_investment_plan") or "")
    trader_action = "Hold"
    if "FINAL TRANSACTION PROPOSAL: **BUY**" in trader_text:
        trader_action = "Buy"
    elif "FINAL TRANSACTION PROPOSAL: **SELL**" in trader_text:
        trader_action = "Sell"

    market_rating = str(signals["market_rating"])
    sentiment_band = signals["sentiment_band"]

    pm_rating = research_rating
    if research_rating == "Hold" and trader_action == "Sell":
        pm_rating = "Underweight"
    elif research_rating == "Overweight" and trader_action == "Sell":
        pm_rating = "Hold"
    elif research_rating == "Underweight" and trader_action == "Buy":
        pm_rating = "Hold"

    trader_action_enum = {
        "Buy": TraderAction.BUY,
        "Hold": TraderAction.HOLD,
        "Sell": TraderAction.SELL,
    }.get(trader_action, TraderAction.HOLD)
    levels = _build_trade_levels(trader_action_enum, signals["market_metrics"])

    if is_chinese_output():
        summary = {
            "Buy": "可以分批增加敞口，但要通过纪律化执行管理风险，而不是追涨。",
            "Overweight": "可适度提高仓位，但应保留后续加减仓空间，并继续观察技术趋势修复情况。",
            "Hold": "在技术面与情绪面冲突尚未收敛前，维持中性仓位更稳妥。",
            "Underweight": "当前应维持低于常规的仓位水平，在技术弱势阶段避免激进入场。",
            "Sell": "当证据仍以技术性弱势为主时，不宜继续持有敞口。",
        }[pm_rating]

        thesis_parts = [
            f"当前最清晰的确定性输入来自市场报告，其核心信号为 `{market_rating}`。"
        ]
        if sentiment_band:
            thesis_parts.append(f"情绪面显示 `{sentiment_band}`，因此它构成的是交叉信号，而不是一致确认。")
        else:
            thesis_parts.append("本轮未提取到稳定的情绪头部，因此情绪面没有被用作方向性覆盖。")
        thesis_parts.append("基本面数据包仅作为事实材料保留，不对原始报表之外的信息追加多空推断。")
        thesis_parts.append(f"在这种组合下，最终组合层面的立场上限被约束在 `{pm_rating}`。")

        horizon = {
            "Buy": "3-6个月",
            "Overweight": "1-3个月",
            "Hold": "2-6周",
            "Underweight": "2-6周",
            "Sell": "立即执行 / 至技术修复前",
        }[pm_rating]
    else:
        summary = {
            "Buy": "Add exposure in controlled tranches and manage risk through disciplined execution rather than chasing price.",
            "Overweight": "Increase exposure modestly, but keep room to add only if the technical trend improves.",
            "Hold": "Maintain a neutral stance until the conflict between technicals and softer qualitative signals resolves.",
            "Underweight": "Keep exposure below normal size and avoid aggressive entries while the technical trend remains weak.",
            "Sell": "Do not carry exposure while the evidence set remains dominated by a bearish technical regime.",
        }[pm_rating]

        thesis_parts = [
            f"The clearest deterministic input is the market report's `{market_rating}` signal."
        ]
        if sentiment_band:
            thesis_parts.append(f"Sentiment reads `{sentiment_band}`, creating a cross-signal rather than a clean confirmation.")
        else:
            thesis_parts.append("No deterministic sentiment header was available, so sentiment was not used as a directional override.")
        thesis_parts.append(
            "The fundamentals package was preserved as factual source material, but no additional bullish or bearish score was inferred from raw statements alone."
        )
        thesis_parts.append(f"Given that mix, the final portfolio stance is capped at `{pm_rating}`.")

        horizon = {
            "Buy": "3-6 months",
            "Overweight": "1-3 months",
            "Hold": "2-6 weeks",
            "Underweight": "2-6 weeks",
            "Sell": "Immediate / until technical repair is visible",
        }[pm_rating]

    decision = PortfolioDecision(
        rating=_safe_rating_enum(pm_rating),
        executive_summary=summary,
        investment_thesis=" ".join(thesis_parts),
        price_target=levels["price_target"],
        time_horizon=horizon,
    )
    return render_pm_decision(decision)
