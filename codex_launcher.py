#!/usr/bin/env python3
"""Local launcher API for the Codex governance dashboard."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import codex_governance


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent


def default_repo_root() -> Path:
    if SCRIPT_DIR.name == "codex_governance" and SCRIPT_DIR.parent.name == "tools":
        return SCRIPT_DIR.parents[1]
    return SCRIPT_DIR


REPO_ROOT = default_repo_root()
PROMPT_DIR = REPO_ROOT / ".tmp" / "codex_governance_prompts"
MAILBOX_ROOT = REPO_ROOT / ".tmp" / "codex_governance_mailbox"
RUNNER = SCRIPT_DIR / "run_codex_prompt.py"
MAX_CODEX_TERMINALS = int(os.environ.get("CODEX_GOVERNANCE_MAX_DEPARTMENTS", "2"))
API_VERSION = 3
ACTIVE_PROCESSES: list[subprocess.Popen] = []
SESSIONS: list[dict] = []
ASSIGNMENT_QUEUE: list[dict] = []
REPORTS_BY_ZHONGSHU: dict[str, list[dict]] = {}
PLANS_BY_ZHONGSHU: dict[str, dict] = {}
STATE_LOCK = threading.RLock()
MODEL_CHOICES = tuple(
    item.strip()
    for item in os.environ.get("CODEX_GOVERNANCE_MODELS", "gpt-5.5,gpt-5.4").split(",")
    if item.strip()
) or ("gpt-5.5", "gpt-5.4")
ZHONGSHU_MODEL = os.environ.get("CODEX_GOVERNANCE_ZHONGSHU_MODEL", MODEL_CHOICES[0])
DEPARTMENT_MODEL = os.environ.get("CODEX_GOVERNANCE_DEPARTMENT_MODEL", MODEL_CHOICES[-1])
SESSION_KIND_ZHONGSHU = "zhongshu"
SESSION_KIND_DEPARTMENT = "department"
LAUNCHER_BASE_URL = os.environ.get("CODEX_GOVERNANCE_LAUNCHER_URL", "http://127.0.0.1:6211")
PROJECT_NAME = os.environ.get("CODEX_GOVERNANCE_PROJECT_NAME", REPO_ROOT.name)
WORKFLOW_DOC = os.environ.get("CODEX_GOVERNANCE_WORKFLOW_DOC", "Codex governance workflow")
ALLOW_ORIGIN = os.environ.get("CODEX_GOVERNANCE_ALLOW_ORIGIN", "*")

DEPARTMENT_PROMPTS = {
    "menxia": ("门下省", "风险复核、边界检查、必要时驳回"),
    "zhilibu": ("治理部", "任务拆分、代理规则、README、文档、发布说明"),
    "gongchengbu": ("工程部", "launcher、前端、脚本、验证、回归、发布链路"),
    "lingyubu": ("领域部", "领域实现、业务代码、集成联调"),
}


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def normalize_task_text(task: str) -> str:
    normalized = " ".join(str(task).replace("\r", "\n").splitlines())
    normalized = " ".join(normalized.split())
    return normalized.strip()


def context_doc_instruction(*, include_related_docs: bool) -> str:
    optional_docs = ["AGENTS.md"]
    if WORKFLOW_DOC and WORKFLOW_DOC not in {"README.md", "AGENTS.md"}:
        optional_docs.append(WORKFLOW_DOC)
    related_docs = " 和相关目录文档" if include_related_docs else ""
    return f"先读取 README.md；如存在 {'、'.join(optional_docs)}{related_docs}，也一并读取"


def write_prompt(prefix: str, prompt: str) -> Path:
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = PROMPT_DIR / f"{stamp}-{prefix}.txt"
    path.write_text(prompt, encoding="utf-8")
    return path


def prune_processes() -> None:
    ACTIVE_PROCESSES[:] = [process for process in ACTIVE_PROCESSES if process.poll() is None]


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_session_id(prefix: str) -> str:
    return f"{prefix}-{time.time_ns()}"


def session_public(session: dict) -> dict:
    return {key: value for key, value in session.items() if key != "_process"}


def zhongshu_context_snapshot(session_id: str) -> dict:
    session = require_zhongshu_session(session_id, active_only=False)
    plan = PLANS_BY_ZHONGSHU.get(session_id) or {}
    reports = [result_public(item) for item in REPORTS_BY_ZHONGSHU.get(session_id, [])[:10]]
    children = [session_public(child) for child in parent_children(session_id)]
    return {
        "session": session_public(session),
        "task": session.get("task", ""),
        "plan": plan_public(plan) if plan else {},
        "reports": reports,
        "children": children,
    }


def mailbox_paths(zhongshu_session_id: str) -> dict[str, Path]:
    root = MAILBOX_ROOT / zhongshu_session_id
    return {
        "root": root,
        "incoming": root / "incoming",
        "archive": root / "archive",
    }


def ensure_zhongshu_mailbox(zhongshu_session_id: str) -> dict[str, str]:
    paths = mailbox_paths(zhongshu_session_id)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return {name: str(path) for name, path in paths.items()}


def read_mailbox_items(zhongshu_session_id: str, archive: bool = True) -> list[dict]:
    paths = mailbox_paths(zhongshu_session_id)
    ensure_zhongshu_mailbox(zhongshu_session_id)
    items = []
    for path in sorted(paths["incoming"].glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw, "decode_error": True}
        item = {
            "mailbox_file": str(path),
            "filename": path.name,
            "payload": payload,
        }
        if archive:
            archive_path = paths["archive"] / path.name
            if archive_path.exists():
                archive_path = paths["archive"] / f"{path.stem}-{time.time_ns()}{path.suffix}"
            path.replace(archive_path)
            item["archived_to"] = str(archive_path)
        items.append(item)
    return items


def write_mailbox_item(zhongshu_session_id: str, department: str, payload: dict) -> Path:
    paths = mailbox_paths(zhongshu_session_id)
    ensure_zhongshu_mailbox(zhongshu_session_id)
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{department}-{time.time_ns()}.json"
    path = paths["incoming"] / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_archive_item(zhongshu_session_id: str, department: str, payload: dict) -> Path:
    paths = mailbox_paths(zhongshu_session_id)
    ensure_zhongshu_mailbox(zhongshu_session_id)
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{department}-{time.time_ns()}.json"
    path = paths["archive"] / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def refresh_sessions() -> None:
    prune_processes()
    for session in SESSIONS:
        process = session.get("_process")
        if process is None:
            continue
        running = process.poll() is None
        session["status"] = "running" if running else "exited"
        session["ended_at"] = None if running else session.get("ended_at") or now_text()


def active_terminal_count() -> int:
    refresh_sessions()
    return len(ACTIVE_PROCESSES)


def active_session_count(session_kind: str | None = None) -> int:
    refresh_sessions()
    return sum(
        1
        for session in SESSIONS
        if session["status"] == "running" and (session_kind is None or session["session_kind"] == session_kind)
    )


def active_zhongshu_count() -> int:
    return active_session_count(SESSION_KIND_ZHONGSHU)


def active_department_count() -> int:
    return active_session_count(SESSION_KIND_DEPARTMENT)


def get_session(session_id: str, session_kind: str | None = None) -> dict | None:
    refresh_sessions()
    for session in SESSIONS:
        if session["id"] != session_id:
            continue
        if session_kind and session["session_kind"] != session_kind:
            continue
        return session
    return None


def close_session_process(session_id: str) -> bool:
    session = get_session(session_id)
    if session is None:
        return False
    process = session.get("_process")
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    session["status"] = "exited"
    session["ended_at"] = now_text()
    return True


def send_prompt_to_window(window_title: str, prompt: str) -> tuple[bool, str]:
    text = normalize_task_text(prompt)
    if not text:
        return False, "prompt is empty"
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$ws = New-Object -ComObject WScript.Shell; "
        "$title = " + ps_quote(window_title) + "; "
        "$text = " + ps_quote(text) + "; "
        "$hadText = [System.Windows.Forms.Clipboard]::ContainsText(); "
        "$backup = if ($hadText) { [System.Windows.Forms.Clipboard]::GetText() } else { $null }; "
        "try { "
        "  [System.Windows.Forms.Clipboard]::SetText($text); "
        "  if (-not $ws.AppActivate($title)) { throw 'window not found'; } "
        "  Start-Sleep -Milliseconds 250; "
        "  $ws.SendKeys('^v'); "
        "  Start-Sleep -Milliseconds 120; "
        "  $ws.SendKeys('~'); "
        "} finally { "
        "  Start-Sleep -Milliseconds 80; "
        "  if ($hadText -and $null -ne $backup) { [System.Windows.Forms.Clipboard]::SetText($backup) } "
        "} "
    )
    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-STA",
            "-Command",
            script,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode == 0:
        return True, ""
    error = completed.stderr.strip() or completed.stdout.strip() or f"powershell exit {completed.returncode}"
    return False, error


def build_zhongshu_result_prompt(parent_session_id: str, result: dict) -> str:
    children = parent_children(parent_session_id)
    completed = [item for item in children if item.get("status") != "running"]
    running = [item for item in children if item.get("status") == "running"]
    queued = [item for item in queue_snapshot() if item.get("parent_session_id") == parent_session_id]
    summary = normalize_task_text(str(result.get("summary", "")).strip()) or "无摘要"
    next_action = normalize_task_text(str(result.get("next_action", "")).strip())
    risks = result.get("risks", [])
    risk_text = "；".join(normalize_task_text(str(item)) for item in risks[:4]) or "无新增风险"
    suffix = (
        f"建议下一步：{next_action}。"
        if next_action
        else "若三部和门下省都已完成且无需续派，请直接汇总当前结果给用户。"
    )
    return (
        f"收到新的下属部门回传，不要等待用户转述。"
        f"本次回传部门：{result.get('department', 'unknown')}。摘要：{summary}。"
        f"风险：{risk_text}。"
        f"当前状态：已完成 {len(completed)} 个，运行中 {len(running)} 个，排队 {len(queued)} 个。"
        f"请立即读取 {LAUNCHER_BASE_URL}/api/zhongshu_inbox?id={parent_session_id}&peek=1，结合当前任务继续监察、续派或汇总。"
        f"{suffix}"
    )


def auto_notify_zhongshu(parent_session_id: str, result: dict) -> dict:
    session = require_zhongshu_session(parent_session_id, active_only=False)
    if session.get("status") != "running":
        message = "zhongshu session is not running"
        session["auto_notification_status"] = "skipped"
        session["auto_notification_error"] = message
        session["auto_notification_at"] = now_text()
        return {"ok": False, "status": "skipped", "error": message}
    prompt = build_zhongshu_result_prompt(parent_session_id, result)
    ok, error = send_prompt_to_window(str(session.get("window_title", "")), prompt)
    session["auto_notification_status"] = "sent" if ok else "error"
    session["auto_notification_error"] = error if not ok else ""
    session["auto_notification_at"] = now_text()
    session["last_auto_notification_prompt"] = prompt
    return {"ok": ok, "status": session["auto_notification_status"], "error": error, "prompt": prompt}


def require_zhongshu_session(session_id: str, active_only: bool = False) -> dict:
    session = get_session(session_id, SESSION_KIND_ZHONGSHU)
    if session is None:
        raise ValueError(f"unknown zhongshu session: {session_id}")
    if active_only and session["status"] != "running":
        raise ValueError(f"zhongshu session is not running: {session_id}")
    if "mailbox" not in session:
        session["mailbox"] = ensure_zhongshu_mailbox(session_id)
    else:
        ensure_zhongshu_mailbox(session_id)
    session.setdefault("unread_result_count", 0)
    session.setdefault("child_department_ids", [])
    REPORTS_BY_ZHONGSHU.setdefault(session_id, [])
    PLANS_BY_ZHONGSHU.setdefault(session_id, {})
    return session


def latest_active_zhongshu_session() -> dict | None:
    refresh_sessions()
    for session in SESSIONS:
        if session["session_kind"] == SESSION_KIND_ZHONGSHU and session["status"] == "running":
            return session
    return None


def resolve_parent_session_id(parent_session_id: str | None, *, active_only: bool = True) -> str:
    candidate = (parent_session_id or "").strip()
    if candidate:
        require_zhongshu_session(candidate, active_only=active_only)
        return candidate
    latest = latest_active_zhongshu_session()
    if latest is None:
        raise ValueError("parent_session_id is required because no active zhongshu session exists")
    return latest["id"]


def queue_snapshot() -> list[dict]:
    return [
        {
            "department": item["department"],
            "title": item["title"],
            "model": item["model"],
            "parent_session_id": item["parent_session_id"],
            "queued_at": item["queued_at"],
        }
        for item in ASSIGNMENT_QUEUE
    ]


def plan_public(plan: dict) -> dict:
    return dict(plan)


def normalize_plan_assignment(assignment: dict) -> dict:
    department = str(assignment.get("department", "")).strip()
    if department not in DEPARTMENT_PROMPTS:
        raise ValueError(f"unknown department in plan: {department}")
    title, duty = DEPARTMENT_PROMPTS[department]
    model = validate_model(str(assignment.get("model", DEPARTMENT_MODEL)).strip(), DEPARTMENT_MODEL)
    task = normalize_task_text(str(assignment.get("task", "")).strip())
    if not task:
        raise ValueError(f"task is required for department plan: {department}")
    files = assignment.get("files", [])
    verify = assignment.get("verify", assignment.get("verify_commands", []))
    return {
        "department": department,
        "title": str(assignment.get("title", title)).strip() or title,
        "duty": str(assignment.get("duty", duty)).strip() or duty,
        "model": model,
        "model_reason": str(assignment.get("model_reason", "")).strip(),
        "reason": str(assignment.get("reason", "")).strip(),
        "task": task,
        "files": [str(item).strip() for item in files if str(item).strip()],
        "verify": [str(item).strip() for item in verify if str(item).strip()],
        "selected": bool(assignment.get("selected", True)),
    }


def register_zhongshu_plan(parent_session_id: str, payload: dict, *, source: str) -> dict:
    session = require_zhongshu_session(parent_session_id, active_only=False)
    assignments = payload.get("assignments", [])
    if not isinstance(assignments, list):
        raise ValueError("assignments must be a list")
    normalized_assignments = [normalize_plan_assignment(item) for item in assignments]
    plan = {
        "session_id": parent_session_id,
        "summary": str(payload.get("summary", "")).strip() or "中书省已生成分派方案。",
        "reported_at": payload.get("reported_at", now_text()),
        "source": source,
        "ready": True,
        "needs_confirmation": True,
        "assignments": normalized_assignments,
        "active_department_sessions": active_department_count(),
        "max_department_sessions": MAX_CODEX_TERMINALS,
        "active_zhongshu_sessions": active_zhongshu_count(),
        "model_choices": MODEL_CHOICES,
    }
    PLANS_BY_ZHONGSHU[parent_session_id] = plan
    session["plan_status"] = "ready"
    session["plan_reported_at"] = plan["reported_at"]
    return plan


def zhongshu_plan_payload(session_id: str) -> dict:
    session = require_zhongshu_session(session_id, active_only=False)
    stored = PLANS_BY_ZHONGSHU.get(session_id) or {}
    plan = dict(stored) if stored else {}
    plan.setdefault("session_id", session_id)
    plan.setdefault("summary", "中书省尚未回传分派方案。")
    plan.setdefault("reported_at", None)
    plan.setdefault("source", None)
    plan.setdefault("ready", False)
    plan.setdefault("needs_confirmation", False)
    plan.setdefault("assignments", [])
    plan["active_department_sessions"] = active_department_count()
    plan["max_department_sessions"] = MAX_CODEX_TERMINALS
    plan["active_zhongshu_sessions"] = active_zhongshu_count()
    plan["model_choices"] = MODEL_CHOICES
    return {"ok": True, "session": session_public(session), "plan": plan_public(plan)}


def parent_children(parent_session_id: str) -> list[dict]:
    return [
        session
        for session in SESSIONS
        if session.get("parent_session_id") == parent_session_id and session["session_kind"] == SESSION_KIND_DEPARTMENT
    ]


def result_public(result: dict) -> dict:
    return {key: value for key, value in result.items() if key not in {"_sort_key"}}


def report_identity(payload: dict, fallback: str | None = None) -> str:
    for key in ("report_id", "department_session_id"):
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    if fallback:
        return fallback
    return f"report-{time.time_ns()}"


def register_result(
    parent_session_id: str,
    payload: dict,
    *,
    source: str,
    mailbox_file: str | None = None,
    mark_unread: bool = True,
) -> dict:
    parent = require_zhongshu_session(parent_session_id, active_only=False)
    result_id = report_identity(payload, fallback=mailbox_file)
    reports = REPORTS_BY_ZHONGSHU.setdefault(parent_session_id, [])
    existing = next((item for item in reports if item["report_id"] == result_id), None)
    if existing:
        existing["source"] = source
        if mailbox_file:
            existing["mailbox_file"] = mailbox_file
        return existing

    result = {
        "report_id": result_id,
        "parent_session_id": parent_session_id,
        "department_session_id": payload.get("department_session_id"),
        "department": payload.get("department", "unknown"),
        "summary": payload.get("summary", ""),
        "changed_files": payload.get("changed_files", payload.get("files", [])),
        "verifications_run": payload.get("verifications_run", payload.get("verification", [])),
        "verifications_skipped": payload.get("verifications_skipped", []),
        "risks": payload.get("risks", []),
        "needs_user_confirmation": bool(payload.get("needs_user_confirmation", False)),
        "next_action": payload.get("next_action", ""),
        "reported_at": payload.get("reported_at", now_text()),
        "source": source,
        "read": not mark_unread,
        "_sort_key": time.time_ns(),
    }
    if mailbox_file:
        result["mailbox_file"] = mailbox_file
    reports.insert(0, result)
    if mark_unread:
        parent["unread_result_count"] = parent.get("unread_result_count", 0) + 1

    department_session_id = str(payload.get("department_session_id", "")).strip()
    if department_session_id:
        department_session = get_session(department_session_id, SESSION_KIND_DEPARTMENT)
        if department_session is not None:
            department_session["report_status"] = "reported"
            department_session["reported_at"] = result["reported_at"]
            department_session["last_report_id"] = result_id
            department_session["auto_closed"] = close_session_process(department_session_id)
    notification = auto_notify_zhongshu(parent_session_id, result)
    result["auto_notification"] = notification
    return result


def collect_mailbox_results(zhongshu_session_id: str) -> list[dict]:
    require_zhongshu_session(zhongshu_session_id, active_only=False)
    collected = []
    for item in read_mailbox_items(zhongshu_session_id, archive=True):
        payload = item.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"summary": str(payload)}
        payload["parent_session_id"] = payload.get("parent_session_id") or zhongshu_session_id
        payload.setdefault("reported_at", now_text())
        collected.append(
            register_result(
                zhongshu_session_id,
                payload,
                source="mailbox",
                mailbox_file=item.get("archived_to") or item.get("mailbox_file"),
                mark_unread=True,
            )
        )
    return collected


def zhongshu_inbox_payload(session_id: str, *, mark_read: bool) -> dict:
    session = require_zhongshu_session(session_id, active_only=False)
    collect_mailbox_results(session_id)
    reports = [result_public(item) for item in REPORTS_BY_ZHONGSHU.get(session_id, [])]
    unread = [item for item in reports if not item.get("read")]
    read = [item for item in reports if item.get("read")]
    response_unread = list(unread)
    response_read = list(read)
    if mark_read and unread:
        for item in REPORTS_BY_ZHONGSHU.get(session_id, []):
            item["read"] = True
        session["unread_result_count"] = 0
        response_read = [result_public(item) for item in REPORTS_BY_ZHONGSHU.get(session_id, []) if item.get("read")]
    running_departments = [
        session_public(child)
        for child in parent_children(session_id)
        if child.get("status") == "running"
    ]
    completed_departments = [
        session_public(child)
        for child in parent_children(session_id)
        if child.get("status") != "running"
    ]
    queued_departments = [item for item in queue_snapshot() if item.get("parent_session_id") == session_id]
    return {
        "ok": True,
        "session": session_public(session),
        "unread_results": response_unread,
        "read_results": response_read,
        "running_departments": running_departments,
        "completed_departments": completed_departments,
        "queued_departments": queued_departments,
        "unread_count": session.get("unread_result_count", 0),
    }


def validate_model(model: str | None, fallback: str) -> str:
    if not model:
        return fallback
    if model not in MODEL_CHOICES:
        raise ValueError(f"unknown model: {model}")
    return model


def session_snapshot() -> list[dict]:
    refresh_sessions()
    with STATE_LOCK:
        pump_assignment_queue()
    return [session_public(session) for session in SESSIONS]


def start_codex_terminal(
    prompt: str,
    prefix: str,
    title: str | None = None,
    model: str | None = None,
    *,
    session_kind: str,
    parent_session_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    if session_kind == SESSION_KIND_DEPARTMENT and active_department_count() >= MAX_CODEX_TERMINALS:
        raise ValueError(f"active Codex terminals limit reached: {MAX_CODEX_TERMINALS}")
    selected_model = validate_model(model, ZHONGSHU_MODEL if session_kind == SESSION_KIND_ZHONGSHU else DEPARTMENT_MODEL)
    resolved_session_id = session_id or new_session_id(prefix)
    mailbox = None
    if session_kind == SESSION_KIND_ZHONGSHU:
        mailbox = ensure_zhongshu_mailbox(resolved_session_id)
    elif parent_session_id:
        mailbox = ensure_zhongshu_mailbox(parent_session_id)
    prompt_path = write_prompt(prefix, prompt)
    repo = str(REPO_ROOT)
    window_title = f"Codex {title or prefix} [{selected_model}]"
    script = (
        f"$Host.UI.RawUI.WindowTitle = {ps_quote(window_title)}; "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"python -X utf8 {ps_quote(str(RUNNER))} "
        f"--model {ps_quote(selected_model)} "
        f"--repo {ps_quote(repo)} "
        f"--prompt-file {ps_quote(str(prompt_path))} "
        f"--title {ps_quote(window_title)}"
    )
    process = subprocess.Popen(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=REPO_ROOT,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    ACTIVE_PROCESSES.append(process)
    session = {
        "id": resolved_session_id,
        "department": prefix,
        "role": session_kind,
        "session_kind": session_kind,
        "title": title or prefix,
        "pid": process.pid,
        "model": selected_model,
        "prompt_path": str(prompt_path),
        "window_title": window_title,
        "status": "running",
        "started_at": now_text(),
        "ended_at": None,
        "_process": process,
    }
    if session_kind == SESSION_KIND_ZHONGSHU:
        session["unread_result_count"] = 0
        session["child_department_ids"] = []
        REPORTS_BY_ZHONGSHU.setdefault(resolved_session_id, [])
    if parent_session_id:
        session["parent_session_id"] = parent_session_id
    if session_kind == SESSION_KIND_DEPARTMENT:
        session["report_status"] = "pending"
        session["reported_at"] = None
    if mailbox:
        session["mailbox"] = mailbox
    SESSIONS.insert(0, session)
    if parent_session_id:
        parent = require_zhongshu_session(parent_session_id, active_only=False)
        child_ids = parent.setdefault("child_department_ids", [])
        if resolved_session_id not in child_ids:
            child_ids.append(resolved_session_id)
    return {
        "ok": True,
        "prompt_path": str(prompt_path),
        "pid": process.pid,
        "active": active_department_count(),
        "active_zhongshu_sessions": active_zhongshu_count(),
        "active_department_sessions": active_department_count(),
        "active_sessions_total": active_session_count(),
        "session": session_public(session),
    }


def start_zhongshu_session(task: str, model: str | None = None) -> dict:
    task = normalize_task_text(task)
    session_id = new_session_id("zhongshu")
    PLANS_BY_ZHONGSHU[session_id] = {
        "session_id": session_id,
        "summary": "等待中书省回传分派方案。",
        "reported_at": None,
        "source": "launcher",
        "ready": False,
        "needs_confirmation": False,
        "assignments": [],
    }
    prompt = build_zhongshu_prompt(task, LAUNCHER_BASE_URL, session_id)
    result = start_codex_terminal(
        prompt,
        "zhongshu",
        "中书省",
        model,
        session_kind=SESSION_KIND_ZHONGSHU,
        session_id=session_id,
    )
    session = get_session(session_id, SESSION_KIND_ZHONGSHU)
    if session is not None:
        session["task"] = task
    return result


def build_zhongshu_resume_prompt(snapshot: dict, launcher_url: str, session_id: str) -> str:
    task = normalize_task_text(snapshot.get("task", "继续之前的中书省任务"))
    plan = snapshot.get("plan", {})
    reports = snapshot.get("reports", [])
    children = snapshot.get("children", [])
    report_summary = "；".join(
        f"{item.get('department', 'unknown')}:{item.get('summary', '无摘要')}" for item in reports[:5]
    ) or "暂无回传结果"
    child_summary = "；".join(
        f"{item.get('title', item.get('department', 'unknown'))}:{item.get('status', 'unknown')}" for item in children[:5]
    ) or "暂无下挂部门"
    plan_summary = normalize_task_text(plan.get("summary", "暂无分派方案"))
    return (
        f"你是 {PROJECT_NAME} 的中书省。恢复之前中断的任务：{task}。不要要求用户重述任务。"
        f"上一次分派方案：{plan_summary}。当前下挂部门状态：{child_summary}。最近回传摘要：{report_summary}。"
        f"继续{context_doc_instruction(include_related_docs=True)}，必要时再运行治理报告脚本。"
        f"如果还需要前端确认新的分派方案，就回传到 {launcher_url}/api/report_zhongshu_plan（session_id={session_id}）；否则继续监察部门执行和结果回传，收取结果只用 {launcher_url}/api/zhongshu_inbox?id={session_id}。"
    )


def restart_zhongshu_session(session_id: str, model: str | None = None) -> dict:
    snapshot = zhongshu_context_snapshot(session_id)
    old_session = require_zhongshu_session(session_id, active_only=False)
    task = normalize_task_text(snapshot.get("task", "") or old_session.get("task", "继续之前的中书省任务"))
    new_session_id_value = new_session_id("zhongshu")
    PLANS_BY_ZHONGSHU[new_session_id_value] = snapshot.get("plan", {}) or {
        "session_id": new_session_id_value,
        "summary": "恢复中书省上下文。",
        "reported_at": now_text(),
        "source": "resume",
        "ready": False,
        "needs_confirmation": False,
        "assignments": [],
    }
    REPORTS_BY_ZHONGSHU[new_session_id_value] = [
        {**item, "read": True, "_sort_key": time.time_ns()} for item in REPORTS_BY_ZHONGSHU.get(session_id, [])
    ]
    prompt = build_zhongshu_resume_prompt(snapshot, LAUNCHER_BASE_URL, new_session_id_value)
    result = start_codex_terminal(
        prompt,
        "zhongshu",
        "中书省",
        model or old_session.get("model") or ZHONGSHU_MODEL,
        session_kind=SESSION_KIND_ZHONGSHU,
        session_id=new_session_id_value,
    )
    new_session = get_session(new_session_id_value, SESSION_KIND_ZHONGSHU)
    if new_session is not None:
        new_session["task"] = task
        new_session["resumed_from_session_id"] = session_id
        new_session["resume_snapshot_summary"] = snapshot.get("plan", {}).get("summary", "")
    return result


def start_department_session(
    department: str,
    task: str,
    parent_session_id: str,
    model: str | None = None,
) -> dict:
    task = normalize_task_text(task)
    resolved_parent_session_id = resolve_parent_session_id(parent_session_id, active_only=True)
    department_session_id = new_session_id(department)
    prompt = build_department_prompt(
        department,
        task,
        resolved_parent_session_id,
        department_session_id,
        LAUNCHER_BASE_URL,
    )
    title = DEPARTMENT_PROMPTS[department][0]
    return start_codex_terminal(
        prompt,
        department,
        title,
        model,
        session_kind=SESSION_KIND_DEPARTMENT,
        parent_session_id=resolved_parent_session_id,
        session_id=department_session_id,
    )


def normalize_assignment(assignment: dict, default_parent_session_id: str | None = None) -> dict:
    department = str(assignment.get("department", "")).strip()
    task = normalize_task_text(str(assignment.get("task", "")).strip())
    if department not in DEPARTMENT_PROMPTS:
        raise ValueError(f"unknown department: {department}")
    if not task:
        raise ValueError("task is required")
    parent_session_id = resolve_parent_session_id(
        str(assignment.get("parent_session_id", default_parent_session_id or "")).strip()
    )
    fallback_model = str(assignment.get("model", DEPARTMENT_MODEL)).strip()
    model = validate_model(fallback_model, DEPARTMENT_MODEL)
    title = DEPARTMENT_PROMPTS[department][0]
    return {
        "department": department,
        "title": title,
        "task": task,
        "model": model,
        "parent_session_id": parent_session_id,
        "queued_at": now_text(),
    }


def start_assignment(assignment: dict) -> dict:
    return start_department_session(
        assignment["department"],
        assignment["task"],
        assignment["parent_session_id"],
        assignment["model"],
    )


def pump_assignment_queue() -> list[dict]:
    started = []
    while ASSIGNMENT_QUEUE and active_department_count() < MAX_CODEX_TERMINALS:
        started.append(start_assignment(ASSIGNMENT_QUEUE.pop(0)))
    return started


def queue_worker() -> None:
    while True:
        time.sleep(2)
        with STATE_LOCK:
            pump_assignment_queue()


def build_zhongshu_prompt(task: str, launcher_url: str, session_id: str) -> str:
    return (
        f"你是 {PROJECT_NAME} 的中书省。正式任务：{task}。不要要求用户重述任务。"
        f"{context_doc_instruction(include_related_docs=True)}，再运行治理报告脚本。"
        f"第一阶段只生成结构化分派方案并回传到 {launcher_url}/api/report_zhongshu_plan（session_id={session_id}），不要直接启动下属部门。"
        f"等前端确认后，再继续监察三部执行和结果回传；收取部门结果只用 {launcher_url}/api/zhongshu_inbox?id={session_id}。"
        f"如果下属部门出现 exceeded retry limit、429 Too Many Requests 或 request limit 报错，不要立刻拉满重试；先等待一段时间，再按原部门任务重试，并优先保持低并发。"
    )


def build_department_prompt(
    department: str,
    task: str,
    parent_session_id: str,
    department_session_id: str,
    launcher_url: str,
) -> str:
    title, duty = DEPARTMENT_PROMPTS[department]
    mailbox = ensure_zhongshu_mailbox(parent_session_id)
    return (
        f"你是 {PROJECT_NAME} 的{title}。正式任务：{task}。不要要求用户重述任务。职责：{duty}。"
        f"{context_doc_instruction(include_related_docs=False)}；再读取与你职责相关的文件，执行前先看 git status --short。"
        f"只处理本部门职责范围内文件，不要回滚用户或其他终端改动。完成后运行治理报告脚本。"
        f"然后优先把结果 POST 到 {launcher_url}/api/report_result，并带 parent_session_id={parent_session_id}、department_session_id={department_session_id}、department={department}；"
        f"若 HTTP 失败，再把同结构 JSON 写入 {mailbox['incoming']}。最终说明已改文件、已跑验证、未跑验证和剩余风险。"
    )


def build_assignment_task(department: dict, user_task: str, report: dict) -> str:
    files = "、".join(department["files"][:8]) or "无"
    verify = "；".join(department["verify"]) or "python tools/codex_governance/codex_governance.py"
    return (
        f"用户总任务：{normalize_task_text(user_task)}。"
        f"中书省分配给{department['title']}，职责：{department['duty']}。"
        f"优先关注这些文件：{files}。"
        f"建议验证：{verify}。"
        f"边界：只处理本部门职责内文件，不回滚用户或其他 Codex 终端改动。"
        f"当前报告共 {report['changed_count']} 个改动文件、{len(report['risks'])} 个风险。"
    )


def build_menxia_task(user_task: str, report: dict) -> str:
    risks = "；".join(f"[{risk['level']}] {risk['path']}: {risk['message']}" for risk in report["risks"]) or "未命中风险规则，但需抽查路径边界。"
    return (
        f"用户总任务：{normalize_task_text(user_task)}。"
        f"中书省判定当前存在需要门下省复核的风险。"
        f"复核重点：{risks}。"
        f"要求：只做风险复核和驳回建议，不直接修改业务文件，输出可执行的放行/驳回意见。"
    )


def recommended_model(department: dict, report: dict) -> tuple[str, str]:
    key = department["key"]
    files = department.get("files", [])
    risk_levels = {risk["level"] for risk in report["risks"]}
    high_risk = "high" in risk_levels
    medium_risk = "medium" in risk_levels
    complex_change = report["changed_count"] >= 20 or len(files) >= 12

    if key == "menxia":
        return ZHONGSHU_MODEL, "门下省负责高风险复核，默认使用最强模型。"
    if high_risk:
        return ZHONGSHU_MODEL, "当前报告命中 high 风险，优先降低误判成本。"
    if complex_change and key in {"gongchengbu", "lingyubu"}:
        return ZHONGSHU_MODEL, "项目改动复杂且涉及高影响部门，使用最强模型。"
    if key in {"gongchengbu", "lingyubu"}:
        return DEPARTMENT_MODEL, "涉及工程或领域实现，错误成本较高。"
    if medium_risk and key == "gongchengbu":
        return DEPARTMENT_MODEL, "存在风险命中，测试复核需要更稳。"
    if len(files) >= 8:
        return DEPARTMENT_MODEL, "命中文件较多，需要更强上下文整合。"
    return DEPARTMENT_MODEL, "职责范围较窄，默认使用基础模型。"


def plan_assignments(user_task: str, report: dict) -> dict:
    assignments = []
    for department in report["departments"]:
        model, model_reason = recommended_model(department, report)
        assignments.append(
            {
                "department": department["key"],
                "title": department["title"],
                "duty": department["duty"],
                "files": department["files"],
                "model": model,
                "model_reason": model_reason,
                "task": build_assignment_task(department, user_task, report),
            }
        )

    menxia_required = any(risk["level"] in {"high", "medium"} for risk in report["risks"])
    if menxia_required:
        menxia_department = {"key": "menxia", "files": [risk["path"] for risk in report["risks"]]}
        model, model_reason = recommended_model(menxia_department, report)
        assignments.insert(
            0,
            {
                "department": "menxia",
                "title": "门下省",
                "duty": "风险复核、边界检查、必要时驳回",
                "files": [risk["path"] for risk in report["risks"]],
                "model": model,
                "model_reason": model_reason,
                "task": build_menxia_task(user_task, report),
            },
        )

    return {
        "summary": "中书省已按当前报告生成三部分派方案。",
        "menxia_required": menxia_required,
        "max_terminals": MAX_CODEX_TERMINALS,
        "max_department_sessions": MAX_CODEX_TERMINALS,
        "active_terminals": active_department_count(),
        "active_department_sessions": active_department_count(),
        "active_zhongshu_sessions": active_zhongshu_count(),
        "model_choices": MODEL_CHOICES,
        "zhongshu_model": ZHONGSHU_MODEL,
        "department_model": DEPARTMENT_MODEL,
        "assignments": assignments,
    }


def build_status_payload(*, include_session_lists: bool = True) -> dict:
    sessions = session_snapshot() if include_session_lists else []
    zhongshu_sessions = [session for session in sessions if session["session_kind"] == SESSION_KIND_ZHONGSHU]
    department_sessions = [session for session in sessions if session["session_kind"] == SESSION_KIND_DEPARTMENT]
    return {
        "ok": True,
        "api_version": API_VERSION,
        "repo": str(REPO_ROOT),
        "departments": DEPARTMENT_PROMPTS,
        "active_terminals": active_department_count(),
        "active_department_sessions": active_department_count(),
        "active_zhongshu_sessions": active_zhongshu_count(),
        "active_sessions_total": active_session_count(),
        "max_terminals": MAX_CODEX_TERMINALS,
        "max_department_sessions": MAX_CODEX_TERMINALS,
        "model_choices": MODEL_CHOICES,
        "zhongshu_model": ZHONGSHU_MODEL,
        "department_model": DEPARTMENT_MODEL,
        "queue": queue_snapshot(),
        "department_queue": queue_snapshot(),
        "sessions": sessions,
        "zhongshu_sessions": zhongshu_sessions,
        "department_sessions": department_sessions,
    }


def zhongshu_sessions_payload() -> dict:
    sessions = session_snapshot()
    zhongshu_sessions = []
    for session in sessions:
        if session["session_kind"] != SESSION_KIND_ZHONGSHU:
            continue
        child_sessions = [session_public(child) for child in parent_children(session["id"])]
        zhongshu_sessions.append(
            {
                **session,
                "child_departments": child_sessions,
                "queued_departments": [item for item in queue_snapshot() if item.get("parent_session_id") == session["id"]],
                "report_count": len(REPORTS_BY_ZHONGSHU.get(session["id"], [])),
            }
        )
    return {
        "ok": True,
        "active_zhongshu_sessions": active_zhongshu_count(),
        "active_department_sessions": active_department_count(),
        "max_department_sessions": MAX_CODEX_TERMINALS,
        "queue": queue_snapshot(),
        "zhongshu_sessions": zhongshu_sessions,
    }


def queue_assignments(assignments: list[dict]) -> dict:
    with STATE_LOCK:
        ASSIGNMENT_QUEUE.extend(assignments)
        started = pump_assignment_queue()
        queued = queue_snapshot()
        active = active_department_count()
    return {
        "ok": True,
        "started": started,
        "queued": queued,
        "queued_count": len(queued),
        "active": active,
        "active_department_sessions": active,
        "active_zhongshu_sessions": active_zhongshu_count(),
    }


class LauncherHandler(BaseHTTPRequestHandler):
    server_version = "CodexGovernanceLauncher/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/status":
            self.send_json(build_status_payload())
            return
        if parsed.path == "/api/sessions":
            self.send_json(build_status_payload())
            return
        if parsed.path == "/api/zhongshu_sessions":
            self.send_json(zhongshu_sessions_payload())
            return
        if parsed.path == "/api/zhongshu_inbox":
            session_id = str(query.get("id", [""])[0]).strip()
            if not session_id:
                self.send_json({"ok": False, "error": "id is required"}, 400)
                return
            mark_read = query.get("peek", ["0"])[0] not in {"1", "true", "yes"}
            self.send_json(zhongshu_inbox_payload(session_id, mark_read=mark_read))
            return
        if parsed.path == "/api/zhongshu_plan":
            session_id = str(query.get("id", [""])[0]).strip()
            if not session_id:
                self.send_json({"ok": False, "error": "id is required"}, 400)
                return
            self.send_json(zhongshu_plan_payload(session_id))
            return
        if parsed.path == "/api/zhongshu_context":
            session_id = str(query.get("id", [""])[0]).strip()
            if not session_id:
                self.send_json({"ok": False, "error": "id is required"}, 400)
                return
            self.send_json({"ok": True, "context": zhongshu_context_snapshot(session_id)})
            return
        if parsed.path == "/api/report":
            staged = query.get("mode", ["worktree"])[0] == "staged"
            base = query.get("base", [None])[0]
            report = codex_governance.build_report(base=base, staged=staged)
            self.send_json({"ok": True, "report": report})
            return
        self.send_json({"ok": False, "error": "unknown endpoint"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.send_json({"ok": False, "error": f"invalid json: {exc}"}, 400)
            return

        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/start_zhongshu", "/api/start_zhongshu_session"}:
                task = normalize_task_text(str(payload.get("task", "")).strip())
                if not task:
                    raise ValueError("task is required")
                model = validate_model(str(payload.get("model", ZHONGSHU_MODEL)).strip(), ZHONGSHU_MODEL)
                self.send_json(start_zhongshu_session(task, model))
                return

            if parsed.path == "/api/restart_zhongshu_session":
                session_id = str(payload.get("session_id", "")).strip()
                if not session_id:
                    raise ValueError("session_id is required")
                model = validate_model(str(payload.get("model", ZHONGSHU_MODEL)).strip(), ZHONGSHU_MODEL)
                self.send_json(restart_zhongshu_session(session_id, model))
                return

            if parsed.path == "/api/plan_assignments":
                task = normalize_task_text(str(payload.get("task", "")).strip())
                if not task:
                    raise ValueError("task is required")
                report = codex_governance.build_report(base=None, staged=False)
                self.send_json({"ok": True, "plan": plan_assignments(task, report), "report": report})
                return

            if parsed.path in {"/api/start_department", "/api/start_department_for_zhongshu"}:
                department = str(payload.get("department", "")).strip()
                task = normalize_task_text(str(payload.get("task", "")).strip())
                if department not in DEPARTMENT_PROMPTS:
                    raise ValueError("unknown department")
                if not task:
                    raise ValueError("task is required")
                raw_parent_session_id = str(
                    payload.get("parent_session_id", payload.get("zhongshu_session_id", ""))
                ).strip()
                if parsed.path == "/api/start_department_for_zhongshu" and not raw_parent_session_id:
                    raise ValueError("parent_session_id is required")
                parent_session_id = resolve_parent_session_id(raw_parent_session_id)
                model = validate_model(str(payload.get("model", "")).strip(), DEPARTMENT_MODEL)
                self.send_json(start_department_session(department, task, parent_session_id, model))
                return

            if parsed.path == "/api/start_assignments":
                assignments = payload.get("assignments", [])
                if not isinstance(assignments, list):
                    raise ValueError("assignments must be a list")
                default_parent_session_id = str(
                    payload.get("parent_session_id", payload.get("zhongshu_session_id", ""))
                ).strip()
                normalized = [normalize_assignment(assignment, default_parent_session_id) for assignment in assignments]
                self.send_json(queue_assignments(normalized))
                return

            if parsed.path == "/api/report_result":
                parent_session_id = resolve_parent_session_id(
                    str(payload.get("parent_session_id", payload.get("zhongshu_session_id", ""))).strip(),
                    active_only=False,
                )
                department = str(payload.get("department", "unknown")).strip() or "unknown"
                report_payload = dict(payload)
                report_payload["parent_session_id"] = parent_session_id
                report_payload["department"] = department
                report_payload.setdefault("reported_at", now_text())
                archived_path = write_archive_item(parent_session_id, department, report_payload)
                result = register_result(
                    parent_session_id,
                    report_payload,
                    source="http",
                    mailbox_file=str(archived_path),
                    mark_unread=True,
                )
                self.send_json(
                    {
                        "ok": True,
                        "parent_session_id": parent_session_id,
                        "department": department,
                        "report": result_public(result),
                        "archive_file": str(archived_path),
                    }
                )
                return

            if parsed.path == "/api/report_zhongshu_plan":
                parent_session_id = resolve_parent_session_id(
                    str(payload.get("session_id", payload.get("parent_session_id", payload.get("zhongshu_session_id", "")))).strip(),
                    active_only=False,
                )
                plan_payload = dict(payload)
                plan_payload["session_id"] = parent_session_id
                plan_payload.setdefault("reported_at", now_text())
                plan = register_zhongshu_plan(parent_session_id, plan_payload, source="http")
                self.send_json({"ok": True, "session_id": parent_session_id, "plan": plan_public(plan)})
                return
        except (OSError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return

        self.send_json({"ok": False, "error": "unknown endpoint"}, 404)


def main() -> int:
    global LAUNCHER_BASE_URL
    parser = argparse.ArgumentParser(description="Start local Codex governance launcher.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6211)
    args = parser.parse_args()

    LAUNCHER_BASE_URL = f"http://127.0.0.1:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), LauncherHandler)
    threading.Thread(target=queue_worker, daemon=True).start()
    print(f"Codex governance launcher listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
