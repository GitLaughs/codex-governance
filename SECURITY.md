# Security Policy

Codex Governance is a local-first tool. The launcher binds to `127.0.0.1` by default and is intended for trusted local development environments only.

## Supported Usage

- Run the launcher only on a trusted workstation.
- Keep the API bound to loopback unless you have added your own authentication and network controls.
- Review task text before launching Codex sessions from the dashboard.
- Treat prompt files and mailbox archives under `.tmp/` as potentially sensitive local data.

## Security Boundaries

The launcher exposes a small HTTP API that can start local Codex sessions, write prompt files, and read governance state. It does not expose arbitrary shell execution endpoints, but task text is ultimately passed to Codex, so local users should treat the dashboard as a privileged control surface.

The PowerShell launcher may stop older matching governance processes and starts Python/Codex processes. Review `launch.ps1` before using it in shared machines.

## Reporting

For public releases, report security issues through the repository issue tracker or the maintainer contact listed by the repository owner. Avoid posting secrets, private prompts, mailbox files, or local paths in public reports.
