# AKShare 与 BaoStock 推荐接口及调试指南

> 面向金融工作台与数据采集 Agent。目标是让 Agent 能根据数据需求选择正确接口，并在东方财富不可用、代理异常、字段漂移或数据为空时安全降级。
>
> 基准版本：AKShare `1.18.81`、BaoStock `0.9.3`；整理日期：2026-08-01。第三方数据接口可能随时变化，升级依赖后应重新执行本文的字段探针。

## 1. 先看结论：接口选择总表

| 数据需求 | AKShare 首选 | AKShare 备用 | BaoStock 兜底 | 结论 |
|---|---|---|---|---|
| A 股全市场实时快照 | `stock_zh_a_spot_tx()`（腾讯） | `stock_zh_a_spot()`（新浪） | 无实时接口 | 腾讯优先；BaoStock 只能用最近收盘数据降级 |
| A 股个股日线 | `stock_zh_a_hist_tx()`（腾讯） | `stock_zh_a_daily()`（新浪） | `query_history_k_data_plus()` | 推荐顺序：腾讯 → 新浪 → BaoStock → 本地缓存 |
| A 股分钟线 | `stock_zh_a_minute()`（新浪） | — | `query_history_k_data_plus(frequency="5/15/30/60")` | BaoStock 分钟线不支持指数；字段与日线不同 |
| A 股指数日线 | `stock_zh_index_daily_tx()`（腾讯） | `stock_zh_index_daily()`（新浪） | `query_history_k_data_plus()` | 腾讯接口的 `amount` 不要直接当成交额 |
| A 股指数实时快照 | `stock_zh_index_spot_sina()` | — | 无实时接口 | 无实时源时展示最近交易日收盘并标注延迟 |
| 港股日线/快照 | `stock_hk_daily()` / `stock_hk_spot()`（新浪） | 东财接口仅作增强源 | 不支持 | BaoStock 不能兜底港股 |
| 美股日线/快照 | `stock_us_daily()` / `stock_us_spot()`（新浪） | — | 不支持 | 新浪快照约延迟 15 分钟 |
| 美股指数日线 | `index_us_stock_sina()` | — | 不支持 | 支持标普、纳指、道指、纳斯达克 100 |
| A 股交易日历 | `tool_trade_date_hist_sina()` | — | `query_trade_dates()` | 两源结果可交叉校验 |
| A 股证券主表 | 上交所/深交所/北交所官方列表接口 | `stock_info_a_code_name()` | `query_stock_basic()` / `query_all_stock()` | 证券主表优先交易所官方接口 |
| 指数成分股 | `index_stock_cons_csindex()` | `index_stock_cons_weight_csindex()` | 沪深 300/上证 50/中证 500 专用接口 | 中证 1000 等优先中证指数官网接口 |
| 申万行业归属 | `stock_industry_clf_hist_sw()` | — | 不等价 | BaoStock 是证监会行业口径，禁止直接混用 |
| 行业行情/热力图 | 个股收益 + 统一行业映射自行聚合 | `stock_board_industry_index_ths()` | 个股收益 + `query_stock_industry()` | 工作台推荐自行聚合，口径最透明 |
| 行业当前概览 | `stock_board_industry_summary_ths()` | — | 无等价接口 | 同花顺口径，不能与申万行业直接拼接 |
| 板块主力资金流 | `stock_sector_fund_flow_rank()`（东财） | `stock_board_industry_summary_ths()` 仅作不同口径参考 | 无等价接口 | 东财失败时不要用收益率冒充资金流 |
| 市场广度 | 全市场个股日线自行聚合 | `stock_a_high_low_statistics()` | `query_daily_history_k_AStock()` | 上涨/下跌、收益中位数建议自行计算 |
| 融资融券汇总 | `stock_margin_sse()` + `stock_margin_szse()` | — | 无推荐等价接口 | 分沪深两市抓取后按日期汇总 |
| 财务与估值 | AKShare 对应财务接口 | — | `query_*_data()` 系列 | BaoStock 很适合做基础财务兜底 |

## 2. 推荐的系统级降级策略

