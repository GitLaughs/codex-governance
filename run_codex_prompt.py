#!/usr/bin/env python3
"""Run Codex with a UTF-8 prompt file in a Windows console."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


def resolve_codex_command() -> list[str]:
    for candidate in ("codex", "codex.cmd", "codex.exe", "codex.ps1"):
        resolved = shutil.which(candidate)
        if not resolved:
            continue
        suffix = Path(resolved).suffix.lower()
        if suffix == ".ps1":
            return [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                resolved,
            ]
        return [resolved]
    raise FileNotFoundError("Could not find codex CLI in PATH. Checked: codex, codex.cmd, codex.exe, codex.ps1")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Codex from a UTF-8 prompt file.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--title", default="Codex Governance")
    parser.add_argument("--dry-run", action="store_true", help="Read and print the prompt without launching Codex.")
    args = parser.parse_args()

    if os.name == "nt":
        os.system("chcp 65001 > nul")
        try:
            sys.stdin.reconfigure(encoding="utf-8")
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    prompt_path = Path(args.prompt_file)
    prompt = prompt_path.read_text(encoding="utf-8")

    if os.name == "nt":
        ctypes.windll.kernel32.SetConsoleTitleW(args.title)

    if args.dry_run:
        print("Codex Governance Prompt:")
        print(prompt)
        print()
        return 0

    codex_cmd = resolve_codex_command()
    return subprocess.call([*codex_cmd, "-m", args.model, "--cd", args.repo, prompt], cwd=args.repo)


if __name__ == "__main__":
    raise SystemExit(main())
