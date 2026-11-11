"""check_repo: "Check my repo", a first result on your own code in minutes.

  1. secrets and dependencies   seconds, and the most convincing; the repo page
                                is published as soon as they are done
  2. a first look at the code   the riskiest files only, capped at a few
                                minutes, each finding double-checked
  3. pull request previews      only with GitHub connected and publishing in
                                preview: the newest few open pull requests,
                                reviewed on the page, nothing posted

The digest is not part of a first run. Results fill one repo page as they
finish, behind one link that always shows the latest run. Ask in chat
("Check my repo"), or start it from the agent's Runs.

Every day at 07:30, after the security watch (06:00) and the deep audit
(03:00), a scheduled run refreshes each repo's page from what they found:
no scan and no model call. check_repo is the only workflow that publishes
repo pages, because a page key belongs to one workflow in Hubzoid.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from hubzoid import hub, step, workflow


def _flow():
    path = Path(__file__).with_name("_flow.py")
    name = "engineering_desk_flow_" + hashlib.sha1(str(path).encode()).hexdigest()[:10]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


flow = _flow()
gz = flow.gz
FIRST_LOOK_PARTS = 6        # windows of the riskiest files read on a first run
FIRST_LOOK_MINUTES = 4      # and never longer than this
PREVIEWS = 3                # newest open pull requests previewed


class RepoCheck(BaseModel):
    repo: str | None = Field(None, description="The repo to check (owner/name, or just its name). Empty: the "
                                               "only repo, or the first one listed")


@step(max_attempts=2)
def first_dependencies(repo: str) -> dict:
    return flow.dependency_scan(repo)


@step()
def first_dependency_record(repo: str, items: list[dict], ignored: list[dict], stamp: str, clean: bool,
                            complete: bool, skipped_files: list[str] = ()) -> dict:
    # No email from a first check: saved unalerted, the next security watch emails them once.
    return flow.record_dependencies(repo, items, ignored, stamp, clean, complete, skipped_files, alerted=False)


@step()
def first_secrets(repo: str) -> dict:
    return flow.secret_sweep(repo)


@step()
def first_secret_record(repo: str, findings: list[dict], stamp: str, refuted: list[dict]) -> list[dict]:
    return flow.record_secrets(repo, findings, stamp, refuted, alerted=False)


@step()
def first_look_plan(repo: str) -> dict:
    """The riskiest parts of the code: sign-in and permission code, routes,
    then sensitive-sounding files, as the weekly audit orders them."""
    settings, store, gh = flow.ctx()
    root = gz.checkout.path_for(hub.data_dir, repo)
    if not root.is_dir():
        return {"units": [], "total": 0, "profile": "", "problem": "the code could not be read"}
    profile = store.profile(repo) or {"facts": gz.profiles.facts(root)}
    files = gz.audit.select(root, profile, [], [], 1_000_000, exclude=settings.exclude_for(repo))
    units = gz.audit.windows(root, files, [])
    return {"units": units[:FIRST_LOOK_PARTS], "total": len(units), "profile": gz.profiles.text(profile)}


@step()
def first_look_load(repo: str, unit: str) -> list | None:
    root = gz.checkout.path_for(hub.data_dir, repo)
    path, start, end = gz.audit.unit(unit)
    if not (root / path).is_file():
        return None
    return [path, "".join((root / path).read_text(errors="replace").splitlines(keepends=True)[start:end]), start]


@step()
def first_look_record(repo: str, findings: list[dict], paths: list[str], stamp: str, finished: bool) -> list[dict]:
    store = gz.store.Store(hub.data_dir)
    root = gz.checkout.path_for(hub.data_dir, repo)
    new = gz.audit.record(store, repo, findings, paths, root, stamp, alerted=False)
    if finished:
        store.coverage_ok(repo, "first look")
    return new


@step()
def newest_pulls(repo: str) -> dict:
    """The newest open pull requests worth a preview, or why there are none."""
    settings, store, gh = flow.ctx()
    if settings.source != "github":
        return {"numbers": [], "note": "Connect GitHub to preview pull request reviews."}
    if gz.settings.publishing(settings) != "preview":
        return {"numbers": [], "note": "Pull request previews are skipped while reviews are published live, so a "
                                       "first check never posts on GitHub."}
    controls = flow.controls(gh, store, repo)
    pulls = [p for p in gh.open_pulls(repo) if not gz.rules.skip_reason(p, settings.review, controls)]
    pulls.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return {"numbers": [p["number"] for p in pulls[:PREVIEWS]], "note": "" if pulls else "No open pull request to preview."}


@step()
def page_counts(repo: str, stamp: str) -> dict:
    """The numbers the repo page shows: every open finding, from the store;
    and the code findings first seen in this run (`stamp`)."""
    rows = gz.store.Store(hub.data_dir).ledger_rows([repo], state="open")
    secret = [r for r in rows if r["kind"] == "audit" and r.get("advisory") == "secret"]
    code = [r for r in rows if r["kind"] == "audit" and r.get("advisory") != "secret"]
    return {"secrets": len(secret), "vulnerable": sum(1 for r in rows if r["kind"] == "dependency"),
            "code": len(code), "new_code": sum(1 for r in code if r.get("first_seen") == stamp)}


@step()
def first_look_time_left(deadline: float) -> bool:
    return time.time() < deadline


def _repo(settings, asked: str | None) -> str:
    names = settings.repo_names()
    if not names:
        raise ValueError("Engineering Desk has no repo yet. Add one under repos: in workflows/settings.yaml.")
    if not asked:
        return names[0]
    short = [n for n in names if n == asked or n.split("/", 1)[1] == asked]
    if len(short) != 1:
        raise ValueError(f"{asked!r} is not one of Engineering Desk's repos here: {', '.join(names)}")
    return short[0]


def _first_look(settings, repo: str, plan: dict, stamp: str, deadline: float) -> dict:
    """Read the riskiest parts, each answer double-checked, until the parts or
    the minutes run out."""
    read, new, refuted, stopped = [], [], 0, ""
    for unit in plan["units"]:
        if not first_look_time_left(deadline):
            stopped = "time limit"
            break
        batch = first_look_load(repo, unit)
        problem = flow.charge(1)
        if batch is None or problem:
            stopped = problem or "the code changed while reading"
            break
        path = batch[0]
        try:
            result = flow.ask(gz.audit.prompt(repo, plan["profile"], [tuple(batch)]), system=gz.audit.SYSTEM,
                              response_model=gz.models.Audit, model=settings.audit.model, timeout=300)
        except flow.Unreadable as exc:
            stopped = str(exc)
            break
        found = gz.audit.gate([f.model_dump() for f in result.findings], {path})
        if found and settings.audit.verify and not flow.charge(1):
            try:
                checked = flow.ask(gz.audit.verify_prompt(repo, plan["profile"], found, [tuple(batch)]),
                                   system=gz.review.VERIFY_SYSTEM, response_model=gz.models.Verification,
                                   model=settings.audit.model, timeout=300)
                found, dropped = gz.audit.apply_verdicts(found, [v.model_dump() for v in checked.verdicts])
                refuted += len(dropped)
            except flow.Unreadable:
                pass  # unverified findings are kept, as in the weekly audit
        read.append(unit)
        new += first_look_record(repo, found, [path], stamp, False)
    finished = bool(read) and not stopped
    if finished:
        first_look_record(repo, [], [], stamp, True)
    return {"parts_read": len(read), "parts_total": plan["total"], "new": new, "refuted": refuted, "stopped": stopped}


@step()
def team_page_link(repo: str) -> str:
    return flow.team_page(repo)


def _fast(settings, repo: str, stamp: str, notes: list[str]) -> dict:
    """Secrets and dependencies: seconds, no model call unless a secret needs
    the second pass. Saved unalerted: the next security watch emails them."""
    deps = first_dependencies(repo)
    dep_summary: dict = {}
    if deps.get("error"):
        notes.append(f"dependencies: {deps['error']}")
    else:
        items, ignored = flow.judge_dependencies(settings, repo, deps)
        first_dependency_record(repo, items, ignored, stamp, not deps["notes"], deps["complete"],
                                deps.get("skipped", []))
        notes += deps["notes"]
        dep_summary = {"dependencies": flow.dependency_count(deps),
                       "read_with": deps.get("read_with"), "vulnerable": len(items)}
    sweep = first_secrets(repo)
    if sweep.get("problem"):
        notes.append(sweep["problem"])
    secrets, refuted = flow.verify_secrets(settings, repo, deps.get("profile", ""), sweep)
    if not sweep.get("problem"):
        first_secret_record(repo, secrets, stamp, refuted)
    return {"dep_summary": dep_summary, "sweep_problem": sweep.get("problem"), "refuted": refuted}


def _refresh(settings, rescan: bool) -> dict:
    """The scheduled run redraws each repo's page from the store, nothing
    scanned. "Update now" on a page also rescans secrets and dependencies
    first (the fast part of the check), for that run's repo or every repo."""
    pages = {}
    asked = hub.input.repo if hub.input else None
    repos = [_repo(settings, asked)] if asked else settings.repo_names()
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for repo in repos:
        try:
            notes: list[str] = []
            if rescan:
                _fast(settings, repo, stamp, notes)
            pages[repo] = flow.publish_repo_page(repo, notes)["page"]
        except Exception as exc:  # noqa: BLE001 - one page never stops the others
            pages[repo] = f"not published: {type(exc).__name__}: {exc}"[:200]
    return {"refreshed": pages, "rescanned": rescan}


