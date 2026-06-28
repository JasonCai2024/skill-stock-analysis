"""A-share market and indicator tools backed by the Tushare base skill."""

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


TUSHARE_INDICATOR_PARAMS = {
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
    "rsi": (
        "RSI: Relative Strength Index. "
        "Usage: Identify overbought (>70) / oversold (<30) conditions and confirm trend strength. "
        "Tips: In strong trends, RSI may remain extreme; always cross-check with trend analysis."
    ),
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
    "atr": (
        "ATR: Average True Range. "
        "Usage: Set stop-loss levels and adjust position sizes based on current market volatility. "
        "Tips: It's a reactive measure, so use it as part of a broader risk management strategy."
    ),
    "mfi": (
        "MFI: Money Flow Index. "
        "Usage: Identify overbought (>80) or oversold (<20) conditions using both price and volume. "
        "Tips: Use alongside RSI or MACD to confirm signals; divergence between price and MFI can indicate potential reversals."
    ),
    "kdj": (
        "KDJ: Stochastic indicator with RSI-like calculation. "
        "Usage: Identify overbought/oversold conditions and crossover signals. "
        "Tips: Works best in trending markets; combine with trend indicators."
    ),
    "cci": (
        "CCI: Commodity Channel Index. "
        "Usage: Identify cyclical trends and overbought/oversold levels (typically +/-100). "
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


def _format_date(date_value: str) -> str:
    return str(date_value).replace("-", "")


def _market_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    rename_map = {
        "trade_date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "vol": "Volume",
        "amount": "Amount",
    }
    df = df.rename(columns=rename_map)
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    df = df.sort_values("Date")
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    return df


def _indicator_source_df(symbol: str, curr_date: str) -> pd.DataFrame:
    service = load_tushare_service()
    bundle = service.get_indicator_bundle(
        _normalize_ts_code(symbol),
        end_date=_format_date(curr_date),
        lookback_days=260,
        limit=320,
    )
    rows = bundle.get("market_daily", [])
    df = _market_df(rows)
    if df.empty:
        return df
    df = df.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    return df


def _compute_indicator_series(df: pd.DataFrame, indicator: str) -> dict[str, str]:
    from stockstats import wrap

    if df.empty:
        return {}
    working = df.copy()
    working = working.sort_values("date").set_index("date", drop=False)
    stats_df = wrap(working)
    stats_df[indicator]
    series: dict[str, str] = {}
    for idx, row in stats_df.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
        value = row.get(indicator)
        series[date_str] = "N/A" if pd.isna(value) else f"{float(value):.4f}"
    return series


def get_tushare_stock_data(
    symbol: Annotated[str, "ticker symbol, e.g. 601127.SH or 601127.SS"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    ts_code = _normalize_ts_code(symbol)
    service = load_tushare_service()

    try:
        bundle = service.get_market_bundle(
            ts_code,
            start_date=_format_date(start_date),
            end_date=_format_date(end_date),
            limit=500,
        )
        resolved_ts_code = str(bundle.get("company", {}).get("ts_code") or ts_code).upper()
        df = _market_df(bundle.get("market_daily", []))
        if df.empty:
            return (
                f"NO_DATA_AVAILABLE: No historical data returned for '{symbol}' "
                f"(ts_code={resolved_ts_code}) between {start_date} and {end_date}."
            )

        df = df[
            (df["Date"] >= start_date)
            & (df["Date"] <= end_date)
        ]
        if df.empty:
            return (
                f"NO_DATA_AVAILABLE: No historical data returned for '{symbol}' "
                f"(ts_code={resolved_ts_code}) between {start_date} and {end_date}."
            )

        columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
        df = df[[col for col in columns if col in df.columns]]
        csv_string = df.to_csv(index=False)
        label = resolved_ts_code if resolved_ts_code == symbol.upper() else f"{resolved_ts_code} (from {symbol})"
        header = (
            f"# A-share stock data for {label} from {start_date} to {end_date}\n"
            f"# Exchange: Tushare base skill cache/service\n"
            f"# Total records: {len(df)}\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + csv_string
    except Exception as exc:
        return f"Error retrieving stock data for '{symbol}' from Tushare base skill: {exc}"


def get_tushare_indicators(
    symbol: Annotated[str, "ticker symbol, e.g. 601127.SH or 601127.SS"],
    indicator: Annotated[str, "technical indicator name"],
    curr_date: Annotated[str, "The current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
):
    from dateutil.relativedelta import relativedelta

    if indicator not in TUSHARE_INDICATOR_PARAMS:
        return (
            f"Unsupported indicator '{indicator}' for A-share stocks. "
            f"Supported indicators: {list(TUSHARE_INDICATOR_PARAMS.keys())}"
        )

    try:
        df = _indicator_source_df(symbol, curr_date)
        if df.empty:
            return f"NO_DATA_AVAILABLE: No indicator source data returned for '{symbol}' on {curr_date}."

        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = end_dt - relativedelta(days=look_back_days)
        values = _compute_indicator_series(df, indicator)

        lines: list[str] = []
        current = end_dt
        while current >= start_dt:
            date_str = current.strftime("%Y-%m-%d")
            value = values.get(date_str, "N/A: Not a trading day (weekend or holiday)")
            lines.append(f"{date_str}: {value}")
            current -= relativedelta(days=1)

        description = TUSHARE_INDICATOR_PARAMS[indicator]
        return (
            f"## {indicator} values for {symbol} from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + description
        )
    except Exception as exc:
        return f"Error retrieving indicators for '{symbol}' from Tushare base skill: {exc}"
