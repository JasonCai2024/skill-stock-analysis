"""Deterministic decision builders for manager/trader/final-PM nodes.

These helpers intentionally avoid free-form LLM synthesis at the final
decision layers. They only consume already-produced report text and map a
small set of explicit signals into stable markdown outputs.
"""

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
from tradingagents.agents.utils.rating import parse_rating


_SENTIMENT_HEADER_RE = re.compile(
    r"\*\*Overall Sentiment:\*\*\s*\*\*(?P<band>[^*]+)\*\*\s*\(Score:\s*(?P<score>[0-9.]+)/10\)",
    re.IGNORECASE,
)
_SENTIMENT_FALLBACK_RE = re.compile(
    r"\*\*overall_band\*\*:\s*(?P<band>.+?)\s*$.*?\*\*overall_score\*\*:\s*(?P<score>[0-9.]+)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)


def _extract_sentiment_band(report: str) -> tuple[Optional[str], Optional[float]]:
    text = report or ""
    match = _SENTIMENT_HEADER_RE.search(text)
    if not match:
        match = _SENTIMENT_FALLBACK_RE.search(text)
    if not match:
        return None, None
    score = None
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


def _build_signal_snapshot(state: Mapping[str, object]) -> dict[str, object]:
    market_report = str(state.get("market_report") or "")
    sentiment_report = str(state.get("sentiment_report") or "")
    news_report = str(state.get("news_report") or "")
    fundamentals_report = str(state.get("fundamentals_report") or "")

    market_rating = parse_rating(market_report, default="Hold")
    sentiment_band, sentiment_score = _extract_sentiment_band(sentiment_report)
    sentiment_rating = _sentiment_band_to_rating(sentiment_band)
    news_rating = parse_rating(news_report, default="Hold")

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
    }


def build_research_plan_text(state: Mapping[str, object]) -> str:
    signals = _build_signal_snapshot(state)
    market_rating = str(signals["market_rating"])
    sentiment_band = signals["sentiment_band"]
    sentiment_score = signals["sentiment_score"]
    research_rating = str(signals["research_rating"])
    has_fundamentals = bool(signals["has_fundamentals"])

    rationale_parts = [
        f"Technical market evidence is the strongest explicit signal in this run and currently maps to `{market_rating}`.",
    ]
    if sentiment_band:
        sentiment_text = f"Sentiment is `{sentiment_band}`"
        if sentiment_score is not None:
            sentiment_text += f" ({sentiment_score:.1f}/10)"
        rationale_parts.append(sentiment_text + ", which partially offsets but does not override the technical picture.")
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
    recommendation = parse_rating(str(state.get("investment_plan") or ""), default=str(signals["research_rating"]))
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

    reasoning_parts = [
        f"The research plan recommendation is `{recommendation}`, while the explicit technical signal is `{market_rating}`."
    ]
    if sentiment_band:
        reasoning_parts.append(f"Sentiment remains `{sentiment_band}`, so execution should respect the conflict between price trend and softer qualitative support.")
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
        position_sizing=sizing,
    )
    return render_trader_proposal(proposal)


def build_portfolio_decision_text(state: Mapping[str, object]) -> str:
    signals = _build_signal_snapshot(state)
    research_rating = parse_rating(str(state.get("investment_plan") or ""), default=str(signals["research_rating"]))
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

    summary = {
        "Buy": "Add exposure in controlled tranches and manage risk through disciplined execution rather than chasing price.",
        "Overweight": "Increase exposure modestly, but keep room to add only if the technical trend improves.",
        "Hold": "Maintain a neutral stance until the conflict between technicals and softer qualitative signals resolves.",
        "Underweight": "Keep exposure below normal size and avoid aggressive entries while the technical trend remains weak.",
        "Sell": "Do not carry exposure while the evidence set remains dominated by a bearish technical regime.",
    }[pm_rating]

    thesis_parts = [
        f"The clearest deterministic input is the market report's `{market_rating}` signal.",
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
        time_horizon=horizon,
    )
    return render_pm_decision(decision)
