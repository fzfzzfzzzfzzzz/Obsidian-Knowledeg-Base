# Changelog v0.4.16

> 日期:2026-07-24 ~ 2026-07-26
> 主题:**全站 Lucide 图标 + 类别元数据单一数据源 + AGENTS.md 规范重写 + 深色对比度修复**

本版把全站 emoji 换成本地自托管的 Lucide 线条图标,把散落在 4 个页面的类别元数据
抽取为单一数据源 `cat-meta.js`,并把 v0.4.16 图标 bundle 截断事故的教训沉淀进
重写的 AGENTS.md。416 passed(无新增测试,纯前端 / 规范 / 样式)。

> 覆盖范围说明:本份以最标志性的 v0.4.16 事故命名,正文按 v0.4.16 / v0.4.17 / v0.4.18 /
> v0.4.19 / v0.4.20 分节叙述(代码注释里这些版本号散落)。主题统一(图标系统 + 元数据统一 +
> 规范),合并归档到本份。

---

## 新增

### 1. 全站 Lucide 图标本地化(v0.4.16,提交 `cb0e0e1`)

**背景**:v0.4.16 之前,全站图标用 emoji(📌 事件、✅ 任务、📊 概览等)。emoji 的问题:
- 跨平台渲染不一致(Windows / macOS / Linux 各画各的)
- 在深色玻璃背景上对比度差
- 没有线条图标的统一设计语言

**实现**:
- 引入 **Lucide** 图标库,本地 vendored:`scripts/web/static/lucide.min.js`(599034 B,约 585 KB)
- 版本钉死 **lucide v0.460.0**(下载 URL 用 `@0.460.0` 非 `@latest`,可复现)
- `base.html:22` 在 `<head>` 同步加载(CSS 之后、body 之前),保证首屏图标即时渲染
- 渲染机制:`<i data-lucide="icon-name"></i>` → `lucide.createIcons()` 把 `<i>` 替换成 svg
- `createIcons()` 内部用 `toPascalCase` 自动把 `data-lucide="alarm-clock"` 匹配到 `icons.AlarmClock`,
  **不需要**手写 kebab→Pascal 转换映射

**离线优先**:Lucide bundle 自托管在 `/static/`,**绝不依赖外部 CDN**,工作台在离线状态下
也能完整渲染(AGENTS.md Hard Rules 硬性要求)。

### 2. v0.4.16 图标 bundle 截断事故(教训沉淀)

**事故**:首次 vendoring Lucide 时,下载的 bundle 被截断 / 残缺,静默缺失了大部分图标。
表现:`alarm-clock` 等图标显示成文字「alarm-clock」而非图标,且**无任何报错**(bundle 能加载,
只是内容不全)。调试耗时数小时。

**根因**:下载后**没有验证文件内容**,直接提交了残缺 bundle。

**修复**(提交 `ece3ad7`):重新下载完整 bundle,验证文件大小接近预期(599KB)+ grep
会用到的符号名(`AlarmClock` / `TrendingUp` 等)。

**教训沉淀**(AGENTS.md「Vendoring JS 库」规则):
> 下载任何 vendored JS 后,**提交前先验证内容**:检查文件大小是否接近完整 bundle,
> 并 grep 几个你会用到的具体符号名。v0.4.16 的 bug 就是一个被截断/残缺的 bundle,
> 静默缺失了大部分图标。

### 3. refreshIcons 双机制(v0.4.16,`base.html:108-135`)

动态渲染的图标(列表 / 卡片)需要刷新机制。设计为**主次分明**两条机制:

**主机制 —— 显式调用**(`window.refreshIcons`,`base.html:111-118`):
封装 `lucide.createIcons()`,带 try/catch 兜底。已知的动态渲染流程,在插入含 `<i data-lucide>`
的 HTML 后**主动**调用。这是主要手段。

**兜底机制 —— MutationObserver**(`base.html:122-132`):
全局监听 `document.documentElement` 的 `{childList, subtree}`,用 `requestAnimationFrame`
单帧防抖(`scheduled` 标志),在下一帧调 `refreshIcons()`。**只用于兜底**第三方/不可控 DOM 改动,
**不得替代**显式调用。浏览器无 MutationObserver 时降级为直接调一次。

