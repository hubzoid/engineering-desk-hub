# Changes

## 1.0.0 (unreleased)

GitZoid moves out of the Hubzoid SDK into this repo and becomes the
Engineering Desk. It needs Hubzoid 2.0.3 or later within 2.x.
[UPGRADING.md](UPGRADING.md) covers hubs made from the bundled template and
the move from the old names.

- **New name.** GitZoid is now the Engineering Desk, in
  `hubzoid/engineering-desk-hub`. Permissions are `engineering_desk`,
  `engineering_desk_admin` and `engineering_desk_manager`; the settings block
  is `engineering_desk:`; workflows live in `workflows/engineering_desk/`; a
  repo's own rules go in `.engineering-desk/review.md`; the status check is
  `engineering-desk/review`.
- **Slash commands.** Pull request commands are `/hubzoid review`, `pause`,
  `resume`, `dismiss <reason>`, `defer` and `help`, instead of `@gitzoid`.
  A slash command notifies no GitHub account. Write access is still required,
  and commands inside quotes and code blocks are still ignored.
- **You choose what runs.** `workflows/settings.yaml` ships with
  `version: 2` and no repos. Each repo turns on `reviews`, `security` and
  `reports` itself. Nothing runs on its own until one is on, and each
  scheduled workflow says how to turn it on. A settings file with no version
  keeps everything on, as before.
- **Email** in one place: `email.security` and `email.reports` name a list
  each. Named groups still work, limited to repos with the switch on.
- **Chat reads more of GitHub** through GitHub's hosted MCP server in
  read-only mode (`connectors/.mcp.json`): issues, Actions runs and logs,
  releases, and any repo the token can read.
- **Profiles first.** A repo without a profile gets one within a few minutes,
  and its first reviews wait for it (up to `review.wait_for_profile_minutes`,
  10 by default), so open pull requests are not reviewed twice. The
  code-changed check still runs once a day.
- Turning `security` or `reports` on or off never re-reviews pull requests.
- **Example rules** moved to `knowledge/review-rules/examples/`, on only in
  sample mode.
- **Status says what is on.** `engineering_desk_status`, `setup_check` and
  `hubzoid hub doctor .` show each repo's switches, the source, and whether
  publishing is preview or live (the sample is always preview).
- **Doctor checks** (`hub.manifest.yaml`): settings, schedules on, and that
  the token reads each listed repo.
- **`.env.example`** turns schedules on (`HUBZOID_SCHEDULES=1`). Without it,
  sweeps, the security watch and digests never ran under `hubzoid run`.
- `setup.py` is removed: the token goes in `.env`, repos and options in
  `workflows/settings.yaml`.
- Messages say Settings instead of Console.
- Tests and CI live here, on Hubzoid 2.0.3 and the latest 2.x.
- **GitHub hiccups.** Reads (and GraphQL queries, and repo downloads) are
  retried with backoff when GitHub times out, drops the connection or
  answers 500 to 504. Writes are never resent after a server error or a
  dropped connection, because GitHub may already have applied them: the next
  sweep republishes instead, so a review is never posted twice. A repo GitHub
  did not answer for shows "retry next sweep", and no longer fails the run.
- **Suggestions over several lines.** A one-click suggestion can replace up
  to 15 consecutive lines (`start_line` to `line`), when every one of them is
  in the diff. Otherwise the finding stays on its one line without it.
- Chat tools name their hub folder, so they work in evals and over MCP, and
  the three evals run as `admin@localhost`.
- The Desk no longer imports a private part of Hubzoid (`_file_lock`).
- **Every language.** The deep audit, repo profiles and code search read
  every text file, whatever its language (Swift, Objective-C, Kotlin, Dart,
  C and C++ included), instead of a fixed list. They skip vendored and
  build folders (now also `Pods/`, `Carthage/`, `.build/`, `DerivedData/`,
  `.gradle/` and others), binary files, and for the audit lockfiles,
  documentation, data and generated Xcode files.
- **"Not checked", never "0 issues".** A repo where the audit can read no
  file is reported as not checked, and is never recorded as a clean audit.
  The security watch says the same for a repo with no dependency file.
- **Scanners for everyone.** Gitleaks 8.30.1 and Trivy 0.76.1 are
  downloaded on first use from their GitHub releases, checked against a
  pinned SHA-256, and kept in a cache outside the hub's data folder.
  `hubzoid hub doctor .` shows which build runs, and `setup_check` fetches
  them. A machine that cannot download uses the tool on PATH. A review whose
  secret scanner did not run says so at the top. The sample never downloads.
- **Every dependency file.** The security watch lists packages with Trivy,
  so Swift (`Package.resolved`), CocoaPods (`Podfile.lock`), Maven, NuGet,
  Dart and others are checked, not only Python, npm, Go, Rust, Ruby and PHP.
  OSV.dev still supplies the advisories; CocoaPods, which it does not cover,
  gets them from Trivy's database, downloaded only for repos that have a
  `Podfile.lock`. Without Trivy the Desk's own readers run, and any other
  dependency file is reported as not checked.
- **Secrets are double-checked.** A secret the pattern sweep or Gitleaks
  finds in a pull request is a finding that now goes through the second
  pass, like the model's own: a fake key in a test fixture is dropped with
  the reason under Run details, and a real one is kept. Dependency
  advisories and team-rule patterns are still not second-guessed.
- **Weekly secret scan.** Each full deep audit runs Gitleaks over the whole
  default branch. The audit's second pass checks every hit before anyone is
  alerted. A scan that could not run is a coverage problem.
- **Local folders.** `source: local` with a `path:` per repo checks git
  working copies on this machine, with no GitHub token: what git tracks at
  the current commit (never ignored files such as `.env`), and the whole
  history for secrets. Pull request reviews and reports need GitHub.
