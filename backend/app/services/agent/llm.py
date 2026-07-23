import asyncio
import json
import logging
import random
import time
from typing import Any

from openai import APITimeoutError, AsyncOpenAI

from app.core.config import TEMPERATURE_RESTRICTED_MODELS, settings
from app.services.agent.prompt_logger import log_llm_call

logger = logging.getLogger("app.services.agent.llm")

# Timeout and retry config
DEFAULT_TIMEOUT = 12.0  # seconds (fail fast for interactive sessions)
MAX_RETRIES = 1  # Total attempts per provider (1 initial + 1 retry)
RETRY_BASE_DELAY = 0.5  # seconds
RETRY_MAX_DELAY = 3.0  # seconds

# Provider client cache: {provider_name: AsyncOpenAI}
_provider_clients: dict[str, AsyncOpenAI] = {}

# Current provider tracking for health check
_current_provider_index: int = 0


def get_llm_client(
    provider_name: str, base_url: str, api_key: str, timeout: float
) -> AsyncOpenAI:
    """Get or create an AsyncOpenAI client for the given provider."""
    cache_key = f"{provider_name}:{base_url}"
    if cache_key not in _provider_clients:
        logger.info(
            f"Initializing AsyncOpenAI client for provider '{provider_name}' at {base_url}"
        )
        _provider_clients[cache_key] = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout + 10,
            max_retries=0,  # We handle retries ourselves
        )
    return _provider_clients[cache_key]


def get_all_providers() -> list[dict[str, Any]]:
    """Get the list of all configured LLM providers."""
    return settings.parsed_llm_providers


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


