import functools
import logging
from typing import Any, Mapping, Optional
from pathlib import Path
import sys

import yfinance as yf
from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.market_data_validation_tools import (
    get_verified_market_snapshot
)

logger = logging.getLogger(__name__)

SKILL_ROOT = Path(__file__).resolve().parents[3]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tushare_dependency import load_tushare_service


def get_output_language() -> str:
    from tradingagents.dataflows.config import get_config

    lang = str(get_config().get("output_language", "English") or "English").strip()
    return lang or "English"


def is_chinese_output() -> bool:
    return get_output_language().lower() == "chinese"


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    lang = get_output_language()
    if lang.lower() == "english":
        return ""
    return (
        f" IMPORTANT: You must write your entire response in {lang}. "
        "This includes all section headers, bullet points, tables, labels, and narrative text. "
        "Do not output any explanatory prose in English unless a raw tool result is already in English."
    )


def get_evidence_guardrails() -> str:
    """Prompt guardrails that forbid unsupported factual invention."""
    return (
        " Evidence discipline rules: "
        "1. Only use facts, numbers, dates, ratios, business descriptions, and signals that are explicitly present in the provided reports or tool outputs. "
        "2. If a fact is missing, say it is unknown or not provided; do not estimate or fill gaps. "
        "3. Do not invent customer concentration, restricted cash, market share, policy subsidies, orders, product launches, margin trends, institutional behavior, or valuation targets unless explicitly stated in the provided material. "
        "4. If different reports conflict, call out the conflict explicitly and prefer the deterministic report sections over narrative speculation. "
        "5. When making a recommendation, tie it to the evidence that is actually present and avoid adding new unsupported reasoning."
    )


def _clean_identity_value(value: Any) -> Optional[str]:
    """Return a trimmed string, or None for empty / placeholder-ish values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "null"}:
        return None
    return cleaned


@functools.lru_cache(maxsize=256)
def resolve_instrument_identity(ticker: str) -> dict:
    """Resolve deterministic identity metadata (company name, sector, …) for a ticker.

    This exists to stop the pipeline from hallucinating a *different* company
    when a chart pattern suggests a different industry than the real one
    (#814): without a ground-truth name, the market analyst would pattern-match
    the price action to a narrative and invent an identity that then cascaded
    through every downstream agent.

    Best-effort by design: if yfinance is unavailable, rate-limited, or doesn't
    recognise the ticker, we return ``{}`` and the caller falls back to
    ticker-only context rather than failing before analysis starts. Cached so
    the lookup happens at most once per ticker per process.
    """
    from tradingagents.dataflows.china.market_detector import detect_market_type, MarketType
    
    market = detect_market_type(ticker)
    if market == MarketType.CHINA_A:
        try:
            service = load_tushare_service()
            profile = service.get_company_profile(ticker)
            company = profile.get("company", {})
            identity = {}
            if company.get("name"):
                identity["company_name"] = company["name"]
            if company.get("industry"):
                identity["industry"] = company["industry"]
            if company.get("area"):
                identity["sector"] = company["area"]
            if company.get("market"):
                identity["exchange"] = company["market"]
            if identity:
                identity["quote_type"] = "EQUITY"
                return identity
        except Exception as exc:
            logger.debug("Could not resolve A-share identity for %s via Tushare: %s", ticker, exc)
        return {}  # Do not fall back to yfinance for A-shares to avoid incorrect mapping/collisions

    try:
        info = yf.Ticker(ticker.upper()).info or {}
    except Exception as exc:  # noqa: BLE001 — fail open, never block the run
        logger.debug("Could not resolve instrument identity for %s: %s", ticker, exc)
        return {}

    identity: dict[str, str] = {}
    company_name = _clean_identity_value(info.get("longName")) or _clean_identity_value(
        info.get("shortName")
    )
    if company_name:
        identity["company_name"] = company_name
    for source_key, target_key in (
        ("sector", "sector"),
        ("industry", "industry"),
        ("exchange", "exchange"),
        ("quoteType", "quote_type"),
    ):
        value = _clean_identity_value(info.get(source_key))
        if value:
            identity[target_key] = value
    return identity


def build_instrument_context(
    ticker: str,
    asset_type: str = "stock",
    identity: Optional[Mapping[str, str]] = None,
) -> str:
    """Describe the exact instrument so agents preserve identity and ticker.

    When ``identity`` is provided (resolved deterministically via
    :func:`resolve_instrument_identity`), the company name and business
    classification are injected so agents anchor to the real company rather
    than pattern-matching the price chart to a wrong one (#814).
    """
    is_crypto = asset_type == "crypto"
    instrument_label = "asset" if is_crypto else "instrument"
    context = (
        f"The {instrument_label} to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
    )

    details = []
    if identity:
        name = identity.get("company_name") or identity.get("name")
        if name:
            details.append(f"{'Name' if is_crypto else 'Company'}: {name}")
        sector, industry = identity.get("sector"), identity.get("industry")
        if sector and industry:
            details.append(f"Business classification: {sector} / {industry}")
        elif sector:
            details.append(f"Sector: {sector}")
        elif industry:
            details.append(f"Industry: {industry}")
        if identity.get("exchange"):
            details.append(f"Exchange: {identity['exchange']}")

    if details:
        context += (
            f" Resolved identity: {'; '.join(details)}. "
            "Do not substitute a different company or ticker unless a tool "
            "result explicitly disproves this resolved identity."
        )

    if is_crypto:
        context += (
            " Treat it as a crypto asset rather than a company, and do not "
            "assume company fundamentals are available."
        )
    return context


def get_instrument_context_from_state(state: Mapping[str, Any]) -> str:
    """Return the instrument context for the current run.

    Prefers the identity-resolved context computed once at run start and
    stored on the state (see ``TradingAgentsGraph.resolve_instrument_context``).
    Falls back to a ticker-only context — with no network lookup — when the
    state was constructed without it (bare programmatic states, tests), so a
    consumer is never forced to make a yfinance call mid-graph.
    """
    context = state.get("instrument_context")
    if isinstance(context, str) and context.strip():
        return context
    return build_instrument_context(
        str(state["company_of_interest"]),
        state.get("asset_type", "stock"),
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add a context-anchored placeholder.

        The placeholder must not be a bare ``"Continue"``: some
        OpenAI-compatible providers interpret that literally as the user task
        and produce output about the word "continue" instead of analysing the
        instrument (#888). Anchoring it to the resolved instrument context and
        date keeps the next analyst on-task even if the provider treats the
        placeholder as a standalone request.
        """
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "the requested date")
        placeholder = HumanMessage(
            content=(
                f"Proceed with your assigned analysis for this workflow. "
                f"{instrument_context} The analysis date is {trade_date}."
            )
        )
        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