```text
A股个股日线：AKShare/腾讯 → AKShare/新浪 → BaoStock → 本地最近成功缓存
A股指数日线：AKShare/腾讯 → AKShare/新浪 → BaoStock → 本地最近成功缓存
A股实时快照：AKShare/腾讯 → AKShare/新浪 → 最近收盘价（必须标 stale）
港股：AKShare/新浪 → 其他独立供应商 → 本地缓存
美股：AKShare/新浪 → 其他独立供应商 → 本地缓存
板块资金流：AKShare/东财 → 显示“数据源暂不可用”
行业热力图：统一行业映射 + 个股收益自行计算，不依赖资金流接口
```

降级原则：

1. 降级只能替代同一语义的数据。价格收益率、成交额和“主力资金净流入”是三种不同指标。
2. 每条入库记录必须保存 `source`、`source_api`、`adjustment`、`fetched_at` 和 `is_stale`。
3. 不同源的复权价格不能直接首尾拼接。切源后至少检查重叠交易日的收盘价误差。
4. 空 DataFrame 不一定代表股票不存在，也可能是接口限流、参数格式错误、退市或上游结构变化。
5. 核心行情失败时允许使用缓存；资金流失败时宁可缺失，也不要伪造替代值。

## 3. AKShare：非东财优先接口

### 3.1 A 股实时快照

#### 首选：腾讯

```python
import akshare as ak

df = ak.stock_zh_a_spot_tx()
```

- 数据源：腾讯证券。
- 范围：沪、深、北 A 股全市场快照。
- 优点：不依赖 `eastmoney.com`，适合当前工作台实时页。
- 注意：返回字段是腾讯原始字段风格，AKShare 升级后可能变化；接入层应做字段存在性检查，而不是依赖列位置。

#### 备用：新浪

```python
df = ak.stock_zh_a_spot()
```

- 数据源：新浪财经。
- 适合腾讯快照失败时短时降级。
- 批量、高频调用可能触发限流或封禁 IP；务必缓存并限制并发。

### 3.2 A 股个股日线

#### 首选：腾讯 `stock_zh_a_hist_tx`

```python
df = ak.stock_zh_a_hist_tx(
    symbol="sz000001",       # 也接受 000001；推荐内部统一后再转换
    start_date="20250101",
    end_date="20260801",
    adjust="qfq",            # "" / "qfq" / "hfq"
    timeout=15,
)
```

AKShare `1.18.81` 的标准输出列为：

```text
date, open, close, high, low, volume, turnover, amount
```

当前实现的单位处理：

- `volume`：统一为股；
- `amount`：统一为元；
- `turnover`：实现中除以 100，按小数比率使用，例如 `0.023` 表示 `2.3%`。

Agent 必须在依赖升级后用一只高流动性股票抽样验证单位，禁止再次无条件乘以 100 或 10,000。

#### 备用：新浪 `stock_zh_a_daily`

```python
df = ak.stock_zh_a_daily(
    symbol="sh600519",
    start_date="20250101",
    end_date="20260801",
    adjust="qfq",  # "" / "qfq" / "hfq" / "qfq-factor" / "hfq-factor"
)
```

常见输出包含：

```text
date, open, high, low, close, volume, amount, outstanding_share, turnover
```

注意：

- AKShare 官方说明该接口大量抓取容易封 IP，不适合每日并发抓取数千只股票；
- 新浪与腾讯的复权算法可能不同，不能把两源复权序列直接拼成一条；
- `qfq-factor` / `hfq-factor` 返回的是复权因子，不是 K 线。

### 3.3 A 股分钟线

```python
df = ak.stock_zh_a_minute(
    symbol="sh600519",
    period="5",     # "1" / "5" / "15" / "30" / "60"
    adjust="",      # "" / "qfq" / "hfq"
)
```

- 数据源：新浪财经。
- 当前接口单次大约只取最近 `1970` 根，不能当作无限历史库。
- 输出时间列通常为 `day`，接入层应转换为带 `Asia/Shanghai` 时区的时间戳。
- 分钟复权会依赖新浪日线复权结果；若日线接口被限流，分钟复权也可能失败。

### 3.4 A 股指数

#### 日线首选：腾讯

```python
df = ak.stock_zh_index_daily_tx(
    symbol="sh000300",
    start_date="20250101",
    end_date="20260801",
)
```

输出列：

```text
date, open, close, high, low, amount
```

关键陷阱：该接口虽然把第六列命名为 `amount`，但腾讯指数数据中它通常对应成交量语义，历史文档也曾按“手”解释。除非经过样本核对，不得映射为 `amount_cny`。推荐先落为 `raw_activity`，或单独维护该接口的字段映射。

