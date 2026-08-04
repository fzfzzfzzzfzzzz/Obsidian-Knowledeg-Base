# Changelog v0.4.25

> 日期:2026-08-04
> 主题:**收藏夹拖拽归入 + 批量操作**
> 用户可见变化见根 [`../../CHANGELOG.md`](../../CHANGELOG.md#-0425--2026-08-04);本文件记录开发细节。

---

## 新增

### 1. 收藏夹拖拽归入

**背景**
收藏页原只能通过文章详情页「加入文件夹」操作,需要多次点击;
对于高频整理的用户,「拖拽卡片到文件夹」是更直觉的交互。

**实现**
- 原生 HTML5 Drag-and-Drop(不用 Sortable.js):
  - Sortable 适合「列表内排序 / 跨列表迁移 DOM」场景;
  - 收藏夹是「拖到窄文件夹条上触发一个动作」,原生 `dragover`+`drop` 命中更准、代码更直接。
- 源(右侧卡片):通过 `dragstart` 事件委托,记录被拖卡片的 `source_id`(`_dragSid`)。
- 目标(左侧文件夹):每个真实文件夹加 `col-drop` class,「全部收藏」虚拟视图不带此 class,自动排除。
- `dragover` 时加 `col-drop-hover` 高亮,`drop` 时调 `POST /api/collections/{col_id}/articles`。

### 2. 批量操作栏

**背景**
拖拽适合单篇;多篇归入同一文件夹时,批量选择更高效。

**实现**
- 勾选文章后显示 `#batch-bar`:「已选 N 篇 + 加入文件夹 + 取消选择」。
- `batchAddToCollection()`:
  1. 从 `selectedIds` 取所选 source_ids;
  2. 拉 `/api/collections` 获取文件夹列表;
  3. `_pickOneCollection()` 弹窗用 radio 单选目标夹(与详情页的多选弹窗不同,批量是「追加到某一个夹」);
  4. 调 `POST /api/collections/{col_id}/articles`。
- 弹窗明确提示「文章会追加到所选文件夹,不会从其他文件夹移出」,消除用户对「多归属」的疑虑。

### 3. 收藏夹子导航

**背景**
知识库几个主要页面(仪表盘 / 全部文章 / 最近阅读 / 收藏夹 / 投稿)之间缺少统一快速跳转入口。

**实现**
- 收藏页加 `kb-subnav`,与其他知识库子页(投稿页、最近阅读页)保持一致的导航样式。

### 4. `POST /api/collections/{col_id}/articles`

**背景**
拖拽和批量操作都需要「把文章追加到某个文件夹」的能力。

**实现**
- 入参 `CollectionArticlesRequest { source_ids: [...] }`。
- 双向同步(见 AGENTS.md 双写约束):
  - 正向:`cols[col_id].source_ids` 追加 source_id;
  - 反向:`sources[sid].collection_ids` 回指 col_id。
- 幂等:已存在的条目不重复追加。
- 错误处理:`col_id === 'all'` 返回 400(虚拟视图,不能作目标);`col_id` 不存在返回 404;state.json 损坏返回 503。

---

## 修复

### 1. 活跃文件夹高亮失效

**背景**
`favorites.html` 原代码用 `li.dataset.col` 判断是否激活,但 HTML 属性是 `data-col-id`,
对应 `dataset.colId`(kebab-case 转 camelCase)。`dataset.col` 永远 `undefined`,导致 active 高亮失效。

**修复**
`li.dataset.col` → `li.dataset.colId`。

### 2. 批量按钮文案不一致

**背景**
知识库页的「取消选择」按钮与收藏夹页新增的「取消选择」语义相同,但视觉上「退出选择」更符合「退出批量模式」的语感。

**修复**
知识库页 `clearSelection()` 文案改为「退出选择」。

---

## 文件改动

| 类别 | 文件 |
|------|------|
| 路由 | `scripts/web/routers/collections.py`(新增 `POST /api/collections/{col_id}/articles`) |
| 模板 | `scripts/web/templates/favorites.html`(拖拽 + 批量栏 + 子导航 + 高亮 bug 修复) |
| 模板 | `scripts/web/templates/base.html`(style.css `v=92→105`、app.js `v=51→52` 缓存号) |
| 模板 | `scripts/web/templates/knowledge_base.html`(「取消选择」→「退出选择」) |

---

## 不在本次范围

- 拖拽仅支持「单篇 → 单个夹」;多选拖拽未做(批量栏已覆盖该场景)。
- 拖拽动画(卡片跟随鼠标、放入时的过渡效果)未做,当前用浏览器默认。
- 文件夹侧栏本身不支持拖拽重排序(需 Sortable.js 介入,留作后续)。

---

## 测试

457 passed(无新增,本版本为纯前端 + 新增 API 端点,API 逻辑在 collections.py 中已覆盖现有 state.json 读写路径)。
