# PRD v0.1 —— Obsidian 本地知识库

> 版本:v0.1(首个可用版本)
> 状态:已发布
> 日期:2026-07-14

---

## 一、版本目标

搭建一个 local-first 的 Obsidian 知识库,实现"看到资料 → 结构化总结 → 提炼 idea/todo → 用户确认 → 进入正式计划"的完整闭环,并提供 Web 阅读前端。

## 二、核心功能

### 2.1 内容采集(ingest)
- 自由文本投稿:直接粘贴 URL 或正文,无需格式
- 网页自动抓取:URL 自动抓取正文(requests + HTML 解析),最长 50000 字符
- LLM 智能识别:自动识别 source_type/area/title/intent(glm-4.7-flash)
- 多来源支持:微信/X/GitHub/抖音/GPT 对话/普通网页/纯文本
- 幂等去重:基于正文 SHA1,重复 ingest 不重复创建
- 抓取失败降级:标记 url_only,summary 生成时跳过避免瞎编

### 2.2 AI 总结(make-prompts)
- LLM 按模板章节生成结构化中文笔记
- 详细保留模式:保留事实/数据/项目名/链接,不压缩成空话
- 按类型选模板:github/web/wechat/douyin/gpt_chat/manual 各有专属章节
- 两种模式:--auto 直调 LLM;默认生成 prompt 文件供手动粘贴
- 网站一键生成:投稿页勾选"自动生成 summary"

### 2.3 Idea / Todo 候选抽取(extract-suggestions)
- 从 summary 抽 idea 候选(含领域/优先级/可行性/新颖度)
- 从 summary 抽 todo 候选(含推荐计划/时间/难度/验收标准)
- 宁缺毋滥:无可转化内容时返回空
- 进 review 队列,不直接进正式清单

### 2.4 Review 确认(accept-ideas / accept-todos)
- 用户改 status 为 accepted_*,脚本移动到正式清单
- 自动创建 weekly/monthly 计划文件
- 不覆盖正式内容,只 append;原 suggestion 标记 moved 保留追溯

### 2.5 Web 阅读前端(serve)
- 仪表盘:未读/已读/总计/进度统计 + 稍后读列表
- 投稿页:网页直接粘贴内容,多文本框动态添加
- 最近阅读:自动追踪打开详情,按时间倒序最多 30 篇
- 收藏夹:手动收藏
- 文章详情:summary 渲染,无 summary 时回退显示原文
- 删除:彻底删除文章(source+summary+raw+state+关联候选)
- idea/todo review 页面:卡片+status 徽章+可直接改 status

## 三、技术方案

| 层 | 技术 |
|----|------|
| LLM | 智谱 GLM-4.7-flash(免费,200K 上下文,思考模型) |
| 网页抓取 | requests + 自写 HTML 解析器 |
| CLI | Python 标准库(argparse) |
| Web 后端 | FastAPI + uvicorn |
| Web 前端 | 原生 JS + Jinja2 模板 + CSS |
| 数据 | Markdown 文件(主)+ state.json(状态索引) |

## 四、不在本版本范围

- 全文搜索
- AI 深度讨论(针对 summary 继续追问)
- 知识关联图谱
- 多收藏夹分组
- 标签系统
- 移动端优化
- 多用户/同步

## 五、验收标准

- [x] 投稿 URL → 自动抓取 + 识别 + 生成 source note
- [x] 一键生成 summary(详细保留,链接完整)
- [x] 从 summary 抽取 idea/todo 候选
- [x] 用户 review 后 accept 进入正式清单
- [x] Web 前端可阅读/投稿/收藏/删除
- [x] 代码与 vault 内容分离,可上传 GitHub
