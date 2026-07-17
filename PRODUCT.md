# Obsidian 本地知识库 —— 产品功能文档

> Local-first 知识库:收集前沿技术内容 → AI 总结 → 提炼 idea/todo → 个人阅读管理 → 日历事件管理。
> 当前版本:**v0.4.1**(2026-07-17)。

---

## 一、产品定位

**一句话**:把看到的技术内容(文章/repo/推文/视频文案)快速沉淀成结构化知识,辅助提炼可执行的 idea/todo,管理阅读进度,并从内容中识别重要日期加入日历。

**核心原则**:
- **Local-first**:Markdown 文件是主数据层,不依赖私有数据库
- **AI 只建议,不替用户决策**:AI 生成的 idea/todo 先进 review 队列,用户确认后才进正式清单
- **可追溯**:每个 source/summary/idea/todo/calendar 都有来源链接和 frontmatter
- **幂等可重跑**:重复处理不会破坏已有内容

---

## 二、已实现功能清单

### 2.1 内容采集(v0.1)

| 功能 | 说明 |
|------|------|
| 自由文本投稿 | 直接粘贴 URL 或正文,无需格式 |
| 网页自动抓取 | URL 自动抓取正文(requests + HTML 解析),最长 50000 字符 |
| LLM 智能识别 | 自动识别 source_type/area/title/intent(glm-4-flash) |
| 多来源支持 | 微信/X/GitHub/抖音/GPT 对话/普通网页/纯文本 |
| 幂等去重 | 基于正文 SHA1,重复 ingest 不重复创建 |
| 抓取失败降级 | 标记 url_only,summary 生成时跳过避免瞎编 |
| 可读文件名 | source_YYYYMMDD_可读标题.md(hash 放 frontmatter) |

### 2.2 AI 总结(v0.1,持续优化)

| 功能 | 说明 |
|------|------|
| 自动生成 summary | LLM 按模板章节生成结构化中文笔记 |
| 详细保留模式 | 保留事实/数据/项目名/链接,summary 达原文 40-50% |
| 按类型选模板 | github/web/wechat/douyin/gpt_chat/manual 各有专属章节 |
| 两种模式 | --auto 直调 LLM;默认生成 prompt 文件供手动粘贴 |
| 重新生成 | 详情页「🔄 重新生成」按钮(备份旧 summary) |
| 删除 summary | 详情页「🗑 删除 summary」按钮(保留 source,可让别的 Agent 重做) |
| 网站一键生成 | 投稿页勾选"自动生成 summary",或对待总结文章逐个/批量生成 |
| 手动 Agent 生成 | AGENT_SUMMARIZE.md 手册供本地 Agent 自主生成 summary |
| 空内容检查 | LLM 返回空时不写入空 summary(防思考模型 token 浪费) |

### 2.3 Idea/Todo 候选(v0.1)

| 功能 | 说明 |
|------|------|
| 从 summary 抽 idea 候选 | LLM 提炼可长期跟进的 idea(含领域/优先级/可行性/新颖度) |
| 从 summary 抽 todo 候选 | LLM 提炼可执行 todo(含推荐计划/时间/难度/验收标准) |
| 宁缺毋滥 | 无可转化内容时返回空 |
| 进 review 队列 | 候选先进 idea_suggestions.md / todo_suggestions.md |
| 幂等 | action_status 标记,重复抽取不重复 append |

### 2.4 Review 确认(v0.1)

| 功能 | 说明 |
|------|------|
| idea 确认 | accepted_research/productivity → 正式 idea list |
| todo 确认 | accepted_weekly/monthly/someday → 计划文件 |
| 自动创建计划文件 | weekly/monthly 不存在时用模板创建 |
| 不覆盖正式内容 | 只 append;原 suggestion 标记 moved 保留追溯 |

### 2.5 阅读管理(v0.1~v0.2)

| 功能 | 说明 |
|------|------|
| 仪表盘 | 未读/已读/总计/进度 统计卡片 + 进度条 + 稍后读列表 |
| 首页搜索框 | 输入关键词跳转搜索页 |
| 稍后阅读 | 手动标记,卡片/详情页 toggle |
| 最近阅读 | 自动追踪打开详情(last_read_at + read_count),按时间倒序最多 30 篇 |
| 收藏夹 | 手动收藏,独立页面 |
| 投稿页 | 网页直接粘贴,多文本框动态添加,勾选自动总结 |
| 文章详情 | summary 渲染,无 summary 时回退显示原文,查看原文链接 |
| 删除文章 | 彻底删除(source+summary+raw+state+候选+日历关联清理) |
| 首页过滤 | 只显示有 summary 的文章 |

### 2.6 搜索与筛选(v0.2)

