# Roadmap

> 本文件汇总所有版本 PRD 中提到的后续迭代方向 + 已知限制的改进计划。
> 按优先级分层,供评审和规划参考。
> 最后更新:2026-07-20(v0.4.5 后)

---

## 当前版本:v0.4.5

已实现:P0 真 bug 修复 + P2 数据一致性。第二轮深度审查发现的 10 个高危问题全部修复(kb_date 日期错误、_html_to_text 重复输出、JSON 死代码、ingest-image 覆盖 inbox、备份命名、原子写、文件锁、损坏检测、Web accept 事务化)。224 passed。
- v0.4.0:详情页「生成 Idea/Todo 列表」按钮 + 引导弹窗(见 `docs/v0.4.0/`)
- v0.4.1:投稿页批量投稿(URL 提取)、/ideas /todos 拆「待定/已确定」tab、已确认 todo 放入日历(见 `docs/v0.4.1/`)
- v0.4.2:日历「时间轴」视图(垂直+水平)、category 字段(6 预设+自定义)、标签筛选条影响三个视图(见 `docs/v0.4.2/`)
- v0.4.3:rebuild-index 命令、Web accept 自动搬运、6 路径常量环境变量覆盖、文档同步、+61 测试(见 `docs/v0.4.3/`)
- v0.4.4:kb_web.py 2117→74 行装配文件 + web/ 包(9 router + 4 service)、kb.py 抽公共工具、+11 测试(见 `docs/v0.4.4/`)
- v0.4.5:第二轮审查 P0+P2 修复(10 个高危问题),+52 测试(见 `docs/v0.4.5/`)
完整功能清单见 `PRODUCT.md`。

---

## P1:近期值得做

### 1. ~~自动化测试~~ ✅ v0.4.3 完成
- **结果**:从 0 → 161 passed。覆盖核心命令(accept/make-prompts/rebuild-index)、move 纯函数、Web accept 端到端、路径配置等。kb_date.py 日期识别仍有覆盖空间,但高风险命令已全部有回归网。
- **遗留**:kb_date.py 16 种日期格式用例覆盖偏薄(已有 test_date.py 13 用例,但边界 case 可补)。

### 2. ~~rebuild-index~~ ✅ v0.4.3 完成
- **结果**:`python scripts/kb.py rebuild-index` 已实现,支持 --dry-run / --tags-only / --summary-path-only,写前自动备份,不碰用户行为数据。
- **文档**:`docs/v0.4.3/changelog.md` 第 1 节

### 3. ~~kb_web.py 按域拆 8 个 APIRouter~~ ✅ v0.4.4 完成
- **结果**:`kb_web.py` 2117 → 74 行装配文件,拆出 `scripts/web/` 包(9 个 APIRouter + 4 个 service + models/utils)。同步抽 kb.py 公共工具(hash_from_source_id / make_note_filename / _strip_inbox_header_lines / _count_status_in_file)。172 passed,零回归。
- **文档**:`docs/v0.4.4/changelog.md`

### 4. 日期识别基准优化
- **现状**:用当前日期做年份推断和相对日期基准
- **要做**:优先用文章发布时间(created_at),其次导入时间,最后当前日期
- **来源**:v0.3 PRD 6.2.4 / 6.2.6
- **价值**:提高日期识别精度,避免跨年误判

### 5. idea/todo 抽取的 prompt 量化标准(v0.4.0 批注后续项 A)
- **现状**:`priority`/`feasibility`/`novelty`/`difficulty` 只给枚举可选值,无判定门槛,同份 summary 不同时间跑结果不稳定
- **要做**:prompt 里补量化判定标准(P0/P1/P2/P3 各代表什么、novelty high 的门槛等)
- **来源**:v0.4.0 PRD §1.2 批注 + §12 后续项 A
- **价值**:抽取结果可复现、可排序,review 队列不再全是兜底默认值

### 6. 修 todo estimated_time 硬兜底(v0.4.0 批注后续项 B)
- **现状**:`kb_llm.py:812-813` LLM 没返回 `estimated_time` 就强制填 `"2-4h"`,伪造数据污染 review 队列
- **要做**:空值留空或标"(未估)",不要伪造
- **来源**:v0.4.0 PRD §1.2 批注 + §12 后续项 B
- **价值**:review 队列的时间估计可信

### 7. 修 JSON 解析静默失败(v0.4.0 批注后续项 C)
- **现状**:`_extract_json_list` 失败返回 `[]`,调用方 `if items is None` 分支永远走不到,解析失败被当成"0 候选",无日志无告警
- **要做**:解析失败时记日志 + 在 source state 标 `extract_error`,区分"真没候选"和"解析出错"
- **来源**:v0.4.0 PRD §1.2 批注 + §12 后续项 C
- **价值**:抽取异常可观测,不再静默丢数据

### 8. ~~Web 端 accept 自动搬运~~ ✅ v0.4.3 完成(原 P1-15)
- **结果**:Web 端点接受按钮直接触发搬运,不再需要手动跑 CLI accept-ideas/accept-todos。
- **文档**:`docs/v0.4.3/changelog.md` 第 2 节

---

## P2:中期功能增强

