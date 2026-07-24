# 暗色模式文字对比度修复 — 概述

## 问题
暗色模式下大量文字看不清。根因不在变量本身,而在于 **Ardot 暗色主题把主色 / 成功 / 警告 / 危险 全部改成了浅色强调色**(`#7aa2ff` / `#34d399` / `#fbbf24` / `#f87171`),但大量按钮、徽章、日历事件块仍写死 `color:#fff`(白字),于是出现「浅色底 + 白字」,对比度严重不达标(WCAG AA 要求正文 4.5:1、大字号 3:1)。

受影响最明显的组件:
- 接受按钮 `.btn-accept`(浅绿底白字 ≈1.8:1)
- 危险/警告按钮悬停态 `.btn-danger:hover` `.btn-warn:hover`
- 状态徽章 `.status-badge` 的 accepted(浅绿)/rejected/archived(浅红)/pending(灰蓝)变体
- 任务状态 `.tk-status-badge`(JS 注入绿/蓝/红/灰底 + 白字,尤其「已完成」绿底最明显)
- 日历/时间轴事件块 `.cal-day-item` `.tl-item-cat`、今日标记 `.cal-today-badge` `.tl-today-tag`(浅彩底白字)
- 已读/收藏激活图标 `.icon-btn.active-rl/fav`、`.detail-action-btn.active-rl/fav`、删除悬停等
- 第一段暗色块漏定义 `--c-text-soft`,导致工作台副标题/占位符黑字黑底

## 修复方案
在 `scripts/web/static/style.css` 末尾新增第 33 节(层叠优先级最高,仅作用于 `[data-theme="dark"]`):
1. 给上述「浅底白字」元素叠加 `box-shadow: inset 0 0 0 999px rgba(15,23,42,0.5)` 压暗背景 → 白字对比度全面达 AA(含黄色警告)。
   - 选用「压暗背景」而非「改深色文字」,是因为任务状态徽章/侧栏激活项背景为中明度,改深字会反成「深字深底」;压暗背景对浅/中明度底色统一有效。
2. 排除 `.status-moved`(深底浅字,本身已达标)与 `.sb-link.active`(深紫渐变底白字 ≈13:1,保留原观感)。
3. 补 `--c-text-soft: #c9c9e8` 到暗色块,修复副标题/占位符。

## 验证
- `python scripts/kb.py serve` 启动 FastAPI,首页与 `/static/style.css` 均返回 200。
- 服务端返回的 CSS 已包含修复层(grep 命中)。
- 运行依赖 uvicorn / jinja2 / python-multipart 已装在隔离 venv:`C:/Users/ffmic/.workbuddy/binaries/python/envs/kb`。
- 预览地址:`http://127.0.0.1:5173`(右上角主题切换切到暗色即可对比)。

## 可选后续(未改,保持克制)
- 部分 `.tag-*`（如 `.tag-github` 浅蓝底深蓝字）在暗色下是「亮色小芯片」,文字本身可读,但视觉风格与玻璃暗色略有出入,如需可统一加暗色外框。
