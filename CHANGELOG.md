# Changes

## 1.0.0 (unreleased)

GitZoid moves out of the Hubzoid SDK into this repo. It needs Hubzoid 2.0.2 or
later within 2.x. [UPGRADING.md](UPGRADING.md) covers hubs made from the
bundled template.

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
- **Status says what is on.** `gitzoid_status`, `setup_check` and
  `hubzoid hub doctor .` show each repo's switches, the source, and whether
  publishing is preview or live (the sample is always preview).
- **Doctor checks** (`hub.manifest.yaml`): settings, schedules on, and that
  the token reads each listed repo.
- **`.env.example`** turns schedules on (`HUBZOID_SCHEDULES=1`). Without it,
  sweeps, the security watch and digests never ran under `hubzoid run`.
- `setup.py` is removed: the token goes in `.env`, repos and options in
  `workflows/settings.yaml`.
- Messages say Settings instead of Console.
- Tests and CI live here, on Hubzoid 2.0.2 and the latest 2.x.
