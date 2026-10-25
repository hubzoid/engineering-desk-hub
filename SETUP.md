# Setting up Engineering Desk

Every step, in order. The [README](README.md) has the short version. Commands
run from the cloned `engineering-desk` folder with its virtual environment active.

## 1. Install

```bash
git clone https://github.com/hubzoid/engineering-desk-hub engineering-desk
cd engineering-desk
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env` holds the model and turns schedules on:

- `MODEL=claude-local` uses the Claude Code signed in on this machine,
  `MODEL=codex-local` the Codex. A provider key works too
  ([Hubzoid's providers guide](https://github.com/hubzoid/hubzoid/blob/main/docs/providers.md)).
- `HUBZOID_SCHEDULES=1` lets `hubzoid run` run Engineering Desk's schedules. Without it
  nothing runs on its own, and `hubzoid hub doctor .` says so.

## 2. Give Engineering Desk a GitHub token

Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new)
with access to **only the repos you want Engineering Desk to read**. Chat can read
anything the token can, so the token is the real limit.

| For | Repository permissions |
|---|---|
| Preview reviews and chat | Metadata, Contents, Pull requests, Issues, Actions, Commit statuses, Checks: **read** |
| Publishing reviews (later) | Also Pull requests, Issues and Commit statuses: **write** |

If your organization requires approval or SSO for tokens, finish that in
GitHub first.

Add it to `.env` without it showing on screen or in your shell history:

```bash
read -rs GH && printf 'GITHUB_TOKEN=%s\n' "$GH" >> .env && unset GH
```

Paste the token and press Enter. `.env` is never committed. Keep it readable
only by you (`chmod 600 .env`).

**A GitHub App instead** (its own bot identity, better for a team server):
install your App on the chosen repos with the same permissions, and put these
in `.env` instead of `GITHUB_TOKEN`:

```dotenv
GITHUB_APP_ID=your-app-id-or-client-id
GITHUB_INSTALLATION_ID=your-numeric-installation-id
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```

Engineering Desk signs short-lived tokens from the key and renews them before they
expire. App credentials win when both are set. Chat's GitHub tools use
`GITHUB_TOKEN`, so set a read-only token as well if you want them.

## 3. Choose repos and what runs

Everything is in `workflows/settings.yaml`. It is yours: updates never change
it. Set `source: github` and list your repos:

```yaml
engineering_desk:
  version: 2
  source: github
  repos:
    - name: your-org/api
      reviews: true
      security: true
      reports: true
      context: "Customer emails and addresses live in the orders table."
    - name: your-org/web
      reviews: true
      reports: true
    - name: your-org/docs
  email:
    security: platform-security
    reports: eng-leads

email_lists:
  platform-security: [sam@your-company.com]
  eng-leads: [maya@your-company.com, lee@your-company.com]
```

| Switch | Off by default. When on |
|---|---|
| `reviews` | Pull requests are reviewed every 2 minutes (or instantly with a webhook), pushes are re-reviewed, and `/hubzoid` commands work on that repo's pull requests. |
| `security` | A daily dependency check against known advisories (06:00 UTC) and a weekly deep audit of the code (Wednesdays by default, up to 20 minutes a day until it is done). Alerts only for new or worse problems. |
| `reports` | A weekly digest (Mondays 08:00 UTC) and monthly code and delivery reports (the 1st, 07:00 UTC). |

- **Chat** answers about every listed repo, and about anything else the token
  can read through GitHub's tools. A repo listed with no switches (like
  `your-org/docs`) gets chat and a profile only.
- **Profiles.** A new repo gets a short profile (what it is, its parts, where
  sign-in lives) within a few minutes. Its first reviews wait for it, so they
  are not done twice. It is refreshed once a day, only when the code changed.
- **Email** is optional. Without an `email` list, alerts and reports stay on
  their pages in the web app. Each recipient needs an account on this Hubzoid
  or an allowed company domain.
- **Asking always works.** On any listed repo, a person can ask for a report
  in chat ("delivery report for your-org/docs, last two weeks") whatever its
  switches.
- **Groups**, for different teams and lists: `security_groups` and
  `digest_groups` still work. Each group keeps only its repos with the switch on.

The next run reads changes. No restart needed. A wrong key or value fails
the next run with a message that names it.

## 4. Check

```bash
hubzoid hub doctor .
```

It checks the settings, that schedules are on, and that the token reads each
listed repo (one read per repo, nothing written), and says how to fix what is
wrong. For a deeper check of each repo's pull requests and CI:

```bash
hubzoid schedule run . setup_check
```

## 5. Run

```bash
hubzoid grant admin@localhost engineering_desk .
hubzoid grant admin@localhost wf_delivery_report .
hubzoid run .
```

Open the address `hubzoid run` prints. Results show in three places:

- **Chat.** "What is Engineering Desk watching?", "What did Engineering Desk find on
  your-org/web PR 41?"
- **Settings, Agents, Engineering Desk, Runs & schedules.** Each workflow's runs, with
  "Run now", pause and resume.
- **Report pages**, linked from chat and from the runs.

Reviews start in **preview**: each one shows the comment Engineering Desk would post,
and nothing is written to GitHub. Existing open pull requests are reviewed in
batches of five per sweep.

## 6. Publish reviews

When you like the previews:

1. Give the token write access (step 2), or use a GitHub App.
2. In `workflows/settings.yaml`, set `review.post_to_github: true`.

Pull requests already reviewed are published on the next sweep without
another model call. Engineering Desk comments as the token's owner. A GitHub App gives
it its own name.

