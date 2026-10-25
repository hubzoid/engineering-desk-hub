<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/hubzoid/hubzoid/72ac7bf1610c8a335b9b3ac3b536de8fdb6770f1/assets/mark-dark.svg">
    <img alt="Hubzoid" src="https://raw.githubusercontent.com/hubzoid/hubzoid/72ac7bf1610c8a335b9b3ac3b536de8fdb6770f1/assets/mark-light.svg" width="200">
  </picture>
</p>

<h1 align="center">Engineering Desk</h1>
<h3 align="center">Pull request reviews and answers about your code, on your own Hubzoid.</h3>
<p align="center">You choose the repos. You choose what runs. Nothing is posted until you say so.</p>
<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="SETUP.md">Setup guide</a> ·
  <a href="UPGRADING.md">Upgrading</a> ·
  <a href="CHANGELOG.md">Changes</a> ·
  <a href="https://github.com/hubzoid/hubzoid">Hubzoid</a>
</p>
<p align="center">
  <a href="https://github.com/hubzoid/hubzoid"><img src="https://img.shields.io/badge/Built%20on-Hubzoid-B5471F" alt="Built on Hubzoid"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-0B0B0C" alt="Apache License 2.0"></a>
  <a href="https://github.com/hubzoid/hubzoid/discussions"><img src="https://img.shields.io/badge/Community-Discussions-0B0B0C?logo=github" alt="GitHub Discussions"></a>
</p>

**The Engineering Desk is a ready-to-use Hubzoid hub for engineering teams.** It reviews pull requests against your team's rules, answers questions about your code in chat, watches dependencies for security problems and writes a weekly digest. It runs on your machine or your server, with the Claude Code or Codex you already sign in to.

<!-- Screenshot: a review preview on a sample pull request, with its findings and fix prompts. -->

## How it works

Each repository you list gets three switches, all off until you turn them on. Chat needs no switch.

- **Reviews** (`reviews`). Every two minutes, or within seconds through a webhook, the desk reviews each new pull request and push against your team's rules, the repository's own rules and a profile of the repository. A second pass tries to refute each finding, so what reaches you has survived a challenge. It starts in **preview**, showing the comment it would post and writing nothing to GitHub, and it tracks which findings get fixed.
- **Security** (`security`). Checks dependencies daily against known advisories and audits the code weekly. It alerts only when something new and serious appears.
- **Reports** (`reports`). A weekly digest and monthly code and delivery reports, as pages in the web app and, if you add a list, email.
- **Chat.** Ask *"Where do we check sign-in?"* or *"Why did CI fail on main?"*. It answers from your code, history, issues and Actions runs, and only reads.
- **Team rules.** Say *"Remember: retries must stop after three attempts."* It drafts a team rule, and an admin approves it before it applies.

Reviews, findings and schedules live in `.hubzoid/`. A restart carries on where it stopped, and each comment is posted once. A review is usually one model call plus a verification call, and daily limits are in `workflows/settings.yaml`. [Setup guide](SETUP.md)

## Quick start

You need Python 3.11 or 3.12, Git, and Claude Code or Codex signed in on this machine. No API key. The quick start uses the fictional sample, so you need no GitHub token.

Paste this into Claude Code or Codex, from any folder:

```text
Help me set up the Hubzoid Engineering Desk. Clone
https://github.com/hubzoid/engineering-desk-hub into a folder called
engineering-desk, cd in, and follow README.md and SETUP.md. Start with the
fictional sample, and keep publishing to GitHub off until I say so.
```

Or by hand:

```bash
git clone https://github.com/hubzoid/engineering-desk-hub engineering-desk
cd engineering-desk
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env` uses Claude Code (`MODEL=claude-local`). For Codex, set `MODEL=codex-local`.

In `workflows/settings.yaml`, change `source: github` to `source: sample`. Then give yourself, the local owner, the chat tools and the delivery report, and start:

```bash
hubzoid grant admin@localhost engineering_desk .
hubzoid grant admin@localhost wf_delivery_report .
hubzoid run .
```

Open the address `hubzoid run` prints. Within two minutes the desk reviews the five sample pull requests: an endless retry, an unprotected admin export, unsafe SQL, a vulnerable package and one clean change. Nothing is posted anywhere. Ask in the web chat:

> What is waiting or stuck right now?

Then ask *"Show the findings on storefront PR 102 with fix prompts."* You see each finding with a prompt you can hand to your own coding assistant to fix it. [Full setup](SETUP.md)

## Integrations

| Works with | What the desk does |
|---|---|
| GitHub | Reviews pull requests and pushes in the repositories you list. Publishes a comment, inline findings and a status once you turn publishing on. Comment `/hubzoid review`, `pause`, `resume`, `dismiss`, `defer` or `help` on a pull request to act on it. |
| GitHub's MCP server, read only | Gives chat issues, pull requests, Actions runs and logs, releases and branches, for any repository the token can read. It never writes. |
| The web chat, and Claude Code over MCP | Answers questions about your code. Its own tools answer signed-in people only. |
| Email | Sends reports and the weekly digest to a list, if you add one. |

