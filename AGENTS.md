# AGENTS.md

## Project Goal

构建一个本地优先、兼容 Obsidian Markdown 的个人工作台。

系统统一管理知识库、阅读内容、笔记、Idea、任务、事件、截止日期和项目上下文。

## Hard Rules

- Markdown 文件是主要数据层。
- 不要静默覆盖用户手写的笔记。
- AI 生成的 idea 和 todo 必须先进入建议文件(suggestion files)。
- 只有用户接受的建议,才能移入正式 idea 列表或周/月度 todo 文件。
- MVP 不得依赖外部 LLM API。
- MVP 必须支持在 Inbox 手动粘贴文本。
- **离线优先:所有前端资源(JS 库、字体、图标)必须自托管在 `scripts/web/static/` 下。** 绝不依赖外部 CDN —— 工作台必须在离线状态下也能完整渲染。Lucide 图标库已 vendored 在 `scripts/web/static/lucide.min.js`;引用时写成 `/static/lucide.min.js?v=N`(每次内容变更都要 bump `v=` 以刷新浏览器缓存)。

## Data Ownership

各类数据有且只有一个"唯一数据源(Single Source of Truth)",不得在多处各存一份。

### 原则
- 同一个可编辑字段,不得同时保存在 Markdown、JSON 和 localStorage 中。
- 临时筛选条件、页面展开状态、滚动位置、显示偏好等**纯 UI 状态**可存 localStorage / sessionStorage。
- 新增数据类型前,必须先确定它的数据源和读写入口,再写代码。

### 现状(单数据源,改动前先核对此表)
- **知识内容**(文章 / 源笔记 / summary / idea / todo 建议 / 已接受的 idea 和计划):Markdown。
  - `01_Sources/`、`02_Summaries/`、`03_Ideas/`、`04_Plans/`
- **任务**:`07_Tasks/task_*.md` 的 YAML frontmatter(含 checklist、deadline、pinned、category、status),正文是自由描述。读写入口 `kb.write_task_file` / `kb.load_task_file`。
- **事件**:`06_Events/event_*.md` 的 frontmatter。读写入口 `kb.write_event_file` / `kb.load_event_file`。
- **日历事项**:`.kb/calendar.json`(独立 JSON 存储,不是从任务/事件派生)。任务和事件可**单向推送**到它。
- **收藏 / 稍后阅读 / 阅读状态 / 集合 / 文章标签**:`.kb/state.json`(索引 + 行为数据)。
- **工作台"当前任务"指针**:`.kb/workspace_state.json`(只存 task_id,不复制任务内容)。
- **主题偏好(light/dark)**:浏览器 localStorage `kb-theme`(纯客户端)。

> 全项目**无 SQLite**。设计原则:内容类数据不得仅存于 SQLite / 数据库。

### 已知双写风险(改这些字段时务必两处一起改)
- **文章标签**:同时写在 `state.json` 和 summary 的 frontmatter 里;`rebuild-index` 时**以 summary frontmatter 为准**重建 state.json(此过程中收藏/阅读次数等 state-only 字段会丢失,属已知行为)。
- **summary 元数据**:`summary_path`、`tags` 同时存在于 summary frontmatter 和 `state.json`。
- **日历 ↔ 任务/事件**:日历事项里可反向引用 `task_id` / `event_id`,任务/事件 frontmatter 里存 `synced_calendar_ids`;删除不级联,孤儿由 `cleanup_dead_calendar_items` 清理。
- **集合成员关系**:在 `state.json` 里双向存储(`collections[].source_ids` 和 `sources[].collection_ids`),两处必须一起更新。

## Module Ownership(模块归属,防止 kb.py 再次膨胀)

> v0.4.22 起执行。历史教训:kb.py 曾因 event/market/task 三个业务域的"七件套"全堆进来,涨到 3500+ 行。本节规定代码归属,确保新功能不再默认落到 kb.py。

### kb.py 只放这些(门面层 + 基础设施)

