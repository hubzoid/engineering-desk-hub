"""Plan step 2, task 3: Gitleaks and Trivy for everyone. Pinned builds are
checked before they run, Trivy lists every dependency file type, CocoaPods
advisories come through Trivy, and what could not be checked is said.
No network: downloads and Trivy itself are stand-ins."""
from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
from pathlib import Path

import httpx
import pytest

from tests import engineering_desk_harness as h
from tests.engineering_desk_harness import template_lib

gz = template_lib()


# --------------------------------------------------------------- pinned builds

def _archive(name: str, body: bytes = b"#!/bin/sh\necho ok\n") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for member, data in (("README.md", b"docs"), (name, body)):
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A fake 'gitleaks' release for this platform, and an empty cache."""
    monkeypatch.setenv("ENGINEERING_DESK_SCANNERS", str(tmp_path / "cache"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    data = _archive("gitleaks")
    monkeypatch.setattr(gz.scanners, "this_platform", lambda: ("linux", "x64"))
    monkeypatch.setitem(gz.scanners.PINS, "gitleaks", {
        "version": "9.9.9", "url": "https://example.invalid/{asset}",
        "assets": {("linux", "x64"): ("gitleaks.tar.gz", hashlib.sha256(data).hexdigest())}})
    return data


def test_a_pinned_build_is_downloaded_checked_and_kept(pinned):
    calls = []

    def serve(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=pinned)

    tool = gz.scanners.find("gitleaks", transport=httpx.MockTransport(serve))
    assert tool.ready and tool.version == "9.9.9" and "just downloaded" in tool.note
    assert Path(tool.path).stat().st_mode & stat.S_IXUSR
    assert gz.scanners.find("gitleaks").note == "gitleaks 9.9.9 (pinned)" and len(calls) == 1  # kept, not fetched again
    assert str(gz.scanners.cache_dir()) in tool.path


def test_a_build_with_the_wrong_checksum_is_never_installed(pinned):
    tampered = _archive("gitleaks", b"#!/bin/sh\necho evil\n")
    tool = gz.scanners.find("gitleaks", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=tampered)))
    assert not tool.ready and "checksum mismatch" in tool.note
    assert not gz.scanners.pinned_path("gitleaks").exists()


def test_the_sample_never_downloads(pinned):
    def refuse(request):
        raise AssertionError("no download in the sample")

    tool = gz.scanners.find("gitleaks", download=False, transport=httpx.MockTransport(refuse))
    assert not tool.ready and "downloads are off in the sample" in tool.note


def test_doctor_status_never_downloads(pinned):
    assert gz.scanners.status("gitleaks").note == "gitleaks 9.9.9 is downloaded on first use"


def test_the_cache_is_outside_the_hub(monkeypatch, tmp_path):
    monkeypatch.delenv("ENGINEERING_DESK_SCANNERS", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert gz.scanners.cache_dir() == tmp_path / "xdg" / "hubzoid" / "engineering-desk" / "scanners"


def test_every_supported_platform_has_a_checksum():
    for name, pin in gz.scanners.PINS.items():
        assert set(pin["assets"]) == {("darwin", "arm64"), ("darwin", "x64"), ("linux", "arm64"), ("linux", "x64")}
        assert all(len(digest) == 64 and pin["version"] in asset for asset, digest in pin["assets"].values()), name


# ----------------------------------------------------------- Trivy's packages

SBOM = {
    "components": [
        {"bom-ref": "a1", "type": "application", "name": "ios/Podfile.lock"},
        {"bom-ref": "a2", "type": "application", "name": "ios/Package.resolved"},
        {"bom-ref": "a3", "type": "application", "name": "api/requirements.txt"},
        {"bom-ref": "a4", "type": "application", "name": "tests/fixtures/requirements.txt"},
        {"bom-ref": "a5", "type": "application", "name": "web/package-lock.json"},
        {"bom-ref": "a6", "type": "application", "name": "android/pom.xml"},
    ],
    "dependencies": [
        {"ref": "a1", "dependsOn": ["pkg:cocoapods/SwiftNIO@2.40.0", "pkg:cocoapods/Alamofire@5.4.0"]},
        {"ref": "a2", "dependsOn": ["pkg:swift/github.com/apple/swift-nio@2.40.0"]},
        {"ref": "a3", "dependsOn": ["pkg:pypi/Django_REST@3.0.0"]},
        {"ref": "a4", "dependsOn": ["pkg:pypi/requests@1.0.0"]},
        {"ref": "a5", "dependsOn": ["pkg:npm/%40babel/core@7.0.0", "pkg:generic/thing@1.0"]},
        {"ref": "a6", "dependsOn": ["pkg:maven/org.apache.logging.log4j/log4j-core@2.14.1"]},
    ],
}
VULNS = {"Results": [
    {"Target": "ios/Podfile.lock", "Type": "cocoapods", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-2026-28970", "VendorIDs": ["GHSA-rj37-6j9x-74q6"], "PkgName": "SwiftNIO",
         "InstalledVersion": "2.40.0", "FixedVersion": "2.100.0, 2.41.0", "Severity": "HIGH",
         "Title": "SwiftNIO NIOHTTP1: HTTPDecoder accepts unbounded heads",
         "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2026-28970", "CVSS": {"ghsa": {"V3Score": 7.5}}}]},
    {"Target": "api/requirements.txt", "Type": "pip", "Vulnerabilities": [
        {"VulnerabilityID": "CVE-1", "PkgName": "django-rest", "InstalledVersion": "3.0.0", "Severity": "HIGH"}]},
]}


@pytest.fixture
def fake_trivy(tmp_path):
    """A 'trivy' that prints the package list or the vulnerability report."""
    (tmp_path / "sbom.json").write_text(json.dumps(SBOM))
    (tmp_path / "vulns.json").write_text(json.dumps(VULNS))
    exe = tmp_path / "trivy"
    exe.write_text(f"""#!/bin/sh
