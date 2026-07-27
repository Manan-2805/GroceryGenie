"""
Task 10 verification tests for chat.py.

Tests:
  1. _build_sse_payload: options_response → options_request with card_variant
  2. _build_sse_payload: card_variant forwarded (BUG-10 fix)
  3. _build_sse_payload: card_variant absent when not set
  4. _build_sse_payload: role_switch_request shape
  5. _build_sse_payload: toggle_theme shape
  6. _build_sse_payload: delta forwarded as-is
  7. _build_sse_payload: plain response
  8. No asyncio.sleep in sse_generator source
  9. No fake word-chunking in sse_generator source
  10. sse_generator: structured result emits single options_request SSE event
  11. sse_generator: delta stream emits multiple delta events
  12. GET /chat/history route exists on the router
  13. _build_sse_payload: options_response with no card_variant omits the key
"""

from __future__ import annotations

import inspect
import json

import pytest

from app.api.chat import _build_sse_payload, router, sse_generator

# ── _build_sse_payload tests ─────────────────────────────────────────────────


def test_options_response_becomes_options_request():
    result = {
        "type": "options_response",
        "text": "Found 2 products:",
        "options": [{"label": "Mango", "value": "uuid-1"}],
        "free_input_allowed": True,
        "card_variant": "search",
    }
    payload = _build_sse_payload(result)
    assert payload["type"] == "options_request"
    assert payload["text"] == "Found 2 products:"
    assert len(payload["options"]) == 1


def test_bug10_card_variant_forwarded():
    """BUG-10 regression: card_variant must be in the SSE payload for options_request."""
    result = {
        "type": "options_response",
        "text": "Fulfillment queue",
        "options": [],
        "card_variant": "fulfillment_queue",
    }
    payload = _build_sse_payload(result)
    assert payload.get("card_variant") == "fulfillment_queue", (
        "BUG-10 REGRESSION: card_variant='fulfillment_queue' was dropped in SSE payload"
    )


def test_inventory_card_variant_forwarded():
    result = {
        "type": "options_response",
        "text": "Your inventory",
        "options": [],
        "card_variant": "inventory",
    }
    payload = _build_sse_payload(result)
    assert payload.get("card_variant") == "inventory"


def test_card_variant_absent_when_not_set():
    """When card_variant is not in the result, it must NOT appear in the payload."""
    result = {
        "type": "options_response",
        "text": "Some options",
        "options": [{"label": "A", "value": "a"}],
    }
    payload = _build_sse_payload(result)
    assert "card_variant" not in payload


def test_role_switch_request_shape():
    result = {
        "type": "role_switch_request",
        "text": "Switch to seller?",
        "summary": "switch to seller",
        "options": [{"label": "Yes", "value": "switch_role:seller"}],
        "needed_role": "seller",
        "original_tool": "seller_create_product",
    }
    payload = _build_sse_payload(result)
    assert payload["type"] == "role_switch_request"
    assert payload["needed_role"] == "seller"
    assert payload["original_tool"] == "seller_create_product"
    assert payload["free_input_allowed"] is False


def test_toggle_theme_shape():
    result = {"type": "toggle_theme", "text": "Theme toggled."}
    payload = _build_sse_payload(result)
    assert payload["type"] == "toggle_theme"
    assert payload["text"] == "Theme toggled."


def test_delta_forwarded_as_is():
    result = {"type": "delta", "text": "Hello"}
    payload = _build_sse_payload(result)
    assert payload["type"] == "delta"
    assert payload["text"] == "Hello"


def test_plain_response_shape():
    result = {"type": "response", "text": "Done."}
    payload = _build_sse_payload(result)
    assert payload["type"] == "response"
    assert payload["text"] == "Done."


def test_plain_response_with_options():
    result = {"type": "response", "text": "Pick one:", "options": [{"label": "A"}]}
    payload = _build_sse_payload(result)
    assert payload["options"] == [{"label": "A"}]


# ── No fake streaming in sse_generator ────────────────────────────────────────


def test_no_asyncio_sleep_in_sse_generator():
    src = inspect.getsource(sse_generator)
    assert "asyncio.sleep" not in src, (
        "asyncio.sleep found in sse_generator — fake streaming not removed!"
    )


def test_no_word_chunking_in_sse_generator():
    src = inspect.getsource(sse_generator)
    assert "chunk_size" not in src, (
        "chunk_size found in sse_generator — fake word-chunking not removed!"
    )
    # Should not split by words anymore
    assert "words.split" not in src.replace("user_message", "").replace(
        "user message", ""
    ), "word splitting still in sse_generator"


# ── sse_generator integration (mock orchestrator) ────────────────────────────


@pytest.mark.asyncio
async def test_sse_generator_structured_result_single_event():
    """A structured options_response must produce exactly one options_request SSE event."""
    from unittest.mock import AsyncMock, MagicMock

    async def mock_stream(msg):
        yield {
            "type": "options_response",
            "text": "Found products:",
            "options": [{"label": "Mango"}],
            "card_variant": "search",
        }

    orch = MagicMock()
    orch.run_turn_stream = mock_stream
    orch.execute_approved_mutation = AsyncMock()

    events = []
    async for sse_line in sse_generator(orch, "find mango"):
        if sse_line.startswith("event: message"):
            data_line = sse_line.split("data: ", 1)[1].strip()
            events.append(json.loads(data_line))

    # Filter out the thinking status event
    content_events = [e for e in events if e["type"] != "status"]
    assert len(content_events) == 1
    assert content_events[0]["type"] == "options_request"
    assert content_events[0].get("card_variant") == "search"


@pytest.mark.asyncio
async def test_sse_generator_delta_stream_multiple_events():
    """A delta stream must produce multiple delta SSE events (one per token)."""
    from unittest.mock import MagicMock

    tokens = ["Jasmine ", "rice ", "is ", "fragrant."]

    async def mock_stream(msg):
        for token in tokens:
            yield {"type": "delta", "text": token}

    orch = MagicMock()
    orch.run_turn_stream = mock_stream

    delta_events = []
    async for sse_line in sse_generator(orch, "what is jasmine rice?"):
        if "data: " in sse_line:
            data_line = sse_line.split("data: ", 1)[1].strip()
            event = json.loads(data_line)
            if event["type"] == "delta":
                delta_events.append(event["text"])

    assert delta_events == tokens, f"Expected {tokens}, got {delta_events}"


@pytest.mark.asyncio
async def test_sse_generator_error_handling():
    """When run_turn_stream raises, generator emits error event without crashing."""
    from unittest.mock import MagicMock

    async def failing_stream(msg):
        raise RuntimeError("test error")
        yield  # make it an async generator

    orch = MagicMock()
    orch.run_turn_stream = failing_stream

    events = []
    async for sse_line in sse_generator(orch, "anything"):
        if "data: " in sse_line:
            data_line = sse_line.split("data: ", 1)[1].strip()
            events.append(json.loads(data_line))

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert (
        "error" in error_events[0].get("text", "").lower()
        or "occurred" in error_events[0].get("text", "").lower()
    )


# ── Route registration ────────────────────────────────────────────────────────


def test_history_route_registered():
    routes = [r.path for r in router.routes]
    assert "/chat/history" in routes, f"GET /chat/history not found in routes: {routes}"


def test_text_route_registered():
    routes = [r.path for r in router.routes]
    assert "/chat/text" in routes, f"POST /chat/text not found in routes: {routes}"
