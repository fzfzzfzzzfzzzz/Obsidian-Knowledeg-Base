# Changelog v0.4.9

> 日期:2026-07-22 ~ 2026-07-23
> 主题:**首页拆分(工作台 / 知识库)+ 桌面启动图标 + 导航精简**

本版把原首页"仪表盘"整体搬到 `/kb`,首页 `/` 改为全新的「个人工作台」,
并为 Windows 桌面双击启动配置了规范多尺寸图标。325 passed(无新增测试,纯 UI/资产改动)。

---

## 新增

### 1. 首页拆分:工作台 vs 知识库

**背景**:原首页同时承担「阅读管理仪表盘」(未读/已读/稍后读卡片 + 统计)和
「进入知识库的入口」两个职责,信息密度高、定位模糊。随着任务/事件/时间线等功能加入,
需要一个更聚焦「今日要做的事 + 推荐阅读」的驾驶舱页面。

**实现**(`scripts/web/routers/dashboard.py:88-109`):
- `GET /` → 渲染 `templates/workspace.html`,定位「个人工作台」(idea/时间线/活动/推荐文章)
- `GET /kb` → 渲染 `templates/knowledge_base.html`,定位「文章阅读管理」(原首页内容全量搬迁)

两个页面的职责分工:

| 维度 | 工作台 `workspace.html` | 知识库 `knowledge_base.html` |
|---|---|---|
| 定位 | 个人驾驶舱(任务/时间线/统计/快捷入口) | 文章阅读管理(原仪表盘全量搬迁) |
| 数据 | 任务 + 日历 + 事件 + 阅读 + 概览,聚合自多个端点 | `/api/dashboard` + `/api/dashboard_full` |
| JS | 页面内联 IIFE,与 app.js 解耦 | `app.js:897` `initDashboard()`(复用,无改动) |
| 批量操作 | 无 | 有 batch-bar(归档/收藏/加标签/抽 idea/生成 summary/删除) |

**工作台三栏布局初版**(`templates/workspace.html`):
- `ws-hero`:顶部标题 + 搜索框 + 投稿 + 通知铃铛
- `ws-layout`(grid `minmax(0,1fr) 320px`):
  - `ws-main`(主列):今日时间线、当前任务、底部四栏辅助卡片
  - `ws-rail`(右侧):推荐阅读栏、最近阅读栏

> 注:当前工作台的"底部四栏""当前任务卡片"等内容在 v0.4.10 / v0.4.16 等后续版本中
> 又经历多轮迭代(置顶排序、类别元数据统一、深色对比度等),本份只记录 v0.4.9 的拆分初版。

### 2. 桌面启动图标(`assets/`)

**背景**:`start_kb.vbs`(v0.4.7 新增)把知识库做成了桌面双击启动的本地应用,
但 Windows 快捷方式(`.lnk`)的 `IconLocation` 原本指向 `shell32.dll,13`(系统通用图标),
没有产品识别度。本版补上专属图标。

**资产**:
- `assets/icon.ico`(97587 B):主图标,Windows 快捷方式指向它
- `assets/icon.png`(9552 B):PNG 源 / 通用
- `assets/icon_original_whitebg.png`(9552 B):白底修复前的原图备份

**规范多尺寸 ICO**(提交 `b63eeda`):
- 6 尺寸:16 / 32 / 48 / 64 / 128 / 256
- 全部 32bpp 带真 alpha 透明通道
- LANCZOS 高质量缩放

**白底修复**(提交 `e1693a1`):
- 排查发现原图 100% 不透明,背景是实色白(非 PNG 转换丢透明度)
- 用边缘 flood-fill 算法抠除连通白底,约 31% 像素转透明,主体保留
- 备份原图为 `icon_original_whitebg.png`(两 PNG 同源,仅 alpha 不同)

**注意**:`.ico` 没有作为 `<link rel="icon">` 进 `base.html`(浏览器标签页无 favicon 引用),
纯粹给 Windows 桌面快捷方式 `知识库.lnk` 用(快捷方式本身被 `.gitignore` 排除)。

### 3. `start_kb.vbs` 启动器增强

