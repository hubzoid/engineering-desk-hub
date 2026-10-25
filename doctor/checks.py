"""Engineering Desk's doctor checks: `hubzoid hub doctor .` runs them, and `hubzoid doctor .`
includes them. Each returns one row with what is wrong and the next step, and
never prints a credential. They only read: no GitHub write, no model call."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


LIMIT = 20   # repos checked here, one GET each, inside doctor's time limit


def _row(status: str, summary: str, recovery: str | None = None, details: dict | None = None) -> dict:
    out = {"status": status, "summary": summary}
    if recovery:
        out["recovery"] = recovery
    if details:
        out["details"] = details
    return out


def _settings(hub_dir: Path):
    root = hub_dir / "workflows" / "engineering_desk" / "lib"
    name = "engineering_desk_doctor_lib"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, root / "package.py", submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name].settings


def _env(hub_dir: Path) -> dict:
    """The environment as the hub sees it: its .env wins over the shell."""
    from dotenv import dotenv_values

    return {**os.environ, **{k: v for k, v in dotenv_values(hub_dir / ".env").items() if v is not None}}


def settings(context) -> dict:
    """workflows/settings.yaml is valid, and what each repo has on."""
    hub_dir = Path(context["hub_dir"])
    lib = _settings(hub_dir)
    try:
        s, data = lib.read_file(hub_dir)
    except lib.SettingsError as exc:
        return _row("fail", str(exc), "Fix workflows/settings.yaml; SETUP.md lists every key.")
    if "gitzoid" in data and "engineering_desk" not in data:
        return _row("fail", "workflows/settings.yaml still has the old gitzoid: block, so nothing it sets is read.",
                    "Rename gitzoid: to engineering_desk: (UPGRADING.md, \"From GitZoid\").")
    mode = lib.publishing(s)
    if s.legacy:
        return _row("warn", f"Settings without a version: all {len(s.repos)} repos have reviews, security and reports on.",
                    "Add version: 2 and turn on reviews, security or reports per repo (UPGRADING.md).")
    if not s.repos:
        return _row("info", "Engineering Desk is not watching any repo yet. Chat can still read what the token can.",
                    "Add repos under repos: in workflows/settings.yaml (SETUP.md, step 3).")
    on = {r.name: [k for k, v in s.switches(r.name).items() if v] for r in s.repos}
    summary = "; ".join(f"{name}: {', '.join(v) or 'chat only'}" for name, v in on.items())
    return _row("ok", f"{'Sample' if s.source == 'sample' else 'GitHub'}, {mode}. {summary}.",
                details={"publishing": mode, "repos": on})


def schedules(context) -> dict:
    """Scheduled work (sweeps, watch, digests) runs only with schedules on."""
    hub_dir = Path(context["hub_dir"])
    from hubzoid.workflows.boot import schedules_enabled

    if schedules_enabled(_env(hub_dir)):
        return _row("ok", "Schedules are on: sweeps, profiles, the security watch and reports run on their own.")
    return _row("fail", "Schedules are off: nothing Engineering Desk schedules will run, though the web app lists times.",
                "Add HUBZOID_SCHEDULES=1 to .env (it is in .env.example) and restart hubzoid run.")


def github(context) -> dict:
    """The token reads each listed repo (one GET per repo, nothing written)."""
    hub_dir = Path(context["hub_dir"])
    lib = _settings(hub_dir)
    try:
        s, _ = lib.read_file(hub_dir)
    except lib.SettingsError:
        return _row("info", "Skipped until workflows/settings.yaml is valid.")
    if s.source == "sample":
        return _row("info", "Sample mode: no GitHub access is needed.")
    env = _env(hub_dir)
    if env.get("GITHUB_APP_ID"):
        return _row("info", "A GitHub App is set. Run hubzoid schedule run . setup_check to test each repo.")
    token = (env.get("GITHUB_TOKEN") or "").strip()
    if not token and (context.get("available") or {}).get("GITHUB_TOKEN"):
        return _row("info", "A GitHub token is set outside .env, so this check cannot read it.",
                    "Run hubzoid schedule run . setup_check to test each repo with it.")
    if not token:
        return _row("fail", "No GitHub token: Engineering Desk and chat cannot read GitHub.",
                    "Add GITHUB_TOKEN to .env: a fine-grained, read-only token for your repos. "
                    "SETUP.md, step 2, shows how to add it without it showing on screen.")
    if not s.repos:
        return _row("ok", "A GitHub token is set. No repos are listed yet.")
    import httpx

    problems, ok = [], []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    names = s.repo_names()
    with httpx.Client(timeout=8, headers=headers) as client:
        for name in names[:LIMIT]:
            try:
                r = client.get(f"https://api.github.com/repos/{name}")
            except httpx.HTTPError as exc:
                problems.append(f"{name}: {type(exc).__name__}")
                continue
            if r.status_code == 401:
                return _row("fail", "GitHub refused the token (HTTP 401): it is wrong, expired or revoked.",
                            "Make a new fine-grained token and replace GITHUB_TOKEN in .env (SETUP.md, step 2).")
            (ok.append(name) if r.status_code == 200 else
             problems.append(f"{name}: HTTP {r.status_code}" + (" (not found or not shared with the token)"
                                                              if r.status_code in (403, 404) else "")))
    if problems:
        return _row("fail", "The token cannot read " + "; ".join(problems) + ".",
                    "Give the token access to these repos (Contents, Metadata, Pull requests: read) "
                    "or fix the names in workflows/settings.yaml.")
    if len(names) > LIMIT:
        return _row("warn", f"The token reads the first {LIMIT} of {len(names)} listed repos. The rest were not checked.",
                    "Run hubzoid schedule run . setup_check to check every repo.")
    return _row("ok", f"The token reads all {len(ok)} listed repos.")
