# Obsidian 本地知识库

> Local-first Obsidian knowledge base —— 把看到的前沿技术内容整理成结构化总结,提炼 idea,生成 todo 建议。
> 当前版本:**MVP Phase 0 + Phase 1**(目录结构 + Inbox 解析器,**已接入智谱 GLM API**)。

完整设计见 [`obsidian_kb_codex_implementation_plan.md`](./obsidian_kb_codex_implementation_plan.md)。

---

## 快速上手

环境要求:Python 3.8+(本机已验证 3.11.9)。

### 1. 安装依赖

```bash
pip install -r requirements.txt   # 只需 requests
```

### 2. 配置 API key

```bash
# 复制模板
copy .env.example .env     # Windows
# cp .env.example .env     # Mac/Linux
```

编辑 `.env`,填入智谱 API key(在 https://open.bigmodel.cn 控制台获取):

```
ZHIPU_API_KEY=你的key
KB_LLM_MODEL=glm-4-flash        # 免费模型
```

> `.env` 已被 `.gitignore` 忽略,不会入库。代码只读取环境变量,日志只显示 key 前 4 位。

### 3. 初始化 + 测试

```bash
python scripts/kb.py init        # 创建目录结构、模板、空文件
python scripts/kb.py llm-test    # 验证 API 连通性
```

### 4. 录入内容(无需任何格式!)

打开 `00_Inbox/inbox.md`,**直接粘贴正文**即可。多个内容之间用 `---` 分隔。

```markdown
# Inbox

（直接粘贴你看到的内容,可以是文章正文、GitHub README、GPT 对话、抖音文案……）

我和 GPT 讨论了本地知识库的架构,核心结论是 local-first...

---

https://github.com/langchain-ai/langgraph

这个 repo 是图式 agent 编排框架,我在评估是否值得用...

---

抖音上看到 Whisper 本地部署教程,博主用 faster-whisper 跑 large-v3...
```

### 5. 处理 inbox

```bash
python scripts/kb.py ingest     # LLM 自动识别来源/类型/意图,生成 source note
python scripts/kb.py status     # 查看知识库状态
```

ingest 时 LLM 会为每段内容自动识别:
- `source_type`(github / x / wechat / douyin / gpt_chat / web / manual)
- `area`(research / productivity / ai_agent / ...)
- `user_intent`(summarize / evaluate_try / extract_idea / archive_only)
- `source_title`(中文标题)、`source_url`(从正文提取)

---

## 两种录入模式

| 模式 | 格式 | 是否调 LLM | 适用场景 |
|------|------|-----------|---------|
| **自由文本(推荐)** | 直接粘贴正文,`---` 分隔 | ✅ 自动识别 metadata | 日常使用,最省事 |
| **结构化 KB_ITEM** | `<!-- KB_ITEM_START -->` 包裹,内嵌 metadata | ❌ 不调 LLM | 离线、或想精确控制分类 |

结构化模式示例见 plan.md 第 4 节。两种模式可混用:inbox 里有 KB_ITEM 标记就走结构化,否则走自由文本。

---

## 命令一览

| 命令 | 状态 | 作用 |
|------|------|------|
| `python scripts/kb.py init` | ✅ | 创建全部目录、模板、空文件、`state.json` |
| `python scripts/kb.py llm-test` | ✅ | 测试 API 连通性,显示配置摘要和 token 用量 |
| `python scripts/kb.py ingest` | ✅ | 解析 inbox,生成 source note(LLM 或离线) |
| `python scripts/kb.py ingest --no-llm` | ✅ | 离线模式,只接受 KB_ITEM 格式 |
| `python scripts/kb.py status` | ✅ | 输出 pending inbox / sources / 待 review 数量 |
| `python scripts/kb.py make-prompts` | ⏳ Phase 2 | 生成总结 prompt |
| `python scripts/kb.py accept-ideas` | ⏳ Phase 4 | 移动 accepted idea |
| `python scripts/kb.py accept-todos` | ⏳ Phase 4 | 移动 accepted todo |

---

## 降级与安全

- **无 API key**:自由文本 item 友好跳过,原文保留在 inbox,不崩溃;`llm-test` 明确提示配置
- **LLM 调用失败**(网络/限流/输出异常):该 item 跳过并报错,原文保留,不中断整个 ingest
- **幂等性**:基于正文 SHA1 去重。重复 ingest 相同内容 → 命中即跳过,**自由文本模式不会重复调 LLM**(省 token)
- **密钥安全**:`.env` 不入库;代码只读环境变量;日志只显示 key 前 4 位
- **原文不丢失**:处理过的 item 移动到 `processed.md` 留底,绝不删除

---

## 目录结构

```
00_Inbox/        用户输入区(inbox.md 主入口,processed.md 留底)
01_Sources/      ingest 生成的 source note,按来源类型分子目录
02_Summaries/    总结输出区(Phase 2+ 填充)
03_Ideas/        research_ideas / productivity_ideas / idea_suggestions(review 队列)
04_Plans/        Weekly/ Monthly/ todo_suggestions.md / completed_todos.md
05_Projects/     项目自身的进度记录
90_Templates/    11 个模板
99_System/       schema / prompt_library / processing_log / settings
.kb/             机器运行目录(state.json / raw_text / logs,已被 .gitignore 忽略)
scripts/         kb.py(CLI) + kb_llm.py(LLM 封装)
.env             API key 配置(不入库)
```

---

## 技术细节

- **LLM 提供方**:智谱 GLM(`glm-4-flash` 免费模型),OpenAI 兼容接口,`requests` 直调
- **状态层**:`.kb/state.json`(JSON),每个 source 记录 `metadata_source`(llm/inline)、`llm_model`
- **source_id**:
  - 自由文本模式 `source_ff_<hash>`(稳定,跨天幂等)
  - KB_ITEM 模式 `source_<YYYYMMDD>_<hash>`(向后兼容)
- **跨平台**:pathlib 相对路径,显式 UTF-8 编码,Windows 用 `python` 命令

---

## 下一阶段(待实现)

- **Phase 2** `make-prompts`:为 source 生成总结 prompt,调 LLM 输出结构化 summary
- **Phase 3** manual output import:summary/idea/todo 写回对应目录
- **Phase 4** `accept-ideas` / `accept-todos`:用户改 status 后自动 append 到正式计划

详见 plan.md 第 15、16 节。
