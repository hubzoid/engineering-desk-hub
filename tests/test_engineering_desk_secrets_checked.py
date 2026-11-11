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
    dropped = store.ledger_rows([REPO], state="refuted", kind="audit")
    assert [(row["path"], row["impact"]) for row in dropped] == [("CONTRIBUTING.md", "Documentation shows a placeholder.")]
    assert not dropped[0]["alerted_at"]


def test_a_dropped_secret_is_kept_with_its_reason_and_reopens_if_confirmed(tmp_path):
    """The plan's "dropped with a reason": the reason is stored and shown on the
    repo page, folded away. A later confirmation opens and alerts it; a
    refutation never closes an open one; one no longer found goes away."""
    store = gz.store.Store(tmp_path)
    fake = gz.audit.secret_findings([{"path": "tests/fixtures/keys.py", "line": 1, "rule": "github-pat"}])[0]
    live = gz.audit.secret_findings([{"path": "app/settings.py", "line": 3, "rule": "github-pat"}])[0]
    why = f"A made-up token ({_token(5)}) in a test fixture."
    gz.audit.record(store, REPO, [live], ["app/settings.py"], tmp_path, "2026-11-01")
    gz.audit.record_refuted(store, REPO, [{**fake, "reason": why}], "2026-11-01")
    row = store.ledger(gz.audit.key(REPO, fake))
    assert row["state"] == "refuted" and not row["alerted_at"]
    assert row["impact"] == "A made-up token ([redacted]) in a test fixture."  # never the key itself
    coverage = [{"check_name": "secret scan", "last_ok": "2026-11-01T00:00:00", "last_error": None}]
    html = gz.render.repo_page(REPO, "2026-11-01T00:00:00", store.ledger_rows([REPO], state=None), coverage)
    assert "Judged not a real secret (1)" in html and "tests/fixtures/keys.py" in html and _token(5) not in html

    gz.audit.record_refuted(store, REPO, [{**live, "reason": "looks fake"}], "2026-11-02")
    assert store.ledger(gz.audit.key(REPO, live))["state"] == "open"  # an open one stays open
    assert store.ledger(gz.audit.key(REPO, fake))["state"] == "resolved"  # not found this time

    gz.audit.record_refuted(store, REPO, [{**fake, "reason": "fixture"}], "2026-11-03")
    assert store.ledger(gz.audit.key(REPO, fake))["state"] == "refuted"  # found again: shown again
    new = gz.audit.record(store, REPO, [fake], ["tests/fixtures/keys.py"], tmp_path, "2026-11-04")
    assert [n["path"] for n in new] == ["tests/fixtures/keys.py"]  # confirmed later: opened and alerted
    assert store.ledger(gz.audit.key(REPO, fake))["state"] == "open"


