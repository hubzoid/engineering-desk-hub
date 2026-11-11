"""Plan step 3, task 5: a local folder as the code. Only what git tracks is
read, nothing needs a GitHub token, and the weekly secret scan reads the
folder's whole history."""
from __future__ import annotations

import functools
import random
import shutil
import string
import subprocess
from pathlib import Path

import pytest

from tests import engineering_desk_harness as h
from tests.engineering_desk_harness import template_lib

gz = template_lib()
REPO = "me/ios-app"


def _token(seed: int) -> str:
    return "ghp_" + "".join(random.Random(seed).choices(string.ascii_letters + string.digits, k=36))


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(folder),
                               "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
                               "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}).stdout


@pytest.fixture
def folder(tmp_path) -> Path:
    """A working copy: a key committed and later deleted, an ignored .env, and an uncommitted edit."""
    app = tmp_path / "ios-app"
    (app / "App/Auth").mkdir(parents=True)
    _git(app, "init", "-q", "-b", "main")
    (app / "App/Auth/Login.swift").write_text(f'let token = "{_token(7)}"\nfunc login() {{}}\n')
    (app / ".gitignore").write_text(".env\n")
    _git(app, "add", "-A")
    _git(app, "commit", "-q", "-m", "first")
    (app / "App/Auth/Login.swift").write_text("let token = ProcessInfo.processInfo.environment[\"TOKEN\"]\nfunc login() {}\n")
    (app / "App/AppDelegate.swift").write_text("import UIKit\n")
    _git(app, "add", "-A")
    _git(app, "commit", "-q", "-m", "read the token from the environment")
    (app / ".env").write_text(f"TOKEN={_token(8)}\n")                      # ignored: never read
    (app / "App/AppDelegate.swift").write_text("import UIKit\n// work in progress\n")  # not committed yet
    return app


def test_the_checkout_is_what_git_tracks_at_the_current_commit(folder, tmp_path):
    gh = gz.local.LocalRepos({REPO: folder})
    root, sha = gz.checkout.ensure(gh, REPO, tmp_path / "data")
    assert sha == _git(folder, "rev-parse", "HEAD").strip() and gh.default_branch(REPO) == "main"
    files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".engineering-desk" not in p.name}
    assert files == {".gitignore", "App/Auth/Login.swift", "App/AppDelegate.swift"}
    assert (root / "App/AppDelegate.swift").read_text() == "import UIKit\n"  # the commit, not the uncommitted edit
    assert gz.profiles.facts(root)["languages"][0].startswith("Swift")


def test_local_reads_answer_like_github(folder):
    gh = gz.local.LocalRepos({REPO: folder})
    first, second = _git(folder, "rev-list", "--reverse", "HEAD").split()
    changed = gh.compare_files(REPO, first, second)
    assert {(c["filename"], c["status"]) for c in changed} == {("App/Auth/Login.swift", "modified"),
                                                              ("App/AppDelegate.swift", "added")}
    assert gh.file(REPO, ".gitignore") == ".env\n" and gh.file(REPO, ".env") is None
    assert [c["message"] for c in gh.commits(REPO)] == ["read the token from the environment", "first"]
    assert gh.open_pulls(REPO) == [] and gh.login() == "local"


def test_a_folder_that_is_not_a_working_copy_says_so(tmp_path):
    (tmp_path / "plain").mkdir()
    gh = gz.local.LocalRepos({REPO: tmp_path / "plain", "me/gone": tmp_path / "gone"})
    with pytest.raises(gz.github.GitHubError, match="not a git working copy"):
        gh.branch_sha(REPO, "main")
    with pytest.raises(gz.github.GitHubError, match="does not exist"):
        gh.branch_sha("me/gone", "main")


@pytest.mark.parametrize("raw, words", [
    ({"version": 2, "source": "local", "repos": [{"name": REPO, "security": True}]}, "give the folder as path"),
    ({"version": 2, "source": "local", "repos": [{"name": REPO, "path": "~/x", "reviews": True}]}, "reviews need GitHub"),
    ({"version": 2, "source": "local", "repos": [{"name": REPO, "path": "~/x", "reports": True}]}, "reports need GitHub"),
    ({"version": 2, "source": "github", "repos": [{"name": REPO, "path": "~/x"}]}, "path is for source: local"),
])
def test_local_settings_say_what_is_wrong(raw, words):
    with pytest.raises(gz.settings.SettingsError, match=words):
        gz.settings.load(raw)


def test_local_settings_need_no_token(folder):
    s = gz.settings.load({"version": 2, "source": "local", "repos": [{"name": REPO, "path": str(folder), "security": True}]})
    gh = gz.runtime.make_github(s, None, Path("."), token="")
    assert gh.name == "local" and s.security_repos() == [REPO]


@pytest.fixture
def local_hub(tmp_path, monkeypatch, folder):
    h.isolate(monkeypatch)
    hub = h.make_hub(tmp_path / "hub")
    doc = h.settings_doc(hub)
    doc["engineering_desk"] = {**doc["engineering_desk"], "version": 2, "source": "local",
                               "repos": [{"name": REPO, "path": str(folder), "security": True}]}
    doc["engineering_desk"].pop("security_groups", None)
    doc["engineering_desk"].pop("digest_groups", None)
    import yaml
    (hub / "workflows" / "settings.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    scanners = h.flow(hub).gz.scanners
    monkeypatch.setattr(scanners, "find", functools.partial(scanners.find, download=False))  # tests stay offline
    return hub


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_the_weekly_scan_finds_a_key_that_only_the_history_still_has(local_hub, monkeypatch, tmp_path):
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "none"))

    def llm(prompt, system, response_model):
        if response_model.__name__ == "Verification":
            return {"verdicts": [{"index": 0, "verdict": "confirmed", "severity": "high", "reason": "A live token."}]}
        return {"findings": []}

    r = h.run_local(h.wf(local_hub, "deep_audit"), hub_dir=local_hub, trigger="schedule", llm=h.scripted(llm))
    store = h.lib(local_hub).store.Store(local_hub / ".hubzoid" / "data")
    [row] = [x for x in store.ledger_rows([REPO], kind="audit") if x["advisory"] == "secret"]
    assert row["path"] == "App/Auth/Login.swift" and row["line"] == 1
    assert "in commit" in row["title"] and "remove it from the history" in row["title"]
    assert r.value["audited"][0]["repo"] == REPO
