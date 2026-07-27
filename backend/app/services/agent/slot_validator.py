"""
SlotValidator — schema-driven slot-filling for the GroceryGenie agent.

Replaces all ad-hoc slot-fill methods in orchestrator.py:
  - _handle_seller_create_slot_fill / _handle_seller_create_followup
  - _start_address_collect_flow / _handle_address_collect_response
  - _ask_for_quantity (quantity is now just a slot in add_to_cart schema)

Public API:
    validate(tool_name, params)
        → (is_complete: bool, missing: list[str], ask_text: str)

    merge(tool_name, partial_params, user_message)
        → merged_params: dict  (calls LLM to extract new values, coerces types)

Both functions are pure in the sense that they do NOT touch Redis.
The orchestrator is responsible for reading/writing pending state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.agent.llm import call_llm, extract_json_from_response
from app.services.agent.prompts import ADDRESS_EXTRACT_PROMPT, FIELD_EXTRACT_PROMPT
from app.services.agent.tools import TOOL_SCHEMAS

logger = logging.getLogger("app.services.agent.slot_validator")

# Address tools — use the dedicated ADDRESS_EXTRACT_PROMPT
_ADDRESS_TOOLS: frozenset[str] = frozenset({"manage_addresses"})

# Fields that represent the address sub-form (inside address_data)
_ADDRESS_FIELDS: tuple[str, ...] = (
    "label",
    "line1",
    "line2",
    "city",
    "state",
    "postal_code",
    "country",
)

# Required address sub-fields for "add" action
_ADDRESS_REQUIRED: tuple[str, ...] = (
    "label",
    "line1",
    "city",
    "state",
    "postal_code",
)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def validate(
    tool_name: str,
    params: dict[str, Any],
) -> tuple[bool, list[str], str]:
    """Check whether all required fields for *tool_name* are present in *params*.

    For manage_addresses with action=add, the required fields are checked
    inside the nested address_data dict.

    Returns:
        (is_complete, missing_fields, ask_text)

        is_complete:    True if all required fields are present and non-empty.
        missing_fields: List of field names that are absent/None/empty.
        ask_text:       Human-readable message listing what's still needed,
                        including hints from TOOL_SCHEMAS.
                        Empty string if is_complete is True.
    """
    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        # Unknown tool — treat as complete (RBAC will catch it later)
        return True, [], ""

    # Special handling: manage_addresses add action — validate inside address_data
    if tool_name == "manage_addresses" and params.get("action") == "add":
        address_data: dict[str, Any] = params.get("address_data") or {}
        # Flatten: normalise aliases so validation is against canonical field names
        normalised = _normalise_address(address_data)
        missing = [
            f
            for f in _ADDRESS_REQUIRED
            if not normalised.get(f) or str(normalised[f]).strip() == ""
        ]
        if not missing:
            return True, [], ""
        addr_hints = schema.get("hints", {})
        hint_parts = [f"{f} ({addr_hints.get(f, '')})" for f in missing]
        already = _describe_collected_address(normalised)
        have_str = f" (I have: {already})" if already else ""
        ask = (
            f"I still need the following to save this address{have_str}: "
            f"**{', '.join(hint_parts)}**.\n\n"
            "You can provide them in one message, e.g. "
            '"Home, B-63 Street 5, Bhuj, Gujarat, 370001"'
        )
        return False, missing, ask

    # General tool slot-fill
    required: list[str] = schema.get("required", [])
    hints: dict[str, str] = schema.get("hints", {})

    missing = []
    for field in required:
        val = params.get(field)
        if val is None or str(val).strip() == "":
            missing.append(field)

    if not missing:
        return True, [], ""

    # Build human-readable ask
    hint_parts = []
    for f in missing:
        hint = hints.get(f, "")
        if hint:
            hint_parts.append(f"{f} ({hint})")
        else:
            hint_parts.append(f)

    already_have = [
        f"{f}: {params[f]}"
        for f in required
        if f not in missing and params.get(f) is not None
    ]
    have_str = f" (I have: {', '.join(already_have)})" if already_have else ""

    ask = f"I still need the following{have_str}: **{', '.join(hint_parts)}**."

    # Add example if available for seller_create_product
    if tool_name == "seller_create_product":
        ask += '\n\nPlease provide them together, e.g. "price 4.99, stock 100, category Fruits"'

    return False, missing, ask


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


async def merge(
    tool_name: str,
    partial_params: dict[str, Any],
    user_message: str,
) -> dict[str, Any]:
    """Extract new field values from *user_message* and merge into *partial_params*.

    Uses:
      - ADDRESS_EXTRACT_PROMPT for manage_addresses (address field extraction)
      - FIELD_EXTRACT_PROMPT for all other tools (generic field extraction)

    Type coercion is applied based on TOOL_SCHEMAS[tool_name]["types"].

    Returns the merged params dict. Original partial_params is not mutated.
    """
    result = dict(partial_params)

    if tool_name in _ADDRESS_TOOLS:
        addr_extracted = await _extract_address_fields(user_message)
        # Merge: extracted values win over existing None/empty values
        for k, v in addr_extracted.items():
            if v is not None and str(v).strip():
                # Map into address_data sub-dict
                addr_data: dict[str, Any] = result.get("address_data") or {}
                addr_data[k] = v
                result["address_data"] = addr_data
        return result

    # Generic extraction using FIELD_EXTRACT_PROMPT
    schema = TOOL_SCHEMAS.get(tool_name, {})
    required: list[str] = schema.get("required", [])
    optional: list[str] = schema.get("optional", [])
    hints: dict[str, str] = schema.get("hints", {})
    types: dict[str, type] = schema.get("types", {})

    all_fields = list(dict.fromkeys(required + optional))  # preserve order, deduplicate
    if not all_fields:
        return result

    hints_text = "; ".join(f"{f}: {hints[f]}" for f in all_fields if f in hints)

    prompt = FIELD_EXTRACT_PROMPT.format(
        fields=", ".join(all_fields),
        hints=hints_text or "none",
        user_message=user_message,
    )

    raw = await call_llm(
        system_prompt="You are a precise field extractor. Return only JSON.",
        user_prompt=prompt,
        temperature=0.0,
        max_tokens=256,
        call_type="slot_field_extract",
    )

    extracted: dict[str, Any] = {}
    if raw:
        try:
            extracted = json.loads(extract_json_from_response(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                f"[SlotValidator] Failed to parse extracted fields: {exc}. Raw: {raw[:200]}"
            )

    # Merge: only non-null extracted values update the result
    for field, value in extracted.items():
        if value is None:
            continue
        str_val = str(value).strip()
        if not str_val or str_val.lower() == "null":
            continue
        result[field] = value

    # Type coercion
    return _coerce_types(result, types)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_types(params: dict[str, Any], types: dict[str, type]) -> dict[str, Any]:
    """Coerce param values to their declared types. Returns new dict.

    On coercion failure for a field, the original string value is kept and
    a warning is logged — the orchestrator will detect it as still-missing
    on the next validate() call if required, or silently ignore if optional.
    """
    result = dict(params)
    for field, target_type in types.items():
        if field not in result or result[field] is None:
            continue
        val = result[field]
        if isinstance(val, target_type):
            continue
        try:
            if target_type is float:
                # Strip leading $ signs or other currency markers
                result[field] = float(
                    str(val).replace("$", "").replace(",", "").strip()
                )
            elif target_type is int:
                result[field] = int(float(str(val).replace(",", "").strip()))
            elif target_type is bool:
                result[field] = str(val).lower() in ("true", "1", "yes")
            else:
                result[field] = target_type(val)
        except (ValueError, TypeError) as exc:
            logger.warning(
                f"[SlotValidator] Type coercion failed for field '{field}' "
                f"(value={val!r}, target={target_type.__name__}): {exc}"
            )
    return result


async def _extract_address_fields(text: str) -> dict[str, Any]:
    """Run ADDRESS_EXTRACT_PROMPT on *text* and return structured fields."""
    raw = await call_llm(
        system_prompt="You are a precise address field extractor.",
        user_prompt=ADDRESS_EXTRACT_PROMPT.format(address_text=text),
        temperature=0.0,
        max_tokens=200,
        call_type="address_extract",
    )
    if not raw:
        return {}
    try:
        extracted = json.loads(extract_json_from_response(raw))
        # Strip null / empty values
        return {k: v for k, v in extracted.items() if v is not None and str(v).strip()}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"[SlotValidator] Address extraction parse error: {exc}")
        return {}


def _normalise_address(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise address field aliases to canonical names."""
    norm = dict(raw)
    if "line1" not in norm:
        for alias in ("street", "line_1", "house_number", "street_address", "address"):
            if alias in norm and norm[alias]:
                norm["line1"] = norm[alias]
                break
    if "postal_code" not in norm:
        for alias in ("zip_code", "pin_code", "zip", "pincode", "postal", "pin"):
            if alias in norm and norm[alias]:
                norm["postal_code"] = str(norm[alias])
                break
    if "country" not in norm or not norm.get("country"):
        norm["country"] = "India"
    if "label" not in norm or not norm.get("label"):
        norm["label"] = "Home"
    return norm


def _describe_collected_address(norm: dict[str, Any]) -> str:
    """Build a short human-readable summary of already-collected address fields."""
    parts = []
    if norm.get("label"):
        parts.append(f"label: {norm['label']}")
    if norm.get("line1"):
        parts.append(f"street: {norm['line1']}")
    if norm.get("city"):
        parts.append(f"city: {norm['city']}")
    if norm.get("state"):
        parts.append(f"state: {norm['state']}")
    if norm.get("postal_code"):
        parts.append(f"pin: {norm['postal_code']}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# coerce_types — re-exported for use in orchestrator
# ---------------------------------------------------------------------------
coerce_types = _coerce_types
