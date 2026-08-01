# v0.4.13 PRD:Idea / Todo 简化 + Web 新建 idea

> 日期:2026-07-23
> 上一版:v0.4.10(见 `docs/v0.4.10/`)
> 性质:功能简化 + 新功能(Web 新建 idea)

## 0. 文档定位

本 PRD 事后补写,记录 idea/todo 简化的**设计动机**与 Web 新建 idea 的**接口决策**。
涵盖 v0.4.11(idea 简化 + 新建 idea + completed_at)与 v0.4.13(todo 简化 + 抽取简化)。
359 passed(346 → 359,+8)。

## 1. 动机:为什么要简化

### 1.1 卡片信息过载

v0.4.10 之前,idea/todo 卡片堆叠了大量字段:

```
[标题]
[正文预览...]
estimated_time: 2-4h
priority: P2
difficulty: medium
recommended_area: 研究
feasibility: medium
novelty: low
[标签1] [标签2]
[接受] [拒绝]
```

问题:
- **estimated_time 多是伪造**:v0.4.7 刚修过 LLM 没返回时硬兜底 `"2-4h"` 的污染问题,
  但即使不兜底,LLM 估的 estimated_time 质量也很低(它没真正理解任务工作量)
- **priority / difficulty / feasibility / novelty 不可复现**:同份 summary 不同时间跑,
  LLM 给的值不稳定(ROADMAP P1-#5 记录的问题),用户无法据此排序
- **recommended_area 多是兜底**:LLM 倾向给通用值,区分度低

真正影响「这个 idea/todo 要不要接受」决策的,是**标题本身**。其他字段在卡片阶段是噪声。

### 1.2 决策:砍掉,而非修补

ROADMAP P1-#5 原计划「补量化判定标准」让 LLM 抽取的 priority/novelty 可复现。
但评估后发现:即便有量化标准,LLM 对「新颖性」「可行性」的判断质量仍不足以支撑排序,
投入产出比低。**决策:主动放弃该方向,只保留标题**。

这是「信息收敛」:去掉低价值/不可靠字段,让真正有价值的标题和来源凸显。

### 1.3 卡片、抽取、格式三层同步

简化不是只改卡片显示。如果只改卡片、文件里还写 estimated_time,就是死字段(没人显示、
没人消费),徒增数据不一致。所以三层同步:
- **卡片**:只显示标题 + 操作
- **抽取**:LLM 只返回 title(prompt 也只要求 title,省 token、更稳定)
- **格式**:文件只写 title + id + status + source

## 2. Web 新建 idea 决策

### 2.1 为什么需要凭空创建

idea 原本只能从文章 summary 抽取(source → idea 链路)。但灵感常常不来自任何文章 ——
洗澡时、走路时、和别人聊天时冒出来的想法,需要立刻记下。如果强制走「先投稿一篇文章 →
生成 summary → 抽取 idea」,链路太长,灵感早忘了。

### 2.2 accepted_general 状态

抽取的 idea 进 review 队列(`pending_review`),因为 LLM 抽取质量不稳定,需要人审。
但用户**主动创建**的 idea 不需要 review —— 用户自己写的,本来就是审过的。

决策:新增 `accepted_general` 状态,Web 新建的 idea 直接进正式 `general_ideas.md` 清单,
跳过 review。状态语义清晰:
- `pending_review`:LLM 抽取,需人审
- `accepted_general`:用户主动创建,直接落地

## 3. completed_at 字段的归属说明

`completed_at` 是任务 frontmatter 字段,本属 v0.4.10 任务系统。但它归到本份(v0.4.13)有两个理由:

1. **存在理由**:它唯一的消费方是工作台「本周完成数」统计(`services/cards.py:378`),
   与本版的「工作台数据精简」主题同源
2. **时间线**:它随工作台概览的「本周完成数」一起落地,与 idea 简化同期

生命周期决策(为什么不用 updated_at 代替):
- 首次 done → 写入;重复 done → **不覆盖**;重新激活 → **清空**
- 若用 updated_at,任何编辑都会刷新,「本周完成数」会把「本周编辑过的已完成任务」
  错算成「本周完成的任务」,统计失真

## 4. 不在本次范围

- **maturity 状态机**:正式 idea 的 maturity 固定 `spark`,从 spark → exploring → validated
  的流转未实现
- **todo 的 Web 新建**:只做了 idea 的 Web 新建,todo 仍只能从文章抽取
- **抽取字段恢复**:ROADMAP P1-#5 被「简化掉」而非解决,属于主动放弃