### 8. AI 深度讨论
- **现状**:不能就某篇 summary 继续追问 LLM
- **要做**:详情页加对话框,基于当前 summary 上下文和 LLM 多轮对话
- **价值**:从"只读总结"变成"可交互探讨"

### 9. 全文搜索索引
- **现状**:搜索是实时扫描所有 summary 文件
- **要做**:预建 search_index.json 或 SQLite FTS,新增/删除/编辑后同步更新
- **来源**:v0.2 Implementation Prompt 第六节
- **价值**:文章到 500+ 篇时搜索性能保障

### 10. 多收藏夹
- **现状**:收藏只是布尔值 is_favorite
- **要做**:collections 数据结构,一篇文章可属于多个收藏夹
- **来源**:v0.1 PRD 1.4 / PRODUCT.md 限制 3
- **价值**:按主题/项目分组管理重要文章

### 11. 日历提醒
- **要做**:事项支持提前 1 天/3 天/7 天提醒,浏览器通知
- **来源**:v0.3 PRD 17.2 / Checklist P2-34
- **价值**:日历事项到期前主动提醒,不遗漏截止日期

### 12. 标签管理
- **现状**:无标签管理页,无重命名/合并
- **要做**:标签列表页、重命名、合并、使用统计
- **来源**:v0.2 PRD 5.2 明确不做(第一版),后续可加
- **价值**:标签多了后的维护能力

### 13. 自动产出补全模板章节(v0.4.0 批注后续项 D)
- **现状**:自动生成的 suggestion 比模板少一半章节(模板的 MVP/风险/下一步 todo/依赖条件等节在 `_format_idea_suggestion`/`_format_todo_suggestion` 里没产出),review 信息残缺
- **要做**:prompt 要求产出这些章节,`_format_*` 同步写全;todo 补 `related_idea` 关联
- **来源**:v0.4.0 PRD §1.2 批注 + §12 后续项 D
- **价值**:review 队列信息完整,用户决策有依据

### 14. prompt_library.md 沉淀与同步(v0.4.0 批注后续项 E)
- **现状**:`99_System/prompt_library.md` 第 42 行仍写「Summary 生成待实现」,idea/todo prompt 未沉淀,文档严重滞后于代码
- **要做**:把 idea/todo 的 prompt 沉淀进 prompt_library.md,删过时表述,建立"代码改 prompt 同步更新文档"的约定
- **来源**:v0.4.0 PRD §1.2 批注 + §12 后续项 E
- **价值**:文档与代码一致,符合 AGENTS.md "状态字段一致"要求

### 15. ~~Web 端 accept 自动搬运~~ ✅ v0.4.3 完成(v0.4.0 批注后续项 F)
- **结果**:Web accept API 已改为接受即搬运,不再需要跑 CLI。详见 P1 第 8 项与 `docs/v0.4.3/changelog.md` 第 2 节。

### 16. summary 重生成后允许重抽(v0.4.0 批注后续项 G)
- **现状**:`extract-suggestions` 成功一次就把 `action_status` 置 `todo_suggested`,summary 重新生成后也无法重抽(除非手动改 state)
- **要做**:summary 重生成时把对应 source 的 `action_status` 回退到 `undecided`,允许重抽(旧候选标 superseded 保留追溯)
- **来源**:v0.4.0 PRD §1.2 批注 + §12 后续项 G
- **价值**:summary 更新后 idea/todo 能跟上,不锁死

---

## P3:远期/大功能

### 17. 外部日历同步
- Google Calendar / Outlook Calendar OAuth 同步
- 来源:v0.3 PRD 17.3 / Checklist P2-36

### 18. 知识关联图谱
- 文章之间的关系图 / 自动发现相关文章
- 来源:PRODUCT.md 评审候选

### 19. 定期回顾(周报/月报)
- 自动汇总本周/本月阅读和 idea 进展
- 来源:PRODUCT.md 评审候选

### 20. 移动端优化
- 响应式已有,但未针对手机交互优化
- 来源:PRODUCT.md 限制 8

### 21. 多端同步
- 支持云同步或移动端访问
- 来源:PRODUCT.md 限制 9

### 22. 导入导出
- 批量导入 / 导出为 PDF/EPUB
- 来源:PRODUCT.md 评审候选

### 23. 正文日期高亮
- 在 summary 正文中高亮识别到的日期,点击可直接添加到日历
- 来源:v0.3 PRD 17.2 / Checklist P2-35

### 24. 一个知识条目关联多个日历事项
- 当前限制一个 source 只关联一个 calendar item
- 来源:v0.3 PRD 17.1 / Checklist P2-33

---

## 明确不做的(架构限制)

| 不做 | 原因 |
|------|------|
| 多用户/权限系统 | 本地单人 local-first 架构,无登录体系 |
| Obsidian 自研插件 | MVP 不依赖插件,通过 Markdown + 脚本完成 |
| 平台自动爬虫(X/抖音/微信) | 反爬难度高、稳定性差,用户手动粘贴更可控 |
| 向量数据库/语义搜索 | 第一版保持简单,关键词搜索够用 |
| 自动日程安排 | AI 不替用户决策 |
