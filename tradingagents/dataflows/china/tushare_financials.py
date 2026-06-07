"""
Tushare Pro A股财务报表 — 同步封装
利润表、资产负债表、现金流量表

优先使用 ServiceHub Tushare 代理（ SERVICETUBER_USERNAME / PASSTOKEN ）；
若未配置则回退到本地 Tushare Token（ TUSHARE_TOKEN + tushare 库）。
"""
from typing import Annotated
import os
import pandas as pd
from datetime import datetime

# ── 本地 Tushare（备用） ─────────────────────────────────────────────────────
try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")

# ── ServiceHub Tushare 代理（优先） ──────────────────────────────────────────
_proxy_client = None  # type: ignore


def _get_proxy():
    global _proxy_client
    if _proxy_client is None:
        try:
            from . import tushare_proxy_client as pc
            if pc._is_configured():
                _proxy_client = pc
                return _proxy_client
        except Exception:
            pass
        _proxy_client = False
    return _proxy_client if _proxy_client else None


def _normalize_ts_code(symbol: str) -> str:
    if "." in symbol:
        s = symbol.upper()
        if s.endswith(".SS"):
            return s[:-3] + ".SH"
        return s
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith(("60", "68", "90")):
            return f"{symbol}.SH"
        elif symbol.startswith(("83", "43", "87")):
            return f"{symbol}.BJ"
        else:
            return f"{symbol}.SZ"
    return symbol.upper()


def _is_rate_limit_error(error_msg: str) -> bool:
    keywords = [
        "每分钟最多访问", "每分钟最多", "rate limit",
        "too many requests", "访问频率", "请求过于频繁",
        "积分不足", "权限", "quota"
    ]
    lower = error_msg.lower()
    return any(kw in lower for kw in keywords)


def _connect_tushare():
    """
    返回 (api, connected)。
    - api=None, connected=True  → 走 ServiceHub 代理
    - api!=None, connected=True → 走本地 tushare 库
    - connected=False           → 不可用
    """
    if _get_proxy() is not None:
        return None, True

    if not TUSHARE_AVAILABLE or not TUSHARE_TOKEN:
        return None, False
    try:
        ts.set_token(TUSHARE_TOKEN)
        api = ts.pro_api()
        api.stock_basic(list_status="L", limit=1)
        return api, True
    except Exception:
        return None, False


