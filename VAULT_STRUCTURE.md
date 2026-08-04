# Obsidian Vault 结构说明

> 本文档说明 vault 的目录组织、数据流、状态字段。
> vault 内容由 `python scripts/kb.py init` 自动创建,**不包含在 GitHub 仓库中**(已被 .gitignore 忽略)。
> clone 代码后运行 `init` 即可在本地生成完整 vault 结构。

---

## 目录树

```
<vault 根>/
  00_Inbox/           投稿入口
  01_Sources/         source note(ingest 生成)
  02_Summaries/       summary(make-prompts 生成)
  03_Ideas/           idea 管理
  04_Plans/           plan / 计划管理
  05_Projects/        项目自身记录
  06_Events/          事件管理(event_*.md, frontmatter 含日期/类别,可同步到日历)
  07_Tasks/           任务管理(task_*.md, frontmatter 含 checklist/deadline/pinned/category/status)
  08_Market/          市场自选股(watchlist / 判断等;行情经 kb_quote.py + 派生 SQLite 缓存)
  90_Templates/       模板(init 生成,代码里硬编码)
  99_System/          系统配置 / schema / prompt 沉淀
  .kb/                机器运行目录(state.json / raw_text / logs,gitignore 忽略)
  .env                API key 配置(gitignore 忽略)
```

---

## 各目录详解

### 00_Inbox/ —— 投稿入口
| 文件 | 用途 | 谁写入 |
|------|------|--------|
| `inbox.md` | 用户粘贴 URL/正文的入口 | 用户 / Web 投稿页 |
| `processed.md` | 已处理 item 的留底备份 | ingest 命令自动追加 |
| `gpt_chats.md` | GPT 对话存档(可选) | 用户手动 |
| `clips.md` | 碎片摘录(可选) | 用户手动 |

**数据流**:用户贴内容 → `ingest` 解析 → 移动到 processed.md → 生成 source note

### 01_Sources/ —— source note
按来源类型分子目录:`raw/ github/ x/ wechat/ douyin/ gpt_chat/ web/ manual/`

每个 source note 文件名格式:`source_YYYYMMDD_可读标题.md`(如 `source_20260708_zed_编辑器.md`)

**frontmatter 字段**:
```yaml
id: source_ff_<hash>           # 幂等键(基于正文 SHA1)
content_hash: <hash 前8位>
kind: source
source_type: wechat|github|x|...
source_url: https://...
source_title: ...
area: research|productivity|ai_agent|...
status: source_created|summarized|needs_content
raw_location: .kb/raw_text/<id>.txt
summary_location: 02_Summaries/.../<id>.md
metadata_source: llm|inline    # metadata 来源
```

### 02_Summaries/ —— summary
按类型分子目录(同 01_Sources)。

文件名格式:`summary_YYYYMMDD_可读标题.md`

**frontmatter 字段**:
```yaml
id: summary_<source_id>
source_id: source_ff_<hash>     # 关联的 source
kind: summary
source_type: ...
status: summarized
action_status: undecided|idea_extracted|plan_suggested
```

**正文**:按 source_type 选模板章节(一句话结论 / 主要内容 / 核心观点 / 方法框架...)。

### 03_Ideas/ —— idea 管理
| 文件 | 用途 |
|------|------|
| `idea_suggestions.md` | AI 抽取的 idea 候选(review 队列),status 改 accepted_* 后被 accept-ideas 移走 |
| `research_ideas.md` | 正式科研 idea list(用户确认后进入) |
| `productivity_ideas.md` | 正式效率 idea list |
| `archived_ideas.md` | 归档的 idea |

### 04_Plans/ —— plan / 计划
| 文件 | 用途 |
|------|------|
| `plan_suggestions.md` | AI 抽取的 plan 候选(review 队列) |
| `plan_<hash>.md` | 独立 plan 文件(accept 后生成,frontmatter 含 deadline,与 task 同模式) |

> v0.4.23 重构:不再按 weekly/monthly/someday 分桶。每条 plan 是独立文件,要么有 deadline 要么没有。

### 05_Projects/ —— 项目记录
`obsidian_kb_project.md`:本项目自身的进度记录。

### 90_Templates/ —— 模板
11 个模板文件,由 `kb.py init` 生成(内容硬编码在 `kb.py` 的 `TEMPLATES` 字典里):