#### 日线备用：新浪

```python
df = ak.stock_zh_index_daily(symbol="sh000300")
```

- 一次返回该指数可用的全部历史数据；不能传开始/结束日期，需在本地过滤。
- 官方提示大量抓取容易封 IP。

#### 实时快照：新浪

```python
df = ak.stock_zh_index_spot_sina()
```

常用指数代码：

| 指数 | AKShare 腾讯/新浪代码 | BaoStock 代码 |
|---|---|---|
| 上证指数 | `sh000001` | `sh.000001` |
| 沪深 300 | `sh000300` | `sh.000300` |
| 中证 500 | `sh000905` | `sh.000905` |
| 中证 1000 | `sh000852` | `sh.000852` |
| 深证成指 | `sz399001` | `sz.399001` |
| 创业板指 | `sz399006` | `sz.399006` |
| 上证红利 | `sh000015` | `sh.000015` |

### 3.5 港股与美股

```python
# 港股历史与快照
hk_daily = ak.stock_hk_daily(symbol="00700", adjust="qfq")
hk_spot = ak.stock_hk_spot()

# 美股历史与快照
us_daily = ak.stock_us_daily(symbol="AAPL", adjust="qfq")
us_spot = ak.stock_us_spot()  # 约延迟 15 分钟

# 美股指数
sp500 = ak.index_us_stock_sina(symbol=".INX")
nasdaq = ak.index_us_stock_sina(symbol=".IXIC")
dow = ak.index_us_stock_sina(symbol=".DJI")
ndx100 = ak.index_us_stock_sina(symbol=".NDX")
```

注意：

- `stock_hk_daily` 支持 `""`、`qfq`、`hfq`，以及因子模式；
- `stock_us_daily` 支持未复权、`qfq` 和前复权因子，不要假设支持 `hfq`；
- 新浪美股个别股票存在错误复权因子的历史记录，复权前后应检查异常跳变；
- BaoStock 不支持港股和美股，不能作为这两类资产的备份。

### 3.6 证券列表与交易日历

证券主表优先使用交易所官方源：

```python
sz = ak.stock_info_sz_name_code(symbol="A股列表")
sh_main = ak.stock_info_sh_name_code(symbol="主板A股")
sh_star = ak.stock_info_sh_name_code(symbol="科创板")
bj = ak.stock_info_bj_name_code()

calendar = ak.tool_trade_date_hist_sina()
```

原因：交易所列表能明确区分沪市主板、科创板、深市和北交所，适合作为证券主数据。`stock_info_a_code_name()` 可以快速取全 A 代码名称，但不应成为唯一证券主表来源。

### 3.7 指数成分股

```python
# 最新成分股
cons = ak.index_stock_cons_csindex(symbol="000300")

# 最新成分权重
weights = ak.index_stock_cons_weight_csindex(symbol="000300")
```

- 数据源：中证指数有限公司官网文件。
- 适合沪深 300、中证 500、中证 1000 等中证系列指数。
- 接口返回的是最新快照，不等于完整历史调仓记录；回测时不能把今天的成分股用于历史日期，否则产生幸存者偏差。

### 3.8 行业分类、行业行情与资金流

#### 申万行业历史归属

```python
sw = ak.stock_industry_clf_hist_sw()
```

主要字段包括：

```text
symbol, start_date, industry_code, update_time, ...
```

该接口适合建立“股票—申万行业—生效日期”的映射。行业收益热力图应固定一个层级，例如申万一级，并按生效日期关联股票，避免历史口径漂移。

#### 同花顺行业行情

```python
industry_names = ak.stock_board_industry_name_ths()
industry_index = ak.stock_board_industry_index_ths(
    symbol="半导体",
    start_date="20250101",
    end_date="20260801",
)
industry_snapshot = ak.stock_board_industry_summary_ths()
```

- `stock_board_industry_index_ths`：行业指数 OHLC、成交量和成交额历史；
- `stock_board_industry_summary_ths`：当期板块涨跌幅、总成交额、净流入、上涨/下跌家数等；
- 这是同花顺行业口径，不是申万行业口径。除非有明确映射表，不能与申万行业数据按名称直接合并。

#### 东财板块资金流

```python
flow = ak.stock_sector_fund_flow_rank(
    indicator="今日",          # "今日" / "5日" / "10日"
    sector_type="行业资金流",  # "行业资金流" / "概念资金流" / "地域资金流"
)
```

