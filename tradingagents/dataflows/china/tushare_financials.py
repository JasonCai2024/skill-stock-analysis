"""A-share financial tools backed by the Tushare base skill."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated
import sys

import pandas as pd

SKILL_ROOT = Path(__file__).resolve().parents[3]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tushare_dependency import load_tushare_service


def _normalize_ts_code(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if "." in symbol:
        if symbol.endswith(".SS"):
            return symbol[:-3] + ".SH"
        return symbol
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith(("60", "68", "90")):
            return f"{symbol}.SH"
        if symbol.startswith(("83", "43", "87")):
            return f"{symbol}.BJ"
        return f"{symbol}.SZ"
    return symbol


def _fmt(val, unit: str = "yuan") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return str(val)

    if unit == "wan":
        if abs(num) >= 1e4:
            return f"{num / 1e4:.2f} billion yuan"
        if abs(num) >= 1:
            return f"{num:.2f} ten-thousand yuan"
        return f"{num:.4f}"

    if unit == "yuan":
        if abs(num) >= 1e8:
            return f"{num / 1e8:.2f} hundred-million yuan"
        if abs(num) >= 1e4:
            return f"{num / 1e4:.2f} ten-thousand yuan"
        if abs(num) >= 1:
            return f"{num:.2f}"
        return f"{num:.4f}"

    if abs(num) >= 1:
        return f"{num:.2f}"
    return f"{num:.4f}"


def _latest_rows(rows: list[dict], freq: str) -> list[dict]:
    sorted_rows = sorted(rows, key=lambda item: str(item.get("end_date", "")), reverse=True)
    if freq.lower() == "annual":
        sorted_rows = [row for row in sorted_rows if str(row.get("end_date", "")).endswith("1231")]
    return sorted_rows[:4]


def _period_headers(rows: list[dict]) -> list[str]:
    headers = []
    for row in rows:
        end_date = str(row.get("end_date", "N/A"))
        if len(end_date) == 8 and end_date.isdigit():
            headers.append(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}")
        else:
            headers.append(end_date)
    return headers


def _table_output(title: str, ts_code: str, freq: str, rows: list[dict], key_items: dict[str, str], ratio_fields: set[str] | None = None) -> str:
    ratio_fields = ratio_fields or set()
    headers = _period_headers(rows)
    lines = [f"# {title}: {ts_code}"]
    lines.append(f"# Period: {freq} | Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("  | " + " | ".join(f"{header:>20}" for header in headers) + " |")
    lines.append("  | " + " | ".join("-" * 20 for _ in headers) + " |")

    for field, label in key_items.items():
        present = any(field in row for row in rows)
        if not present:
            continue
        unit = "ratio" if field in ratio_fields else "yuan"
        values = [_fmt(row.get(field), unit=unit) for row in rows]
        lines.append(f"  {label:24s} | " + " | ".join(f"{value:>20}" for value in values) + " |")

    return "\n".join(lines)


def _load_finance_context(ticker: str) -> tuple[str, dict, dict, dict]:
    service = load_tushare_service()
    profile = service.get_company_profile(ticker)
    finance = service.get_finance_bundle(ticker, years=3, limit=20)
    market = service.get_market_bundle(ticker, days=30, limit=30)
    company = profile.get("company", {}) or finance.get("company", {}) or market.get("company", {})
    ts_code = str(company.get("ts_code") or _normalize_ts_code(ticker)).upper()
    return ts_code, profile, finance, market


def get_tushare_fundamentals(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format (not used)"] = None,
):
    try:
        ts_code, profile, finance, market = _load_finance_context(ticker)
        company = profile.get("company", {}) or finance.get("company", {})
        name = company.get("name") or ts_code
        indicator_rows = sorted(finance.get("fina_indicator", []), key=lambda item: str(item.get("end_date", "")), reverse=True)
        daily_basic_rows = sorted(market.get("market_daily_basic", []), key=lambda item: str(item.get("trade_date", "")), reverse=True)
        business_segments = profile.get("business_segments", [])

        lines = [f"# A-share company fundamentals: {name} ({ts_code})"]
        lines.append(f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        lines.append("## Basic Information")
        for label, value in [
            ("Company Name", name),
            ("Ticker", ts_code),
            ("Area", company.get("area")),
            ("Industry", company.get("industry")),
            ("Market", company.get("market")),
            ("List Date", company.get("list_date")),
        ]:
            if value:
                lines.append(f"  {label}: {value}")

        if daily_basic_rows:
            latest = daily_basic_rows[0]
            lines.append("\n## Valuation Snapshot")
            for label, field, unit in [
                ("Close", "close", "ratio"),
                ("PE", "pe", "ratio"),
                ("PB", "pb", "ratio"),
                ("Total MV", "total_mv", "wan"),
                ("Circulating MV", "circ_mv", "wan"),
                ("Turnover Rate", "turnover_rate", "ratio"),
            ]:
                lines.append(f"  {label}: {_fmt(latest.get(field), unit=unit)}")

        if indicator_rows:
            latest = indicator_rows[0]
            lines.append("\n## Financial Indicators")
            for label, field in [
                ("ROE", "roe"),
                ("Net Profit Margin", "net_profit_ratio"),
                ("Gross Profit Margin", "gross_profit_margin"),
                ("Debt To Assets", "debt_to_assets"),
                ("Current Ratio", "current_ratio"),
                ("Accounts Receivable Turnover Days", "arturndays"),
                ("Inventory Days", "invturndays"),
            ]:
                lines.append(f"  {label}: {_fmt(latest.get(field), unit='ratio')}")

        if business_segments:
            lines.append("\n## Main Business Segments")
            for segment in business_segments[:5]:
                item = segment.get("bz_item") or segment.get("item") or "N/A"
                sales = _fmt(segment.get("bz_sales"), unit="yuan")
                profit = _fmt(segment.get("bz_profit"), unit="yuan")
                lines.append(f"  {item}: sales={sales}, profit={profit}")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error retrieving fundamentals for '{ticker}' from Tushare base skill: {exc}"


def get_tushare_balance_sheet(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    try:
        ts_code, _, finance, _ = _load_finance_context(ticker)
        rows = _latest_rows(finance.get("balancesheet", []), freq)
        if not rows:
            return f"NO_DATA_AVAILABLE: No balance sheet data for '{ticker}'."

        key_items = {
            "total_liab": "Total Liabilities",
            "total_assets": "Total Assets",
            "total_hldr_eqy_exc_min_int": "Total Equity",
            "total_cur_liab": "Current Liabilities",
            "total_ncl": "Non-current Liabilities",
            "total_cur_assets": "Current Assets",
            "total_nca": "Non-current Assets",
            "fix_assets": "Fixed Assets",
            "intan_assets": "Intangible Assets",
            "goodwill": "Goodwill",
            "st_borr": "Short-term Borrowings",
            "lt_borr": "Long-term Borrowings",
            "bond_payable": "Bonds Payable",
            "inventories": "Inventories",
            "accounts_receiv": "Accounts Receivable",
            "money_cap": "Cash And Equivalents",
            "prepayment": "Prepayments",
            "oth_cur_assets": "Other Current Assets",
        }
        return _table_output("A-share Balance Sheet", ts_code, freq, rows, key_items)
    except Exception as exc:
        return f"Error retrieving balance sheet for '{ticker}' from Tushare base skill: {exc}"


def get_tushare_cashflow(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    try:
        ts_code, _, finance, _ = _load_finance_context(ticker)
        rows = _latest_rows(finance.get("cashflow", []), freq)
        if not rows:
            return f"NO_DATA_AVAILABLE: No cashflow data for '{ticker}'."

        key_items = {
            "net_profit": "Net Profit",
            "c_fr_sale_sg": "Operating Cash Inflow",
            "c_paid_goods_s": "Cash Paid For Goods And Services",
            "n_cashflow_act": "Net Operating Cash Flow",
            "stot_inflows_inv_act": "Investing Cash Inflow",
            "c_paid_invest": "Investing Cash Outflow",
            "n_cashflow_inv_act": "Net Investing Cash Flow",
            "c_fr_borrow": "Financing Cash Inflow",
            "c_paid_div_prof_int": "Financing Cash Outflow",
            "n_cash_flows_fnc_act": "Net Financing Cash Flow",
            "free_cashflow": "Free Cash Flow",
            "c_disp_withdrwl_invest": "Capex Related Cash",
            "c_cash_equ_end_period": "Ending Cash",
        }
        return _table_output("A-share Cashflow", ts_code, freq, rows, key_items)
    except Exception as exc:
        return f"Error retrieving cashflow for '{ticker}' from Tushare base skill: {exc}"


def get_tushare_income_statement(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    try:
        ts_code, _, finance, _ = _load_finance_context(ticker)
        rows = _latest_rows(finance.get("income", []), freq)
        if not rows:
            return f"NO_DATA_AVAILABLE: No income statement data for '{ticker}'."

        key_items = {
            "revenue": "Revenue",
            "total_profit": "Total Profit",
            "operate_profit": "Operating Profit",
            "total_revenue": "Total Revenue",
            "oper_cost": "Operating Cost",
            "sell_exp": "Selling Expense",
            "admin_exp": "Administrative Expense",
            "fin_exp": "Financial Expense",
            "rd_exp": "R&D Expense",
            "invest_income": "Investment Income",
            "non_oper_income": "Non-operating Income",
            "non_oper_exp": "Non-operating Expense",
            "income_tax": "Income Tax",
            "n_income": "Net Income",
            "n_income_attr_p": "Net Income Parent",
            "basic_eps": "Basic EPS",
            "diluted_eps": "Diluted EPS",
        }
        ratio_fields = {"basic_eps", "diluted_eps"}
        return _table_output("A-share Income Statement", ts_code, freq, rows, key_items, ratio_fields=ratio_fields)
    except Exception as exc:
        return f"Error retrieving income statement for '{ticker}' from Tushare base skill: {exc}"
