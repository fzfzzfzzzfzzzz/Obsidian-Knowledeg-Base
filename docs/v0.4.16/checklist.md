# v0.4.16 任务清单(验收记录)

> 日期:2026-07-24 ~ 2026-07-26
> PRD 见 `v0416_PRD.md`,changelog 见 `changelog.md`
> 涵盖 v0.4.16 ~ v0.4.20,全部已完成(事后补录)

## Lucide 图标本地化 — 完成

- [x] `lucide.min.js` v0.460.0 vendored(599KB 完整 bundle)
- [x] 下载 URL 钉死版本 `@0.460.0`(可复现)
- [x] `base.html:22` 同步加载(CSS 后、body 前)
- [x] 渲染机制 `<i data-lucide="...">` + `createIcons()`
- [x] 全站 emoji 替换为 Lucide 线条图标
- [x] 不建 kebab→Pascal 映射(createIcons 自动处理)

## v0.4.16 事故修复 — 完成

- [x] 重新下载完整 bundle(验证 599KB + grep 符号名 AlarmClock/TrendingUp 等)
- [x] 沉淀 AGENTS.md「Vendoring JS 库」规则(下载后必须验证内容)

## refreshIcons 双机制 — 完成

- [x] `window.refreshIcons`(`base.html:111-118`)封装 createIcons + try/catch
- [x] 主机制:显式调用(动态渲染后主动调)
- [x] 兜底机制:MutationObserver(`base.html:122-132`)+ rAF 防抖
- [x] 无 MutationObserver 时降级直接调用
- [x] 首屏 `window.refreshIcons()` 立即触发(`base.html:134`)
- [x] 容器范围说明写进 AGENTS.md(走全局,不 fork Lucide)

## cat-meta.js 单一数据源 — 完成

- [x] `KB_CATEGORIES`(事件 7 类:todolist/会议/财报/截止日期/发布/比赛/其他)
- [x] `KB_TASK_CATEGORIES`(任务 6 类:开发/科研/个人/金融/工作/其他)
- [x] 两套独立维护(「其他」配色故意不同)
- [x] `catColor/catIcon` + `taskCatColor/taskCatIcon` 辅助函数(防裸拼)
- [x] 自定义类别字符串 hash 稳定取色
- [x] `catPresets/taskCatPresets` 供 `<select>` 渲染
- [x] 全部挂 window 全局

## 消费方统一 — 完成

- [x] calendar.html / events.html 改读 KB_CATEGORIES
- [x] tasks.html / task_detail.html / task_edit.html 改读 taskCatColor/taskCatIcon
- [x] workspace.html 删除 CAT_COLOR(#3b82f6 错值)/ CAT_ICON 重复定义
- [x] app.js 提交表单调 catPresets()
- [x] 校验:类别元数据层面已无重复硬编码对象字面量

## AGENTS.md 规范重写 — 完成

- [x] Hard Rules / 离线优先(CDN 禁令 + v= 缓存策略)
- [x] 前端 / 图标规范(主次机制 / 容器范围 / Vendoring 验证)
- [x] Shared Category Metadata(禁止页面重定义)
- [x] UI Debugging Order(六步排查法)
- [x] Data Ownership(单数据源表 + 已知双写风险)
- [x] Frontend Modification Boundaries(局部修改边界)

## 深色对比度修复(v0.4.18) — 完成

- [x] `--c-surface` 5% → 8%
- [x] `--c-surface-2` 3.5% → 5.5%
- [x] 文字提亮 `--c-text: #ececff` / `--c-text-muted: #9aa0c7`
- [x] 时间线轴线 / 圆点深色提亮

## 图标按钮 pointer-events 修复(v0.4.20) — 完成

- [x] 按钮内 svg `pointer-events: none`(`style.css:3644-3648`)
- [x] 注释记录根因(Lucide mousedown→mouseup 间替换 svg)

## 静态资源版本号 — 完成

- [x] style.css / app.js / cat-meta.js / lucide.min.js 引用带 `?v=N` 缓存策略
- [x] 资源变更时 bump 版本号

## 验收

- [x] 416 passed(无新增测试,纯前端 / 样式 / 规范)
- [x] 全站图标统一 Lucide 线条风格
- [x] 深色模式卡片 / badge 可见
- [x] 点图标按钮有反应
- [x] 加新类别只改 cat-meta.js 一处