- **CLI 入口**:`cmd_*` / `build_parser` / `main`。
- **全局配置常量**:`VAULT_ROOT` / `KB_DIR` / `STATE_FILE` / `EVENT_DIR_NAME` / `TASK_DIR_NAME` / `MARKET_DIR_NAME` 等(集中定义,不散落)。
- **基础设施**:`write_text` / `read_text` / 文件锁 / 时区(`now_ts`/`today_iso`)/ `parsefrontmatter` / `content_hash` / `load_state`·`save_state`·`load_calendar`·`save_calendar`(JSON store 读写门面)/ ingest 解析 / make-prompts 流水线。

### 每个业务域必须有独立模块

- **task / event / market**:实现都在 `kb_entities.py`(共享 find/scan/损坏备份骨架,保留各实体字段差异)。kb.py 只 re-export 供旧调用方(`kb._find_task_file` / `kb.load_task_file` 等)。
- **未来新增的实体/业务域**(如 contacts、habits…):**先建对应模块**(`kb_<domain>.py` 或并入 `kb_entities.py`),实现写在新模块里,kb.py 只 re-export。**绝不直接往 kb.py 加业务逻辑。**

### 新增功能前的自检

写代码前先问自己:
1. 这是哪个业务域?对应模块存在吗?
2. 如果不存在,**先建模块,再写功能**。不要因为"顺手"就把函数塞进 kb.py。
3. 如果是跨域的基础设施(锁、IO、解析),才允许进 kb.py。

### 软性约束

`wc -l scripts/kb.py` 超过 ~1800 行就该警惕(v0.4.22 重构后约 1500 行)。超了先看是不是又有业务域该拆出去。

### kb_entities.py 的特殊约束

- **绝不 import-time 拷贝 kb 的路径常量**(`from kb import VAULT_ROOT` 会拿到 import-time 副本,导致 `conftest.isolate_vault` 的 `monkeypatch.setattr(kb, "VAULT_ROOT")` 失效,测试污染真实 vault)。一律用模块内的 `_kb()` helper 运行时取 kb 模块对象。
- 当 kb.py 作为 `__main__` 直接运行时,顶部 `import kb` 会触发循环重执行;`_kb()` 用 `sys.modules.get("kb") or sys.modules.get("__main__")` 同时覆盖两种场景。
- `scan_*` 的 loader 参数走 `kb.load_*_file`(而非本模块直接引用),保证测试 `monkeypatch.setattr(kb, "load_task_file", ...)` 注入故障时能生效。

## Git Rules

- 未经用户明确要求,不得执行 `git commit`、`git push`、创建分支或修改远程仓库。
- 可以用 `git status` 和 `git diff` 检查修改。
- 如果用户只要求修改代码,默认不创建 commit。

## Frontend Modification Boundaries

- 用户要求局部修改时,只修改指定模块。
- 不得因为修改一个模块而重新设计整个页面。
- 用户提供目标截图时,该截图是视觉母版。
- 当前实现截图仅用于说明问题时,不得作为新设计依据。
- 未经明确要求,不得修改导航结构、页面模块顺序或整体布局。
- 应优先复用现有组件、样式变量和布局结构。

## 前端 / 图标规范(源自 v0.4.16 事故的教训)

本项目所有图标都用 **Lucide**(本地 vendored)。为避免重演 v0.4.16 那场数小时的调试拉锯,遵守以下规则:

### 图标用法
- 图标渲染为 `<i data-lucide="icon-name"></i>`。
- **不要**建立 Lucide kebab-case → PascalCase 的转换映射,Lucide 的 `createIcons()` 已自动处理该转换(`data-lucide="alarm-clock"` 会自动匹配 `icons.AlarmClock`)。
- **允许并要求**建立业务级元数据映射,例如 `category → { label, icon, color }`(任务类别、文章类别、事件类别等)。这类映射是必需的,不是被禁止的"映射层"。
- 业务级类别映射必须**集中维护**,不得由各页面分别定义。本项目的类别元数据统一在 `scripts/web/static/cat-meta.js`(`KB_CATEGORIES` / `catColor()` / `catIcon()` / `catPresets()`),加新类别只改这一处。
- 图标尺寸/对齐由 `style.css` 里的 `svg.lucide` 规则统一处理。不要在各组件里散落临时 `width/height` 覆盖。

