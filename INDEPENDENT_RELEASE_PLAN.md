# Codex Governance 独立发布方案

本文只基于 `tools/codex_governance` 目录内现有实现，整理独立仓发布时的文档与仓库说明方案。不引用上层业务场景做功能卖点。

## 1. 新仓库名称建议

推荐顺序：

1. `codex-governance`
   - 最直接，和当前目录名一致。
   - 适合保留“三省三部”作为内部编排模型，不强绑具体业务。
2. `codex-local-governance`
   - 强调本地 launcher、本地文件、工作区治理。
   - 适合与云端代理编排器区分。
3. `codex-department-launcher`
   - 强调会话分派和部门编排。
   - 语义更偏执行器，弱化治理报告。

结论：首选 `codex-governance`。

## 2. README 结构建议

独立仓 README 建议结构：

1. 项目一句话简介
2. 为什么存在
3. 核心能力
4. 架构图或分层说明
5. 快速开始
6. API 概览
7. 仓库结构
8. 开发验证
9. 安全与边界
10. 贡献指南入口
11. License

首页不要写上层业务背景，直接写“本地多代理治理、分派、回传、确认、并发控制”。

## 3. 功能描述建议

对外功能描述建议聚焦 5 点：

- 工作区治理报告：按路径规则把改动映射到部门职责，并输出风险和建议验证。
- 本地白名单 launcher：只开放有限 API，不直接给前端任意 shell 执行能力。
- 中书省先审后发：主代理先提交结构化分派方案，前端确认后再启动执行部门。
- 部门结果回传：统一走 mailbox 文件，避免网络回传失败造成数据丢失。
- 并发与模型策略：中书省常驻，部门有限并发，模型选择可按风险与复杂度调整。

卖点措辞建议：

- `local-first multi-agent governance`
- `reviewable assignment planning`
- `white-listed launcher API`
- `mailbox reporting`
- `human-confirmed department startup`

不要写：

- 某个具体机器人、板卡、训练模型的上下文
- 与独立仓功能无关的业务规则

## 4. 快速开始建议

独立仓 README 中快速开始建议压缩为 4 步：

```powershell
python codex_governance.py
.\launch.ps1
start dashboard.html
python run_codex_prompt.py --help
```

配套说明：

- 运行环境：Windows、PowerShell、Python 3、Git、Codex CLI
- 默认地址：`http://127.0.0.1:6211`
- 默认并发：部门会话最多 2 个

若未来要支持跨平台，再单列 `Linux/macOS status: not yet supported`，避免 README 暗示已支持。

## 5. 架构说明建议

独立仓文档建议拆成 4 层：

### 报告层

`codex_governance.py`

- 输入：Git worktree / staged / base diff
- 处理：glob 分派、风险命中、验证命令汇总
- 输出：文本报告 / JSON 报告

### 编排层

`codex_launcher.py`

- 会话生命周期
- 分派方案注册
- 队列与并发控制
- 结果归档
- mailbox 收取

### 表现层

`dashboard.html`

- 状态轮询
- 任务下发
- 计划确认
- 结果展示

### 执行适配层

`run_codex_prompt.py`、`launch.ps1`

- Windows 控制台编码适配
- 旧进程回收
- launcher 启动与端口探测

## 6. API 说明建议

独立仓至少补一份单独 API 文档，建议文件名：

- `docs/api.md`
  或
- `API.md`

最少覆盖：

### GET

- `/api/status`
- `/api/zhongshu_sessions`
- `/api/zhongshu_plan`
- `/api/zhongshu_inbox`
- `/api/zhongshu_context`
- `/api/report`

### POST

- `/api/start_zhongshu`
- `/api/restart_zhongshu_session`
- `/api/start_department`
- `/api/start_assignments`
- `/api/report_zhongshu_plan`

每个接口应写：

- 作用
- 关键请求字段
- 关键响应字段
- 常见失败场景

当前代码已足够支撑这份 API 文档；不需要先改实现。

## 7. 贡献指南建议

建议需要 `CONTRIBUTING.md`。原因：

- 本项目有明显的边界规则和白名单 API 约束。
- 提交者需要知道哪些文件改动会影响安全边界。
- 需要统一验证命令和回归方式。

建议内容：

1. 开发前环境要求
2. 分支 / 提交建议
3. 新增部门或风险规则时的要求
4. 修改 launcher API 时的兼容性要求
5. 前端改动的本地回归步骤
6. 发布前检查

## 8. 开发验证命令建议

独立仓 README / CONTRIBUTING 中建议写这些命令：

```powershell
python codex_governance.py
python codex_governance.py --json
python codex_governance.py --staged
python run_codex_prompt.py --help
```

若保留仓内相对路径版本，也可写：

```powershell
python tools/codex_governance/codex_governance.py
python tools/codex_governance/codex_governance.py --json
python tools/codex_governance/run_codex_prompt.py --help
```

若后续补测试，优先加：

- launcher API 的最小 smoke test
- plan/result mailbox roundtrip test
- dashboard 静态交互 smoke test

## 9. 发布前清单建议

建议单列 `RELEASING.md` 或 README 中的 checklist：

1. 去掉仓库根路径、业务专用路径、上层仓库说明。
2. 检查 README 只描述 `tools/codex_governance` 自身能力。
3. 确认默认端口、API version、并发限制、模型候选写法与代码一致。
4. 确认 `launch.ps1`、`run_codex_prompt.py`、`codex_launcher.py`、`codex_governance.py` 互相引用路径可在新仓成立。
5. 确认 `.tmp/`、mailbox、archive 属于运行时产物，加入 ignore。
6. 确认没有把上层私有 prompt、业务敏感路径、历史任务残留带入新仓。
7. 跑最小验证命令。
8. 人工检查 API 文档和前端文案是否仍引用旧仓语境。

## 10. LICENSE / SECURITY / CONTRIBUTING 是否需要

### LICENSE

需要。

原因：独立仓对外发布，不给 License 会直接影响复用和贡献。

建议：

- 若目标偏开放协作：`MIT`
- 若希望显式保留专利授予与贡献保护：`Apache-2.0`

结论：优先 `MIT`，除非后续要更强专利条款。

### SECURITY.md

建议需要。

原因：本项目会启动本地进程、开放本地 HTTP API、写入 mailbox。即使只绑定 `127.0.0.1`，仍应说明：

- 支持的版本
- 漏洞报告方式
- 不建议暴露到公网
- 白名单 API 设计边界

### CONTRIBUTING.md

需要。

原因：本项目规则多，贡献者需要统一入口。

## 11. 推荐的独立仓文件集

首版建议至少有：

- `README.md`
- `LICENSE`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `API.md` 或 `docs/api.md`
- `RELEASING.md`
- `launch.ps1`
- `codex_governance.py`
- `codex_launcher.py`
- `run_codex_prompt.py`
- `dashboard.html`
- `governance.yaml`

## 12. 当前落地建议

本轮先做两件事最值：

1. 把当前目录 README 改成独立功能口径。
2. 在目录内补这份独立发布方案，供后续在隔离目录或新仓落地时直接执行。

本轮不做：

- GitHub 发布
- 新仓初始化
- 跨平台适配
- API 实现改造