**容器范围说明**(AGENTS.md 明确记录):
lucide@0.460 的 `createIcons()` 内部总是全局 `querySelectorAll('[data-lucide]')`,
且 `replaceElement` 未导出,**无法真正按容器范围渲染**。但 Lucide 的替换是幂等的
(已转图标失去 `data-lucide`,下次扫描自动跳过),全局扫描开销很小。
**结论**:`refreshIcons()` 走全局调用即可,不为容器范围去 fork Lucide 或 hack 内部 API。

### 4. cat-meta.js 类别元数据单一数据源(v0.4.17,提交 `9d7d81f`)

**背景**:v0.4.16 之前,类别元数据(类别名 → 配色/图标)散落在 4 个页面各自定义,
导致「会议」类别在不同页面配色不一致(一处 `#3b82f6` 错值,一处 `#2563eb` 正确值)。
这正是 v0.4.16 事故排查时暴露的次生问题。

**实现**:`scripts/web/static/cat-meta.js`(140 行),全站类别元数据的**单一数据源**。

**两套类别独立维护**(注释 `cat-meta.js:82-87` 说明为何不合并):

事件 / 日历类别 `KB_CATEGORIES`(`:27-35`,顺序由 `KB_CAT_ORDER` 定义):

| key | icon | color |
|---|---|---|
| todolist | `list` | `#64748b` |
| 会议 | `users` | `#2563eb` |
| 财报 | `trending-up` | `#16a34a` |
| 截止日期 | `alarm-clock` | `#dc2626` |
| 发布 | `rocket` | `#8b5cf6` |
| 比赛 | `trophy` | `#0d9488` |
| 其他 | `pin` | `#d97706` |

任务类别 `KB_TASK_CATEGORIES`(`:88-95`):

| key | icon | color |
|---|---|---|
| 开发 | `code` | `#2563eb` |
| 科研 | `flask-conical` | `#16a34a` |
| 个人 | `user` | `#d97706` |
| 金融 | `dollar-sign` | `#ca8a04` |
| 工作 | `briefcase` | `#0891b2` |
| 其他 | `circle` | `#8b5cf6` |

> 注:两套的「其他」配色**故意不同**(事件橙 vs 任务紫),因为它们是不同业务域,视觉区分有益。

**辅助函数(防裸拼的核心)**:
- `catColor(cat)` / `taskCatColor(cat)`:取色;**未知/自定义类别用字符串 hash 取稳定色**,
  保证用户自定义类别配色不会每次刷新变
- `catIcon(cat)` / `taskCatIcon(cat)`:**关键防裸拼函数** —— 返回 `<i data-lucide="..."></i>`
  标签字符串,保证图标名永远包在 `data-lucide` 里(注释明确禁止裸拼 `'<span>'+iconName+'</span>'`,
  那样图标名会变成文字)
- `catPresets()` / `taskCatPresets()`:返回数组格式供 `<select>` 渲染

### 5. 消费方统一(v0.4.17 ~ v0.4.19)

7 个模板 + app.js 全部改读 cat-meta.js:
- `calendar.html` / `events.html`:事件类别,别名指向 `KB_CATEGORIES`
- `tasks.html` / `task_detail.html` / `task_edit.html`:任务类别,调 `taskCatColor/taskCatIcon`
- `workspace.html`:删除原 `CAT_COLOR`(`#3b82f6` 错值)/ `CAT_ICON` 重复定义,改用 `catColor/catIcon`
  (`workspace.html:179-180` 注释是 v0.4.16 事故的现场证据)
- `app.js:1054`:提交表单分类下拉调 `catPresets()`

**校验结果**:类别元数据层面**已无重复的硬编码对象字面量**。各页面的 `CAT_META` 等只是
别名赋值(指向 `KB_CATEGORIES`),数据仍来自 cat-meta.js。

### 6. AGENTS.md 规范重写(v0.4.16,提交 `fe637b2`)

把 v0.4.16 事故 + cat-meta 抽取的教训沉淀为硬规范:

- **Hard Rules / 离线优先**:所有前端资源必须自托管,绝不依赖 CDN;Lucide 引用必须
  `/static/lucide.min.js?v=N`,**每次内容变更都要 bump `v=`** 刷浏览器缓存
- **前端 / 图标规范(源自 v0.4.16 事故)**:图标用法(禁止建 kebab→Pascal 映射,允许建业务级
  元数据映射但必须集中维护)、图标刷新规则(主次机制,不依赖 MutationObserver 替代显式调用)、
  容器范围说明、Vendoring JS 库(下载后必须验证内容)
