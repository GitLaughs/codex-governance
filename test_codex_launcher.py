import unittest
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_launcher


class ZhongshuPlanTests(unittest.TestCase):
    def setUp(self):
        codex_launcher.SESSIONS.clear()
        codex_launcher.REPORTS_BY_ZHONGSHU.clear()
        codex_launcher.PLANS_BY_ZHONGSHU.clear()
        codex_launcher.BROWSER_TERMINALS.clear()
        codex_launcher.ASSIGNMENT_QUEUE.clear()

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

        original_queue = codex_launcher.queue_assignments
        queued = []
        codex_launcher.queue_assignments = lambda assignments: queued.extend(assignments) or {
            "started": [],
            "queued_count": len(assignments),
            "active": 0,
        }
        try:
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
        finally:
            codex_launcher.queue_assignments = original_queue

        self.assertFalse(plan["needs_confirmation"])
        self.assertEqual(plan["summary"], "嵌套计划。")
        self.assertEqual(plan["assignments"][0]["department"], "zhilibu")
        self.assertEqual(plan["auto_dispatch"]["queued_count"], 1)
        self.assertEqual(queued[0]["parent_session_id"], session_id)

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

    def test_result_notification_allows_department_to_finish_after_mailbox(self):
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
                "summary": "已写入 mailbox。",
                "risks": ["需要中书省复核摘要。"],
                "next_action": "",
            },
        )

        self.assertIn("mailbox 回传即视为部门本轮结束", prompt)
        self.assertIn("无需继续观察该部门终端", prompt)
        self.assertNotIn("观察窗", prompt)
        self.assertNotIn("终端无新输出", prompt)

    def test_start_zhongshu_starts_browser_terminal(self):
        original_start_codex = codex_launcher.start_codex_terminal
        original_start_browser = codex_launcher.start_browser_terminal
        browser_started = []

        def fake_start_codex(prompt, prefix, title, model, *, session_kind, parent_session_id=None, session_id=None):
            session = {
                "id": session_id,
                "session_kind": session_kind,
                "department": prefix,
                "title": title,
                "status": "running",
                "model": model or codex_launcher.ZHONGSHU_MODEL,
                "unread_result_count": 0,
                "child_department_ids": [],
            }
            codex_launcher.SESSIONS.insert(0, session)
            browser_started.append(True)
            return {
                "ok": True,
                "session": codex_launcher.session_public(session),
                "terminal": {
                    "id": "browser-terminal-test",
                    "status": "running",
                    "scope": "session",
                    "kind": "codex_session",
                    "url": "http://127.0.0.1:54321/?token=abc",
                },
                "browser_terminal": {
                    "id": "browser-terminal-test",
                    "status": "running",
                    "scope": "session",
                    "kind": "codex_session",
                    "url": "http://127.0.0.1:54321/?token=abc",
                },
            }

        try:
            codex_launcher.start_codex_terminal = fake_start_codex
            result = codex_launcher.start_zhongshu_session("整理任务。")
        finally:
            codex_launcher.start_codex_terminal = original_start_codex
            codex_launcher.start_browser_terminal = original_start_browser

        self.assertTrue(result["ok"])
        self.assertEqual(result["browser_terminal"]["id"], "browser-terminal-test")
        self.assertEqual(browser_started, [True])

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
        self.assertIn("mailbox 回传即视为部门本轮结束", zhongshu_prompt)
        self.assertIn("写完 mailbox 后必须立即停止本部门会话", department_prompt)
        self.assertNotIn("观察窗", zhongshu_prompt)
        self.assertNotIn("观察窗", department_prompt)
        self.assertIn("跑最相关验证", department_prompt)

    def test_department_observation_interval_defaults_to_ninety_seconds(self):
        self.assertEqual(codex_launcher.DEPARTMENT_OBSERVATION_WAIT_MINUTES, 10)
        self.assertEqual(codex_launcher.DEPARTMENT_OBSERVATION_CHECK_SECONDS, 90)

    def test_department_report_auto_closes_running_session(self):
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
        self.assertEqual(child["status"], "exited")
        self.assertTrue(child["auto_closed"])
        self.assertEqual(child["auto_close_reason"], "mailbox_report_received")

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
                "ttyd_url": "http://127.0.0.1:7681/?arg=session",
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
        self.assertEqual(event["session"]["ttyd_url"], "http://127.0.0.1:7681/?arg=session")

    def test_build_status_payload_exposes_ttyd_capability(self):
        payload = codex_launcher.build_status_payload(include_session_lists=False)

        self.assertIn("ttyd", payload)
        self.assertIn("enabled", payload["ttyd"])
        self.assertIn("available", payload["ttyd"])
        self.assertIn("port", payload["ttyd"])

    def test_start_browser_terminal_uses_loopback_and_tokenized_url(self):
        started = []
        original_popen = codex_launcher.subprocess.Popen
        original_dir = codex_launcher.CODEX_TERMINAL_DIR

        class FakeProcess:
            pid = 2468
            stdout = iter(
                [
                    "[codex-terminal] shell=powershell.exe\n",
                    "[codex-terminal] cwd=E:\\repo\n",
                    "[codex-terminal] url=http://127.0.0.1:54321/?token=abc\n",
                ]
            )

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            started.append((command, kwargs))
            return FakeProcess()

        with tempfile.TemporaryDirectory() as tmp:
            terminal_dir = Path(tmp)
            (terminal_dir / "node_modules").mkdir()
            try:
                codex_launcher.subprocess.Popen = fake_popen
                codex_launcher.CODEX_TERMINAL_DIR = terminal_dir
                result = codex_launcher.start_browser_terminal()
            finally:
                codex_launcher.subprocess.Popen = original_popen
                codex_launcher.CODEX_TERMINAL_DIR = original_dir
                codex_launcher.BROWSER_TERMINALS.clear()

        self.assertTrue(result["ok"])
        self.assertEqual(result["terminal"]["host"], "127.0.0.1")
        self.assertEqual(result["terminal"]["url"], "http://127.0.0.1:54321/?token=abc")
        self.assertEqual(started[0][0], ["node", "server.js", "--host", "127.0.0.1", "--port", "0"])
        self.assertEqual(started[0][1]["env"]["CODEX_TERMINAL_HOST"], "127.0.0.1")
        self.assertEqual(started[0][1]["env"]["CODEX_TERMINAL_PORT"], "0")

    def test_build_session_preview_shell_args_tails_transcript_log(self):
        shell_args = codex_launcher.build_session_preview_shell_args(
            Path("E:/repo/.tmp/session.log"),
            "中书省",
        )

        self.assertTrue(shell_args.startswith("-NoLogo -NoProfile -EncodedCommand "))
        encoded = shell_args.split(" ", 3)[-1]
        decoded = codex_launcher.base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("Get-Content", decoded)
        self.assertIn("-Wait", decoded)
        self.assertIn("-Tail 80", decoded)
        self.assertIn("session.log", decoded)
        self.assertIn("中书省", decoded)

    def test_start_session_browser_terminal_uses_loopback_and_updates_session(self):
        started = []
        original_popen = codex_launcher.subprocess.Popen
        original_dir = codex_launcher.CODEX_TERMINAL_DIR
        session_id = "zhongshu-preview"
        codex_launcher.SESSIONS.append(
            {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                "department": "zhongshu",
                "title": "中书省",
                "status": "running",
                "model": "gpt-5.5",
                "pid": 321,
                "log_path": "E:/repo/.tmp/zhongshu.log",
            }
        )

        class FakeProcess:
            pid = 2468
            stdout = iter(
                [
                    "[codex-terminal] shell=powershell.exe\n",
                    "[codex-terminal] cwd=E:\\repo\n",
                    "[codex-terminal] url=http://127.0.0.1:54321/?token=session-preview\n",
                ]
            )

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            started.append((command, kwargs))
            return FakeProcess()

        with tempfile.TemporaryDirectory() as tmp:
            terminal_dir = Path(tmp)
            (terminal_dir / "node_modules").mkdir()
            try:
                codex_launcher.subprocess.Popen = fake_popen
                codex_launcher.CODEX_TERMINAL_DIR = terminal_dir
                result = codex_launcher.start_session_browser_terminal(session_id)
            finally:
                codex_launcher.subprocess.Popen = original_popen
                codex_launcher.CODEX_TERMINAL_DIR = original_dir
                codex_launcher.BROWSER_TERMINALS.clear()
                codex_launcher.SESSIONS.clear()

        self.assertTrue(result["ok"])
        self.assertEqual(result["terminal"]["host"], "127.0.0.1")
        self.assertEqual(result["terminal"]["session_id"], session_id)
        self.assertEqual(result["terminal"]["url"], "http://127.0.0.1:54321/?token=session-preview")
        self.assertEqual(started[0][0], ["node", "server.js", "--host", "127.0.0.1", "--port", "0"])
        self.assertEqual(started[0][1]["env"]["CODEX_TERMINAL_HOST"], "127.0.0.1")
        self.assertEqual(started[0][1]["env"]["CODEX_TERMINAL_PORT"], "0")
        self.assertEqual(started[0][1]["env"]["CODEX_TERMINAL_SHELL"], "powershell.exe")
        self.assertIn("EncodedCommand", started[0][1]["env"]["CODEX_TERMINAL_SHELL_ARGS"])
        self.assertEqual(started[0][1]["env"]["CODEX_TERMINAL_READ_ONLY"], "1")
        self.assertTrue(result["terminal"]["read_only"])

    def test_build_ttyd_command_uses_cwd_port_and_defaults_read_only(self):
        command = codex_launcher.build_ttyd_command(Path("E:/repo"), 7685)

        self.assertEqual(command[:5], ["ttyd", "-p", "7685", "-w", "E:\\repo"])
        self.assertNotIn("-W", command)
        self.assertGreater(len(command), 5)

    def test_build_ttyd_command_can_enable_writable_flag(self):
        original_writable = codex_launcher.TTYD_WRITABLE
        try:
            codex_launcher.TTYD_WRITABLE = True
            command = codex_launcher.build_ttyd_command(Path("E:/repo"), 7685)
        finally:
            codex_launcher.TTYD_WRITABLE = original_writable

        self.assertIn("-W", command)

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

    def test_reported_running_department_does_not_block_assignment_queue(self):
        parent_session_id = "zhongshu-queue-slots"
        codex_launcher.SESSIONS.extend(
            [
                {
                    "id": parent_session_id,
                    "session_kind": codex_launcher.SESSION_KIND_ZHONGSHU,
                    "status": "running",
                    "child_department_ids": ["menxia-reported", "gongchengbu-pending"],
                },
                {
                    "id": "menxia-reported",
                    "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                    "department": "menxia",
                    "title": "门下省",
                    "status": "running",
                    "report_status": "reported",
                    "parent_session_id": parent_session_id,
                },
                {
                    "id": "gongchengbu-pending",
                    "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                    "department": "gongchengbu",
                    "title": "工程部",
                    "status": "running",
                    "report_status": "pending",
                    "parent_session_id": parent_session_id,
                },
            ]
        )
        queued = [
            codex_launcher.normalize_assignment(
                {"department": "gongchengbu", "task": "修复 launcher 队列。"},
                default_parent_session_id=parent_session_id,
            ),
            codex_launcher.normalize_assignment(
                {"department": "menxia", "task": "复核 launcher 队列。"},
                default_parent_session_id=parent_session_id,
            ),
        ]
        codex_launcher.ASSIGNMENT_QUEUE.extend(queued)
        original_start = codex_launcher.start_department_session
        started = []

        def fake_start(department, task, parent, model=None):
            session_id = f"{department}-started"
            session = {
                "id": session_id,
                "session_kind": codex_launcher.SESSION_KIND_DEPARTMENT,
                "department": department,
                "title": codex_launcher.DEPARTMENT_PROMPTS[department][0],
                "status": "running",
                "report_status": "pending",
                "parent_session_id": parent,
                "model": model,
            }
            codex_launcher.SESSIONS.insert(0, session)
            started.append(session)
            return {"ok": True, "session": session}

        try:
            codex_launcher.start_department_session = fake_start
            result = codex_launcher.pump_assignment_queue()
        finally:
            codex_launcher.start_department_session = original_start

        self.assertEqual(len(result), 1)
        self.assertEqual(started[0]["department"], "gongchengbu")
        self.assertEqual(codex_launcher.active_department_count(), codex_launcher.MAX_CODEX_TERMINALS)
        self.assertEqual(len(codex_launcher.ASSIGNMENT_QUEUE), 1)

    def test_codex_runner_uses_terminal_stdout_with_transcript_log(self):
        script = codex_launcher.build_codex_runner_script(
            "Codex 中书省 [gpt-5.5]",
            "gpt-5.5",
            Path("E:/repo"),
            Path("E:/repo/.tmp/prompt.txt"),
            Path("E:/repo/.tmp/session.log"),
        )

        self.assertIn("Start-Transcript", script)
        self.assertIn("-Append", script)
        self.assertIn("run_codex_prompt.py", script)
        self.assertNotIn("stdout=subprocess.PIPE", Path(codex_launcher.RUNNER).read_text(encoding="utf-8"))

    def test_start_codex_terminal_uses_browser_terminal_and_attaches_ttyd_url(self):
        started_commands = []
        original_popen = codex_launcher.subprocess.Popen
        original_probe = codex_launcher.probe_ttyd
        original_available = codex_launcher.TTYD_AVAILABLE
        original_enabled = codex_launcher.TTYD_ENABLED
        original_port = codex_launcher.TTYD_PORT
        original_base_url = codex_launcher.TTYD_BASE_URL
        original_terminal_dir = codex_launcher.CODEX_TERMINAL_DIR

        class FakeProcess:
            def __init__(self, pid, stdout=None):
                self.pid = pid
                self.stdout = stdout

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            started_commands.append(command)
            if command[0] == "node":
                return FakeProcess(
                    9876,
                    iter(
                        [
                            "[codex-terminal] shell=powershell.exe\n",
                            "[codex-terminal] cwd=E:\\repo\n",
                            "[codex-terminal] url=http://127.0.0.1:54321/?token=codex\n",
                        ]
                    ),
                )
            return FakeProcess(7654)

        with tempfile.TemporaryDirectory() as tmp:
            terminal_dir = Path(tmp)
            (terminal_dir / "node_modules").mkdir()
            try:
                codex_launcher.subprocess.Popen = fake_popen
                codex_launcher.probe_ttyd = lambda force=False: {
                    "enabled": True,
                    "available": True,
                    "port": 7681,
                    "base_url": "http://127.0.0.1:7681",
                    "command": "ttyd",
                }
                codex_launcher.CODEX_TERMINAL_DIR = terminal_dir
                codex_launcher.TTYD_AVAILABLE = True
                codex_launcher.TTYD_ENABLED = True
                codex_launcher.TTYD_PORT = 7681
                codex_launcher.TTYD_BASE_URL = "http://127.0.0.1:7681"

                result = codex_launcher.start_codex_terminal(
                    "测试 ttyd",
                    "gongchengbu",
                    "工程部",
                    "gpt-5.4",
                    session_kind=codex_launcher.SESSION_KIND_DEPARTMENT,
                )
            finally:
                codex_launcher.subprocess.Popen = original_popen
                codex_launcher.probe_ttyd = original_probe
                codex_launcher.CODEX_TERMINAL_DIR = original_terminal_dir
                codex_launcher.TTYD_AVAILABLE = original_available
                codex_launcher.TTYD_ENABLED = original_enabled
                codex_launcher.TTYD_PORT = original_port
                codex_launcher.TTYD_BASE_URL = original_base_url
                codex_launcher.SESSIONS.clear()
                codex_launcher.ACTIVE_PROCESSES.clear()
                codex_launcher.BROWSER_TERMINALS.clear()

        self.assertTrue(result["ok"])
        self.assertEqual(result["browser_terminal"]["kind"], "codex_session")
        self.assertEqual(result["browser_terminal"]["scope"], "session")
        self.assertEqual(result["browser_terminal"]["url"], "http://127.0.0.1:54321/?token=codex")
        self.assertEqual(result["session"]["ttyd_url"], "http://127.0.0.1:7681/")
        self.assertEqual(len(started_commands), 2)
        self.assertEqual(started_commands[0], ["node", "server.js", "--host", "127.0.0.1", "--port", "0"])
        self.assertEqual(started_commands[1][:5], ["ttyd", "-p", "7681", "-w", str(codex_launcher.REPO_ROOT)])

    def test_dashboard_history_uses_scrollable_session_history(self):
        dashboard = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")

        self.assertIn('class="session-history-scroll"', dashboard)
        self.assertIn(".session-history-scroll", dashboard)
        self.assertIn("overflow-y: auto", dashboard)

    def test_dashboard_terminal_viewer_is_removed_for_rebuild(self):
        dashboard = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")

        self.assertNotIn("@xterm/xterm", dashboard)
        self.assertNotIn("session-terminal", dashboard)
        self.assertNotIn("EventSource", dashboard)
        self.assertNotIn("/api/session_stream", dashboard)
        self.assertNotIn("open-session-ttyd", dashboard)

    def test_dashboard_exposes_session_browser_preview_controls(self):
        dashboard = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")

        self.assertNotIn("data-open-session-preview", dashboard)
        self.assertNotIn("data-select-browser-terminal", dashboard)
        self.assertNotIn("/api/session_browser_terminal/start", dashboard)
        self.assertIn("selectedBrowserTerminalId", dashboard)
        self.assertNotIn('id="terminal-switcher"', dashboard)
        self.assertIn('id="browser-terminal-grid"', dashboard)
        self.assertIn("terminalSlotCount = 3", dashboard)
        self.assertIn("function ensureTerminalSlots", dashboard)
        self.assertIn("function orderedRunningTerminals", dashboard)
        self.assertNotIn("function renderTerminalSwitcher", dashboard)
        self.assertIn("function terminalFromSession", dashboard)
        self.assertIn("function mergeBrowserTerminals", dashboard)

    def test_dashboard_places_browser_terminal_before_session_list(self):
        dashboard = (Path(__file__).resolve().parent / "dashboard.html").read_text(encoding="utf-8")

        self.assertLess(dashboard.index('class="browser-terminal-shell"'), dashboard.index('class="session-shell"'))
        self.assertIn("width: min(100%, 1440px)", dashboard)
        self.assertIn("justify-items: stretch", dashboard)
        self.assertIn(".browser-terminal-shell", dashboard)
        self.assertIn(".browser-terminal-card", dashboard)
        self.assertIn("grid-template-columns: 1fr", dashboard)
        self.assertIn("height: clamp(520px, 68vh, 860px)", dashboard)

    def test_browser_terminal_page_uses_stable_full_height_fit(self):
        terminal_page = (codex_launcher.REPO_ROOT / "tools" / "codex_terminal" / "public" / "index.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("overflow: hidden", terminal_page)
        self.assertIn("flex: 1 1 auto", terminal_page)
        self.assertIn("padding: 0", terminal_page)
        self.assertIn("ResizeObserver", terminal_page)
        self.assertIn("disableStdin = true", terminal_page)
        self.assertIn("cursorBlink: false", terminal_page)
        self.assertIn("cursorBlink = false", terminal_page)
        self.assertNotIn("term.focus();", terminal_page)
        self.assertNotIn("cursorBlink = true", terminal_page)
        self.assertIn("convertEol: false", terminal_page)
        self.assertNotIn("convertEol: true", terminal_page)

    def test_browser_terminal_server_marks_read_only_sessions(self):
        server = (codex_launcher.REPO_ROOT / "tools" / "codex_terminal" / "server.js").read_text(encoding="utf-8")

        self.assertIn("CODEX_TERMINAL_READ_ONLY", server)
        self.assertIn("readOnly", server)
        self.assertIn("只读预览终端不接收输入", server)
        self.assertIn("term.onExit", server)
        self.assertIn("shutdown();", server)

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

    def test_department_report_writes_handoff_packet(self):
        parent_session_id = "zhongshu-handoff"
        department_session_id = "gongchengbu-handoff"
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
                    "department": "gongchengbu",
                    "title": "工程部",
                    "status": "exited",
                    "parent_session_id": parent_session_id,
                    "report_status": "pending",
                    "task": "增强治理交接。",
                },
            ]
        )
        original_notify = codex_launcher.auto_notify_zhongshu
        codex_launcher.auto_notify_zhongshu = lambda parent, result: {"ok": True, "status": "test"}
        try:
            report = codex_launcher.register_result(
                parent_session_id,
                {
                    "department_session_id": department_session_id,
                    "department": "gongchengbu",
                    "summary": "已补 handoff。",
                    "changed_files": ["tools/codex_governance/codex_launcher.py"],
                    "verification": ["python -m unittest tools.codex_governance.test_codex_launcher"],
                    "risks": ["仍需中书省复核。"],
                    "next_action": "中书省读取交接包后决定是否续派。",
                },
                source="mailbox",
            )
        finally:
            codex_launcher.auto_notify_zhongshu = original_notify

        handoff_path = Path(report["handoff_packet"])
        self.addCleanup(lambda: handoff_path.unlink(missing_ok=True))
        self.assertTrue(handoff_path.exists())
        packet = handoff_path.read_text(encoding="utf-8")
        self.assertIn("# Codex Department Handoff", packet)
        self.assertIn("department_session_id: gongchengbu-handoff", packet)
        self.assertIn("## Verification", packet)
        self.assertIn("python -m unittest tools.codex_governance.test_codex_launcher", packet)
        self.assertIn("## Next Action", packet)


if __name__ == "__main__":
    unittest.main()