**Merge gate (optional).** `review.status_check: gate` makes the
`engineering-desk/review` status fail while a blocking finding (open, high, bug or
security) is open. Make it a required check in branch protection, and keep a
required human approval too: Engineering Desk's green status is not an approval. With
the gate on, a pull request's own author cannot dismiss or defer a blocking
finding. The `engineering-desk-skip` label stops reviews on a pull request but keeps
its last status, so a label cannot lift the gate.

## 7. Bring your team

Turn on sign-in and add people ([Hubzoid team setup](https://github.com/hubzoid/hubzoid/blob/main/docs/ADMINISTRATION.md)).
In **Settings, Agents, Engineering Desk, Access**, grant:

| Permission | Lets a person |
|---|---|
| `use_hub` and `engineering_desk` | Chat with Engineering Desk and use its tools |
| `wf_code_report`, `wf_delivery_report`, `wf_repo_profiles`, `wf_review_diff` | Run those workflows for themselves |
| `schedule_reports` | Keep a personal report on a schedule |
| `engineering_desk_admin` | Approve or reject drafted team rules |
| `engineering_desk_manager` and `wf_people_report` | See activity counts for the digest groups in their `engineering_desk_groups` attribute. Counts describe activity. They never score people. |

For a team server, set `HUBZOID_WORKFLOW_USER` to the account scheduled work
runs as, keep the process running, and keep the folder, `.hubzoid/` included,
on persistent storage. Back up with `hubzoid backup` before upgrades.

## 8. Chat and GitHub's tools

Chat has two sets of tools:

- **Engineering Desk's own:** code search and file reading on the listed repos, commit
  history, review findings and fix prompts, security results, repo profiles,
  the rules for a file.
- **GitHub's**, from GitHub's hosted MCP server in read-only mode
  (`connectors/.mcp.json`): issues, pull requests Engineering Desk has not reviewed,
  Actions runs and logs, releases, branches, and any repo the token can read.
  It never writes.

To turn GitHub's tools off, remove the `github` entry from
`connectors/.mcp.json` and restart. To run that server locally instead, see
[GitHub's MCP server](https://github.com/github/github-mcp-server) and keep it
read-only.

## 9. Instant reviews (webhook)

Polling every two minutes needs no public address. For reviews within
seconds, on a hub GitHub can reach:

1. `workflows/settings.yaml`: `trigger: webhook`.
2. `.env`: `WEBHOOK_SECRET_GITHUB=<a long random string>`.
3. GitHub, repo or organization settings, Webhooks: payload URL
   `https://<your hub>/webhooks/engineering-desk/github`, content type JSON, the same
   secret, events: Pull requests, Issue comments, Pull request review
   comments, Pushes.

A sweep still runs every 30 minutes as a safety net. Until the secret is set,
`hubzoid doctor` lists it as missing, which is expected while you poll.

## 10. Fix findings with your own coding agent

Engineering Desk reviews. Your coding agent fixes. Engineering Desk never commits.

1. Connect Engineering Desk to Claude Code or Codex over MCP (the command
   `hubzoid run` prints) and sign in to `gh`.
2. Copy `client/skills/engineering-desk-fix/` to `~/.claude/skills/` (Claude Code) or
   `~/.codex/skills/` (Codex).
3. Ask: "fix the Engineering Desk findings on your-org/web#42 until it's clean".

The agent reads the findings, fixes, runs the tests, pushes, waits for
Engineering Desk's review of the new commit and repeats, at most three rounds. It never
dismisses a finding. `client/github-actions/engineering-desk-fix.yml` runs the same
loop in GitHub Actions when someone adds the `engineering-desk-fix` label. That one
needs its own model API key in the repo's secrets.

## 11. Options

All under `engineering_desk:` in `workflows/settings.yaml`. The file's comments show
the defaults.

| Option | Default | Other choices |
|---|---|---|
| `review.backlog` | `all`: every open pull request, five per sweep | `latest` (the newest `first_run_limit`), `new` (only new pull requests and pushes) |
| `review.skip_drafts`, `review.skip_bots` | `true` | `false` reviews them |
| `review.status_check` | `report`: information only | `gate` (see step 6), `off` |
| `review.severity_floor` | `high` | `medium`, `low`. Per repo too |
| `review.max_age_days` | `0`: no cutoff | Older pull requests wait for a push or a manual review |
| `review.auto_pause_after` | `0`: keep reviewing | Pause a busy pull request after this many pushes |
| `limits.model_calls_per_day` | `400` | Work over the limit is shown, not dropped |
| `reports.evidence_prs` | `100` diffs per report | Bigger or smaller reports |
| `analyzers` | Ruff and Gitleaks when installed | Your own SARIF tools, with `allow_project_code: true` only for trusted commands |

## 12. Troubleshooting and costs

- **Nothing happens.** Run `hubzoid hub doctor .`. Usually schedules are off,
  no repo has the switch on, or the token cannot read the repo. Keep
  `hubzoid run` running: schedules stop when it stops or the machine sleeps,
  and catch up on restart.
- **HTTP 403 or 404 for a repo.** The token is not shared with that repo, or
  the organization has not approved it. Missing CI permission shows as
  unknown CI, never as passing.
- **Model errors.** Sign in to Claude Code or Codex again, or check the
  provider key.
- **An incomplete review.** The pull request was larger than
  `review.max_diff_chars`. The review says which files it read. Raise the
  limit or split the pull request.
- **Costs.** A review is usually one model call plus one verification call.
  Profiles and reports add calls. With Claude Code or Codex this uses your
  subscription. With a provider key it is billed by the provider.
