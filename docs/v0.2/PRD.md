# A. 给 Codex / Agent 的完整实现 Prompt

我想在当前个人知识库项目中实现三个功能：**全文搜索 + 筛选、标签系统、批量管理**。请先检查现有项目代码结构、数据结构、路由、模板、状态管理逻辑，然后在尽量少改动现有架构的基础上实现。

当前产品是一个 Local-first 的个人知识库，Markdown 文件是主数据层，`state.json` 是状态索引，Web 前端使用 FastAPI + Jinja2 + 原生 JS，CLI 已经有 `ingest`、`make-prompts`、`extract-suggestions`、`accept-ideas`、`accept-todos`、`serve` 等功能。请不要重构整个项目，不要引入复杂数据库系统，不要破坏现有 Markdown / Obsidian 兼容性。

这次只实现三个核心功能：

1. 全文搜索 + 筛选
2. 标签系统
3. 批量管理

目标是：当文章数量增加后，用户可以快速找回文章、按主题整理文章，并批量处理未读 / 已读文章。

---

## 一、全文搜索 + 筛选

请新增一个 `Search` 页面，并在侧边栏加入 `Search` 入口。首页可以放一个搜索框，但首页不要展示搜索结果。首页搜索框提交后跳转到 `Search` 页面。

第一版搜索范围只包括三类内容：

1. 文章标题 `title` / `source_title`
2. `summary` 内容
3. `tags` 标签

第一版不要搜索 `raw_text`，不要搜索 source 原文，不要搜索 idea/todo 候选，不做 embedding，不做语义搜索，不做模糊搜索，不做搜索词高亮。

搜索方式要求：

- 普通关键词搜索
- 大小写不敏感
- 只要包含关键词即可命中
- 第一版按相关性排序
- 搜索结果只展示已有 summary 的文章
- 点击搜索结果进入现有文章详情页

搜索结果使用卡片视图展示。卡片上已有的信息尽量展示，没有的字段不要报错。建议展示：

- 标题
- summary 摘要或 summary 开头内容
- tags
- source_type
- area
- reading_status
- is_favorite
- last_read_at
- read_count
- 操作按钮

Search 页面需要同时支持关键词搜索和筛选：

- 可以只输入关键词搜索
- 可以不输入关键词，只通过筛选浏览
- 可以关键词 + 筛选组合使用

第一版筛选条件包括：

1. `reading_status`: `to_read` / `reading` / `read` / `archived`
2. 是否收藏 `is_favorite`
3. `source_type`
4. `tags`
5. 是否已有 `summary`

---

## 二、标签系统

请实现轻量标签系统。标签 `tags` 支持中文和英文，一篇文章可以有多个标签。

第一版需要支持：

1. AI 自动生成 3–5 个标签
2. 用户手动添加标签
3. 用户从文章详情页删除当前文章的某个标签
4. 搜索和筛选都可以使用 tags
5. 批量管理中可以批量添加 tags

第一版不做：

- 标签层级
- 标签颜色
- 标签管理页
- 标签重命名
- 标签合并
- 标签自动补全
- 系统标签 / 用户标签分开管理

标签主要在文章详情页管理。文章详情页需要展示当前 tags，并支持手动添加 tag、删除当前文章的某个 tag。卡片上只展示 tags，不需要直接编辑 tags。批量管理中需要支持批量添加 tags。

请支持 AI 推荐标签功能。用户可以在文章详情页点击“AI 推荐标签”，系统基于当前 summary 自动生成 3–5 个 tags。生成后可以直接写入文章，用户之后可以手动删除或继续添加。

标签存储方式请遵循 Local-first 原则：

- tags 写入 summary markdown 的 frontmatter
- 同时同步到 state.json
- Markdown / frontmatter 是长期主数据
- state.json 用于列表、筛选和搜索加速
- 如果 state.json 和 Markdown frontmatter 不一致，后续 rebuild-index 时应以 Markdown frontmatter 为准重建 state

如果某篇 summary 没有 tags 字段，页面显示“暂无标签”即可，不要报错。用户添加标签或 AI 生成标签后，再补充 tags 字段。

建议在 `state.json` 的每个 source 记录中增加：

```json
{
  "tags": [],
  "has_summary": true
}
```

建议在 summary markdown frontmatter 中增加：

```yaml
tags: []
```

注意兼容旧文件。旧 summary 没有 tags 字段时不能报错。

---

## 三、批量管理

请在未读列表和已读列表中实现批量管理。第一版不要求在收藏夹、最近阅读、Search 页面全部实现批量操作。

