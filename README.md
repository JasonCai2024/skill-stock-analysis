# skill-stock-analysis

`skill-stock-analysis` 是一个上层决策型股票技能。它基于 TradingAgents 多分析角色流程，为 A 股股票生成一份面向投资动作的研究报告，而不是只做泛化的公司介绍或事实查询。

它的核心输出不是“公司情况汇总”，而是：

1. 买入、卖出或持有建议
2. 目标价
3. 止损位
4. 持有周期
5. 复核触发条件

## 定位

适合以下请求：

- 给我投资建议
- 这只股票值不值得买
- 给我买卖建议
- 给我交易策略
- 给我目标价和止损位
- 用多智能体框架分析这只股票

不适合作为以下请求的默认入口：

- 分析一下这家公司
- 了解一下这家公司
- 看看它的主营业务
- 看看近三年财务
- 看看最近行情

这类请求默认应由下层技能 `skill-tushare-servicehub-assistant` 承接，因为它更适合公司情况、财务、行情、股权结构和结构化数据查询。

## 分析模块

本技能以多角色协同方式生成最终决策，主要包括：

1. Fundamentals Analyst
2. Market Analyst
3. News Analyst
4. Sentiment Analyst
5. Trader
6. Portfolio Manager

上面的模块共同服务于一个目标：形成最终交易建议。

## 与下层技能的关系

本技能依赖同级目录下的 `skill-tushare-servicehub-assistant`。

推荐目录结构：

```text
SKILLS-办公技能/
├─ skill-stock-analysis/
└─ skill-tushare-servicehub-assistant/
```

本技能不会直接调用 Tushare 官方接口，而是复用下层技能提供的：

1. 公司解析能力
2. ServiceHub 凭证
3. 本地缓存库
4. 本地业务仓库
5. 稳定公开函数

## 安装

```bash
git clone https://github.com/JasonCai2024/skill-stock-analysis.git
cd skill-stock-analysis
pip install -r requirements.txt
```

## 运行前准备

在运行前，需要具备 ServiceHub 账号信息。运行时设置：

```env
SERVICETUBER_BASE_URL=https://www.ccailab.top
SERVICETUBER_USERNAME=<your-username>
SERVICETUBER_PASSTOKEN=<your-passtoken>
TRADINGAGENTS_LLM_PROVIDER=servicehub
```

## 输出

运行完成后，会在 `reports/logs/<ticker>/TradingAgentsStrategy_logs/` 下生成：

1. JSON 全量状态文件
2. Markdown 标准研究报告

## 推荐触发示例

- `请给我一份美心翼申的投资建议`
- `分析920833.BJ，给出买卖建议`
- `这只股票值不值得买`
- `帮我给出目标价、止损位和持有建议`
- `用 TradingAgents 分析一下这只 A 股`

## 不推荐作为本技能触发的模糊示例

以下表达默认不应该直接触发本技能：

- `分析一下某某公司`
- `了解一下某某上市公司`
- `帮我看看这家公司`

这些请求应优先理解为“公司情况或泛分析需求”，默认转由 `skill-tushare-servicehub-assistant` 处理；只有当用户进一步明确要投资建议或交易建议时，再切到本技能。
