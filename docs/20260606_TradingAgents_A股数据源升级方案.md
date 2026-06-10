# TradingAgents 原版 A 股数据源升级方案

> 整理时间：2026-06-06
> 整理人：Mavis

---

## 一、问题诊断

### 1.1 原版对 A 股的真实支持程度

原版 `v0.2.5` 声称支持 A 股（`.SS` / `.SZ` 后缀），但实际存在三个根本性缺陷：

**缺陷 1：数据质量严重不足**

| 数据类型 | 原版依赖 | A 股实际情况 |
|---------|---------|------------|
| 实时行情 | Yahoo Finance | yfinance 对 A 股数据有 1-3 天延迟，且部分股票存在"可能退市"警告 |
| 技术指标 | yfinance + stockstats | 同上，数据陈旧导致指标失真 |
| 基本面 | yfinance | yfinance 对 A 股财报收录不完整，特别是上交所股票 |
| 新闻舆情 | StockTwits + Reddit + Yahoo Finance | 三者均不覆盖 A 股 → Sentiment/News Analyst 输出为空 |
| 内幕交易 | Alpha Vantage | A 股不适用 |

**缺陷 2：舆情数据源完全缺失**

跑赛力斯时，Sentiment Analyst 的三个数据源全部哑火：
- StockTwits：HTTP 404（不支持 A 股）
- Reddit：无提及帖子
- Yahoo Finance 新闻：无 A 股新闻数据

结果：Sentiment Analyst 输出 `Neutral，Score 5.0，Confidence: Low`，本质上是"无法评估"而非真正中性。

**缺陷 3：新闻缺乏中文语境**

News Analyst 只能获取英文全球宏观新闻，对赛力斯公司的中文新闻、政策动态、A股市场特有事件完全无法捕捉。

---

### 1.2 当前数据源架构

原版的数据源路由在 `tradingagents/dataflows/interface.py` 中：

```
interface.py
├── VENDOR_LIST = ["yfinance", "alpha_vantage"]
├── VENDOR_METHODS = {method: {vendor: impl_function}}
└── route_to_vendor() → 按 category → vendor 路由，有完整的 fallback 链
```

目前两层路由：
- `data_vendors`（类别级）：`core_stock_apis`、`technical_indicators` 等默认走哪个 vendor
- `tool_vendors`（工具级）：单个工具可覆盖类别默认值

**核心问题**：这个路由机制没有按**股票市场类型**（美股/A股/港股）来选择数据源，所有股票都用同一套 vendor 配置。

---

### 1.3 升级目标

1. **自动识别 A 股**：通过 ticker 后缀（`.SS` / `.SZ`）自动路由到中国数据源
2. **Tushare 作为 A 股主数据源**：利用你已有的 Tushare Pro Token
3. **AkShare 作为备用数据源**：免费，无需 Key，做 fallback
4. **中文新闻源**：东方财富、同花顺等 A 股中文财经新闻
5. **保持原有美股功能不变**：对美股继续使用 yfinance / Alpha Vantage

---

## 二、升级架构设计

### 2.1 整体架构

```
数据源路由层（dataflows/interface.py 增强）
│
├── 自动识别 ticker 市场类型
│   ├── .SS / .SZ → 中国 A 股
│   ├── .HK       → 香港股票
│   ├── .T        → 日本股票
│   └── 无后缀    → 美股（默认）
│
├── A 股路由链
│   ├── 主数据源：Tushare Pro（你的 Token）
│   ├── 次数据源：AkShare（免费备用）
│   └── 兜底：yfinance（极有限）
│
├── 美股路由链（保持不变）
│   └── yfinance → Alpha Vantage（fallback）
│
└── 中文新闻路由
    ├── 主：东方财富（eastmoney）
    └── 次：同花顺（10jqka）
```

### 2.2 新增文件清单

```
tradingagents/dataflows/
├── tushare_stock.py          # Tushare OHLCV + 指标数据
├── tushare_financials.py     # Tushare 财务报表（利润表/资产负债表/现金流量表）
├── akshare_wrapper.py        # AkShare 封装（免费备用数据源）
├── china_news.py             # 中文财经新闻（东方财富/同花顺）
├── market_detector.py        # 通过 ticker 后缀自动识别市场类型
└── interface.py             # 【修改】增强路由逻辑，按市场类型分发
```

