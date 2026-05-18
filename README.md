# Codex Governance

Codex Governance 是一套本地优先的 Codex 协作治理工具，用于把多代理执行拆成可审查的三省三部流程，并通过白名单 launcher、前端看板、结果回传机制维持可控协作。

当前实现只依赖本地文件、Git 工作区、PowerShell 和 Codex CLI，不要求云端控制面。

## 核心能力

- `codex_governance.py`：读取 Git 工作区，按路径规则生成人工可读或 JSON 治理报告。
- `codex_launcher.py`：提供本地 HTTP API，负责中书省会话、部门会话、并发队列、结果归档、计划确认。
- `dashboard.html`：前端看板，展示报告、会话、分派方案和回传结果。
- `launch.ps1`：启动 launcher 并打开看板，处理旧进程和端口探测。
- `run_codex_prompt.py`：以 UTF-8 prompt 文件方式启动 Codex CLI，兼容 Windows 控制台编码。
- portability preflight：扫描治理面中的本机绝对路径引用，默认随治理报告输出，严格模式用 `--preflight`。
- handoff packet：部门回传登记后自动在 mailbox archive 中生成 Markdown 交接包。

## 工作流

1. 运行治理报告，识别当前改动属于哪些部门。
2. 启动本地 launcher 和看板。
3. 由中书省会话先生成结构化分派方案。
4. 前端确认后，再批量启动门下省 / 三部。
5. 部门完成后写入 mailbox 回传结果。
6. 中书省轮询 inbox，继续分派或汇总交付。

## 快速开始

在独立仓根目录运行报告：

```powershell
python codex_governance.py
```

常用参数：

```powershell
python codex_governance.py --base HEAD~1
python codex_governance.py --staged
python codex_governance.py --json
python codex_governance.py --preflight
```

启动 launcher 和看板：

```powershell
.\launch.ps1
```

后台启动：

```powershell
.\launch.ps1 -Detach
```

只打开静态页面：

```powershell
start dashboard.html
```

## 架构

### 1. 报告层

`codex_governance.py` 读取 Git 状态，不修改仓库文件。它根据部门 glob 和风险规则输出：

- 三省职责视图
- 命中的部门列表
- 风险列表
- 建议验证命令
- portability preflight 摘要

### 2. 编排层

`codex_launcher.py` 提供本地白名单 API：

- 启动 / 恢复中书省会话
- 启动部门会话
- 队列与并发控制
- 分派方案确认
- 结果归档与 mailbox 兜底
- 部门 handoff packet 生成

默认并发限制：

- 中书省会话不计入部门并发
- 部门会话最多同时运行 `2` 个
- 模型候选固定为 `gpt-5.5` 和 `gpt-5.4`

### 3. 前端层

`dashboard.html` 只访问本地 launcher API，不直接执行任意 shell。前端负责：

- 拉取报告与状态
- 启动中书省
- 确认中书省回传的部门分派方案
- 查看会话、队列、回传结果
- 当前暂不内嵌终端；浏览器终端方案会单独重做。

### 4. 终端执行层

`run_codex_prompt.py` 把 prompt 写入文件后再启动 Codex CLI，解决 Windows 控制台 UTF-8 和长 prompt 传递问题。

## API 概览

当前 launcher 暴露的主要接口：

### GET

- `/api/status`：总体状态、并发、模型、队列、会话列表
- `/api/sessions`：同 `/api/status`
- `/api/zhongshu_sessions`：中书省会话及其子部门摘要
- `/api/zhongshu_inbox?id=<session_id>`：读取中书省结果 inbox
- `/api/zhongshu_plan?id=<session_id>`：读取中书省分派方案
- `/api/zhongshu_context?id=<session_id>`：读取中书省上下文快照
- `/api/report?mode=worktree|staged&base=<git_ref>`：返回治理报告

### POST

- `/api/start_zhongshu` 或 `/api/start_zhongshu_session`
- `/api/restart_zhongshu_session`
- `/api/plan_assignments`
- `/api/start_department`
- `/api/start_department_for_zhongshu`
- `/api/start_assignments`
- `/api/report_zhongshu_plan`

接口请求与响应字段细节见 [API.md](./API.md)。

## 本地文件约定

- prompt 临时文件：`.tmp/codex_governance_prompts/`
- mailbox：`.tmp/codex_governance_mailbox/<zhongshu_session_id>/incoming`
- archive：`.tmp/codex_governance_mailbox/<zhongshu_session_id>/archive`
- handoff packet：`.tmp/codex_governance_mailbox/<zhongshu_session_id>/archive/handoff-*.md`

## 配置

路径分派和风险规则可在 `governance.yaml` 中调整。若安装了 `PyYAML`，`codex_governance.py` 会读取该文件；否则使用内置通用规则。

launcher 支持这些环境变量：

- `CODEX_GOVERNANCE_PROJECT_NAME`：写入 Codex prompt 的项目名
- `CODEX_GOVERNANCE_WORKFLOW_DOC`：启动提示默认只要求阅读的入口文档，默认 `AGENTS.md`
- `CODEX_GOVERNANCE_MODELS`：逗号分隔的模型候选
- `CODEX_GOVERNANCE_ZHONGSHU_MODEL`：中书省默认模型
- `CODEX_GOVERNANCE_DEPARTMENT_MODEL`：部门默认模型
- `CODEX_GOVERNANCE_MAX_DEPARTMENTS`：部门并发上限
- `CODEX_GOVERNANCE_ALLOW_ORIGIN`：本地 API 的 CORS `Access-Control-Allow-Origin`

## 开发验证

最小验证：

```powershell
git status --short
python codex_governance.py
```

若改动 launcher 或前端，建议再补：

```powershell
python codex_governance.py --json
python run_codex_prompt.py --help
```

## 独立发布

- [API.md](./API.md)：launcher API 参考
- [CONTRIBUTING.md](./CONTRIBUTING.md)：贡献指南
- [SECURITY.md](./SECURITY.md)：本地 API 与进程启动安全边界
- [RELEASING.md](./RELEASING.md)：发布检查清单
- [INDEPENDENT_RELEASE_PLAN.md](./INDEPENDENT_RELEASE_PLAN.md)：从嵌入式目录迁移到独立仓的整理记录

## 已知边界

- 当前实现偏 Windows / PowerShell / 本地 Codex CLI。
- API 默认监听 `127.0.0.1`，目标是本机协作，不是公网服务。
- 路由规则与默认提示词仍带三省三部中文语义；若做社区发布，建议保留概念，同时补英文术语映射。
