"""Plan step 1, the known bugs: GitHub reads retried and writes never resent,
suggestions over several lines, and no private Hubzoid imports. Plain code,
no hub, no network, no model."""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest

from tests.engineering_desk_harness import template_lib

gz = template_lib()
HUB = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(gz.github.time, "sleep", lambda s: None)


def _client(handler, **kw):
    return gz.github.GitHub("t", transport=httpx.MockTransport(handler), **kw)


# ----------------------------------------------------- no private Hubzoid parts

def test_the_desk_imports_no_private_part_of_hubzoid():
    """Hubzoid can rename a private module in any release. Tests may still
    check Hubzoid's real email limits through them; the Desk's code may not."""
    for path in [*HUB.joinpath("workflows").rglob("*.py"), *HUB.joinpath("restricted").glob("*.py"),
                 *HUB.joinpath("doctor").glob("*.py")]:
        text = path.read_text()
        assert "from hubzoid import _" not in text and "hubzoid._" not in text, path


def test_chat_tools_name_their_hub_folder():
    """Outside a running hub (evals, MCP) Hubzoid cannot tell which hub a tool
    belongs to, so data_dir() needs the folder."""
    for path in HUB.joinpath("restricted").glob("*.py"):
        assert "data_dir()" not in path.read_text(), path
