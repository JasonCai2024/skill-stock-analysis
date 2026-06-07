"""
ServiceHub Tushare 代理客户端
通过 ServiceHub HTTP API 透传任意 Tushare REST 调用，返回 pandas.DataFrame。
用户只需配置 ServiceHub 用户名密码，无需独立 Tushare Token。

环境变量:
    SERVICETUBER_BASE_URL   ServiceHub 地址，默认 https://www.ccailab.top
    SERVICETUBER_USERNAME   ServiceHub 用户名
    SERVICETUBER_PASSTOKEN  ServiceHub 密码
"""
from __future__ import annotations

import os
import json
import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── 凭证 & 端点 ──────────────────────────────────────────────────────────────

BASE_URL = os.environ.get(
    "SERVICETUBER_BASE_URL", "https://www.ccailab.top"
).rstrip("/")

USERNAME = os.environ.get("SERVICETUBER_USERNAME", "")
PASSTOKEN = os.environ.get("SERVICETUBER_PASSTOKEN", "")


def _is_configured() -> bool:
    return bool(USERNAME and PASSTOKEN)


# ── 核心 HTTP 转发 ────────────────────────────────────────────────────────────

def _post(api_name: str, params: dict, fields: str = "") -> dict:
    """
    向 ServiceHub /api/tushare/query 发送请求，返回 JSON body（不含外层包裹）。

    Returns:
        {"columns": [...], "records": [[...], ...]}

    Raises:
        ValueError: 认证失败 / 积分不足 / Tushare 报错
    """
    if not _is_configured():
        raise ValueError(
            "ServiceHub Tushare 代理未配置。请设置环境变量 "
            "SERVICETUBER_USERNAME 和 SERVICETUBER_PASSTOKEN。"
        )

    payload = {
        "username": USERNAME,
        "passtoken": PASSTOKEN,
        "api_name": api_name,
        "params": params,
    }
    if fields:
        payload["fields"] = fields

    url = f"{BASE_URL}/api/tushare/query"
    try:
        resp = requests.post(url, json=payload, timeout=90)
    except requests.RequestException as exc:
        raise ValueError(f"ServiceHub 请求失败: {exc}") from exc

    data = resp.json()

    # HTTP 层错误
    if resp.status_code == 401:
        raise ValueError(f"ServiceHub 认证失败 (401): {data.get('message', '用户名或密码错误')}")
    if resp.status_code == 402:
        raise ValueError(
            f"ServiceHub 积分不足 (402): {data.get('message', '余额不足 10 积分')}"
        )
    if resp.status_code == 502:
        tushare_err = data.get("message", "")
        raise ValueError(f"Tushare 接口报错 (502): {tushare_err}")
    if resp.status_code == 422:
        raise ValueError(f"请求参数错误 (422): {data.get('message', data)}")
    if resp.status_code != 200:
        raise ValueError(f"ServiceHub 返回错误 {resp.status_code}: {data}")

    body_code = data.get("code")
    if body_code != 200:
        raise ValueError(f"Tushare 代理业务错误 (code={body_code}): {data.get('message')}")

    return data.get("data", {})


def _raw_to_df(data: dict) -> pd.DataFrame:
    """
    将 ServiceHub 返回的 {columns, records} 转为 pandas.DataFrame。
    """
    columns = data.get("columns", [])
    records = data.get("records", [])
    if not columns:
        return pd.DataFrame()
    return pd.DataFrame(records, columns=columns)


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _normalize_ts_code(symbol: str) -> str:
    """标准化为 Tushare ts_code 格式"""
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


def _format_date(date_value) -> str:
    """格式化日期为 YYYYMMDD"""
    if isinstance(date_value, str):
        return date_value.replace("-", "")
    if hasattr(date_value, "strftime"):
        return date_value.strftime("%Y%m%d")
    return str(date_value)


# ── 核心 API ─────────────────────────────────────────────────────────────────

def daily(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    fields: str = "ts_code,trade_date,open,high,low,close,vol,amount",
) -> pd.DataFrame:
    """
    日线行情，对应 Tushare REST api_name='daily'。
    返回未复权的原始 OHLCV 数据（vol=成交量，单位手）。
    """
    params = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = _format_date(start_date)
    if end_date:
        params["end_date"] = _format_date(end_date)

    data = _post("daily", params, fields)
    return _raw_to_df(data)


def adj_factor(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
) -> pd.DataFrame:
    """
    复权因子，对应 Tushare REST api_name='adj_factor'。
    返回字段: ts_code, trade_date, adj_factor
    """
    params = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = _format_date(start_date)
    if end_date:
        params["end_date"] = _format_date(end_date)

    data = _post("adj_factor", params, "ts_code,trade_date,adj_factor")
    return _raw_to_df(data)


