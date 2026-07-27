"""
Task 3 verification tests for state_manager.py.

Tests:
  1. Basic set → get → clear round-trip
  2. get_pending returns None when key does not exist
  3. Concurrency: two coroutines race to set_pending on same session — one wins, one raises
  4. Corrupt Redis value is cleared gracefully
  5. History append + get
  6. Last-options cache round-trip
  7. Fact-index cache round-trip
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.state_manager import (
    ConcurrentMessageError,
    PendingState,
    append_history,
    clear_pending,
    get_fact_index,
    get_history,
    get_last_options,
    get_pending,
    set_fact_index,
    set_last_options,
    set_pending,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_redis(store: dict) -> MagicMock:
    """Build a minimal async Redis mock backed by a plain dict."""
    r = MagicMock()

    async def _get(key):
        return store.get(key)

    async def _set(key, value, ex=None):
        store[key] = value

    async def _delete(*keys):
        for k in keys:
            store.pop(k, None)

    async def _rpush(key, *values):
        if key not in store:
            store[key] = []
        for v in values:
            store[key].append(v)
        return len(store[key])

    async def _expire(key, ttl):
        pass  # not tracked in unit tests

    async def _lrange(key, start, end):
        lst = store.get(key, [])
        if end == -1:
            return lst[start:]
        if start < 0:
            # negative indexing: last |start| items
            return lst[start:]
        return lst[start : end + 1]

    # Lock mock: always acquires immediately
    lock_mock = MagicMock()
    lock_mock.acquire = AsyncMock(return_value=True)
    lock_mock.release = AsyncMock()

    r.get = _get
    r.set = _set
    r.delete = _delete
    r.rpush = _rpush
    r.expire = _expire
    r.lrange = _lrange
    r.lock = MagicMock(return_value=lock_mock)

    return r


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_get_clear_round_trip():
    """set_pending → get_pending → clear_pending works correctly."""
    store: dict = {}
    sid = str(uuid.uuid4())

    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        await set_pending(
            sid,
            "slot_fill",
            {"tool": "seller_create_product", "partial": {"name": "Mango"}},
        )

        state = await get_pending(sid)
        assert state is not None
        assert state.flow == "slot_fill"
        assert state.data["tool"] == "seller_create_product"
        assert state.data["partial"]["name"] == "Mango"

        await clear_pending(sid)
        assert await get_pending(sid) is None


@pytest.mark.asyncio
async def test_get_pending_returns_none_when_absent():
    """get_pending returns None when no state is stored."""
    store: dict = {}
    sid = str(uuid.uuid4())
    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        result = await get_pending(sid)
        assert result is None


@pytest.mark.asyncio
async def test_corrupt_state_cleared_gracefully():
    """Corrupt JSON in Redis is cleared and None is returned."""
    store: dict = {}
    sid = str(uuid.uuid4())
    pending_key = f"chat:session:{sid}:pending"
    store[pending_key] = "{not valid json{{{"

    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        result = await get_pending(sid)
        assert result is None
        # Key should have been deleted
        assert pending_key not in store


@pytest.mark.asyncio
async def test_concurrency_second_message_rejected():
    """Two coroutines racing to set_pending: second one gets ConcurrentMessageError."""
    store: dict = {}
    sid = str(uuid.uuid4())

    # First lock: acquires immediately. Second lock: fails to acquire.
    call_count = 0

    def _make_lock(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        lock = MagicMock()
        if call_count == 1:
            lock.acquire = AsyncMock(return_value=True)
        else:
            lock.acquire = AsyncMock(return_value=False)
        lock.release = AsyncMock()
        return lock

    fake_redis = _make_fake_redis(store)
    fake_redis.lock = MagicMock(side_effect=_make_lock)

    with patch(
        "app.services.agent.state_manager.get_redis_client", return_value=fake_redis
    ):
        # First call succeeds
        await set_pending(
            sid, "slot_fill", {"tool": "seller_create_product", "partial": {}}
        )

        # Second call should raise ConcurrentMessageError
        with pytest.raises(ConcurrentMessageError):
            await set_pending(sid, "slot_fill", {"tool": "other_tool", "partial": {}})


@pytest.mark.asyncio
async def test_history_append_and_get():
    """append_history + get_history returns messages in order."""
    store: dict = {}
    sid = str(uuid.uuid4())

    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        await append_history(sid, "user", "hello")
        await append_history(sid, "assistant", "hi there")
        await append_history(sid, "user", "show my orders")

        msgs = await get_history(sid, limit=20)
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"
        assert msgs[2]["content"] == "show my orders"


@pytest.mark.asyncio
async def test_history_limit():
    """get_history with limit=2 returns only last 2 messages."""
    store: dict = {}
    sid = str(uuid.uuid4())

    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        for i in range(5):
            await append_history(sid, "user", f"msg {i}")

        msgs = await get_history(sid, limit=2)
        assert len(msgs) == 2
        assert msgs[-1]["content"] == "msg 4"


@pytest.mark.asyncio
async def test_last_options_cache():
    """set_last_options / get_last_options round-trip."""
    store: dict = {}
    sid = str(uuid.uuid4())
    options = [
        {"label": "Mango", "value": "uuid-1", "description": "$4.49"},
        {"label": "Apple", "value": "uuid-2", "description": "$3.99"},
    ]

    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        await set_last_options(sid, options)
        result = await get_last_options(sid)
        assert result == options


@pytest.mark.asyncio
async def test_last_options_empty_when_absent():
    """get_last_options returns [] when nothing stored."""
    store: dict = {}
    sid = str(uuid.uuid4())
    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        assert await get_last_options(sid) == []


@pytest.mark.asyncio
async def test_fact_index_cache():
    """set_fact_index / get_fact_index round-trip."""
    store: dict = {}
    sid = str(uuid.uuid4())
    index_map = {"1": "fact-uuid-aaa", "2": "fact-uuid-bbb"}

    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        await set_fact_index(sid, index_map)
        result = await get_fact_index(sid)
        assert result == index_map


@pytest.mark.asyncio
async def test_fact_index_empty_when_absent():
    """get_fact_index returns {} when nothing stored."""
    store: dict = {}
    sid = str(uuid.uuid4())
    with patch(
        "app.services.agent.state_manager.get_redis_client",
        return_value=_make_fake_redis(store),
    ):
        assert await get_fact_index(sid) == {}


@pytest.mark.asyncio
async def test_pending_state_serialization():
    """PendingState.to_json / from_json round-trip."""
    state = PendingState(
        flow="role_switch",
        data={
            "tool_name": "seller_create_product",
            "original_params": {"name": "Test"},
            "needed_role": "seller",
        },
        created_at=1234567890.0,
    )
    serialized = state.to_json()
    restored = PendingState.from_json(serialized)
    assert restored.flow == state.flow
    assert restored.data == state.data
    assert restored.created_at == state.created_at