---

## 三、详细实施方案

### 3.1 第一步：环境依赖

```bash
pip install tushare akshare
```

> Tushare Pro 需要 Token（已配置在 `E:\BaiduSyncdisk\WorkSpace\config.json`）
> AkShare 完全免费，无需 Token

### 3.2 第二步：配置增强（default_config.py）

**新增配置项：**

```python
# 中国数据源配置
"china_data_vendors": {
    "primary": "tushare",      # 主数据源
    "fallback": "akshare",     # 备用数据源
},
"china_news_vendor": "eastmoney",  # 中文新闻源

# Tushare Token
"TUSHARE_TOKEN": "9d95884fa9d648213bf77a0686323d92eccb7108250d5cd4a17514a6",

# 工具级数据源覆盖（新增）
"tool_vendors": {
    # A 股专用
    "get_stock_data": "china_when_applicable",  # 新增路由逻辑
    "get_indicators": "china_when_applicable",
    "get_fundamentals": "china_when_applicable",
    "get_news": "china_news_when_applicable",
},
```

### 3.3 第三步：市场识别模块（market_detector.py）

```python
"""通过 ticker 后缀自动识别市场类型"""

class MarketType(Enum):
    A_SHARE_CN = "a_share_cn"      # A股（.SS/.SZ）
    HK = "hk"                        # 港股（.HK）
    JP = "jp"                        # 日股（.T）
    US = "us"                        # 美股（无后缀）
    CRYPTO = "crypto"               # 加密货币
    OTHER = "other"

def detect_market(ticker: str) -> MarketType:
    t = ticker.upper()
    if t.endswith(".SS") or t.endswith(".SZ"):
        return MarketType.A_SHARE_CN
    elif t.endswith(".HK"):
        return MarketType.HK
    elif t.endswith(".T"):
        return MarketType.JP
    elif "-USD" in t or "-USDT" in t:
        return MarketType.CRYPTO
    elif "." not in t:
        return MarketType.US
    else:
        return MarketType.OTHER
```

### 3.4 第四步：Tushare 数据实现

**tushare_stock.py — 行情和指标**

```python
import tushare as ts
from typing import Annotated

def get_tushare_stock_data(
    symbol: Annotated[str, "A股代码，如 '601127'"],
    start_date: str,
    end_date: str,
) -> str:
    """获取 A 股日线行情数据"""
    pro = ts.pro_api(TUSHARE_TOKEN)

    # Tushare 代码转换：601127.SS → 601127.SH（上交所）
    ts_code = symbol.replace(".SS", ".SH").replace(".SZ", ".SZ")

    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    # 转换为 OHLCV 格式输出
    return df_to_ohlcv_csv(df, ts_code)
```

**tushare_financials.py — 财务报表**

```python
def get_tushare_financials(symbol: str, year: int) -> str:
    """获取 A 股年报/季报财务数据"""
    pro = ts.pro_api(TUSHARE_TOKEN)
    ts_code = symbol.replace(".SS", ".SH").replace(".SZ", ".SZ")

    # 利润表
    income = pro.income(ts_code=ts_code, period=str(year))
    # 资产负债表
    balance = pro.balancesheet(ts_code=ts_code, period=str(year))
    # 现金流量表
    cashflow = pro.cashflow(ts_code=ts_code, period=str(year))

    return format_financial_report(income, balance, cashflow)
```

### 3.5 第五步：中文新闻源（china_news.py）

**关键挑战**：A股舆情无法从 Reddit/StockTwits 获取，需要中文数据源。

| 中文数据源 | 类型 | 说明 |
|-----------|------|------|
| 东方财富（eastmoney） | 新闻 + 公告 | 最全，API 友好 |
| 同花顺（10jqka） | 新闻 + 舆情 | 社区数据丰富 |
| 巨潮资讯 | 官方公告 | 监管文件 |

```python
def get_china_stock_news(symbol: str, days: int = 7) -> str:
    """获取 A 股相关新闻和公告"""
    import akshare as ak

    # 东方财富个股新闻
    news_df = ak.stock_news_em(symbol=symbol)
    # 东财个股公告
    ann_df = ak.stock_announcement_em(symbol=symbol)

    return format_china_news(news_df, ann_df)
```

