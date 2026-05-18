import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_launcher


class ZhongshuPlanTests(unittest.TestCase):
    def setUp(self):
        codex_launcher.SESSIONS.clear()
        codex_launcher.REPORTS_BY_ZHONGSHU.clear()
        codex_launcher.PLANS_BY_ZHONGSHU.clear()

    def test_empty_plan_does_not_require_confirmation(self):
        session_id = "zhongshu-test-empty"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
            }
        )

        plan = codex_launcher.register_zhongshu_plan(
            session_id,
            {"summary": "中书省自己处理。", "assignments": []},
            source="test",
        )

        self.assertTrue(plan["ready"])
        self.assertFalse(plan["needs_confirmation"])
        self.assertEqual(plan["assignments"], [])

    def test_nested_plan_assignments_are_accepted(self):
        session_id = "zhongshu-test-nested"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
            }
        )

        plan = codex_launcher.register_zhongshu_plan(
            session_id,
            {
                "plan": {
                    "summary": "嵌套计划。",
                    "assignments": [
                        {
                            "department": "zhilibu",
                            "task": "更新文档。",
                        }
                    ],
                }
            },
            source="test",
        )

        self.assertTrue(plan["needs_confirmation"])
        self.assertEqual(plan["summary"], "嵌套计划。")
        self.assertEqual(plan["assignments"][0]["department"], "zhilibu")

    def test_auto_notify_starts_fallback_session_when_window_missing(self):
        parent_session_id = "zhongshu-test-notify"
        started = []
        codex_launcher.SESSIONS.append(
            {
                "id": parent_session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
                "model": "gpt-5.5",
                "window_title": "missing window",
                "pid": 1234,
                "unread_result_count": 0,
                "child_department_ids": [],
            }
        )

        original_send = codex_launcher.send_prompt_to_window
        original_start = codex_launcher.start_codex_terminal

        def fake_send(window_title, prompt, process_id=None):
            return False, "window not found"

        def fake_start(prompt, prefix, title, model, *, session_kind, parent_session_id=None, session_id=None):
            session = {
                "id": "zhongshu-notify-test",
                "session_kind": session_kind,
                "department": prefix,
                "title": title,
                "status": "running",
                "model": model,
            }
            codex_launcher.SESSIONS.insert(0, session)
            started.append(prompt)
            return {"ok": True, "session": session}

        try:
            codex_launcher.send_prompt_to_window = fake_send
            codex_launcher.start_codex_terminal = fake_start
            notification = codex_launcher.auto_notify_zhongshu(
                parent_session_id,
                {
                    "id": "report-1",
                    "department": "zhilibu",
                    "summary": "已完成。",
                    "risks": [],
                },
            )
        finally:
            codex_launcher.send_prompt_to_window = original_send
            codex_launcher.start_codex_terminal = original_start

        self.assertTrue(notification["ok"])
        self.assertEqual(notification["status"], "fallback_started")
        self.assertEqual(notification["fallback_session"]["id"], "zhongshu-notify-test")
        self.assertIn("/api/zhongshu_inbox?id=zhongshu-test-notify", started[0])
        parent = codex_launcher.get_session(parent_session_id, codex_launcher.SESSION_KIND_ZHONGSHU)
        self.assertEqual(parent["auto_notification_status"], "fallback_started")

    def test_result_notification_prompt_is_concise(self):
        codex_launcher.SESSIONS.append(
            {
                "id": "zhongshu-test-short",
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
            }
        )

        prompt = codex_launcher.build_zhongshu_result_prompt(
            "zhongshu-test-short",
            {
                "department": "zhilibu",
                "summary": "长摘要" * 300,
                "risks": ["长风险" * 300],
                "next_action": "长动作" * 300,
            },
        )

        self.assertLess(len(prompt), 1000)
        self.assertIn("读完整结果", prompt)
        self.assertIn("/api/zhongshu_inbox?id=zhongshu-test-short", prompt)

    def test_result_notification_forces_continuation_when_work_remains(self):
        codex_launcher.SESSIONS.append(
            {
                "id": "zhongshu-test-continue",
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
            }
        )

        prompt = codex_launcher.build_zhongshu_result_prompt(
            "zhongshu-test-continue",
            {
                "department": "gongchengbu",
                "summary": "当前只是 xterm 显示层，不是真 PTY。",
                "risks": ["还需要 websocket 或 stream 接口。"],
                "next_action": "继续分派工程部实现真实输入输出。",
            },
        )

        self.assertIn("部门回传非最终", prompt)
        self.assertIn("继续推进或回传", prompt)
        self.assertIn("续派 1-2 个最有价值部门", prompt)
        self.assertIn("勿闲置空位", prompt)
        self.assertIn("部门回传不等于部门结束", prompt)
        self.assertIn("不得因收到一次回传就终止运行中的下属部门", prompt)
        self.assertIn("至少保留 10 分钟观察窗", prompt)
        self.assertIn("每 1-2 分钟检查一次 inbox/终端", prompt)
        self.assertIn("终端无新输出、会话退出或明确报错", prompt)
        self.assertIn("report_zhongshu_plan", prompt)

    def test_department_prompt_uses_mailbox_only_report(self):
        parent_session_id = "zhongshu-test-report"
        prompt = codex_launcher.build_department_prompt(
            "zhilibu",
            "测试回传。",
            parent_session_id,
            "zhilibu-test",
            "http://127.0.0.1:6211",
        )

        self.assertIn("回传只写 mailbox JSON", prompt)
        self.assertIn("ConvertTo-Json -Depth 8", prompt)
        self.assertIn("WriteAllText", prompt)
        self.assertIn("[System.Text.UTF8Encoding]::new($false)", prompt)
        self.assertNotIn("/api/" + "report_" + "result", prompt)
        self.assertNotIn("Invoke-" + "RestMethod", prompt)

    def test_prompts_push_efficient_execution(self):
        zhongshu_prompt = codex_launcher.build_zhongshu_prompt(
            "修一个小问题。",
            "http://127.0.0.1:6211",
            "zhongshu-efficient",
        )
        department_prompt = codex_launcher.build_department_prompt(
            "gongchengbu",
            "修一个小问题。",
            "zhongshu-efficient",
            "gongchengbu-efficient",
            "http://127.0.0.1:6211",
        )

        for prompt in (zhongshu_prompt, department_prompt):
            self.assertIn("大胆推进", prompt)
            self.assertIn("只读必要文件", prompt)
            self.assertIn("中高风险/公共接口才扩大验证", prompt)
            self.assertIn("明确失败、破坏性操作、越权文件或高风险合约问题", prompt)

        self.assertIn("合理使用最多 2 个部门空位", zhongshu_prompt)
        self.assertIn("同时派两个", zhongshu_prompt)
        self.assertIn("部门回传不等于部门结束", zhongshu_prompt)
        self.assertIn("部门回传不等于部门结束", department_prompt)
        self.assertIn("至少保留 10 分钟观察窗", zhongshu_prompt)
        self.assertIn("至少保留 10 分钟观察窗", department_prompt)
        self.assertIn("跑最相关验证", department_prompt)

    def test_department_observation_interval_defaults_to_ninety_seconds(self):
        self.assertEqual(codex_launcher.DEPARTMENT_OBSERVATION_WAIT_MINUTES, 10)
        self.assertEqual(codex_launcher.DEPARTMENT_OBSERVATION_CHECK_SECONDS, 90)

    def test_department_report_does_not_auto_close_running_session(self):
        parent_session_id = "zhongshu-preserve-child"
        department_session_id = "zhilibu-still-running"
        codex_launcher.SESSIONS.extend(
            [
                {
                    "id": parent_session_id,
                    "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                    "status": "running",
                    "unread_result_count": 0,
                    "child_department_ids": [department_session_id],
                },
                {
                    "id": department_session_id,
                    "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                    "department": "zhilibu",
                    "status": "running",
                    "report_status": "pending",
                    "parent_session_id": parent_session_id,
                },
            ]
        )
        original_notify = codex_launcher.auto_notify_zhongshu
        codex_launcher.auto_notify_zhongshu = lambda parent, result: {"ok": True, "status": "test"}
        try:
            codex_launcher.register_result(
                parent_session_id,
                {
                    "department_session_id": department_session_id,
                    "department": "zhilibu",
                    "summary": "阶段回传，继续检查文档事实。",
                },
                source="mailbox",
                mark_unread=True,
            )
        finally:
            codex_launcher.auto_notify_zhongshu = original_notify

        child = codex_launcher.get_session(department_session_id, codex_launcher.SESSION_KIND_DEPARTMENT)
        self.assertEqual(child["report_status"], "reported")
        self.assertEqual(child["status"], "running")
        self.assertFalse(child["auto_closed"])
        self.assertEqual(child["auto_close_reason"], "report_received_but_session_preserved")

    def test_restart_running_zhongshu_sends_prompt_to_original_session(self):
        session_id = "zhongshu-running"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
                "model": "gpt-5.5",
                "window_title": "Codex 中书省 [gpt-5.5]",
                "pid": 123,
                "task": "继续原任务。",
                "unread_result_count": 0,
                "child_department_ids": [],
            }
        )
        sent = []
        original_send = codex_launcher.send_prompt_to_window

        def fake_send(window_title, prompt, process_id=None):
            sent.append((window_title, prompt, process_id))
            return True, ""

        try:
            codex_launcher.send_prompt_to_window = fake_send
            result = codex_launcher.restart_zhongshu_session(session_id)
        finally:
            codex_launcher.send_prompt_to_window = original_send

        self.assertTrue(result["resumed_inline"])
        self.assertEqual(result["session"]["id"], session_id)
        self.assertEqual(sent[0][0], "Codex 中书省 [gpt-5.5]")
        self.assertEqual(sent[0][2], 123)
        self.assertIn("恢复任务", sent[0][1])

    def test_session_stream_event_includes_transcript_and_input_state(self):
        session_id = "zhongshu-stream"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "department": "zhongshu",
                "title": "中书省",
                "status": "running",
                "model": "gpt-5.5",
                "pid": 321,
                "prompt_path": "prompt.txt",
                "started_at": "2026-05-18 20:10:00",
                "unread_result_count": 1,
                "child_department_ids": [],
            }
        )

        event = codex_launcher.session_stream_event(session_id)

        self.assertTrue(event["ok"])
        self.assertEqual(event["session"]["id"], session_id)
        self.assertTrue(event["input_enabled"])
        self.assertIn("session: 中书省", event["transcript"])
        self.assertIn("unread: 1", event["transcript"])
        self.assertIn("transcript_preview", event["session"])
        self.assertIn("unread: 1", event["session"]["transcript_preview"])

    def test_send_session_input_posts_to_window_and_records_history(self):
        session_id = "zhongshu-input"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "status": "running",
                "model": "gpt-5.5",
                "window_title": "Codex 中书省 [gpt-5.5]",
                "pid": 456,
            }
        )
        sent = []
        original_send = codex_launcher.send_prompt_to_window

        def fake_send(window_title, prompt, process_id=None):
            sent.append((window_title, prompt, process_id))
            return True, ""

        try:
            codex_launcher.send_prompt_to_window = fake_send
            result = codex_launcher.send_session_input(session_id, "继续执行")
        finally:
            codex_launcher.send_prompt_to_window = original_send

        self.assertTrue(result["ok"])
        self.assertEqual(sent, [("Codex 中书省 [gpt-5.5]", "继续执行", 456)])
        session = codex_launcher.get_session(session_id)
        self.assertEqual(session["input_history"][-1]["text"], "继续执行")

    def test_session_snapshot_exposes_recent_transcript_preview(self):
        session_id = "gongchengbu-preview"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                "department": "gongchengbu",
                "title": "工程部",
                "status": "running",
                "model": "gpt-5.4",
                "pid": 654,
                "started_at": "2026-05-18 20:20:00",
                "report_status": "pending",
                "input_history": [
                    {"text": "先做最小改动", "sent_at": "2026-05-18 20:21:00"},
                    {"text": "补验证", "sent_at": "2026-05-18 20:22:00"},
                ],
            }
        )

        snapshot = codex_launcher.session_snapshot()

        self.assertEqual(snapshot[0]["id"], session_id)
        self.assertIn("transcript_preview", snapshot[0])
        self.assertIn("补验证", snapshot[0]["transcript_preview"])

    def test_session_stream_tails_real_terminal_log(self):
        session_id = "gongchengbu-log-tail"
        log_path = codex_launcher.SESSION_LOG_DIR / "test-gongchengbu-log-tail.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("old line\nlive output line\n", encoding="utf-8")
        self.addCleanup(lambda: log_path.unlink(missing_ok=True))
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                "department": "gongchengbu",
                "title": "工程部",
                "status": "running",
                "model": "gpt-5.4",
                "pid": 654,
                "started_at": "2026-05-18 20:20:00",
                "report_status": "pending",
                "log_path": str(log_path),
            }
        )

        event = codex_launcher.session_stream_event(session_id)

        self.assertIn("terminal output tail:", event["transcript"])
        self.assertIn("live output line", event["transcript"])
        self.assertIn("live output line", event["session"]["transcript_preview"])

    def test_exited_department_without_report_gets_launcher_fallback(self):
        parent_session_id = "zhongshu-missing-report"
        codex_launcher.SESSIONS.extend(
            [
                {
                    "id": parent_session_id,
                    "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                    "status": "running",
                    "model": "gpt-5.5",
                    "window_title": "missing",
                    "pid": 1,
                    "unread_result_count": 0,
                    "child_department_ids": ["gongchengbu-missing"],
                },
                {
                    "id": "gongchengbu-missing",
                    "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                    "department": "gongchengbu",
                    "status": "exited",
                    "report_status": "pending",
                    "parent_session_id": parent_session_id,
                    "ended_at": "2026-05-18 20:00:00",
                },
            ]
        )
        original_notify = codex_launcher.auto_notify_zhongshu
        codex_launcher.auto_notify_zhongshu = lambda parent, result: {"ok": True, "status": "test"}
        try:
            synthesized = codex_launcher.synthesize_missing_department_reports()
        finally:
            codex_launcher.auto_notify_zhongshu = original_notify

        self.assertEqual(len(synthesized), 1)
        self.assertEqual(synthesized[0]["source"], "launcher_fallback")
        self.assertIn("未写入 mailbox 回传", synthesized[0]["summary"])
        parent = codex_launcher.get_session(parent_session_id, codex_launcher.SESSION_KIND_ZHONGSHU)
        child = codex_launcher.get_session("gongchengbu-missing", codex_launcher.SESSION_KIND_DEPARTMENT)
        self.assertEqual(parent["unread_result_count"], 1)
        self.assertEqual(child["report_status"], "reported")

    def test_real_report_replaces_launcher_fallback(self):
        parent_session_id = "zhongshu-real-report"
        codex_launcher.SESSIONS.extend(
            [
                {
                    "id": parent_session_id,
                    "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                    "status": "running",
                    "unread_result_count": 0,
                    "child_department_ids": ["zhilibu-real"],
                },
                {
                    "id": "zhilibu-real",
                    "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                    "department": "zhilibu",
                    "status": "exited",
                    "report_status": "pending",
                    "parent_session_id": parent_session_id,
                },
            ]
        )
        original_notify = codex_launcher.auto_notify_zhongshu
        codex_launcher.auto_notify_zhongshu = lambda parent, result: {"ok": True, "status": "test"}
        try:
            codex_launcher.synthesize_missing_department_reports()
            report = codex_launcher.register_result(
                parent_session_id,
                {
                    "department_session_id": "zhilibu-real",
                    "department": "zhilibu",
                    "summary": "真实 mailbox 回传。",
                    "verification": ["python -m unittest"],
                },
                source="mailbox",
            )
        finally:
            codex_launcher.auto_notify_zhongshu = original_notify

        self.assertEqual(report["source"], "mailbox")
        self.assertEqual(report["summary"], "真实 mailbox 回传。")
        self.assertEqual(report["verifications_run"], ["python -m unittest"])


if __name__ == "__main__":
    unittest.main()
