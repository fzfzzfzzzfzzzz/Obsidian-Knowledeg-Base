# Obsidian 本地知识库 —— 产品功能文档

> Local-first 知识库:收集前沿技术内容 → AI 总结 → 提炼 idea/todo → 个人阅读管理。
> 本文档供评审,判断还需要补充哪些功能。

---

## 一、产品定位

**一句话**:把看到的技术内容(文章/repo/推文/视频文案)快速沉淀成结构化知识,并辅助提炼可执行的 idea 和 todo。

**核心原则**(来自 plan.md):
- **Local-first**:Markdown 文件是主数据层,不依赖私有数据库
- **AI 只建议,不替用户决策**:AI 生成的 idea/todo 先进 review 队列,用户确认后才进正式清单
- **可追溯**:每个 source/summary/idea/todo 都有来源链接和 frontmatter
- **幂等可重跑**:重复处理不会破坏已有内容

---

## 二、整体架构

```
用户输入(URL/正文)
    │
    ▼
ingest(抓取 + LLM 识别 metadata)──▶ source note(01_Sources/)
    │
    ▼
make-prompts(LLM 生成结构化 summary)──▶ summary(02_Summaries/)
    │
    ▼
extract-suggestions(LLM 抽取候选)──▶ idea_suggestions.md / todo_suggestions.md
    │
    ▼
用户 review,改 status 为 accepted_*
    │
    ▼
accept-ideas / accept-todos ──▶ 正式 idea list / weekly·monthly 计划
```

**两种使用入口**:
1. **命令行**(`python scripts/kb.py ...`):完整功能,适合批处理
2. **Web 前端**(`python scripts/kb.py serve`):阅读、投稿、review,可视化操作

---

## 三、已实现功能清单

### 3.1 内容采集(ingest)

| 功能 | 说明 | 命令/入口 |
|------|------|----------|
| 自由文本投稿 | 直接粘贴 URL 或正文,无需格式 | `ingest` / Web 投稿页 |
| 网页自动抓取 | URL 自动抓取正文(requests + HTML 解析),最长 50000 字符 | ingest 时自动触发 |
| LLM 智能识别 | 自动识别 source_type/area/title/intent(glm-4.7-flash) | ingest 时自动调用 |
| 多种格式兼容 | 微信/X/GitHub/抖音/GPT 对话/普通网页/纯文本 | 按 source_type 分类入库 |
| 结构化格式(旧) | 仍兼容 `KB_ITEM_START/END` 包裹的格式 | `ingest --no-llm` |
| 幂等去重 | 基于正文 SHA1,重复 ingest 不重复创建 | source_id 机制 |
| 抓取失败降级 | 反爬/超时时标记 `url_only`,summary 生成时跳过避免瞎编 | 自动处理 |

### 3.2 AI 总结(make-prompts)

| 功能 | 说明 |
|------|------|
| 自动生成 summary | LLM 按模板章节生成结构化中文笔记(glm-4.7-flash,200K 上下文) |
| 详细保留模式 | 保留事实/数据/项目名/链接,不压缩成空话;链接必须完整不省略 |
| 按类型选模板 | github/web/wechat/douyin/gpt_chat/manual 各有专属章节结构 |
| 两种模式 | `--auto` 直调 LLM;默认生成 prompt 文件供手动粘贴 |
| 批量处理 | 一次为所有未总结的 source 生成 summary |
| 单条强制重生成 | `--force --source <id>` 重新生成指定 summary |
| 手动结果回填 | `--reconcile` 扫描已有 summary 文件,回填到 state |
| 网站一键生成 | 投稿页可勾选"自动生成 summary",或对待总结文章逐个/批量生成 |

### 3.3 Idea / Todo 候选抽取(extract-suggestions)

| 功能 | 说明 |
|------|------|
| 从 summary 抽 idea 候选 | LLM 提炼可长期跟进的 idea,含领域/优先级/可行性/新颖度/预估投入 |
| 从 summary 抽 todo 候选 | LLM 提炼可执行 todo,含推荐计划/时间/难度/验收标准 |
| 宁缺毋滥 | 无可转化内容时返回空,不硬编 |
| 进 review 队列 | 候选先进 `idea_suggestions.md` / `todo_suggestions.md`,不直接进正式清单 |
| 幂等 | action_status 标记,重复抽取不重复 append |

### 3.4 Review 确认(accept-ideas / accept-todos)

| 功能 | 说明 |
|------|------|
| idea 确认 | 用户改 status 为 `accepted_research`/`accepted_productivity`,脚本移动到正式 idea list |
| todo 确认 | 改为 `accepted_weekly`/`accepted_monthly`/`accepted_someday`,移动到 weekly/monthly/someday 文件 |
| 自动创建计划文件 | weekly 文件不存在时用模板创建(`YYYY-Www.md`) |
| 不覆盖正式内容 | 只 append,绝不覆盖用户手写内容;原 suggestion 标记 `moved` 保留追溯 |

### 3.5 阅读管理(Web 前端)