批量选择方式：

- 每张文章卡片左上角增加 checkbox
- 用户勾选至少一篇文章后，页面出现批量操作栏
- 第一版只对当前选中的文章执行操作
- 不做“选择全部搜索结果”

第一版批量操作包括：

1. 批量归档
2. 批量删除
3. 批量收藏
4. 批量取消收藏
5. 批量添加标签
6. 批量生成 summary
7. 批量抽取 idea/todo

批量添加标签时：

- 新标签追加到已有 tags 中
- 不覆盖旧 tags
- 自动去重

批量归档时：

- 将 `reading_status` 改为 `archived`
- 归档后文章应从当前未读 / 已读列表中消失

批量收藏 / 取消收藏时：

- 只修改 `is_favorite`
- 不改变 `reading_status`
- 文章仍保留在原列表

批量生成 summary 时：

- 默认跳过已经有 summary 的文章
- 只处理没有 summary 的文章
- 如果当前未读 / 已读页面只展示已有 summary 的文章，则可以先保留后端能力，或放到 All Articles 页面后续使用
- 不要重复生成已有 summary

批量抽取 idea/todo 时：

- 只对已有 summary 的文章执行
- 没有 summary 的文章自动跳过
- 操作结果中提示跳过数量

批量删除时：

- 必须二次确认
- 删除前需要自动备份 state.json 和相关将被修改 / 删除的文件
- 删除逻辑可以沿用现有单篇删除逻辑：删除 source note、summary、raw、state 记录，以及相关候选记录
- 如果部分文章失败，不要回滚已经成功的文章，但必须显示成功数量、失败数量和失败项

---

## 四、All Articles 页面

请新增 `All Articles` 页面，并在侧边栏加入 `All Articles` 入口。

All Articles 页面用于浏览所有文章，最好包括没有 summary 的 source。这个页面第一版可以先作为完整文章列表，不强制实现复杂批量管理。未来它可以承载批量生成 summary。

All Articles 页面文章卡片需要明确标记：

- 是否已有 summary
- reading_status
- source_type
- tags
- 是否收藏

点击文章卡片后进入文章详情页。

---

## 五、首页要求

首页 Dashboard 继续保持轻量。

首页只展示：

- 未读 / 已读总结
- 阅读状态概览
- 可选：搜索框

首页不要展示：

- 搜索结果
- 最近阅读列表
- 收藏夹列表
- All Articles 列表

最近阅读和收藏夹仍然通过侧边栏独立页面进入。

---

## 六、搜索和索引实现建议

搜索索引具体实现可以根据现有项目选择。优先选择简单、稳定、少依赖的方案。可以使用 `search_index.json`，也可以使用 SQLite FTS，但不要引入过重的系统。

最低要求：

- 能搜索 title / summary / tags
- 能按 reading_status、is_favorite、source_type、tags、has_summary 筛选
- 新增、删除、编辑 tags 后，搜索结果能同步更新
- 缺少字段时不报错

建议预留或实现 `rebuild-index` 能力，用于从 Markdown frontmatter 重建 state.json 中的 tags、summary 状态和搜索索引。

---

## 七、稳定性要求

请优先保证：

- 不误删文件
- 不破坏 frontmatter
- 不破坏已有 Obsidian Markdown 结构
- 不破坏已有 ingest、summary 生成、idea/todo review、最近阅读、收藏夹功能
- 兼容旧数据
- 缺少 tags、summary_path、last_read_at、read_count 等字段时页面不报错

---

## 八、完成标准

实现完成后，需要满足：

1. 用户能在 Search 页面通过关键词找到标题、summary 或 tags 命中的文章。
2. 用户能通过 reading_status、收藏状态、source_type、tags、是否已有 summary 进行筛选。
3. 用户能在文章详情页看到、添加、删除 tags。
4. 用户能让 AI 为一篇文章推荐 3–5 个 tags。
5. 用户能在未读 / 已读页面勾选多篇文章，并批量归档、删除、收藏、取消收藏、添加标签、抽取 idea/todo。
6. 批量删除有二次确认和备份。
7. 批量操作后页面显示成功数量和失败数量。
8. 如果部分失败，需要列出失败项。
9. 首页仍然只做未读 / 已读概览，不变成文章列表聚合页。
10. 现有功能如 ingest、summary 生成、idea/todo review、最近阅读、收藏夹不能被破坏。

请按照“先数据层，再搜索，再标签 UI，再批量管理”的顺序实现。不要一开始先做批量删除。实现前先阅读现有代码，确认数据流和模板结构，再开始改动。