def pro_bar(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    adj: str = "qfq",  # "qfq" | "hfq" | None
    fields: str = "ts_code,trade_date,open,high,low,close,vol,amount",
) -> pd.DataFrame:
    """
    等价于 tushare.pro_bar()，通过 ServiceHub 透传。
    - adj=None   → 不复权，直接返回日线数据
    - adj='qfq'  → 前复权（默认）
    - adj='hfq'  → 后复权

    前复权逻辑：
        adjusted_close = raw_close * adj_factor_latest / adj_factor_historical
        其他 OHLC 价格按 close 的比例同步调整，成交量 vol 保持不变。
    """
    if adj is None or adj == "":
        return daily(ts_code, start_date, end_date, fields)

    if adj not in ("qfq", "hfq"):
        raise ValueError(f"adj 参数只支持 None/'qfq'/'hfq'，收到: {adj!r}")

    # 1. 取原始日线
    df_daily = daily(ts_code, start_date, end_date, fields)
    if df_daily.empty:
        return df_daily

    # 2. 取复权因子（全量历史，不需要日期范围）
    df_adj = adj_factor(ts_code)
    if df_adj.empty:
        logger.warning("adj_factor 返回空，返不复权数据")
        return df_daily

    # 3. 合并复权因子
    df = df_daily.merge(
        df_adj[["trade_date", "adj_factor"]],
        on="trade_date",
        how="left"
    )

    # 4. 计算前/后复权价格
    # adj_factor 为该日期的复权因子；最新日期的因子 = 基准（=1）
    # 前复权: price_adj = price_raw * factor_latest / factor_historical
    # 后复权: price_adj = price_raw * factor / factor_Earliest(=1) = price_raw * factor
    factor_cols = ["open", "high", "low", "close"]
    latest_factor = df["adj_factor"].iloc[-1]  # 最后一行是最近交易日

    if abs(latest_factor) < 1e-10:
        logger.warning("最新复权因子接近 0，返不复权数据")
        return df_daily

    if adj == "qfq":
        # 前复权：所有历史价格按最新因子归一化
        df[factor_cols] = df[factor_cols].multiply(latest_factor / df["adj_factor"], axis=0)
    else:
        # 后复权：乘以各日期自身因子
        df[factor_cols] = df[factor_cols].multiply(df["adj_factor"], axis=0)

    # 5. 保留原始列
    cols_to_keep = [c for c in fields.split(",") if c in df.columns]
    return df[cols_to_keep].reset_index(drop=True)


def stock_basic(
    ts_code: str = "",
    list_status: str = "L",
    fields: str = "ts_code,symbol,name,area,industry,market,list_date",
) -> pd.DataFrame:
    """股票基本信息，对应 api_name='stock_basic'"""
    params: dict = {"list_status": list_status}
    if ts_code:
        params["ts_code"] = ts_code
    data = _post("stock_basic", params, fields)
    return _raw_to_df(data)


def daily_basic(
    ts_code: str,
    trade_date: str = "",
    start_date: str = "",
    end_date: str = "",
    fields: str = "ts_code,trade_date,close,turnover_rate,pe,pb,total_mv,circ_mv",
) -> pd.DataFrame:
    """每日指标，对应 api_name='daily_basic'"""
    params: dict = {"ts_code": ts_code}
    if trade_date:
        params["trade_date"] = _format_date(trade_date)
    else:
        if start_date:
            params["start_date"] = _format_date(start_date)
        if end_date:
            params["end_date"] = _format_date(end_date)
    data = _post("daily_basic", params, fields)
    return _raw_to_df(data)


def income(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    period: str = "",
    fields: str = "",
) -> pd.DataFrame:
    """利润表，对应 api_name='income'"""
    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = _format_date(start_date)
    if end_date:
        params["end_date"] = _format_date(end_date)
    if period:
        params["period"] = period  # 格式 YYYMMDD，如 20231231
    data = _post("income", params, fields)
    return _raw_to_df(data)


def balance_sheet(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    period: str = "",
    fields: str = "",
) -> pd.DataFrame:
    """资产负债表，对应 api_name='balancesheet'"""
    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = _format_date(start_date)
    if end_date:
        params["end_date"] = _format_date(end_date)
    if period:
        params["period"] = period
    data = _post("balancesheet", params, fields)
    return _raw_to_df(data)


def cashflow(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    period: str = "",
    fields: str = "",
) -> pd.DataFrame:
    """现金流量表，对应 api_name='cashflow'"""
    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = _format_date(start_date)
    if end_date:
        params["end_date"] = _format_date(end_date)
    if period:
        params["period"] = period
    data = _post("cashflow", params, fields)
    return _raw_to_df(data)


def fina_indicator(
    ts_code: str,
    start_date: str = "",
    end_date: str = "",
    period: str = "",
    fields: str = "",
) -> pd.DataFrame:
    """财务指标，对应 api_name='fina_indicator'"""
    params: dict = {"ts_code": ts_code}
    if start_date:
        params["start_date"] = _format_date(start_date)
    if end_date:
        params["end_date"] = _format_date(end_date)
    if period:
        params["period"] = period
    data = _post("fina_indicator", params, fields)
    return _raw_to_df(data)


# ── 快捷构造器 ────────────────────────────────────────────────────────────────

class TushareViaServiceHub:
    """
    简易封装：给定股票代码，以 ServiceHub 代理方式获取各类数据。
    与原有 ts.pro_bar / ts.pro_api().income() 用法保持一致，
    只需 import 本模块即可，无需独立 Tushare Token。
    """

    def __init__(self, ts_code: str):
        self.ts_code = _normalize_ts_code(ts_code)

    def bar(
        self,
        start_date: str = "",
        end_date: str = "",
        adj: str = "qfq",
    ) -> pd.DataFrame:
        return pro_bar(self.ts_code, start_date, end_date, adj)

    def daily(self, start_date: str = "", end_date: str = "") -> pd.DataFrame:
        return daily(self.ts_code, start_date, end_date)

    def income(self, period: str = "") -> pd.DataFrame:
        return income(self.ts_code, period=period)

    def balancesheet(self, period: str = "") -> pd.DataFrame:
        return balance_sheet(self.ts_code, period=period)

    def cashflow(self, period: str = "") -> pd.DataFrame:
        return cashflow(self.ts_code, period=period)

    def fina_indicator(self, period: str = "") -> pd.DataFrame:
        return fina_indicator(self.ts_code, period=period)

    def daily_basic(self, trade_date: str = "") -> pd.DataFrame:
        return daily_basic(self.ts_code, trade_date=trade_date)

    def basic_info(self) -> pd.DataFrame:
        return stock_basic(ts_code=self.ts_code)