Ready for your own repositories? Add a fine-grained, read-only GitHub token to `.env` yourself, never in chat ([SETUP.md](SETUP.md), step 2, keeps it off your screen and out of your shell history). List your repositories in `workflows/settings.yaml` with `source: github`, then run `hubzoid hub doctor .` and `hubzoid run .`. Or ask your coding assistant to follow [SETUP.md](SETUP.md).

## Make it yours

The files you will edit, and what each one changes:

```text
engineering-desk/
├── .env                          your model and your GitHub token. Never committed
├── workflows/settings.yaml       your repos, what runs on each, limits, preview or publish
├── knowledge/
│   ├── review-rules/             your team's rules, one Markdown file each
│   │   └── examples/             rules to copy and adapt
│   └── *.md                      conventions you want chat and reviews to know
└── connectors/.mcp.json          GitHub's read-only MCP server for chat
```

Choose what runs on each repository in `workflows/settings.yaml`:

```yaml
repos:
  - name: your-org/api
    reviews: true
    security: true
  - name: your-org/web
    reviews: true
    reports: true
  - name: your-org/docs        # chat and a profile only
```

Reviews start in preview. When you like them, give the token write access and set `review.post_to_github: true`, and the desk comments on pull requests. A GitHub App gives it its own name. [SETUP.md](SETUP.md), "Publish reviews"

A team rule has a title, the paths it covers, a severity and an optional pattern. Copy one of the examples to start. In a repository, a `.engineering-desk/review.md` file sets what to skip, focus on or ignore there, and the desk also reads the repository's `CLAUDE.md`, `AGENTS.md` and `CONTRIBUTING.md`.

To save a rule from chat, tell the desk *"Remember: retries must stop after three attempts."* It drafts the rule, and an admin approves it before it applies. Your `.env`, `.hubzoid/`, `workflows/settings.yaml` and your rules are yours: updates never change them.

## Safety

- **Nothing is posted until you say so.** Reviews start in preview, and every switch is per repo and off by default. Chat only reads, and GitHub's MCP server runs in read-only mode.
- **The desk's green status is not an approval.** With the optional merge gate on, its status fails while a blocking finding is open, and a pull request's own author cannot dismiss or defer one. Keep a required human approval in branch protection too.
- **Pull request commands need write access.** `/hubzoid` commands count only from people with write access to the repository, and only outside quotes and code blocks.

[SETUP.md](SETUP.md), "Troubleshooting and costs", covers limits and what a review costs.

## Host it for your team

The desk runs on a server the same way any Hubzoid hub does: one durable folder, sign-in on, and one public address. Three things are specific to the desk:

- **`HUBZOID_SCHEDULES=1`**, so sweeps, profiles, security checks and digests run on their own. It is set in `.env.example`.
- **`HUBZOID_WORKFLOW_USER`**, the account scheduled work runs as. Keep the folder, `.hubzoid/` included, on persistent storage, and back up with `hubzoid backup` before upgrades.
- **A webhook, if you want reviews within seconds.** Set `trigger: webhook` and `WEBHOOK_SECRET_GITHUB`, and point GitHub at `https://<your hub>/webhooks/engineering-desk/github`. Polling every two minutes needs no public address.

Grant each person what they need in **Settings, Agents, Engineering Desk, Access**: chat and tools, their own reports, approving team rules, or activity counts for digest groups. Counts describe activity. They never score people. [SETUP.md](SETUP.md), "Bring your team", has the permission table. [Hubzoid deployment](https://github.com/hubzoid/hubzoid/blob/main/docs/deploy/README.md) lists the hosting options and which are verified.

## Updating

```bash
git pull
python -m pip install -r requirements.txt
hubzoid hub doctor .
hubzoid restart engineering-desk
```

If pip upgraded Hubzoid itself, stop `hubzoid run` and start it again. [UPGRADING.md](UPGRADING.md) has the details, the move from the old GitZoid names, and the move from the GitZoid bundled with Hubzoid 1.3.

## Go further

| Next step | Guide |
|---|---|
| Install, add a token and choose what runs | [Setup](SETUP.md) |
| Publish reviews and use the merge gate | [Publish reviews](SETUP.md#6-publish-reviews) |
| Give your team access | [Bring your team](SETUP.md#7-bring-your-team) |
| Reviews within seconds | [Instant reviews](SETUP.md#9-instant-reviews-webhook) |
| Fix findings with your own coding agent | [Fix findings](SETUP.md#10-fix-findings-with-your-own-coding-agent) |
| Every option | [Options](SETUP.md#11-options) |
| Update, and move from GitZoid | [Upgrading](UPGRADING.md) |
| What changed | [Changes](CHANGELOG.md) |

Questions go to [GitHub Discussions](https://github.com/hubzoid/hubzoid/discussions). Bugs in the desk go to [this repository's issues](https://github.com/hubzoid/engineering-desk-hub/issues).

The Engineering Desk is **Apache-2.0**. Built on [Hubzoid](https://github.com/hubzoid/hubzoid). Need it running for your team? [Build with us](https://hubzoid.com/build-with-us).