def _fmt(val) -> str:
    """格式化数值，保留合理精度

    注意：daily_basic 的 total_mv / float_mv 单位是亿元（亿 = 1e8 元）。
    其他字段通常以元为单位。
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    try:
        v = float(val)
        # Tushare daily_basic.total_mv / circ_mv 单位是 万元
        # 万元数据且 >= 1亿（v >= 1e4 万元 = 1e8 元 = 1亿）→ 转为"XXX亿"显示
        # 其他字段（revenue/profit 等）单位是 元，>= 1亿（v >= 1e8）→ "XXX亿"
        if abs(v) >= 1e4:
            # 万元量级数据（total_mv/circ_mv）：除以 1e4 转亿
            return f"{v/1e4:.2f}亿"
        elif abs(v) >= 1e2:
            # 百元以上数据（pe/pb/ratios）→ 直接显示
            return f"{v:.2f}"
        elif abs(v) >= 1:
            # 小数十以内（ROE%/利润率等）→ 两位小数
            return f"{v:.2f}"
        else:
            return f"{v:.4f}"
    except (ValueError, TypeError):
        return str(val)


def get_tushare_fundamentals(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format (not used)"] = None,
):
    """
    获取 A股公司概况，对标 yfinance 的 get_fundamentals。
    合并展示：公司信息 + 估值 + 财务摘要
    """
    api, connected = _connect_tushare()
    if not connected:
        return (
            f"NO_DATA_AVAILABLE: Neither ServiceHub proxy nor local Tushare token is configured for '{ticker}'. "
            f"Set SERVICETUBER_USERNAME/PASSTOKEN or TUSHARE_TOKEN."
        )

    ts_code = _normalize_ts_code(ticker)
    proxy = _get_proxy()

    try:
        # 1. 基本信息
        if proxy:
            basic = proxy.stock_basic(ts_code=ts_code)
        else:
            basic = api.stock_basic(ts_code=ts_code, fields="ts_code,symbol,name,area,industry,market,list_date")
        if basic is None or basic.empty:
            return f"NO_DATA_AVAILABLE: No basic info found for '{ticker}' via Tushare."

        row = basic.iloc[0]
        name = row.get("name", ts_code)

        # 2. 估值指标 (daily_basic)
        if proxy:
            daily = proxy.daily_basic(ts_code=ts_code)
        else:
            daily = api.daily_basic(ts_code=ts_code, trade_date=datetime.now().strftime("%Y%m%d"))
        if daily is None or daily.empty:
            if proxy:
                daily = proxy.daily_basic(ts_code=ts_code)
            else:
                daily = api.daily_basic(ts_code=ts_code, limit=1)

        valuation = {}
        if daily is not None and not daily.empty:
            dr = daily.iloc[0]
            valuation = {
                "最新价 (close)": dr.get("close"),
                "总市值 (total_mv)": dr.get("total_mv"),
                "流通市值 (float_mv)": dr.get("float_mv"),
                "市盈率 PE": dr.get("pe"),
                "市净率 PB": dr.get("pb"),
                "市销率 PS": dr.get("ps"),
                "换手率 (turnover)": dr.get("turnover_rate"),
                "量比": dr.get("vol_ratio"),
                "振幅": dr.get("amplitude"),
            }

        # 3. 财务指标
        if proxy:
            fin_indicator = proxy.fina_indicator(ts_code=ts_code, start_date="20180101")
            if fin_indicator is not None and not fin_indicator.empty:
                fin_indicator = fin_indicator.head(8)
        else:
            fin_indicator = api.fina_indicator(ts_code=ts_code, start_date="20180101", limit=8)
        fin_summary = {}
        if fin_indicator is not None and not fin_indicator.empty:
            fi = fin_indicator.iloc[0]
            fin_summary = {
                "ROE (净资产收益率)": fi.get("roe"),
                "净利润率 (net_profit_ratio)": fi.get("net_profit_ratio"),
                "毛利率 (gross_profit_margin)": fi.get("gross_profit_margin"),
                "资产负债率 (debt_to_assets)": fi.get("debt_to_assets"),
                "流动比率 (current_ratio)": fi.get("current_ratio"),
                "应收账款周转天数": fi.get("arturndays"),
                "存货周转天数": fi.get("inventory_days"),
            }

        # 构建输出
        lines = [f"# A股公司概况: {name} ({ts_code})"]
        lines.append(f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        lines.append("## 基本信息")
        for k, v in [("公司名称", name), ("股票代码", ts_code),
                      ("地域", row.get("area")), ("行业", row.get("industry")),
                      ("上市日期", row.get("list_date"))]:
            if v:
                lines.append(f"  {k}: {v}")

        if valuation:
            lines.append("\n## 估值指标")
            for k, v in valuation.items():
                lines.append(f"  {k}: {_fmt(v)}")

        if fin_summary:
            lines.append("\n## 财务指标（最新季度）")
            for k, v in fin_summary.items():
                lines.append(f"  {k}: {_fmt(v)}")

        return "\n".join(lines)

    except Exception as e:
        if _is_rate_limit_error(str(e)):
            return f"NO_DATA_AVAILABLE: Tushare rate limit exceeded for '{ticker}'."
        return f"Error retrieving fundamentals for '{ticker}' from Tushare: {e}"


def get_tushare_balance_sheet(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """获取 A股资产负债表，对标 yfinance 的 get_balance_sheet"""
    api, connected = _connect_tushare()
    if not connected:
        return (
            f"NO_DATA_AVAILABLE: Neither ServiceHub proxy nor local Tushare token is configured for '{ticker}'. "
            f"Set SERVICETUBER_USERNAME/PASSTOKEN or TUSHARE_TOKEN."
        )

    ts_code = _normalize_ts_code(ticker)
    period = "1231" if freq == "annual" else ""
    proxy = _get_proxy()

    try:
        if proxy:
            df = proxy.balance_sheet(ts_code=ts_code, period=period, start_date="20180101")
        else:
            df = api.balancesheet(ts_code=ts_code, period=period, start_date="20180101")
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No balance sheet data for '{ticker}' via Tushare."

        # 取最近一期
        df = df.head(4)  # 最近4个报告期

        # 关键科目（中英文对照）
        key_items = {
            "total_liab": "负债合计",
            "total_asset": "资产合计",
            "total_hldr_eqy_exc_min_int": "股东权益合计",
            "accounts_payable": "应付账款",
            "advance_receipts": "预收款项",
            "total_current_liab": "流动负债合计",
            "total_non_current_liab": "非流动负债合计",
            "total_current_assets": "流动资产合计",
            "total_non_current_assets": "非流动资产合计",
            "fixed_assets": "固定资产",
            "intangible_assets": "无形资产",
            "good_will": "商誉",
            "short_term_loan": "短期借款",
            "long_term_loan": "长期借款",
            "bonds_payable": "应付债券",
            "inventories": "存货",
            "accounts_receivable": "应收账款",
            "cash_equi": "货币资金",
            " prepay": "预付款项",
            "other_current_assets": "其他流动资产",
        }

        lines = [f"# A股资产负债表: {ts_code}"]
        lines.append(f"# Period: {freq} | Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # 列头：报告期
        headers = []
        for _, r in df.iterrows():
            pd_str = str(r.get("end_date", "N/A"))
            headers.append(f"{pd_str[:4]}-{pd_str[4:6]}-{pd_str[6:8]}")
        lines.append("  | " + " | ".join(f"{h:>15}" for h in headers) + " |")
        lines.append("  | " + " | ".join("-" * 15 for _ in headers) + " |")

        for eng, chn in key_items.items():
            if eng not in df.columns:
                continue
            vals = []
            for _, r in df.iterrows():
                vals.append(_fmt(r.get(eng)))
            lines.append(f"  {chn:20s} | " + " | ".join(f"{v:>15}" for v in vals) + " |")

        return "\n".join(lines)

    except Exception as e:
        if _is_rate_limit_error(str(e)):
            return f"NO_DATA_AVAILABLE: Tushare rate limit exceeded for '{ticker}'."
        return f"Error retrieving balance sheet for '{ticker}' from Tushare: {e}"


def get_tushare_cashflow(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """获取 A股现金流量表，对标 yfinance 的 get_cashflow"""
    api, connected = _connect_tushare()
    if not connected:
        return (
            f"NO_DATA_AVAILABLE: Neither ServiceHub proxy nor local Tushare token is configured for '{ticker}'. "
            f"Set SERVICETUBER_USERNAME/PASSTOKEN or TUSHARE_TOKEN."
        )

    ts_code = _normalize_ts_code(ticker)
    period = "1231" if freq == "annual" else ""
    proxy = _get_proxy()

    try:
        if proxy:
            df = proxy.cashflow(ts_code=ts_code, period=period, start_date="20180101")
        else:
            df = api.cashflow(ts_code=ts_code, period=period, start_date="20180101")
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No cashflow data for '{ticker}' via Tushare."

        df = df.head(4)

        key_items = {
            "net_profit": "净利润",
            "operate_cash_inflow": "经营活动现金流入",
            "operate_cash_outflow": "经营活动现金流出",
            "net_operate_cash_flow": "经营活动现金流量净额",
            "invest_cash_inflow": "投资活动现金流入",
            "invest_cash_outflow": "投资活动现金流出",
            "net_invest_cash_flow": "投资活动现金流量净额",
            "finance_cash_inflow": "筹资活动现金流入",
            "finance_cash_outflow": "筹资活动现金流出",
            "net_finance_cash_flow": "筹资活动现金流量净额",
            "free_cash_flow": "自由现金流量",
            "capex": "购建固定资产等投资",
            "end_cash": "期末现金",
        }

        lines = [f"# A股现金流量表: {ts_code}"]
        lines.append(f"# Period: {freq} | Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        headers = []
        for _, r in df.iterrows():
            pd_str = str(r.get("end_date", "N/A"))
            headers.append(f"{pd_str[:4]}-{pd_str[4:6]}-{pd_str[6:8]}")
        lines.append("  | " + " | ".join(f"{h:>15}" for h in headers) + " |")
        lines.append("  | " + " | ".join("-" * 15 for _ in headers) + " |")

        for eng, chn in key_items.items():
            if eng not in df.columns:
                continue
            vals = [_fmt(r.get(eng)) for _, r in df.iterrows()]
            lines.append(f"  {chn:20s} | " + " | ".join(f"{v:>15}" for v in vals) + " |")

        return "\n".join(lines)

    except Exception as e:
        if _is_rate_limit_error(str(e)):
            return f"NO_DATA_AVAILABLE: Tushare rate limit exceeded for '{ticker}'."
        return f"Error retrieving cashflow for '{ticker}' from Tushare: {e}"


def get_tushare_income_statement(
    ticker: Annotated[str, "A-share ticker, e.g. 601127.SH or 601127.SS"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
):
    """获取 A股利润表，对标 yfinance 的 get_income_statement"""
    api, connected = _connect_tushare()
    if not connected:
        return (
            f"NO_DATA_AVAILABLE: Neither ServiceHub proxy nor local Tushare token is configured for '{ticker}'. "
            f"Set SERVICETUBER_USERNAME/PASSTOKEN or TUSHARE_TOKEN."
        )

    ts_code = _normalize_ts_code(ticker)
    period = "1231" if freq == "annual" else ""
    proxy = _get_proxy()

    try:
        if proxy:
            df = proxy.income(ts_code=ts_code, period=period, start_date="20180101")
        else:
            df = api.income(ts_code=ts_code, period=period, start_date="20180101")
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No income statement data for '{ticker}' via Tushare."

        df = df.head(4)

        key_items = {
            "revenue": "营业收入",
            "total_profit": "利润总额",
            "operate_profit": "营业利润",
            "total_income": "营业总收入",
            "operating_income": "营业利润",  # alias
            "net_profit": "净利润",
            "net_profit_attr_p": "归母净利润",
            "basic_eps": "基本每股收益",
            "diluted_eps": "稀释每股收益",
            "total_revenue": "营业总收入",
            "operating_cost": "营业成本",
            "selling_distribute_expense": "销售费用",
            "manage_finance_expense": "管理费用/财务费用",
            "rd_expense": "研发费用",
            "fin_expense": "财务费用",
            "invest_income": "投资收益",
            "non_operate_income": "营业外收入",
            "non_operate_expense": "营业外支出",
            "income_tax": "所得税",
        }

        lines = [f"# A股利润表: {ts_code}"]
        lines.append(f"# Period: {freq} | Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        headers = []
        for _, r in df.iterrows():
            pd_str = str(r.get("end_date", "N/A"))
            headers.append(f"{pd_str[:4]}-{pd_str[4:6]}-{pd_str[6:8]}")
        lines.append("  | " + " | ".join(f"{h:>15}" for h in headers) + " |")
        lines.append("  | " + " | ".join("-" * 15 for _ in headers) + " |")

        for eng, chn in key_items.items():
            if eng not in df.columns:
                continue
            vals = [_fmt(r.get(eng)) for _, r in df.iterrows()]
            lines.append(f"  {chn:20s} | " + " | ".join(f"{v:>15}" for v in vals) + " |")

        return "\n".join(lines)

    except Exception as e:
        if _is_rate_limit_error(str(e)):
            return f"NO_DATA_AVAILABLE: Tushare rate limit exceeded for '{ticker}'."
        return f"Error retrieving income statement for '{ticker}' from Tushare: {e}"
