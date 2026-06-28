---
name: skill-stock-analysis
description: Runs a TradingAgents multi-analyst pipeline for a Chinese A-share stock and produces a BUY/SELL/HOLD equity research report with explicit investment and trading recommendations. Use when the user clearly asks for investment advice, trading strategy, buy/sell guidance, target price, stop-loss, position guidance, or mentions multi-agent / TradingAgents analysis.
disable-model-invocation: false
user-invocable: true
argument-hint: <company-name-or-ticker>
---

# Stock Analysis

## Goal

Run the TradingAgents analysis pipeline on a Chinese A-share stock and produce a decision-oriented Chinese equity research report with:

1. Final BUY / SELL / HOLD recommendation
2. Target price
3. Stop-loss
4. Suggested holding period
5. Re-evaluation triggers
6. Supporting reasoning from multiple analyst roles

## Scope

Use this skill when the user explicitly wants investment or trading advice, for example:

- whether a stock is worth buying
- a buy/sell recommendation
- a trading strategy
- target price or stop-loss
- a multi-agent or TradingAgents style decision report

Works for:

- Chinese company names, such as `华邦健康`
- Direct Tushare-style tickers, such as `002004.SZ`

Covers Chinese A-shares only. US stocks and HK stocks are out of scope.

## Routing Boundary

This is an upper-layer decision skill. It is not the default entry point for generic company analysis.

Route to the lower sibling skill `skill-tushare-servicehub-assistant` instead when the user mainly wants:

1. Company basic situation
2. Main business analysis
3. Financial analysis
4. Market行情 or recent price behavior
5. Ownership structure
6. Structured Tushare data, local warehouse data, or JSON

If the request is ambiguous, such as:

- `分析一下某某公司`
- `了解一下这家公司`
- `帮我看看这只股票`

do not auto-trigger this skill unless the user clearly asks for investment advice or trading advice.

## Dependency

This skill depends on the sibling base skill `skill-tushare-servicehub-assistant`.

Preferred install layout:

- `SKILLS-办公技能/skill-stock-analysis`
- `SKILLS-办公技能/skill-tushare-servicehub-assistant`

Optional override:

- set `TUSHARE_SKILL_ROOT=<absolute-path-to-skill-tushare-servicehub-assistant>`

This upper skill does not call Tushare or ServiceHub directly for market and financial data. It imports the lower skill's stable Python service API and reuses the lower skill's credentials, cache DB, and warehouse DB.

## Required Credentials

All A-share data requests are served by the lower base skill. No local Tushare token is needed in this skill.

On first use, ask the user for:

1. ServiceHub username
2. ServiceHub passtoken

Store them as environment variables for the current session:

```python
import os
os.environ["SERVICETUBER_BASE_URL"] = "https://www.ccailab.top"
os.environ["SERVICETUBER_USERNAME"] = "<ask user>"
os.environ["SERVICETUBER_PASSTOKEN"] = "<ask user>"
os.environ["TRADINGAGENTS_LLM_PROVIDER"] = "servicehub"
```

Do not ask the user to edit files.

## Required Inputs

1. Stock identifier: company name or Tushare ticker
2. Python 3.11+ with dependencies installed

First-time setup:

```bash
pip install -r <skill-root>/requirements.txt
```

## Workflow

### Step 1: Resolve stock code

If the user provided a Chinese company name, call the lower skill's stable function `resolve_company()` to resolve the exact ticker and reuse its local cache and warehouse.

If the user already provided a ticker, skip this step.

If no result is found, try AkShare as fallback. If neither source finds the stock, stop and report failure.

### Step 2: Run TradingAgents pipeline

Set runtime environment variables first:

```python
import os
os.environ["SERVICETUBER_BASE_URL"] = "https://www.ccailab.top"
os.environ["SERVICETUBER_USERNAME"] = "<from user>"
os.environ["SERVICETUBER_PASSTOKEN"] = "<from user>"
os.environ["TRADINGAGENTS_LLM_PROVIDER"] = "servicehub"
```

Then run:

```python
import subprocess
import sys

subprocess.run(
    [sys.executable, "<skill-root>/scripts/run_analysis.py", "<ticker-or-company-name>"],
    check=True,
)
```

The wrapper script:

1. Imports the lower skill through `tushare_dependency.py`
2. Resolves company name to ticker through the lower skill's API
3. Runs the TradingAgents graph
4. Saves the full JSON state under `reports/logs/<ticker>/TradingAgentsStrategy_logs/`
5. Renders a standardized Markdown report next to the JSON file

### Step 3: Present results

Read the generated Markdown report and present it to the user. The output should include analyst conclusions and the final trading recommendation.

## Decision Rules

1. Resolve company name to ticker first. Never guess.
2. If multiple stock matches are found, ask the user to choose.
3. If the same ticker already has a report for the same date, reuse it when appropriate.
4. LLM calls inside TradingAgents go through ServiceHub.
5. A fresh run can consume multiple ServiceHub calls. Warn the user when cost matters.
6. This skill should only be selected when the user's goal is clearly decision-oriented.
7. Generic company analysis should default to the lower sibling skill.

## Output Requirements

Return a clean Chinese report including:

1. Company name and ticker
2. `data_as_of`
3. `report_date`
4. Each analyst's conclusion
5. Final recommendation: BUY / SELL / HOLD
6. Target price
7. Stop-loss price
8. Holding period
9. Re-evaluation triggers
10. Saved JSON report path

Always derive `data_as_of` from the underlying JSON state rather than trusting narrative prose.

## Fallback

If the wrapper is unavailable, run the skill directly through `main.py` with the same environment variables.

## Examples

- `请给我一份华邦健康的投资建议`
- `分析002004.SZ，给出买卖建议和止损位`
- `望变电气最近值不值得买`
- `帮我用多智能体框架分析603191.SH，并给出交易策略`
