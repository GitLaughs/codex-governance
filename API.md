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

## POST `/api/report_result`

Registers a department result.

Request fields:

- `parent_session_id`
- `department_session_id`
- `department`
- `summary`
- `changed_files`
- `verifications_run`
- `verifications_skipped`
- `risks`
- `needs_user_confirmation`
- `next_action`

## Failure Shape

Most failures return:

```json
{
  "ok": false,
  "error": "message"
}
```
