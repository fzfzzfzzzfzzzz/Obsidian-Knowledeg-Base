# Agent Summary 操作手册

> 本文档供本地编程 Agent 使用。Agent 读完本文档后,能自主完成"为知识库里没 summary 的文章生成结构化总结"的全流程。
>
> **触发指令**:`读 AGENT_SUMMARIZE.md,把所有没 summary 的文章都总结了`

---

## 一、你要做什么

知识库里有若干篇文章(source),每篇有原文但部分还没有 summary(结构化总结)。你的任务是:

1. 找出所有**没有 summary** 的文章
2. 读取每篇的原文
3. 按**模板章节**生成详细的中文总结
4. 把总结写入指定的 summary 文件
5. 更新状态索引(state.json)

---

## 二、项目结构(关键路径)

```
D:\Obsidian\
  01_Sources/             文章原文(source note)
    <type>/               按来源类型分目录(wechat/github/web/x/...)
      source_*.md         每篇文章一个文件
  02_Summaries/           总结输出(你要写到这里)
    <type>/
      summary_*.md
  .kb/
    state.json            状态索引(你要更新)
    raw_text/             抓取的网页原文备份
```

---

## 三、详细操作步骤

### 第 1 步:读状态索引,找出没有 summary 的文章

读取 `D:\Obsidian\.kb\state.json`,结构如下:

```json
{
  "sources": {
    "source_ff_xxxxxxxx": {
      "source_id": "source_ff_xxxxxxxx",
      "path": "01_Sources/wechat/source_20260714_xxx.md",
      "source_type": "wechat",
      "source_title": "文章标题",
      "summary_path": "02_Summaries/...",   // 有这个字段 = 已有 summary
      ...
    }
  }
}
```

**判断逻辑**:
- `summary_path` 字段**存在且非空** → 已有 summary,**跳过**
- `summary_path` 字段**不存在或为空** → **需要生成 summary**

收集所有需要生成的 source_id 列表。

### 第 2 步:读取文章原文

对每个待处理的 source,读取它的 source note 文件(state.json 里的 `path` 字段):

```
D:\Obsidian\<path>
```

例如:`D:\Obsidian\01_Sources\wechat\source_20260714_waic前瞻.md`

source note 文件结构:
```markdown
---
(frontmatter 元数据,不用管)
---

## 元信息
...

## 原始内容

(这里是要总结的原文,从「## 原始内容」之后开始)
```

**提取原文**:取 `## 原始内容` 标题之后的全部文本。

### 第 3 步:按模板生成 summary

根据 source_type 选择章节模板:

#### wechat / web 类型
```
# 一句话结论
# 文章主要讲什么
# 核心观点
# 方法 / 框架 / 实现路径
# 相关链接
```

#### github 类型
```
# 一句话结论
# 这个 repo 是什么
# 它解决的问题
# 核心功能
# 技术路线 / 架构
# 安装与运行难度
# 依赖条件
# 值得尝试的地方
# 风险 / 局限
```

#### gpt_chat 类型
```
# 一句话结论
# 这段对话讨论了什么
# 已经形成的结论
# 仍然不确定的问题
# 可以沉淀为长期知识的内容
# 需要后续追问 / 验证的地方
```

#### douyin 类型
```
# 一句话结论
# 视频内容概括
# 关键信息点
# 展示的工具 / 方法 / 项目
# 是否值得进一步验证
```

#### manual 类型(兜底)
```
# 一句话结论
# 主要内容
```

### 第 4 步:总结规则(非常重要)

**核心原则:写详细笔记,不是简短概括。**

1. 每个章节标题用 markdown `#` 一级标题,顺序不变
2. 「一句话结论」必须是 1 句话
3. **保留原文的关键事实、数据、项目名、步骤、论据**。不要压缩成抽象概括,不要用「介绍了几个工具」这种空话
4. **列举类内容(多个项目/步骤/特性)要逐项保留**,带上原文给出的具体数据(star 数、参数、价格等)。每个项目至少写 2-3 句,不要只写一个名字
5. **summary 长度至少达到原文的 40-50%**。宁可多写也不要漏掉信息
6. 只过滤:广告、网站导航、页脚版权、重复段落、无关闲聊
7. 不要瞎编原文没有的内容。某个章节原文没涉及就写「原文未涉及」
8. 全程中文(专有名词/代码可保留英文),客观克制,不要营销腔
9. **链接必须完整保留**:原文里的所有 URL 用 `[文字](完整URL)` 写进 summary,绝对不要省略

### 第 5 步:写入 summary 文件

文件路径:`D:\Obsidian\02_Summaries\<source_type>\summary_<日期>_<标题slug>.md`

(看 `02_Summaries/<source_type>/` 目录下已有文件的命名风格,保持一致)

文件内容格式:
```markdown
---
id: summary_<source_id>
source_id: <source_id>
kind: summary
source_type: <source_type>
source_title: <标题>
area: <area,从 state.json 读>
created_at: <created_at,从 state.json 读>
summarized_at: <今天日期 YYYY-MM-DD>
status: summarized
action_status: undecided
priority: P2
confidence: medium
idea_extracted: false
todo_extracted: false
related_ideas: []
related_todos: []
tags: []
---

(你生成的 summary 正文)
```

### 第 6 步:更新 state.json

为刚生成 summary 的 source 记录,添加/更新以下字段:

```json
{
  "summary_path": "02_Summaries/<type>/<filename>.md",
  "action_status": "undecided"
}
```

同时更新 source note 文件(`01_Sources/...`)的 frontmatter:
- `summary_location:` 字段填上 summary 的相对路径
- `status:` 改为 `summarized`

### 第 7 步:报告结果

处理完所有文章后,输出:
```
✓ 已生成 summary:N 篇
  - source_ff_xxx: 标题(summary XXXX 字)
  - source_ff_yyy: 标题(summary XXXX 字)
✗ 失败:M 篇(如有)
  - source_ff_zzz: 失败原因
```

---

## 四、注意事项

1. **不要覆盖已有 summary**:如果 `summary_path` 已存在,跳过
2. **不要修改原文**(`01_Sources/` 里的文件正文),只改 frontmatter 的 summary_location 和 status
3. **文件编码统一 UTF-8**
4. **路径用相对路径**(相对 `D:\Obsidian\`)
5. **state.json 修改后要格式化保存**(JSON, indent=2, ensure_ascii=False)
6. 如果某篇文章原文为空或只有 URL(没有正文),跳过并报告
7. 一次处理多篇时,逐篇完成,单篇失败不影响其他

---

## 五、快速验证

处理完后可以跑:
```bash
python scripts/kb.py status
```
确认 `Summaries generated` 数量增加。

或访问 `http://127.0.0.1:5173` 看首页是否出现新文章。
