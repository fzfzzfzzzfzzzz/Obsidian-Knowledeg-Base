# Changelog v0.4.24

> 日期:2026-08-04
> 主题:**行情数据引擎重构(BaoStock + SQLite 缓存)+ 行业/个人概览子页**
> 用户可见变化见根 [`../../CHANGELOG.md`](../../CHANGELOG.md#-0424--2026-08-04);本文件记录开发细节。

---

## 新增

### 1. 行情数据引擎重构

**背景**
v0.4.23 拆出 `kb_quote.py` 后,数据源仅有 AKShare 一条路径,A 股稳定性受限于单一供应方;
且个股详情缓存用 JSON 文件(`stock_details_90d.json`),维护成本高。

**实现**
- **BaoStock 接入**:A 股 K 线优先走 BaoStock(稳定、无 token 限制),形成 `BaoStock → AKShare → SQLite` 三层降级链;网络不可达时仍可返回 SQLite 缓存数据。
- **数据标准化**:`_normalize_baostock_row` / `_normalize_akshare_row` 统一字段映射(成交量单位统一为"股"、复权标识统一为 qfq),保证多源数据可互换。
- **新增 `kb_market_cache.py`**:独立 SQLite 缓存层(`.kb/cache/market/market_cache.sqlite`),4 张表:
  - `daily_kline`:日 K 线(OHLCV + 20+ 字段)
  - `quote_snapshot`:最新行情快照
  - `detail_blocks`:个股详情分块 JSON(财务/资金流/基本面)
  - `fetch_status`:按数据源记录抓取状态,用于降级决策
- **大盘趋势**:`get_market_trends` / `get_cached_market_trends` 支持 A 股 / 美股 / 港股指数走势。
- **市场宽度**:`get_market_breadth` / `get_cached_market_breadth` 统计涨跌家数、20 日新高/新低、涨停/跌停计数。
- **行业趋势**:`get_industry_trends` / `get_cached_industry_trends` 支持申万 + 同花顺双源,含行业强度排名、资金流向、候选股列表。
- **实时报价**:`_apply_akshare_realtime_quote` 叠加实时行情,配合 SQLite 快照缓存,无网络时回退到缓存值。

### 2. 行业概览页

**背景**
市场页原把所有内容挤在一处;行业强度、资金流向等宏观视图无处安放。

**实现**
- 新增 `/market/industry` 路由 + `industry_overview.html` 模板。
- 展示行业强度排名(颜色映射涨跌幅)、资金流向气泡图、行业候选股。
- 子导航从 market.html 主页拆出,市场页现含四 tab:市场概览 / 自选股 / 行业概览 / 个人概览。

### 3. 个人概览页

**背景**
用户需要看到自己的持仓概览、盈亏追踪,原先只有自选股列表,没有宏观视图。

**实现**
- 新增 `/market/personal` 路由 + `personal_overview.html` 模板。
- 展示持仓概览(成本 / 市值 / 盈亏)、持仓分布、与大盘对比。

### 4. 大盘走势 API

**实现**
- `GET /api/market/trends`:大盘指数走势(支持 CN/US/HK)。
- `GET /api/market/trends/industry`:行业走势(多 tab 切换、均线、成交量)。
- 刷新去重:`_claim_trend_refresh` / `_release_trend_refresh` 基于 `threading.Lock` 防止并发重复抓取。

### 5. `requirements-market.txt` + `AKShare_BaoStock_API_Guide.md`

- 新增 `requirements-market.txt`:把 akshare / baostock 从主依赖分离为可选依赖,未安装时主系统不受影响。
- 新增 `AKShare_BaoStock_API_Guide.md`:AKShare v1.18.81 + BaoStock v0.9.3 的接口选型参考表。

---

## 变更

### 1. Market 页面拆子页

**背景**
market.html 原同时包含自选股、个股详情、行业视图,模板膨胀到难以维护。

**实现**
- `market.html` 精简:行业概览 / 个人概览内容移到独立模板,主页只保留市场概览 + 自选股。
- 子导航统一为 `mk-subnav`,四 tab 链接到 `/market` / `/market/watchlist` / `/market/industry` / `/market/personal`。
- 新增 `market-trends.js`:客户端走势图表,支持时间周期切换(5/20/90/180 日)、均线开关(ma5/ma20)、图例显隐、自选股叠加对比。

### 2. 个股详情缓存迁 SQLite

- 移除旧 `stock_details_90d.json` 及对应函数(`_load_stock_detail_cache` / `_save_stock_detail_cache` 等)。
- 改走 `kb_market_cache` 的 `detail_blocks` 表,缓存周期从 90 天延长到 180 天。
- 个股详情响应新增持仓字段:`cost_price` / `shares` / `target_price` / `stop_price`。

### 3. 样式扩展

- 新增 `.mk-ind-page` 行业概览容器、`.mk-overview-grid` 两列响应式网格、`.mk-placeholder-card` 占位卡片、`.mk-trend-card` 走势图卡片。
- 完善 A 股指数显示:`.mk-index-chg-pct.up/down` 红涨绿跌配色。

---

## 文件改动

| 类别 | 文件 |
|------|------|
| 新增模块 | `scripts/kb_market_cache.py` |
| 新增模板 | `scripts/web/templates/industry_overview.html`, `scripts/web/templates/personal_overview.html` |
| 新增静态资源 | `scripts/web/static/market-trends.js` |
| 新增文档 | `AKShare_BaoStock_API_Guide.md`, `requirements-market.txt` |
| 核心模块 | `scripts/kb_quote.py`(BaoStock 接入 + 数据标准化 + 全量重构) |
| 路由 | `scripts/web/routers/market.py`(industry/personal 页 + trend API) |
| Models | `scripts/web/models.py`(+12 行,新增持仓字段) |
| 模板 | `scripts/web/templates/market.html`(精简)、`stock_detail.html`、`watchlist.html`、`market_judgments.html` |
| 静态资源 | `scripts/web/static/style.css`(市场页样式 +667 行)、`scripts/web/static/app.js`(+44 行) |
| 测试 | `scripts/tests/test_market_quote_cache.py`(+374 行)、`scripts/tests/test_market_personal.py`(+15 行) |
| 新增测试 | `scripts/tests/test_market_data_standardization.py` |

---

## 不在本次范围

- `kb_quote.py` 的单元测试覆盖率仍有提升空间,部分分支依赖网络,无法在离线环境跑。
- 行业概览页的图表交互(ECharts 集成)未在本次实施,当前用纯 HTML 占位 + CSS 可视化。
- 个人概览页的 P&L 历史追踪图表尚未实施,当前只展示快照数据。

---

## 测试

+30 测试(test_market_quote_cache +374 行 / test_market_data_standardization 新增 / test_market_personal +15 行)。
总计 **457 passed**。