此接口请求 `push2.eastmoney.com`，属于东方财富特色数据。使用规则：

- 它是“资金流”指标，不是价格收益率；
- 官方接口只保证行业/概念/地域选择，并未保证结果为纯申万某一级行业；
- `白酒`、`白酒Ⅱ` 等名称可能对应不同分类层级或不同成分范围；
- 禁止删除罗马数字后按名称合并，禁止把资金流数值相加；
- 去重优先键应是 `(source, classification, level, sector_code)`；缺代码时才退化到 `(source, level, normalized_name)`；
- 东财不可用时，展示“资金流数据源暂不可用”。`stock_board_industry_summary_ths()` 的“净流入”只能作为同花顺口径的独立指标，不能无提示替换。

### 3.9 市场广度与流动性

推荐从全市场个股行情自行计算：

```text
上涨/下跌家数：close > preclose / close < preclose
全市场收益中位数：median(close / preclose - 1)
20日新高/新低：close 或 high 与过去20个交易日窗口比较
两市成交额：沪深 A 股 amount 求和；明确是否包含北交所、ETF、B股
```

AKShare 可用的辅助接口：

```python
high_low = ak.stock_a_high_low_statistics(symbol="all")
margin_sh = ak.stock_margin_sse(start_date="20250101", end_date="20260801")
margin_sz = ak.stock_margin_szse(date="20260801")
```

- `stock_a_high_low_statistics` 来自乐咕乐股，可取 20/60/120 日新高新低数量；核心系统仍应保留自行计算能力。
- 沪市融资融券接口可取日期范围，深市汇总接口按单日查询；合并前统一单位和交易日期。
- “两市成交额”通常指沪深市场，不应默认把北交所、港股或美股计入。

## 4. BaoStock：推荐接口

### 4.1 使用模型与连接特性

BaoStock 所有查询前需要登录，结果不是 DataFrame，而是游标式 `ResultData`：

```python
import baostock as bs
import pandas as pd

login_result = bs.login()
if login_result.error_code != "0":
    raise RuntimeError(login_result.error_msg)

try:
    rs = bs.query_trade_dates("2026-01-01", "2026-12-31")
    if rs.error_code != "0":
        raise RuntimeError(rs.error_msg)

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
finally:
    bs.logout()
```

连接注意事项：

- BaoStock `0.9.3` 默认连接 `public-api.baostock.com:10030`；这是原始 TCP socket，不是普通 HTTP 请求；
- `HTTP_PROXY`、`HTTPS_PROXY`、`requests.Session.trust_env` 通常不会控制这条连接；
- 公司网络、云环境或防火墙若禁止出站 TCP 10030，`login()` 会直接失败；
- 一个采集进程保持一次登录即可，不要每只股票反复登录/登出；
- 所有值通常先以字符串返回，入库前必须显式转换数值和日期。

### 4.2 历史 K 线：核心兜底接口

```python
fields = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)

rs = bs.query_history_k_data_plus(
    code="sh.600000",
    fields=fields,
    start_date="2025-01-01",
    end_date="2026-08-01",
    frequency="d",
    adjustflag="2",
)
```

参数规则：

| 参数 | 可用值 | 说明 |
|---|---|---|
| `code` | `sh.600000`、`sz.000001` | 与 AKShare 的 `sh600000` 格式不同 |
| `frequency` | `d`、`w`、`m`、`5`、`15`、`30`、`60` | 日/周/月/分钟 |
| `adjustflag` | `1` | 后复权 |
| `adjustflag` | `2` | 前复权，组合净值与收益计算推荐 |
| `adjustflag` | `3` | 不复权，默认值 |

字段集合：

- 日线可用：`date, code, open, high, low, close, preclose, volume, amount, adjustflag, turn, tradestatus, pctChg, peTTM, pbMRQ, psTTM, pcfNcfTTM, isST`；
- 分钟线可用：`date, time, code, open, high, low, close, volume, amount, adjustflag`；
- 周/月线可用：`date, code, open, high, low, close, volume, amount, adjustflag, turn, pctChg`；
- 分钟线不支持指数；不要把日线字段列表原样传给分钟线。

重要：若省略 `start_date`，BaoStock 包当前默认从 `2015-01-01` 开始。需要更早历史时必须显式传入日期。

### 4.3 单日全市场行情：市场广度首选兜底

