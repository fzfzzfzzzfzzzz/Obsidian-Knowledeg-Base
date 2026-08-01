# F. 任务拆分 Checklist

## Phase 0：实现前检查

```text
[ ] 阅读现有项目结构
[ ] 找到 state.json 读写逻辑
[ ] 找到 source / summary 读取逻辑
[ ] 找到文章详情页 route
[ ] 找到未读 / 已读列表渲染逻辑
[ ] 找到收藏、最近阅读、删除的现有实现
[ ] 找到 sidebar 模板
[ ] 找到现有 JS 操作逻辑
[ ] 确认 summary frontmatter 的解析和写回方式
```

---

## Phase 1：数据层 tags 支持

```text
[ ] 给 state.json source 记录兼容 tags 字段
[ ] 给 state.json source 记录兼容 has_summary 字段
[ ] 给 summary markdown frontmatter 支持 tags: []
[ ] 写 get_article_tags(source_id) 工具函数
[ ] 写 set_article_tags(source_id, tags) 工具函数
[ ] 写 add_article_tags(source_id, tags) 工具函数
[ ] 写 remove_article_tag(source_id, tag) 工具函数
[ ] tags 写入 summary frontmatter
[ ] tags 同步写入 state.json
[ ] tags 自动去重
[ ] 旧文件没有 tags 时不报错
[ ] 页面读取 tags 时默认返回 []
```

---

## Phase 2：搜索数据准备

```text
[ ] 确认搜索字段：title / summary / tags
[ ] 写 load_searchable_articles() 函数
[ ] 只返回已有 summary 的文章
[ ] summary 文件不存在时跳过
[ ] 缺少字段时不报错
[ ] title 使用 source_title 或 title fallback
[ ] tags 从 state 或 frontmatter 读取
[ ] has_summary 根据 summary_path 和文件存在状态判断
```

---

## Phase 3：Search 页面

```text
[ ] 新增 /search route
[ ] 新增 search.html 模板
[ ] 侧边栏新增 Search 入口
[ ] Search 页面添加搜索框
[ ] Search 页面添加筛选区
[ ] 支持 q 关键词参数
[ ] 支持 reading_status 参数
[ ] 支持 is_favorite 参数
[ ] 支持 source_type 参数
[ ] 支持 tags 参数
[ ] 支持 has_summary 参数
[ ] 搜索 title
[ ] 搜索 summary 内容
[ ] 搜索 tags
[ ] 搜索大小写不敏感
[ ] 搜索结果按相关性排序
[ ] 搜索结果使用卡片展示
[ ] 点击卡片进入文章详情页
[ ] 无结果时显示简单提示
```

---

## Phase 4：首页搜索框

```text
[ ] 首页保留未读 / 已读总结
[ ] 首页不展示搜索结果
[ ] 首页可增加搜索框
[ ] 首页搜索框提交后跳转 /search?q=关键词
[ ] 不在首页展示最近阅读列表
[ ] 不在首页展示收藏夹列表
[ ] 不在首页展示 All Articles 列表
```

---

## Phase 5：All Articles 页面

```text
[ ] 新增 /articles route
[ ] 新增 articles.html 模板
[ ] 侧边栏新增 All Articles 入口
[ ] 展示所有 source
[ ] 包括没有 summary 的 source
[ ] 卡片展示是否已有 summary
[ ] 卡片展示 title
[ ] 卡片展示 source_type
[ ] 卡片展示 reading_status
[ ] 卡片展示 tags
[ ] 卡片展示 is_favorite
[ ] 点击卡片进入文章详情页
```

---

## Phase 6：文章详情页 tags UI

```text
[ ] 文章详情页显示 tags
[ ] 没有 tags 时显示“暂无标签”
[ ] 添加 tag 输入框
[ ] 添加 tag 按钮
[ ] 删除单个 tag 按钮
[ ] 添加后更新 frontmatter
[ ] 添加后更新 state.json
[ ] 删除后更新 frontmatter
[ ] 删除后更新 state.json
[ ] 操作成功后刷新当前 tags
[ ] 操作失败时显示错误提示
```

---

## Phase 7：AI 推荐 tags

```text
[ ] 新增 AI 推荐 tags 按钮
[ ] 基于当前 summary 调用 LLM
[ ] Prompt 要求生成 3–5 个 tags
[ ] tags 支持中文和英文
[ ] 不要生成过多标签
[ ] 返回结果解析为 list
[ ] 自动去重
[ ] 写入 summary frontmatter
[ ] 同步 state.json
[ ] 页面显示新 tags
[ ] 失败时不影响原 tags
```

---

## Phase 8：卡片展示 tags

```text
[ ] 未读文章卡片展示 tags
[ ] 已读文章卡片展示 tags
[ ] Search 结果卡片展示 tags
[ ] All Articles 卡片展示 tags
[ ] 收藏夹卡片可展示 tags
[ ] 最近阅读卡片可展示 tags
[ ] 没有 tags 时不报错
```

---

## Phase 9：批量选择 UI

```text
[ ] 未读列表卡片增加 checkbox
[ ] 已读列表卡片增加 checkbox
[ ] 勾选文章后显示批量操作栏
[ ] 未勾选时隐藏批量操作栏
[ ] 批量操作栏显示已选数量
[ ] 支持取消选择
[ ] 第一版只操作当前选中的文章
[ ] 不做选择全部搜索结果
```

---

## Phase 10：批量操作 API

