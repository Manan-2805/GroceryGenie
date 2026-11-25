import json
from typing import Any

import httpx
import pytest

from app.assistant import provider
from app.db.models.enums import UserRole


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", [True, False])
async def test_provider_fallback_is_bounded_and_parses_approved_schema(
    monkeypatch, recovery
):
    monkeypatch.setattr(
        provider.settings,
        "LLM_PROVIDERS",
        """[
        {"name":"primary","base_url":"https://primary.example.invalid/v1","model":"example","api_key":"synthetic-test-key","reasoning_effort":"low","token_limit_field":"max_completion_tokens"},
        {"name":"fallback","base_url":"https://fallback.example.invalid/v1","model":"example","api_key":"synthetic-test-key"},
        {"name":"unused","base_url":"https://unused.example.invalid/v1","model":"example","api_key":"synthetic-test-key"}
    ]""",
    )
    observed = []

    def serve(request: httpx.Request) -> httpx.Response:
        observed.append(str(request.url))
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        assert request.url.path == "/v1/chat/completions"
        if len(observed) == 1:
            body = json.loads(request.content)
            assert body["reasoning_effort"] == "low"
            assert body["max_completion_tokens"] == 900
            assert "max_tokens" not in body
            return httpx.Response(429)
        if not recovery:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"steps":[{"tool":"unknown"}]}',
                            }
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"steps":[{"tool":"orders"}]}',
                        }
                    }
                ],
                "usage": {"prompt_tokens": 17, "completion_tokens": 8},
            },
        )

    client = httpx.AsyncClient

    def mock_client(**kwargs: Any) -> httpx.AsyncClient:
        return client(transport=httpx.MockTransport(serve), **kwargs)

    monkeypatch.setattr(provider.httpx, "AsyncClient", mock_client)
    result = await provider.interpret("List my recent orders.", UserRole.customer, "")
    assert len(observed) == 2
    assert (result is not None) == recovery
    if result:
        assert result.steps[0].tool == "orders"
