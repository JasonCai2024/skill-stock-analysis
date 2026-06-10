#!/usr/bin/env python3
"""
TradingAgents Report Renderer
Parses the output JSON state of a TradingAgents run and generates a solidified,
professional Markdown equity research report.
"""

import sys
import json
import os
import re
from pathlib import Path
from datetime import datetime

TEMPLATE = """# 📊 证券研究报告：{company_name} ({ticker})

**报告日期**：{report_date} | **数据截止**：{data_as_of} | **决策评级**：{final_rating}

---

## 💡 一、 核心投资结论与资金配置建议 (Portfolio Manager Verdict)
> 投资组合经理的最终裁定与对冲操盘建议。

{final_trade_decision}

---

## 📈 二、 交易员具体操盘策略 (Trader Strategy)
> 交易员的技术面操盘执行方案，包含建仓点、止损位与目标位。

{trader_decision}

---

## 🔍 三、 多维度支撑数据分析 (Analyst Reports)

### 1. 基本面深度研究 (Fundamentals Analyst)
{fundamentals_report}

---

### 2. 技术指标分析 (Market Analyst)
{market_report}

---

### 3. 消息面与舆情分析 (News & Sentiment Analyst)

#### 📰 核心新闻动向:
{news_report}

#### 🗣️ 市场舆情监测:
{sentiment_report}

---
* 原始数据日志归档：{json_path} *
"""

def extract_rating(pm_decision: str) -> str:
    """Extract final rating from the PM decision text (BUY/SELL/HOLD)."""
    pm_upper = pm_decision.upper()
    
    # Check for exact matches or highlights
    if "BUY" in pm_upper or "买入" in pm_decision:
        if "SELL" not in pm_upper and "卖出" not in pm_decision:
            return "BUY (买入)"
        # If both are present, inspect proximity or default
    if "SELL" in pm_upper or "卖出" in pm_decision:
        if "BUY" not in pm_upper and "买入" not in pm_decision:
            return "SELL (卖出)"
    
    return "HOLD (持有)"

def render_report(json_path: str) -> str:
    path = Path(json_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"JSON log file not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract meta information
    ticker = data.get("company_of_interest", "Unknown")
    data_as_of = data.get("trade_date", "Unknown")
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Extract reports (handle missing keys/None)
    final_trade_decision = (data.get("final_trade_decision") or "").strip()
    trader_decision = (data.get("trader_investment_decision") or "").strip()
    fundamentals_report = (data.get("fundamentals_report") or "").strip()
    market_report = (data.get("market_report") or "").strip()
    news_report = (data.get("news_report") or "").strip()
    sentiment_report = (data.get("sentiment_report") or "").strip()

    # Default placeholders for empty fields
    if not final_trade_decision:
        final_trade_decision = "*未生成核心投资结论。*"
    if not trader_decision:
        trader_decision = "*未生成操盘策略。*"
    if not fundamentals_report:
        fundamentals_report = "*未生成基本面分析。*"
    if not market_report:
        market_report = "*未生成技术指标分析。*"
    if not news_report:
        news_report = "*无相关新闻动向记录。*"
    if not sentiment_report:
        sentiment_report = "*无相关市场舆情记录。*"

    # Attempt to resolve company name from fundamentals report or stock name using robust regex patterns
    company_name = "未命名"
    
    # 1) Search for "company_name": "..." (JSON style)
    m = re.search(r'"company_name"\s*:\s*"([^"]+)"', fundamentals_report, re.IGNORECASE)
    if m:
        company_name = m.group(1).strip()
        
    # 2) Search for "公司名称：..." (Chinese style)
    if company_name == "未命名" and "公司名称" in fundamentals_report:
        for line in fundamentals_report.split("\n"):
            if "公司名称" in line:
                parts = line.split("：")
                if len(parts) > 1:
                    company_name = parts[1].replace("*", "").strip()
                    break

    # 3) Search for 证券代码 `300122.SZ`（智飞生物）
    if company_name == "未命名":
        m = re.search(r'证券代码\s*[`\'"]?\d{6}\.(?:SZ|SH|SS|BJ)[`\'"]?（([^）]+)）', fundamentals_report)
        if m:
            company_name = m.group(1).strip()

    # 4) Search for 智飞生物（300122.SZ）
    if company_name == "未命名":
        m = re.search(r'([^（\s#*]+)（\d{6}\.(?:SZ|SH|SS|BJ)）', fundamentals_report)
        if m:
            company_name = m.group(1).strip()
        else:
            m = re.search(r'([^（\s#*]+)（\d{6}\.(?:SZ|SH|SS|BJ)）', final_trade_decision)
            if m:
                company_name = m.group(1).strip()

    # Extract final rating
    final_rating = extract_rating(final_trade_decision)

    # Format template
    rendered = TEMPLATE.format(
        company_name=company_name,
        ticker=ticker,
        report_date=report_date,
        data_as_of=data_as_of,
        final_rating=final_rating,
        final_trade_decision=final_trade_decision,
        trader_decision=trader_decision,
        fundamentals_report=fundamentals_report,
        market_report=market_report,
        news_report=news_report,
        sentiment_report=sentiment_report,
        json_path=str(path)
    )

    # Save to MD file next to JSON file
    md_path = path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    
    print(f"[Report Renderer] Standardized markdown report saved to: {md_path}", file=sys.stderr)
    return rendered

def main():
    if len(sys.argv) < 2:
        print("Usage: python render_report.py <path-to-json-log>", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    try:
        rendered = render_report(json_path)
        print(rendered)
    except Exception as e:
        print(f"Error rendering report: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
