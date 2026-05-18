import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_governance


class GovernancePreflightTests(unittest.TestCase):
    def test_portability_scan_flags_absolute_link_targets_but_allows_code_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            docs = repo / "docs" / "governance"
            docs.mkdir(parents=True)
            surface = docs / "authority.md"
            surface.write_text(
                "\n".join(
                    [
                        "# Authority",
                        "Bad link: [local](E:/private/output.txt)",
                        "Inline code is an example: `E:/SYMTH_files/output/evb/latest/`",
                        "```powershell",
                        "cd E:/See-you-more-than-her",
                        "```",
                    ]
                ),
                encoding="utf-8",
            )

            result = codex_governance.scan_portability(repo)

        self.assertEqual(len(result["violations"]), 1)
        self.assertEqual(result["violations"][0]["path"], "docs/governance/authority.md")
        self.assertEqual(result["violations"][0]["pattern"], "WINDOWS_DRIVE")
        self.assertGreaterEqual(len(result["exceptions"]), 2)

    def test_build_report_exposes_preflight_summary(self):
        report = codex_governance.build_report(base=None, staged=False)

        self.assertIn("preflight", report)
        self.assertIn("portability_reference_scan", report["preflight"]["checks"])
        portability = report["preflight"]["checks"]["portability_reference_scan"]
        self.assertIn("decision", portability)
        self.assertIn("violations", portability)


if __name__ == "__main__":
    unittest.main()