### 3.6 第六步：interface.py 路由逻辑增强

**核心改动**：在 `route_to_vendor()` 中增加市场类型检测

```python
def route_to_vendor(method: str, *args, **kwargs):
    # 1. 从参数中提取 ticker（大多数工具的第一个参数）
    ticker = _extract_ticker(method, args, kwargs)

    # 2. 识别市场类型
    market = detect_market(ticker)

    # 3. 根据市场类型选择数据源
    if market == MarketType.A_SHARE_CN:
        return _route_china(method, *args, **kwargs)
    else:
        # 保持原有美股路由逻辑不变
        return _route_us(method, *args, **kwargs)

def _route_china(method: str, *args, **kwargs):
    """A 股路由：Tushare → AkShare → yfinance"""
    china_vendors = ["tushare", "akshare"]

    for vendor in china_vendors:
        if vendor not in VENDOR_METHODS.get(method, {}):
            continue
        try:
            return VENDOR_METHODS[method][vendor](*args, **kwargs)
        except Exception:
            continue

    # 兜底：回退到 yfinance（数据可能陈旧）
    if "yfinance" in VENDOR_METHODS.get(method, {}):
        return VENDOR_METHODS[method]["yfinance"](*args, **kwargs)

    raise NoMarketDataError(...)
```

---

## 四、Tushare vs AkShare 功能对照

| 功能 | Tushare Pro | AkShare |
|------|------------|---------|
| 日线行情 | ✅ | ✅ |
| 分钟线 | ✅（需权限） | ✅ |
| 财务数据 | ✅（完整年报/季报） | ✅ |
| 资金流向 | ✅ | ✅ |
| 舆情/新闻 | ❌（无） | ✅（东方财富） |
| 龙虎榜 | ✅ | ✅ |
| 指数数据 | ✅ | ✅ |
| 需要的 Token | ✅（你有） | ❌（免费） |
| 每日调用限制 | 2000积分/日 | 无限制 |

**建议策略**：Tushare 作为基本面/行情主数据源；AkShare 作为新闻/舆情主数据源，同时作为行情的 fallback。

---

## 五、舆情增强方案（对 A 股最关键）

### 5.1 问题分析

当前 `Sentiment Analyst` 对 A 股失效的原因：

| 数据源 | 状态 | 替代方案 |
|--------|------|---------|
| StockTwits | 404 | 东方财富股吧 / 同花顺社区 |
| Reddit | 无 A 股帖子 | 雪球（xueqiu.com）|
| Yahoo Finance 新闻 | 无 A 股新闻 | 东方财富 news API |

### 5.2 解决方案：新增 `Sentiment Analyst China` 分支

```python
def get_china_social_sentiment(symbol: str) -> dict:
    """
    获取 A 股舆情数据，输出结构与美股 Sentiment Analyst 兼容：
    - overall_band: Bullish/Neutral/Bearish
    - overall_score: 0-10
    - sources: [{name, signal, evidence}]
    """
    import akshare as ak

    # 1. 东方财富股吧帖子情绪（通过 akshare）
    try:
        posts = ak.stock_board_em(symbol=symbol)
        sentiment = analyze_china_posts_sentiment(posts)
    except Exception:
        sentiment = None

    # 2. 同花顺投资者互动
    try:
        qa = ak.stock_individual_xq_realtime(symbol=symbol)
        interaction_score = analyze_qa_sentiment(qa)
    except Exception:
        interaction_score = None

    # 3. 整合输出
    return aggregate_china_sentiment(sentiment, interaction_score)
```

### 5.3 中文新闻增强

当前 `News Analyst` 只能输出英文全球宏观新闻。增强后：