| 模板 | 用途 |
|------|------|
| `source_note_template.md` | source note 骨架 |
| `summary_github.md` | GitHub repo 总结模板 |
| `summary_article.md` | 网页/微信文章总结模板 |
| `summary_video.md` | 视频/抖音总结模板 |
| `summary_gpt_chat.md` | GPT 对话总结模板 |
| `summary_manual.md` | 手动内容总结模板 |
| `idea_template.md` | 正式 idea 条目模板 |
| `idea_suggestion_template.md` | idea 候选模板 |
| `plan_suggestion_template.md` | plan 候选模板 |

> init 用 `if not exists` 保护,**不会覆盖用户已修改的模板**。
> v0.4.23:weekly/monthly 模板已从 init 移除(plan 不再分桶);旧 vault 里残留的 `weekly_template.md` / `monthly_template.md` 不再生成,故上表 9 个 + 2 个历史残留 = 磁盘共 11 个。

### 99_System/ —— 系统配置
| 文件 | 用途 |
|------|------|
| `schema.md` | 数据结构定义概要 |
| `prompt_library.md` | LLM prompt 沉淀(便于审计调优) |
| `processing_log.md` | 人工审计日志(机器日志在 .kb/logs/) |
| `settings.md` | 设置 |

### .kb/ —— 机器运行目录(gitignore 忽略)
| 路径 | 用途 |
|------|------|
| `state.json` | **核心状态索引**:所有 source 的元数据 + 阅读状态 |
| `raw_text/<id>.txt` | 抓取的网页原文 |
| `logs/kb.log` | 命令行操作日志 |
| `logs/web_backups/` | Web 改 status 时的备份 |
| `prompts/` | 手动模式生成的 prompt 文件 |
| `outputs/` | 预留(手动输出导入) |

---

## state.json 结构

```json
{
  "version": 1,
  "created_at": "2026-07-07",
  "sources": {
    "source_ff_<hash>": {
      "source_id": "source_ff_<hash>",
      "path": "01_Sources/<type>/<file>.md",
      "source_type": "wechat",
      "source_title": "...",
      "summary_path": "02_Summaries/.../...md",
      "metadata_source": "llm",
      "llm_model": "glm-4.7-flash",
      "created_at": "2026-07-08",
      "ingested_at": "2026-07-08",
      "reading_status": "to_read|reading|read",
      "read_later": false,
      "is_favorite": false,
      "last_read_at": null,
      "read_count": 0,
      "action_status": "undecided|plan_suggested",
      "tags": [],                         // 文章标签(双写到 summary frontmatter)
      "collection_ids": [],               // 所属收藏夹 id 列表(与 collections[].source_ids 双向同步)
      "detected_dates": []                // 正文识别出的日期候选(供日历推荐)
    }
  },
  "collections": {                         // 收藏夹: id → {name, source_ids}
    "<collection_id>": {
      "name": "...",
      "source_ids": ["source_ff_<hash>"]
    }
  }
}
```

---

## 数据流

```
用户粘贴 URL/正文 → 00_Inbox/inbox.md
        │
        ▼  ingest(抓取 + LLM 识别 metadata)
   01_Sources/<type>/source_*.md  +  .kb/raw_text/<id>.txt
        │
        ▼  make-prompts --auto(LLM 生成结构化 summary)
   02_Summaries/<type>/summary_*.md
        │
        ▼  extract-suggestions(LLM 抽取候选)
   03_Ideas/idea_suggestions.md  +  04_Plans/plan_suggestions.md
        │
        ▼  用户 review,改 status 为 accepted
        │
   ├─ accept-ideas →  03_Ideas/research_ideas.md 或 productivity_ideas.md
   └─ accept-plans →  04_Plans/plan_<hash>.md(独立文件,含 deadline)
```

**阅读追踪**:打开详情页 → state.json 的 `last_read_at` + `read_count` 更新 → `reading_status` 自动标 `read`

---

## init 如何创建这些目录

`python scripts/kb.py init` 执行时:
1. 创建全部目录(00_Inbox 到 99_System + .kb 子目录)
2. 写入 11 个模板(从代码 TEMPLATES 字典,`if not exists` 保护)
3. 创建空的 idea/plan 文件(带头部说明)
4. 创建 state.json 空骨架
5. 创建 .env.example / .gitignore / requirements.txt(若不存在)

已存在的文件/目录**跳过,绝不覆盖**。
