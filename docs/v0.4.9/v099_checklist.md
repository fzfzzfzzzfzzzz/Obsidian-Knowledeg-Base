# v0.4.9 任务清单(验收记录)

> 日期:2026-07-22 ~ 2026-07-23
> PRD 见 `v099_PRD.md`,changelog 见 `changelog.md`
> 全部已完成(事后补录,勾选状态反映当前实现)

## 路由拆分 — 完成

- [x] `GET /` 改渲染 `workspace.html`(个人工作台)
- [x] `GET /kb` 渲染 `knowledge_base.html`(原首页仪表盘全量搬迁)
- [x] 工作台三栏布局骨架(`ws-layout` / `ws-main` / `ws-rail`)
- [x] 顶部 `ws-hero`(标题 + 搜索框 + 投稿 + 通知铃铛)
- [x] 主列「今日时间线」横向 5 节点骨架
- [x] 右侧「推荐阅读」+「最近阅读」栏骨架

## 知识库页 — 完成

- [x] 原 `/` 仪表盘内容全量搬到 `/kb`
- [x] `.kb-subnav` 子导航(仪表盘 / 全部文章 / 最近阅读 / 投稿)
- [x] 访问文章子页时「知识库」一级入口保持高亮

## 桌面图标 — 完成

- [x] `assets/icon.ico` 规范多尺寸(16/32/48/64/128/256,32bpp,alpha 透明,LANCZOS)
- [x] `assets/icon.png` PNG 源
- [x] 白底修复(flood-fill 抠除连通白底,备份 `icon_original_whitebg.png`)
- [x] `start_kb.vbs` 端口探测 + `/api/health` 轮询 + SW_HIDE 无黑窗

## 导航精简 — 完成

- [x] 主导航删除 4 个文章相关一级条目(11 → 7)
- [x] 文章入口收进 `/kb` 的 `.kb-subnav` 子导航
- [x] `.kb-subnav` 样式(flex + 横向滚动 + active 高亮)

## 验收

- [x] 访问 `/` 看到工作台(任务/时间线/推荐阅读)
- [x] 访问 `/kb` 看到原阅读仪表盘(未读/已读/稍后读 + 统计)
- [x] 文章子页(`/articles` / `/recent` / `/submit` / `/search`)时「知识库」导航高亮
- [x] Windows 桌面快捷方式显示专属图标(非系统通用图标)
- [x] 双击 `start_kb.vbs` 无黑窗启动 + 自动开浏览器
- [x] 325 passed(无新增测试,纯 UI/资产)
