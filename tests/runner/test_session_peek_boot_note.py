"""``sys_session_get_history`` must flag an empty transcript as boot lag.

Regression for the field failure where the polly orchestrator peeked a
freshly-dispatched native worker (claude_code / cursor), saw a history holding
only the terminal ``resource_event`` (the TUI was still booting; transcripts
mirror back with a forwarder lag), concluded the worker was dead, and
cancel-and-redispatched it. The peek payload now carries an explicit note when
the tail has no conversation content, so the parent cannot misread boot lag
as death.
"""

from __future__ import annotations

import json

import httpx
import pytest

from omnigent.runner.tool_dispatch import (
    _PEEK_EMPTY_HISTORY_NOTE,
    _peek_items_substantive,
    _session_get_history_via_rest,
)

_TARGET = "cafedeadbeef00000000000000000001"


def _server_client(items: list[dict[str, object]]) -> httpx.AsyncClient:
    """A mock Omnigent server serving the items tail + session snapshot."""

    def _handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/sessions/{_TARGET}/items":
            return httpx.Response(200, json={"data": items})
        if request.url.path == f"/v1/sessions/{_TARGET}":
            return httpx.Response(200, json={"title": "cursor:pr2-outbound-correlation"})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handle), base_url="http://server")


@pytest.mark.asyncio
async def test_empty_history_carries_boot_lag_note() -> None:
    """Only a resource_event in the tail -> the boot-lag note is attached."""
    client = _server_client([{"type": "resource_event", "resource_id": "terminal_cursor_main"}])
    result = json.loads(await _session_get_history_via_rest({"conversation_id": _TARGET}, client))
    assert result["note"] == _PEEK_EMPTY_HISTORY_NOTE


@pytest.mark.asyncio
async def test_substantive_history_carries_no_note() -> None:
    """A mirrored user message in the tail -> no note (normal peek shape)."""
    client = _server_client(
        [
            {"type": "resource_event", "resource_id": "terminal_cursor_main"},
            {"type": "message", "role": "user", "content": "IMPLEMENT task ..."},
        ]
    )
    result = json.loads(await _session_get_history_via_rest({"conversation_id": _TARGET}, client))
    assert "note" not in result


def test_substantive_predicate() -> None:
    assert _peek_items_substantive([{"type": "message"}]) is True
    assert _peek_items_substantive([{"type": "resource_event"}]) is False
    assert _peek_items_substantive([]) is False