### 图标刷新规则(主次分明,避免重复执行)
图标刷新有两条机制,**明确主次**:

- **主机制 —— 显式调用。** 已知的动态渲染流程,在插入含 `<i data-lucide>` 的 HTML 之后,**主动**调用 `window.refreshIcons()`。这是主要手段,不要省略。
- **兜底机制 —— `MutationObserver`。** `base.html` 里有一个全局 `MutationObserver` 监听 DOM 变化,在下一帧(`requestAnimationFrame` 防抖)重新执行 `refreshIcons()`。它**只用于兜底**第三方/不可控的 DOM 改动,**不得替代**显式调用。
- **不要依赖 `MutationObserver` 替代明确的渲染调用。** 它是安全网,不是首选路径。
- **关于"容器范围"**:理想做法是只处理新插入的容器、不扫整个 document,但我们 vendored 的 `lucide@0.460` 的 `createIcons()` 内部总是全局 `querySelectorAll('[data-lucide]')`,且内部 `replaceElement` 未导出,**无法真正按容器范围渲染**。Lucide 的替换是幂等的(已转的图标会失去 `data-lucide`,下次扫描自动跳过),所以全局扫描的实际开销很小。基于此,`refreshIcons()` 当前走全局调用即可,**不要**为了"容器范围"去 fork Lucide 或 hack 内部 API。

### Vendoring JS 库
- 下载任何 vendored JS 后,**提交前先验证内容**:检查文件大小是否接近完整 bundle,并 grep 几个你会用到的具体符号名。v0.4.16 的 bug 就是一个被截断/残缺的 bundle,静默缺失了大部分图标。
- 在下载 URL 里钉死具体版本(`@0.460.0`,不要 `@latest`),保证 vendored 文件可复现。

## UI Debugging Order

UI 不显示 / 显示异常时,按以下顺序排查(不强制先索取 F12):

1. **先检查代码。** 很多问题能直接从渲染函数、模板字符串、资源路径(`/static/xxx?v=N`)、CSS 选择器里看出来。明显的拼写错误、路径错误、变量未定义这类,**先看代码就能定位**,不必先找用户。
2. **能本地复现就本地复现。** 用真实浏览器复现问题(浏览器证据比 node 模拟可靠 —— Node ≠ 浏览器,静态分析 / node 跑 JS 不能反映真实渲染)。
3. **检查 Console / Network / Elements。** 复现后看 DevTools:Console 报错、Network 资源 404、Elements 里元素是否在 DOM / 样式是否被覆盖。
4. **无法本地复现时,再向用户索取 F12 Console 输出。** 把浏览器/系统的差异交给用户去抓。
5. **必要时加临时调试标记。** 加一行 `console.log` 或临时 `outline: 1px solid red` 来区分「不在 DOM 里」(什么都没有) vs. 「在 DOM 里但看不见」(红框出现)—— 两种失败模式的修法完全不同(注册/时序 vs. CSS/颜色/尺寸)。
6. **任务完成前必须删除全部临时调试代码和视觉标记。** `console.log`、临时 `outline`、调试用的 HTML 都得清掉,不能留在提交里。

## Shared Category Metadata

类别元数据(任务 / 事件 / 日历等)必须在单一文件集中维护,各页面只读取、不重新定义。

- **事件 / 日历类别**的单一数据源:`scripts/web/static/cat-meta.js` 的 `KB_CATEGORIES`。
- **任务类别**的单一数据源:同文件的 `KB_TASK_CATEGORIES`。
- 每个类别含 `key`(类别名)/ `label` / `icon`(Lucide 名)/ `color`。
- 访问统一走辅助函数:`catColor()` / `catIcon()`(事件)、`taskCatColor()` / `taskCatIcon()`(任务)。**禁止**直接把 iconName 作为普通文字插进页面。
- calendar / events / workspace / tasks / task_detail / task_edit 等模块**必须读取同一份配置**,**禁止**在页面文件里重新定义类别或图标映射。
- 加新类别只改 cat-meta.js 一处。

