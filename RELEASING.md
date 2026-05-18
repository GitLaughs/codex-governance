# Releasing

Use this checklist when publishing Codex Governance as a standalone repository.

## Preflight

- Confirm the release tree contains only Codex Governance files.
- Confirm `.tmp/`, prompt files, mailbox archives, local sessions, and caches are absent.
- Run `rg` for private repository names, absolute paths, secrets, and project-specific terms.
- Review `SECURITY.md` for current launcher behavior.

## Verify

```powershell
python -m py_compile codex_governance.py codex_launcher.py run_codex_prompt.py
python codex_governance.py
python codex_governance.py --json
python codex_launcher.py --help
python run_codex_prompt.py --help
```

Optional local smoke:

```powershell
python codex_launcher.py --host 127.0.0.1 --port 6211
```

Then open `dashboard.html?launcher=http://127.0.0.1:6211` in a browser.

## Publish

1. Create a clean repository.
2. Copy the release file set.
3. Commit with a concise message.
4. Create the GitHub repository.
5. Push the default branch.
6. Re-run the verification commands from the clean clone when practical.
