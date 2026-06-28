#!/usr/bin/env python3
"""Render a readable Chinese markdown report from a TradingAgents JSON state."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path


def extract_md_value(text: str, label: str) -> str | None:
    pattern = re.compile(rf"\*\*{re.escape(label)}\*\*:\s*(.+)")
    match = pattern.search(text or "")
    if not match:
        return None
    return match.group(1).strip()


def extract_table_metric(text: str, label: str) -> str | None:
    pattern = re.compile(rf"\|\s*{re.escape(label)}\s*\|\s*([^|]+)\|")
    match = pattern.search(text or "")
    if not match:
        return None
    return match.group(1).strip()


def extract_line_value(text: str, label: str) -> str | None:
    pattern = re.compile(rf"{re.escape(label)}:\s*(.+)")
    match = pattern.search(text or "")
    if not match:
        return None
    return match.group(1).strip()


def extract_company_name(fundamentals_report: str, ticker: str) -> str:
    for label in ("Company Name", "公司名称"):
        value = extract_line_value(fundamentals_report, label)
        if value:
            return value
    match = re.search(rf"A-share company fundamentals:\s*(.+?)\s*\({re.escape(ticker)}\)", fundamentals_report)
    if match:
        return match.group(1).strip()
    return ticker


def extract_news_count(news_report: str) -> str | None:
    patterns = [
        r"文章数量:\s*([0-9]+)\s*篇",
        r"文章数量[:：]\s*([0-9]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, news_report or "")
        if match:
            return match.group(1)
    return None


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_unit(text: str | None) -> str | None:
    if text is None:
        return None
    value = text
    value = value.replace("hundred-million yuan", "亿元")
    value = value.replace("ten-thousand yuan", "万元")
    return value.strip()


def first_sentence(text: str) -> str:
    cleaned = compact_text(text)
    if not cleaned:
        return ""
    match = re.search(r"(.+?[。.!?])", cleaned)
    return match.group(1).strip() if match else cleaned


def extract_section_text(text: str, heading: str) -> str | None:
    pattern = re.compile(
        rf"###\s*{re.escape(heading)}\s*(?P<body>.*?)(?:\n###|\n##|\Z)",
        re.DOTALL,
    )
    match = pattern.search(text or "")
    if not match:
        return None
    return compact_text(match.group("body"))


def build_report(data: dict, json_path: Path) -> str:
    ticker = str(data.get("company_of_interest") or "Unknown")
    data_as_of = str(data.get("trade_date") or "Unknown")
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    market_report = str(data.get("market_report") or "")
    sentiment_report = str(data.get("sentiment_report") or "")
    news_report = str(data.get("news_report") or "")
    fundamentals_report = str(data.get("fundamentals_report") or "")
    trader_decision = str(data.get("trader_investment_decision") or "")
    final_trade_decision = str(data.get("final_trade_decision") or "")

    company_name = extract_company_name(fundamentals_report, ticker)

    rating = extract_md_value(final_trade_decision, "评级") or extract_md_value(final_trade_decision, "Rating") or "未提取"
    exec_summary = extract_md_value(final_trade_decision, "执行摘要") or extract_md_value(final_trade_decision, "Executive Summary") or "未提取"
    thesis = extract_md_value(final_trade_decision, "投资逻辑") or extract_md_value(final_trade_decision, "Investment Thesis") or "未提取"
    price_target = extract_md_value(final_trade_decision, "目标价格") or extract_md_value(final_trade_decision, "Price Target")
    time_horizon = extract_md_value(final_trade_decision, "时间周期") or extract_md_value(final_trade_decision, "Time Horizon")

    action = extract_md_value(trader_decision, "交易动作") or extract_md_value(trader_decision, "Action") or "未提取"
    trader_reason = extract_md_value(trader_decision, "交易理由") or extract_md_value(trader_decision, "Reasoning") or "未提取"
    entry_price = extract_md_value(trader_decision, "入场价格") or extract_md_value(trader_decision, "Entry Price")
    stop_loss = extract_md_value(trader_decision, "止损价格") or extract_md_value(trader_decision, "Stop Loss")
    position_sizing = extract_md_value(trader_decision, "仓位建议") or extract_md_value(trader_decision, "Position Sizing")

    close_price = normalize_unit(extract_line_value(fundamentals_report, "Close") or extract_table_metric(market_report, "Close"))
    pe = normalize_unit(extract_line_value(fundamentals_report, "PE"))
    pb = normalize_unit(extract_line_value(fundamentals_report, "PB"))
    roe = normalize_unit(extract_line_value(fundamentals_report, "ROE"))
    debt_to_assets = normalize_unit(extract_line_value(fundamentals_report, "Debt To Assets"))
    current_ratio = normalize_unit(extract_line_value(fundamentals_report, "Current Ratio"))
    revenue = normalize_unit(extract_table_metric(fundamentals_report, "Revenue"))
    net_income_parent = normalize_unit(extract_table_metric(fundamentals_report, "Net Income Parent"))
    operating_cash_flow = normalize_unit(extract_table_metric(fundamentals_report, "Net Operating Cash Flow"))
    free_cash_flow = normalize_unit(extract_table_metric(fundamentals_report, "Free Cash Flow"))

    ema10 = normalize_unit(extract_table_metric(market_report, "close_10_ema"))
    sma50 = normalize_unit(extract_table_metric(market_report, "close_50_sma"))
    sma200 = normalize_unit(extract_table_metric(market_report, "close_200_sma"))
    rsi = normalize_unit(extract_table_metric(market_report, "rsi"))
    macd = normalize_unit(extract_table_metric(market_report, "macd"))
    macdh = normalize_unit(extract_table_metric(market_report, "macdh"))
    atr = normalize_unit(extract_table_metric(market_report, "atr"))
    boll_lb = normalize_unit(extract_table_metric(market_report, "boll_lb"))
    boll_ub = normalize_unit(extract_table_metric(market_report, "boll_ub"))
    latest_trade_row = re.search(r"Latest trading row used:\s*([0-9-]+)", market_report)
    latest_trade_date = latest_trade_row.group(1) if latest_trade_row else data_as_of

    sentiment_band = extract_md_value(sentiment_report, "整体情绪") or extract_md_value(sentiment_report, "Overall Sentiment") or "未提取"
    sentiment_confidence = extract_md_value(sentiment_report, "置信度") or extract_md_value(sentiment_report, "Confidence") or "未提取"
    sentiment_summary = first_sentence(
        extract_section_text(sentiment_report, "综合判断")
        or extract_md_value(sentiment_report, "综合判断")
        or extract_md_value(sentiment_report, "Summary")
        or ""
    )
    news_count = extract_news_count(news_report)

    lines: list[str] = []
    lines.append(f"# 证券研究报告：{company_name} ({ticker})")
    lines.append("")
    lines.append(f"**报告日期**：{report_date}")
    lines.append(f"**数据截止**：{data_as_of}")
    lines.append(f"**实际最新交易日**：{latest_trade_date}")
    lines.append("")
    lines.append("## 一、核心结论")
    lines.append("")
    lines.append(f"- 投资评级：`{rating}`")
    lines.append(f"- 交易动作：`{action}`")
    if close_price:
        lines.append(f"- 当前参考价：`{close_price}`")
    if price_target:
        lines.append(f"- 目标价格：`{price_target}`")
    if stop_loss:
        lines.append(f"- 止损价格：`{stop_loss}`")
    if time_horizon:
        lines.append(f"- 观察周期：`{time_horizon}`")
    if position_sizing:
        lines.append(f"- 仓位建议：{position_sizing}")
    lines.append("")
    lines.append("## 二、投资建议分析")
    lines.append("")
    lines.append("### 1. 综合判断")
    lines.append("")
    lines.append(exec_summary)
    lines.append("")
    lines.append(thesis)
    lines.append("")
    lines.append("### 2. 技术面")
    lines.append("")
    tech_points = []
    if close_price:
        tech_points.append(f"最新收盘价为 `{close_price}`。")
    if ema10 and sma50 and sma200:
        tech_points.append(f"10日 EMA `{ema10}`、50日均线 `{sma50}`、200日均线 `{sma200}`。")
    if rsi and macd and macdh:
        tech_points.append(f"RSI `{rsi}`，MACD `{macd}`，MACD 柱值 `{macdh}`。")
    if atr:
        tech_points.append(f"波动率参考 ATR 为 `{atr}`。")
    if boll_lb and boll_ub:
        tech_points.append(f"布林区间参考下轨 `{boll_lb}`，上轨 `{boll_ub}`。")
    tech_points.append(trader_reason)
    lines.append(" ".join(tech_points))
    lines.append("")
    lines.append("### 3. 基本面")
    lines.append("")
    fundamental_points = []
    if revenue:
        fundamental_points.append(f"最近一期收入 `{revenue}`。")
    if net_income_parent:
        fundamental_points.append(f"归母净利润 `{net_income_parent}`。")
    if roe:
        fundamental_points.append(f"ROE `{roe}`。")
    if pe and pb:
        fundamental_points.append(f"估值参考 PE `{pe}`，PB `{pb}`。")
    if debt_to_assets and current_ratio:
        fundamental_points.append(f"资产负债率 `{debt_to_assets}`，流动比率 `{current_ratio}`。")
    if operating_cash_flow:
        fundamental_points.append(f"经营性现金流 `{operating_cash_flow}`。")
    if free_cash_flow:
        fundamental_points.append(f"自由现金流 `{free_cash_flow}`。")
    lines.append(" ".join(fundamental_points) if fundamental_points else "当前未提取到足够的基本面摘要。")
    lines.append("")
    lines.append("### 4. 消息与情绪")
    lines.append("")
    sentiment_points = []
    if news_count:
        sentiment_points.append(f"近一期提取到 `{news_count}` 篇个股相关新闻。")
    sentiment_points.append(f"整体情绪为 `{sentiment_band}`。")
    sentiment_points.append(f"置信度为 `{sentiment_confidence}`。")
    if sentiment_summary:
        sentiment_points.append(sentiment_summary)
    lines.append(" ".join(sentiment_points))
    lines.append("")
    lines.append("## 三、交易执行建议")
    lines.append("")
    lines.append(f"- 执行动作：`{action}`")
    if entry_price:
        lines.append(f"- 参考入场价：`{entry_price}`")
    if stop_loss:
        lines.append(f"- 止损价：`{stop_loss}`")
    if price_target:
        lines.append(f"- 目标价：`{price_target}`")
    if time_horizon:
        lines.append(f"- 建议观察周期：`{time_horizon}`")
    if position_sizing:
        lines.append(f"- 仓位控制：{position_sizing}")
    lines.append("")
    lines.append("## 四、触发重新评估的条件")
    lines.append("")
    reevaluate = []
    if price_target:
        reevaluate.append(f"股价接近或达到目标价 `{price_target}`。")
    if stop_loss:
        reevaluate.append(f"价格触及止损位 `{stop_loss}`。")
    reevaluate.append("技术指标出现明显修复或进一步恶化。")
    reevaluate.append("公司基本面披露新的关键财务数据。")
    reevaluate.append("个股新闻或行业情绪出现显著变化。")
    for item in reevaluate:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 五、附录")
    lines.append("")
    lines.append("### 1. 原始决策文本")
    lines.append("")
    lines.append(final_trade_decision or "无")
    lines.append("")
    lines.append("### 2. 原始交易员文本")
    lines.append("")
    lines.append(trader_decision or "无")
    lines.append("")
    lines.append("### 3. 原始数据文件")
    lines.append("")
    lines.append(f"- JSON：`{json_path}`")
    lines.append("")
    return "\n".join(lines)


def render_report(json_path: str) -> str:
    path = Path(json_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"JSON log file not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rendered = build_report(data, path)
    md_path = path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"[Report Renderer] Standardized markdown report saved to: {md_path}", file=sys.stderr)
    return rendered


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python render_report.py <path-to-json-log>", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    try:
        rendered = render_report(json_path)
        print(rendered)
    except Exception as exc:
        print(f"Error rendering report: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
