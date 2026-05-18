import unittest

import codex_launcher


class LauncherPromptTests(unittest.TestCase):
    def test_default_prompts_do_not_require_missing_docs(self):
        prompts = [
            codex_launcher.build_zhongshu_prompt("publish", "http://127.0.0.1:6211", "zhongshu-1"),
            codex_launcher.build_zhongshu_resume_prompt(
                {
                    "task": "publish",
                    "plan": {"summary": "plan"},
                    "reports": [],
                    "children": [],
                },
                "http://127.0.0.1:6211",
                "zhongshu-2",
            ),
            codex_launcher.build_department_prompt(
                "zhilibu",
                "publish",
                "zhongshu-1",
                "zhilibu-1",
                "http://127.0.0.1:6211",
            ),
        ]

        for prompt in prompts:
            self.assertIn("README.md", prompt)
            self.assertIn("如存在", prompt)
            self.assertNotIn("先读取 README.md、AGENTS.md", prompt)
            self.assertNotIn("先读取 AGENTS.md、Codex governance workflow", prompt)


if __name__ == "__main__":
    unittest.main()
