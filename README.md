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
  <a href="SETUP.md">Setup guide</a> ·
  <a href="UPGRADING.md">Upgrading</a> ·
  <a href="CHANGELOG.md">Changes</a> ·
  <a href="https://github.com/hubzoid/hubzoid">Hubzoid</a>
</p>
<p align="center">
  <a href="https://github.com/hubzoid/hubzoid"><img src="https://img.shields.io/badge/Built%20on-Hubzoid-B5471F" alt="Built on Hubzoid"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-0B0B0C" alt="Apache License 2.0"></a>
</p>

**The Engineering Desk is a ready-to-use Hubzoid hub for engineering teams.**
It reviews pull requests against your team's rules, answers questions about
your code in chat, watches dependencies for security problems and writes a
weekly digest. It runs on your machine or your server, with the Claude Code or
Codex you already sign in to.

## How it works for you

| You | Engineering Desk |
|---|---|
| Ask in chat, Slack, or Claude Code over MCP: "Where do we check sign-in?", "Why did CI fail on main?" | Answers from your code, history, issues and Actions runs. It only reads. |
| Turn on `reviews` for a repo | Reviews each new pull request and push against your rules, and tracks which findings get fixed. Preview first: nothing is posted until you allow it. |
| Comment `/hubzoid review`, `pause`, `resume`, `dismiss`, `defer` or `help` on a pull request | Acts on that pull request (repos with reviews on). |
| Turn on `security` | Checks dependencies daily against known advisories and audits the code weekly. Alerts only when something new and serious appears. |
| Turn on `reports` | A weekly digest and monthly code and delivery reports, as pages in the web app and, if you add a list, email. |
| Say "Remember: retries must stop after three attempts" | Drafts a team rule. An admin approves it before it applies. |

Every switch is per repo and off until you turn it on. Chat needs no switch.

## Get your first useful result

You need Python 3.11 or 3.12, Git, and Claude Code or Codex signed in on this
machine. No API key.

```bash
git clone https://github.com/hubzoid/engineering-desk-hub engineering-desk
cd engineering-desk
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env.example` uses Claude Code (`MODEL=claude-local`). For Codex, set
`MODEL=codex-local` in `.env`.

**Try it on the fictional sample first** (no GitHub token). In
`workflows/settings.yaml`, change `source: github` to `source: sample`. Then:

```bash
hubzoid grant admin@localhost engineering_desk .
hubzoid grant admin@localhost wf_delivery_report .
hubzoid run .
```

The two grants let you, the local owner, use the Engineering Desk's chat tools and ask for
a delivery report. Within two minutes the Engineering Desk reviews the five sample pull
requests: an endless retry, an unprotected admin export, unsafe SQL, a
vulnerable package and one clean change. Nothing is posted anywhere. Ask in
the web chat:

> What is waiting or stuck right now?

> Show the findings on storefront PR 102 with fix prompts.

**Then connect your own repos** in three steps ([SETUP.md](SETUP.md) has
every detail):

1. Add a fine-grained, read-only GitHub token to `.env`.
2. List your repos in `workflows/settings.yaml`, set `source: github`, and
   turn on what you want per repo:

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

3. Check and start:

   ```bash
   hubzoid hub doctor .
   hubzoid run .
   ```

Reviews start in preview. When you like them, set `post_to_github: true` and
the Engineering Desk comments on pull requests. Give the token write access first
([SETUP.md](SETUP.md), "Publish reviews").

<details>
<summary>Prefer to set up with Claude Code or Codex?</summary>

Paste this into Claude Code or Codex, from any folder:

```text
Help me set up the Hubzoid Engineering Desk. Clone
https://github.com/hubzoid/engineering-desk-hub into a folder called
engineering-desk, cd in, and follow README.md and SETUP.md. Start with the
fictional sample, and keep publishing to GitHub off until I say so.
```

</details>

## Make it yours

- **Team rules.** One Markdown file each in `knowledge/review-rules/`, with a
  title, the paths it covers, a severity, and an optional pattern. Copy one of
  the examples in `knowledge/review-rules/examples/` to start. Or ask the Engineering Desk
  to draft one, and approve it as an admin.
- **Repo rules.** A `.engineering-desk/review.md` file in a repo sets what to skip,
  focus on or ignore there. The Engineering Desk also reads the repo's `CLAUDE.md`,
  `AGENTS.md` and `CONTRIBUTING.md`.
- **Your own notes.** Add Markdown files under `knowledge/` for conventions
  you want chat and reviews to know.

## Updating

```bash
git pull
python -m pip install -r requirements.txt
hubzoid hub doctor .
hubzoid restart engineering-desk
```

`.env`, `.hubzoid/`, `workflows/settings.yaml` and your rules are yours:
updates never change them. If pip upgraded Hubzoid itself, stop `hubzoid run`
and start it again. [UPGRADING.md](UPGRADING.md) has the details, the move
from the old GitZoid names, and the move from the GitZoid bundled with
Hubzoid 1.3 to 2.0.1.

## Under the hood

```text
pull request ─▶ sweep (every 2 min) or webhook ─▶ your rules + repo rules + repo profile
             ─▶ review with your model ─▶ second pass tries to refute each finding
             ─▶ preview, or a comment, inline findings and a status on GitHub
```

- **Your model.** Reviews, profiles and summaries use the model in `.env`. A
  review is usually one call plus a verification call. Daily limits are in
  `workflows/settings.yaml` (`limits`).
- **Two ways to read GitHub.** Workflows use the Engineering Desk's own GitHub client:
  paging, rate limits, each comment posted once, and a preview mode that writes
  nothing. Chat also gets GitHub's own MCP server in read-only mode for
  issues, Actions and anything else the token can read.
- **Durable.** Reviews, findings and schedules live in `.hubzoid/`. A restart
  carries on where it stopped.
- **Tested.** `python -m pytest` runs over 150 tests on the sample with a
  scripted model, on every push and nightly against the latest Hubzoid 2.x.

The Engineering Desk is Apache-2.0, like Hubzoid. Need help adapting it for your team?
[Build with us](https://hubzoid.com/build-with-us).
