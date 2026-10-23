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


def test_a_new_repos_first_reviews_wait_for_its_profile(hub):
    switch(hub, reviews=True)
    h.write_settings(hub, {"review": {"wait_for_profile_minutes": 10}})
    first = run(hub, "pr_sweep")
    assert first["waiting_for_profile"] == [REPO] and first["reviews"] == []
    run(hub, "repo_profiles")
    second = run(hub, "pr_sweep")
    assert second["waiting_for_profile"] == [] and len(second["reviews"]) == 5


def test_turning_a_switch_on_does_not_re_review(hub):
    switch(hub, reviews=True)
    assert len(run(hub, "pr_sweep")["reviews"]) == 5
    switch(hub, reviews=True, security=True, reports=True)
    assert run(hub, "pr_sweep")["reviews"] == []


# ------------------------------------------------- found by the Codex review

def test_the_review_fingerprint_sees_exactly_what_it_saw_before_the_switches():
    """Hubs from the bundled template keep their fingerprints, so upgrading
    neither re-reviews nor releases a skipped backlog."""
    s = load({"source": "github", "repos": [{"name": "a/api", "reviews": True}]})
    repo = s.repo("a/api").model_dump(exclude={"reviews", "security", "reports"})
    review = s.review.model_dump(exclude={"wait_for_profile_minutes"})
    assert set(repo) == {"name", "severity_floor", "model", "context", "commands", "status_check", "exclude_paths"}
    assert set(review) == {"severity_floor", "backlog", "first_run_limit", "max_prs_per_run", "max_findings",
                           "max_age_days", "max_diff_chars", "verify", "post_to_github", "summary_on_clean",
                           "auto_pause_after", "skip_label", "skip_drafts", "skip_bots", "status_check", "model"}


def _event(kind, body):
    return {"body": {**body, "repository": {"full_name": REPO, "default_branch": "main"}},
            "headers": {"x-github-event": kind, "x-github-delivery": f"d-{kind}"}}


def test_a_rules_push_reviews_nothing_when_reviews_are_off(hub):
    switch(hub, security=True)
    pushed = run(hub, "github_events", trigger="webhook", event=_event("push", {
        "ref": "refs/heads/main", "commits": [{"added": [], "modified": ["review.md"], "removed": []}]}))
    assert pushed["rules_changed"] and "re_reviewed" not in pushed


def test_webhook_reviews_wait_for_the_first_profile_too(hub):
    switch(hub, reviews=True)
    h.write_settings(hub, {"review": {"wait_for_profile_minutes": 10}})
    pr = run(hub, "github_events", trigger="webhook", event=_event("pull_request", {
        "action": "opened", "pull_request": {"number": 102}}))
    assert "first profile" in pr["deferred"]


def test_a_sweep_where_every_repo_waits_is_not_the_safety_sweep(hub):
    switch(hub, reviews=True)
    h.write_settings(hub, {"trigger": "webhook", "review": {"wait_for_profile_minutes": 10}})
    assert run(hub, "pr_sweep")["waiting_for_profile"] == [REPO]
    run(hub, "repo_profiles")
    assert len(run(hub, "pr_sweep")["reviews"]) == 5  # not held back for 30 minutes


def test_a_repo_that_cannot_be_read_costs_no_model_call(hub, monkeypatch):
    calls = []
    flow = h.flow(hub)
    real = flow.charge
    monkeypatch.setattr(flow, "charge", lambda n=1: calls.append(n) or real(n))
    monkeypatch.setattr(h.lib(hub).checkout, "ensure", lambda *a, **k: (_ for _ in ()).throw(OSError("unreachable")))
    out = run(hub, "repo_profiles")
    assert out["built"][0]["error"].startswith("OSError") and calls == []


def test_a_report_someone_asks_for_covers_the_whole_group():
    s = load({"version": 2, "source": "github",
              "repos": [{"name": "a/api", "reports": True}, {"name": "a/web"}],
              "digest_groups": {"team": {"repos": ["a/api", "a/web"], "monthly_reports": ["code"]}}})
    req = gz().reports.ReportRequest(period="last_month", group="team")
    assert gz().reports.scope(req, s) == ("team", ["a/api", "a/web"])
    assert gz().reports.scope(req, s, scheduled=True) == ("team", ["a/api"])


def test_doctor_reads_the_hub_env_over_the_shell(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("gz_doctor", h.TEMPLATE / "doctor" / "checks.py")
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    (tmp_path / ".env").write_text("HUBZOID_SCHEDULES=1\n")
    monkeypatch.setenv("HUBZOID_SCHEDULES", "0")
    assert checks._env(tmp_path)["HUBZOID_SCHEDULES"] == "1"
