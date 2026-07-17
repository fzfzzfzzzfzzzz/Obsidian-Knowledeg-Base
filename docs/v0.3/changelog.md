# Changelog v0.3

> 日期:2026-07-15

## 新增
- **日历功能**：独立 `/calendar` 页面，支持月视图 + 列表视图
- **日期识别模块**（kb_date.py）：正则提取明确日期/相对日期/模糊日期，支持年份推断、关键词分级（截止/发布/活动）、八级排序推荐、版本号/价格误匹配过滤
- **日历数据层**：`.kb/calendar.json` 独立存储 CalendarItem，与 state.json 分离
- **日期识别 API**：`GET /api/article/{id}/detected-dates`、`POST /api/article/{id}/detect-dates`
- **日历 CRUD API**：创建/查询/更新/删除 CalendarItem，支持按日期范围筛选、防重复创建
- **详情页「添加到日历」**：自动识别正文日期，推荐最佳日期，创建关联日历事项
- **月视图**：7×6 网格、上下月切换、回到今天、高亮今天、点击日期创建事项、事项超 3 个显示"+N 更多"
- **列表视图**：即将到来/已过去/全部筛选、来源显示、关联跳转
- **导航栏新增「📅 日历」入口**

## 修复
- 无

## 文件改动
- 新建 `scripts/kb_date.py`（日期识别模块，~300 行）
- `kb.py`：+CALENDAR_FILE + load_calendar/save_calendar + init 初始化
- `kb_web.py`：+import kb_date + 6 个日历 API + /calendar 页面路由（~200 行）
- `summary.html`：+「添加到日历」按钮 + 弹窗逻辑
- `calendar.html`：新建（月视图 + 列表视图）
- `base.html`：导航加日历入口
- `style.css`：日历页面样式
