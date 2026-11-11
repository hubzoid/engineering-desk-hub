"""Plan step 2, task 2: every language is read, vendored code never is, and a
repo with nothing readable is "not checked", never "no findings"."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests import engineering_desk_harness as h
from tests.engineering_desk_harness import template_lib

gz = template_lib()
REPO = "kestrel-oak/storefront"


def _ios_app(root: Path) -> Path:
    files = {
        "App/AppDelegate.swift": "import UIKit\n@main class AppDelegate: UIResponder {}\n",
        "App/Auth/LoginViewController.swift": "let apiKey = \"live-key\"\nfunc login() {}\n",
        "App/Legacy/Session.m": "#import \"Session.h\"\n@implementation Session\n@end\n",
        "App/Info.plist": "<plist><dict><key>API_KEY</key><string>x</string></dict></plist>\n",
        "App.xcodeproj/project.pbxproj": "// !$*UTF8*$!\n{ archiveVersion = 1; }\n",
        "App/Base.lproj/Main.storyboard": "<document/>\n",
        "Podfile": "platform :ios, '15.0'\npod 'Alamofire'\n",
        "Podfile.lock": "PODS:\n  - Alamofire (5.4.0)\n",
        "Pods/Alamofire/Source/Session.swift": "public class Session {}\n",
        "Carthage/Checkouts/Lib/Lib.swift": "class Lib {}\n",
        ".build/checkouts/swift-nio/Sources/NIO.swift": "struct NIO {}\n",
        "README.md": "# The app\n",
        "Tests/LoginTests.swift": "import XCTest\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    (root / "App/Assets/icon.png").parent.mkdir(parents=True)
    (root / "App/Assets/icon.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0")
    (root / "App/blob.data").write_bytes(b"abc\0def")
    return root


def test_every_text_file_is_listed_and_vendored_code_never_is(tmp_path):
    listed = {rel for rel, _ in gz.checkout.text_files(_ios_app(tmp_path))}
    assert {"App/AppDelegate.swift", "App/Legacy/Session.m", "App/Info.plist", "Podfile"} <= listed
    assert not any(rel.startswith(("Pods/", "Carthage/", ".build/")) for rel in listed)
    assert "App/Assets/icon.png" not in listed and "App/blob.data" not in listed  # binary


def test_the_audit_reads_swift_and_skips_what_is_not_code(tmp_path):
    files = gz.audit.select(_ios_app(tmp_path), None, [], [], 100)
    assert files[0] == "App/Auth/LoginViewController.swift"  # sign-in code first
    assert {"App/AppDelegate.swift", "App/Legacy/Session.m", "App/Info.plist"} <= set(files)
    for left_out in ("Podfile.lock", "README.md", "App.xcodeproj/project.pbxproj", "App/Base.lproj/Main.storyboard",
                     "Tests/LoginTests.swift"):
        assert left_out not in files, left_out


def test_a_profile_names_swift(tmp_path):
    facts = gz.profiles.facts(_ios_app(tmp_path))
    assert facts["languages"][0].startswith("Swift") and "Podfile" in facts["manifests"]
    assert "App/AppDelegate.swift" in facts["entry_points"]


@pytest.fixture
def hub(tmp_path, monkeypatch):
    h.isolate(monkeypatch)
    return h.make_hub(tmp_path)


def test_a_repo_with_nothing_to_read_is_not_checked(hub):
    h.write_settings(hub, {"security": {"exclude_paths": ["*"]}})
    r = h.run_local(h.wf(hub, "deep_audit"), hub_dir=hub, trigger="schedule")
    assert r.value["audited"] == []
    [u] = r.value["unfinished"]
    assert u["repo"] == REPO and u["error"].startswith("not checked: all ") and "excluded" in u["error"]
    store = h.lib(hub).store.Store(hub / ".hubzoid" / "data")
    assert store.audit(REPO)["last_full"] is None  # never recorded as a clean audit
    assert any(c["check_name"] == "audit" and c["last_error"].startswith("not checked") for c in store.coverage([REPO]))
