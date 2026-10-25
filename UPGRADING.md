# Upgrading Engineering Desk

## Updating this repo

```bash
cd engineering-desk
git pull
python -m pip install -r requirements.txt
hubzoid hub doctor .
hubzoid restart engineering-desk
```

If pip upgraded Hubzoid itself, stop `hubzoid run` and start it again instead
of the restart. Back up first on a team server (`hubzoid backup`).

**What is yours and what is the repo's.** Updates never ship or change your
files, so `git pull` does not conflict with them:

| Yours | The repo's (updated by `git pull`) |
|---|---|
| `.env`, `.hubzoid/` (state), `workflows/settings.yaml`, your rules in `knowledge/review-rules/*.md`, `hub.settings.yaml`, anything you add under `knowledge/` | `workflows/engineering_desk/`, `restricted/`, `AGENTS.md`, `evals/`, `doctor/`, `client/`, `connectors/.mcp.json`, `raw_data/sample/`, `knowledge/review-rules/examples/`, docs and tests |

New options get a default in code and a line in [CHANGELOG.md](CHANGELOG.md).
They are never added to your `workflows/settings.yaml`. Put your team's
conventions in your own files under `knowledge/` or in rules, not in
`AGENTS.md`. If you do change a file of the repo's, `git pull` merges it or
shows the conflict for you (or your coding agent) to resolve.

If `git pull` says your local changes would be overwritten, commit them first
(`git commit -am "Our settings"`) and pull again, so Git merges both.

## From GitZoid (the old names)

This hub was called GitZoid until October 2026, in the `hubzoid/gitzoid-hub`
repo. GitHub redirects the old URL. The rename changes names you may have
used, so it is the one update that needs steps from you. Keep your hub
folder's name: grants and stored state are tied to it.

1. Stop `hubzoid run`, back up (`hubzoid backup <your hub>`, and copy the
   folder), and commit any local changes.
2. Point the clone at the new repo and pull:
   `git remote set-url origin https://github.com/hubzoid/engineering-desk-hub`,
   then `git pull`. Delete `workflows/gitzoid/` if anything is left in it.
3. In `workflows/settings.yaml`, the top-level `gitzoid:` block is now
   `engineering_desk:`. `git pull` usually renames it for you; if not, rename
   it yourself. `hubzoid hub doctor .` fails until it is renamed. If you used
   the default skip label, it is now `engineering-desk-skip`; set
   `review.skip_label: gitzoid-skip` to keep the old one.
4. Rename the state file in `.hubzoid/data/` (or `HUBZOID_DATA_DIR`):
   `gitzoid.db` to `engineering_desk.db`, and `gitzoid.db-wal` and
   `gitzoid.db-shm` the same way if they exist.
5. Grant the new permissions to the people who had the old ones, then revoke
   the old ones: `gitzoid` is now `engineering_desk`, `gitzoid_admin` is
   `engineering_desk_admin`, and `gitzoid_manager` is
   `engineering_desk_manager`. Rename the `gitzoid_groups` access attribute
   to `engineering_desk_groups`.
6. In your repos and on GitHub:
   - Pull request commands are now `/hubzoid review`, `/hubzoid pause`,
     `/hubzoid resume`, `/hubzoid dismiss <reason>`, `/hubzoid defer` and
     `/hubzoid help`. `@gitzoid` comments are ignored.
   - Move each repo's `.gitzoid/review.md` to `.engineering-desk/review.md`.
   - The status check is now `engineering-desk/review`. Update branch
     protection that requires `gitzoid/review`.
   - The fix loop is now `client/skills/engineering-desk-fix/` and
     `client/github-actions/engineering-desk-fix.yml`, with the
     `engineering-desk-fix` label and environment and the
     `ENGINEERING_DESK_MCP_URL` and `ENGINEERING_DESK_MCP_KEY` variables.
     Replace your copies of the old ones.
   - Hidden markers in the desk's comments are now
     `<!-- engineering-desk:… -->`. On a pull request reviewed before the
     rename, the next review may post a new summary instead of editing the
     old one.
7. Run `hubzoid hub doctor .` and start the hub.

## From the GitZoid bundled with Hubzoid (1.3.1 to 2.0.1)

Hubs made with `hubzoid init <name> --template gitzoid` keep working with
nothing to do: `init` copied the files, and Hubzoid never reads its own copy
of the template at run time. Their settings file has no `version`, so every
listed repo keeps reviews, security and reports on, as before. `hubzoid hub
doctor` warns about it.

To take this repo's fixes, update your hub folder in place. This keeps its
name, which its access grants and stored state are tied to:

1. Stop `hubzoid run` and let running work finish. Back up both the state
   (`hubzoid backup <your hub>`) and the files: copy the whole hub folder,
   for example `cp -R my-hub my-hub.before-update`. `hubzoid backup`
   saves state, not the hub's code and settings. If you set
   `HUBZOID_DATA_DIR`, the state is there, not in the folder.
2. Install Hubzoid 2.0.2 or later in the hub's virtual environment:
   `python -m pip install "hubzoid>=2.0.2,<3"`.
3. Clone this repo next to your hub and copy its code over your hub folder:
   `workflows/engineering_desk/`, `restricted/`, `client/`, `evals/`, `doctor/`,
   `connectors/.mcp.json`, `AGENTS.md`, `hub.manifest.yaml`, `settings.yaml`,
   `raw_data/sample/`. Keep your `.env`, `.hubzoid/`,
   `workflows/settings.yaml` and `knowledge/review-rules/`. Then delete the
   old `workflows/gitzoid/`, `restricted/gitzoid*.py` and
   `restricted/_gitzoid_common.py`, and follow steps 3 to 6 of "From GitZoid
   (the old names)" above: your hub has the old names too.
4. Add `HUBZOID_SCHEDULES=1` to `.env`. The bundled GitZoid's README did not
   say so, so its schedules (polling, security watch, digests) may never have
   run under `hubzoid run`.
5. Before anything runs, set `review.post_to_github: false` in your settings,
   then run `hubzoid hub doctor <your hub>` and
   `hubzoid schedule run <your hub> setup_check`. Start the hub, check a
   preview sweep, then set publishing back on.
6. When you are ready, add `version: 2` under `engineering_desk:` and turn on
   `reviews`, `security` and `reports` per repo. Until then everything stays on.

Also changed since the bundled version:

- `setup.py` is gone. Put `GITHUB_TOKEN` in `.env` ([SETUP.md](SETUP.md),
  step 2) and edit `workflows/settings.yaml` for repos and options.
- The three example rules moved to `knowledge/review-rules/examples/` and are
  off outside sample mode. Your own rules in `knowledge/review-rules/` are
  unchanged. To keep an example, copy it up one folder.
- Chat can read GitHub through GitHub's read-only MCP server
  (`connectors/.mcp.json`), using `GITHUB_TOKEN`.
- Messages say Settings instead of Console, as Hubzoid 2.0 does.

Rollback: stop the hub, put the folder copy from step 1 back in place of the
hub folder, restore the state with `hubzoid restore`, and reinstall the
Hubzoid version you had before.

## From WaveAssist GitZoid

Same repos, `review.md` files, groups and recipients. Copy the security and
digest groups and recipients into `workflows/settings.yaml`, start with
`post_to_github: false`, compare a week of results, then publish. Emails keep
the same layout with a link to the full report (no PDF attachment).
Recipients must have an account on your Hubzoid or be at an allowed company
domain. Repo profiles refresh when the code changes, not every 14 days.
