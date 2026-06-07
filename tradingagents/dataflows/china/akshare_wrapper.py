"""
AkShare A股数据 — 同步封装
新闻、舆情、公告（作为 Tushare 降级备选）
"""
from typing import Annotated
import os
from datetime import datetime, timedelta
import pandas as pd

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


def _normalize_symbol(symbol: str) -> str:
    """统一股票代码: 6位纯数字 → 沪市:sh / 深市:sz"""
    if "." in symbol:
        s = symbol.upper().split(".")[0]
        suffix = symbol.upper().split(".")[1]
        # 统一 .SS → .SH
        if suffix == "SS":
            suffix = "SH"
    else:
        s = symbol
        suffix = None
    if not (s.isdigit() and len(s) == 6):
        return symbol
    if suffix:
        return f"{s}.{suffix}"
    if s.startswith(("60", "68", "90")):
        return f"{s}.SH"
    else:
        return f"{s}.SZ"


# ══════════════════════════════════════════════════════════════════════════════
# 新闻 & 公告
# ══════════════════════════════════════════════════════════════════════════════

def get_akshare_news(
    ticker: Annotated[str, "A-share ticker, e.g. 601127 or 000001"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    获取 A股新闻，对标 yfinance_news 的 get_news_yfinance。
    AkShare 股票新闻接口: stock_news_em
    """
    if not AKSHARE_AVAILABLE:
        return (
            "NO_DATA_AVAILABLE: AkShare is not installed. "
            "Install with: pip install akshare"
        )

    symbol = _normalize_symbol(ticker)
    try:
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No news found for '{ticker}' via AkShare."

        # 过滤日期
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        df = df.copy()
        if "发布时间" in df.columns:
            df["_dt"] = pd.to_datetime(df["发布时间"], errors="coerce")
            df = df[(df["_dt"] >= start_dt) & (df["_dt"] <= end_dt)]
        elif "发布时间" not in df.columns and "datetime" in df.columns:
            df["_dt"] = pd.to_datetime(df["datetime"], errors="coerce")
            df = df[(df["_dt"] >= start_dt) & (df["_dt"] <= end_dt)]

        if df.empty:
            return f"NO_DATA_AVAILABLE: No news found for '{ticker}' between {start_date} and {end_date}."

        lines = [
            f"# A股新闻: {symbol} ({ticker})",
            f"# Date range: {start_date} to {end_date}",
            f"# Total articles: {len(df)}\n",
        ]

        for _, row in df.iterrows():
            title = row.get("新闻标题", row.get("title", "N/A"))
            content = row.get("新闻内容", row.get("content", ""))
            # 截断过长内容
            if content and len(content) > 500:
                content = content[:500] + "..."
            source = row.get("文章来源", row.get("source", ""))
            pub_time = row.get("发布时间", row.get("datetime", ""))
            lines.append(f"\n## {title}")
            lines.append(f"来源: {source} | 时间: {pub_time}")
            if content:
                lines.append(f"\n{content}")
            lines.append("-" * 60)

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving news for '{ticker}' from AkShare: {e}"


def get_akshare_announcement(
    ticker: Annotated[str, "A-share ticker, e.g. 601127 or 000001"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    获取 A股公告，对标 alpha_vantage 的 get_news。
    使用 AkShare 公告接口: stock_announcement_em
    """
    if not AKSHARE_AVAILABLE:
        return (
            "NO_DATA_AVAILABLE: AkShare is not installed. "
            "Install with: pip install akshare"
        )

    symbol = _normalize_symbol(ticker)
    try:
        # 公告接口通常需要股票代码和日期范围
        df = ak.stock_announcement_em(symbol=symbol[:6])
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No announcements found for '{ticker}' via AkShare."

        # 过滤日期
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        df = df.copy()
        date_col = None
        for col in ["公告日期", "date", "publish_time"]:
            if col in df.columns:
                date_col = col
                break
        if date_col:
            df["_dt"] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[(df["_dt"] >= start_dt) & (df["_dt"] <= end_dt)]

        if df.empty:
            return f"NO_DATA_AVAILABLE: No announcements for '{ticker}' between {start_date} and {end_date}."

        lines = [
            f"# A股公告: {symbol} ({ticker})",
            f"# Date range: {start_date} to {end_date}",
            f"# Total announcements: {len(df)}\n",
        ]

        for _, row in df.head(20).iterrows():  # 最多20条
            title = row.get("公告标题", row.get("title", "N/A"))
            ann_date = row.get("公告日期", row.get("date", ""))
            lines.append(f"\n## {title}")
            lines.append(f"日期: {ann_date}")
            lines.append("-" * 60)

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving announcements for '{ticker}' from AkShare: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# 舆情 / 社交媒体（雪球、微博等）
# ══════════════════════════════════════════════════════════════════════════════

def get_akshare_social_sentiment(
    ticker: Annotated[str, "A-share ticker, e.g. 601127 or 000001"],
    curr_date: Annotated[str, "current date in yyyy-mm-dd format"],
) -> str:
    """
    获取 A股舆情数据（雪球讨论热度等），对标 stocktwits 的舆情感知。
    """
    if not AKSHARE_AVAILABLE:
        return (
            "NO_DATA_AVAILABLE: AkShare is not installed. "
            "Install with: pip install akshare"
        )

    symbol = _normalize_symbol(ticker)
    try:
        # 雪球热门股
        df = ak.stock_hot_rank_xq()
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No social sentiment data found via AkShare."

        # 找该股票是否在热门榜
        rank = None
        for col in ["股票代码", "code", "symbol"]:
            if col in df.columns:
                match = df[df[col].astype(str).str.contains(symbol[:6])]
                if not match.empty:
                    rank = match.iloc[0].to_dict()
                    break

        if rank:
            lines = [
                f"# 雪球热门榜单 — {symbol} ({ticker})",
                f"# Date: {curr_date}\n",
            ]
            for k, v in rank.items():
                if k not in ("_dt",):
                    lines.append(f"  {k}: {v}")
            return "\n".join(lines)
        else:
            return (
                f"# 雪球舆情: {symbol} ({ticker})\n"
                f"# 当前不在雪球热门榜单中，可能讨论量较低。\n"
                f"# 热榜前20仅供参考:\n\n"
                + df.head(20).to_string()
            )

    except Exception as e:
        return f"Error retrieving social sentiment for '{ticker}' from AkShare: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# 全局宏观新闻（A股相关）
# ══════════════════════════════════════════════════════════════════════════════

def get_akshare_global_news(
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"],
    look_back_days: Annotated[int, "how many days to look back"],
    limit: Annotated[int, "max number of articles"] = 20,
) -> str:
    """获取 A股/中国宏观新闻，对标 yfinance_news 的 get_global_news_yfinance"""
    if not AKSHARE_AVAILABLE:
        return (
            "NO_DATA_AVAILABLE: AkShare is not installed. "
            "Install with: pip install akshare"
        )

    try:
        # 东方财富宏观新闻
        df = ak.macro_china_news()
        if df is None or df.empty:
            return "NO_DATA_AVAILABLE: No macro news found via AkShare."

        # 过滤日期
        start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days)
        df = df.copy()
        date_col = None
        for col in ["发布时间", "datetime", "date"]:
            if col in df.columns:
                date_col = col
                break
        if date_col:
            df["_dt"] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[df["_dt"] >= start_dt].sort_values(date_col, ascending=False)

        if df.empty:
            return f"NO_DATA_AVAILABLE: No macro news found for the last {look_back_days} days."

        lines = [
            f"# 中国宏观财经新闻",
            f"# Date range: last {look_back_days} days",
            f"# Retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        ]
        for _, row in df.head(limit).iterrows():
            title = row.get("新闻标题", row.get("title", "N/A"))
            content = row.get("新闻内容", row.get("content", ""))
            if content and len(content) > 300:
                content = content[:300] + "..."
            source = row.get("文章来源", row.get("source", ""))
            pub_time = row.get("发布时间", row.get("datetime", ""))
            lines.append(f"\n## {title}")
            lines.append(f"来源: {source} | 时间: {pub_time}")
            if content:
                lines.append(content)
            lines.append("-" * 60)

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving global news from AkShare: {e}"
