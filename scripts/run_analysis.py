"""
TradingAgents stock analysis wrapper for skill-stock-analysis.

Usage:
    python run_analysis.py <ticker-or-company-name>

The skill is fully self-contained. No Tushare Token is needed —
all Tushare calls (including stock_basic for company name search)
go through the ServiceHub proxy.
"""

import sys
import os
import re
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve paths relative to this script
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
TRADINGAGENTS_ROOT = SKILL_ROOT / "tradingagents"


# ---------------------------------------------------------------------------
# Resolve ticker from company name (via ServiceHub Tushare proxy)
# ---------------------------------------------------------------------------

def resolve_ticker(name_or_ticker: str) -> str:
    """Return ticker if already in Tushare format, otherwise search by name."""
    name_or_ticker = name_or_ticker.strip()

    # Already a Tushare ticker?
    if re.match(r"^\d{6}\.(SZ|SS|SH|HK)$", name_or_ticker, re.IGNORECASE):
        return name_or_ticker.upper()

    # Search via ServiceHub Tushare proxy (no local Tushare Token needed)
    sys.path.insert(0, str(SCRIPT_DIR))

    from servicehub_tushare_client import ServiceHubTushareClient
    client = ServiceHubTushareClient()

    ok, ticker, extra = client.search_stock(name_or_ticker)
    if not ok:
        raise ValueError(f"ServiceHub Tushare search failed for '{name_or_ticker}': {ticker}")

    if extra == "no results":
        raise ValueError(f"No Tushare results for '{name_or_ticker}'")

    if extra == "multiple":
        print(f"[stock-analysis] Multiple matches for '{name_or_ticker}' — using first result: {ticker}", file=sys.stderr)
    else:
        print(f"[stock-analysis] '{name_or_ticker}' → {ticker}", file=sys.stderr)

    return ticker


# ---------------------------------------------------------------------------
# Run TradingAgents pipeline
# ---------------------------------------------------------------------------

def run_analysis(ticker: str) -> Path:
    """Run TradingAgents and return path to saved JSON report."""
    # Insert SKILL_ROOT (parent of tradingagents/), not TRADINGAGENTS_ROOT,
    # so 'import tradingagents' finds the skill's copy first.
    sys.path.insert(0, str(SKILL_ROOT))

    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    today = date.today().isoformat()
    config = DEFAULT_CONFIG.copy()
    config["checkpoint_enabled"] = False

    print(f"[stock-analysis] Running analysis for {ticker} ({today})...", file=sys.stderr)

    ta = TradingAgentsGraph(debug=True, config=config)
    ta.propagate(ticker, today)

    # Locate the saved JSON report
    log_dir = TRADINGAGENTS_ROOT / "reports" / "logs" / ticker / "TradingAgentsStrategy_logs"
    pattern = f"full_states_log_{date.today().isoformat()}.json"
    candidates = list(log_dir.glob(pattern))

    if candidates:
        return candidates[0]

    # Fallback: most recent log for this ticker
    candidates = sorted(log_dir.glob("full_states_log_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]

    raise FileNotFoundError(f"Could not locate saved report for {ticker}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_analysis.py <ticker-or-company-name>", file=sys.stderr)
        sys.exit(1)

    identifier = sys.argv[1]

    try:
        ticker = resolve_ticker(identifier)
        report_path = run_analysis(ticker)
        print(report_path)
    except Exception as e:
        print(f"[stock-analysis] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
