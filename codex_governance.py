#!/usr/bin/env python3
"""Local Codex governance report for a Git repository."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent


def default_repo_root() -> Path:
    if SCRIPT_DIR.name == "codex_governance" and SCRIPT_DIR.parent.name == "tools":
        return SCRIPT_DIR.parents[1]
    return SCRIPT_DIR


REPO_ROOT = default_repo_root()


@dataclass(frozen=True)
class Department:
    key: str
    title: str
    duty: str
    globs: tuple[str, ...]
    verify: tuple[str, ...]


@dataclass(frozen=True)
class RiskRule:
    name: str
    level: str
    pattern: str
    message: str
    allow_pattern: str | None = None


DEFAULT_DEPARTMENTS = (
    Department(
        "zhilibu",
        "治理部",
        "任务拆分、代理规则、README、文档、发布说明",
        (
            "AGENTS.md",
            "CLAUDE.md",
            "README.md",
            "API.md",
            "CONTRIBUTING.md",
            "INDEPENDENT_RELEASE_PLAN.md",
            "SECURITY.md",
            "RELEASING.md",
            "LICENSE",
            "docs/**",
            "**/README.md",
        ),
        ("git status --short", "python codex_governance.py"),
    ),
    Department(
        "gongchengbu",
        "工程部",
        "launcher、前端、脚本、验证、回归、发布链路",
        ("*.py", "*.ps1", "*.html", "*.yaml", ".gitignore", "scripts/**", "tests/**", "**/tests/**", "tools/**"),
        (
            "python -m py_compile codex_governance.py codex_launcher.py run_codex_prompt.py",
            "python codex_governance.py --json",
        ),
    ),
    Department(
        "lingyubu",
        "领域部",
        "领域实现、业务代码、集成联调",
        (
            "src/**",
            "app/**",
            "packages/**",
            "data/**",
            "models/**",
        ),
        (
            "git status --short",
        ),
    ),
)


DEFAULT_RISK_RULES = (
    RiskRule("runtime_artifact", "high", "output/", "output 是构建产物，不应作为源码或提交对象"),
    RiskRule("secret_file", "high", ".env", "疑似环境变量或密钥文件，提交前需确认脱敏"),
    RiskRule("vendor_tree", "medium", "vendor/", "vendor 目录通常是外部导入，修改前需说明来源和边界"),
)


def config_path() -> Path:
    candidates = (
        REPO_ROOT / "governance.yaml",
        SCRIPT_DIR / "governance.yaml",
        REPO_ROOT / "tools" / "codex_governance" / "governance.yaml",
    )
    return next((path for path in candidates if path.exists()), candidates[0])


def load_yaml_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def departments_from_config(raw: dict) -> tuple[Department, ...]:
    configured = raw.get("departments")
    if not isinstance(configured, dict):
        return DEFAULT_DEPARTMENTS
    departments = []
    for key, value in configured.items():
        if not isinstance(value, dict):
            continue
        departments.append(
            Department(
                str(key),
                str(value.get("title", key)),
                str(value.get("duty", "")),
                tuple(str(item) for item in value.get("globs", []) if str(item).strip()),
                tuple(str(item) for item in value.get("verify", []) if str(item).strip()),
            )
        )
    return tuple(departments) or DEFAULT_DEPARTMENTS


def risks_from_config(raw: dict) -> tuple[RiskRule, ...]:
    configured = raw.get("risk_rules")
    if not isinstance(configured, list):
        return DEFAULT_RISK_RULES
    risks = []
    for item in configured:
        if not isinstance(item, dict):
            continue
        risks.append(
            RiskRule(
                str(item.get("name", "custom")),
                str(item.get("level", "medium")),
                str(item.get("pattern", "")),
                str(item.get("message", "")),
                str(item["allow_pattern"]) if item.get("allow_pattern") else None,
            )
        )
    return tuple(risk for risk in risks if risk.pattern) or DEFAULT_RISK_RULES


CONFIG = load_yaml_config()
DEPARTMENTS = departments_from_config(CONFIG)
RISK_RULES = risks_from_config(CONFIG)


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(stderr.strip() or stdout.strip())
    return stdout


def changed_paths(base: str | None, staged: bool) -> list[str]:
    if staged:
        raw = run_git(["diff", "--cached", "--name-only", "-z"])
        return sorted({entry.replace("\\", "/") for entry in raw.split("\0") if entry})
    elif base:
        raw = run_git(["diff", "--name-only", "-z", base])
        return sorted({entry.replace("\\", "/") for entry in raw.split("\0") if entry})
    else:
        raw = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        paths = []
        entries = raw.split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            status = entry[:2]
            path = entry[3:]
            if status.startswith("R") or status.startswith("C"):
                if index < len(entries):
                    path = entries[index]
                    index += 1
            paths.append(path.replace("\\", "/"))
        return sorted(set(paths))

    return sorted({line.strip().replace("\\", "/") for line in raw.splitlines() if line.strip()})


def matches(path: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/")
    return fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("*"))


def departments_for(path: str) -> list[Department]:
    hits = []
    for department in DEPARTMENTS:
        if any(matches(path, glob) for glob in department.globs):
            hits.append(department)
    return hits


def risks_for(path: str) -> list[RiskRule]:
    hits = []
    lowered = path.lower()
    for rule in RISK_RULES:
        pattern = rule.pattern.replace("\\", "/")
        if rule.allow_pattern and path.startswith(rule.allow_pattern):
            continue
        if pattern.lower() in lowered or path.startswith(pattern):
            hits.append(rule)
    return hits


def print_section(title: str) -> None:
    print(f"\n## {title}")


def build_report(base: str | None, staged: bool) -> dict:
    paths = changed_paths(base, staged)
    grouped: dict[str, list[str]] = {department.key: [] for department in DEPARTMENTS}
    uncategorized: list[str] = []
    all_risks: list[tuple[str, RiskRule]] = []
    verify_commands: set[str] = set()

    for path in paths:
        departments = departments_for(path)
        if not departments:
            uncategorized.append(path)
        for department in departments:
            grouped[department.key].append(path)
            verify_commands.update(department.verify)
        for risk in risks_for(path):
            all_risks.append((path, risk))

    return {
        "title": "Codex 三省三部治理报告",
        "mode": "staged" if staged else ("base" if base else "worktree"),
        "base": base,
        "changed_count": len(paths),
        "changed_paths": paths,
        "provinces": [
            {"key": "zhongshu", "title": "中书省", "duty": "任务拆分、范围判断、拟定执行计划"},
            {"key": "menxia", "title": "门下省", "duty": "风险复核、边界检查、必要时驳回"},
            {"key": "shangshu", "title": "尚书省", "duty": "按三部分派执行、验证、交付"},
        ],
        "departments": [
            {
                "key": department.key,
                "title": department.title,
                "duty": department.duty,
                "files": grouped[department.key],
                "verify": list(department.verify),
            }
            for department in DEPARTMENTS
            if grouped[department.key]
        ],
        "uncategorized": uncategorized,
        "risks": [
            {
                "path": path,
                "name": risk.name,
                "level": risk.level,
                "message": risk.message,
            }
            for path, risk in all_risks
        ],
        "verify_commands": sorted(verify_commands),
    }


def print_text_report(report: dict) -> None:
    paths = report["changed_paths"]
    print(f"# {report['title']}")

    if not paths:
        print("\n无待分析改动。")
        return

    print_section("中书省")
    print(f"- 改动文件数: {report['changed_count']}")
    print("- 任务: 按路径分派下属部门，并给出验证入口")

    print_section("门下省")
    if report["risks"]:
        for risk in report["risks"]:
            print(f"- [{risk['level']}] {risk['path']}: {risk['message']}")
    else:
        print("- 未命中高风险路径规则")

    print_section("尚书省")
    for department in report["departments"]:
        files = department["files"]
        print(f"- {department['title']}: {department['duty']} ({len(files)} files)")
        for path in files[:8]:
            print(f"  - {path}")
        if len(files) > 8:
            print(f"  - ... {len(files) - 8} more")

    if report["uncategorized"]:
        print("- 未分派:")
        for path in report["uncategorized"]:
            print(f"  - {path}")

    print_section("建议验证")
    for command in report["verify_commands"]:
        print(f"- {command}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Codex 三省三部 routing for local changes.")
    parser.add_argument("--base", help="Git ref to compare against, for example HEAD~1")
    parser.add_argument("--staged", action="store_true", help="Only inspect staged changes")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    report = build_report(args.base, args.staged)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
