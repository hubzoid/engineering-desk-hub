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


# ------------------------------------------------------------- GitHub retry

def test_a_read_survives_a_dropped_connection_and_a_gateway_error():
    calls = []

    def handler(request):
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow", request=request)
        if len(calls) == 2:
            return httpx.Response(502, text="<html>bad gateway</html>")
        return httpx.Response(200, json={"default_branch": "main"})

    assert _client(handler).default_branch("a/b") == "main"
    assert calls == ["GET", "GET", "GET"]


def test_a_read_that_keeps_failing_says_retry_next_sweep():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(gz.github.Transient, match="did not answer"):
        _client(handler).default_branch("a/b")


@pytest.mark.parametrize("failure", ["502", "dropped"])
def test_a_write_is_sent_once_whatever_happens(failure):
    """GitHub may have applied a write that failed on the way back: sending it
    again could post a review twice. The next sweep republishes instead."""
    writes = []

    def handler(request):
        writes.append(request.method)
        if failure == "dropped":
            raise httpx.RemoteProtocolError("connection closed", request=request)
        return httpx.Response(502)

    gh = _client(handler, dry_run=False)
    with pytest.raises(gz.github.Transient):
        gh.reply("a/b", 7, {"kind": "issue", "id": 1}, "hi")
    assert writes == ["POST"]


def test_a_rate_limited_write_is_still_retried():
    """A rate limit means GitHub refused the write without applying it."""
    calls = []

    def handler(request):
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(201, json={"id": 5})

    assert _client(handler, dry_run=False).reply("a/b", 7, {"kind": "issue", "id": 1}, "hi") == 5
    assert calls == ["POST", "POST"]


def test_graphql_queries_retry_like_reads():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(503, text="<html>unavailable</html>")
        return httpx.Response(200, json={"data": {"ok": True}})

    assert _client(handler)._graphql("query { ok }") == {"ok": True}
    assert calls == ["/graphql", "/graphql"]


def test_a_dropped_download_starts_again():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"print('hi')\n"
        info = tarfile.TarInfo("repo-abc/app.py")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=buf.getvalue())

    assert _client(handler).tarball("a/b", "abc1234") == buf.getvalue()
    assert len(calls) == 2


def test_errors_say_whether_the_next_sweep_should_retry():
    assert isinstance(gz.github._error("GET x", httpx.Response(504)), gz.github.Transient)
    assert not isinstance(gz.github._error("GET x", httpx.Response(422)), gz.github.Transient)
    assert issubclass(gz.github.Transient, gz.github.GitHubError)  # chat tools still relay it as a sentence


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
