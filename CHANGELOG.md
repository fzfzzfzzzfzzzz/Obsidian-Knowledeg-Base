# Changelog

> 本文件记录用户可见的变化,面向读者。详细的开发过程文档(PRD / checklist / changelog)
> 在 [`docs/vX.Y.Z/`](./docs/) 各版本文件夹下,版本演进索引见 [`docs/ROADMAP.md`](./docs/ROADMAP.md)。
>
> 当前版本见 [`VERSION`](./VERSION)。格式参考 [Keep a Changelog](https://keepachangelog.com/)。

---

## [0.4.23] —— 2026-08-01

### 新增
- **Plan 域(替代 Todo)**:计划项改为独立文件 `04_Plans/plan_*.md`,frontmatter 含可选 `deadline`,
  与 Task 同模式;不再按 weekly / monthly / someday 分桶。详情见 [`docs/v0.4.23/changelog.md`](./docs/v0.4.23/changelog.md)。
- **Task `next_action` 字段**:任务新增「下一步行动」属性,CRUD 与 Web API 同步支持。
- **Market 重构**:拆出独立行情模块 `kb_quote.py`;新增个股详情页(`/market/stock/{ticker}`)、
  自选股看板、判断(judgments)视图,支持拖拽排序(vendored `sortable.min.js`)。
- **侧栏可折叠**:左侧导航支持折叠/展开,状态持久化到 localStorage,刷新不闪。

### 变更
- **Market 去除 alert 子类型**:`kind` 收敛为仅 `watchlist`;原 alert 相关字段
  (`date` / `trigger` / `direction` / `magnitude`)移除,异动需求改由事件系统承载。
- `accept-todos` 命令更名为 `accept-plans`;`extract-suggestions` 现抽取 idea / plan 候选。
- 根文档(AGENTS / PRODUCT / README / VAULT_STRUCTURE)同步 todo→plan 术语。

### 修复
- 版本号管理:引入根 `VERSION` 文件作为单一数据源,清除 README / PRODUCT / AGENTS / ROADMAP
  四处打架的硬编码版本号。

### 测试
- 427 passed。

---

## [0.4.22] —— 2026-07-28

### 变更
- **任务状态元数据统一**:任务状态(active / done / blocked / archived)的徽章配色、标签、
  图标统一到 `cat-meta.js` 的 `KB_TASK_STATUS` 表 + `taskStatusColor/Label/Icon/Options` 辅助函数。
  原散落在 tasks / task_detail / task_edit / workspace / market / app.js 的 6 份本地副本全部删除,
  改读单一数据源(加新任务状态只改一处)。

---

## [0.4.16 ~ 0.4.20] —— 2026-07-24 ~ 2026-07-26

> 代码注释里这些版本号散落,主题统一(图标系统 + 元数据统一 + 规范),合并归档。
> 完整叙述见 [`docs/v0.4.16/changelog.md`](./docs/v0.4.16/changelog.md)。

### 新增
- **全站 Lucide 图标本地化**:全站 emoji 换成本地自托管的 Lucide 线条图标
  (`scripts/web/static/lucide.min.js`,版本钉死 v0.460.0),离线可渲染。
- **类别元数据单一数据源**:`cat-meta.js` 成为事件 / 任务类别的唯一数据源
  (`KB_CATEGORIES` / `KB_TASK_CATEGORIES`),各页面只读取、不重定义。
- **AGENTS.md 规范重写**:沉淀 Module Ownership(防止 kb.py 膨胀)、前端 / 图标规范、
  UI Debugging Order 等工程规则。
- **深色模式对比度修复**:暗色主题下大量「浅底白字」组件达到 WCAG AA 对比度。

---

## [0.4.8 ~ 0.4.13] —— 2026-07-21 前后

### 新增
- **v0.4.13**:Idea / Todo 卡片与抽取简化(只留标题);Web 新建 idea;`completed_at` 生命周期。
- **v0.4.10**:任务(Tasks)管理系统 —— checklist / deadline / blocker / 项目 / 置顶 / 客户端排序。
- **v0.4.9**:首页拆分(工作台 / 知识库)+ 桌面启动图标 + 导航精简。
- **v0.4.8**:事件(Events)管理 + 日历事件链接。

---

## [0.4.3 ~ 0.4.7] —— 2026-07-18 ~ 2026-07-20

### 新增
- **v0.4.7**:shutdown host 白名单;`extract-suggestions` 的 `estimated_time` 与可观测性修复。
- **v0.4.6**:安全加固第二轮(XSS / SSRF / Auth / 时区 / 测试网),+65 测试。
- **v0.4.5**:审查修复第二轮 P0 + P2(10 个高危问题),+52 测试。
- **v0.4.4**:`kb_web.py` 从 2117 行拆为 74 行装配文件 + `web/` 包(9 router + 4 service)。
- **v0.4.3**:`rebuild-index` 命令;Web accept 自动搬运;6 路径常量环境变量覆盖。

---

## [0.4.0 ~ 0.4.2] —— 2026-07-16 前后

### 新增
- **v0.4.2**:日历「时间轴」视图(垂直 + 水平);`category` 字段(6 预设 + 自定义);标签筛选条。
- **v0.4.1**:批量投稿(URL 提取);/ideas /todos 拆「待定 / 已确定」tab;已确认 todo 放入日历。
- **v0.4.0**:文章详情页「生成 Idea / Todo 列表」按钮 + 引导弹窗。

---

## [0.3 ~ 0.3.1] —— 2026-07-12 前后

### 新增
- **v0.3.1**:日历事件表单增量改进。
- **v0.3**:日历功能 —— 从内容识别重要日期加入日历;`category` 字段初版。

---

## [0.1 ~ 0.2] —— 2026-07-10 前后

MVP 阶段。采集 → 总结 → idea/todo 建议 → 用户确认 → 正式清单的完整闭环;
阅读管理(收藏 / 稍后 / 阅读状态);搜索与标签。
