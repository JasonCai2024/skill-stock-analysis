from typing import Annotated

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance, get_news_summary_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .symbol_utils import NoMarketDataError

# China / A-share data sources
from .china.market_detector import is_china_a_share, detect_market_type, MarketType
from .china import tushare_stock
from .china import tushare_financials
from .china import akshare_wrapper
from .china import eastmoney_news

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support.

    Market detection order:
      1. A-share (.SS/.SH/.SZ/.BJ)  → _route_china()
      2. Hong Kong (.HK)              → _route_hk()   (yfinance)
      3. US / international           → existing vendors
    """
    # ── Market detection ───────────────────────────────────────────────────────
    symbol = args[0] if args else ""
    market = detect_market_type(symbol)

    if market == MarketType.CHINA_A:
        return _route_china(method, *args, **kwargs)
    elif market == MarketType.CHINA_HK:
        return _route_hk(method, *args, **kwargs)
    # ── US / international vendors ──────────────────────────────────────────────
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Rate limits: try the next vendor
        except NoMarketDataError as e:
            last_no_data = e  # No data here; another vendor may have it
            continue
        except Exception as e:
            # A fallback vendor failing for an incidental reason (e.g. no API
            # key configured) must not crash the call when another vendor
            # already determined the symbol simply has no data. Remember the
            # first error so a genuine primary-vendor failure still surfaces.
            if first_error is None:
                first_error = e
            continue

    # If any vendor reported "no data", the symbol is genuinely unavailable.
    # Return one explicit, instructive sentinel rather than a vendor-specific
    # empty string, so the agent reports "unavailable" instead of inventing a
    # value. This takes precedence over incidental fallback errors.
    if last_no_data is not None:
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        return (
            f"NO_DATA_AVAILABLE: No market data found for '{sym}'{resolved} from "
            f"any configured vendor. The symbol may be invalid, delisted, or not "
            f"covered by Yahoo Finance / Alpha Vantage. Do not estimate or "
            f"fabricate values — report that data is unavailable for this symbol."
        )

    # No vendor returned data and none reported clean "no data" — surface the
    # first real error (e.g. the primary vendor's network failure).
    if first_error is not None:
        raise first_error

    raise RuntimeError(f"No available vendor for '{method}'")


# ══════════════════════════════════════════════════════════════════════════════
# A-share routing — Tushare (primary) + AkShare (fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _route_china(method: str, *args, **kwargs):
    """
    Route A-share data requests to Tushare (primary) or AkShare (fallback).
    Each method returns a string or raises an exception.
    """
    # Map method → (tushare_fn, akshare_fn_or_None)
    CHINA_METHODS = {
        # core_stock_apis
        "get_stock_data": (
            tushare_stock.get_tushare_stock_data,
            None,  # yfinance can't serve A-shares well
        ),
        # technical_indicators
        "get_indicators": (
            tushare_stock.get_tushare_indicators,
            None,
        ),
        # fundamental_data
        "get_fundamentals": (
            tushare_financials.get_tushare_fundamentals,
            None,
        ),
        "get_balance_sheet": (
            tushare_financials.get_tushare_balance_sheet,
            None,
        ),
        "get_cashflow": (
            tushare_financials.get_tushare_cashflow,
            None,
        ),
        "get_income_statement": (
            tushare_financials.get_tushare_income_statement,
            None,
        ),
        # news_data — 东方财富个股新闻（精准）+ yfinance 全局宏观新闻降级
        "get_news": (
            eastmoney_news.get_eastmoney_news,
            get_news_yfinance,
        ),
        "get_global_news": (
            eastmoney_news.get_eastmoney_macro_news,
            get_global_news_yfinance,
        ),
        # 舆情摘要 — A股用东方财富关键词情感分析，港股用 yfinance
        "get_news_summary": (
            eastmoney_news.get_eastmoney_news_summary,
            get_news_summary_yfinance,
        ),
        # AkShare-only (no Tushare equivalent for insider/announcements)
        "get_announcement": (
            akshare_wrapper.get_akshare_announcement,
            None,
        ),
        "get_social_sentiment": (
            akshare_wrapper.get_akshare_social_sentiment,
            None,
        ),
        # Skip: get_insider_transactions (A-share insider data requires premium)
    }

    if method not in CHINA_METHODS:
        return (
            f"NO_DATA_AVAILABLE: Method '{method}' is not supported for A-share stocks. "
            f"Supported A-share methods: {list(CHINA_METHODS.keys())}"
        )

    primary_fn, fallback_fn = CHINA_METHODS[method]
    sentinel_prefixes = ("NO_DATA_AVAILABLE", "Error retrieving", "Error:")

    def _is_real_result(result):
        """Return True only if this is an actual data result (not a sentinel or error)."""
        return (
            result is not None
            and result != ""
            and not any(result.startswith(p) for p in sentinel_prefixes)
        )

    # Try primary first
    if primary_fn is not None:
        try:
            result = primary_fn(*args, **kwargs)
            # Real result → use it; sentinel → try fallback
            if _is_real_result(result):
                return result
        except Exception:
            pass  # Exception → try fallback

    # Try fallback
    if fallback_fn is not None:
        try:
            result = fallback_fn(*args, **kwargs)
            if result is not None and result != "":
                return result
        except Exception:
            pass

    # All failed
    symbol = args[0] if args else "unknown"
    return (
        f"NO_DATA_AVAILABLE: No data available for A-share '{symbol}' "
        f"via Tushare or AkShare for method '{method}'. "
        f"The symbol may be invalid, delisted, or require higher Tushare credit tier."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Hong Kong (.HK) routing — Yahoo Finance (primary)
# ══════════════════════════════════════════════════════════════════════════════

def _route_hk(method: str, *args, **kwargs):
    """
    Route Hong Kong stock data requests to Yahoo Finance.
    yfinance natively supports .HK tickers (e.g. 0700.HK).
    """
    HK_METHODS = {
        "get_stock_data":      (get_YFin_data_online,              [get_alpha_vantage_stock]),
        "get_indicators":      (get_stock_stats_indicators_window, [get_alpha_vantage_indicator]),
        "get_fundamentals":    (get_yfinance_fundamentals,         [get_alpha_vantage_fundamentals]),
        "get_balance_sheet":   (get_yfinance_balance_sheet,        [get_alpha_vantage_balance_sheet]),
        "get_cashflow":        (get_yfinance_cashflow,             [get_alpha_vantage_cashflow]),
        "get_income_statement":(get_yfinance_income_statement,      [get_alpha_vantage_income_statement]),
        "get_news":            (get_news_yfinance,                 [get_alpha_vantage_news]),
        "get_news_summary":   (get_news_summary_yfinance,        []),
        "get_global_news":     (get_global_news_yfinance,          [get_alpha_vantage_global_news]),
        "get_insider_transactions": (get_yfinance_insider_transactions, [get_alpha_vantage_insider_transactions]),
    }

    if method not in HK_METHODS:
        return (
            f"NO_DATA_AVAILABLE: Method '{method}' is not supported for Hong Kong stocks."
        )

    primary_fn, fallback_fns = HK_METHODS[method]

    # Try primary
    try:
        result = primary_fn(*args, **kwargs)
        if result and not result.startswith("NO_DATA_AVAILABLE"):
            return result
    except Exception:
        pass

    # Try fallbacks
    for fn in fallback_fns:
        try:
            result = fn(*args, **kwargs)
            if result and not result.startswith("NO_DATA_AVAILABLE"):
                return result
        except Exception:
            pass

    symbol = args[0] if args else "unknown"
    return (
        f"NO_DATA_AVAILABLE: No data available for Hong Kong stock '{symbol}' "
        f"via Yahoo Finance or Alpha Vantage. "
        f"The symbol may be invalid or delisted."
    )