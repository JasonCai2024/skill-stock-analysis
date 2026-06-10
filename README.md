# 📈 OpenClaw 股票智能分析与研报生成技能 (skill-stock-analysis)

本仓库是基于 **OpenClaw** 智能体网关架构开发的 A 股股票智能分析技能。它能够自动调度多智能体协作网络（TradingAgents），对指定的 A 股股票进行基本面、技术面、消息舆情的全方位量化分析，并自动输出格式标准的专业证券研究报告。

---

## 🌟 核心功能

* **多智能体协同分析**：
  * **基本面分析师 (Fundamentals Analyst)**：评估财务健康度、资产负债表、利润表与现金流质量。
  * **市场/技术分析师 (Market Analyst)**：基于日线数据分析 EMA、MACD、RSI、布林带等技术指标，捕捉超买超卖与反转信号。
  * **消息/舆情分析师 (News & Sentiment Analyst)**：监控新闻动向与社交媒体舆情。
  * **交易员 (Trader)**：基于技术面制定包含建仓区间、止损价与目标价的执行方案。
  * **投资组合经理 (Portfolio Manager)**：对分歧观点进行裁决，给出最终的评级结论与资金配置建议。
* **数据流免密代理**：所有 Tushare 数据与 LLM 接口默认通过 ServiceHub 代理进行转发，调用者无需配置本地 Tushare Token。
* **自动化研报生成**：分析结束后，系统会自动编译生成结构固化、逻辑一致的标准化 Markdown 中文研究报告（`.md` 文件）。

---

## 📂 技能文件结构

```text
skill-stock-analysis/
├── SKILL.md                 # OpenClaw 技能定义描述文件（定义工作流与规则）
├── main.py                  # TradingAgents 核心执行入口
├── requirements.txt         # 技能依赖的 Python 依赖包
├── .env.example             # 本地私有环境变量/凭证模板
├── docs/                    # 技能设计与技术规格文档
├── scripts/
│   ├── run_analysis.py      # 技能主包装运行脚本
│   └── render_report.py     # 自动化 Markdown 研报渲染器
└── tradingagents/           # 自包含的 TradingAgents 多智能体核心库
```

---

## 🚀 快速开始

### 1. 克隆并放入 OpenClaw 技能目录
将本目录放入您 OpenClaw 网关的技能加载路径下（例如 `~/.openclaw/workspace/skills/`）：
```bash
git clone https://github.com/JasonCai2024/skill-stock-analysis.git
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置凭证
复制根目录下的 `.env.example` 并重命名为 `.env`，填入您的 ServiceHub 凭证：
```bash
cp .env.example .env
```
编辑 `.env`：
```env
SERVICETUBER_USERNAME=您的用户名
SERVICETUBER_PASSTOKEN=您的Passtoken
SERVICETUBER_BASE_URL=https://www.ccailab.top
TRADINGAGENTS_LLM_PROVIDER=servicehub
```
> [!NOTE]
> `.env` 文件已被列入 `.gitignore`，您的私有密码永远不会被提交到 Git 仓库，确保了分享安全性。

### 4. 在 OpenClaw 中调用
在 OpenClaw 的对话框中，您只需发出以下指令即可自动触发技能：
* *“帮我分析一下智飞生物的股价”*
* *“分析 601127.SH 的基本面”*
* *“望变电气最近值得买入吗？”*

---

## 📊 报告输出归档
运行完成后，技能会自动在以下路径归档两份文件：
* **JSON 运行全状态记录**：`reports/logs/<代码>/TradingAgentsStrategy_logs/full_states_log_<日期>.json`
* **Markdown 证券研究报告**：`reports/logs/<代码>/TradingAgentsStrategy_logs/full_states_log_<日期>.md`
