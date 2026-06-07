"""
东方财富个股新闻 — 同步封装
使用 AkShare stock_news_em 接口获取单只 A股的精准新闻
"""
from typing import Annotated
import os
import pandas as pd
from datetime import datetime, timedelta

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False


def _normalize_symbol(symbol: str) -> str:
    """统一为6位纯数字代码"""
    if "." in symbol:
        s = symbol.upper().split(".")[0]
    else:
        s = symbol
    return s.strip()


def get_eastmoney_news(
    ticker: Annotated[str, "A-share ticker, e.g. 601127 or 601127.SH"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    获取 A股个股新闻，对标 yfinance_news 的 get_news_yfinance。
    数据来源：东方财富 (eastmoney.com)
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
            return f"NO_DATA_AVAILABLE: No news found for '{ticker}' via 东方财富."

        # 过滤日期范围
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        df = df.copy()
        # 解析发布时间
        date_col = None
        for col in ["发布时间", "pub_time"]:
            if col in df.columns:
                date_col = col
                break

        if date_col:
            df["_dt"] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[(df["_dt"] >= start_dt) & (df["_dt"] <= end_dt)]

        if df.empty:
            return f"NO_DATA_AVAILABLE: No news found for '{ticker}' between {start_date} and {end_date}."

        # 计算舆情信号
        articles = []
        for _, row in df.iterrows():
            title = str(row.get("新闻标题", "N/A"))
            content = str(row.get("新闻内容", ""))
            # 截断过长内容
            if len(content) > 600:
                content = content[:600] + "..."
            source = str(row.get("文章来源", ""))
            pub_time = str(row.get("发布时间", ""))

            # 提取关键词
            keywords = str(row.get("关键词", ""))
            articles.append({
                "title": title,
                "content": content,
                "source": source,
                "pub_time": pub_time,
                "keywords": keywords,
            })

        # 构建输出
        lines = [
            f"# A股个股新闻: {symbol} ({ticker})",
            f"# 数据来源: 东方财富 (eastmoney.com)",
            f"# 日期范围: {start_date} 至 {end_date}",
            f"# 文章数量: {len(articles)} 篇\n",
        ]

        for art in articles:
            lines.append(f"\n## {art['title']}")
            lines.append(f"时间: {art['pub_time']} | 来源: {art['source']}")
            if art['keywords'] and art['keywords'] != 'nan':
                lines.append(f"关键词: {art['keywords']}")
            if art['content'] and art['content'] != 'nan':
                lines.append(f"\n{art['content']}")
            lines.append("-" * 60)

        return "\n".join(lines)

    except Exception as e:
        return f"Error retrieving news for '{ticker}' from 东方财富: {e}"


def get_eastmoney_news_summary(
    ticker: Annotated[str, "A-share ticker, e.g. 601127 or 601127.SH"],
    curr_date: Annotated[str, "current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "how many days to look back"] = 7,
) -> str:
    """
    获取 A股个股新闻摘要，用于舆情分析。
    计算新闻数量趋势和情感关键词密度。
    """
    if not AKSHARE_AVAILABLE:
        return (
            "NO_DATA_AVAILABLE: AkShare is not installed."
        )

    symbol = _normalize_symbol(ticker)
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = curr_date

    try:
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return f"NO_DATA_AVAILABLE: No news found for '{ticker}'."

        df = df.copy()
        for col in ["发布时间", "pub_time"]:
            if col in df.columns:
                df["_dt"] = pd.to_datetime(df[col], errors="coerce")
                break

        if "_dt" in df.columns:
            df = df[(df["_dt"] >= start_dt) & (df["_dt"] <= end_dt)]

        if df.empty:
            return f"NO_DATA_AVAILABLE: No news for '{ticker}' in the last {look_back_days} days."

        # 情感关键词
        bullish_kw = ["增长", "盈利", "突破", "创新", "新高", "加码", "扩张", "看好",
                       "买入", "增持", "突破", "强势", "超预期", "销量", "订单", "签约"]
        bearish_kw = ["亏损", "下降", "减持", "预警", "风险", "诉讼", "调查", "造假",
                      "暴跌", "危机", "违约", "终止", "裁员", "清仓", "卖", "减持"]
        neutral_kw = ["公告", "会议", "变更", "提名"]

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0

        for _, row in df.iterrows():
            text = str(row.get("新闻标题", "")) + " " + str(row.get("新闻内容", ""))
            text_lower = text.lower()

            b_count = sum(1 for kw in bullish_kw if kw in text)
            br_count = sum(1 for kw in bearish_kw if kw in text)
            n_count = sum(1 for kw in neutral_kw if kw in text)

            if b_count > br_count:
                bullish_count += 1
            elif br_count > b_count:
                bearish_count += 1
            else:
                neutral_count += 1

        total = bullish_count + bearish_count + neutral_count

        # 趋势信号
        df_sorted = df.sort_values("_dt")
        recent_week = df_sorted.tail(7) if len(df_sorted) >= 7 else df_sorted
        prev_week = df_sorted.head(len(df_sorted) - len(recent_week)) if len(df_sorted) > 7 else pd.DataFrame()

        recent_count = len(recent_week)
        prev_count = len(prev_week)
        trend = "上升 📈" if recent_count > prev_count else "下降 📉" if recent_count < prev_count else "持平 ➡️"

        # 新闻来源分布
        source_dist = df["文章来源"].value_counts().head(5).to_dict() if "文章来源" in df.columns else {}

        lines = [
            f"# A股舆情摘要: {symbol} ({ticker})",
            f"# 分析周期: 最近 {look_back_days} 天 ({start_str} 至 {end_str})",
            f"# 新闻总量: {len(df)} 篇\n",
            f"## 新闻量趋势",
            f"  本周期: {recent_count} 篇 | 前期: {prev_count} 篇",
            f"  新闻热度趋势: {trend}\n",
            f"## 舆情信号 (基于标题关键词)",
            f"  正面新闻: {bullish_count} 篇 ({bullish_count/total*100:.0f}%)",
            f"  负面新闻: {bearish_count} 篇 ({bearish_count/total*100:.0f}%)",
            f"  中性新闻: {neutral_count} 篇 ({neutral_count/total*100:.0f}%)\n",
            f"## 新闻来源 (Top 5)",
        ]
        for src, cnt in list(source_dist.items())[:5]:
            lines.append(f"  {src}: {cnt} 篇")

        sentiment_score = (bullish_count - bearish_count) / max(total, 1) * 100
        if sentiment_score > 20:
            sentiment_label = "偏正面 🟢"
        elif sentiment_score < -20:
            sentiment_label = "偏负面 🔴"
        else:
            sentiment_label = "中性 🟡"

        lines.append(f"\n## 综合舆情评分")
        lines.append(f"  舆情分: {sentiment_score:+.0f}/100 → {sentiment_label}")
        lines.append(f"  (计算方式: 正面权重 - 负面权重, 基准线 ±20)")

        return "\n".join(lines)

    except Exception as e:
        return f"Error analyzing sentiment for '{ticker}': {e}"


# ─── 全局宏观新闻 ───────────────────────────────────────────────────────────

def get_eastmoney_macro_news(
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"],
    look_back_days: Annotated[int, "how many days to look back"] = 7,
    limit: Annotated[int, "max number of articles"] = 20,
) -> str:
    """获取中国宏观财经新闻，对标 yfinance_news 的 get_global_news_yfinance。
    先尝试东财宏观新闻，失败则返回 sentinel 让 interface 层 fallback 到 Yahoo Finance。
    """
    if not AKSHARE_AVAILABLE:
        return "NO_DATA_AVAILABLE: AkShare is not installed."

    # 检查 macro_china_news 是否存在
    if not hasattr(ak, "macro_china_news"):
        return "NO_DATA_AVAILABLE: macro_china_news not available in this AkShare version."

    try:
        df = ak.macro_china_news()
        if df is None or df.empty:
            return "NO_DATA_AVAILABLE: No macro news found via 东方财富."

        start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days)
        df = df.copy()

        for col in ["发布时间", "datetime", "date"]:
            if col in df.columns:
                df["_dt"] = pd.to_datetime(df[col], errors="coerce")
                break

        if "_dt" in df.columns:
            df = df[df["_dt"] >= start_dt].sort_values("_dt", ascending=False)
        else:
            df = df.head(limit)

        if df.empty:
            return f"NO_DATA_AVAILABLE: No macro news found for the last {look_back_days} days."

        lines = [
            f"# 中国宏观财经新闻",
            f"# 日期范围: 最近 {look_back_days} 天",
            f"# Retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        ]

        for _, row in df.head(limit).iterrows():
            title = str(row.get("新闻标题", row.get("title", "N/A")))
            content = str(row.get("新闻内容", row.get("content", "")))
            if len(content) > 300:
                content = content[:300] + "..."
            source = str(row.get("文章来源", row.get("source", "")))
            pub_time = str(row.get("发布时间", row.get("datetime", "")))
            lines.append(f"\n## {title}")
            lines.append(f"来源: {source} | 时间: {pub_time}")
            if content and content != "nan":
                lines.append(content)
            lines.append("-" * 60)

        return "\n".join(lines)

    except Exception as e:
        # 网络错误等，返回 sentinel 让 interface 层 fallback
        return f"NO_DATA_AVAILABLE: 东方财富宏观新闻暂时不可用 ({type(e).__name__}). Fallback to global news."
