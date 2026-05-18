# Contributing

Thanks for improving Codex Governance. Keep changes small and easy to verify.

## Development Setup

Requirements:

- Python 3.10 or newer
- Git
- Windows PowerShell for `launch.ps1`
- Codex CLI for live session launching

## Local Checks

Run these before opening a pull request:

```powershell
python -m py_compile codex_governance.py codex_launcher.py run_codex_prompt.py
python codex_governance.py
python codex_governance.py --json
python run_codex_prompt.py --help
```

## Change Guidelines

- Keep launcher API changes backward compatible when possible.
- Update `API.md` when endpoints or payload fields change.
- Update `SECURITY.md` when process launching, local HTTP behavior, or file persistence changes.
- Do not commit `.tmp/`, prompt files, mailbox archives, secrets, or generated caches.
- Keep project-specific routing rules in `governance.yaml`; avoid hard-coding a private repository into Python or HTML.

## Pull Request Checklist

- Scope is limited and documented.
- Verification commands and results are included.
- New configuration keys have defaults.
- User-owned local changes are not reverted or mixed into unrelated commits.
