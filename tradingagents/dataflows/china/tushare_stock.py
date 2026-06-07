"""
Tushare Pro A股数据 — 同步封装
OHLCV历史数据 + 技术指标

优先使用 ServiceHub Tushare 代理（ SERVICETUBER_USERNAME / PASSTOKEN ）；
若未配置则回退到本地 Tushare Token（ TUSHARE_TOKEN + tushare 库）。
"""
from typing import Annotated
from datetime import datetime, date
import os
import pandas as pd

# ── 本地 Tushare（备用） ─────────────────────────────────────────────────────
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
TUSHARE_AVAILABLE = False

try:
    import tushare as ts

    TUSHARE_AVAILABLE = True
except ImportError:
    pass

# ── ServiceHub Tushare 代理（优先） ──────────────────────────────────────────
# 懒加载，避免循环 import
_proxy_client = None  # type: ignore


def _get_proxy_client():
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


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_ts_code(symbol: str) -> str:
    """标准化为 Tushare ts_code 格式: 601127.SH, 000001.SZ, 430001.BJ"""
    if "." in symbol:
        # 处理 Yahoo/TradingAgents 的 .SS 后缀 → Tushare 的 .SH
        s = symbol.upper()
        if s.endswith(".SS"):
            return s[:-3] + ".SH"  # 601127.SS → 601127.SH
        return s

    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith(("60", "68", "90")):
            return f"{symbol}.SH"  # 上交所
        elif symbol.startswith(("83", "43", "87")):
            return f"{symbol}.BJ"  # 北交所
        else:
            return f"{symbol}.SZ"  # 深交所（含创业板）
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
    """建立 Tushare 连接，返回 (api, connected)。

    优先顺序：ServiceHub 代理 > 本地 Tushare Token。
    若返回 (None, True) 表示走 ServiceHub 代理，不需要 api。
    """
    # 优先尝试 ServiceHub 代理
    if _get_proxy_client() is not None:
        return None, True  # 约定：api=None 且 connected=True → 走 proxy

    # 回退：本地 tushare 库
    if not TUSHARE_AVAILABLE:
        return None, False
    if not TUSHARE_TOKEN:
        return None, False
    try:
        ts.set_token(TUSHARE_TOKEN)
        api = ts.pro_api()
        api.stock_basic(list_status="L", limit=1)
        return api, True
    except Exception:
        return None, False


def _format_date(date_value) -> str:
    """格式化日期为 YYYYMMDD"""
    if isinstance(date_value, str):
        return date_value.replace("-", "")
    elif hasattr(date_value, "strftime"):
        return date_value.strftime("%Y%m%d")
    return str(date_value)


# ══════════════════════════════════════════════════════════════════════════════
# OHLCV 数据 (对标 get_YFin_data_online)
# ══════════════════════════════════════════════════════════════════════════════

