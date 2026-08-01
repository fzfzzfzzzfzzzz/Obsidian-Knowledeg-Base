# v0.4.3 PRD:代码健康度提升 + 数据自愈 + 云端部署就绪

> 日期:2026-07-19
> 上一版:v0.4.2(见 `docs/v0.4.2/`)
> 性质:结构性维护版,无面向终端用户的新功能

## 0. 文档定位

本 PRD 描述 v0.4.3 的四个主线:**补测试网、加 rebuild-index 数据自愈命令、Web accept 全流程闭环、路径配置环境变量化**。这四件事都是 ROADMAP 上已登记的 P1 项目(自动化测试、rebuild-index、Web 端 accept 自动搬运),在为云端部署做准备时一并落地。

具体实现细节见 `changelog.md`,本 PRD 聚焦"为什么做、范围边界"。

## 1. 范围内

### 1.1 核心高风险命令单测补齐
**动机**:`accept-ideas` / `accept-todos` / `make-prompts --reconcile` / `_write_summary` 这些会**改写用户正式清单**的操作,此前零单测覆盖(100 passed 主要在解析层和 --no-llm ingest 路径)。这是后续 Web 自动搬运和拆分重构的保险绳。

**范围**:
- `test_accept_commands.py`:CLI accept 命令端到端
- `test_make_prompts.py`:reconcile 回填路径
- `test_format_helpers.py`:格式化纯函数
- 不覆盖 `--auto` 模式(依赖真实 LLM,属集成测试范畴)

### 1.2 rebuild-index 命令(ROADMAP P1-2)
**动机**:state.json 与 frontmatter 长期使用必然漂移(用户手改 frontmatter、summary 文件被删等)。云端部署后漂移概率更高,数据自愈是刚需。

**范围**:
- 从 `02_Summaries/**/*.md` 扫盘,frontmatter 为权威
- 同步 `summary_path` 和 `tags` 到 state
- **不动**用户行为数据(`is_favorite` / `read_count` / `collection_ids` 等)
- 支持 `--dry-run` / `--tags-only` / `--summary-path-only`
- 写前自动备份
- 报告孤儿(state 里有 summary_path 但文件不存在)

**不在范围**:
- 不持久化 `has_summary`(保持运行时派生计算,价值低)
- 不从 processed.md 反向重建(那是灾难恢复级别,另做)
- 不重建 sources 字典的核心字段(`path` / `source_type` / `source_title` 等,这些 frontmatter 里没有)

### 1.3 Web accept 接受即搬运(ROADMAP P1-15)
**动机**:Web UI 改 status + CLI 搬运的两段式流程在云端部署后尤其别扭(用户不一定有 SSH 跑 CLI)。把搬运合到 Web accept 里,体验闭环。

**范围**:
- 抽 `move_accepted_idea` / `move_accepted_todo` 纯函数(CLI 和 Web 共用)
- Web 路由在 `accepted_*` 状态下自动调搬运
- 幂等保护:已 `moved` 不重复搬
- 前端 toast 差异化反馈

**规则合规**:仍是"只有用户接受的才进正式清单",AGENTS.md 硬规则不破。搬运步骤从 CLI 移到 Web,执行时机更早。

**不在范围**:
- 不改 suggestion 块格式
- 不改正式清单文件格式
- 不引入"撤销搬运"功能(moved 状态保留追溯,但反向操作需手动)

### 1.4 路径配置派生量化
**动机**:此前的 `KB_VAULT_ROOT` 只覆盖 `VAULT_ROOT` 一个常量,其余 5 个派生量(`KB_DIR` / `STATE_FILE` / `CALENDAR_FILE` / `RAW_TEXT_DIR` / `LOGS_DIR`)在 import 时按默认布局算死。云端部署需要能独立重定向这些路径(如只读 vault + 可写 state 卷)。

**范围**:6 个常量全部支持环境变量覆盖,默认行为完全不变(向后兼容)。

**不在范围**:
- 不抽独立 `kb_config.py` 模块(改动面太大,留到下次)
- 不改 import-time 冻结的根本机制(只让冻结时读环境变量)
- 不引入运行时动态解析

## 2. 范围外(整体)

- 不拆 `kb_web.py`(2117 行,留 v0.4.4 专项)
- 不抽 `kb.py` 公共工具(同上)
- 不动 vault 内容文件格式
- 不引入新外部依赖
- 不改 API 响应 schema 的现有字段(只加新字段)

## 3. 验收标准

- [x] 全量测试通过(100 → 161)
- [x] 真实 vault `kb.py rebuild-index --dry-run` 不报错
- [x] 真实 vault `kb.py status` 输出与重构前一致
- [x] Web accept 在 TestClient 下端到端跑通(含幂等)
- [x] 6 个路径常量环境变量覆盖有测试
- [x] 无破坏性变更(API 响应只加字段,不删字段;CLI 行为不变)
