---
name: stock-analysis
description: Runs TradingAgents multi-analyst pipeline to produce a BUY/SELL/HOLD equity research report for a Chinese A-share stock. Use when the user asks to analyze a stock price or company, e.g. "请分析华邦健康股价" or "分析002004.SZ"。Supports Chinese company names (auto-resolves to Tushare ticker) and direct ticker codes.
disable-model-invocation: false
user-invocable: true
argument-hint: <company-name-or-ticker>
---

# Stock Analysis

## Goal

Run the TradingAgents quantitative analysis pipeline on a Chinese A-share stock and produce a structured equity research report with a BUY / SELL / HOLD final recommendation, including target price, stop-loss, and risk analysis from four independent analysts.

## Scope

Use this skill when the user wants a comprehensive stock analysis report in Chinese. Works for:
- Chinese company names (e.g. "华邦健康", "望变电气")
- Direct Tushare-style ticker codes (e.g. "002004.SZ", "603191.SH")

Covers Chinese A-shares only (SSE / SZSE). US stocks and HK stocks are out of scope.

## Required Credentials

**All requests route through ServiceHub. No Tushare Token or MiniMax API Key is needed.**

On first use (or if credentials are not yet set), ask the user for:

- **ServiceHub username** — the account used to log into `https://www.ccailab.top`
- **ServiceHub passtoken** — the account password on `https://www.ccailab.top`

Store these as environment variables for the duration of the session:

```python
import os
os.environ["SERVICETUBER_BASE_URL"] = "https://www.ccailab.top"
os.environ["SERVICETUBER_USERNAME"] = "<ask user>"
os.environ["SERVICETUBER_PASSTOKEN"] = "<ask user>"
os.environ["TRADINGAGENTS_LLM_PROVIDER"] = "servicehub"
```

Do not ask the user to edit any files. All configuration is done through the conversation.

## Required Inputs

1. **Stock identifier** — either a Chinese company name or a Tushare ticker code.
2. **Python environment** — requires `E:\Python312_new\python.exe` with required dependencies installed.

## Workflow

### Step 1 — Resolve stock code

If the user provided a company name (Chinese), use the ServiceHub Tushare proxy to look up the exact ticker:

```
POST <SERVICETUBER_BASE_URL>/api/tushare/query
body: {api_name: "stock_basic", params: {name: "<company-name>", list_status: "L"}}
```

Take the first result's `ts_code` field (e.g. `002004.SZ`). If the user already provided a ticker, skip this step.

If the search returns no results, try AkShare as fallback. If neither source finds the stock, stop and report failure.

### Step 2 — Run TradingAgents pipeline

First, set the credentials as environment variables (so the subprocess inherits them):

```python
import os, subprocess
os.environ["SERVICETUBER_BASE_URL"] = "https://www.ccailab.top"
os.environ["SERVICETUBER_USERNAME"] = "<from user>"
os.environ["SERVICETUBER_PASSTOKEN"] = "<from user>"
os.environ["TRADINGAGENTS_LLM_PROVIDER"] = "servicehub"
```

Then execute the wrapper script (the subprocess inherits the env vars above):

```
E:\Python312_new\python.exe "<skill-root>\scripts\run_analysis.py" "<ticker-or-company-name>"
```

The wrapper script:
- Uses `SERVICETUBER_*` environment variables set above
- Resolves company name to ticker (if needed)
- Calls `TradingAgentsGraph(debug=True).propagate(ticker, today's date)`
- Saves the full JSON state to `<skill-root>/reports/logs/<ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json`
- Prints the JSON report path to stdout

### Step 3 — Parse and present results

Read the saved JSON and present a clean Chinese summary covering:

1. **舆情分析** (Sentiment Analyst) — overall_score, key events
2. **基本面分析** (Fundamentals Analyst) — revenue, ROE, P/E, FCF, key financials
3. **交易员决策** (Trader) — BUY / SELL / HOLD with key reasoning
4. **最终裁定** (Portfolio Manager) — final recommendation, target price, stop-loss, holding period, re-evaluation triggers

## Decision Rules

1. If the user gives a company name, resolve to ticker first — never guess.
2. If Tushare search finds multiple results, ask the user to pick the correct one.
3. If the JSON report file exists from a prior run (same ticker, same date), reuse it instead of re-running to save cost.
4. LLM calls inside TradingAgents go through ServiceHub — no local API key needed.
5. Each full run costs multiple ServiceHub LLM calls (~4+ analysts × multiple rounds). Warn the user if this is a fresh run and costs are a concern.

## Output Requirements

Return a clean Chinese report including:

- Company name and ticker
- Date of analysis
- Each analyst's conclusion
- Final recommendation: BUY / SELL / HOLD
- Target price (CNY)
- Stop-loss price (CNY)
- Holding period
- Re-evaluation triggers
- Path to the saved JSON report

## Fallback

If the wrapper script is unavailable, set env vars and run directly:

```python
import os
os.environ["SERVICETUBER_BASE_URL"] = "https://www.ccailab.top"
os.environ["SERVICETUBER_USERNAME"] = "<ask user>"
os.environ["SERVICETUBER_PASSTOKEN"] = "<ask user>"
```

```bash
cd <skill-root>
E:\Python312_new\python.exe main.py <ticker>
```

The report is saved at:
`<skill-root>/reports/logs/<ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json`

## Examples

- "请分析华邦健康的股价"
- "分析一下002004.SZ"
- "望变电气最近值得买吗"
- "帮我看看603191.SH"
