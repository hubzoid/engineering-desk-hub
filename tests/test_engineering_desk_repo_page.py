"""Plan step 3, task 6: one page per repo, behind one link that always shows
the latest run."""
from __future__ import annotations

import pytest

from tests import engineering_desk_harness as h
from tests.engineering_desk_harness import template_lib

gz = template_lib()
REPO = "kestrel-oak/storefront"


def _row(**kw):
    return {"kind": "audit", "state": "open", "severity": "high", "advisory": "authorization", "path": "app/a.py",
            "line": 3, "title": "t", "impact": "", "package": None, "version": None, "fix": "", "kev": 0, **kw}


def test_a_check_that_never_ran_is_not_checked_never_zero():
    html = gz.render.repo_page(REPO, "2026-11-08T10:00:00+00:00", [], [])
    assert html.count("not checked") >= 3 and "<b>0</b>" not in html
    assert html.count("Not checked yet.") == 3


def test_the_page_shows_secrets_packages_and_double_checked_findings():
    rows = [_row(advisory="secret", path="App/Keys.swift", line=4, title="A secret (github-pat) is committed here."),
            _row(kind="dependency", advisory="GHSA-1", package="SwiftNIO", version="2.40.0", path="Podfile.lock",
                 impact="Used: HTTPDecoder parses client requests in Server.swift.", fix="Upgrade to 2.41.0"),
            _row(kind="dependency", state="ignored", advisory="GHSA-2", package="yaml", version="5.3",
                 impact="Only safe_load is called."),
            _row(severity="medium", path="app/z.py", title="Minor"), _row(path="app/b.py", title="Admin route open"),
            _row(state="resolved", title="Old and fixed")]
    coverage = [{"check_name": c, "last_ok": "2026-11-08T10:00:00", "last_error": None}
                for c in ("secret scan", "dependencies", "audit")]
    html = gz.render.repo_page(REPO, "2026-11-08T10:00:00+00:00", rows, coverage)
    assert "App/Keys.swift" in html and "<td>4</td>" in html
    assert "SwiftNIO" in html and "Used: HTTPDecoder parses client requests" in html and "Upgrade to 2.41.0" in html
    assert "1 more judged not reachable" in html and "Only safe_load is called." in html
    assert html.index("Admin route open") < html.index("Minor")  # worst first
    assert "Old and fixed" not in html and "survived a second pass" in html
    assert "checked 2026-11-08 10:00" in html and "Exploited-now list" in html


def test_a_check_with_a_problem_says_so_at_the_top():
    coverage = [{"check_name": "audit", "last_ok": None, "last_error": "not checked: all 4 files are excluded"}]
    html = gz.render.repo_page(REPO, "2026-11-08T10:00:00+00:00", [], coverage, ["Podfile.lock: not checked without Trivy"])
    top = html.index("Part of this repo was not checked")
    assert top < html.index("<h2>Secrets</h2>") and "all 4 files are excluded" in html and "without Trivy" in html
    twice = gz.render.repo_page(REPO, "2026-11-08T10:00:00+00:00", [], coverage, ["not checked: all 4 files are excluded"])
    assert twice.count("all 4 files are excluded") == 1  # a note that repeats a check's problem is said once


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h.isolate(monkeypatch)
    return h.make_hub(tmp_path)


def test_running_the_check_twice_leaves_one_link_with_the_newer_result(hub):
    h.run_local(h.wf(hub, "security_watch"), hub_dir=hub, trigger="schedule")   # finds PyYAML
    check = h.wf(hub, "check_repo")
    first = h.run_local(check, hub_dir=hub, trigger="schedule")                 # the daily refresh
    second = h.run_local(check, hub_dir=hub, trigger="schedule")
    pages = [next(a for a in r.artifacts if (a.get("key") or "").startswith("repo-")) for r in (first, second)]
    assert pages[0]["key"] == pages[1]["key"] == h.flow(hub).repo_page_key(REPO)
    assert first.value["refreshed"][REPO] and first.value["refreshed"] == second.value["refreshed"]
    assert first.calls == []  # a refresh scans nothing and asks no model
    assert "pyyaml" in pages[1]["html"].lower() and "Vulnerable packages" in pages[1]["html"]
    keys = {h.flow(hub).repo_page_key(r) for r in ("a/b", "a-b/c", "A/B")}
    assert len(keys) == 3 and all(k.startswith("repo-") and k == k.lower() for k in keys)


def test_only_check_repo_publishes_repo_pages():
    """Hubzoid gives a page key to one workflow: a second workflow publishing
    the same repo page fails its run (found running the hub end to end; the
    test harness does not enforce key ownership)."""
    folder = h.TEMPLATE / "workflows" / "engineering_desk"
    users = sorted(p.name for p in folder.glob("*.py") if "publish_repo_page(" in p.read_text() and p.name != "_flow.py")
    assert users == ["check_repo.py"]


def test_the_watch_and_the_audit_publish_no_repo_page(hub):
    for name in ("security_watch", "deep_audit"):
        r = h.run_local(h.wf(hub, name), hub_dir=hub, trigger="schedule")
        assert not any((a.get("key") or "").startswith("repo-") for a in r.artifacts), name


def test_chat_links_the_team_page_once_a_team_run_has_published_it(hub):
    """A check from chat can only write the person's own copy. Its answer also
    gives the team's page, which the daily run keeps up to date."""
    check = h.wf(hub, "check_repo")
    mine = h.run_local(check, hub_dir=hub, inputs={"repo": "storefront"})  # from chat: the person's run
    assert "The team page appears after the daily 07:30 refresh." in mine.value["answer"]
    team = h.run_local(check, hub_dir=hub, trigger="schedule").value["refreshed"][REPO]  # the 07:30 team run
    again = h.run_local(check, hub_dir=hub, inputs={"repo": "storefront"}).value
    assert again["team_page"] == team and f"The team page, updated daily: {team}" in again["answer"]


def test_update_now_rescans_secrets_and_dependencies(hub):
    """The 07:30 run only redraws; Update now on the page runs the fast part of
    the check first, so something new shows up without waiting for the watch."""
    check = h.wf(hub, "check_repo")
    redraw = h.run_local(check, hub_dir=hub, trigger="schedule")
    page = next(a for a in redraw.artifacts if (a.get("key") or "").startswith("repo-"))
    assert "pyyaml" not in page["html"].lower() and redraw.value["rescanned"] is False
    update = h.run_local(check, hub_dir=hub, trigger="update")
    page = next(a for a in update.artifacts if (a.get("key") or "").startswith("repo-"))
    assert update.value["rescanned"] is True and "pyyaml" in page["html"].lower()