```python
rs = bs.query_daily_history_k_AStock(date="2026-07-31")
rs_etf = bs.query_daily_history_k_ETF(date="2026-07-31")
```

- 适合计算某日上涨/下跌家数、收益中位数、成交额和估值分布；
- 比逐只股票抓同一天更高效；
- 计算 A 股广度时不要混入 ETF；
- 使用 `tradestatus` 排除停牌数据，并明确 `isST` 是否纳入统计。

### 4.4 交易日历与证券主数据

```python
trade_dates = bs.query_trade_dates(
    start_date="2026-01-01",
    end_date="2026-12-31",
)

all_stock = bs.query_all_stock(day="2026-07-31")
basic = bs.query_stock_basic(code="sh.600000", code_name="")
```

- `query_trade_dates` 返回 `calendar_date` 与 `is_trading_day`；
- `query_all_stock(day)` 返回指定日期的证券集合，适合历史截面；
- `query_stock_basic` 可按代码精确查，也可用 `code_name` 模糊查询；
- BaoStock 证券代码主要采用 `sh.` / `sz.` 前缀，不应假设覆盖北交所、港股或美股。

### 4.5 行业与指数成分股

```python
industry = bs.query_stock_industry(code="", date="2026-07-31")
hs300 = bs.query_hs300_stocks(date="2026-07-31")
sz50 = bs.query_sz50_stocks(date="2026-07-31")
zz500 = bs.query_zz500_stocks(date="2026-07-31")
```

- `query_stock_industry` 是证监会行业分类口径，不是申万或同花顺；
- 行业表建议保留 `industryClassification`、`updateDate` 等源字段；
- BaoStock 仅为沪深 300、上证 50、中证 500提供专用成分接口；中证 1000 等使用 AKShare 的中证指数官网接口；
- 回测时按历史日期请求成分股并保存快照，避免幸存者偏差。

### 4.6 复权、分红与财务数据

```python
adjust = bs.query_adjust_factor(
    code="sh.600000",
    start_date="2020-01-01",
    end_date="2026-08-01",
)

dividend = bs.query_dividend_data(
    code="sh.600000",
    year=2025,
    yearType="report",  # 或 "operate"
)

profit = bs.query_profit_data(code="sh.600000", year=2025, quarter=4)
operation = bs.query_operation_data(code="sh.600000", year=2025, quarter=4)
growth = bs.query_growth_data(code="sh.600000", year=2025, quarter=4)
dupont = bs.query_dupont_data(code="sh.600000", year=2025, quarter=4)
balance = bs.query_balance_data(code="sh.600000", year=2025, quarter=4)
cashflow = bs.query_cash_flow_data(code="sh.600000", year=2025, quarter=4)
```

推荐用途：

| 接口 | 用途 |
|---|---|
| `query_adjust_factor()` | 独立核对前/后复权因子 |
| `query_dividend_data()` | 分红、送转与除权除息信息 |
| `query_profit_data()` | ROE、利润率等盈利能力 |
| `query_operation_data()` | 应收、存货、资产周转等营运能力 |
| `query_growth_data()` | 收入、利润与权益增长 |
| `query_dupont_data()` | 杜邦分析指标 |
| `query_balance_data()` | 偿债与资本结构指标 |
| `query_cash_flow_data()` | 现金流相关指标 |
| `query_performance_express_report()` | 业绩快报 |
| `query_forecast_report()` | 业绩预告 |

回测必须使用公告日期，而不是仅按报告期日期关联，否则会产生未来函数。原始 `pubDate`、`statDate` 等日期字段必须保留。

## 5. 字段标准化规范

建议所有行情源统一到以下内部 schema：

| 内部字段 | 类型/单位 | 说明 |
|---|---|---|
| `trade_date` | `date` | 日线交易日期 |
| `ts` | timezone-aware datetime | 分钟/实时数据，统一 `Asia/Shanghai` 或资产所属市场时区 |
| `symbol` | string | 内部建议 `CN.SH.600000`、`HK.00700`、`US.AAPL` |
| `open/high/low/close` | decimal/float | 价格 |
| `preclose` | decimal/float | 昨收；源缺失时不要盲目用前一行替代停牌日 |
| `volume_shares` | float | 统一为股 |
| `amount_cny` | float | A 股成交额统一为元；无可靠语义时留空 |
| `turnover_ratio` | float | 小数比率：`0.023 = 2.3%` |
| `pct_change` | float | 小数比率：`0.01 = 1%` |
| `adjustment` | enum | `none/qfq/hfq` |
| `source` | enum | `tencent/sina/eastmoney/ths/sw/baostock/...` |
| `source_api` | string | 实际函数名 |
| `fetched_at` | datetime | 抓取时间 |
| `is_stale` | bool | 是否来自缓存或最近收盘降级 |

