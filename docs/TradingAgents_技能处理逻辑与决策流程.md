# TradingAgents 技能处理逻辑与决策流程

> 本文档描述 TradingAgents 多智能体投研 pipeline 的完整处理逻辑与决策流程。
> 
> 更新时间：2026-06-10

---

## 一、整体流程概览（3个阶段）

```
阶段1：并行采集          阶段2：多空辩论              阶段3：最终裁定
─────────────           ──────────────              ──────────────
Market Analyst  ─┐
Social Analyst  ─┼──►  Investment Debate  ──┐
News Analyst   ─┤      (Bull vs Bear)      │
Fundamentals   ─┘                          ├──►  Portfolio Manager
  Analyst         Risk Debate               │     (最终决策)
                  (Aggressive vs          │
                  Conservative vs         │
                  Neutral)               ─┘
```

---

## 二、参与智能体详解（共6个）

### 阶段1 — 4个并行分析师（同时运行）

| 分析师 | 输出报告 | 调用的数据工具 |
|--------|---------|--------------|
| **Market Analyst** | `market_report` | 技术指标工具：`get_stock_data`、`get_indicators`（stockstats） |
| **Social Analyst** | `sentiment_report` | 社交媒体工具：`get_news`（StockTwits、Reddit） |
| **News Analyst** | `news_report` | 新闻工具：`get_news`、`get_global_news`（Yahoo Finance） |
| **Fundamentals Analyst** | `fundamentals_report` | 财务工具：`get_fundamentals`、`get_balance_sheet`、`get_cashflow`、`get_income_statement` |

> 注：每个分析师独立工作，共享相同的股票身份信息（公司名、业务分类、交易所），但数据来源互不干扰。

### 阶段2 — 辩论阶段（串行执行）

#### Investment Debate（投资辩论）

| 参与方 | 角色 |
|--------|------|
| **Bull Agent**（多方） | 提出买入论点：增长逻辑、催化剂、估值优势等 |
| **Bear Agent**（空方） | 提出卖出论点：风险因素、竞争压力、估值过高 |
| **Judge** | 裁判，综合双方论点输出裁定结果 |

#### Risk Debate（风险辩论）

| 参与方 | 角色 |
|--------|------|
| **Aggressive Agent**（激进方） | 高风险高回报视角 |
| **Conservative Agent**（保守方） | 低风险视角，强调下行保护 |
| **Neutral Agent**（中性方） | 平衡观点 |
| **Judge** | 裁判，综合三方论点输出裁定结果 |

### 阶段3 — 最终决策

| 角色 | 职责 |
|------|------|
| **Trader / Portfolio Manager** | 综合4个分析师报告 + 2场辩论结果，输出最终 BUY/SELL/HOLD 建议、目标价、止损价、持仓周期、再评估触发条件 |

---

## 三、决策机制

1. **分析师独立工作**：每个分析师使用相同的股票身份上下文，各自调用工具抓取数据，生成独立报告
2. **辩论层**：分析师报告 → 多空双方辩论 → Judge 裁判裁定；风险三方辩论 → Judge 裁判裁定
3. **汇总裁定**：Portfolio Manager 读取所有输出，输出带理由的最终决策
4. **结果存档**：完整状态 JSON 保存在：
   ```
   reports/logs/<ticker>/TradingAgentsStrategy_logs/full_states_log_<date>.json
   ```

---

## 四、数据源现状与已知限制

| 数据源 | 状态 | 说明 |
|--------|------|------|
| Tushare（通过 ServiceHub） | ✅ 正常 | 用于股票基本信息查询 |
| Yahoo Finance | ⚠️ 部分问题 | 中国 A 股 ticker（如 `601127.SH`）存在 404 问题，技术指标数据获取受影响 |
| StockTwits / Reddit | ⚠️ A股缺失 | 海外社交媒体对 A 股关注极少，数据基本为空 |
| Fundamentals（财务报表） | ⚠️ 部分问题 | Yahoo Finance 对 A 股支持不完善，数据获取不稳定 |

### 核心已知问题

- **Fundamentals Analyst** 用 Yahoo Finance 查 A 股存在 404 问题，数据获取不稳定
- **Social Analyst**（StockTwits/Reddit）在 A 股上基本无数据，信号缺失
- 数据问题会影响部分分析师的报告质量，但辩论层仍会基于已有数据尽力输出

---

## 五、输出报告字段说明

| 字段 | 说明 |
|------|------|
| `company_of_interest` | 股票代码（如 `601127.SH`） |
| `trade_date` | 分析日期（实际数据截止日期） |
| `market_report` | Market Analyst 的技术分析报告 |
| `sentiment_report` | Sentiment Analyst 的社交媒体情绪报告 |
| `news_report` | News Analyst 的新闻分析报告 |
| `fundamentals_report` | Fundamentals Analyst 的基本面分析报告 |
| `investment_debate_state` | 投资辩论状态（含多空双方论点及 Judge 裁定） |
| `trader_investment_decision` | Trader 的投资决策（含 BUY/SELL/HOLD 及理由） |
| `risk_debate_state` | 风险辩论状态（含三方论点及 Judge 裁定） |
| `investment_plan` | 综合投资计划 |
| `final_trade_decision` | Portfolio Manager 的最终裁定 |

---

## 六、文件结构

```
tradingagents/
├── agents/                     # 智能体定义
│   ├── analysts/               # 4个分析师
│   │   ├── market_analyst.py
│   │   ├── social_analyst.py
│   │   ├── news_analyst.py
│   │   └── fundamentals_analyst.py
│   ├── bull_bear/
│   │   ├── bull_agent.py       # 多方
│   │   ├── bear_agent.py       # 空方
│   │   └── judge.py            # 裁判
│   └── risk/
│       ├── aggressive_agent.py
│       ├── conservative_agent.py
│       ├── neutral_agent.py
│       └── judge.py
├── dataflows/                  # 数据层
│   ├── y_finance.py            # Yahoo Finance 数据获取
│   ├── symbol_utils.py         # 股票代码规范化
│   └── interface.py            # route_to_vendor 路由
├── graph/                      # 图结构编排
│   ├── trading_graph.py        # 主图：编排所有智能体
│   ├── setup.py                # 图构建
│   ├── propagation.py          # 状态初始化
│   └── conditional_logic.py    # 条件路由
├── reports/
│   └── logs/
│       └── <ticker>/
│           └── TradingAgentsStrategy_logs/
│               └── full_states_log_<date>.json
└── main.py                     # 入口脚本
```

---

## 七、相关文档

- [TradingAgents A股数据源升级方案](./20260606_TradingAgents_A股数据源升级方案.md)
