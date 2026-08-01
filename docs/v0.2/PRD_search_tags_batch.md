# B. 产品需求文档 PRD

# 个人知识库 v1.0 功能补充 PRD：搜索、标签、批量管理

## 1. 背景

当前个人知识库已经具备基础闭环：内容采集、AI 总结、idea/todo 候选抽取、用户 review、阅读管理、稍后阅读、最近阅读、收藏夹等功能。

随着文章数量增加，当前产品会逐渐出现三个问题：

1. 文章变多后，用户很难快速找回某篇文章。
2. 只能依靠 source_type 和 area 粗略分类，无法按细粒度主题整理。
3. 未读 / 已读文章数量增加后，单篇操作效率较低。

因此，v1.0 需要优先补充三个能力：

1. 全文搜索 + 筛选
2. 标签系统
3. 批量管理

本版本目标不是做复杂知识图谱，也不是做完整文献管理系统，而是让当前知识库在文章数量达到 100–1000 篇时仍然可用、可找回、可整理、可批量处理。

---

## 2. 产品目标

### 2.1 核心目标

让用户在文章数量增加后，仍然可以：

1. 快速找到文章
2. 按主题整理文章
3. 批量处理未读 / 已读文章

### 2.2 用户场景

用户平时会阅读很多技术文章、GitHub repo、网页、推文、视频文案或 AI 对话内容。用户希望把这些内容沉淀为 summary，并在之后继续阅读、查找、收藏、归档、提炼 idea/todo。

典型场景：

1. 用户记得之前读过一篇关于 agent benchmark 的文章，但忘记在哪里，希望通过关键词搜索找到。
2. 用户想给几篇文章加上 `agent`、`benchmark`、`tool-use` 等标签，方便之后筛选。
3. 用户想把一批已读文章归档。
4. 用户想把一批未读文章加入收藏。
5. 用户想对一批已有 summary 的文章抽取 idea/todo。
6. 用户想通过标签快速找到某个主题下的文章。

---

## 3. 功能范围

本版本包含：

1. Search 页面
2. 搜索 + 筛选
3. 轻量 tags 系统
4. AI 推荐 tags
5. 未读 / 已读页面批量管理
6. All Articles 页面

本版本不包含：

1. 语义搜索
2. embedding 检索
3. 模糊搜索
4. 搜索词高亮
5. 标签层级
6. 标签颜色
7. 标签管理页
8. 标签重命名 / 合并
9. 复杂知识图谱
10. 多用户权限
11. 云同步

---

## 4. 功能一：全文搜索 + 筛选

### 4.1 搜索入口

侧边栏新增：

- Search

首页可以放一个搜索框，但首页不展示搜索结果。用户在首页搜索后，跳转到 Search 页面。

### 4.2 搜索范围

第一版只搜索：

1. 文章标题 title / source_title
2. summary 内容
3. tags 标签

第一版不搜索：

1. raw_text 原文
2. source note 全文
3. idea/todo 候选
4. 评论或聊天记录

### 4.3 搜索方式

第一版搜索方式为普通关键词搜索：

- 大小写不敏感
- 包含关键词即可命中
- 不做语义理解
- 不做模糊匹配
- 不做高亮

### 4.4 搜索结果

搜索结果只显示已有 summary 的文章。

搜索结果使用卡片视图。卡片字段根据已有数据动态展示，推荐包括：

- 标题
- summary 摘要
- tags
- source_type
- area
- reading_status
- 收藏状态
- last_read_at
- read_count
- 操作按钮

点击卡片进入文章详情页。

### 4.5 筛选条件

Search 页面支持以下筛选：

1. reading_status：to_read / reading / read / archived
2. is_favorite：是否收藏
3. source_type
4. tags
5. has_summary：是否已有 summary

搜索和筛选可以组合使用：

1. 只输入关键词
2. 只使用筛选
3. 关键词 + 筛选同时使用

---

## 5. 功能二：标签系统

### 5.1 标签定位

标签用于细粒度主题整理，不替代 source_type 和 area。

source_type 表示来源类型，例如 github、wechat、web、x、manual。

area 表示大领域。

tags 表示更细的主题，例如：

- agent
- benchmark
- tool-use
- trajectory
- prompt-compression
- 心理健康
- ADHD

### 5.2 标签规则

第一版 tags 规则：

1. 一篇文章可以有多个标签。
2. 标签支持中文和英文。
3. 标签不做层级。
4. 标签不设置颜色。
5. 不区分系统标签和用户标签。
6. 不做标签管理页。
7. 不做标签重命名和合并。
8. 不做自动补全。

### 5.3 标签入口

标签主要在文章详情页管理。

文章详情页需要支持：

1. 显示当前 tags
2. 手动添加 tag
3. 删除当前文章中的某个 tag
4. 点击按钮让 AI 推荐 tags

文章卡片只展示 tags，不直接编辑 tags。

批量管理中支持批量添加 tags。

### 5.4 AI 推荐标签

文章详情页提供“AI 推荐标签”按钮。

点击后，系统基于当前 summary 自动生成 3–5 个 tags。

生成后可以直接写入文章，用户之后可以手动删除或继续添加。

AI 推荐 tags 不需要单独进入 review 队列，因为 tags 属于轻量 metadata，用户可以随时修改。

### 5.5 标签存储

tags 应写入 summary markdown frontmatter，并同步到 state.json。