- **Shared Category Metadata**:类别元数据单一数据源 = cat-meta.js,各页面只读取不重定义,
  禁止把 iconName 作为文字插进页面,加新类别只改 cat-meta.js 一处
- **UI Debugging Order**:六步排查法(先看代码 → 本地复现 → Console/Network/Elements →
  无法复现再索 F12 → 加临时调试标记区分"不在 DOM" vs "在 DOM 但看不见" → 完成前删除全部调试代码)
- **Data Ownership**:单数据源原则 + 现状表(Markdown / 任务 frontmatter / 事件 frontmatter /
  state.json / workspace_state.json / calendar.json / localStorage)+ 已知双写风险清单

### 7. 深色模式对比度修复(v0.4.18,提交 `e12adcd`)

**问题**:Ardot 深紫黑玻璃调色板(`[data-theme="dark"]`)的表面透明度太低,
导致卡片 / badge / 表格单元格 / markdown body 在 `#030014` 近黑底上几乎隐形(看起来像黑底)。

**修复**(`style.css:2828-2831`):
- `--c-surface`:5% → 8%(`rgba(255,255,255,0.08)`)
- `--c-surface-2`:3.5% → 5.5%
- 文字提亮:`--c-text: #ececff` / `--c-text-muted: #9aa0c7`

微提亮保留玻璃质感,但元素重新可见。时间线轴线 / 圆点在深色模式下也一并提亮。

### 8. 图标按钮 pointer-events 修复(v0.4.20)

**问题**:点图标按钮(按钮内是 Lucide svg)有时没反应。

**根因**(`style.css:3636-3643` 注释):Lucide 在 mousedown→mouseup 之间把 `<i>` 替换成 `<svg>`,
浏览器判定 mousedown / mouseup 落在不同元素 → 不触发 click。

**修复**(`style.css:3644-3648`):按钮内 svg `pointer-events: none`,点击事件统一落在按钮本体。

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/web/static/lucide.min.js` | 新增,Lucide v0.460.0 本地 vendored(599KB,完整 bundle) |
| `scripts/web/static/cat-meta.js` | 新增,类别元数据单一数据源(140 行,`KB_CATEGORIES` + `KB_TASK_CATEGORIES` + 辅助函数) |
| `scripts/web/templates/base.html` | lucide.min.js 引用(`:22`)+ refreshIcons + MutationObserver(`:108-135`);style.css / app.js / cat-meta.js 版本号 bump |
| `scripts/web/static/style.css` | `svg.lucide` 统一样式(`:3628-3635`)+ 深色对比度(`:2828-2849`)+ 图标按钮 pointer-events(`:3644-3648`) |
| `scripts/web/static/app.js` | 卡片渲染改用 `catColor/catIcon/taskCatColor/taskCatIcon`;`:443` 显式 refreshIcons |
| `scripts/web/templates/calendar.html` / `events.html` / `tasks.html` / `task_detail.html` / `task_edit.html` / `workspace.html` | 改读 cat-meta.js,删除重复定义 |
| `AGENTS.md` | 重写(离线优先 / 图标规范 / Shared Category Metadata / UI Debugging Order / Data Ownership) |

---

## 不变

- 后端 API 不变(纯前端 / 样式 / 规范改动)
- 数据格式不变
- 既有类别值不变(只是配色来源统一,「会议」「开发」等 key 不变)

---

## 破坏性变更

**前端资源引用方式变化**(对用户透明):
- 全站 emoji 替换为 Lucide 图标(视觉变化,无功能影响)
- 静态资源必须配合 `?v=N` 缓存策略(开发者需在资源变更时 bump 版本号)

无数据层破坏性变更。

---

## 不在本次范围

- **任务状态元数据统一**:`TK_STATUS_META`(active/done/blocked/archived 的徽章配色)目前在
  `tasks.html:36-41` 与 `task_detail.html` 各自定义,与任务**类别**元数据(已统一)是不同维度,
  尚未统一。可记入 ROADMAP 后续项。
- **按容器范围渲染图标**:lucide@0.460 的 `createIcons()` 不支持,需 fork,不值得(全局扫描开销小)。
- **浏览器 favicon**:仍未引入(`base.html` 无 `<link rel="icon">`)。