## Commands

MVP(本地无 LLM 也能跑):
- 初始化 vault 结构:`python scripts/kb.py init`
- 解析 inbox:`python scripts/kb.py ingest`
- 生成手工 LLM 提示词:`python scripts/kb.py make-prompts`
- 移动已接受的 idea:`python scripts/kb.py accept-ideas`
- 移动已接受的 todo:`python scripts/kb.py accept-todos`
- 查看状态:`python scripts/kb.py status`

Additional commands(require LLM / web deps, gracefully degrade when absent):
- 测试 LLM 连通性:`python scripts/kb.py llm-test`
- 通过 LLM 自动生成 summary:`python scripts/kb.py make-prompts --auto`
- 从已有 summary 回填 `summary_path`:`python scripts/kb.py make-prompts --reconcile`
- 从 summary 抽取 idea/todo 建议:`python scripts/kb.py extract-suggestions`
- 清洗 X (Twitter) 来源正文噪音:`python scripts/kb.py clean-x`
- 启动 FastAPI 阅读前端:`python scripts/kb.py serve`

## Completion Criteria

任务完成必须满足:

1. 保留现有用户内容。
2. 不新增重复的数据源(见 Data Ownership)。
3. 状态字段和派生数据保持一致。
4. 用户可见行为变化需要提供简短说明。
5. 使用与本次任务相关的示例或 smoke test 进行测试。
6. 删除临时日志、测试标记和调试样式。
7. 报告修改文件、测试方式和未完成事项。

### 分类型测试要求

- **Inbox 或解析器修改**:使用至少一个 Inbox 示例测试。
- **前端修改**:在浏览器中测试相关页面。
- **图标修改**:测试首次加载、动态渲染和刷新页面。
- **共享元数据修改**:确认所有消费模块都使用统一数据源。
- **任务修改**:测试创建、读取、编辑、Checklist 和截止日期。

## Current Module Status

> 更新时间:2026-07-26 · 当前版本 **v0.4.18+**
> 各模块状态供 agent 快速定位已实现的功能范围。Phase 0–5 是早期 MVP 阶段(已全部完成),后续按模块演进。

### 早期 MVP 阶段(Phase 0–5,全部 done)
- Phase 0(init):**done**
- Phase 1(ingest parser):**done**(自由文本 + KB_ITEM 双格式,可选 LLM)
- Phase 2(make-prompts):**done**(手工 / `--auto` / `--reconcile` 模式)
- Phase 3(手工产出导入):**done**(LLM 自动写入 + 手工粘贴两条路径)
- Phase 4(accept-ideas / accept-todos):**done**
- Phase 5(status dashboard):**done**(CLI `status` + FastAPI web UI)

### 后续模块(Phase 5 之后)
- **Task system(任务系统)**:**done** —— `07_Tasks/task_*.md`,frontmatter 含 checklist / deadline / pinned / category / status;支持置顶、客户端排序、checklist 稳定 id;Web CRUD + `/api/tasks/{id}/pin`。
- **Event system(事件系统)**:**done** —— `06_Events/event_*.md`,单日期事件,可单向同步到日历。
- **Calendar items(日历事项)**:**done** —— `.kb/calendar.json` 独立存储,任务/事件可推送;`cleanup_dead_calendar_items` 清理孤儿。
- **Collections / favorites / read later(集合 / 收藏 / 稍后阅读)**:**done** —— 统一在 `.kb/state.json`,集合成员关系双向存储。
- **Workbench homepage(工作台首页)**:**done** —— 三栏布局(主内容 + 推荐阅读栏),当前任务卡片、即将到来事项。
- **Timeline(时间线)**:**done** —— 工作台首页底部「即将到来的事项」横向时间轴,深色模式下轴线/圆点已提亮。
- **Shared category metadata refactor(类别元数据统一)**:**done** —— `cat-meta.js` 为事件/任务类别的单一数据源;各页面只读取、不重定义(见 Shared Category Metadata)。