echo "$@" >> {tmp_path}/args
case "$*" in *cyclonedx*) cat {tmp_path}/sbom.json ;; *) cat {tmp_path}/vulns.json ;; esac
""")
    exe.chmod(0o755)
    return exe


def test_trivy_lists_every_dependency_file_type(fake_trivy, tmp_path):
    skipped: list[str] = []
    deps = gz.security.trivy_dependencies(tmp_path, str(fake_trivy), tmp_path / "db", skipped=skipped)
    got = {(d["ecosystem"], d["name"], d["version"], d["file"]) for d in deps}
    assert got == {
        ("CocoaPods", "SwiftNIO", "2.40.0", "ios/Podfile.lock"),
        ("CocoaPods", "Alamofire", "5.4.0", "ios/Podfile.lock"),
        ("SwiftURL", "github.com/apple/swift-nio", "2.40.0", "ios/Package.resolved"),
        ("PyPI", "django-rest", "3.0.0", "api/requirements.txt"),
        ("npm", "@babel/core", "7.0.0", "web/package-lock.json"),
        ("Maven", "org.apache.logging.log4j:log4j-core", "2.14.1", "android/pom.xml"),
    }
    assert skipped == ["tests/fixtures/requirements.txt"]
    args = (tmp_path / "args").read_text()
    assert "--offline-scan" in args and "--skip-dirs **/Pods" in args and "--scanners" not in args  # no database


def test_cocoapods_advisories_come_through_trivy(fake_trivy, tmp_path):
    deps = gz.security.trivy_dependencies(tmp_path, str(fake_trivy), tmp_path / "db")
    [a] = gz.security.trivy_cocoapods(tmp_path, str(fake_trivy), tmp_path / "db", deps)
    assert a["key"] == "GHSA-rj37-6j9x-74q6" and a["cves"] == ["CVE-2026-28970"]
    assert a["severity"] == "high" and a["score"] == 7.5 and a["fixed"] == "2.41.0"
    assert a["dep"]["file"] == "ios/Podfile.lock"


def test_a_repo_without_cocoapods_never_needs_trivys_database(fake_trivy, tmp_path):
    assert gz.security.trivy_cocoapods(tmp_path, str(fake_trivy), tmp_path / "db",
                                       [{"ecosystem": "PyPI", "name": "x", "version": "1", "file": "r.txt"}]) == []
    assert not (tmp_path / "args").exists()


def test_osv_is_never_asked_about_cocoapods():
    sent = []

    def osv(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{} for _ in sent[-1]["queries"]]})

    feeds = gz.security.Feeds(transport=httpx.MockTransport(osv))
    feeds.advisories([{"ecosystem": "CocoaPods", "name": "SwiftNIO", "version": "2.40.0", "file": "Podfile.lock"},
                      {"ecosystem": "SwiftURL", "name": "github.com/apple/swift-nio", "version": "2.40.0", "file": "x"}])
    assert [q["package"]["ecosystem"] for q in sent[0]["queries"]] == ["SwiftURL"]


def test_without_trivy_other_dependency_files_are_not_checked(tmp_path):
    (tmp_path / "ios").mkdir()
    (tmp_path / "ios/Podfile.lock").write_text("PODS:\n  - SwiftNIO (2.40.0)\n")
    (tmp_path / "Pods/Lib").mkdir(parents=True)
    (tmp_path / "Pods/Lib/Package.resolved").write_text("{}")  # vendored: never reported
    (tmp_path / "requirements.txt").write_text("requests==2.19.0\n")
    manifests, _ = gz.security.manifest_files(tmp_path)
    deps, problems, how = gz.security.list_dependencies(tmp_path, manifests, None, None, note="not installed")
    assert [d["name"] for d in deps] == ["requests"] and how == "the Desk's own readers"
    assert problems == ["not checked without Trivy (not installed): ios/Podfile.lock"]


def test_a_failing_trivy_falls_back_and_says_why(tmp_path):
    broken = tmp_path / "trivy"
    broken.write_text("#!/bin/sh\necho 'FATAL cannot read' >&2\nexit 1\n")
    broken.chmod(0o755)
    (tmp_path / "Podfile.lock").write_text("PODS:\n")
    deps, problems, how = gz.security.list_dependencies(tmp_path, {}, str(broken), tmp_path / "db")
    assert how == "the Desk's own readers"
    assert problems == ["not checked without Trivy (Trivy failed: FATAL cannot read): Podfile.lock"]


# ------------------------------------------------- a scanner that did not run

def test_a_secret_scanner_that_did_not_run_is_said_at_the_top():
    view = {"open": [], "risk": "low", "sha": "abc1234", "reviewed_files": 1, "total_files": 1, "verdict": "looks_good",
            "summary": "Adds a thing.", "notes": ["gitleaks: not installed, skipped (gitleaks not installed: offline)"]}
    text = gz.review.summary(view, {"repo": "o/r", "number": 1}, True)
    lines = text.splitlines()
    warning = next(i for i, l in enumerate(lines) if "The secret scanner did not run" in l)
    assert warning < next(i for i, l in enumerate(lines) if l.startswith("## 📝 Summary"))
    assert "Engineering Desk's own patterns only" in lines[warning]


# Real Trivy 0.76.1 output (trivy fs --offline-scan --format cyclonedx), saved
# from an npm, a Poetry and a Cargo project; not written by hand.
REAL = h.TEMPLATE / "tests" / "fixtures" / "trivy"


@pytest.mark.parametrize("project, packages", [("npm", 50), ("poetry", 5), ("cargo", 57)])
def test_indirect_packages_are_listed_too(project, packages, monkeypatch, tmp_path):
    """npm install --package-lock-only for express 4.17.1 locks 50 packages;
    requests 2.19.0 with Poetry locks 5; ripgrep 14.1.0's Cargo.lock has 57.
    A file names only its direct packages: the rest are found through them."""
    sbom = json.loads((REAL / f"{project}.cdx.json").read_text())
    monkeypatch.setattr(gz.security, "_trivy", lambda *a, **k: sbom)
    deps = gz.security.trivy_dependencies(tmp_path, "trivy", tmp_path / "db")
    assert len(deps) == packages
    assert len({(d["name"], d["version"]) for d in deps}) == packages
    assert all(d["file"] in ("package-lock.json", "poetry.lock", "Cargo.lock") for d in deps)


def test_a_vulnerable_indirect_package_is_reported(monkeypatch, tmp_path):
    """qs 6.7.0 comes in through express, and has CVE-2022-24999 (OSV.dev's
    records, saved as they were served)."""
    sbom = json.loads((REAL / "npm.cdx.json").read_text())
    monkeypatch.setattr(gz.security, "_trivy", lambda *a, **k: sbom)
    deps = gz.security.trivy_dependencies(tmp_path, "trivy", tmp_path / "db")
    assert {"ecosystem": "npm", "name": "qs", "version": "6.7.0", "file": "package-lock.json"} in deps
    found = gz.security.Feeds(sample_dir=REAL / "osv").advisories(deps)
    qs = [a for a in found if a["dep"]["name"] == "qs"]
    assert qs and any("CVE-2022-24999" in a["cves"] for a in qs)


def test_a_package_no_file_reaches_is_kept_not_dropped(monkeypatch, tmp_path):
    sbom = {"components": [
        {"bom-ref": "f1", "type": "application", "name": "package-lock.json",
         "properties": [{"name": "aquasecurity:trivy:Type", "value": "npm"}]},
        {"bom-ref": "pkg:npm/a@1.0.0", "type": "library", "purl": "pkg:npm/a@1.0.0"},
        {"bom-ref": "pkg:npm/loose@2.0.0", "type": "library", "purl": "pkg:npm/loose@2.0.0",
         "properties": [{"name": "aquasecurity:trivy:PkgType", "value": "npm"}]}],
        "dependencies": [{"ref": "f1", "dependsOn": ["pkg:npm/a@1.0.0"]}, {"ref": "pkg:npm/a@1.0.0", "dependsOn": []}]}
    monkeypatch.setattr(gz.security, "_trivy", lambda *a, **k: sbom)
    deps = gz.security.trivy_dependencies(tmp_path, "trivy", tmp_path / "db")
    assert [(d["name"], d["file"]) for d in deps] == [("a", "package-lock.json"), ("loose", "package-lock.json")]
