"""security_watch: every day, every repo's dependencies against OSV.dev and the
CISA Known Exploited Vulnerabilities catalog.

  1. checkout     the default branch, read-only, in the private data folder
  2. packages     every dependency file, listed by Trivy (Swift, CocoaPods, Maven,
                  NuGet, Dart and the rest); without Trivy, the Desk's own readers
                  for Python, npm, Go, Rust, Ruby and PHP, and the rest "not checked"
  3. feeds        OSV advisories and the KEV catalog (code decides what counts);
                  CocoaPods, which OSV does not cover, through Trivy's database
  4. reachability where the code imports each package
  5. hub.call_llm judge reachability and write impact and fix, once per advisory
  6. ledger       new, worse and resolved, so nothing is alerted twice
  7. per group    a page for the agent's users and an email to the group's list

A check that could not run (a feed outage, an unreadable lockfile, a repo the
token cannot read) is reported in the email as a coverage problem, never as
silence. Pull requests that change a lockfile are checked in their review.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

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


@step()
def security_plan() -> dict:
    settings = gz.settings.load(hub.setting("engineering_desk"))
    groups = {g: {"repos": grp.repos, "email_list": grp.email_list} for g, grp in settings.security_scope().items()}
    return {"groups": groups, "nothing_on": "" if groups else gz.settings.nothing_on(settings, "security"), "stamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}


@step(max_attempts=2)
def scan(repo: str) -> dict:
    """Advisories for one repo that pass the feed gate, with where the code
    imports each package. Raises nothing: a failure is a coverage problem."""
    return flow.dependency_scan(repo)


@step()
def security_record(repo: str, items: list[dict], ignored: list[dict], stamp: str, clean: bool, complete: bool,
                    skipped_files: list[str] = ()) -> dict:
    return flow.record_dependencies(repo, items, ignored, stamp, clean, complete, skipped_files)


@step()
def security_group_view(repos: list[str]) -> dict:
    store = gz.store.Store(hub.data_dir)
    return {"open": store.ledger_rows(repos, state="open"), "coverage": store.coverage(repos)}


@step()
def security_after_email(sent_ok: bool, keys: list[str], coverage: list[dict]) -> None:
    """An alert counts as given only once its email went out; otherwise the
    next run alerts again."""
    store = gz.store.Store(hub.data_dir)
    if not sent_ok:
        store.unalert(keys)
        return
    for c in coverage:
        store.coverage_alerted(c["repo"], c["check_name"])


@workflow(schedule="daily at 06:00", catch_up=True)
def security_watch():
    p = security_plan()
    if p["nothing_on"]:
        return {"skipped": p["nothing_on"]}
    settings = gz.settings.load(hub.setting("engineering_desk"))
    out = {}
    for group, g in p["groups"].items():
        changes = {"new": [], "escalated": [], "resolved": []}
        summary = []
        for repo in g["repos"]:
            s = scan(repo)
            if s.get("error"):
                summary.append({"repo": repo, "error": s["error"]})
                continue
            items, ignored = flow.judge_dependencies(settings, repo, s)
            c = security_record(repo, items, ignored, p["stamp"], not s["notes"], s["complete"], s.get("skipped", []))
            for k in changes:
                changes[k] += [{**x, "repo": repo} for x in c[k]]
            # No dependency file read is "not checked", never "0 advisories".
            summary.append({"repo": repo, "dependencies": flow.dependency_count(s),
                            "advisories": len(items),
                            "new": len(c["new"]), "worse": len(c["escalated"]), "resolved": len(c["resolved"]),
                            "unused_dropped": s["unused"], "notes": s["notes"],
                            "page": flow.publish_repo_page(repo)["page"]})
        view = security_group_view(g["repos"])
        problems = gz.runtime.due_coverage(view["coverage"])
        art, sent = None, None
        if changes["new"] or changes["escalated"] or problems:
            # One page per alert, never replaced: an emailed link always shows what was sent.
            html = gz.render.security_page(group, p["stamp"], changes, view["open"], view["coverage"])
            art = gz.runtime.publish(hub, f"security-{group}", html, f"Security · {group} · {p['stamp'][:10]}",
                                     key=None, team_audience="hub")
            subject, body = gz.mail.security_email(changes, problems, len(g["repos"]), gz.runtime.link_of(art),
                                                   repos=gz.runtime.pr_repos(settings))
            sent = gz.runtime.email_list(hub, g["email_list"], subject, body, art)
            security_after_email(gz.runtime.delivered(sent), [x["key"] for x in changes["new"] + changes["escalated"]],
                        problems)
        out[group] = {"repos": summary, "page": gz.runtime.link_of(art), "emailed": bool(sent),
                      "email_list": g["email_list"]}
    return out