推荐 summary frontmatter：

```yaml
tags: []
```

推荐 state.json source 记录新增：

```json
{
  "tags": [],
  "has_summary": true
}
```

数据原则：

1. Markdown / frontmatter 是长期主数据。
2. state.json 是状态索引和 Web 读取加速。
3. 如果 state.json 和 Markdown frontmatter 不一致，rebuild-index 时以 Markdown frontmatter 为准。
4. 旧 summary 没有 tags 字段时不能报错。
5. 用户添加 tags 或 AI 生成 tags 后，再补充 tags 字段。

---

## 6. 功能三：批量管理

### 6.1 批量管理入口

第一版批量管理主要放在：

1. 未读列表
2. 已读列表

第一版不强制在收藏夹、最近阅读、Search 页面实现批量管理。

### 6.2 选择交互

每张文章卡片左上角增加 checkbox。

当用户勾选至少一篇文章后，页面显示批量操作栏。

第一版只对当前选中的文章执行操作，不做“选择全部搜索结果”。

### 6.3 批量操作范围

第一版支持：

1. 批量归档
2. 批量删除
3. 批量收藏
4. 批量取消收藏
5. 批量添加标签
6. 批量生成 summary
7. 批量抽取 idea/todo

### 6.4 批量归档

批量归档行为：

1. 将 reading_status 改为 archived。
2. 归档后文章从当前未读 / 已读列表中消失。
3. 不删除 source、summary 或 raw 文件。

### 6.5 批量删除

批量删除行为：

1. 必须二次确认。
2. 删除前自动备份 state.json 和相关文件。
3. 沿用现有单篇删除逻辑。
4. 删除 source note、summary、raw、state 记录，以及相关候选记录。
5. 如果部分失败，不回滚已经成功的文章。
6. 操作完成后显示成功数量、失败数量和失败项。

### 6.6 批量收藏 / 取消收藏

批量收藏：

- 将 is_favorite 改为 true。
- 不改变 reading_status。
- 文章仍留在原列表。

批量取消收藏：

- 将 is_favorite 改为 false。
- 不改变 reading_status。
- 文章仍留在原列表。

### 6.7 批量添加标签

批量添加标签行为：

1. 追加新 tags。
2. 不覆盖旧 tags。
3. 自动去重。
4. 同步写入 summary frontmatter 和 state.json。

### 6.8 批量生成 summary

批量生成 summary 行为：

1. 默认跳过已有 summary 的文章。
2. 只处理没有 summary 的文章。
3. 不重复生成已有 summary。
4. 如果未读 / 已读页面只展示有 summary 的文章，则该功能可以先保留为后端能力，或后续放到 All Articles 页面。

### 6.9 批量抽取 idea/todo

批量抽取 idea/todo 行为：

1. 只对已有 summary 的文章执行。
2. 没有 summary 的文章自动跳过。
3. 操作结果提示成功数量、失败数量、跳过数量。

---

## 7. All Articles 页面

侧边栏新增：

- All Articles

All Articles 页面用于浏览所有文章，最好包括没有 summary 的 source。

第一版 All Articles 可以先作为完整文章列表，不强制实现复杂批量管理。

每篇卡片建议展示：

1. 标题
2. source_type
3. reading_status
4. 是否已有 summary
5. tags
6. 是否收藏
7. created_at / updated_at
8. 操作入口

点击文章进入文章详情页。

---

## 8. 首页要求

首页 Dashboard 保持轻量。

首页只展示：

1. 未读 / 已读总结
2. 阅读状态概览
3. 可选搜索框

首页不展示：

1. 最近阅读列表
2. 收藏夹列表
3. 搜索结果
4. All Articles 列表

最近阅读和收藏夹继续通过侧边栏进入。

---

## 9. 非功能性要求

### 9.1 数据安全

必须保证：

1. 不误删文件。
2. 不破坏 Markdown frontmatter。
3. 不破坏 Obsidian 兼容性。
4. 批量删除前自动备份。
5. 旧文件缺少 tags 字段时不报错。

### 9.2 兼容性

不能破坏已有功能：

1. ingest
2. make-prompts
3. extract-suggestions
4. accept-ideas
5. accept-todos
6. 最近阅读
7. 收藏夹
8. 文章详情页
9. idea/todo review 页面

### 9.3 稳定性

批量操作中如果部分失败：

1. 成功项保留成功结果。
2. 失败项单独列出。
3. 不做整体回滚。
4. 页面必须显示清楚结果。

---

## 10. 验收标准

本版本完成后，应满足以下标准：

1. 用户可以在 Search 页面搜索 title、summary、tags。
2. 用户可以按 reading_status、is_favorite、source_type、tags、has_summary 筛选。
3. 用户可以只搜索、只筛选，或搜索 + 筛选组合使用。
4. 用户可以在文章详情页看到 tags。
5. 用户可以手动添加和删除当前文章 tags。
6. 用户可以让 AI 为文章推荐 3–5 个 tags。
7. 用户可以在未读 / 已读页面勾选多篇文章。
8. 用户可以批量归档、删除、收藏、取消收藏、添加标签、抽取 idea/todo。
9. 批量删除有二次确认和备份。
10. 批量操作后显示成功数量、失败数量和失败项。
11. 首页仍然只展示未读 / 已读概览，不变成文章列表聚合页。
12. 现有采集、总结、review、最近阅读、收藏夹功能不被破坏。
