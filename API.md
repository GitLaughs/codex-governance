# API Reference

`codex_launcher.py` serves a local JSON API. Default URL:

```text
http://127.0.0.1:6211
```

The API is intended for the bundled `dashboard.html` and trusted local tools.

## GET `/api/status`

Returns launcher state, sessions, queue, API version, model choices, and concurrency limits.

## GET `/api/report`

Returns the governance report generated from Git state.

Query parameters:

- `mode`: `worktree`, `staged`, or `base`
- `base`: Git ref used when `mode=base`

Report payloads include a `preflight.checks.portability_reference_scan` object:

- `decision`: `PASS` or `REVIEW`
- `scope`: scanned governance surface family
- `scanned_files`: files inspected with UTF-8 decoding
- `violations`: machine-local references that need review
- `exceptions`: machine-local references treated as command or inline-code examples

## GET `/api/zhongshu_sessions`

Returns Zhongshu sessions with child department summaries and unread result counts.

## GET `/api/zhongshu_plan?id=<session_id>`

Returns the latest structured plan reported by a Zhongshu session.

## GET `/api/zhongshu_inbox?id=<session_id>`

Returns unread and read department reports for a Zhongshu session. By default, unread reports are marked as read. Add `peek=1` to inspect without marking read.

## GET `/api/zhongshu_context?id=<session_id>`

Returns a restart snapshot for a Zhongshu session: task, plan, recent reports, and child sessions.

## GET `/api/browser_terminals`

Returns browser terminal sidecars launched through `tools/codex_terminal/`.

Session payloads returned by `/api/status`, `/api/sessions`, `/api/zhongshu_sessions`, and inbox/context endpoints may also include:

- `browser_terminal_id`
- `browser_terminal_status`
- `browser_terminal_url`
- `browser_terminal_title`
- `heartbeat_status`: department session liveness, one of `active`, `stalled`, `exited`, or `unknown`
- `idle_seconds`: seconds since the department transcript log last changed, present after heartbeat sampling

## POST `/api/start_zhongshu_session`

Starts a Zhongshu Codex session.

Request fields:

- `task`: first prompt text
- `model`: optional model from `model_choices`

## POST `/api/restart_zhongshu_session`

Restarts a Zhongshu session from stored context.

Request fields:

- `session_id`
- `model`: optional model

## POST `/api/report_zhongshu_plan`

Registers a structured plan from Zhongshu.

Request fields:

- `session_id`
- `summary`
- `assignments`: array of department assignment objects

Assignment fields:

- `department`
- `task`
- `model`
- `files`
- `verify`
- `reason`
- `model_reason`
- `selected`

## POST `/api/browser_terminal/start`

Starts the local `tools/codex_terminal/` sidecar and returns a tokenized loopback URL for iframe embedding.

Optional request fields:

- `shell`: override PTY shell
- `shell_args`: override PTY shell arguments

The launcher always sets host to `127.0.0.1` and port to `0`, so the terminal service chooses a free loopback port and generates its own runtime token.

## POST `/api/browser_terminal/close`

Stops a browser terminal sidecar.

Request fields:

- `id`: terminal id returned by `/api/browser_terminal/start`

## POST `/api/session_browser_terminal/start`

Starts or reuses a tokenized loopback browser-terminal sidecar for one governance session.

Request fields:

- `session_id`

The sidecar stays on `127.0.0.1` and tails that session's transcript log for browser preview inside the dashboard.

## POST `/api/start_assignments`

Starts or queues selected department assignments after user confirmation.

Request fields:

- `parent_session_id`
- `assignments`

## POST `/api/start_department`

Starts one department session. Used by the dashboard for manual launches.

Request fields:

- `department`
- `task`
- `parent_session_id`: optional when one active Zhongshu session exists
- `model`: optional

## Department Result Mailbox

Department sessions report by writing UTF-8 JSON files to:

```text
.tmp/codex_governance_mailbox/<zhongshu_session_id>/incoming/
```

Required fields:

- `parent_session_id`
- `department_session_id`
- `department`
- `summary`

Optional fields:

- `changed_files`
- `verification` or `verifications_run`
- `verifications_skipped`
- `risks`
- `next_action`
- `needs_user_confirmation`

When the launcher registers a department report, it also writes a Markdown handoff packet under:

```text
.tmp/codex_governance_mailbox/<zhongshu_session_id>/archive/handoff-*.md
```

The registered result includes `handoff_packet` with the generated path. The packet records the parent session, department session, source, objective, summary, changed files, verification, risks, and next action.

Zhongshu prompts include an inbox reduction rule: when unread results are multiple, risky, need confirmation, conflict on `next_action`, or include `launcher_fallback`, Zhongshu should use a temporary Codex subagent to read `/api/zhongshu_inbox?id=<session_id>&peek=1` and summarize only. That subagent must not edit files, start departments, or make the final Zhongshu decision.

Launcher also appends key flow events to `.tmp/codex_governance_audit.jsonl` as JSON Lines. Current event names include `session_started`, `session_closed`, `assignment_queued`, `zhongshu_plan_registered`, `result_registered`, and `result_updated`.

## Failure Shape

Most failures return:

```json
{
  "ok": false,
  "error": "message"
}
```