```python
def get_china_company_news(symbol: str, days: int = 7) -> str:
    """
    获取 A 股公司相关中文新闻，
    格式与英文 News Analyst 输出兼容，
    方便后续 Agent 理解。
    """
    import akshare as ak

    news = []

    # 1. 东方财富个股新闻
    try:
        news_em = ak.stock_news_em(symbol=symbol)
        news.extend(news_em.to_dict("records"))
    except Exception:
        pass

    # 2. 公司公告（监管文件）
    try:
        ann = ak.stock_announcement_em(symbol=symbol)
        news.extend([{"type": "announcement", **a} for a in ann.to_dict("records")])
    except Exception:
        pass

    # 3. 宏观 A 股新闻
    try:
        macro = ak.stock_market_news()
        stock_news = macro[macro["symbol"] == symbol]
        news.extend(stock_news.to_dict("records"))
    except Exception:
        pass

    return format_china_news_report(news)
```

---

## 六、实施路线图

### Phase 1：数据源核心（预计 1-2 天）

- [ ] 安装 `tushare` 和 `akshare` 依赖
- [ ] 实现 `market_detector.py`（市场类型识别）
- [ ] 实现 `tushare_stock.py`（A 股行情）
- [ ] 实现 `tushare_financials.py`（A 股财报）
- [ ] 修改 `interface.py` 路由逻辑
- [ ] 修改 `default_config.py` 增加配置项

### Phase 2：新闻与舆情（预计 1-2 天）

- [ ] 实现 `china_news.py`（东方财富 + 同花顺）
- [ ] 在 `Sentiment Analyst` 中新增 A 股舆情分支
- [ ] 在 `News Analyst` 中新增中文新闻分支
- [ ] 修改 `Social Analyst` 工具集支持 A 股

### Phase 3：测试与调优（预计 1 天）

- [ ] 用赛力斯（601127.SS）跑完整 4 Agent 流程，验证数据正确性
- [ ] 对比 Tushare 数据与之前 yfinance 数据的差异
- [ ] 测试港股（.HK）路由是否正常工作
- [ ] 确认美股功能未受影响

### Phase 4：可选增强

- [ ] 集成雪球（xueqiu）舆情 API
- [ ] 集成天天基金（fund）数据
- [ ] 支持 A 股指数（上证指数、深证成指等）

---

## 七、你的 TuShare Token 确认

你的 Tushare Pro Token 已确认：

```
Token: 9d95884fa9d648213bf77a0686323d92eccb7108250d5cd4a17514a6
```

Token 存储位置：`E:\BaiduSyncdisk\WorkSpace\config.json` → `datafeed.tushare_pro.password`

Tushare Pro 调用方式：
```python
import tushare as ts
ts.set_token('your_token')
pro = ts.pro_api()
```

---

## 八、关键注意事项

### 8.1 Tushare 积分限制

Tushare Pro 有每日调用积分限制（默认 2000 积分/日）。高频分析场景下需要注意：
- 每次 `get_stock_data` 调用约消耗 1-2 积分
- 每个分析师跑一次约需 10-20 次数据调用
- 建议设置每日最大分析次数，或接入 AkShare 作为 fallback

### 8.2 A 股代码转换

| Yahoo Finance 格式 | Tushare 格式 | 说明 |
|------------------|-------------|------|
| `601127.SS` | `601127.SH` | 上交所股票 |
| `000001.SZ` | `000001.SZ` | 深交所股票（代码相同）|

需要在 `market_detector.py` 中实现自动转换逻辑。

### 8.3 兼容美股

所有改动必须保持美股（无后缀 ticker）继续使用 `yfinance`，不引入任何回归。

---

## 九、参考：CN 版已实现的功能（可移植）

CN 版 `TradingAgents-CN` 已完整实现以下功能，可直接参考其代码：

| CN 版路径 | 功能 | 可参考程度 |
|---------|------|----------|
| `dataflows/providers/china/tushare.py` | 完整 Tushare Provider | ⭐⭐⭐⭐⭐ 直接参考 |
| `dataflows/providers/china/akshare.py` | AkShare 封装 | ⭐⭐⭐⭐ 直接参考 |
| `dataflows/data_source_manager.py` | 多数据源管理器 | ⭐⭐⭐⭐ 参考架构设计 |
| `dataflows/providers/china/fundamentals_snapshot.py` | A 股基本面快照 | ⭐⭐⭐⭐ 直接参考 |

**建议**：直接移植 CN 版中 `dataflows/providers/china/` 下的文件到原版，然后修改接口以适配原版的路由机制。