```text
[ ] 新增 POST /api/batch
[ ] 接收 source_ids
[ ] 接收 action
[ ] 接收 payload
[ ] 校验 source_ids 非空
[ ] 校验 action 合法
[ ] 返回 success_count
[ ] 返回 failed_count
[ ] 返回 skipped_count
[ ] 返回 failed_items
[ ] 单个失败不影响其他文章继续处理
```

---

## Phase 11：批量归档

```text
[ ] 实现 batch action: archive
[ ] 将 reading_status 改为 archived
[ ] 更新 state.json
[ ] 必要时更新 frontmatter 状态
[ ] 操作成功后从未读 / 已读列表移除
[ ] 返回成功数量
[ ] 失败项单独列出
```

---

## Phase 12：批量收藏 / 取消收藏

```text
[ ] 实现 batch action: favorite
[ ] 将 is_favorite 改为 true
[ ] 更新 state.json
[ ] 页面更新收藏状态
[ ] 不改变 reading_status

[ ] 实现 batch action: unfavorite
[ ] 将 is_favorite 改为 false
[ ] 更新 state.json
[ ] 页面更新收藏状态
[ ] 不改变 reading_status
```

---

## Phase 13：批量添加标签

```text
[ ] 实现 batch action: add_tags
[ ] 支持输入一个或多个 tags
[ ] 对每篇文章追加 tags
[ ] 不覆盖旧 tags
[ ] 自动去重
[ ] 写入 summary frontmatter
[ ] 同步 state.json
[ ] 没有 summary 的文章跳过或返回失败
[ ] 返回成功数量 / 失败数量 / 跳过数量
```

---

## Phase 14：批量抽取 idea/todo

```text
[ ] 实现 batch action: extract_suggestions
[ ] 只处理已有 summary 的文章
[ ] 没有 summary 的文章跳过
[ ] 调用现有 extract-suggestions 逻辑
[ ] 不重复 append 已有候选
[ ] 返回成功数量
[ ] 返回失败数量
[ ] 返回跳过数量
```

---

## Phase 15：批量生成 summary

```text
[ ] 实现 batch action: generate_summary
[ ] 默认跳过已有 summary 的文章
[ ] 只处理没有 summary 的文章
[ ] 调用现有 make-prompts / summary 生成逻辑
[ ] 不重复生成已有 summary
[ ] 当前未读 / 已读页面如果没有未总结文章，可以先隐藏按钮或保留后端能力
[ ] 后续可放到 All Articles 页面使用
```

---

## Phase 16：批量删除

```text
[ ] 实现 batch action: delete
[ ] 删除前前端二次确认
[ ] 删除前自动备份 state.json
[ ] 删除前自动备份将要删除或修改的相关文件
[ ] 沿用现有单篇删除逻辑
[ ] 删除 source note
[ ] 删除 summary
[ ] 删除 raw
[ ] 删除 state 记录
[ ] 删除或清理相关 idea/todo 候选
[ ] 部分失败时继续处理其他文章
[ ] 返回成功数量
[ ] 返回失败数量
[ ] 返回失败项
```

---

## Phase 17：批量操作反馈

```text
[ ] 批量操作完成后显示结果
[ ] 显示成功数量
[ ] 显示失败数量
[ ] 显示跳过数量
[ ] 有失败项时列出失败文章
[ ] 操作成功后刷新列表
[ ] 归档后文章从当前列表消失
[ ] 收藏 / 取消收藏后文章保留在原列表
[ ] 添加 tags 后卡片 tags 更新
```

---

## Phase 18：rebuild-index 预留或实现

```text
[ ] 预留 rebuild-index 函数
[ ] 从 summary frontmatter 读取 tags
[ ] 从 summary_path 判断 has_summary
[ ] 同步 state.json tags
[ ] 同步 state.json has_summary
[ ] 修复缺少 tags 字段的旧记录
[ ] 修复缺少 has_summary 字段的旧记录
[ ] 不覆盖用户手写内容
```

---

## Phase 19：回归测试

```text
[ ] 测试 ingest 是否正常
[ ] 测试 make-prompts 是否正常
[ ] 测试 extract-suggestions 是否正常
[ ] 测试 accept-ideas 是否正常
[ ] 测试 accept-todos 是否正常
[ ] 测试文章详情页是否正常
[ ] 测试最近阅读是否正常更新 last_read_at 和 read_count
[ ] 测试收藏夹是否正常
[ ] 测试单篇删除是否正常
[ ] 测试旧文章没有 tags 时页面不报错
[ ] 测试搜索 title 命中
[ ] 测试搜索 summary 命中
[ ] 测试搜索 tags 命中
[ ] 测试 reading_status 筛选
[ ] 测试 is_favorite 筛选
[ ] 测试 source_type 筛选
[ ] 测试 tags 筛选
[ ] 测试 has_summary 筛选
[ ] 测试批量归档
[ ] 测试批量收藏
[ ] 测试批量取消收藏
[ ] 测试批量添加 tags
[ ] 测试批量抽取 idea/todo
[ ] 测试批量删除二次确认
[ ] 测试批量删除备份
[ ] 测试部分失败时结果提示
```

---

## 推荐开发顺序

```text
1. 先做 tags 数据层
2. 再做 Search 页面
3. 再做文章详情页 tags 添加 / 删除
4. 再做 AI 推荐 tags
5. 再做 All Articles 页面
6. 再做未读 / 已读页面 checkbox
7. 再做批量收藏 / 取消收藏 / 归档
8. 再做批量添加 tags
9. 再做批量抽取 idea/todo
10. 最后做批量删除和备份
```

最重要的是：**先保证数据能安全读写，再做搜索，再做批量修改。不要一开始就做批量删除。**
