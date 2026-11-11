"""Plan step 3, task 7: "Check my repo". Secrets and dependencies first, on the
repo page at once; then a capped first look at the riskiest code; then pull
request previews only with GitHub connected. Nothing is posted."""
from __future__ import annotations

import functools
import shutil

import httpx
import pytest
import yaml

from tests import engineering_desk_harness as h
from tests.test_engineering_desk_local import REPO as LOCAL_REPO, folder  # noqa: F401  (fixture)

REPO = "kestrel-oak/storefront"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h.isolate(monkeypatch)
    return h.make_hub(tmp_path / "hub")


def _pages(result):
    return [a for a in result.artifacts if (a.get("key") or "").startswith("repo-")]


def test_check_my_repo_publishes_secrets_and_dependencies_first(hub):
    r = h.run_local(h.wf(hub, "check_repo"), hub_dir=hub, inputs={"repo": "storefront"})
    out = r.value
    pages = _pages(r)
    assert len(pages) >= 2 and len({p["key"] for p in pages}) == 1  # one link, filled as results finish
    assert "pyyaml" in pages[0]["html"].lower()                     # dependencies were on the first copy
    assert out["repo"] == REPO and out["page"] and out["vulnerable"] >= 1
    assert out["first_look"].endswith("parts") and out["code_findings"] >= 0
    assert out["pull_request_previews"] == "Connect GitHub to preview pull request reviews."
    assert "Checked kestrel-oak/storefront" in out["answer"] and out["page"] in out["answer"]
    assert r.emails == []                                           # a first run emails no one
    assert "weekly_digest" not in str(r.calls)


def test_the_first_look_is_capped(hub):
    check = h.wf(hub, "check_repo")
    import sys
    module = sys.modules[check.__module__]
    module.FIRST_LOOK_PARTS = 1
    try:
        out = h.run_local(check, hub_dir=hub).value
    finally:
        module.FIRST_LOOK_PARTS = 6
    assert out["first_look"].startswith("1 of ") and any("first look read 1 of" in n for n in out["not_checked"])


def test_an_unknown_repo_is_refused(hub):
    out = h.run_local(h.wf(hub, "check_repo"), hub_dir=hub, inputs={"repo": "nope"}).value
    assert "not one of Engineering Desk's repos" in out["refused"]


@pytest.fixture
def local_hub(tmp_path, monkeypatch, folder):  # noqa: F811
    h.isolate(monkeypatch)
    hub = h.make_hub(tmp_path / "hub")
    doc = h.settings_doc(hub)
    block = {k: v for k, v in doc["engineering_desk"].items() if k not in ("security_groups", "digest_groups")}
    doc["engineering_desk"] = {**block, "version": 2, "source": "local",
                               "repos": [{"name": LOCAL_REPO, "path": str(folder), "security": True}]}
    (hub / "workflows" / "settings.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "no-pinned-builds"))
    gz = h.flow(hub).gz
    monkeypatch.setattr(gz.scanners, "find", functools.partial(gz.scanners.find, download=False))
    offline = httpx.MockTransport(lambda request: httpx.Response(
        200, json={"results": []} if "querybatch" in str(request.url) else {"vulnerabilities": []}))
    monkeypatch.setattr(gz.runtime, "make_feeds", lambda settings, hub_dir: gz.security.Feeds(transport=offline))
    return hub


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_the_repo_check_runs_on_a_local_folder_with_no_github_token(local_hub):
    def llm(prompt, system, response_model):
        if response_model.__name__ == "Verification":
            return {"verdicts": [{"index": 0, "verdict": "confirmed", "severity": "high", "reason": "A live token."}]}
        return {"findings": []}

    r = h.run_local(h.wf(local_hub, "check_repo"), hub_dir=local_hub, llm=h.scripted(llm))
    out = r.value
    assert out["repo"] == LOCAL_REPO and out["secrets"] == 1  # the key only the history still has
    assert out["dependencies"] == "not checked: no dependency file found"
    page = _pages(r)[-1]["html"]
    assert "App/Auth/Login.swift" in page and "in commit" in page
    assert out["pull_request_previews"] == "Connect GitHub to preview pull request reviews."


def test_files_without_pinned_versions_are_checked_not_missing(hub):
    count = h.flow(hub).dependency_count
    assert count({"deps": 3, "files": 1}) == 3
    assert count({"deps": 0, "files": 2}) == "0: no exact version pinned in 2 dependency files"
    assert count({"deps": 0, "files": 0}) == "not checked: no dependency file found"


def test_a_first_check_leaves_its_findings_for_the_next_watch_to_email_once(hub):
    """"Check my repo" sends no email, so it saves findings unalerted: the next
    security watch emails them once, and not again."""
    h.run_local(h.wf(hub, "check_repo"), hub_dir=hub, inputs={"repo": "storefront"})
    store = h.lib(hub).store.Store(hub / ".hubzoid" / "data")
    deps = store.ledger_rows([REPO], kind="dependency")
    assert deps and all(not r["alerted_at"] for r in deps)
    watch = h.wf(hub, "security_watch")
    first = h.run_local(watch, hub_dir=hub, trigger="schedule")
    assert first.emails and "pyyaml" in first.emails[0]["body"].lower()
    again = h.run_local(watch, hub_dir=hub, trigger="schedule")
    assert again.emails == []


def test_chat_gives_the_pages_numbers(hub):
    """The page shows every open finding; the answer says the same numbers,
    with what this run found new beside them."""
    first = h.run_local(h.wf(hub, "check_repo"), hub_dir=hub, inputs={"repo": "storefront"}).value
    second = h.run_local(h.wf(hub, "check_repo"), hub_dir=hub, inputs={"repo": "storefront"}).value
    rows = h.lib(hub).store.Store(hub / ".hubzoid" / "data").ledger_rows([REPO], state="open")
    code = sum(1 for r in rows if r["kind"] == "audit" and r.get("advisory") != "secret")
    assert second["code_findings"] == code and second["code_findings"] >= first["new_code_findings"]
    assert f"{code} code findings ({second['new_code_findings']} new" in second["answer"]
    assert second["vulnerable"] == sum(1 for r in rows if r["kind"] == "dependency")