`start_kb.vbs`(113 行)在本版趋于稳定,关键实现:
- `:36-40` Python 路径探测(优先 `D:\Python\python.exe`,否则 `python`)
- `:52-55` 端口探测:服务已在跑就直接开浏览器,不重复启动
- `:58-60` 启动:`cmd /c <py> <kb.py> serve`,窗口风格 0(SW_HIDE 完全隐藏无黑窗)
- `:62-81` 轮询 `/api/health`,最多等 30 秒,超时弹 MsgBox 报错
- `:95-112` `IsServerUp()`:**必须用 GET**(`/api/health` 只注册 GET,用 HEAD 会被 FastAPI 返回 405);
  **VBS 的 `Err` 对象全局累积**,每步必须显式 `Err.Clear` 否则前一步错误码会让后续判断产生竞态误报

---

## 顺手改动

### 导航精简到 7 项(提交 `cda4ddd`)

**问题**:主导航原有 11 个一级条目,文章相关页面(搜索/全部文章/投稿/最近阅读)占据主导航空间,
但它们逻辑上都属于「知识库」子域,平铺在主导航反而稀释了核心入口。

**实现**:
- 主导航删除 4 个文章相关页面(11 → 7)
- 收进 `/kb` 顶部的**知识库子导航** `.kb-subnav`(`templates/knowledge_base.html:25-30`):
  仪表盘(`/kb`)/ 全部文章(`/articles`)/ 最近阅读(`/recent`)/ 投稿(`/submit`)
- `.kb-subnav` CSS 在 `static/style.css:2551-2571`(flex + 横向滚动 + active 高亮)
- 访问文章域子页(`/articles` / `/recent` / `/submit` / `/search`)时,「知识库」一级入口保持高亮

> 注:当前主导航条目数已是 9(后续 v0.4.10 加回「任务」、v0.4.20 加「市场」),
> v0.4.9 当时的「精简到 7 项」准确无误。

---

## 文件改动

| 文件 | 改动 |
|---|---|
| `scripts/web/routers/dashboard.py` | `GET /` 改渲染 workspace.html;新增 `GET /kb` 渲染 knowledge_base.html |
| `scripts/web/templates/workspace.html` | 新增,工作台首页(三栏布局 + 时间线 + 推荐阅读栏) |
| `scripts/web/templates/knowledge_base.html` | 新增,原首页仪表盘全量搬迁 + `.kb-subnav` 子导航 |
| `scripts/web/static/style.css` | `.ws-*` 工作台样式 + `.kb-subnav` 子导航样式 |
| `assets/icon.ico` | 新增,6 尺寸 32bpp LANCZOS 多尺寸图标(97587 B) |
| `assets/icon.png` | 新增,图标 PNG 源 |
| `assets/icon_original_whitebg.png` | 新增,白底修复前原图备份 |
| `start_kb.vbs` | 启动器增强(端口探测 / health 轮询 / SW_HIDE) |
| `scripts/web/templates/base.html` | 导航结构精简(文章入口收进子导航) |

---

## 不变

- API schema 不变(`GET /` 与 `GET /kb` 返回 HTMLResponse,数据端点未动)
- 文件格式不变
- 知识库仪表盘功能不变(只是换了路由 `/` → `/kb`,数据来源 `/api/dashboard` 不变)

---

## 破坏性变更

**书签 / 链接**:`/` 的内容从「阅读仪表盘」变成「个人工作台」。原访问 `/` 想看阅读统计的用户,
现需访问 `/kb`。属于可见行为变化,但无数据迁移(两个页面读同样的 API)。

---

## 不在本次范围

- **工作台"当前任务卡片" / "底部四栏"**:v0.4.9 只搭了布局骨架,真实数据填充在 v0.4.10(任务系统)之后才有意义
- **桌面图标 favicon**:未引入浏览器标签页图标(`base.html` 无 `<link rel="icon">`),留作后续
- **`.lnk` 快捷方式**:本身不入库(`.gitignore` 排除),`IconLocation` 指向 `assets/icon.ico` 的配置由用户本地维护
