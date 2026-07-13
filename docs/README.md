# docs/ —— 项目文档

> 开发过程文档(PRD / checklist / changelog),跟着代码进 GitHub。
> vault 内容(文章/总结/idea)不在这里,在 vault 的 00_Inbox~99_System 目录。

## 目录结构

```
docs/
  README.md          本文件
  v0.1/              v0.1 版本文档
    PRD.md           产品需求文档
    checklist.md     开发检查清单
    changelog.md     变更日志
  v0.2/              (以后新增版本时建)
    PRD.md
    checklist.md
    changelog.md
```

## 新版本怎么加

开发新版本时:

1. 复制 `docs/v0.1/` 为 `docs/v0.2/`(或下一个版本号)
2. 改 `PRD.md`:更新本版本目标、新增功能、不在范围
3. 改 `checklist.md`:清空勾选,填入本版本要做的任务
4. 开发过程中逐条勾选 checklist
5. 发布时写 `changelog.md`(新增/修复/破坏性变更)
6. `git add docs/v0.2/ && git commit -m "docs: v0.2 PRD and checklist"`

## 文档规范

| 文件 | 作用 | 什么时候写 |
|------|------|-----------|
| `PRD.md` | 本版本要做什么、不做什么、验收标准 | 开发前 |
| `checklist.md` | 具体任务清单(可勾选) | 开发前建,开发中勾 |
| `changelog.md` | 新增了什么、修了什么 | 发布时 |
