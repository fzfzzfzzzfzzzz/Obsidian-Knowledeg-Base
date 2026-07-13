# Checklist v0.1 —— Obsidian 本地知识库

> 版本:v0.1
> 状态:✅ 全部完成
> 日期:2026-07-14

---

## Phase 0:项目初始化
- [x] 创建 vault 目录结构(00_Inbox ~ 99_System + .kb/)
- [x] 创建 11 个模板文件(source/summary×5/idea/todo/weekly/monthly)
- [x] 创建 AGENTS.md / README.md
- [x] 创建 scripts/kb.py + init 命令
- [x] 创建 .env.example / .gitignore / requirements.txt

## Phase 1:Inbox 解析器
- [x] KB_ITEM_START/END 解析(结构化格式)
- [x] 自由文本解析(--- 分隔多段)
- [x] 网页抓取(requests + HTML 解析)
- [x] LLM 智能识别 metadata(glm-4.7-flash)
- [x] source_id 幂等机制(SHA1 hash)
- [x] 抓取失败降级(url_only 标记)
- [x] 可读文件名(日期+标题,hash 放 frontmatter)

## Phase 2:Summary 生成
- [x] LLM 生成结构化 summary(按 source_type 选模板)
- [x] 详细保留模式(保留事实/数据/链接)
- [x] make-prompts --auto 自动模式
- [x] make-prompts 手动模式(生成 prompt 文件)
- [x] make-prompts --reconcile 回填
- [x] --force --source 单条强制重生成
- [x] 网站一键生成(投稿页勾选 / 待生成板块)
- [x] 思考模型 max_tokens 适配(metadata 2000 / summary 4000 / extract 3000)
- [x] 取消截断限制(FETCH_MAX_CHARS 50000 / 输入 100000)

## Phase 3:Idea/Todo 抽取
- [x] extract-suggestions 独立命令
- [x] 从 summary 抽 idea 候选(JSON 输出)
- [x] 从 summary 抽 todo 候选(JSON 输出)
- [x] 宁缺毋滥(无内容返回空)
- [x] 幂等(action_status 标记)

## Phase 4:Review 确认
- [x] accept-ideas(accepted_research/productivity → 正式 idea list)
- [x] accept-todos(accepted_weekly/monthly/someday → 计划文件)
- [x] 自动创建 weekly/monthly 文件
- [x] 不覆盖正式内容(只 append)
- [x] 原 suggestion 标记 moved

## Phase 5:Web 前端
- [x] FastAPI 后端 + Jinja2 模板
- [x] 仪表盘(未读/已读统计 + 进度条 + 稀后读)
- [x] 投稿页(多文本框 + 自动总结勾选 + 待生成板块)
- [x] 最近阅读页(自动追踪 last_read_at/read_count)
- [x] 收藏夹页
- [x] 文章详情页(markdown 渲染 + 无 summary 回退)
- [x] idea/todo review 页(卡片 + status 徽章 + 改 status)
- [x] 稍后阅读 toggle
- [x] 收藏 toggle
- [x] 删除功能(两次确认 + 彻底清理)
- [x] reading_status 自动流转(打开详情 → read)
- [x] 首页过滤无 summary 的文章

## Phase 6:工程化
- [x] 代码/vault 内容分离(.gitignore)
- [x] VAULT_STRUCTURE.md
- [x] PRODUCT.md
- [x] GitHub 仓库上传
- [x] SSH key 配置