def test_in_the_sample_a_missing_gitleaks_is_a_note_and_the_audit_still_runs(hub, monkeypatch, tmp_path):
    """The sample is fictional and offline: no alert for its scanner. A real
    repo gets a "secret scan not run" coverage problem instead."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "none"))
    r = h.run_local(h.wf(hub, "deep_audit"), hub_dir=hub, trigger="schedule")
    store = h.lib(hub).store.Store(hub / ".hubzoid" / "data")
    assert not any(c["check_name"] == "secret scan" and c["last_error"] for c in store.coverage([REPO]))
    assert r.value["audited"] and r.emails == []


# ------------------------------------------- a scan that cannot stay silent

@pytest.mark.parametrize("script", ["exit 1", "exit 126", "exit 0"])  # an error, a bad flag, a crash with no output
def test_a_failing_gitleaks_is_not_checked_never_clean(tmp_path, script):
    exe = tmp_path / "gitleaks"
    exe.write_text(f"#!/bin/sh\necho 'FTL something broke' >&2\n{script}\n")
    exe.chmod(0o755)
    with pytest.raises(gz.checks.ScanError, match="Gitleaks failed"):
        gz.checks.secret_scan(tmp_path, str(exe))


def _gitleaks_fingerprint(gitleaks: str, root, history: bool) -> str:
    import subprocess
    out = subprocess.run([gitleaks, "git" if history else "dir", str(root), "--report-format", "json",
                          "--report-path", "-", "--no-banner", "--exit-code", "0"], capture_output=True, text=True)
    return json.loads(out.stdout)[0]["Fingerprint"]


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
@pytest.mark.parametrize("history", [False, True])
def test_a_repos_own_gitleaksignore_cannot_hide_a_secret(tmp_path, history):
    import subprocess
    (tmp_path / "app").mkdir()
    (tmp_path / "app/config.py").write_text(f'GITHUB_TOKEN = "{_token(8)}"\n')
    if history:
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "x"],
                       check=True)
    gitleaks = shutil.which("gitleaks")
    (tmp_path / ".gitleaksignore").write_text(_gitleaks_fingerprint(gitleaks, tmp_path, history) + "\n")
    hits = gz.checks.secret_scan(tmp_path, gitleaks, history=history)
    assert [(x["path"], x["line"], x["rule"], x.get("hidden")) for x in hits] == [("app/config.py", 1, "github-pat", True)]
    [finding] = gz.audit.secret_findings(hits)
    assert "hidden from Gitleaks by the repo's .gitleaksignore" in finding["body"]


def test_gitleaksignore_entries_are_read_in_both_forms(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / ".gitleaksignore").write_text(
        "# reviewed\n" f"{tmp_path}/a.py:generic-api-key:3\n" "1a2fc331dc05e8eff9ee15267ac106ba72388618:b/c.py:github-pat:9\n"
        "not an entry\n" "/elsewhere/x.py:rule:1\n")
    assert gz.checks.gitleaks_ignored(tmp_path) == [
        {"path": "a.py", "line": 3, "rule": "generic-api-key", "commit": "", "hidden": True},
        {"path": "b/c.py", "line": 9, "rule": "github-pat", "commit": "1a2fc331dc05", "hidden": True}]


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_a_pull_request_that_adds_a_gitleaksignore_still_has_its_secret_flagged(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "no-pinned-builds"))
    fixed = tmp_path / "scan"  # the scan folder, known in advance, so the entry is the exact fingerprint

    class Folder:
        def __init__(self, **kwargs):
            fixed.mkdir(exist_ok=True)

        def __enter__(self):
            return str(fixed)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(gz.checks.tempfile, "TemporaryDirectory", Folder)
    entry = f"{os.path.realpath(fixed)}/source/app/sync.py:github-pat:1"
    token = _token(9)
    body = {"app/sync.py": f'TOKEN = "{token}"\n', ".gitleaksignore": entry + "\n"}
    files = [{"filename": n, "status": "added", "patch": "@@ -0,0 +1 @@\n+" + t.rstrip("\n")} for n, t in body.items()]
    analyzers = [{"name": "gitleaks", "run": ["gitleaks", *gz.checks.SAFE_RUNS["gitleaks"]]}]
    checks, notes = gz.checks.run_analyzers(files, body.get, analyzers, download=False)
    assert [(c["path"], c["line"], c["secret"]) for c in checks] == [("app/sync.py", 1, True)]
    assert any(n.startswith("gitleaks: this change edits .gitleaksignore") for n in notes)
    view = {"open": [], "risk": "low", "sha": "abc1234", "reviewed_files": 2, "total_files": 2, "notes": notes,
            "verdict": "looks_good"}
    assert "This change edits `.gitleaksignore`" in gz.review.summary(view, {}, False)


def test_a_reworded_secret_stays_marked_as_hidden_and_reasons_keep_their_paths(tmp_path):
    """Seen end to end: the first look found the same key and its wording
    replaced the "hidden by .gitleaksignore" note; and a path in a reason was
    taken for a key."""
    store = gz.store.Store(tmp_path)
    [hidden] = gz.audit.secret_findings([{"path": "config/deploy.py", "line": 2, "rule": "github-pat", "hidden": True}])
    gz.audit.record(store, REPO, [hidden], ["config/deploy.py"], tmp_path, "2026-11-01", alerted=False)
    reworded = {**hidden, "body": "A GitHub token is hardcoded in source."}
    gz.audit.record(store, REPO, [reworded], ["config/deploy.py"], tmp_path, "2026-11-01", alerted=False)
    [row] = store.ledger_rows([REPO], kind="audit")
    assert row["title"].startswith("A GitHub token is hardcoded") and "hidden from Gitleaks" in row["title"]
    long = {**hidden, "body": "A GitHub token is hardcoded in source and anyone can use it. " * 6}
    gz.audit.record(store, REPO, [long], ["config/deploy.py"], tmp_path, "2026-11-01", alerted=False)
    title = store.ledger_rows([REPO], kind="audit")[0]["title"]
    assert len(title) <= 300 and title.endswith("… It is hidden from Gitleaks by the repo's .gitleaksignore.")
    coverage = [{"check_name": "secret scan", "last_ok": "2026-11-01T00:00:00", "last_error": None}]
    html = gz.render.repo_page(REPO, "2026-11-01T00:00:00", store.ledger_rows([REPO], state=None), coverage)
    assert "1 hidden by the repo&#x27;s .gitleaksignore" in html or "1 hidden by the repo's .gitleaksignore" in html
    why = f"tests/fixtures/tokens.py says the values are made up; {_token(4)} was never issued."
    assert gz.audit.TOKENISH.sub("[redacted]", why) == \
        "tests/fixtures/tokens.py says the values are made up; [redacted] was never issued."
