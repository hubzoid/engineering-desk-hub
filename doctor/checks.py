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


def _lib(hub_dir: Path):
    root = hub_dir / "workflows" / "engineering_desk" / "lib"
    name = "engineering_desk_doctor_lib"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, root / "package.py", submodule_search_locations=[str(root)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _settings(hub_dir: Path):
    return _lib(hub_dir).settings


def _env(hub_dir: Path) -> dict:
    """The environment as the hub sees it: its .env wins over the shell."""
    from dotenv import dotenv_values

    return {**os.environ, **{k: v for k, v in dotenv_values(hub_dir / ".env").items() if v is not None}}


def _settings_row(context) -> dict:
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
    where = {"sample": "Sample", "local": "Local folders"}.get(s.source, "GitHub")
    return _row("ok", f"{where}, {mode}. {summary}.",
                details={"publishing": mode, "repos": on})


def _schedules_row(context) -> dict:
    """Scheduled work (sweeps, watch, digests) runs only with schedules on."""
    hub_dir = Path(context["hub_dir"])
    from hubzoid.workflows.boot import schedules_enabled

    if schedules_enabled(_env(hub_dir)):
        return _row("ok", "Schedules are on: sweeps, profiles, the security watch and reports run on their own.")
    return _row("fail", "Schedules are off: nothing Engineering Desk schedules will run, though the web app lists times.",
                "Add HUBZOID_SCHEDULES=1 to .env (it is in .env.example) and restart hubzoid run.")


def scanners(context) -> dict:
    """Which Gitleaks and Trivy will run: the pinned builds, the ones on PATH,
    or none yet. Reads only: a missing pinned build is downloaded by the first
    review or security watch that needs it, not here."""
    hub_dir = Path(context["hub_dir"])
    lib = _lib(hub_dir)
    tools = [lib.scanners.status(name) for name in ("gitleaks", "trivy")]
    summary = "; ".join(t.note for t in tools) + "."
    details = {t.name: {"path": t.path, "version": t.version} for t in tools}
    if any(not t.ready and "no pinned build" in t.note for t in tools):
        return _row("warn", summary, "Install the missing tool on PATH; reviews and the security watch say what "
                    "they could not check without it.", details=details)
    return _row("ok" if all(t.ready for t in tools) else "info", summary, details=details)


def _github_row(context) -> dict:
    """The token reads each listed repo (one GET per repo, nothing written)."""
    hub_dir = Path(context["hub_dir"])
    lib = _settings(hub_dir)
    try:
        s, _ = lib.read_file(hub_dir)
    except lib.SettingsError:
        return _row("info", "Skipped until workflows/settings.yaml is valid.")
    if s.source == "sample":
        return _row("info", "Sample mode: no GitHub access is needed.")
    if s.source == "local":
        return _row("info", "Local folders: no GitHub access is needed. Connect GitHub only for pull request reviews.")
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


# ------------------------------------------------------------ get started cards
# get-started.yaml at the hub root shows four cards for the owner and admins:
# Model (built into Hubzoid), Code, GitHub and Automatic checks. Each check
# below also returns the card's short line (60 characters) and detail (80):
# what is set, or what to do. Status and next step only: no buttons.

def _card(row: dict, line: str, detail: str) -> dict:
    return {**row, "card": {"line": line[:60], "detail": detail[:80]}}


def _read(hub_dir: Path):
    lib = _settings(hub_dir)
    try:
        return lib.read_file(hub_dir)[0]
    except lib.SettingsError:
        return None


def _short_path(path: str, room: int) -> str:
    """A folder as a card line: ~ for home, and the end kept when it is long."""
    home = str(Path.home())
    text = path.replace(home, "~", 1) if path.startswith(home) else path
    if len(text) <= room:
        return text
    tail = text[-(room - 2):]
    return "…/" + tail.split("/", 1)[-1] if "/" in tail else "…" + text[-(room - 1):]


def _branch(path: str) -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "-C", os.path.expanduser(path), "symbolic-ref", "--quiet", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out


def settings(context) -> dict:
    """workflows/settings.yaml is valid, and what each repo has on. The Code card."""
    hub_dir = Path(context["hub_dir"])
    row = _settings_row(context)
    s = _read(hub_dir)
    choose = "Choose a folder or repos in workflows/settings.yaml, or ask your coding agent to"
    if s is None or row["status"] == "fail":
        return _card(row, "Settings need a fix", "Run hubzoid hub doctor . to see which key")
    if not s.repos:
        return _card(row, "Not chosen yet", choose)
    if s.source == "sample":
        return _card(row, "The fictional sample repo", choose)
    more = f" and {len(s.repos) - 1} more" if len(s.repos) > 1 else ""
    if s.source == "local":
        first = s.repos[0]
        branch = _branch(first.path)
        return _card(row, _short_path(first.path, 60 - len(more)) + more, f"Branch {branch}" if branch else "Local folder")
    return _card(row, f"{s.repos[0].name}{more}", "On GitHub")


def github(context) -> dict:
    """The token reads each listed repo (one GET per repo, nothing written). The GitHub card."""
    hub_dir = Path(context["hub_dir"])
    row = _github_row(context)
    s = _read(hub_dir)
    if s is not None and s.source in ("sample", "local"):
        # Not a failure: GitHub is only needed for pull request reviews.
        return _card(row, "Not connected", "Needed only for PR reviews")
    if row["status"] == "ok":
        return _card(row, "Connected", row["summary"])
    if row["status"] == "fail" and "No GitHub token" in row["summary"]:
        return _card(row, "Not connected", "Add GITHUB_TOKEN to .env (SETUP.md, step 2)")
    return _card(row, "Needs attention", row.get("recovery") or row["summary"])


def schedules(context) -> dict:
    """Scheduled work (sweeps, watch, digests) runs only with schedules on. The Automatic checks card."""
    hub_dir = Path(context["hub_dir"])
    row = _schedules_row(context)
    if row["status"] != "ok":
        return _card(row, "Off", "Add HUBZOID_SCHEDULES=1 to .env and restart")
    s = _read(hub_dir)
    if s is not None and s.source == "local":
        return _card(row, "Security watch and audit on", "Dependencies daily, the audit and secret scan weekly")
    return _card(row, "Reviews and security watch on", "Reviews every 2 minutes, security daily")