| 功能 | 说明 | 入口 |
|------|------|------|
| **仪表盘** | 未读/已读/总计/进度 统计卡片 + 进度条 + 稍后读列表 | 首页 `/` |
| **未读/已读列表** | 按 reading_status 分组的文章卡片(只含有 summary 的) | 首页 |
| **稍后阅读** | 手动标记"稍后读",卡片/详情页 toggle | 卡片 📖 按钮 |
| **最近阅读** | 自动追踪打开详情(last_read_at + read_count),按时间倒序最多 30 篇 | 侧边栏 `/recent` |
| **收藏夹** | 手动收藏,卡片/详情页 toggle | 侧边栏 `/favorites` |
| **投稿** | 网页直接粘贴内容,多文本框动态添加,勾选是否自动总结 | 侧边栏 `/submit` |
| **文章详情** | summary 渲染(markdown→HTML),无 summary 时回退显示原文 + 警告 | 点卡片进入 |
| **删除** | 彻底删除文章(source note + summary + raw + state + 关联候选),两次确认 | 卡片 🗑 / 详情页 |

### 3.6 idea/todo Review 页面(Web 前端)

| 功能 | 说明 |
|------|------|
| idea 列表 | 卡片展示,status 徽章(待审核/已接受/已移动),可直接点按钮改 status |
| todo 列表 | 同上,按钮为"本周/本月/someday" |
| 实时写回 | 改 status 直接写回 markdown 文件(只改 status 行 + 自动备份) |

---

## 四、数据结构

### 4.1 文件组织(vault 目录)

```
00_Inbox/         投稿入口(inbox.md / processed.md 留底)
01_Sources/       source note,按来源类型分子目录(github/x/wechat/...)
02_Summaries/     summary,按类型分子目录
03_Ideas/         research_ideas / productivity_ideas / idea_suggestions / archived
04_Plans/         Weekly/ / Monthly/ / todo_suggestions / completed / someday
05_Projects/      项目自身进度
90_Templates/     11 个模板(source/summary×5/idea/todo/weekly/monthly)
99_System/        schema / prompt_library / processing_log / settings
.kb/              机器目录(state.json / raw_text / logs / prompts,gitignore 忽略)
```

### 4.2 state.json(核心状态)

每个 source 记录:
```json
{
  "source_id": "source_ff_<hash>",     // 幂等键(纯 hash)
  "path": "01_Sources/<type>/<可读文件名>.md",
  "source_type": "wechat|github|x|...",
  "source_title": "...",
  "summary_path": "02_Summaries/.../...md",
  "metadata_source": "llm|inline",
  "reading_status": "to_read|reading|read",  // 阅读状态
  "read_later": false,                        // 稍后阅读
  "is_favorite": false,                       // 收藏
  "last_read_at": "2026-07-11T...",           // 最近阅读时间
  "read_count": 0,                            // 阅读次数
  "action_status": "undecided|todo_suggested" // 候选抽取状态
}
```

### 4.3 frontmatter 字段(每类文件)

source note: id / content_hash / source_type / source_url / source_title / area / status / raw_location / summary_location / metadata_source

summary: id / source_id / kind:summary / source_type / status:summarized / action_status / priority / confidence

idea_suggestion: id / status:pending_review / recommended_area / source_summary / priority / feasibility / novelty

todo_suggestion: id / status:pending_review / recommended_plan / estimated_time / difficulty

---

## 五、技术栈

| 层 | 技术 |
|----|------|
| LLM | 智谱 GLM-4.7-flash(免费,200K 上下文,思考模型),OpenAI 兼容 API |
| 网页抓取 | requests + 自写 HTML 解析器(标准库 html.parser) |
| CLI | Python 标准库(argparse),零额外依赖跑核心流程 |
| Web 后端 | FastAPI + uvicorn |
| Web 前端 | 原生 JS + Jinja2 模板 + CSS,无框架 |
| 配置 | `.env` 文件(API key),被 gitignore 忽略 |
| 数据 | Markdown 文件(主)+ state.json(状态索引) |

---

## 六、当前状态/限制

### 已完成且可用
- 完整的采集→总结→抽取→确认闭环
- Web 前端(仪表盘/投稿/阅读管理/idea·todo review)
- 6 个 CLI 命令 + 1 个 serve 命令

### 已知限制(可能需要补充的功能)
1. **无全文搜索**:找不到包含某关键词的文章
2. **无标签/分类系统**:只能按 source_type 和 area 粗分
3. **无多收藏夹**:收藏只是布尔值,不能分组
4. **无 AI 讨论**:不能就某篇文章继续追问 LLM
5. **无导出**:不能批量导出某段时间的 summary/idea
6. **summary 不能网页内编辑**:要改得回 Obsidian
7. **无阅读进度**:只记打开次数,不记"读到哪一段"
8. **无数据统计图表**:只有数字,无趋势图
9. **无移动端适配优化**:响应式但未针对手机优化
10. **无多用户/同步**:本地单人用

---

## 七、评审请关注

请判断以下方向哪些值得优先补充:

1. **搜索**:全文搜索 / 按标签 / 按时间范围筛选
2. **AI 深度讨论**:针对某篇 summary 继续和 LLM 对话追问
3. **知识关联**:文章之间的关系图 / 自动发现相关文章
4. **定期回顾**:周报/月报自动汇总阅读和 idea 进展
5. **多端同步**:支持云同步或移动端访问
6. **导入导出**:批量导入 / 导出为 PDF/EPUB
7. **标签系统**:自定义标签,多维分类
8. **通知提醒**:todo 到期 / 稍后读堆积提醒

(或其他你认为重要的功能)