def get_tushare_stock_data(
    symbol: Annotated[str, "ticker symbol, e.g. 601127.SH or 601127.SS"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    """
    获取 A股历史 OHLCV 数据（前复权），返回 CSV 格式。
    Tushare ts_code 转换:  .SS → .SH（上交所）,  .SZ 保持不变,  .BJ 保持不变
    """
    api, connected = _connect_tushare()
    if not connected:
        return (
            f"NO_DATA_AVAILABLE: Tushare is not configured or unavailable for '{symbol}'. "
            f"Check that TUSHARE_TOKEN is set in your .env file."
        )

    ts_code = _normalize_ts_code(symbol)
    start_str = _format_date(start_date)
    end_str = _format_date(end_date)

    try:
        # 通过 proxy 或本地 Tushare 获取前复权日线
        if api is None:
            # 走 ServiceHub 代理（_connect_tushare 返回 None, True）
            proxy = _get_proxy_client()
            if proxy is None:
                # 两边都没配置
                return (
                    f"NO_DATA_AVAILABLE: Neither ServiceHub proxy nor local Tushare token "
                    f"is configured for '{symbol}'. "
                    f"Set SERVICETUBER_USERNAME/PASSTOKEN or TUSHARE_TOKEN."
                )
            df = proxy.pro_bar(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
                adj="qfq",
            )
        else:
            df = ts.pro_bar(
                ts_code=ts_code,
                api=api,
                start_date=start_str,
                end_date=end_str,
                freq="D",
                adj="qfq",  # 前复权，与同花顺一致
            )

        if df is None or df.empty:
            return (
                f"NO_DATA_AVAILABLE: No historical data returned from Tushare for "
                f"'{symbol}' (ts_code={ts_code}) between {start_date} and {end_date}. "
                f"The symbol may be invalid, delisted, or outside Tushare coverage."
            )

        # 标准化列名
        df = df.rename(columns={"vol": "Volume", "amount": "Amount"})
        df = df.rename(columns={
            "trade_date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
        })

        # 格式化日期
        df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
        df = df.sort_values("Date")
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        # 四舍五入
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = df[col].round(2)

        # 重排列
        cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in cols if c in df.columns]]

        csv_string = df.to_csv(index=False)
        label = ts_code if ts_code == symbol else f"{ts_code} (from {symbol})"
        header = (
            f"# A股 Stock data for {label} from {start_date} to {end_date}\n"
            f"# Exchange: Tushare Pro (前复权 qfq)\n"
            f"# Total records: {len(df)}\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + csv_string

    except Exception as e:
        if _is_rate_limit_error(str(e)):
            return (
                f"NO_DATA_AVAILABLE: Tushare rate limit exceeded for '{symbol}'. "
                f"Please try again later or use a fallback data source."
            )
        return (
            f"Error retrieving stock data for '{symbol}' from Tushare: {e}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 技术指标 (对标 get_stock_stats_indicators_window)
# 支持: macd, rsi, boll (布林带), sma, ema, kdj, wr (威廉指标), cci, trix, DMA, psy
# ══════════════════════════════════════════════════════════════════════════════

TUSHARE_INDICATOR_PARAMS = {
    # Moving Averages
    "close_10_ema": (
        "10 EMA: A short-term exponential moving average. "
        "Usage: Capture quick shifts in momentum and potential entry points. "
        "Tips: Prone to noise in choppy markets; use alongside longer averages for filtering false signals."
    ),
    "close_50_sma": (
        "50 SMA: A medium-term trend indicator. "
        "Usage: Identify trend direction and serve as dynamic support/resistance. "
        "Tips: It lags price; combine with faster indicators for timely signals."
    ),
    "close_200_sma": (
        "200 SMA: A long-term trend benchmark. "
        "Usage: Confirm overall market trend and identify golden/death cross setups. "
        "Tips: It reacts slowly; best for strategic trend confirmation rather than frequent trading entries."
    ),
    # MACD
    "macd": (
        "MACD: Moving Average Convergence Divergence. "
        "Usage: Look for crossovers and divergence as signals of trend changes. "
        "Tips: Confirm with other indicators in low-volatility or sideways markets."
    ),
    "macds": (
        "MACD Signal: An EMA smoothing of the MACD line. "
        "Usage: Use crossovers with the MACD line to trigger trades. "
        "Tips: Should be part of a broader strategy to avoid false positives."
    ),
    "macdh": (
        "MACD Histogram: Shows the gap between the MACD line and its signal. "
        "Usage: Visualize momentum strength and spot divergence early. "
        "Tips: Can be volatile; complement with additional filters in fast-moving markets."
    ),
    # Momentum
    "rsi": (
        "RSI: Relative Strength Index. "
        "Usage: Identify overbought (>70) / oversold (<30) conditions and confirm trend strength. "
        "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
    ),
    # Bollinger Bands
    "boll": (
        "Bollinger Middle: A 20-period SMA serving as the basis for Bollinger Bands. "
        "Usage: Acts as a dynamic benchmark for price movement. "
        "Tips: Combine with the upper and lower bands to effectively spot breakouts or reversals."
    ),
    "boll_ub": (
        "Bollinger Upper Band: Typically 2 standard deviations above the middle line. "
        "Usage: Signals potential overbought conditions and breakout zones. "
        "Tips: Confirm signals with other tools; prices may ride the band in strong trends."
    ),
    "boll_lb": (
        "Bollinger Lower Band: Typically 2 standard deviations below the middle line. "
        "Usage: Indicates potential oversold conditions and reversal zones. "
        "Tips: Use additional analysis to avoid false reversal signals."
    ),
    # Volatility
    "atr": (
        "ATR: Average True Range. "
        "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
        "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
    ),
    # Volume
    "mfi": (
        "MFI: Money Flow Index. "
        "Usage: Identify overbought (>80) or oversold (<20) conditions using both price and volume. "
        "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
    ),
    # Other
    "kdj": (
        "KDJ: Stochastic indicator with RSI-like calculation. "
        "Usage: Identify overbought/oversold conditions and crossover signals. "
        "Tips: Works best in trending markets; combine with trend indicators."
    ),
    "cci": (
        "CCI: Commodity Channel Index. "
        "Usage: Identify cyclical trends and overbought/oversold levels (typically ±100). "
        "Tips: Best used in markets without a clear trend."
    ),
    "wr": (
        "WR: Williams %R. "
        "Usage: Identify overbought (>-20) / oversold (<-80) conditions. "
        "Tips: Very sensitive; combine with slower indicators to filter noise."
    ),
    "psy": (
        "PSY: Psychological Line. "
        "Usage: Measures the proportion of rising days in a period (typically 12). "
        "Tips: Values >75 suggest overbought; <25 suggests oversold."
    ),
    "dma": (
        "DMA: Different of Moving Average. "
        "Usage: Difference between two SMAs used as a momentum oscillator. "
        "Tips: Crossovers of DMA above/below zero generate buy/sell signals."
    ),
    "trix": (
        "TRIX: Triple EMA Rate of Change. "
        "Usage: Smoothed momentum indicator that filters out minor price movements. "
        "Tips: Positive TRIX indicates uptrend; negative indicates downtrend."
    ),
}


def _fetch_tushare_indicators_data(symbol: str, curr_date: str) -> pd.DataFrame:
    """从 Tushare 获取原始 OHLCV 用于本地计算技术指标"""
    from dateutil.relativedelta import relativedelta as rd

    end_date = curr_date
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - rd(days=250)  # 预留足够数据给 200 日均线
    start_date = start_dt.strftime("%Y-%m-%d")

    ts_code = _normalize_ts_code(symbol)
    start_str = _format_date(start_date)
    end_str = _format_date(end_date)

    # 优先 ServiceHub 代理，否则本地 tushare 库
    proxy = _get_proxy_client()
    if proxy is not None:
        df = proxy.pro_bar(
            ts_code=ts_code,
            start_date=start_str,
            end_date=end_str,
            adj="qfq",
        )
    else:
        if not TUSHARE_AVAILABLE or not TUSHARE_TOKEN:
            return pd.DataFrame()
        df = ts.pro_bar(
            ts_code=ts_code,
            api=None,
            start_date=start_str,
            end_date=end_str,
            freq="D",
            adj="qfq",
        )

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={"vol": "volume", "amount": "amount"})
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values("date")
    return df


def _compute_indicator(df: pd.DataFrame, indicator: str, curr_date: str) -> str:
    """使用 stockstats 计算单日技术指标值"""
    try:
        from stockstats import wrap
        if df.empty:
            return "N/A"

        data = df.copy()
        data = data.rename(columns={"date": "Date", "close": "close"})
        if "Date" not in data.columns and "date" in data.columns:
            data["Date"] = df["date"]

        sw = wrap(data.copy())
        sw[indicator]  # 触发计算

        # 找 curr_date 对应的值
        curr_dt = pd.to_datetime(curr_date)
        matched = sw[sw["Date"] == curr_dt]
        if matched.empty:
            # 找最近交易日
            valid = sw[sw["Date"] <= curr_dt].dropna(subset=[indicator])
            if valid.empty:
                return "N/A"
            matched = valid.iloc[-1:]

        val = matched.iloc[0][indicator]
        if pd.isna(val):
            return "N/A"
        return f"{float(val):.4f}"
    except Exception:
        return "N/A"


def _compute_indicator_series(df: pd.DataFrame, indicator: str) -> dict:
    """计算指标序列，返回 {date_str: value_str}"""
    try:
        from stockstats import wrap
        if df.empty:
            return {}
        sw = wrap(df.copy())
        sw[indicator]
        result = {}
        for idx, (_, row) in enumerate(sw.iterrows()):
            # stockstats uses 'date' as the DataFrame index (after wrap), not a column
            date_val = sw.index[idx]
            if hasattr(date_val, "strftime"):
                date_str = date_val.strftime("%Y-%m-%d")
            else:
                date_str = str(date_val)
            val = row.get(indicator)
            if pd.isna(val):
                result[date_str] = "N/A"
            else:
                result[date_str] = f"{float(val):.4f}"
        return result
    except Exception:
        return {}


def get_tushare_indicators(
    symbol: Annotated[str, "ticker symbol, e.g. 601127.SH or 601127.SS"],
    indicator: Annotated[str, "technical indicator name"],
    curr_date: Annotated[str, "The current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
):
    """获取 A股技术指标，对标 yfinance 的 get_stock_stats_indicators_window"""
    from dateutil.relativedelta import relativedelta

    api, connected = _connect_tushare()
    if not connected:
        return (
            f"NO_DATA_AVAILABLE: Tushare is not configured or unavailable for '{symbol}'. "
            f"Check that TUSHARE_TOKEN is set in your .env file."
        )

    if indicator not in TUSHARE_INDICATOR_PARAMS:
        return (
            f"Unsupported indicator '{indicator}' for A-share stocks via Tushare. "
            f"Supported indicators: {list(TUSHARE_INDICATOR_PARAMS.keys())}"
        )

    try:
        df = _fetch_tushare_indicators_data(symbol, curr_date)
        if df.empty:
            return (
                f"NO_DATA_AVAILABLE: No data returned from Tushare for '{symbol}' on {curr_date}. "
                f"The symbol may be invalid, delisted, or not covered by Tushare."
            )

        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = end_dt - relativedelta(days=look_back_days)
        start_str = start_dt.strftime("%Y-%m-%d")

        # 全量计算一次
        ind_series = _compute_indicator_series(df, indicator)

        # 构建日期范围内的值字符串
        lines = []
        cur = end_dt
        while cur >= start_dt:
            date_str = cur.strftime("%Y-%m-%d")
            val = ind_series.get(date_str, "N/A: Not a trading day (weekend or holiday)")
            lines.append(f"{date_str}: {val}")
            cur -= relativedelta(days=1)

        description = TUSHARE_INDICATOR_PARAMS.get(indicator, "No description available.")
        result = (
            f"## {indicator} values for {symbol} from {start_str} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + description
        )
        return result

    except Exception as e:
        if _is_rate_limit_error(str(e)):
            return (
                f"NO_DATA_AVAILABLE: Tushare rate limit exceeded for '{symbol}'. "
                f"Please try again later."
            )
        return f"Error retrieving indicators for '{symbol}' from Tushare: {e}"
