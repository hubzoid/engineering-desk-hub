"""Plan step 4, task 9: an opt-in secret check on each commit. Gitleaks on
the staged changes only, seconds, no model; a missing tool never blocks."""
from __future__ import annotations

import importlib.util
import os
import random
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests import engineering_desk_harness as h

HOOKS = h.TEMPLATE / "client" / "hooks"


def _token(seed: int) -> str:
    return "ghp_" + "".join(random.Random(seed).choices(string.ascii_letters + string.digits, k=36))


def _env(home: Path, **extra) -> dict:
    return {**os.environ, "HOME": str(home), "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
            "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com", **extra}


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "app"
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main"], check=True, env=_env(tmp_path))
    return path


def _install(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOKS / "install.py"), str(repo), *args], capture_output=True, text=True)


def test_the_check_is_opt_in_and_never_replaces_another_hook(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert not hook.exists()  # nothing until someone turns it on
    assert _install(repo).returncode == 0 and "Engineering Desk secret check" in hook.read_text()
    assert os.access(hook, os.X_OK) and str(HOOKS / "secret_check.py") in hook.read_text()
    assert _install(repo).returncode == 0  # again: still ours, rewritten
    assert _install(repo, "--remove").returncode == 0 and not hook.exists()
    hook.write_text("#!/bin/sh\nmake lint\n")
    out = _install(repo)
    assert out.returncode == 1 and "left as it is" in out.stdout and hook.read_text() == "#!/bin/sh\nmake lint\n"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks binary not installed")
def test_committing_a_key_is_blocked_in_seconds(repo, tmp_path):
    cache = tmp_path / "scanners"  # the pinned build, already fetched: here, the gitleaks on PATH
    (cache / "gitleaks-8.30.1").mkdir(parents=True)
    (cache / "gitleaks-8.30.1" / "gitleaks").symlink_to(shutil.which("gitleaks"))
    env = _env(tmp_path, ENGINEERING_DESK_SCANNERS=str(cache))
    assert _install(repo).returncode == 0

    (repo / "config.py").write_text(f'TOKEN = "{_token(3)}"\n')
    subprocess.run(["git", "-C", str(repo), "add", "config.py"], check=True, env=env)
    started = time.time()
    blocked = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "add config"], capture_output=True,
                             text=True, env=env)
    assert blocked.returncode != 0 and "stopped this commit" in blocked.stderr
    assert _token(3) not in blocked.stderr + blocked.stdout  # redacted
    assert time.time() - started < 15

    (repo / "config.py").write_text('import os\nTOKEN = os.environ["TOKEN"]\n')
    subprocess.run(["git", "-C", str(repo), "add", "config.py"], check=True, env=env)
    clean = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "read the token"], capture_output=True,
                           text=True, env=env)
    assert clean.returncode == 0, clean.stderr


def test_a_missing_gitleaks_never_blocks_a_commit(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("hook_check", HOOKS / "secret_check.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    real = check.scanners()

    class Offline:
        Tool = real.Tool

        @staticmethod
        def find(name, **kw):
            return real.Tool(name, None, None, "gitleaks not installed: could not download (offline)")

    monkeypatch.setattr(check, "scanners", lambda: Offline)
    assert check.main() == 0
    assert "secret check skipped" in capsys.readouterr().err