| 功能 | 说明 |
|------|------|
| 全文搜索 | 搜 title + summary 正文 + tags,大小写不敏感 |
| 筛选 | reading_status / is_favorite / source_type / tags / has_summary 组合 |
| 搜索页 | 搜索框 + 5 个筛选器 + 结果卡片 |
| All Articles 页 | 所有文章(含无 summary),卡片显示 has_summary 标记 |

### 2.7 标签系统(v0.2)

| 功能 | 说明 |
|------|------|
| 手动标签 | 详情页添加/删除 tags |
| AI 推荐标签 | 基于 summary 生成 3-5 个主题标签 |
| 双写 | tags 同步写入 state.json + summary frontmatter |
| 卡片展示 | 所有页面的卡片显示 tags 徽章 |
| 搜索/筛选支持 | 按标签搜索和筛选 |

### 2.8 批量管理(v0.2)

| 功能 | 说明 |
|------|------|
| 批量选择 | 卡片 checkbox,勾选后显示批量操作栏 |
| 批量归档 | reading_status → archived |
| 批量删除 | 两次确认 + 备份,彻底清理 |
| 批量收藏/取消收藏 | toggle is_favorite |
| 批量加标签 | 追加去重,无 summary 的跳过 |
| 批量生成 summary | 跳过已有 summary 的 |
| 批量抽取 idea/todo | 只处理有 summary 且未抽取的 |
| 结果反馈 | 显示成功/失败/跳过数量 + 失败项 |

### 2.9 日历功能(v0.3~v0.3.1)

| 功能 | 说明 |
|------|------|
| 日期识别 | 正则提取明确/相对/模糊日期 + 年份推断 + 关键词分级 + 八级排序 |
| 误匹配过滤 | 版本号/价格/IP 不识别为日期 |
| 统一日历表单 | 详情页/Calendar/编辑 三个入口共用同一表单组件 |
| 默认值规则 | 详情页用推荐日期(无则今天),Calendar 新建用今天,日期格用点击日期 |
| 推荐日期说明 | 显示识别依据 + 置信度(high/medium/low) + 模糊日期警告 |
| Calendar CRUD | 创建/查询/更新/删除,防重复创建 |
| 月视图 | 7×6 网格,上下月切换,高亮今天,点格创建,事项超 3 个显示更多 |
| 列表视图 | 即将到来/已过去/全部筛选,来源显示,关联跳转 |
| 关联管理 | 关联知识文章,可查看/移除关联 |
| 删除文章清理 | 删除文章时自动清除日历事项的关联(事项保留) |

### 2.10 手动生成 Idea/Todo(v0.4.0)

| 功能 | 说明 |
|------|------|
| 详情页按钮 | 文章详情页操作栏「💡 生成 Idea 列表」「✅ 生成 Todo 列表」,仅在有 summary 时显示 |
| 引导弹窗 | 点击后弹窗,可输入引导提示词(可选)+ 手动选优先级/领域(idea)/难度/预计时间/计划(todo) |
| 参数语义 | 用户所选作为**引导**传给 LLM(非硬约束),每条候选可独立定级 |
| 多条候选 | 一次生成 1-3 条候选,全部进 review 队列 |
| 进 review 队列 | 生成的候选 status=`pending_review`,追加进 idea_suggestions.md / todo_suggestions.md |
| 流程不变 | 仍需在 /ideas、/todos 页 accept + 跑 CLI 进正式清单(与 v0.1 一致) |
| 兼容现有 | 首页批量「💡 抽 idea/todo」按钮 + CLI extract-suggestions 保留不变 |

### 2.11 批量投稿(v0.4.1)

| 功能 | 说明 |
|------|------|
| 批量投稿 panel | 投稿页「📦 批量投稿」,支持拖入 / 选择 .md/.txt 文件,或直接粘贴文本 |
| URL 提取 + 去重 | 正则提取所有 `https?://` 链接,Set 自动去重 |
| 可编辑列表 | 每个 URL 默认勾选,可取消勾选 / 单条删除 / 全选 / 清空 |
| 只入库不总结 | `auto_summary` 固定 false,卡片出现在「待生成 summary」板块 |
| 精确结果 | 显示「成功 N / 跳过 M 条重复 / 失败 K 条」(后端从 log 解析计数) |
| 复用现有 | 复用 `/api/ingest`,单条/图片投稿不受影响 |

### 2.12 Idea/Todo 页「待定/已确定」拆分(v0.4.1)

