import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger("app.services.agent.llm")

_openai_client: AsyncOpenAI | None = None


def get_llm_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        logger.info(
            f"Initializing AsyncOpenAI client with base URL: {settings.NIM_BASE_URL}"
        )
        _openai_client = AsyncOpenAI(
            api_key=settings.NIM_API_KEY,
            base_url=settings.NIM_BASE_URL,
        )
    return _openai_client


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 512,
    response_format: dict[str, Any] | None = None,
) -> str:
    """Wrapper to query the NIM model using AsyncOpenAI."""
    client = get_llm_client()
    try:
        kwargs: dict[str, Any] = {
            "model": settings.NIM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        return content.strip() if content else ""
    except Exception as e:
        logger.error(f"Error querying NIM model {settings.NIM_MODEL}: {e}")
        raise