@workflow(inputs=RepoCheck, schedule="daily at 07:30", catch_up=True, as_tool=True, tool_wait="5m",
          surfaces=("web", "owui", "mcp"))
def check_repo():
    """Check my repo: secrets and vulnerable dependencies first (seconds), then a
    first look at the riskiest code (a few minutes, each finding double-checked),
    then previews of the newest pull requests when GitHub is connected. Results
    fill one repo page as they finish. Nothing is posted anywhere."""
    settings = gz.settings.load(hub.setting("engineering_desk"))
    if hub.trigger == "update":
        return _refresh(settings, rescan=True)
    if hub.trigger == "schedule" and not (hub.input and hub.input.repo):
        return _refresh(settings, rescan=False)
    try:
        repo = _repo(settings, hub.input.repo if hub.input else None)
    except ValueError as exc:
        return {"refused": str(exc)}
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    notes: list[str] = []

    # 1. Secrets and dependencies: seconds, and published at once.
    fast = _fast(settings, repo, stamp, notes)
    dep_summary, refuted = fast["dep_summary"], fast["refuted"]
    sweep = {"problem": fast["sweep_problem"]}
    page = flow.publish_repo_page(repo, notes)["page"]

    # 2. A first look at the riskiest code, capped.
    plan = first_look_plan(repo)
    look = _first_look(settings, repo, plan, stamp, time.time() + FIRST_LOOK_MINUTES * 60) if plan["units"] else \
        {"parts_read": 0, "parts_total": 0, "new": [], "refuted": 0,
         "stopped": plan.get("problem") or "not checked: no file the audit can read"}
    if look["parts_total"] > look["parts_read"] or look["stopped"]:
        notes.append(f"first look read {look['parts_read']} of {look['parts_total']} parts of the code, riskiest "
                     "first" + (f" ({look['stopped']})" if look["stopped"] else "")
                     + "; the weekly audit reads the rest when security is on")
    page = flow.publish_repo_page(repo, notes)["page"]

    # 3. Pull request previews, only with GitHub connected. Nothing is posted.
    pulls = newest_pulls(repo)
    previews = []
    for number in pulls["numbers"]:
        try:
            res = flow.review_pr(repo, number)
        except Exception as exc:  # noqa: BLE001 - one pull request never stops the check
            res = {"pr": f"{repo}#{number}", "failed": f"{type(exc).__name__}: {exc}"[:200]}
        previews.append({k: res[k] for k in ("pr", "verdict", "skipped", "failed", "open") if k in res})
    if previews:
        page = flow.publish_repo_page(repo, notes, previews)["page"]

    # The page's numbers (every open finding), so chat and page always agree.
    shown = page_counts(repo, stamp)
    if dep_summary:
        dep_summary["vulnerable"] = shown["vulnerable"]
    out = {"repo": repo, "page": page, **dep_summary,
           "secrets": shown["secrets"] if not sweep.get("problem") else "not checked",
           "secrets_refuted_by_second_pass": len(refuted),
           "code_findings": shown["code"], "new_code_findings": shown["new_code"],
           "code_refuted_by_second_pass": look["refuted"],
           "first_look": f"{look['parts_read']} of {look['parts_total']} parts",
           "pull_request_previews": previews or pulls["note"], "not_checked": notes}
    def count(n, word: str) -> str:
        if not isinstance(n, int):
            return f"{word}s: {n}"
        return f"{n} {word}" + ("" if n == 1 else "s")

    # From chat the page is the person's own copy; the team's copy, refreshed
    # daily from the security watch and the audit, has its own link.
    team = "" if hub.team_run else team_page_link(repo)
    if not hub.team_run:
        out["team_page"] = team or "after the daily 07:30 refresh"
    out["answer"] = (f"Checked {repo}: {count(out['secrets'], 'secret')}, "
                     f"{count(dep_summary.get('vulnerable', 'not checked'), 'vulnerable package')}, "
                     f"{count(out['code_findings'], 'code finding')} ({out['new_code_findings']} new from a first "
                     f"look at {out['first_look']}). Your copy of the page has the details: {page}"
                     + (f" The team page, updated daily: {team}" if team else
                        " The team page appears after the daily 07:30 refresh." if not hub.team_run else "")
                     + (f" Not checked: {'; '.join(notes)}." if notes else ""))
    return out