接口适配层必须按列名映射，禁止按 DataFrame 的列序号入库。

### 代码格式转换

```python
def to_akshare_symbol(code: str, market: str) -> str:
    return f"{market.lower()}{code}"       # sh600000 / sz000001 / bj430047


def to_baostock_symbol(code: str, market: str) -> str:
    if market.lower() not in {"sh", "sz"}:
        raise ValueError("BaoStock route only supports configured SH/SZ symbols")
    return f"{market.lower()}.{code}"      # sh.600000 / sz.000001
```

## 6. Agent 调试流程

### 6.1 最小探针

每个数据源上线前固定用少量高流动性标的测试：

```text
A股股票：sh600519 / sz000001
A股指数：sh000300 / sz399006
港股：00700
美股：AAPL
日期：最近 10 个已知交易日
```

探针必须验证：

1. 调用成功且返回行数大于 0；
2. 必要字段存在；
3. 日期单调递增且无重复；
4. `high >= max(open, close)`、`low <= min(open, close)`；
5. 价格、成交量、成交额非负；
6. 最新交易日没有异常缺失；
7. 与另一个源重叠日期的价格差在合理范围内；
8. 单位数量级合理，例如茅台成交量不应因“手/股”差异扩大 100 倍。

### 6.2 错误分类与动作

| 错误/现象 | 判断 | Agent 动作 |
|---|---|---|
| `ProxyError` | 当前 HTTP 代理不可达或目标拒绝代理出口 | 对该数据源切换直连规则；失败后降级到不同域名/不同供应商 |
| `RemoteDisconnected` | 上游或代理主动断开 | 最多短暂重试 1–2 次，然后切源 |
| `ConnectTimeout` / `ReadTimeout` | 路由或上游不稳定 | 指数退避重试，之后切源；不要无限重试 |
| HTTP 200 但 JSON 解析失败 | 可能返回验证码、拦截页或 HTML 错误页 | 记录 `Content-Type` 与响应前 200 字符的脱敏摘要，标记源失败 |
| DataFrame 为空 | 参数、代码、日期、停牌/退市或上游变更 | 先用固定探针复测；探针也空则判定数据源故障 |
| 列缺失/改名 | 上游或 AKShare 版本发生 schema drift | fail closed；禁止按位置猜字段 |
| BaoStock `login()` 失败 | TCP 10030 被拦、DNS/服务器异常 | 检查端口连通性；HTTP 代理切换通常无效 |
| BaoStock `error_code != "0"` | 业务或参数错误 | 记录 `error_code/error_msg`，不要继续遍历结果 |
| 两源价格明显不同 | 复权方式、币种、交易日或代码映射不一致 | 停止拼接，先核对 `adjustment` 和 symbol |

### 6.3 重试、缓存与熔断

建议默认值：

```text
连接超时：5–10 秒
读取超时：15–30 秒
同一接口重试：最多 2 次，指数退避 + jitter
单源连续失败阈值：3–5 次后熔断 5–15 分钟
新浪批量并发：1–3
日线缓存：按 source + symbol + adjustment + trade_date 唯一
交易日历/证券主表/行业映射：每日或每周更新，不随页面请求实时抓取
```

## 7. 参考资料

- [AKShare 股票数据官方文档](https://akshare.akfamily.xyz/data/stock/stock.html)
- [AKShare 指数数据官方文档](https://akshare.akfamily.xyz/data/index/index.html)
- [AKShare 快速入门与接口目录](https://akshare.akfamily.xyz/tutorial.html)
- [AKShare 更新日志](https://akshare.akfamily.xyz/changelog.html)
- [BaoStock 官方网站与 API 示例](https://www.baostock.com/)
- [BaoStock 官方知识库](https://www.baostock.com/helpDocsHome)

---

### 给 Agent 的一句话规则

> 先按数据语义选接口，再按供应商切源；永远记录来源、复权和单位；字段不确定就停止入库，资金流缺失就明确缺失，绝不拿价格收益率冒充。
