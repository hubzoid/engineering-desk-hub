"""Gitleaks and Trivy, on every machine: one pinned version of each,
downloaded on first use from the tool's GitHub release and checked against a
pinned SHA-256 before it is ever run.

They live in a cache outside the hub's data folder (backups stay small), one
folder per version, so a new pin downloads beside the old one. A machine that
cannot download (offline, or a platform without a pinned build) uses the tool
on PATH if there is one, and says so. The sample never downloads: it is
offline by design.

    $ENGINEERING_DESK_SCANNERS     the cache folder, if set
    $XDG_CACHE_HOME or ~/.cache    otherwise, under hubzoid/engineering-desk/scanners
"""
from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path

import httpx

# Bump a version and its checksums together, from the release's checksums file.
PINS = {
    "gitleaks": {
        "version": "8.30.1",
        "url": "https://github.com/gitleaks/gitleaks/releases/download/v{version}/{asset}",
        "assets": {
            ("darwin", "arm64"): ("gitleaks_8.30.1_darwin_arm64.tar.gz",
                                  "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"),
            ("darwin", "x64"): ("gitleaks_8.30.1_darwin_x64.tar.gz",
                                "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709"),
            ("linux", "arm64"): ("gitleaks_8.30.1_linux_arm64.tar.gz",
                                 "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080"),
            ("linux", "x64"): ("gitleaks_8.30.1_linux_x64.tar.gz",
                               "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"),
        },
    },
    "trivy": {
        "version": "0.76.1",
        "url": "https://github.com/aquasecurity/trivy/releases/download/v{version}/{asset}",
        "assets": {
            ("darwin", "arm64"): ("trivy_0.76.1_macOS-ARM64.tar.gz",
                                  "11a9b6cd2752011b54f01ea4bd0dbfa9f0c41dc6538d5a3f9d23955f471bf4e5"),
            ("darwin", "x64"): ("trivy_0.76.1_macOS-64bit.tar.gz",
                                "7aa762eacd582052d053b62dcf972a1ab058abe39a57ccae234ed8894945b6b7"),
            ("linux", "arm64"): ("trivy_0.76.1_Linux-ARM64.tar.gz",
                                 "e174dff2a6dba5e3ae41f8d0537a6324405bd08132497340304c6b20e0f16a1f"),
            ("linux", "x64"): ("trivy_0.76.1_Linux-64bit.tar.gz",
                               "c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0"),
        },
    },
}
MAX_DOWNLOAD = 200_000_000


@dataclass
class Tool:
    name: str
    path: str | None        # the executable to run, or None when there is none
    version: str | None     # the pinned version, or None for a tool found on PATH
    note: str               # one line for results and doctor

    @property
    def ready(self) -> bool:
        return self.path is not None


def cache_dir() -> Path:
    if os.environ.get("ENGINEERING_DESK_SCANNERS"):
        return Path(os.environ["ENGINEERING_DESK_SCANNERS"])
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "hubzoid" / "engineering-desk" / "scanners"


def this_platform() -> tuple[str, str] | None:
    system = {"darwin": "darwin", "linux": "linux"}.get(platform.system().lower())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    return (system, machine) if system and machine else None


def pinned_path(name: str) -> Path:
    return cache_dir() / f"{name}-{PINS[name]['version']}" / name


def find(name: str, *, download: bool = True, transport: httpx.BaseTransport | None = None) -> Tool:
    """The tool to run: the pinned build (downloaded now if needed and
    allowed), else the one on PATH, else none, with a note saying which."""
    pin = PINS[name]
    target = pinned_path(name)
    if target.is_file() and os.access(target, os.X_OK):
        return Tool(name, str(target), pin["version"], f"{name} {pin['version']} (pinned)")
    problem = "downloads are off in the sample" if not download else None
    if download:
        try:
            _install(name, target, transport)
            return Tool(name, str(target), pin["version"], f"{name} {pin['version']} (pinned, just downloaded)")
        except Exception as exc:  # noqa: BLE001 - reported in the note, never silent
            problem = f"could not download {name} {pin['version']}: {exc}"
    on_path = shutil.which(name)
    if on_path:
        return Tool(name, on_path, None, f"{name} from PATH ({on_path}), not the pinned {pin['version']}"
                    + (f"; {problem}" if download else ""))
    return Tool(name, None, None, f"{name} not installed: {problem}")


def status(name: str) -> Tool:
    """What `find` would use, without downloading: for doctor."""
    tool = find(name, download=False)
    if tool.ready:
        return tool
    if this_platform() not in PINS[name]["assets"]:
        return Tool(name, None, None, f"{name}: no pinned build for this platform; install it on PATH")
    return Tool(name, None, None, f"{name} {PINS[name]['version']} is downloaded on first use")


def _install(name: str, target: Path, transport: httpx.BaseTransport | None) -> None:
    pin = PINS[name]
    plat = this_platform()
    if plat not in pin["assets"]:
        raise RuntimeError(f"no pinned build for {plat or platform.platform()}")
    asset, digest = pin["assets"][plat]
    url = pin["url"].format(version=pin["version"], asset=asset)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target.parent / ".lock", "a") as lock:
        _lock(lock)
        if target.is_file():  # another run installed it while we waited
            return
        data = bytearray()
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=120), transport=transport,
                          headers={"User-Agent": "engineering-desk-hub"}) as client:
            with client.stream("GET", url) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"{url} answered {r.status_code}")
                for chunk in r.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_DOWNLOAD:
                        raise RuntimeError(f"{asset} is larger than expected")
        got = hashlib.sha256(data).hexdigest()
        if got != digest:
            raise RuntimeError(f"{asset} checksum mismatch (expected {digest[:12]}…, got {got[:12]}…); not installed")
        with tarfile.open(fileobj=io.BytesIO(bytes(data)), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and Path(m.name).name == name), None)
            if member is None:
                raise RuntimeError(f"{asset} has no {name} executable")
            binary = tar.extractfile(member).read()
        tmp = target.with_name(f".{name}.partial")
        tmp.write_bytes(binary)
        tmp.chmod(0o755)
        tmp.replace(target)


def _lock(file) -> None:
    if os.name == "nt":  # no pinned Windows builds: nothing to install there
        return
    import fcntl
    fcntl.flock(file.fileno(), fcntl.LOCK_EX)
