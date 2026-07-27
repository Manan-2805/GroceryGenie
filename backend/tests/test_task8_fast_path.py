"""
Task 8 verification tests for fast_path.py.

Tests:
  1. Prefix dispatch — add_, remove_, order_detail_, fulfillment_status_, etc.
  2. Fuzzy text matching — "the mango one" hits Mango option
  3. Voice index matching — "option 1", "the first one", "2"
  4. Fuzzy below threshold → returns None (falls through to LLM)
  5. Fuzzy cosine/sequence threshold config constants are not hardcoded in fast_path
  6. No last_options → no fuzzy match → None
  7. cart / orders / theme keyword shortcuts
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.fast_path import (
    _best_option_match,
    _cosine_similarity,
    _extract_option_index,
    _sequence_ratio,
    handle,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_orchestrator(last_options: list[dict] | None = None):
    """Build a minimal mock orchestrator with the fields fast_path.handle() needs."""
    orch = MagicMock()
    orch.session_id = uuid.uuid4()
    orch.db = MagicMock()

    async def _execute_tool(tool_name: str, params: dict) -> Any:
        return {"success": True, "message": f"{tool_name} called"}

    def _format_response_sync(msg: str, result: Any) -> dict:
        if isinstance(result, dict) and "message" in result:
            return {"type": "response", "text": result["message"], "options": None}
        return {"type": "response", "text": "done", "options": None}

    orch._execute_tool = AsyncMock(side_effect=_execute_tool)
    orch._format_response_sync = _format_response_sync
    orch._start_address_update_flow = AsyncMock(
        return_value={"type": "response", "text": "update flow", "options": None}
    )
    orch._start_seller_edit_flow = AsyncMock(
        return_value={"type": "response", "text": "edit flow", "options": None}
    )
    orch._start_address_add_flow = AsyncMock(
        return_value={"type": "response", "text": "add address flow", "options": None}
    )

    # Patch get_last_options for this orchestrator's session
    options = last_options or []
    return orch, options


async def _handle_with_options(msg: str, last_options: list[dict]) -> dict | None:
    orch, options = _make_orchestrator(last_options)
    with patch(
        "app.services.agent.fast_path.get_last_options",
        new=AsyncMock(return_value=options),
    ):
        return await handle(msg, orch)


# ── Prefix dispatch tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prefix_add():
    pid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"add_{pid}", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with(
        "add_to_cart", {"product_id": pid, "quantity": 1}
    )


@pytest.mark.asyncio
async def test_prefix_remove():
    pid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"remove_{pid}", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with("remove_from_cart", {"product_id": pid})


@pytest.mark.asyncio
async def test_prefix_order_detail():
    oid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"order_detail_{oid}", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with("get_order_detail", {"order_id": oid})


@pytest.mark.asyncio
async def test_prefix_fulfillment_status():
    oid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"fulfillment_status_{oid}_packed", orch)
    assert result is not None
    call_args = orch._execute_tool.call_args
    assert call_args[0][0] == "update_order_status"
    assert call_args[0][1]["order_ids"] == [oid]
    assert call_args[0][1]["new_status"] == "packed"


@pytest.mark.asyncio
async def test_prefix_delete_address():
    aid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"delete_address_{aid}", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with(
        "manage_addresses", {"action": "delete", "address_id": aid}
    )


@pytest.mark.asyncio
async def test_prefix_update_address():
    aid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"update_address_{aid}", orch)
    assert result is not None
    orch._start_address_update_flow.assert_called_once_with(aid)


@pytest.mark.asyncio
async def test_prefix_seller_deactivate():
    pid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"seller_deactivate_{pid}", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with(
        "seller_delete_product", {"product_id": pid}
    )


@pytest.mark.asyncio
async def test_prefix_seller_edit():
    pid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"seller_edit_{pid}", orch)
    assert result is not None
    orch._start_seller_edit_flow.assert_called_once_with(pid)


@pytest.mark.asyncio
async def test_prefix_delete_fact():
    fid = str(uuid.uuid4())
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle(f"delete_fact_{fid}", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with(
        "manage_facts", {"action": "delete", "fact_id": fid}
    )


@pytest.mark.asyncio
async def test_keyword_view_cart():
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle("show cart", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with("view_cart", {})


@pytest.mark.asyncio
async def test_keyword_checkout():
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle("checkout", orch)
    assert result is not None
    orch._execute_tool.assert_called_once_with("place_order", {})


@pytest.mark.asyncio
async def test_keyword_theme_toggle():
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle("dark mode", orch)
    assert result is not None
    assert result["type"] == "toggle_theme"


@pytest.mark.asyncio
async def test_no_match_returns_none():
    """A normal user message with no prefix and no last_options → None (falls to LLM)."""
    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options", new=AsyncMock(return_value=[])
    ):
        result = await handle("find me some milk under $2", orch)
    assert result is None


# ── Fuzzy matching unit tests (pure) ─────────────────────────────────────────


def test_cosine_similarity_identical():
    assert _cosine_similarity("fresh mango", "fresh mango") == pytest.approx(1.0)


def test_cosine_similarity_partial():
    score = _cosine_similarity("mango", "fresh mango")
    assert 0.0 < score < 1.0


def test_cosine_similarity_no_overlap():
    assert _cosine_similarity("apple", "banana yogurt") == pytest.approx(0.0)


def test_sequence_ratio_identical():
    assert _sequence_ratio("organic milk", "organic milk") == pytest.approx(1.0)


def test_sequence_ratio_typo():
    # "oragnic milk" vs "organic milk" — close but not identical
    score = _sequence_ratio("oragnic milk", "organic milk")
    assert score > 0.8


def test_best_option_match_above_threshold():
    """'the mango one' should match 'E2E Premium Mango' above threshold."""
    options = [
        {
            "label": "Organic Milk",
            "value": "uuid-1",
            "actions": [{"label": "Add to Cart", "value": "add_uuid-1"}],
        },
        {
            "label": "E2E Premium Mango",
            "value": "uuid-2",
            "actions": [{"label": "Add to Cart", "value": "add_uuid-2"}],
        },
        {
            "label": "Fresh Apples",
            "value": "uuid-3",
            "actions": [{"label": "Add to Cart", "value": "add_uuid-3"}],
        },
    ]
    matched = _best_option_match("the mango one", options)
    assert matched is not None
    assert matched["label"] == "E2E Premium Mango"


def test_best_option_match_below_threshold():
    """Completely unrelated message should not match any option."""
    options = [
        {"label": "Organic Milk", "value": "uuid-1"},
        {"label": "Fresh Apples", "value": "uuid-2"},
    ]
    matched = _best_option_match("what is the weather today", options)
    assert matched is None


def test_best_option_match_empty_options():
    assert _best_option_match("mango", []) is None


# ── Index extraction tests ────────────────────────────────────────────────────


def test_extract_index_numeric():
    assert _extract_option_index("option 1") == 1
    assert _extract_option_index("number 3") == 3
    assert _extract_option_index("the 2") == 2


def test_extract_index_ordinal():
    assert _extract_option_index("the first one") == 1
    assert _extract_option_index("option second") == 2
    assert (
        _extract_option_index("third") is None
    )  # bare ordinal without "option/number/the"


def test_extract_index_bare_digit():
    assert _extract_option_index("2") == 2
    assert _extract_option_index("7") == 7
    assert _extract_option_index("0") is None  # 0 is out of range
    assert _extract_option_index("11") is None  # > 10


def test_extract_index_none_for_plain_text():
    assert _extract_option_index("add milk to cart") is None
    assert _extract_option_index("show my orders") is None


# ── Fuzzy integration test ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuzzy_match_dispatches_option_action():
    """
    Task 8 demo test:
    After showing 3 product options, user types 'the mango one'
    → fast path matches 'E2E Premium Mango' and dispatches add_<uuid>.
    """
    mango_id = str(uuid.uuid4())
    milk_id = str(uuid.uuid4())
    apple_id = str(uuid.uuid4())

    last_options = [
        {
            "label": "Organic Milk",
            "value": milk_id,
            "actions": [{"label": "Add to Cart", "value": f"add_{milk_id}"}],
        },
        {
            "label": "E2E Premium Mango",
            "value": mango_id,
            "actions": [{"label": "Add to Cart", "value": f"add_{mango_id}"}],
        },
        {
            "label": "Fresh Apples",
            "value": apple_id,
            "actions": [{"label": "Add to Cart", "value": f"add_{apple_id}"}],
        },
    ]

    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options",
        new=AsyncMock(return_value=last_options),
    ):
        result = await handle("the mango one", orch)

    assert result is not None
    # Should have dispatched add_to_cart for the mango
    orch._execute_tool.assert_called_once_with(
        "add_to_cart", {"product_id": mango_id, "quantity": 1}
    )


@pytest.mark.asyncio
async def test_voice_index_match_dispatches_option():
    """Voice: 'option 2' selects the second option."""
    ids = [str(uuid.uuid4()) for _ in range(3)]
    last_options = [
        {
            "label": f"Product {i + 1}",
            "value": ids[i],
            "actions": [{"label": "Add to Cart", "value": f"add_{ids[i]}"}],
        }
        for i in range(3)
    ]

    orch, _ = _make_orchestrator()
    with patch(
        "app.services.agent.fast_path.get_last_options",
        new=AsyncMock(return_value=last_options),
    ):
        result = await handle("option 2", orch)

    assert result is not None
    orch._execute_tool.assert_called_once_with(
        "add_to_cart", {"product_id": ids[1], "quantity": 1}
    )


# ── Config constants are not hardcoded ───────────────────────────────────────


def test_fuzzy_thresholds_come_from_config():
    """Verify thresholds are imported from config, not hardcoded in fast_path."""
    import inspect

    import app.services.agent.fast_path as fp_module

    source = inspect.getsource(fp_module)
    # The numeric literals 0.7 and 0.6 must NOT appear in the module body
    # (they should only appear in config.py)
    assert "0.7" not in source, (
        "FUZZY_COSINE_THRESHOLD 0.7 hardcoded in fast_path.py — move to config"
    )
    assert "0.6" not in source, (
        "FUZZY_SEQUENCE_THRESHOLD 0.6 hardcoded in fast_path.py — move to config"
    )
    # But the constants must be imported and used
    assert "FUZZY_COSINE_THRESHOLD" in source
    assert "FUZZY_SEQUENCE_THRESHOLD" in source
