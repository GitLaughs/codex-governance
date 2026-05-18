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

## GET `/api/session_stream?id=<session_id>`

Server-Sent Events stream for the dashboard terminal viewer. Intended for the local trusted launcher UI only.

Query parameters:

- `id`: required session id

Event shape:

- event name: `session`
- payload fields:
  - `ok`
  - `session`: public session metadata
  - `input_enabled`: `true` when the target session is still running
  - `transcript`: launcher-side transcript text for xterm display; when the session was started by this launcher, it includes a tail of the mirrored Codex stdout/stderr log

Notes:

- `dashboard.html` uses `EventSource` against this route and renders the result with root-level `node_modules/@xterm/xterm`.
- The stream is display-oriented launcher metadata plus local log tail, not a raw PTY bridge and not a remote shell API.
- The launcher checks the session transcript once per second and only pushes a new SSE frame when the payload changes.
- The dashboard keeps one interactive xterm viewer for the currently selected session; the "running terminal overview" area is a summary card view, not additional interactive streams.

## GET `/api/zhongshu_sessions`

Returns Zhongshu sessions with child department summaries and unread result counts.

## GET `/api/zhongshu_plan?id=<session_id>`

Returns the latest structured plan reported by a Zhongshu session.

## GET `/api/zhongshu_inbox?id=<session_id>`

Returns unread and read department reports for a Zhongshu session. By default, unread reports are marked as read. Add `peek=1` to inspect without marking read.

## GET `/api/zhongshu_context?id=<session_id>`

Returns a restart snapshot for a Zhongshu session: task, plan, recent reports, and child sessions.

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

## POST `/api/session_input`

Sends one normalized line of input to a running Codex session window through the trusted local launcher path.

Request fields:

- `session_id`
- `input`

Success response fields:

- `ok`
- `session_id`
- `sent_at`

Failure cases:

- unknown `session_id`
- empty `input`
- target session not running
- launcher failed to deliver input to the matched local Codex window

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

## Failure Shape

Most failures return:

```json
{
  "ok": false,
  "error": "message"
}
```
