# Changelog v0.1

> 日期:2026-07-14

## 新增
- 完整的 CLI 工具链:init / ingest / status / llm-test / make-prompts / extract-suggestions / accept-ideas / accept-todos / serve
- LLM 集成(智谱 GLM-4.7-flash):metadata 识别 / summary 生成 / idea·todo 抽取
- 网页抓取(requests + HTML 解析,50000 字符上限)
- Web 前端:仪表盘 / 投稿 / 最近阅读 / 收藏夹 / idea·todo review / 文章详情 / 删除
- 阅读管理:reading_status / read_later / is_favorite / last_read_at / read_count
- 11 个 markdown 模板(按 source_type 区分 summary 章节)
- 代码与 vault 内容分离,支持 GitHub 上传

## 修复(开发过程中)
- metadata 解析 bug(头部说明区污染格式检测)
- 思考模型 max_tokens 不足导致输出为空
- 网页抓取正文截断(FETCH_MAX_CHARS 6000 → 50000)
- source note 未保存抓取正文导致 summary 瞎编
- 详情页对无 summary 的 source 报 404(改为回退读原文)
- Starlette TemplateResponse 新版签名变更
