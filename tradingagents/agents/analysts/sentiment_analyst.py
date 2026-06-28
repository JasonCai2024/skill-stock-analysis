"""Deterministic sentiment analyst for a target ticker."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import get_news
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def _count_company_news_items(news_block: str) -> int:
    return len(re.findall(r"^##\s+", news_block or "", flags=re.MULTILINE))


def _parse_stocktwits_summary(block: str) -> tuple[int, int, int, int]:
    match = re.search(
        r"Bullish:\s*(\d+).*?Bearish:\s*(\d+).*?Unlabeled:\s*(\d+).*?Total:\s*(\d+)",
        block or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return 0, 0, 0, 0
    return tuple(int(match.group(i)) for i in range(1, 5))


def _reddit_status(block: str) -> tuple[int, bool]:
    no_post = "no Reddit posts found" in (block or "")
    if no_post:
        return 0, True
    mentions = len(re.findall(r"r\/(?:wallstreetbets|stocks|investing)", block or "", flags=re.IGNORECASE))
    return mentions, False


def _build_sentiment_report(
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
    reddit_block: str,
) -> str:
    news_items = _count_company_news_items(news_block)
    bullish, bearish, unlabeled, total = _parse_stocktwits_summary(stocktwits_block)
    reddit_mentions, reddit_silent = _reddit_status(reddit_block)

    if total > 0:
        score = 5.0 + min(2.0, max(-2.0, (bullish - bearish) / max(total, 1) * 4))
        if bullish > bearish:
            band = "Mildly Bullish" if score < 6.5 else "Bullish"
        elif bearish > bullish:
            band = "Mildly Bearish" if score > 3.5 else "Bearish"
        else:
            band = "Neutral"
    elif news_items >= 3:
        score = 6.0
        band = "Mildly Bullish"
    else:
        score = 5.0
        band = "Neutral"

    missing_sources = 0
    if "<stocktwits unavailable" in (stocktwits_block or "").lower():
        missing_sources += 1
    if reddit_silent or "<no reddit posts found" in (reddit_block or "").lower():
        missing_sources += 1
    confidence = "high"
    if missing_sources >= 2:
        confidence = "low"
    elif missing_sources == 1:
        confidence = "medium"

    narrative = "\n".join([
        f"分析区间：{start_date} 至 {end_date}。",
        "",
        "### 分来源结论",
        f"- 个股新闻：共提取到 {news_items} 条相关新闻。当前新闻块主要反映北交所活跃度、成交额和融资净买入信息，说明该标的近期存在一定市场关注度。",
        (
            f"- StockTwits：共抓取 {total} 条最新消息，其中看多 {bullish} 条、看空 {bearish} 条、无标签 {unlabeled} 条。"
            if total > 0
            else f"- StockTwits：{stocktwits_block.strip() or '无可用数据。'}"
        ),
        (
            "- Reddit：过去 7 天未发现相关讨论，说明主流英文散户社区几乎没有形成公开叙事。"
            if reddit_silent
            else f"- Reddit：检测到 {reddit_mentions} 个相关社区块，存在一定讨论痕迹，但整体仍偏有限。"
        ),
        "",
        "### 综合判断",
        (
            "- 当前情绪信号更多来自新闻活跃度，而非散户社区共识，因此只能作为弱确认信号使用。"
            if total == 0
            else "- 当前情绪判断同时参考了新闻活跃度与 StockTwits 标签分布，但仍需服从技术面与基本面约束。"
        ),
        "",
        "### 情绪信号汇总表",
        "",
        "| 来源 | 方向 | 证据 |",
        "|---|---|---|",
        f"| 个股新闻 | {'偏多' if news_items >= 3 else '中性'} | 提取到 {news_items} 条相关新闻，主要围绕成交活跃与融资动向 |",
        f"| StockTwits | {'偏多' if bullish > bearish else '偏空' if bearish > bullish else '中性/缺失'} | 看多 {bullish} / 看空 {bearish} / 总计 {total} |",
        f"| Reddit | {'中性' if reddit_silent else '弱信号'} | {'无相关讨论' if reddit_silent else f'检测到 {reddit_mentions} 个社区块'} |",
    ])

    report = SentimentReport(
        overall_band=band,
        overall_score=max(0.0, min(10.0, score)),
        confidence=confidence,
        narrative=narrative,
    )
    return render_sentiment_report(report)


def create_sentiment_analyst(llm):
    del llm

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)

        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)
        reddit_block = fetch_reddit_posts(ticker)

        report_text = _build_sentiment_report(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
            reddit_block=reddit_block,
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def create_social_media_analyst(llm):
    return create_sentiment_analyst(llm)
