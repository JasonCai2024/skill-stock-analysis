"""
TradingAgents stock analysis wrapper for skill-stock-analysis.

Usage:
    python run_analysis.py <ticker-or-company-name>

This wrapper depends on the sibling skill
``skill-tushare-servicehub-assistant`` for company resolution and all
Tushare/ServiceHub data access.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tushare_dependency import load_tushare_service


def resolve_ticker(name_or_ticker: str) -> str:
    """Return ticker if already normalized, otherwise resolve by company."""
    identifier = name_or_ticker.strip()

    if re.match(r"^\d{6}\.(SZ|SS|SH|HK|BJ)$", identifier, re.IGNORECASE):
        return identifier.upper()

    service = load_tushare_service()
    resolved = service.resolve_company(identifier)
    company = resolved["company"]
    ticker = str(company["ts_code"]).upper()
    print(f"[stock-analysis] '{identifier}' -> {ticker}", file=sys.stderr)
    return ticker


def run_analysis(ticker: str) -> Path:
    """Run TradingAgents and return the saved JSON report path."""
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.dataflows.china.market_detector import MarketType, detect_market_type
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    today = date.today().isoformat()
    config = DEFAULT_CONFIG.copy()
    config["checkpoint_enabled"] = False

    if detect_market_type(ticker) == MarketType.CHINA_A:
        config["output_language"] = "Chinese"

    print(f"[stock-analysis] Running analysis for {ticker} ({today})...", file=sys.stderr)

    ta = TradingAgentsGraph(debug=True, config=config)
    ta.propagate(ticker, today)

    results_dir = Path(DEFAULT_CONFIG.get("results_dir") or (SKILL_ROOT / "reports" / "logs"))
    log_dir = results_dir / ticker / "TradingAgentsStrategy_logs"
    today_str = date.today().isoformat()

    candidates = list(log_dir.glob(f"full_states_log_{today_str}.json"))
    if candidates:
        return candidates[0]

    candidates = sorted(
        log_dir.glob("full_states_log_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        print(
            f"[stock-analysis] No log for {today_str}; using most recent: {candidates[0].name}",
            file=sys.stderr,
        )
        return candidates[0]

    raise FileNotFoundError(
        f"Could not locate saved report for {ticker} under {log_dir}. "
        "Make sure TradingAgents finished writing its log files."
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python run_analysis.py <ticker-or-company-name>", file=sys.stderr)
        sys.exit(1)

    identifier = sys.argv[1]

    try:
        ticker = resolve_ticker(identifier)
        report_path = run_analysis(ticker)
        try:
            from render_report import render_report

            render_report(str(report_path))
        except Exception as render_error:
            print(
                f"[stock-analysis] Warning: Failed to render markdown report: {render_error}",
                file=sys.stderr,
            )

        print(report_path)
    except Exception as exc:
        print(f"[stock-analysis] Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
