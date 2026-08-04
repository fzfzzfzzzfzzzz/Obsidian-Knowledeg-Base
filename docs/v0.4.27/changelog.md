# Changelog v0.4.27

> 日期:2026-08-04
> 主题:**文档同步 —— 修复审计报告发现的文档/代码不一致**
> 用户可见变化见根 [`../../CHANGELOG.md`](../../CHANGELOG.md#-0427--2026-08-04);本文件记录开发细节。

---

## 背景

v0.4.23 之后做了一次完整的文档/代码一致性审计(见 `docs/文档更新.md`),发现多个文档与代码实际实现不符。
本次统一修复这些过期描述。

---

## 变更

### 1. PRODUCT.md §六 "已知限制" 三项修正

**问题**
- #2 "无 rebuild-index":v0.4.3 起已实现,文档仍标为限制
- #3 "无多收藏夹":collections 已完整实现(CRUD + 21 测试),文档仍标为限制
- #10 测试数:文档写 "74 个核心测试",实际 460 passed

**修复**
- 删除 #2 和 #3,剩余条目重新编号(11 → 9 条)。
- #10 改为 "460 个测试(覆盖 ingest/解析/日历/批量/collections/rebuild-index/事件/任务/行情等)"。

### 2. PRODUCT.md §四 / §五 补漏

**问题**
- §四 文件组织缺少 06_Events / 07_Tasks / 08_Market 三个数据目录。
- §五 CLI 命令表只列 8 个,缺 `serve` / `rebuild-index` / `clean-x`。

**修复**
- §四 文件组织补 3 个目录。
- §五 命令表补 3 个命令。

### 3. README.md 命令一览补 4 个命令

**问题**
README §"命令一览" 只列 8 个命令,缺 `extract-suggestions` / `serve` / `rebuild-index` / `clean-x`。

**修复**
补 4 个命令到表格。

### 4. VAULT_STRUCTURE.md 补目录和 state.json 字段

**问题**
- 目录树只列到 05_Projects/,缺 06_Events / 07_Tasks / 08_Market。
- state.json schema 示例缺少 `tags` / `collection_ids` / `detected_dates` 字段,也无顶层 `collections` 对象。
- 模板表漏了 `idea_suggestion_template.md`。
- 模板数量说明不清晰(磁盘 11 个 vs 当前 9 个 + 历史残留 2 个)。

**修复**
- 目录树补 3 个目录,并附一句话说明。
- state.json schema 补 3 个字段 + collections 顶层对象。
- 模板表补 1 行。
- 模板说明改为"9 个当前 + 2 个历史残留 = 磁盘 11 个"。

### 5. AGENTS.md Data Ownership + Module Ownership 补 market 子域

**问题**
- Data Ownership 仍写"全项目无 SQLite",但 v0.4.24 引入了 `kb_market_cache.py`(SQLite 派生缓存)。
- Module Ownership 缺少 market 行情接入子域的归属说明。

**修复**
- Data Ownership 加"派生行情缓存"条目,把 SQLite 的定位说清楚(只用于派生缓存,不存内容类数据)。
- Module Ownership 加 "market 行情接入子域" 条目。

### 6. docs/v0.4.23/changelog.md 路由名修正

**问题**
v0.4.23 changelog 写个股详情路由为 `/market/stock/{ticker}`,实际是 `/market/{market_id}`。

**修复**
更正为 `/market/{market_id}`。

### 7. docs/ROADMAP.md P2 标记 + 版本行

**修复**
- P2-#10 "多收藏夹" 标为 ✅ 已完成。
- P2-#13 "自动产出补全模板章节" 标为 ❌ 主动放弃(v0.4.13 决策)。
- 当前版本 summary 更新为 460 passed。

---

## 文件改动

| 类别 | 文件 |
|------|------|
| 文档 | `PRODUCT.md`(已知限制修正 + 目录/命令补漏 + 测试数更新) |
| 文档 | `README.md`(命令表补 4 个命令) |
| 文档 | `VAULT_STRUCTURE.md`(目录树 + state.json schema + 模板表) |
| 文档 | `AGENTS.md`(Data Ownership + Module Ownership 补 market 子域) |
| 文档 | `docs/ROADMAP.md`(P2-#10/#13 标记 + 版本行 + 测试数) |
| 文档 | `docs/v0.4.23/changelog.md`(路由名修正) |
| 新增 | `docs/文档更新.md`(v0.4.23 一致性审计报告) |
| 新增 | `docs/v0.4.27/changelog.md`(本文件) |

---

## 不在本次范围

- PRODUCT.md §七 "评审请关注" 段引用 v0.4.0 / v0.4.1 的 PRD,未更新到其他版本(留给后续按需维护)。
- 90_Templates 模板内容本身的同步(模板文档化)未做。
- prompt_library.md 补全其余 LLM 调用的 prompt 全文镜像(ROADMAP P2-#14 剩余小项)未做。

---

## 测试

460 passed(无新增,本版本纯文档)。
