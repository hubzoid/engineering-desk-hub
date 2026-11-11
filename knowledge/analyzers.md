---
title: Open-source analyzers
description: Optional tools Engineering Desk runs on each pull request's changed files.
---

The supplied Ruff and Gitleaks presets scan changed files as data, including
dotfiles. They ignore PR-controlled configuration and suppression markers. Keep
their `run` lists unchanged to retain this isolated preset behavior.

Other SARIF commands, including modified presets, need `allow_project_code: true`
on that analyzer under `engineering_desk.analyzers` in `workflows/settings.yaml`. These
commands are **not sandboxed** and may execute PR-controlled configuration. An
operator must decide whether the repositories and execution environment are
appropriate before enabling them. The setting does not create a sandbox.

Gitleaks and Trivy need no install. Engineering Desk downloads one pinned
version of each from its GitHub release the first time it needs it, checks it
against a pinned SHA-256, and keeps it in a cache outside the hub's data folder
(`~/.cache/hubzoid/engineering-desk/scanners`, or `$ENGINEERING_DESK_SCANNERS`).
`hubzoid hub doctor .` shows which build runs. A machine that cannot download
uses the tool on PATH; with neither, a review says at the top that the secret
scanner did not run. Trivy lists the packages in every dependency file
(Swift, CocoaPods, Maven, NuGet, Dart and the rest) for the security watch;
OSV.dev supplies their advisories, and Trivy's own database those for
CocoaPods, which OSV.dev does not cover.

Results on added lines are evidence for the reviewer; they do not become findings
by themselves. Gitleaks results are the exception: a secret is a finding, and
the second pass confirms or refutes it (a test fixture's fake key is dropped,
with the reason under Run details). The deep audit also runs Gitleaks over the
whole default branch on each weekly audit, and its second pass checks every
hit before anyone is alerted. Missing tools and custom commands without opt-in are skipped with
a note in the summary's run details. The other tools below are custom-command
options, not supplied isolated presets.

| Tool | Finds | Install |
|---|---|---|
| Ruff | Python bugs and security patterns | `pip install ruff` |
| Gitleaks | Secrets | Nothing to install: a pinned build is downloaded on first use |
| OSV-Scanner | Vulnerable dependencies | `brew install osv-scanner` (`--format sarif`) |
| Opengrep | Semgrep-style rules for many languages | see opengrep.dev |
| zizmor | GitHub Actions workflow problems | `pip install zizmor` |
