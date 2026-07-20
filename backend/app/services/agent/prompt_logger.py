"""
Prompt logger for dev mode.
Logs all LLM calls (system prompt, user prompt, response, timing) to timestamped files
in a prompt_logs/ directory. Only active in dev mode.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

from app.core.config import settings

logger = logging.getLogger("app.services.agent.prompt_logger")

LOG_DIR = "prompt_logs"


def _ensure_log_dir() -> str:
    """Ensure the prompt_logs directory exists and return its path."""
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    log_dir = os.path.join(project_root, LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def log_llm_call(
    call_type: str,
    system_prompt: str,
    user_prompt: str,
    response: str,
    temperature: float = 0.0,
    max_tokens: int = 256,
    duration_ms: float = 0.0,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Log an LLM call to a timestamped file for debugging.

    Args:
        call_type: Type of call (e.g. 'decomposition', 'synthesis', 'cart_decision', 'fact_classifier')
        system_prompt: The system prompt sent to the LLM
        user_prompt: The user prompt sent to the LLM
        response: The raw response from the LLM
        temperature: Temperature used
        max_tokens: Max tokens used
        duration_ms: Duration of the call in milliseconds
        error: Error message if the call failed
        extra: Any additional context to log
    """
    # Skip logging in production unless explicitly enabled
    if settings.ENV_MODE != "development" and not os.environ.get("PROMPT_LOG_ENABLED"):
        return

    try:
        log_dir = _ensure_log_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        safe_type = call_type.replace(" ", "_").replace("/", "_")[:50]
        filename = f"{timestamp}_{safe_type}.json"
        filepath = os.path.join(log_dir, filename)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": call_type,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "duration_ms": round(duration_ms, 2),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
        }

        if error:
            log_entry["error"] = error

        if extra:
            log_entry["extra"] = extra

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, indent=2, ensure_ascii=False)

        logger.debug(f"Prompt logged to {filepath}")

    except Exception as e:
        logger.warning(f"Failed to log prompt: {e}")
