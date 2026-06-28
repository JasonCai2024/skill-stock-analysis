---
name: skill-stock-analysis
description: 使用 TradingAgents 多分析角色流程，对 A 股股票生成面向投资动作的决策报告。仅适用于用户明确要求投资建议、买卖建议、交易策略、目标价、止损位、仓位建议，或明确提到多智能体 / TradingAgents 分析时。
argument-hint: <company-name-or-ticker>
---

Use the skill at `~/.claude/skills/skill-stock-analysis/`.

Treat this as an upper-layer decision skill, not a generic company-analysis skill.

Default routing policy:

1. Use this skill only when the user clearly wants investment advice or trading advice.
2. If the user asks for buy/sell guidance, trading strategy, target price, stop-loss, position guidance, holding suggestion, or multi-agent decision analysis, stay in this skill.
3. If the user only wants to understand a company, its business, finance, market performance, or ownership structure, route downward to `skill-tushare-servicehub-assistant`.
4. If the request is ambiguous, ask one minimal routing question:
   `你是想了解公司的情况，还是想让我直接给出投资建议或交易建议？`

Execution policy:

1. Resolve company name to ticker through the lower sibling skill.
2. Reuse the lower skill's credentials, cache DB, and warehouse DB.
3. Reuse the existing report for the same ticker and date when appropriate.
4. Warn the user when a fresh run will consume multiple ServiceHub calls.
5. Present the final output as a decision-oriented report, not raw intermediate data.

Examples:

- `请给我一份美心翼申的投资建议`
- `分析920833.BJ，给出买卖建议和止损位`
- `这只股票值不值得买`
- `帮我给出目标价、止损位和持有建议`
- `帮我用多智能体框架分析这只 A 股，并给出交易策略`
