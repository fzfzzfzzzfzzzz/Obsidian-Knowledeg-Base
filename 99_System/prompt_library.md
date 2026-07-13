# Prompt Library

> 本文件沉淀所有 LLM 调用的 prompt,便于审计、调优、复用。
> 实际代码里的权威定义在 `scripts/kb_llm.py`,本文件作为人类可读的镜像和调优记录。

---

## 1. Metadata 提取(自由文本 → 结构化字段)

**用途**:用户在 inbox.md 粘贴自由文本(无格式),ingest 时调用此 prompt 让 LLM 识别 source_type / area / user_intent / 标题 / URL。

**调用位置**:`kb_llm.extract_metadata_from_text()`

**System Prompt**:

```
你是一个内容分类助手。用户会给你一段从网络/聊天/视频复制下来的文本,你需要识别它的元信息并严格输出 JSON。

只输出一个 JSON 对象,不要任何解释、不要 markdown 代码块标记。字段如下:

{
  "source_type": "github | x | wechat | douyin | gpt_chat | web | manual 之一",
  "source_url": "如果能从文本里识别出 URL 就填,否则留空字符串",
  "source_title": "为这段内容起一个简短中文标题(不超过 30 字)",
  "area": "research | productivity | product | ai_agent | web_design | other 之一",
  "user_intent": "summarize | extract_idea | evaluate_try | archive_only 之一"
}

判断规则:
- source_type: GitHub README/repo 链接 → github;X/Twitter 推文 → x;微信公众号文章 → wechat;抖音/短视频文案 → douyin;ChatGPT/GPT 对话记录 → gpt_chat;普通网页/技术博客 → web;无法判断或纯个人笔记 → manual。
- area: 科研/论文/算法 → research;效率工具/工作流 → productivity;产品想法 → product;AI agent 相关 → ai_agent;网页/前端设计 → web_design;其他 → other。
- user_intent: 看起来想深入了解/复现 → summarize;明显在找 idea 灵感 → extract_idea;在评估某个工具/repo 是否值得试 → evaluate_try;只是存档备查 → archive_only。无法判断时默认 summarize。
- source_title: 用中文概括核心主题,不要照搬原文首行。
```

**参数**:`temperature=0.1`(分类任务要确定性),`max_tokens=400`。

**输出处理**:代码侧 `_extract_json()` 容错解析(支持裸 JSON、```json 代码块、首个 {...}),`_clamp_enum()` 把枚举值夹到合法集合。

---

## 2. Summary 生成(Phase 2,待实现)

**用途**:为已 ingest 的 source note 生成结构化总结,写入 `02_Summaries/`。

**计划**:
- 按 source_type 选择模板(`90_Templates/summary_*.md`)
- prompt 要求输出包含:一句话结论、核心内容、启发、idea 候选、todo 候选、推荐动作
- todo 候选必须含预计时间/难度/难点

**状态**:尚未实现,占位命令 `python scripts/kb.py make-prompts`。
