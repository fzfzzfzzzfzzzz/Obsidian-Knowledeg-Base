# Changelog v0.2

> 日期:2026-07-15

## 新增

### 搜索与筛选(batch 1)
- **全文搜索**:搜索 title + summary 正文 + tags,大小写不敏感,包含即命中
- **筛选**:reading_status / is_favorite / source_type / tags / has_summary 组合筛选
- **搜索页**(`/search`):搜索框 + 5 个筛选器 + 结果卡片
- **首页搜索框**:首页输入关键词跳转搜索页

### 标签系统(batch 1)
- **手动标签**:详情页添加/删除 tags,双写 state.json + summary frontmatter
- **AI 推荐标签**:基于 summary 生成 3-5 个主题标签(glm-4-flash)
- **卡片展示 tags**:所有页面卡片显示 tags 徽章
- **搜索/筛选支持 tags**

### All Articles 页(batch 1)
- 独立页面 `/articles`,展示所有文章(含无 summary 的)
- 卡片标记 has_summary 状态

### 批量管理(batch 2)
- **批量选择**:卡片 checkbox,勾选后显示批量操作栏(显示已选数量)
- **7 种批量操作**:归档/删除/收藏/取消收藏/加标签/生成 summary/抽取 idea/todo
- **批量删除**:两次确认 + 自动备份
- **结果反馈**:显示成功/失败/跳过数量 + 失败项列表
- **单条失败不影响其他**:部分失败不回滚

### 后续增量
- **重新生成 summary**:详情页「🔄 重新生成」按钮(备份旧 summary)
- **删除 summary**:详情页「🗑 删除 summary」按钮(保留 source,可让别的 Agent 重做)
- **查看原文**:详情页显示原始链接「🔗 查看原文」
- **模板更新**:"详细内容总结"替代"方法/框架/实现路径"
- **AGENT_SUMMARIZE.md**:供本地 Agent 自主生成 summary 的操作手册

## 修复
- AI 推荐标签返回空(`_extract_json_list` 过滤了字符串标签,改为独立解析)
- LLM 返回空 summary 时静默写入空文件(加空内容检查)
- 网页抓取正文截断(FETCH_MAX_CHARS 6000 → 50000)
- summary 生成输入截断(8000 → 100000)
- glm-4.7-flash 思考模型 max_tokens 不足(调大后换回 glm-4-flash)
