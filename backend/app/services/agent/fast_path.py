"""
FastPath — zero-LLM prefix dispatch + fuzzy option matching.

handle() is called by the orchestrator BEFORE intent classification.
It returns a formatted response dict if it can resolve the message
deterministically, or None to fall through to the LLM.

Two resolution strategies:

1. Prefix dispatch (O(1))
   Direct action prefixes emitted by the frontend (add_, remove_, view_,
   order_detail_, fulfillment_status_, etc.) are handled immediately.

2. Fuzzy option matching (O(N) where N = number of last options)
   When no prefix matches, compare the user message against the labels of
   the last options_request (stored in Redis by the orchestrator after each
   options response). If either:
     - cosine similarity >= FUZZY_COSINE_THRESHOLD, or
     - SequenceMatcher ratio >= FUZZY_SEQUENCE_THRESHOLD
   then we treat the message as selecting that option and dispatch its action.

   Voice-specific numeric matching ("the first one", "option 2", "number three")
   is checked before fuzzy text matching.

Fuzzy thresholds live in app.core.config and are never hardcoded here.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import TYPE_CHECKING, Any

from app.core.config import FUZZY_COSINE_THRESHOLD, FUZZY_SEQUENCE_THRESHOLD
from app.services.agent.state_manager import get_last_options

if TYPE_CHECKING:
    from app.services.agent.orchestrator import AgentOrchestrator

logger = logging.getLogger("app.services.agent.fast_path")

# ---------------------------------------------------------------------------
# Numeric / ordinal word patterns for voice index matching
# ---------------------------------------------------------------------------
# Stopwords excluded from keyword-contains matching
_FUZZY_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "one",
        "some",
        "any",
        "of",
        "for",
        "is",
        "are",
        "my",
        "me",
        "that",
        "this",
        "those",
        "these",
    }
)

_ORDINAL_MAP = {
    "first": 1,
    "one": 1,
    "1": 1,
    "second": 2,
    "two": 2,
    "2": 2,
    "third": 3,
    "three": 3,
    "3": 3,
    "fourth": 4,
    "four": 4,
    "4": 4,
    "fifth": 5,
    "five": 5,
    "5": 5,
    "sixth": 6,
    "six": 6,
    "6": 6,
    "seventh": 7,
    "seven": 7,
    "7": 7,
    "eighth": 8,
    "eight": 8,
    "8": 8,
    "ninth": 9,
    "nine": 9,
    "9": 9,
    "tenth": 10,
    "ten": 10,
    "10": 10,
}

_INDEX_RE = re.compile(
    r"\b(?:option|number|the)\s*(\d+|first|second|third|fourth|fifth|"
    r"sixth|seventh|eighth|ninth|tenth|one|two|three|four|five|"
    r"six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)


def _extract_option_index(text: str) -> int | None:
    """Return 1-based option index if text contains a numeric/ordinal reference, else None."""
    m = _INDEX_RE.search(text)
    if m:
        word = m.group(1).lower()
        return _ORDINAL_MAP.get(word)
    # Bare number anywhere in short messages ("2", "3")
    stripped = text.strip()
    if stripped.isdigit():
        idx = int(stripped)
        if 1 <= idx <= 10:
            return idx
    return None


def _cosine_similarity(a: str, b: str) -> float:
    """Compute token-overlap cosine similarity between two strings.

    Uses a simple bag-of-words representation (no embeddings) so it runs
    in-process without loading any model. For option label matching this is
    sufficient; real semantic embedding is unnecessary for short labels.
    """
    tokens_a: set[str] = set(a.lower().split())
    tokens_b: set[str] = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection: set[str] = tokens_a & tokens_b
    denom: float = (len(tokens_a) * len(tokens_b)) ** 0.5
    if denom == 0:
        return 0.0
    return float(len(intersection)) / denom


def _sequence_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _best_option_match(
    user_message: str,
    options: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the best-matching option or None if no option clears the threshold.

    Matching uses three complementary signals (highest wins):
      1. Cosine similarity (bag-of-words token overlap)
      2. SequenceMatcher ratio (character-level similarity)
      3. Keyword-contains: any non-trivial word (>=4 chars) from the user
         message that appears in an option label scores above the sequence
         threshold — enough to fire for cases like "the mango one" →
         "E2E Premium Mango".

    At least one of cosine >= FUZZY_COSINE_THRESHOLD or
    seq >= FUZZY_SEQUENCE_THRESHOLD or keyword_hit must be true.
    """
    _stopwords = frozenset(
        {
            "the",
            "a",
            "an",
            "one",
            "some",
            "any",
            "of",
            "for",
            "is",
            "are",
            "my",
            "me",
            "that",
            "this",
            "those",
            "these",
        }
    )

    msg_tokens = [
        t.lower()
        for t in user_message.split()
        if len(t) >= 4 and t.lower() not in _stopwords
    ]

    best_score = 0.0
    best_opt: dict[str, Any] | None = None

    for opt in options:
        label = str(opt.get("label", ""))
        if not label:
            continue
        label_lower = label.lower()

        cosine = _cosine_similarity(user_message, label)
        seq = _sequence_ratio(user_message, label)

        # Keyword-contains signal: any significant user token appears in label
        keyword_score = 0.0
        for token in msg_tokens:
            if token in label_lower:
                keyword_score = (
                    FUZZY_SEQUENCE_THRESHOLD + 0.05
                )  # just above seq threshold
                break

        score = max(cosine, seq, keyword_score)
        if score > best_score:
            best_score = score
            best_opt = opt

    if best_opt is None:
        return None

    label = str(best_opt.get("label", ""))
    label_lower = label.lower()
    cosine = _cosine_similarity(user_message, label)
    seq = _sequence_ratio(user_message, label)
    keyword_hit = any(t in label_lower for t in msg_tokens)

    if (
        cosine >= FUZZY_COSINE_THRESHOLD
        or seq >= FUZZY_SEQUENCE_THRESHOLD
        or keyword_hit
    ):
        return best_opt
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def handle(
    user_message: str,
    orchestrator: AgentOrchestrator,
) -> dict[str, Any] | None:
    """Try to resolve user_message without an LLM call.

    Returns a formatted response dict if resolved, or None to fall through.
    """
    msg = user_message.strip()
    msg_lower = msg.lower()
    session_id = str(orchestrator.session_id)

    # ── 1. Prefix dispatch ───────────────────────────────────────────────

    # add_<uuid>
    if msg.startswith("add_"):
        pid = msg[4:].strip()
        if pid:
            result = await orchestrator._execute_tool(
                "add_to_cart", {"product_id": pid, "quantity": 1}
            )
            return orchestrator._format_response_sync(user_message, result)

    # remove_<uuid>
    if msg.startswith("remove_"):
        pid = msg[7:].strip()
        if pid:
            result = await orchestrator._execute_tool(
                "remove_from_cart", {"product_id": pid}
            )
            return orchestrator._format_response_sync(user_message, result)

    # view_<uuid>  (product detail — NOT view_cart or view_orders or view_facts)
    if (
        msg.startswith("view_")
        and not msg_lower.startswith("view_cart")
        and not msg_lower.startswith("view_orders")
        and not msg_lower.startswith("view_facts")
    ):
        # Also handle legacy view_product_id_<uuid>
        if msg.startswith("view_product_id_"):
            pid = msg[16:].strip()
        else:
            pid = msg[5:].strip()
        if pid:
            from uuid import UUID

            from sqlalchemy import select

            from app.db.models.product import Product

            try:
                puuid = UUID(pid)
                p_res = await orchestrator.db.execute(
                    select(Product).where(Product.id == puuid)
                )
                product = p_res.scalar_one_or_none()
                if product:
                    return {
                        "type": "options_response",
                        "text": f"**{product.name}** — ${float(product.price):.2f}\n{product.description}",
                        "options": [
                            {
                                "label": product.name,
                                "value": str(product.id),
                                "description": (
                                    f"${float(product.price):.2f} · Stock: {product.stock} "
                                    f"· ⭐ {float(product.avg_rating):.1f}"
                                ),
                                "actions": [
                                    {
                                        "label": "Add to Cart",
                                        "value": f"add_{product.id}",
                                    }
                                ],
                            }
                        ],
                        "free_input_allowed": True,
                        "card_variant": "search",
                    }
            except (ValueError, Exception):
                pass

    # order_detail_<uuid>
    if msg.startswith("order_detail_"):
        oid = msg[13:].strip()
        if oid:
            result = await orchestrator._execute_tool(
                "get_order_detail", {"order_id": oid}
            )
            return orchestrator._format_response_sync(user_message, result)

    # fulfillment_status_<uuid>_<status>
    if msg.startswith("fulfillment_status_"):
        remainder = msg[19:].strip()
        if len(remainder) > 37 and remainder[36] == "_":
            order_id = remainder[:36]
            new_status = remainder[37:]
            result = await orchestrator._execute_tool(
                "update_order_status",
                {"order_ids": [order_id], "new_status": new_status},
            )
            return orchestrator._format_response_sync(user_message, result)

    # delete_address_<uuid>
    if msg.startswith("delete_address_"):
        aid = msg[15:].strip()
        if aid:
            result = await orchestrator._execute_tool(
                "manage_addresses", {"action": "delete", "address_id": aid}
            )
            return orchestrator._format_response_sync(user_message, result)

    # set_default_address_<uuid>
    if msg.startswith("set_default_address_"):
        aid = msg[20:].strip()
        if aid:
            result = await orchestrator._execute_tool(
                "manage_addresses",
                {
                    "action": "update",
                    "address_id": aid,
                    "address_data": {"is_default": True},
                },
            )
            return orchestrator._format_response_sync(user_message, result)

    # update_address_<uuid>
    if msg.startswith("update_address_"):
        aid = msg[15:].strip()
        if aid:
            return await orchestrator._start_address_update_flow(aid)

    # seller_deactivate_<uuid>  (single product from catalog card)
    if msg.startswith("seller_deactivate_"):
        pid = msg[18:].strip()
        if pid:
            result = await orchestrator._execute_tool(
                "seller_delete_product", {"product_id": pid}
            )
            return orchestrator._format_response_sync(user_message, result)

    # seller_edit_<uuid>  — start update flow (show current product, ask what to change)
    if msg.startswith("seller_edit_"):
        pid = msg[12:].strip()
        if pid:
            return await orchestrator._start_seller_edit_flow(pid)

    # delete_fact_<uuid>
    if msg.startswith("delete_fact_"):
        fid = msg[12:].strip()
        if fid:
            result = await orchestrator._execute_tool(
                "manage_facts", {"action": "delete", "fact_id": fid}
            )
            return orchestrator._format_response_sync(user_message, result)

    # compare_<uuid>,<uuid>[,<uuid>]  — explicit compare prefix
    if msg.startswith("compare_"):
        raw_ids = msg[8:].strip()
        product_ids = [p.strip() for p in raw_ids.split(",") if p.strip()]
        if len(product_ids) >= 2:
            result = await orchestrator._execute_tool(
                "compare_products", {"product_ids": product_ids}
            )
            return orchestrator._format_response_sync(user_message, result)

    # checkout / place order keywords
    if msg_lower in ("place_order", "checkout", "place order", "buy now"):
        result = await orchestrator._execute_tool("place_order", {})
        return orchestrator._format_response_sync(user_message, result)

    # view cart keywords
    if msg_lower in (
        "view_cart",
        "cart",
        "view cart",
        "my cart",
        "show cart",
        "show my cart",
    ):
        result = await orchestrator._execute_tool("view_cart", {})
        return orchestrator._format_response_sync(user_message, result)

    # clear cart
    if msg_lower in ("clear cart", "empty cart", "clear my cart", "remove all"):
        cart_res = await orchestrator._execute_tool("view_cart", {})
        if isinstance(cart_res, dict) and "items" in cart_res:
            for item in cart_res["items"]:
                pid = item.get("product_id", "")
                if pid:
                    await orchestrator._execute_tool(
                        "remove_from_cart", {"product_id": pid}
                    )
        return {"type": "response", "text": "🗑️ Cart cleared.", "options": None}

    # view orders keywords
    if msg_lower in (
        "view_orders",
        "orders",
        "view orders",
        "my orders",
        "check my orders",
        "order history",
    ):
        result = await orchestrator._execute_tool("view_orders", {})
        return orchestrator._format_response_sync(user_message, result)

    # addresses
    if msg_lower in (
        "addresses",
        "my addresses",
        "view addresses",
        "list addresses",
        "saved addresses",
    ):
        result = await orchestrator._execute_tool(
            "manage_addresses", {"action": "list"}
        )
        return orchestrator._format_response_sync(user_message, result)

    # facts / preferences
    if msg_lower in (
        "my preferences",
        "my facts",
        "view preferences",
        "preferences",
        "my dietary preferences",
    ):
        result = await orchestrator._execute_tool(
            "manage_facts", {"action": "list", "session_id": session_id}
        )
        return orchestrator._format_response_sync(user_message, result)

    # seller catalog
    if msg_lower in (
        "my products",
        "seller catalog",
        "list my products",
        "view my products",
        "my listings",
    ):
        result = await orchestrator._execute_tool("seller_list_products", {})
        return orchestrator._format_response_sync(user_message, result)

    # fulfillment queue
    if msg_lower in (
        "fulfillment queue",
        "my fulfillment queue",
        "orders to fulfill",
        "pending orders",
        "show fulfillment",
    ):
        result = await orchestrator._execute_tool("list_fulfillment_orders", {})
        return orchestrator._format_response_sync(user_message, result)

    # inventory
    if msg_lower in (
        "inventory",
        "my inventory",
        "show inventory",
        "stock levels",
        "view inventory",
    ):
        result = await orchestrator._execute_tool("inventory_search", {})
        return orchestrator._format_response_sync(user_message, result)

    # theme toggles
    _theme_triggers = (
        "dark mode",
        "light mode",
        "toggle theme",
        "switch theme",
        "night mode",
        "enable dark mode",
        "enable light mode",
        "turn on dark mode",
        "turn on light mode",
    )
    if msg_lower in _theme_triggers or any(kw in msg_lower for kw in _theme_triggers):
        return {"type": "toggle_theme", "text": "Theme toggled.", "options": None}

    # switch_role:<role>  (from role-switch offer button)
    if msg.startswith("switch_role:"):
        role_str = msg[12:].strip()
        result = await orchestrator._execute_tool("switch_role", {"role": role_str})
        return orchestrator._format_response_sync(user_message, result)

    # add_address keyword
    if msg_lower in ("add address", "add_address", "new address"):
        return await orchestrator._start_address_add_flow({}, user_message)

    # ── 2. Fuzzy option matching ─────────────────────────────────────────

    last_options = await get_last_options(session_id)
    if last_options:
        # Only attempt fuzzy matching on short messages (≤ 6 words).
        # Long sentences are queries/questions, not option selections.
        word_count = len(msg.split())
        is_short_message = word_count <= 6

        # Only match if the message doesn't start with a question/list word.
        # These patterns indicate the user is asking, not selecting.
        _query_starters = (
            "show",
            "list",
            "what",
            "which",
            "how",
            "are",
            "is",
            "do",
            "can",
            "nope",
            "no",
            "why",
            "tell",
            "give",
            "find",
            "search",
            "display",
        )
        starts_with_query = (
            msg_lower.split()[0] in _query_starters if msg_lower.split() else False
        )

        if is_short_message and not starts_with_query:
            # 2a. Voice numeric / ordinal index matching ("the first one", "option 2")
            idx = _extract_option_index(msg)
            if idx is not None and 1 <= idx <= len(last_options):
                selected_opt = last_options[idx - 1]
                logger.info(
                    f"[FastPath] Voice index match: '{msg}' → option {idx}: "
                    f"'{selected_opt.get('label', '')}'"
                )
                action_value = _get_option_action(selected_opt)
                if action_value:
                    return await handle(action_value, orchestrator)

            # 2b. Fuzzy text match — only dispatch if the best option has an action
            # (i.e. it's an actionable card like "Add to Cart", not a list item)
            matched = _best_option_match(msg, last_options)
            if matched and _get_option_action(matched):
                logger.info(
                    f"[FastPath] Fuzzy match: '{msg}' → '{matched.get('label', '')}'"
                )
                action_value = _get_option_action(matched)
                if action_value:
                    return await handle(action_value, orchestrator)

    return None


def _get_option_action(opt: dict[str, Any]) -> str | None:
    """Extract the primary action value from an option dict.

    Preference order:
      1. First action in opt["actions"] (e.g. "Add to Cart" → "add_<uuid>")
      2. opt["value"] itself if it starts with a known prefix
      3. None
    """
    actions = opt.get("actions", [])
    if actions:
        return str(actions[0].get("value", ""))
    val = str(opt.get("value", ""))
    # Only dispatch known prefixes as values — don't send raw UUIDs to run_turn
    known_prefixes = (
        "add_",
        "remove_",
        "view_",
        "order_detail_",
        "fulfillment_status_",
        "delete_address_",
        "set_default_address_",
        "update_address_",
        "seller_deactivate_",
        "seller_edit_",
        "delete_fact_",
        "checkout",
        "switch_role:",
        "place_order",
    )
    if any(val.startswith(p) for p in known_prefixes):
        return val
    return None
