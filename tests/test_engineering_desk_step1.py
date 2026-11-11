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


# ---------------------------------------------------- several-line suggestions

LINES = {("app/sync.py", n) for n in range(10, 20)}


def _finding(**kw):
    return {"path": "app/sync.py", "line": 14, "severity": "high", "confidence": "high", "category": "bug",
            "body": "The retry never stops.", **kw}


def test_a_range_inside_the_diff_is_kept():
    [f] = gz.review.gate([_finding(start_line=12)], LINES, "high", 8)
    assert f["start_line"] == 12 and gz.review.spans(f, LINES)


@pytest.mark.parametrize("start, why", [
    (5, "starts outside the diff"),
    (14, "not before line"),
    (-1, "not a line"),
    ("12", "not a number"),
])
def test_a_range_github_cannot_take_becomes_one_line(start, why):
    [f] = gz.review.gate([_finding(start_line=start)], LINES, "high", 8)
    assert f["start_line"] is None, why


def test_a_range_is_at_most_fifteen_lines():
    lines = {("app/sync.py", n) for n in range(1, 40)}
    assert gz.review.gate([_finding(line=30, start_line=16)], lines, "high", 8)[0]["start_line"] == 16
    assert gz.review.gate([_finding(line=30, start_line=15)], lines, "high", 8)[0]["start_line"] is None


def test_a_range_with_a_gap_in_the_diff_becomes_one_line():
    gap = LINES - {("app/sync.py", 13)}
    [f] = gz.review.gate([_finding(start_line=12)], gap, "high", 8)
    assert f["start_line"] is None


def test_several_lines_are_suggested_only_with_a_range():
    pr = {"repo": "o/r", "number": 7}
    f = {**_finding(), "id": "0123456789abcdef", "suggestion": "for attempt in range(3):\n    sync()"}
    assert "```suggestion\nfor attempt in range(3):\n    sync()\n```" in gz.review.inline_body({**f, "start_line": 13}, pr, True)
    assert "```suggestion" not in gz.review.inline_body(f, pr, True)  # several lines over one would add lines
    long = "x = 1\n" * 400  # 2,400 characters, over the 2,000 a range may suggest
    assert "```suggestion" not in gz.review.inline_body({**f, "start_line": 13, "suggestion": long}, pr, True)


def test_github_receives_the_range():
    sent = []

    def handler(request):
        if request.method == "POST":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": 9})
        return httpx.Response(200, json=[])

    gh = _client(handler, dry_run=False)
    gh.post_review("a/b", 7, "abc", [{"path": "app/sync.py", "line": 14, "start_line": 12, "body": "b"},
                                     {"path": "app/sync.py", "line": 18, "body": "c"}], "r")
    ranged, single = sent[0]["comments"]
    assert ranged["start_line"] == 12 and ranged["start_side"] == "RIGHT" and ranged["line"] == 14
    assert "start_line" not in single and "start_side" not in single


def test_the_range_moves_with_the_finding():
    assert gz.lifecycle.moved({"line": 14, "start_line": 12}, 20) == 18
    assert gz.lifecycle.moved({"line": 14}, 20) is None
    assert gz.lifecycle.moved({"line": 14, "start_line": 12}, None) is None


def test_the_range_is_stored_with_the_finding(tmp_path):
    store = gz.store.Store(tmp_path)
    store.save_finding({"id": "f1", "repo": "a/b", "number": 7, "path": "app/sync.py", "line": 14,
                        "start_line": 12, "state": "open"})
    assert store.finding("f1")["start_line"] == 12


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


def test_chat_tools_answer_outside_the_bridge(tmp_path, monkeypatch):
    """`hubzoid eval run` and MCP call the tools with no HUBZOID_HUB_DIR set.
    current_user() then needs the hub folder too, or every tool fails with
    "No hub here" (seen on a real eval run)."""
    from tests import engineering_desk_harness as h

    h.isolate(monkeypatch)
    hub = h.make_hub(tmp_path)
    monkeypatch.delenv("HUBZOID_HUB_DIR", raising=False)
    with h.as_person(h.PERSON, "web"):
        out = h.invoke(h.tools(hub)["engineering_desk_status"])
    assert json.loads(out)["source"] == "fictional sample repo", out