| 功能 | 说明 |
|------|------|
| 同页 tab | /ideas、/todos 各加「待定 / 已确定」tab,复用首页 tab 样式,懒加载 |
| 待定面板 | 现状 review 队列(idea/todo_suggestions.md),accept/reject 不变 |
| 已确定 Idea | 扫 `03_Ideas/*_ideas.md` 正式清单,按 `## Idea:` 解析,显示 area/priority/maturity |
| 已确定 Todo | 扫 `04_Plans/Weekly`、`Monthly`、`someday`、`completed`,按 plan 分组 |
| Todo 确定性 id | 基于 plan+period+title 的 sha1,重新解析不变(供日历关联) |
| 健壮 | 文件不存在/为空显示友好空状态,不报错 |

### 2.13 已确认 Todo → 日历链接(v0.4.1)

| 功能 | 说明 |
|------|------|
| 放入日历按钮 | 已确定 todo 卡片「📅 放入日历」,复用统一日历表单,标题默认=todo、日期可选 |
| source_id 关联 | 用 todo 的确定性 id 作日历事项 source_id,建立 todo↔calendar 关联 |
| 去重 | 同一 todo 重复放入返回已有事项,不创建重复 |
| 已加入状态 | 卡片显示「📅 已加入日历 · {date}」+ 编辑按钮,刷新后正确回显 |
| 零新增 API | 复用现有 `POST /api/calendar`(已支持 source_id 关联+去重) |

---

## 三、技术栈

| 层 | 技术 |
|----|------|
| LLM | 智谱 GLM-4-flash(免费,非思考模型) |
| 网页抓取 | requests + 自写 HTML 解析器(标准库 html.parser) |
| CLI | Python 标准库(argparse) |
| Web 后端 | FastAPI + uvicorn |
| Web 前端 | 原生 JS + Jinja2 模板 + CSS,无框架 |
| 日期识别 | 纯正则(kb_date.py),不调 LLM |
| 配置 | .env 文件(API key),被 gitignore 忽略 |
| 数据 | Markdown 文件(主)+ state.json(状态索引)+ calendar.json(日历) |

---

## 四、数据结构

### 文件组织
```
00_Inbox/         投稿入口
01_Sources/       source note(按来源类型分子目录)
02_Summaries/     summary(按类型分子目录)
03_Ideas/         idea 管理(review 队列 + 正式清单)
04_Plans/         todo/计划管理(Weekly/Monthly/someday)
05_Projects/      项目记录
90_Templates/     11 个模板(init 生成)
99_System/        schema/prompt_library/settings
.kb/              机器目录(state.json/calendar.json/raw_text/logs)
```

### 核心数据文件
- **state.json**:所有 source 的元数据 + 阅读状态 + tags + detected_dates
- **calendar.json**:CalendarItem(id/title/date/note/source_id/date_source/confidence)
- **summary frontmatter**:tags 字段 + 全部元数据
- **source note frontmatter**:content_hash/source_url/summary_location/metadata_source

---

## 五、CLI 命令

| 命令 | 说明 |
|------|------|
| `kb.py init` | 创建 vault 目录结构/模板/空文件 |
| `kb.py ingest` | 解析 inbox,抓取+识别+生成 source note |
| `kb.py make-prompts --auto` | LLM 生成 summary |
| `kb.py extract-suggestions` | 从 summary 抽 idea/todo 候选 |
| `kb.py accept-ideas` | accepted idea → 正式清单 |
| `kb.py accept-todos` | accepted todo → weekly/monthly |
| `kb.py status` | 知识库状态统计 |
| `kb.py llm-test` | 测试 API 连通性 |
| `kb.py serve` | 启动 Web 前端 |

---

## 六、已知限制

1. **无全文搜索索引**:搜索是实时扫描,文章多了会慢
2. **无 rebuild-index**:state.json 和 frontmatter 不一致时无自动修复
3. **无多收藏夹**:收藏只是布尔值,不能分组
4. **无 AI 讨论**:不能就某篇 summary 继续追问 LLM
5. **summary 不能网页内编辑**:要改得回 Obsidian 或用本地 Agent
6. **无阅读进度**:只记打开次数,不记"读到哪一段"
7. **无数据统计图表**:只有数字,无趋势图
8. **无移动端优化**:响应式但未针对手机优化
9. **无多用户/同步**:本地单人用
10. **测试覆盖有限**:已有 74 个核心测试(ingest/解析/日历/批量/confirmed),但前端交互无自动化测试
11. **日历无提醒/通知**:不会到期推送
12. **日历无外部同步**:不支持 Google/Outlook Calendar
13. **日期识别基准**:用当前日期而非文章发布时间做年份推断(精度略低)

---

## 七、评审请关注

详见 `docs/ROADMAP.md`。

- v0.4.0:详情页手动生成 idea/todo 见 `docs/v0.4.0/manual_idea_todo_generation_PRD.md`,含 idea/todo 生成规则已知问题批注
- v0.4.1:批量投稿、Idea/Todo 页「待定/已确定」拆分、Todo→日历链接 三项功能见 `docs/v0.4.1/v041_features_PRD.md`
