"""Check Engineering Desk setup without a model call or any GitHub writes."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from hubzoid import hub, step, workflow

path = Path(__file__).with_name("_flow.py")
name = "engineering_desk_flow_" + hashlib.sha1(str(path).encode()).hexdigest()[:10]
if name not in sys.modules:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
flow = sys.modules[name]
gz = flow.gz


@step()
def check() -> dict:
    settings, store, gh = flow.ctx()
    repos = []
    for repo in settings.repo_names():
        try:
            branch = gh.default_branch(repo)
            sha = gh.branch_sha(repo, branch)
            pulls = gh.open_pulls(repo)
            controls = flow.controls(gh, store, repo, fresh=True)
            eligible = [p for p in pulls if not flow.gz.rules.skip_reason(p, settings.review, controls)]
            ci = gh.ci_status(repo, sha)
            # Read permissions are exercised. Write permissions are not tested by mutating a repo.
            identity = gh.login()
            repos.append({"repo": repo, "ready": True, "on": settings.switches(repo), "identity": identity, "default_branch": branch,
                          "open": len(pulls), "eligible": len(eligible), "ci": ci,
                          "profile": "ready" if store.profile(repo) else "made within a few minutes of the hub running"})
        except Exception as exc:
            repos.append({"repo": repo, "ready": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
    from hubzoid.access import store_for
    subject = hub.user.email or hub.user.id
    access = store_for(flow.HUB_DIR).can(subject, hub.name, "engineering_desk")
    return {"chat_tools": "enabled for " + subject if access else
            "Not enabled for " + subject + ". Grant Engineering Desk tools in Settings, Agents, Engineering Desk, Access, "
            "or run: hubzoid grant " + subject + " engineering_desk .",
            "source": settings.source, "repos": repos,
            "ready": bool(repos) and all(r["ready"] for r in repos),
            "switches": "version 1 settings: every repo has everything on. Add version: 2 and per-repo switches to choose."
            if settings.legacy else "per repo, reviews, security and reports are off unless set to true",
            "publishing": "live" if gz.settings.publishing(settings) == "live" else "preview; nothing written to GitHub",
            "backlog": settings.review.backlog, "reviews_per_sweep": settings.review.max_prs_per_run,
            "model": "uses MODEL in the Hub .env unless a workflow override is selected; not tested by this check",
            "next": ("Add repos and switches in workflows/settings.yaml." if not repos else
                     "Start hubzoid run (with HUBZOID_SCHEDULES=1). Results are in Settings, Agents, Engineering Desk, Runs & schedules, "
                     "or ask Engineering Desk in chat."),
            "write_permissions": "not tested; posting requires Pull requests and Issues write, Commit statuses write",
            "email": "optional; no email is sent by this check"}


@workflow()
def setup_check():
    return check()
