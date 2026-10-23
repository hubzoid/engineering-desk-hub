"""Per-repo switches: nothing runs on its own until a repo turns it on. A hub
made from the template bundled with Hubzoid 2.0.1 (no `version`) keeps
everything on. Run on the sample with Hubzoid's run_local, no model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tests import gitzoid_harness as h

REPO = "kestrel-oak/storefront"
SHIPPED = h.TEMPLATE / "workflows" / "settings.yaml"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h.isolate(monkeypatch)
    return h.make_hub(tmp_path)


def gz():
    return h.template_lib()


def load(block: dict):
    return gz().settings.load(block)


def switch(hub, **on):
    """The sample repo with only the named switches on."""
    h.write_settings(hub, {"repos": [{"name": REPO, **on}]})


def run(hub, name, trigger="schedule", **kw):
    return h.run_local(h.wf(hub, name), hub_dir=hub, trigger=trigger, **kw).value


# ------------------------------------------------------------------ settings

def test_the_shipped_settings_watch_nothing():
    doc = yaml.safe_load(SHIPPED.read_text())
    s = load(doc["gitzoid"])
    assert (s.version, s.source, s.repos) == (2, "github", [])
    assert s.review_repos() == s.security_repos() == s.report_repos() == []
    assert s.security_scope() == {} and s.report_groups() == {}
    assert gz().settings.publishing(s) == "preview"
    assert "github" in doc["webhooks"]  # github_events needs it to load


def test_a_repo_gets_only_what_it_switches_on():
    s = load({"version": 2, "source": "github", "repos": [
        {"name": "a/api", "reviews": True, "security": True}, {"name": "a/web", "reports": True}, "a/docs"]})
    assert s.repo_names() == ["a/api", "a/web", "a/docs"]
    assert (s.review_repos(), s.security_repos(), s.report_repos()) == (["a/api"], ["a/api"], ["a/web"])
    assert s.switches("a/docs") == {"reviews": False, "security": False, "reports": False}
    assert list(s.security_scope()) == ["unassigned"] and s.security_scope()["unassigned"].repos == ["a/api"]


def test_without_a_version_everything_stays_on():
    s = load({"source": "github", "repos": ["a/api", "a/web"], "owner_list": "owners"})
    assert s.legacy and s.review_repos() == s.security_repos() == s.report_repos() == ["a/api", "a/web"]
    assert s.security_scope()["unassigned"].email_list == "owners"
    assert s.report_groups() == {}  # the weekly digest keeps its own implicit group, as before


def test_report_and_security_email_lists():
    s = load({"version": 2, "source": "github", "repos": [{"name": "a/api", "reports": True, "security": True}],
              "email": {"security": "sec", "reports": "leads"}})
    assert s.security_scope()["unassigned"].email_list == "sec"
    group = s.report_groups()["all"]
    assert (group.repos, group.email_list, group.monthly_reports) == (["a/api"], "leads", ["code", "delivery"])


def test_named_groups_keep_only_repos_with_the_switch():
    s = load({"version": 2, "source": "github",
              "repos": [{"name": "a/api", "reports": True, "security": True}, {"name": "a/web"}],
              "digest_groups": {"team": {"repos": ["a/api", "a/web"], "monthly_reports": ["code"]}},
              "security_groups": {"plat": {"repos": ["a/web"]}}})
    assert s.report_groups()["team"].repos == ["a/api"]
    assert list(s.security_scope()) == ["unassigned"]  # a/web has security off, so plat is empty


def test_sample_mode_needs_no_repo_list_and_never_publishes():
    s = load({"version": 2, "source": "sample", "review": {"post_to_github": True}})
    assert s.repo_names() == [REPO] and s.review_repos() == [REPO]
    assert gz().settings.publishing(s) == "preview"


def test_an_unknown_switch_is_named():
    with pytest.raises(gz().settings.SettingsError, match="review"):
        load({"version": 2, "repos": [{"name": "a/api", "review": True}]})


# ----------------------------------------------------------------- workflows

def test_with_everything_off_each_scheduled_workflow_says_how_to_turn_it_on(hub):
    switch(hub)
    assert "reviews: true" in run(hub, "pr_sweep")["skip"]
    assert "security: true" in run(hub, "security_watch")["skipped"]
    assert "security: true" in run(hub, "deep_audit")["skipped"]
    assert "reports: true" in run(hub, "weekly_digest")["skipped"]
    h.write_settings(hub, {"digest_groups": {}, "security_groups": {}})
    assert "reports: true" in run(hub, "code_report", inputs={"period": "last_month"})["skipped"]


def test_reviews_off_ignores_pull_request_events_but_not_pushes(hub):
    switch(hub, security=True)
    event = lambda kind, body: {"body": {**body, "repository": {"full_name": REPO, "default_branch": "main"}},  # noqa: E731
                                "headers": {"x-github-event": kind, "x-github-delivery": f"d-{kind}"}}
    pr = run(hub, "github_events", trigger="webhook", event=event("pull_request", {
        "action": "opened", "pull_request": {"number": 102}}))
    assert "reviews are off" in pr["ignored"]
    pushed = run(hub, "github_events", trigger="webhook", event=event("push", {
        "ref": "refs/heads/main", "commits": [{"added": [], "modified": ["app/auth.py"], "removed": []}]}))
    assert "ignored" not in pushed


def test_reviews_on_reviews_only_that_repo(hub):
    switch(hub, reviews=True)
    reviewed = {r["pr"] for r in run(hub, "pr_sweep")["reviews"]}
    assert reviewed and all(p.startswith(REPO) for p in reviewed)
    assert "security: true" in run(hub, "security_watch")["skipped"]


def test_a_report_can_still_be_asked_for_when_reports_are_off(hub):
    switch(hub)
    h.write_settings(hub, {"digest_groups": {}, "security_groups": {}})
    out = h.run_local(h.wf(hub, "delivery_report"), hub_dir=hub, trigger="tool", as_user=h.PERSON,
                      inputs={"period": "last_n_days", "days": 30, "repos": [REPO]}).value
    assert "skipped" not in out


# --------------------------------------------------------------- rules, chat

def test_example_rules_are_off_outside_sample_mode(hub):
    rules = lambda: {r["title"] for r in h.lib(hub).rules.hub_rules(hub)}  # noqa: E731
    assert rules()  # the test hub is in sample mode
    h.write_settings(hub, {"source": "github"})
    assert rules() == set()
    own = hub / "knowledge" / "review-rules" / "ours.md"
    own.write_text("---\ntitle: Our rule\n---\nNo secrets in logs.\n")
    assert rules() == {"Our rule"}


def test_status_shows_switches_and_mode(hub, monkeypatch):
    switch(hub, reports=True)
    monkeypatch.setenv("HUBZOID_HUB_DIR", str(hub))  # as the hub's bridge sets it for its tools
    with h.as_person():
        status = json.loads(h.invoke(h.tools(hub)["gitzoid_status"]))
    assert status["repos"][0]["on"] == {"reviews": False, "security": False, "reports": True}
    assert status["publishing"].startswith("preview")


def test_profiles_are_made_for_missing_repos_and_checked_once_a_day(hub, monkeypatch):
    first = run(hub, "repo_profiles")
    assert [b["repo"] for b in first["built"]] == [REPO]
    calls = []
    sample = h.lib(hub).sample.SampleGitHub
    monkeypatch.setattr(sample, "branch_sha", lambda self, *a, **k: calls.append(a) or "same")
    again = run(hub, "repo_profiles")
    assert again["built"] == [] and calls == []  # the code-changed check already ran today