def get_safe_temperature(
    provider_config: dict[str, Any], requested_temp: float
) -> float:
    """Return a temperature that is valid for the given provider's model.
    Some models (like Kimi k2.6) only allow temperature=1.0.
    """
    model = provider_config.get("model", "")
    if model in TEMPERATURE_RESTRICTED_MODELS:
        return 1.0
    return requested_temp


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 512,
    response_format: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    call_type: str = "llm_call",
    provider_name: str | None = None,
) -> str:
    """Wrapper to query any LLM provider with retry logic, timeout, and cross-provider fallback.

    Args:
        system_prompt: System prompt for the LLM
        user_prompt: User prompt for the LLM
        temperature: Temperature parameter (may be overridden for model-restricted providers)
        max_tokens: Maximum tokens to generate
        response_format: Optional response format (e.g. json_object)
        timeout: Timeout in seconds for each request
        call_type: Type of call for logging
        provider_name: Optional specific provider to use. If None, tries all providers in order.

    Returns:
        The LLM response text, or empty string if all attempts fail.
    """
    providers = get_all_providers()

    # If a specific provider is requested, try only that one
    if provider_name:
        providers = [p for p in providers if p["name"] == provider_name]
        if not providers:
            logger.warning(f"Requested provider '{provider_name}' not found in config")
            return ""

    last_error: Exception | None = None
    start_time = time.monotonic()

    # Try each provider in order (primary first, then secondary, etc.)
    for provider_idx, provider_config in enumerate(providers):
        provider_name = provider_config["name"]
        base_url = provider_config["base_url"]
        api_key = provider_config["api_key"]
        model = provider_config["model"]
        provider_timeout = provider_config.get("timeout", timeout)
        safe_temperature = get_safe_temperature(provider_config, temperature)

        client = get_llm_client(provider_name, base_url, api_key, provider_timeout)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": safe_temperature,
            "max_tokens": max_tokens,
            "timeout": provider_timeout,
        }
        if response_format:
            kwargs["response_format"] = response_format

        logger.info(
            f"Calling LLM provider '{provider_name}' (model={model}, temp={safe_temperature}, "
            f"call_type={call_type}, provider_idx={provider_idx})"
        )

        # Retry loop within this provider
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    client.chat.completions.create(**kwargs),
                    timeout=provider_timeout,
                )
                content: str | None = response.choices[0].message.content
                duration_ms = (time.monotonic() - start_time) * 1000

                # Extract token usage
                input_tokens = None
                output_tokens = None
                if hasattr(response, "usage") and response.usage is not None:
                    input_tokens = getattr(response.usage, "prompt_tokens", None)
                    output_tokens = getattr(response.usage, "completion_tokens", None)

                if content is None:
                    if attempt < MAX_RETRIES:
                        wait = _compute_retry_delay(attempt)
                        logger.warning(
                            f"LLM provider '{provider_name}' returned None content (attempt {attempt + 1}), "
                            f"retrying in {wait:.1f}s..."
                        )
                        await asyncio.sleep(wait)
                        continue
                    log_llm_call(
                        call_type=call_type,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response="",
                        temperature=safe_temperature,
                        max_tokens=max_tokens,
                        duration_ms=duration_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        extra={"provider": provider_name, "model": model},
                        error="LLM returned None content after all retries",
                    )
                    # Move to next provider
                    break

                # Log the successful call with token usage
                log_llm_call(
                    call_type=call_type,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response=content.strip(),
                    temperature=safe_temperature,
                    max_tokens=max_tokens,
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    extra={
                        "provider": provider_name,
                        "model": model,
                        "attempt": attempt + 1,
                        "provider_idx": provider_idx,
                    },
                )

                logger.info(
                    f"LLM call successful: provider='{provider_name}', model={model}, "
                    f"call_type={call_type}, duration={duration_ms:.0f}ms, attempt={attempt + 1}"
                    + (
                        f", tokens_in={input_tokens}, tokens_out={output_tokens}"
                        if input_tokens
                        else ""
                    )
                )

                return content.strip()

            except (TimeoutError, APITimeoutError):
                last_error = TimeoutError(
                    f"LLM request timed out after {provider_timeout}s"
                )
                if attempt < MAX_RETRIES:
                    wait = _compute_retry_delay(attempt)
                    logger.warning(
                        f"LLM timeout on provider '{provider_name}' (attempt {attempt + 1}), "
                        f"retrying in {wait:.1f}s..."
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning(
                    f"LLM provider '{provider_name}' timed out after {MAX_RETRIES + 1} attempts"
                )

            except Exception as e:
                last_error = e
                # Don't retry auth errors - they won't succeed on retry
                if _is_auth_error(e):
                    logger.error(
                        f"LLM auth error on provider '{provider_name}': {e}. "
                        f"Skipping remaining retries for this provider."
                    )
                    break

                if attempt < MAX_RETRIES:
                    wait = _compute_retry_delay(attempt)
                    logger.warning(
                        f"LLM error on provider '{provider_name}': {e} (attempt {attempt + 1}), "
                        f"retrying in {wait:.1f}s..."
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning(
                    f"LLM provider '{provider_name}' failed after {MAX_RETRIES + 1} attempts: {e}"
                )

        # If we get here, this provider failed all retries. Try next provider.
        if provider_idx < len(providers) - 1:
            logger.info("Falling back to next LLM provider...")

    # All providers exhausted
    duration_ms = (time.monotonic() - start_time) * 1000
    error_msg = (
        str(last_error)
        if last_error
        else "LLM call failed after all providers and retries"
    )

    log_llm_call(
        call_type=call_type,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response="",
        temperature=temperature,
        max_tokens=max_tokens,
        duration_ms=duration_ms,
        error=error_msg,
        extra={"providers_tried": [p["name"] for p in providers]},
    )

    logger.error(
        f"Error querying LLM after {len(providers)} providers and up to {MAX_RETRIES + 1} retries each: {last_error}"
    )
    # Return empty string instead of raising - let callers handle gracefully
    return ""


def _compute_retry_delay(attempt: int) -> float:
    """Compute exponential backoff with jitter for retry delay."""
    delay = RETRY_BASE_DELAY * (1.5**attempt)
    delay = min(delay, RETRY_MAX_DELAY)
    # Add jitter: +/- 25% (not security sensitive - only for retry timing)
    jitter = delay * 0.25 * (2 * random.random() - 1)  # nosec
    return delay + jitter


def _is_auth_error(e: Exception) -> bool:
    """Check if the exception is an authentication/authorization error."""
    error_str = str(e).lower()
    return any(
        keyword in error_str
        for keyword in [
            "401",
            "402",
            "403",
            "auth",
            "api key",
            "unauthorized",
            "forbidden",
        ]
    )
