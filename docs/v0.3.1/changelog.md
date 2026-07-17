# Changelog v0.3.1

> 日期:2026-07-15

## 新增
- **统一日历事件表单**：详情页「添加到日历」、Calendar「新建事件」、Calendar「编辑事件」三个入口统一为同一表单组件（`openCalendarEventForm`）
- **表单字段**：标题(必填) + 日期(必填) + 关联内容(可选) + 备注(可选)，不含事件类型/时间/提醒
- **默认值规则**：
  - 知识详情页：标题默认知识标题，日期默认推荐日期
  - 无推荐日期时默认今天（覆盖 v0.3 原规则"日期为空"）
  - Calendar 顶部新建：默认今天
  - 日期格点击新建：默认所点日期
  - 编辑模式：回填已有数据
- **推荐日期说明**：仅知识详情页入口显示识别依据 + 置信度提示
- **关联内容管理**：可查看关联文章、可移除关联

## 修复（P1 缺陷）
- **删除文章时不清理日历关联**：删除知识文章后，关联的日历事项的 source_id/source_title 自动清空（事项保留，不再成为孤儿）
- **编辑模式移除关联不持久化**：PATCH API 新增 source_id 字段，前端保存时发送，移除关联真正生效

## 文件改动
- `app.js`：+`openCalendarEventForm` 统一表单函数（~140 行）+ PATCH body 加 source_id
- `summary.html`：替换旧 prompt 链为统一表单调用
- `calendar.html`：替换旧 prompt 链为统一表单调用
- `kb_web.py`：`CalendarItemUpdate` 加 source_id 字段 + PATCH API 处理 + `_delete_one` 加日历清理
- `style.css`：统一表单样式
