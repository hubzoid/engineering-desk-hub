"""Plan step 3, task 8: the Get started cards. Four cards on a new chat,
each saying whether its step is done and, if not, what to do."""
from __future__ import annotations

import importlib.util
import subprocess

import pytest
import yaml

from tests import engineering_desk_harness as h


def _checks():
    spec = importlib.util.spec_from_file_location("gz_doctor_cards", h.TEMPLATE / "doctor" / "checks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(hub, block):
    doc = h.settings_doc(hub)
    doc["engineering_desk"] = block
    (hub / "workflows" / "settings.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def _short(row):
    card = row["card"]
    assert len(card["line"]) <= 60 and len(card["detail"]) <= 80
    return row["status"], card["line"], card["detail"]


def test_the_cards_name_engineering_desks_own_checks():
    doc = yaml.safe_load((h.TEMPLATE / "get-started.yaml").read_text())
    manifest = yaml.safe_load((h.TEMPLATE / "hub.manifest.yaml").read_text())
    checks = {c["id"] for c in manifest["doctor"]}
    assert [c["title"] for c in doc["cards"]] == ["Model", "Code", "GitHub", "Automatic checks"]
    assert all(c["check"] == "model" or c["check"] in checks for c in doc["cards"])


def test_hubzoid_reads_the_cards():
    get_started = pytest.importorskip("hubzoid.hubs.get_started")  # Hubzoid 2.0.8 and later
    cards = get_started.load(h.TEMPLATE)
    assert [c.id for c in cards.cards] == ["model", "code", "github", "runs"]


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h.isolate(monkeypatch)
    monkeypatch.delenv("HUBZOID_SCHEDULES", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return h.make_hub(tmp_path / "hub")


def test_with_nothing_chosen_each_card_says_what_to_do(hub):
    checks = _checks()
    _settings(hub, {"version": 2, "source": "github", "repos": []})
    ctx = {"hub_dir": str(hub)}
    assert _short(checks.settings(ctx))[1:] == (
        "Not chosen yet", "Choose a folder or repos in workflows/settings.yaml, or ask your coding agent to")
    assert _short(checks.github(ctx)) == ("fail", "Not connected", "Add GITHUB_TOKEN to .env (SETUP.md, step 2)")
    assert _short(checks.schedules(ctx)) == ("fail", "Off", "Add HUBZOID_SCHEDULES=1 to .env and restart")


def test_a_local_folder_is_ready_and_github_can_wait(hub, tmp_path):
    folder = tmp_path / "ios-app"
    folder.mkdir()
    subprocess.run(["git", "-C", str(folder), "init", "-q", "-b", "main"], check=True)
    _settings(hub, {"version": 2, "source": "local", "repos": [{"name": "me/ios-app", "path": str(folder),
                                                               "security": True}]})
    (hub / ".env").write_text("HUBZOID_SCHEDULES=1\n")
    checks, ctx = _checks(), {"hub_dir": str(hub)}
    status, line, detail = _short(checks.settings(ctx))
    assert (status, detail) == ("ok", "Branch main") and line.startswith("…/") and line.endswith("/ios-app")
    assert checks._short_path(str(checks.Path.home() / "code" / "ios-app"), 60) == "~/code/ios-app"
    assert _short(checks.github(ctx)) == ("info", "Not connected", "Needed only for PR reviews")  # later, not a failure
    assert _short(checks.schedules(ctx)) == ("ok", "Security watch and audit on",
                                             "Dependencies daily, the audit and secret scan weekly")


def test_github_repos_and_schedules_on(hub):
    _settings(hub, {"version": 2, "source": "github",
                    "repos": [{"name": "acme/api", "reviews": True}, {"name": "acme/web"}]})
    (hub / ".env").write_text("HUBZOID_SCHEDULES=1\n")
    checks, ctx = _checks(), {"hub_dir": str(hub)}
    assert _short(checks.settings(ctx))[1:] == ("acme/api and 1 more", "On GitHub")
    assert _short(checks.schedules(ctx)) == ("ok", "Reviews and security watch on",
                                             "Reviews every 2 minutes, security daily")


def test_the_chat_suggests_the_first_steps():
    front = yaml.safe_load((h.TEMPLATE / "AGENTS.md").read_text().split("---")[1])
    assert front["suggestions"] == ["Check my repo", "What is waiting or stuck right now?", "See a sample review"]
    body = (h.TEMPLATE / "AGENTS.md").read_text()
    assert "Never ask for a token, key or password in chat" in body and "`check_repo`" in body
