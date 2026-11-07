"""Plan step 2, task 4: scanner hits are double-checked. A secret the pattern
sweep or Gitleaks finds goes through the second pass, which drops a test
fixture's fake key with a reason and keeps a real one; and the deep audit
scans the whole repo for secrets every week."""
from __future__ import annotations

import json
import random
import shutil
import string

import pytest

from tests import engineering_desk_harness as h
from tests.engineering_desk_harness import template_lib

gz = template_lib()
REPO = "kestrel-oak/storefront"


def _token(seed: int) -> str:
    # Built at run time so this file is not itself a secret to a scanner.
    return "ghp_" + "".join(random.Random(seed).choices(string.ascii_letters + string.digits, k=36))


# ------------------------------------------------------- pull request reviews

def test_gitleaks_results_are_secrets_and_other_tools_are_hints():
    doc = {"runs": [{"results": [{"ruleId": "github-pat", "locations": [{"physicalLocation": {
        "artifactLocation": {"uri": "app/settings.py"}, "region": {"startLine": 3}}}]}]}]}
    assert gz.checks.parse_sarif(doc, "gitleaks", secret=True)[0]["secret"]
    assert not gz.checks.parse_sarif(doc, "ruff")[0]["secret"]


def test_secrets_go_to_the_second_pass_and_checked_facts_do_not():
    secret = {"path": "a.py", "line": 3, "rule": "secret: github-pat", "checked": True}
    advisory = {"path": "requirements.txt", "line": 2, "rule": "dependency advisory", "checked": True}
    team_rule = {"path": "a.py", "line": 9, "rule": "no print in handlers", "checked": True}
    model = {"path": "a.py", "line": 12, "rule": "", "checked": False}
    assert gz.review.to_verify([secret, advisory, team_rule, model]) == [secret, model]


def test_a_fixture_key_is_dropped_with_a_reason_and_a_real_one_is_kept():
    checks = [{"tool": "gitleaks", "rule": "github-pat", "path": "app/settings.py", "line": 3, "secret": True},
              {"tool": "gitleaks", "rule": "github-pat", "path": "tests/fixtures/keys.py", "line": 1, "secret": True}]
    found = [{**f, "checked": True} for f in gz.checks.secret_findings(checks)]
    lines = {("app/settings.py", 3), ("tests/fixtures/keys.py", 1)}
    kept = gz.review.gate(found, lines, "high", 8)
    todo = gz.review.to_verify(kept)
    assert {f["path"] for f in todo} == {"app/settings.py", "tests/fixtures/keys.py"}
    fixture = next(i for i, f in enumerate(todo) if f["path"].startswith("tests/"))
    verdicts = [{"index": fixture, "verdict": "refuted", "reason": "A made-up token in a test fixture."},
                {"index": 1 - fixture, "verdict": "confirmed", "severity": "high", "reason": "A live token."}]
    kept, dropped = gz.review.apply_verdicts(kept, todo, verdicts)
    assert [f["path"] for f in kept] == ["app/settings.py"]
    assert dropped[0]["path"] == "tests/fixtures/keys.py" and dropped[0]["reason"] == "A made-up token in a test fixture."


def test_the_second_pass_is_told_what_a_fake_secret_looks_like():
    f = {"severity": "high", "category": "security", "path": "a.py", "line": 1, "body": "A secret."}
    assert "a key in a test fixture" in gz.review.verify_prompt([f], {"a.py": "TOKEN = 'x'\n"})


# ----------------------------------------------------- the weekly secret scan

@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_the_whole_repo_scan_finds_a_planted_key_and_ignores_the_repos_own_allowlist(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/config.py").write_text(f'GITHUB_TOKEN = "{_token(1)}"\n')
    (tmp_path / "Pods/Lib").mkdir(parents=True)
    (tmp_path / "Pods/Lib/Keys.swift").write_text(f'let token = "{_token(2)}"\n')  # vendored: not ours
    (tmp_path / ".gitleaks.toml").write_text('[extend]\nuseDefault = true\n[allowlist]\npaths = [".*"]\n')
    hits = gz.checks.secret_scan(tmp_path, shutil.which("gitleaks"))
    assert [(x["path"], x["line"]) for x in hits] == [("app/config.py", 1)]
    assert hits[0]["rule"] == "github-pat" and hits[0]["commit"] == ""


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h.isolate(monkeypatch)
    return h.make_hub(tmp_path / "hub")


@pytest.fixture
def fake_gitleaks(tmp_path, monkeypatch):
    """A 'gitleaks' on PATH that reports one real-looking key and one in a
    test fixture, as Gitleaks reports them: absolute paths under the scanned folder."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    report = [{"File": "{root}/app/sync.py", "StartLine": 2, "RuleID": "github-pat"},
              {"File": "{root}/CONTRIBUTING.md", "StartLine": 1, "RuleID": "generic-api-key"}]
    (bin_dir / "report.json").write_text(json.dumps(report))
    exe = bin_dir / "gitleaks"
    exe.write_text(f"#!/bin/sh\nsed \"s#{{root}}#$2#g\" {bin_dir}/report.json\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "no-pinned-builds"))


def test_the_weekly_scan_alerts_only_the_secrets_the_second_pass_keeps(hub, fake_gitleaks):
    asked = []

    def llm(prompt, system, response_model):
        if response_model.__name__ == "Verification" and "secret" in prompt and "CONTRIBUTING.md" in prompt:
            asked.append(prompt)
            fake = 0 if prompt.index("CONTRIBUTING.md") < prompt.index("app/sync.py") else 1
            return {"verdicts": [{"index": fake, "verdict": "refuted", "severity": "low",
                                  "reason": "Documentation shows a placeholder."},
                                 {"index": 1 - fake, "verdict": "confirmed", "severity": "high", "reason": "Live."}]}
        if response_model.__name__ == "Verification":
            return {"verdicts": []}
        return {"findings": []}

    r = h.run_local(h.wf(hub, "deep_audit"), hub_dir=hub, trigger="schedule", llm=h.scripted(llm))
    assert asked, "the secrets went to the second pass"
    store = h.lib(hub).store.Store(hub / ".hubzoid" / "data")
    secrets = [row for row in store.ledger_rows([REPO], kind="audit") if row["advisory"] == "secret"]
    assert [(row["path"], row["line"]) for row in secrets] == [("app/sync.py", 2)]
    assert r.value["new_findings"] == 1 and r.value["audited"][0]["refuted_by_second_pass"] == 1


def test_in_the_sample_a_missing_gitleaks_is_a_note_and_the_audit_still_runs(hub, monkeypatch, tmp_path):
    """The sample is fictional and offline: no alert for its scanner. A real
    repo gets a "secret scan not run" coverage problem instead."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "none"))
    r = h.run_local(h.wf(hub, "deep_audit"), hub_dir=hub, trigger="schedule")
    store = h.lib(hub).store.Store(hub / ".hubzoid" / "data")
    assert not any(c["check_name"] == "secret scan" and c["last_error"] for c in store.coverage([REPO]))
    assert r.value["audited"] and r.emails == []
