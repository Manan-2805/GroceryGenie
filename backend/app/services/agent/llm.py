import asyncio
import json
import logging
import time
from typing import Any

from openai import APITimeoutError, AsyncOpenAI

from app.core.config import settings
from app.services.agent.prompt_logger import log_llm_call

logger = logging.getLogger("app.services.agent.llm")

_openai_client: AsyncOpenAI | None = None

# Single timeout - no double retry. OpenAI client handles its own retries internally.
DEFAULT_TIMEOUT = 60.0  # seconds
MAX_RETRIES = 1  # Only 1 retry to avoid compounding delays
RETRY_DELAY = 2.0  # seconds


def get_llm_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        logger.info(
            f"Initializing AsyncOpenAI client with base URL: {settings.NIM_BASE_URL}"
        )
        _openai_client = AsyncOpenAI(
            api_key=settings.NIM_API_KEY,
            base_url=settings.NIM_BASE_URL,
            timeout=DEFAULT_TIMEOUT + 10,
            max_retries=0,  # Disable internal retries - we handle retries ourselves
        )
    return _openai_client


def extract_json_from_response(text: str) -> str:
    """
    Robustly extract JSON from an LLM response.
    Handles markdown code blocks, leading/trailing text, and multiple JSON objects.
    Returns the FIRST complete JSON object found.
    """
    cleaned = text.strip()

    # Remove markdown code block markers
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    # Try to parse the entire cleaned text as JSON first
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    # Find the first { and track brace depth to find matching closing }
    start_idx = cleaned.find("{")
    if start_idx == -1:
        return cleaned

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start_idx, len(cleaned)):
        char = cleaned[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start_idx : i + 1]

    # Fallback: find first { and last }
    end_idx = cleaned.rfind("}")
    if end_idx > start_idx:
        return cleaned[start_idx : end_idx + 1]

    return cleaned


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 512,
    response_format: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    call_type: str = "llm_call",
) -> str:
    """Wrapper to query the NIM model using AsyncOpenAI with retry logic and timeout."""
    client = get_llm_client()

    kwargs: dict[str, Any] = {
        "model": settings.NIM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if response_format:
        kwargs["response_format"] = response_format

    last_error: Exception | None = None
    start_time = time.monotonic()

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=timeout,
            )
            content: str | None = response.choices[0].message.content
            duration_ms = (time.monotonic() - start_time) * 1000

            if content is None:
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY
                    logger.warning(f"LLM returned None content, retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                log_llm_call(
                    call_type=call_type,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response="",
                    temperature=temperature,
                    max_tokens=max_tokens,
                    duration_ms=duration_ms,
                    error="LLM returned None content after all retries",
                )
                return ""

            # Log the successful call
            log_llm_call(
                call_type=call_type,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=content.strip(),
                temperature=temperature,
                max_tokens=max_tokens,
                duration_ms=duration_ms,
            )

            return content.strip()

        except (TimeoutError, APITimeoutError):
            last_error = TimeoutError(f"LLM request timed out after {timeout}s")
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"LLM timeout (attempt {attempt + 1}), retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
                continue
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"LLM error: {e} (attempt {attempt + 1}), retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
                continue

    duration_ms = (time.monotonic() - start_time) * 1000
    error_msg = str(last_error) if last_error else "LLM call failed after all retries"

    log_llm_call(
        call_type=call_type,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response="",
        temperature=temperature,
        max_tokens=max_tokens,
        duration_ms=duration_ms,
        error=error_msg,
    )

    logger.error(
        f"Error querying NIM model {settings.NIM_MODEL} after {MAX_RETRIES + 1} attempts: {last_error}"
    )
    # Return empty string instead of raising - let callers handle gracefully
    return ""
