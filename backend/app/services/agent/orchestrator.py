import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import UserRole
from app.services.agent.llm import call_llm, extract_json_from_response
from app.services.agent.tools import (
    TOOL_DESCRIPTIONS,
    TOOL_REGISTRY,
    check_tool_permission,
)
from app.services.memory import (
    Mem0,
    append_message_to_session,
    get_redis_client,
    get_session_history,
)

logger = logging.getLogger("app.services.agent.orchestrator")

# Intent classification prompt — kept intentionally lean.
# Parameter docs for address/product creation are omitted here because the
# orchestrator handles slot-filling in Python; the LLM only needs to pick the
# right tool name and extract the handful of simple scalars.
INTENT_PROMPT = """You are a grocery-store AI assistant. Your ONLY job here is to classify the user's intent and extract parameters as JSON.

Available tools for this session:
{tool_descriptions}

User preferences/facts: {facts}
Recent conversation (last 4 turns):
{history}

CLASSIFICATION RULES:
1. Grocery-related requests ALWAYS map to a tool — never mark them out_of_scope.
2. "out_of_scope" is ONLY for topics completely unrelated to groceries/shopping/orders/addresses
   (e.g. sports scores, politics, writing code, general trivia).
3. Pronouns like "them", "it", "those" refer to the most recent products/items in the conversation.
4. "my orders", "past orders", "order history", "transactions", "purchases" → view_orders
5. "add X to cart", "put X in cart", "buy X", "get me X" → add_to_cart
6. "show cart", "what's in my cart" → view_cart
7. "switch to seller", "become seller", "seller mode" → switch_role with role=seller
8. "dark mode", "light mode", "toggle theme" → toggle_theme (special non-tool response)

Return ONLY valid JSON — no markdown, no explanation:
{{
  "tool": "<tool_name> or out_of_scope or toggle_theme",
  "params": {{}},
  "fact_to_remember": null,
  "fact_category": null
}}

Key param rules (only extract what's clearly present — use null otherwise):
- search_products: query, category, min_price, max_price, min_rating, in_stock_only
- add_to_cart / remove_from_cart / update_cart_quantity: product_id (null if unknown), quantity (null if not stated)
- switch_role: role ("customer" or "seller")
- manage_addresses: action ("list"/"add"/"update"/"delete"), address_data (raw address string as "text" field — extraction handled separately)
- get_order_detail: order_id
- seller_create_product: name, description, category, price, stock (null for any not provided)
- seller_update_product: product_id, plus any of name/description/category/price/stock
- seller_delete_product: product_id
- list_fulfillment_orders: status, min_total, max_total, date_from (YYYY-MM-DD), date_to (YYYY-MM-DD)
- update_order_status: order_id, new_status
- inventory_search: stock_filter, min_rating, min_sold, sort_by, category
- All other tools: no params needed

fact_to_remember: only for durable facts (allergy, dietary restriction, strong preference). NOT for one-off purchases.

Output ONLY raw JSON."""

RESPONSE_PROMPT = """You are a friendly grocery shopping assistant. Format the tool execution results into a natural response.

CRITICAL RULES:
- ONLY mention products/data that actually appear in the results below.
- Do NOT invent products, names, or prices.
- If there are 0 results, say so honestly.
- Keep responses concise and helpful.
- NEVER show raw UUIDs or technical identifiers to the user.

CANONICAL ACTION VALUE FORMATS — use these EXACTLY in all "actions" arrays:
  - Add to cart:    "add_<uuid>"          e.g. "add_928a374a-9e34-470b-8aab-86654fde0a9a"
  - View detail:    "view_<uuid>"         e.g. "view_928a374a-9e34-470b-8aab-86654fde0a9a"
  - Order detail:   "order_detail_<uuid>" e.g. "order_detail_358ef3f6-1a46-49a2-9ab5-d3dd3c94b030"
  Never truncate UUIDs. Never use "add_product_id_" or "view_product_id_" prefixes.

User query: {query}
Results: {results}

If the results include product data and making sense, offer structured options for the user to take actions (add to cart, view details).
Each option can have "actions" for quick actions:
{{
  "text": "Your response text",
  "options": [
    {{"label": "Product Name", "value": "<uuid>", "description": "Price info", "actions": [{{"label": "Add to Cart", "value": "add_<uuid>"}}, {{"label": "View Details", "value": "view_<uuid>"}}]}}
  ]
}}

If no options make sense, set options to null.
Output ONLY raw JSON: {{"text": "...", "options": [...] or null}}."""

# Prompt for narrowing down search results (when too_many is returned)
NARROWING_PROMPT = """You are a friendly grocery assistant helping the user narrow down their product search.

The user searched for: "{query}"
We found {count} products. Here are the available categories: {categories}
Price range: ${price_min:.2f} - ${price_max:.2f}
Sample product names: {product_names}

Your task:
1. Analyze these products and decide the best way to help the user narrow down.
2. Generate a response that asks the user to be more specific.
3. Suggest filtering options like category, price range, or product type.
4. You may ask with structured options (e.g., "Which type? Whole milk, Almond milk...") or as a natural question.

Output ONLY raw JSON:
{{
  "text": "Your question to help the user narrow down their search",
  "options": [
    {{"label": "Option Name", "value": "option_value", "description": "Brief description"}}
  ] or null if you want a free-text response
}}"""

# Prompt for asking quantity when not specified
QUANTITY_PROMPT = """You are a friendly grocery assistant. The user wants to add a product to their cart but didn't specify the quantity.

Product: {product_name}

Ask the user how many they would like to add. Keep it brief.

Output ONLY raw JSON:
{{
  "text": "How many {product_name} would you like to add?",
  "options": [
    {{"label": "1", "value": "1", "description": "Single item"}},
    {{"label": "2", "value": "2", "description": "Two items"}},
    {{"label": "3", "value": "3", "description": "Three items"}},
    {{"label": "5", "value": "5", "description": "Five items"}}
  ]
}}"""

# Dedicated small prompt for extracting structured address fields from any free-text input.
# Intentionally minimal — no tool list, no grocery context — just field extraction.
ADDRESS_EXTRACT_PROMPT = """Extract address fields from the text below.
Return ONLY a JSON object with these keys (set to null if not found):
  label        - nickname e.g. "Home", "Work", "Office" (null if not mentioned)
  line1        - street/house/building e.g. "B-63 Street 5, Akshar Residency"
  line2        - apartment/suite/floor (null if not mentioned)
  city         - city or town name
  state        - state or province name
  postal_code  - postal/ZIP/pin code as a string
  country      - country name (default "India" if not mentioned but address seems Indian)

Text: "{address_text}"

Output ONLY raw JSON. No markdown, no explanation."""


def _sanitize_error_message(raw_error: str) -> str:
    """Sanitize error messages to avoid leaking technical details to users."""
    # Common patterns to mask
    error_lower = raw_error.lower()
    if "uuid" in error_lower or "badly formed" in error_lower:
        return "I couldn't find that product. Please search for it first and select from the results."
    if "json" in error_lower or "decode" in error_lower:
        return "I had trouble understanding that. Could you rephrase?"
    if "timeout" in error_lower:
        return "The request took too long. Please try again."
    if "api key" in error_lower or "auth" in error_lower:
        return "I'm having connection issues. Please try again later."
    # Default
    return "Something went wrong. Please try again."


def _build_role_scoped_tool_descs(user_role: UserRole) -> str:
    """Build a tool-description string scoped to what this role can actually use.

    Customer: sees only the 'all' tools (no seller-specific entries).
    Seller: sees 'all' tools + seller tools.
    This keeps the intent-classifier prompt ~40% shorter for customers and
    prevents the model from suggesting seller tools to customer sessions.
    """
    from app.services.agent.tools import (
        ROLE_TOOL_PERMISSIONS,
    )

    allowed: set[str] = set(ROLE_TOOL_PERMISSIONS.get("all", []))
    role_tools = ROLE_TOOL_PERMISSIONS.get(user_role, [])
    allowed.update(role_tools)

    lines = []
    for name, desc in TOOL_DESCRIPTIONS.items():
        if name in allowed:
            lines.append(f"  - {name}: {desc}")
    return "\n".join(lines)


class AgentOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        user_role: UserRole,
    ):
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.user_role = user_role
        self._facts_cache: str | None = None
        self._progress_queue: asyncio.Queue[str] | None = None
        # Narrowing state
        self._narrowing_context: dict[str, Any] | None = None
        # Quantity pending state
        self._pending_quantity_context: dict[str, Any] | None = None
        # Mem0 memory client (bridges to PersistentFact)
        self._mem0: Mem0 | None = None

    async def _get_mem0(self) -> Mem0:
        """Get or create the Mem0 memory client for this session."""
        if self._mem0 is None:
            from app.services.memory import Mem0 as Mem0Client

            self._mem0 = Mem0Client(db=self.db, user_id=self.user_id)
        return self._mem0

    async def _get_facts(self, query: str | None = None) -> str:
        mem0 = await self._get_mem0()
        if query:
            facts = await mem0.search(query=query, limit=3)
        else:
            facts = await mem0.get_all()
        if facts:
            return "; ".join([f["fact_text"] for f in facts])
        return "None"

    async def run_turn(self, user_message: str) -> dict[str, Any]:
        turn_start_time = time.perf_counter()
        logger.info(
            f"AgentOrchestrator starting turn for user {self.user_id}, session {self.session_id}..."
        )

        redis_client = get_redis_client()

        # Check for address collection state from Redis or self
        addr_collect_key = f"chat:session:{self.session_id}:address_collect"
        addr_collect_str = await redis_client.get(addr_collect_key)
        if addr_collect_str:
            collect_ctx = json.loads(addr_collect_str)
            await redis_client.delete(addr_collect_key)
            return await self._handle_address_collect_response(
                user_message, collect_ctx
            )

        # Check for pending address update (user is sending a delta or confirming)
        addr_update_key = f"chat:session:{self.session_id}:address_update_pending"
        addr_update_str = await redis_client.get(addr_update_key)
        if addr_update_str:
            update_ctx = json.loads(addr_update_str)
            await redis_client.delete(addr_update_key)
            response = await self._handle_address_update_response(
                user_message, update_ctx
            )
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response.get("text", "")
            )
            return response

        # Check for pending quantity response from Redis or self
        quantity_key = f"chat:session:{self.session_id}:pending_quantity"
        pending_quantity_str = await redis_client.get(quantity_key)
        if pending_quantity_str:
            self._pending_quantity_context = json.loads(pending_quantity_str)
            await redis_client.delete(quantity_key)
            return await self._handle_quantity_response(user_message)
        if self._pending_quantity_context:
            return await self._handle_quantity_response(user_message)

        # Check for narrowing response from Redis or self
        narrowing_key = f"chat:session:{self.session_id}:narrowing_context"
        narrowing_str = await redis_client.get(narrowing_key)
        if narrowing_str:
            self._narrowing_context = json.loads(narrowing_str)
            await redis_client.delete(narrowing_key)
            return await self._handle_narrowing_response(user_message)
        if self._narrowing_context:
            return await self._handle_narrowing_response(user_message)

        # Check for pending role switch request
        role_switch_key = f"chat:session:{self.session_id}:pending_role_switch"
        role_switch_str = await redis_client.get(role_switch_key)
        if role_switch_str:
            role_switch_data = json.loads(role_switch_str)
            # Check if user is confirming the role switch
            msg_lower = user_message.strip().lower()
            is_confirm = msg_lower in (
                "yes",
                "sure",
                "ok",
                "do it",
                "proceed",
                "confirm",
                "yeah",
                "yep",
            )
            is_deny = msg_lower in (
                "no",
                "stop",
                "cancel",
                "never mind",
                "don't",
                "dont",
                "nah",
            )

            # Also check for structured option value
            if user_message.startswith("switch_role:"):
                is_confirm = True
                needed_role = user_message.split("switch_role:")[1].strip()
                role_switch_data["needed_role"] = needed_role

            if is_confirm:
                await redis_client.delete(role_switch_key)
                needed_role = role_switch_data.get("needed_role", "seller")
                # Use switch_role tool to change the user's role in DB
                switch_result = await self._execute_tool(
                    "switch_role", {"role": needed_role}
                )
                if isinstance(switch_result, dict) and switch_result.get("success"):
                    # Update the orchestrator's cached role
                    with contextlib.suppress(ValueError):
                        self.user_role = UserRole(needed_role)
                    # Retry the original tool
                    tool_name = role_switch_data.get("tool_name", "")
                    original_message = role_switch_data.get("original_message", "")
                    if tool_name:
                        result = await self._execute_tool(tool_name, {})
                        response = await self._format_response(original_message, result)
                        response["text"] = (
                            f"Role switched to '{needed_role}'. "
                            + response.get("text", "")
                        )
                        return response
                return {
                    "type": "response",
                    "text": f"Switched to '{needed_role}' role. How can I help?",
                    "options": None,
                }

            if is_deny:
                await redis_client.delete(role_switch_key)
                return {
                    "type": "response",
                    "text": "No problem. Please ask for something else.",
                    "options": None,
                }
            # Fall through for other messages
            await redis_client.delete(role_switch_key)

        # Check for pending permission action
        pending_key = f"chat:session:{self.session_id}:pending_action"
        pending_data_str = await redis_client.get(pending_key)

        if pending_data_str:
            pending_data = json.loads(pending_data_str)
            # Check if user is confirming via simple keyword
            msg_lower = user_message.strip().lower()
            is_confirm = msg_lower in (
                "yes",
                "sure",
                "ok",
                "do it",
                "proceed",
                "confirm",
                "yeah",
                "yep",
                "approve",
            )
            is_deny = msg_lower in (
                "no",
                "stop",
                "cancel",
                "never mind",
                "don't",
                "dont",
                "nah",
            )

            if is_confirm:
                await redis_client.delete(pending_key)
                result = await self._execute_tool(
                    pending_data["action_type"],
                    {
                        "product_id": pending_data.get("product_id", ""),
                        "quantity": pending_data.get("quantity", 1),
                    },
                )
                return await self._format_response(user_message, result)

            if is_deny:
                await redis_client.delete(pending_key)
                await append_message_to_session(
                    str(self.session_id), "user", user_message
                )
                await append_message_to_session(
                    str(self.session_id), "assistant", "Cancelled."
                )
                return {
                    "type": "response",
                    "text": "Cancelled that action.",
                    "options": None,
                }

            # Fall through for other messages
            await redis_client.delete(pending_key)

        # Check for pending seller_create_product slot-fill
        seller_partial_key = f"chat:session:{self.session_id}:seller_create_partial"
        seller_partial_str = await redis_client.get(seller_partial_key)
        if seller_partial_str:
            # User is responding to a slot-fill prompt — route directly to merger
            response = await self._handle_seller_create_followup(user_message)
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response.get("text", "")
            )
            return response

        # Check for deterministic fast path (0ms LLM bypass for button clicks and direct commands)
        fast_result = await self._check_fast_path(user_message)
        if fast_result is not None:
            total_time = time.perf_counter() - turn_start_time
            logger.info(
                f"[FAST PATH] Executed turn in {total_time:.4f}s without LLM call!"
            )
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", fast_result.get("text", "")
            )
            return fast_result

        # Step 1: Classify intent + extract params (single LLM call)
        step_start = time.perf_counter()
        facts_str = await self._get_facts(user_message)
        history = await get_session_history(str(self.session_id))
        history_str = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in history[-4:]]
        )

        tool_descs = _build_role_scoped_tool_descs(self.user_role)

        intent_response = await call_llm(
            system_prompt="You are a precise intent classifier.",
            user_prompt=INTENT_PROMPT.format(
                tool_descriptions=tool_descs,
                facts=facts_str,
                history=history_str,
            )
            + f"\n\nUser message: '{user_message}'",
            temperature=0.0,
            max_tokens=512,
            call_type="intent_classifier",
        )

        # Handle empty/error intent response
        if not intent_response:
            return {
                "type": "response",
                "text": "I had trouble understanding that. Could you rephrase your request?",
                "options": None,
            }

        # Safely parse intent JSON
        try:
            extracted = extract_json_from_response(intent_response)
            intent_data = json.loads(extracted)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                f"Failed to parse intent response: {e}. Response was: '{intent_response[:200]}'"
            )
            # Retry once
            intent_response_retry = await call_llm(
                system_prompt="You are a precise intent classifier. Output ONLY valid JSON.",
                user_prompt=INTENT_PROMPT.format(
                    tool_descriptions=tool_descs,
                    facts=facts_str,
                    history=history_str,
                )
                + f"\n\nUser message: '{user_message}'",
                temperature=0.0,
                max_tokens=512,
                call_type="intent_classifier_retry",
            )
            if intent_response_retry:
                try:
                    extracted = extract_json_from_response(intent_response_retry)
                    intent_data = json.loads(extracted)
                except (json.JSONDecodeError, ValueError):
                    return {
                        "type": "response",
                        "text": "I had trouble understanding that. Could you rephrase?",
                        "options": None,
                    }
            else:
                return {
                    "type": "response",
                    "text": "I had trouble understanding that. Could you rephrase?",
                    "options": None,
                }

        selected_tool = intent_data.get("tool", "out_of_scope")
        params = intent_data.get("params", {})
        fact_to_remember = intent_data.get("fact_to_remember")
        fact_category = intent_data.get("fact_category")

        logger.info(
            f"[TIMING] Step 1: Intent classification - Time: {time.perf_counter() - step_start:.4f}s (tool: {selected_tool})"
        )

        # Handle toggle_theme — pure client-side action, no DB needed
        if selected_tool == "toggle_theme":
            await append_message_to_session(str(self.session_id), "user", user_message)
            response = {
                "type": "toggle_theme",
                "text": "Theme toggled.",
                "options": None,
            }
            await append_message_to_session(
                str(self.session_id), "assistant", response["text"]
            )
            return response

        # Handle out of scope dynamically
        if selected_tool == "out_of_scope":
            out_prompt = (
                f"The user said: '{user_message}'. "
                "You are GroceryGenie, a friendly AI grocery shopping assistant. "
                "Briefly acknowledge what the user said in 1 warm sentence, then politely offer to help them find groceries, manage their cart, or check orders."
            )
            response_text = await call_llm(
                system_prompt="You are GroceryGenie, a helpful grocery shopping assistant.",
                user_prompt=out_prompt,
                temperature=0.3,
                max_tokens=150,
                call_type="out_of_scope_response",
            )
            if not response_text or not response_text.strip():
                response_text = "I'm your GroceryGenie shopping assistant! I can help you find products, manage your cart, check orders, or manage addresses. How can I help you today?"
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response_text
            )
            return {"type": "response", "text": response_text.strip(), "options": None}

        # Store fact if found
        if (
            fact_to_remember
            and isinstance(fact_to_remember, str)
            and fact_to_remember.strip()
        ):
            await self._store_fact(fact_to_remember, fact_category)

        # RBAC check: verify user has permission for the selected tool
        if selected_tool != "out_of_scope":
            try:
                check_tool_permission(selected_tool, self.user_role)
            except ValueError:
                # Unknown tool name — LLM hallucinated something not in the registry.
                # Return a graceful error; do NOT trigger the role-switch dialog.
                logger.warning(
                    f"LLM returned unknown tool name '{selected_tool}' — not in TOOL_REGISTRY"
                )
                return {
                    "type": "response",
                    "text": "I'm not sure how to do that. Could you rephrase your request?",
                    "options": None,
                }
            except PermissionError as e:
                # Tool exists but user's role lacks permission → offer role switch
                err_str = str(e)
                needed_role = "seller"
                if "requires '" in err_str:
                    needed_role = err_str.split("requires '")[1].split("'", maxsplit=1)[
                        0
                    ]
                return await self._handle_role_switch_request(
                    user_message, selected_tool, needed_role
                )

        # Handle quantity-pending for add_to_cart
        if selected_tool == "add_to_cart":
            quantity = params.get("quantity")
            if quantity is None:
                # User didn't specify quantity, need to ask
                product_id = params.get("product_id", "")
                return await self._ask_for_quantity(product_id, user_message)

        # Handle missing product_id for update_cart_quantity or remove_from_cart
        if selected_tool in ("update_cart_quantity", "remove_from_cart"):
            pid = params.get("product_id")
            if not pid:
                # Fetch cart items and show a product picker card
                cart_res = await self._execute_tool("view_cart", {})
                if (
                    isinstance(cart_res, dict)
                    and "items" in cart_res
                    and cart_res["items"]
                ):
                    options = []
                    for item in cart_res["items"]:
                        item_pid = item.get("product_id", "")
                        item_name = item.get("name", "")
                        if item_pid:
                            options.append(
                                {
                                    "label": item_name,
                                    "value": item_pid,
                                    "description": f"Currently {item.get('quantity', 1)} in cart",
                                    "actions": [
                                        {
                                            "label": "Update Quantity"
                                            if selected_tool == "update_cart_quantity"
                                            else "Remove",
                                            "value": f"add_{item_pid}"
                                            if selected_tool == "update_cart_quantity"
                                            else f"remove_{item_pid}",
                                        }
                                    ],
                                }
                            )
                    action_label = (
                        "update the quantity for"
                        if selected_tool == "update_cart_quantity"
                        else "remove"
                    )
                    return {
                        "type": "options_response",
                        "text": f"Which item in your cart would you like to {action_label}?",
                        "options": options,
                        "free_input_allowed": True,
                    }
                return {
                    "type": "response",
                    "text": "Your cart is currently empty.",
                    "options": None,
                }

        # Handle address collection slot filling for manage_addresses
        if selected_tool == "manage_addresses":
            action = params.get("action", "list")
            if action == "add":
                addr_data = params.get("address_data") or {}
                # Always route through _start_address_collect_flow — it runs the
                # extractor first and only asks for genuinely missing fields
                return await self._start_address_collect_flow(addr_data, user_message)
            if action == "update" and not params.get("address_id"):
                # No address_id given — show list so user can pick one
                list_result = await self._execute_tool(
                    "manage_addresses", {"action": "list"}
                )
                if isinstance(list_result, dict) and list_result.get("addresses"):
                    addr_list = list_result["addresses"]
                    options = [
                        {
                            "label": a.get("label", "Home"),
                            "value": f"update_address_{a['id']}",
                            "description": f"{a.get('line1', '')}, {a.get('city', '')}",
                        }
                        for a in addr_list
                    ]
                    return {
                        "type": "options_response",
                        "text": "Which address would you like to update?",
                        "options": options,
                        "free_input_allowed": False,
                    }
                return {
                    "type": "response",
                    "text": "You have no saved addresses yet.",
                    "options": None,
                }

        # Handle seller_create_product — slot-fill all required fields before hitting DB
        if selected_tool == "seller_create_product":
            return await self._handle_seller_create_slot_fill(params, user_message)

        # Step 2: Execute tool
        step_start = time.perf_counter()
        result = await self._execute_tool(selected_tool, params)
        logger.info(
            f"[TIMING] Step 2: Tool execution ({selected_tool}) - Time: {time.perf_counter() - step_start:.4f}s"
        )

        # Check if search returned too_many results (narrowing needed)
        if isinstance(result, dict) and result.get("too_many"):
            return await self._handle_too_many_results(result, user_message)

        # Step 3: Format response
        step_start = time.perf_counter()
        response = await self._format_response(user_message, result)
        logger.info(
            f"[TIMING] Step 3: Response formatting - Time: {time.perf_counter() - step_start:.4f}s"
        )

        # Store in session
        await append_message_to_session(str(self.session_id), "user", user_message)
        await append_message_to_session(
            str(self.session_id), "assistant", response.get("text", "")
        )

        total_time = time.perf_counter() - turn_start_time
        logger.info(f"[TIMING] Total turn execution time: {total_time:.4f}s")

        return response

    async def _ask_for_quantity(
        self, product_id: str, original_query: str
    ) -> dict[str, Any]:
        """Ask the user how many of the product they want to add."""
        # Try to look up the product name
        product_name = "this item"
        if product_id and product_id != "":
            try:
                from uuid import UUID

                from sqlalchemy import select

                from app.db.models.product import Product

                product_uuid = UUID(product_id)
                p_res = await self.db.execute(
                    select(Product).where(Product.id == product_uuid)
                )
                product = p_res.scalar_one_or_none()
                if product:
                    product_name = product.name
            except (ValueError, Exception):
                pass

        # Store context for when user responds with quantity
        q_ctx = {
            "product_id": product_id,
            "original_query": original_query,
            "product_name": product_name,
        }
        self._pending_quantity_context = q_ctx
        redis_client = get_redis_client()
        await redis_client.set(
            f"chat:session:{self.session_id}:pending_quantity",
            json.dumps(q_ctx),
            ex=300,
        )

        # Zero-LLM: build quantity card directly in Python
        return {
            "type": "options_response",
            "text": f"How many {product_name} would you like to add?",
            "options": [
                {"label": "1", "value": "1", "description": "Single item"},
                {"label": "2", "value": "2", "description": "Two items"},
                {"label": "3", "value": "3", "description": "Three items"},
                {"label": "5", "value": "5", "description": "Five items"},
            ],
            "free_input_allowed": True,
        }

    async def _handle_quantity_response(self, user_message: str) -> dict[str, Any]:
        """Handle user's response to quantity question."""
        context = self._pending_quantity_context
        self._pending_quantity_context = None
        assert context is not None  # nosec: type guard for mypy

        product_id = context["product_id"]
        original_query = context["original_query"]

        # Try to parse the user's response as a number
        quantity = 1
        try:
            # Extract numeric value from the message
            numbers = re.findall(r"\d+", user_message.strip())
            if numbers:
                quantity = int(numbers[0])
                if quantity < 1:
                    quantity = 1
                elif quantity > 100:
                    quantity = 100
        except (ValueError, IndexError):
            quantity = 1

        # Execute add_to_cart with the specified quantity
        result = await self._execute_tool(
            "add_to_cart",
            {
                "product_id": product_id,
                "quantity": quantity,
            },
        )

        return await self._format_response(original_query, result)

    async def _handle_too_many_results(
        self, result: dict[str, Any], original_query: str
    ) -> dict[str, Any]:
        """Handle too many search results by asking user to narrow down."""
        # Store narrowing context for when user responds
        n_ctx = {
            "original_query": original_query,
            "categories": result.get("categories", []),
            "price_range": result.get("price_range", {}),
            "product_names": result.get("product_names", []),
            "count": result.get("count", 0),
        }
        self._narrowing_context = n_ctx
        redis_client = get_redis_client()
        await redis_client.set(
            f"chat:session:{self.session_id}:narrowing_context",
            json.dumps(n_ctx),
            ex=300,
        )

        # Zero-LLM: build narrowing card directly in Python
        count = result.get("count", 0)
        categories = result.get("categories", [])
        price_range = result.get("price_range", {})
        price_min = price_range.get("min", 0)
        price_max = price_range.get("max", 0)

        options: list[dict[str, Any]] = []
        # Category quick-filter chips
        for cat in categories[:6]:
            options.append(
                {
                    "label": cat.title(),
                    "value": f"category:{cat}",
                    "description": "Filter by category",
                }
            )
        # Price range chips
        if price_max > 0:
            mid = (price_min + price_max) / 2
            options.append(
                {
                    "label": f"Under ${mid:.0f}",
                    "value": f"max_price:{mid:.2f}",
                    "description": "Budget friendly",
                }
            )
            options.append(
                {
                    "label": f"${mid:.0f} – ${price_max:.0f}",
                    "value": f"min_price:{mid:.2f}",
                    "description": "Premium range",
                }
            )

        return {
            "type": "options_response",
            "text": f"I found {count} products matching your search. Which type are you looking for?",
            "options": options or None,
            "free_input_allowed": True,
        }

    async def _handle_narrowing_response(self, user_message: str) -> dict[str, Any]:
        """Handle user's narrowing response by doing a refined search."""
        context = self._narrowing_context
        self._narrowing_context = None
        assert context is not None  # nosec: type guard for mypy

        original_query = context["original_query"]

        # Parse structured chip values (category:X / max_price:X / min_price:X)
        tool_params: dict[str, Any] = {"query": original_query}
        if user_message.startswith("category:"):
            tool_params["category"] = user_message.split("category:", 1)[1].strip()
        elif user_message.startswith("max_price:"):
            with contextlib.suppress(ValueError):
                tool_params["max_price"] = float(
                    user_message.split("max_price:", 1)[1].strip()
                )
        elif user_message.startswith("min_price:"):
            with contextlib.suppress(ValueError):
                tool_params["min_price"] = float(
                    user_message.split("min_price:", 1)[1].strip()
                )
        else:
            # Plain text: append to query
            tool_params["query"] = f"{original_query} {user_message}".strip()

        # Re-run the search with refined params
        result = await self._execute_tool("search_products", tool_params)

        # If still too many results, ask to narrow down again
        if isinstance(result, dict) and result.get("too_many"):
            return await self._handle_too_many_results(result, original_query)

        # Format final result
        response = await self._format_response(user_message, result)

        # Store in session
        await append_message_to_session(str(self.session_id), "user", user_message)
        await append_message_to_session(
            str(self.session_id), "assistant", response.get("text", "")
        )

        return response

    async def _extract_address_fields(self, text: str) -> dict[str, Any]:
        """Call the dedicated ADDRESS_EXTRACT_PROMPT to parse any free-text address.
        Returns a dict of extracted fields (values may be None if not found).
        """
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
            # Strip None values so they don't overwrite valid collected data
            return {
                k: v for k, v in extracted.items() if v is not None and str(v).strip()
            }
        except (json.JSONDecodeError, ValueError):
            return {}

    async def _start_address_update_flow(self, address_id: str) -> dict[str, Any]:
        """Initiate address update: fetch current data, store in Redis, ask what to change."""
        from uuid import UUID

        from sqlalchemy import select

        from app.db.models.address import Address

        try:
            addr_uuid = UUID(address_id)
            a_res = await self.db.execute(
                select(Address).where(
                    Address.id == addr_uuid,
                    Address.user_id == self.user_id,
                )
            )
            address = a_res.scalar_one_or_none()
            if not address:
                return {
                    "type": "response",
                    "text": "Address not found.",
                    "options": None,
                }

            current = {
                "label": address.label,
                "line1": address.line1,
                "line2": address.line2 or "",
                "city": address.city,
                "state": address.state,
                "postal_code": address.postal_code,
                "country": address.country,
            }

            redis_client = get_redis_client()
            ctx = {"address_id": address_id, "current": current}
            await redis_client.set(
                f"chat:session:{self.session_id}:address_update_pending",
                json.dumps(ctx),
                ex=300,
            )

            lines = [f"**{address.label}** — current details:"]
            lines.append(f"  Street: {address.line1}")
            if address.line2:
                lines.append(f"  Line 2: {address.line2}")
            lines.append(f"  City: {address.city}")
            lines.append(f"  State: {address.state}")
            lines.append(f"  Postal code: {address.postal_code}")
            lines.append(f"  Country: {address.country}")
            lines.append(
                "\nWhat would you like to change? "
                "e.g. 'street to 45 Main St' or 'city to Surat, pin 395001'"
            )
            return {"type": "response", "text": "\n".join(lines), "options": None}

        except Exception as e:
            logger.warning(f"_start_address_update_flow failed: {e}")
            return {
                "type": "response",
                "text": "I couldn't find that address.",
                "options": None,
            }

    async def _handle_address_update_response(
        self, user_message: str, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle user's delta message for address update.

        Flow:
          1. Run ADDRESS_EXTRACT_PROMPT on the user message to find changed fields.
          2. Merge into current address data.
          3. Show a confirmation card with the proposed changes.
          4. On confirm → write to DB. On deny → cancel.
        """
        redis_client = get_redis_client()
        confirm_key = f"chat:session:{self.session_id}:address_update_confirm"

        # Check if this is a confirm/deny response to the confirmation card
        confirm_ctx_str = await redis_client.get(confirm_key)
        if confirm_ctx_str:
            confirm_ctx = json.loads(confirm_ctx_str)
            msg_lower = user_message.strip().lower()
            is_confirm = (
                msg_lower
                in (
                    "yes",
                    "confirm",
                    "sure",
                    "ok",
                    "do it",
                    "proceed",
                    "yeah",
                    "yep",
                    "confirm_address_update",
                )
                or user_message.strip() == "confirm_address_update"
            )
            is_deny = msg_lower in (
                "no",
                "cancel",
                "stop",
                "never mind",
                "nah",
                "dont",
                "don't",
            )

            if is_confirm:
                await redis_client.delete(confirm_key)
                result = await self._execute_tool(
                    "manage_addresses",
                    {
                        "action": "update",
                        "address_id": confirm_ctx["address_id"],
                        "address_data": confirm_ctx["updated"],
                    },
                )
                return await self._format_response("update address", result)

            if is_deny:
                await redis_client.delete(confirm_key)
                return {
                    "type": "response",
                    "text": "Address update cancelled.",
                    "options": None,
                }

            # Not a yes/no — treat as a new delta and re-extract
            await redis_client.delete(confirm_key)
            # Fall through to extraction below with current as base
            ctx = {
                "address_id": confirm_ctx["address_id"],
                "current": confirm_ctx["updated"],
            }

        # Extract changed fields from user message
        delta = await self._extract_address_fields(user_message)

        if not delta:
            # Nothing extracted — ask again
            return {
                "type": "response",
                "text": (
                    "I couldn't extract any address fields from that. "
                    "Please try again, e.g. 'change street to 45 Main St' or 'update pin to 395001'."
                ),
                "options": None,
            }

        # Merge delta onto current
        current = ctx.get("current", {})
        updated = {**current, **delta}

        # Build a human-readable diff of what changed
        changes = []
        field_labels = {
            "label": "Label",
            "line1": "Street",
            "line2": "Line 2",
            "city": "City",
            "state": "State",
            "postal_code": "Postal code",
            "country": "Country",
        }
        for field, new_val in delta.items():
            old_val = current.get(field, "")
            if str(old_val) != str(new_val):
                changes.append(
                    f"  **{field_labels.get(field, field)}**: {old_val or '(empty)'} → {new_val}"
                )

        if not changes:
            return {
                "type": "response",
                "text": "The values you provided match what's already saved. No changes needed.",
                "options": None,
            }

        # Store confirmation context in Redis
        confirm_ctx_data = {
            "address_id": ctx["address_id"],
            "current": current,
            "updated": updated,
        }
        await redis_client.set(confirm_key, json.dumps(confirm_ctx_data), ex=300)

        changes_text = "\n".join(changes)
        return {
            "type": "options_response",
            "text": f"I'll make these changes:\n{changes_text}\n\nConfirm?",
            "options": [
                {
                    "label": "✅ Yes, update",
                    "value": "confirm_address_update",
                    "description": "Save the changes",
                },
                {
                    "label": "❌ Cancel",
                    "value": "cancel",
                    "description": "Keep existing address",
                },
            ],
            "free_input_allowed": True,
        }

    async def _start_address_collect_flow(
        self, initial_data: dict[str, Any], user_message: str
    ) -> dict[str, Any]:
        """Start multi-turn slot filling for adding a new address.

        Uses ADDRESS_EXTRACT_PROMPT first to parse whatever the user already
        provided, then only asks for genuinely missing required fields.
        """
        from app.services.agent.tools.address_tools import _normalize_address_data

        # First pass: normalize any aliased keys already in initial_data
        norm = _normalize_address_data(initial_data)

        # Second pass: if user_message looks like a full address string, run extractor on it
        # (happens when LLM passes the raw address text in address_data without parsing it)
        full_text_fields = ("address", "full_address", "raw", "text")
        raw_text = next(
            (initial_data.get(k) for k in full_text_fields if initial_data.get(k)), None
        )
        if raw_text or (len(user_message) > 20 and not norm.get("line1")):
            extract_text = raw_text or user_message
            extracted = await self._extract_address_fields(extract_text)
            # Merge: extractor wins over raw norm for any key it found
            norm = {**norm, **extracted}

        # Build collected from whatever is now resolved
        collected: dict[str, Any] = {}
        for k in ("label", "line1", "line2", "city", "state", "postal_code", "country"):
            if norm.get(k):
                collected[k] = norm[k]

        required = ["label", "line1", "city", "state", "postal_code"]
        missing = [slot for slot in required if slot not in collected]

        ctx = {
            "collected": collected,
            "missing": missing,
            "original_query": user_message,
        }

        return await self._prompt_next_address_slot(ctx)

    async def _prompt_next_address_slot(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Prompt for the next missing slot in address collection."""
        missing = ctx.get("missing", [])
        collected = ctx.get("collected", {})

        if not missing:
            # All required slots collected! Execute tool directly
            result = await self._execute_tool(
                "manage_addresses",
                {"action": "add", "address_data": collected},
            )
            return await self._format_response(ctx.get("original_query", ""), result)

        # Save dialogue state in Redis (5 min TTL)
        redis_client = get_redis_client()
        await redis_client.set(
            f"chat:session:{self.session_id}:address_collect",
            json.dumps(ctx),
            ex=300,
        )

        next_slot = missing[0]
        prompts: dict[str, tuple[str, list[dict[str, Any]] | None]] = {
            "label": (
                "What label would you like for this address? (e.g. Home, Work, Office)",
                [
                    {
                        "label": "Home 🏠",
                        "value": "Home",
                        "description": "Primary residence",
                    },
                    {
                        "label": "Work 💼",
                        "value": "Work",
                        "description": "Office or workplace",
                    },
                    {
                        "label": "Other 📍",
                        "value": "Other",
                        "description": "Custom label",
                    },
                ],
            ),
            "line1": ("What is your street address (Line 1)?", None),
            "city": ("Which city is this address located in?", None),
            "state": ("Which state is this in?", None),
            "postal_code": ("What is your postal / zip code?", None),
        }

        text_prompt, options = prompts.get(
            next_slot, (f"Please provide your {next_slot}:", None)
        )
        return {
            "type": "options_response" if options else "response",
            "text": text_prompt,
            "options": options,
            "free_input_allowed": True,
        }

    async def _handle_address_collect_response(
        self, user_message: str, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        """Ingest user input into current missing address slot and continue."""
        val = user_message.strip()
        missing = ctx.get("missing", [])
        collected = ctx.get("collected", {})

        if missing:
            current_slot = missing.pop(0)
            collected[current_slot] = val
            ctx["collected"] = collected
            ctx["missing"] = missing

        return await self._prompt_next_address_slot(ctx)

    async def _handle_role_switch_request(
        self, user_message: str, tool_name: str, needed_role: str
    ) -> dict[str, Any]:
        """Handle a request to use a tool that requires a different role.
        Asks the user if they want to switch roles, then retries the tool.
        """
        logger.info(
            f"Role switch needed: user needs '{needed_role}' role for tool '{tool_name}'. "
            f"Current role: {self.user_role}"
        )

        # Store the pending action in Redis so we can retry after role switch
        redis_client = get_redis_client()
        pending_key = f"chat:session:{self.session_id}:pending_role_switch"
        pending_data = {
            "tool_name": tool_name,
            "original_message": user_message,
            "needed_role": needed_role,
        }
        await redis_client.set(pending_key, json.dumps(pending_data), ex=300)
        await append_message_to_session(str(self.session_id), "user", user_message)

        role_display = {
            "seller": "a seller",
            "customer": "a customer",
        }
        needed_display = role_display.get(needed_role, f"'{needed_role}'")
        current_role_name = (
            self.user_role.value
            if hasattr(self.user_role, "value")
            else str(self.user_role)
        )

        return {
            "type": "role_switch_request",
            "text": (
                f"This action ({tool_name}) requires you to be {needed_display}. "
                f"Your current role is '{current_role_name}'. "
                "Would you like to switch role?"
            ),
            "summary": (
                f"switch to '{needed_role}' role to {tool_name.replace('_', ' ')}"
            ),
            "options": [
                {
                    "label": f"Yes, switch to {needed_role}",
                    "value": f"switch_role:{needed_role}",
                    "description": "Change role and retry",
                },
                {
                    "label": "No, cancel",
                    "value": "cancel",
                    "description": "Stay as current role",
                },
            ],
            "free_input_allowed": False,
            "needed_role": needed_role,
            "original_tool": tool_name,
        }

    async def _store_fact(self, fact_text: str, fact_category: str | None) -> None:
        """Store a persistent fact for the user using Mem0 bridge."""
        try:
            mem0 = await self._get_mem0()
            category = fact_category if fact_category else "other"
            await mem0.add(text=fact_text.strip(), category=category)
            self._facts_cache = None
        except Exception as e:
            logger.warning(f"Failed to store fact via Mem0: {e}")

    async def _check_fast_path(self, user_message: str) -> dict[str, Any] | None:
        """Deterministically check if message can be handled in 0ms without an LLM call."""
        msg = user_message.strip()
        msg_lower = msg.lower()

        # 1. Handle add_<product_id>
        if msg.startswith("add_"):
            pid = msg.replace("add_", "").strip()
            if pid:
                result = await self._execute_tool(
                    "add_to_cart", {"product_id": pid, "quantity": 1}
                )
                return await self._format_response(user_message, result)

        # 2. Handle remove_<product_id>
        if msg.startswith("remove_"):
            pid = msg.replace("remove_", "").strip()
            if pid:
                result = await self._execute_tool(
                    "remove_from_cart", {"product_id": pid}
                )
                return await self._format_response(user_message, result)

        # 3. Handle view_<product_id>  ── canonical prefix
        #    Also handle legacy view_product_id_<uuid> the LLM used to emit
        if msg.startswith("view_product_id_") or (
            msg.startswith("view_")
            and not msg.startswith("view_cart")
            and not msg.startswith("view_orders")
            and not msg.startswith("view_facts")
        ):
            # Strip either prefix to get the raw UUID
            if msg.startswith("view_product_id_"):
                pid = msg.replace("view_product_id_", "").strip()
            else:
                pid = msg.replace("view_", "").strip()
            if pid:
                try:
                    from uuid import UUID

                    from sqlalchemy import select

                    from app.db.models.product import Product

                    product_uuid = UUID(pid)
                    p_res = await self.db.execute(
                        select(Product).where(Product.id == product_uuid)
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
                                    "description": f"${float(product.price):.2f} • Stock: {product.stock} • ⭐ {float(product.avg_rating):.1f}",
                                    "actions": [
                                        {
                                            "label": "Add to Cart",
                                            "value": f"add_{product.id}",
                                        }
                                    ],
                                }
                            ],
                            "free_input_allowed": True,
                        }
                except Exception:
                    pass  # nosec: B110 — UUID lookup failure is non-critical

        # 4. Handle delete_address_<uuid>
        if msg.startswith("delete_address_"):
            aid = msg.replace("delete_address_", "").strip()
            if aid:
                result = await self._execute_tool(
                    "manage_addresses", {"action": "delete", "address_id": aid}
                )
                return await self._format_response(user_message, result)

        # 5. Handle set_default_address_<uuid>
        if msg.startswith("set_default_address_"):
            aid = msg.replace("set_default_address_", "").strip()
            if aid:
                result = await self._execute_tool(
                    "manage_addresses",
                    {
                        "action": "update",
                        "address_id": aid,
                        "address_data": {"is_default": True},
                    },
                )
                return await self._format_response(user_message, result)

        # 6. Handle seller_deactivate_<uuid>
        if msg.startswith("seller_deactivate_"):
            pid = msg.replace("seller_deactivate_", "").strip()
            if pid:
                result = await self._execute_tool(
                    "seller_delete_product", {"product_id": pid}
                )
                return await self._format_response(user_message, result)

        # 6b. Handle update_address_<uuid>  ── start address-update flow
        if msg.startswith("update_address_"):
            aid = msg.replace("update_address_", "").strip()
            if aid:
                return await self._start_address_update_flow(aid)

        # 6c. Handle order_detail_<uuid>  ── view a specific order
        if msg.startswith("order_detail_"):
            oid = msg.replace("order_detail_", "").strip()
            if oid:
                result = await self._execute_tool("get_order_detail", {"order_id": oid})
                return await self._format_response(user_message, result)

        # 6d. Handle fulfillment_status_<order_id>_<new_status>
        if msg.startswith("fulfillment_status_"):
            # Format: fulfillment_status_<uuid>_<status>
            # UUID is 36 chars; after prefix, split at position 36+1
            remainder = msg.replace("fulfillment_status_", "").strip()
            if len(remainder) > 37 and remainder[36] == "_":
                order_id = remainder[:36]
                new_status = remainder[37:]
                result = await self._execute_tool(
                    "update_order_status",
                    {"order_id": order_id, "new_status": new_status},
                )
                return await self._format_response(user_message, result)

        # 7. Handle direct view_cart / cart / my cart
        if msg_lower in (
            "view_cart",
            "cart",
            "view cart",
            "my cart",
            "show cart",
            "show my cart",
        ):
            result = await self._execute_tool("view_cart", {})
            return await self._format_response(user_message, result)

        # 8. Handle clear cart
        if msg_lower in ("clear cart", "empty cart", "clear my cart", "remove all"):
            result = await self._execute_tool("view_cart", {})
            if isinstance(result, dict) and "items" in result:
                for item in result["items"]:
                    pid = item.get("product_id", "")
                    if pid:
                        await self._execute_tool(
                            "remove_from_cart", {"product_id": pid}
                        )
                return {"type": "response", "text": "🗑️ Cart cleared.", "options": None}

        # 9. Handle direct view_orders / orders / my orders
        if msg_lower in (
            "view_orders",
            "orders",
            "view orders",
            "my orders",
            "check my orders",
            "order history",
        ):
            result = await self._execute_tool("view_orders", {})
            return await self._format_response(user_message, result)

        # 10. Handle direct addresses / my addresses
        if msg_lower in (
            "addresses",
            "my addresses",
            "view addresses",
            "list addresses",
            "saved addresses",
        ):
            result = await self._execute_tool("manage_addresses", {"action": "list"})
            return await self._format_response(user_message, result)

        # 11. Handle my preferences / facts
        if msg_lower in (
            "my preferences",
            "my facts",
            "view preferences",
            "preferences",
            "my dietary preferences",
        ):
            result = await self._execute_tool("view_facts", {})
            return await self._format_response(user_message, result)

        # 12. Handle seller catalog / my products
        if msg_lower in (
            "my products",
            "seller catalog",
            "list my products",
            "view my products",
            "my listings",
        ):
            result = await self._execute_tool("seller_list_products", {})
            return await self._format_response(user_message, result)

        # 13. Handle fulfillment queue shortcut
        if msg_lower in (
            "fulfillment queue",
            "my fulfillment queue",
            "orders to fulfill",
            "pending orders",
            "show fulfillment",
        ):
            result = await self._execute_tool("list_fulfillment_orders", {})
            return await self._format_response(user_message, result)

        # 14. Handle inventory shortcut
        if msg_lower in (
            "inventory",
            "my inventory",
            "show inventory",
            "stock levels",
            "view inventory",
        ):
            result = await self._execute_tool("inventory_search", {})
            return await self._format_response(user_message, result)

        # 15. Handle direct checkout / place order
        if msg_lower in ("place_order", "checkout", "place order", "buy now"):
            result = await self._execute_tool("place_order", {})
            return await self._format_response(user_message, result)

        # 16. Handle theme toggle keywords — pure client-side, zero LLM or DB
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
        if msg_lower in _theme_triggers or any(
            kw in msg_lower for kw in _theme_triggers
        ):
            return {"type": "toggle_theme", "text": "Theme toggled.", "options": None}

        return None

    async def _handle_seller_create_slot_fill(
        self,
        params: dict[str, Any],
        user_message: str,
    ) -> dict[str, Any]:
        """Slot-fill required fields for seller_create_product.

        Checks what the LLM already extracted, identifies missing required fields,
        and either executes immediately (all present) or asks for all missing fields
        in a single message and stores partial data in Redis.
        """
        redis_client = get_redis_client()
        partial_key = f"chat:session:{self.session_id}:seller_create_partial"

        # Merge with any previously stored partial data
        stored_str = await redis_client.get(partial_key)
        partial: dict[str, Any] = json.loads(stored_str) if stored_str else {}

        # Layer in whatever the LLM extracted this turn (non-null values win)
        for field in ("name", "description", "category", "price", "stock"):
            val = params.get(field)
            if val is not None and str(val).strip():
                partial[field] = val

        # Validate which required fields are still missing / invalid
        missing: list[str] = []
        if not partial.get("name", "").strip():
            missing.append("name")
        if partial.get("price") is None or float(partial.get("price", -1)) <= 0:
            missing.append("price (e.g. 2.50)")
        if partial.get("stock") is None or int(partial.get("stock", -1)) < 0:
            missing.append("stock quantity (e.g. 100)")

        if missing:
            # Persist partial data so next turn can merge
            await redis_client.set(partial_key, json.dumps(partial), ex=300)

            already_have = []
            if partial.get("name"):
                already_have.append(f"name: {partial['name']}")
            if partial.get("category"):
                already_have.append(f"category: {partial['category']}")
            if partial.get("price") and float(partial.get("price", 0)) > 0:
                already_have.append(f"price: ${float(partial['price']):.2f}")
            if partial.get("stock") is not None and int(partial.get("stock", -1)) >= 0:
                already_have.append(f"stock: {partial['stock']}")

            have_str = f" (I have: {', '.join(already_have)})" if already_have else ""
            missing_str = ", ".join(missing)
            return {
                "type": "response",
                "text": (
                    f"I still need the following to create this product{have_str}: "
                    f"**{missing_str}**.\n\n"
                    f"Please provide them together, e.g. "
                    f'"price 2.50, stock 100, category Fruits"'
                ),
                "options": None,
            }

        # All required fields present — clear partial cache and create product
        await redis_client.delete(partial_key)
        result = await self._execute_tool("seller_create_product", partial)
        return await self._format_response(user_message, result)

    async def _handle_seller_create_followup(self, user_message: str) -> dict[str, Any]:
        """Handle a follow-up message that supplies missing seller_create_product fields."""
        # Re-run intent classification but only to extract product fields from the message.
        # We call the tool directly with the merged params via slot-fill logic.
        redis_client = get_redis_client()
        partial_key = f"chat:session:{self.session_id}:seller_create_partial"
        stored_str = await redis_client.get(partial_key)
        if not stored_str:
            # Context expired — start fresh
            return {
                "type": "response",
                "text": "I lost track of the product we were creating. Please start again with all details.",
                "options": None,
            }

        # Use a lightweight extraction call to parse the user's follow-up
        extract_prompt = (
            f"Extract product fields from this message. "
            f"Return ONLY JSON with any of: name, description, category, price (number), stock (integer).\n"
            f"Message: '{user_message}'\n"
            f'Output ONLY raw JSON: {{"name": ..., "category": ..., "price": ..., "stock": ...}}'
        )
        extracted_str = await call_llm(
            system_prompt="You extract product creation fields from user messages.",
            user_prompt=extract_prompt,
            temperature=0.0,
            max_tokens=128,
            call_type="product_field_extract",
        )
        extracted_params: dict[str, Any] = {}
        if extracted_str:
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                extracted_params = json.loads(extract_json_from_response(extracted_str))

        return await self._handle_seller_create_slot_fill(
            extracted_params, user_message
        )

    async def _execute_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with params. All pure Python, no LLM calls."""
        tool_params = dict(params)
        tool_params["db"] = self.db
        tool_params["user_id"] = self.user_id

        if tool_name in TOOL_REGISTRY:
            try:
                return await TOOL_REGISTRY[tool_name](**tool_params)
            except Exception as e:
                logger.error(f"Tool {tool_name} failed: {e}")
                safe_message = _sanitize_error_message(str(e))
                return {"success": False, "message": safe_message}
        else:
            return {"success": False, "message": f"Unknown tool: {tool_name}"}

    async def _format_response(self, query: str, results: Any) -> dict[str, Any]:
        """Format tool results into a natural response with optional action options."""
        # If the tool already returned a message (for direct actions like add_to_cart), use it directly
        if isinstance(results, dict) and "message" in results and "success" in results:
            if results.get("success"):
                return {"type": "response", "text": results["message"], "options": None}
            return {"type": "response", "text": results["message"], "options": None}

        # If empty results
        if isinstance(results, dict) and results.get("empty"):
            return {
                "type": "response",
                "text": results.get("message", "No results found."),
                "options": None,
            }

        # ── 1. Cart result ─────────────────────────────────────────────
        if isinstance(results, dict) and "items" in results and "total" in results:
            items = results["items"]
            total = results["total"]
            if not items:
                return {
                    "type": "response",
                    "text": "Your cart is empty.",
                    "options": None,
                }
            lines = [f"**🛒 Your Cart** (Total: **${total:.2f}**)\n"]
            cart_options: list[dict[str, Any]] = []
            for item in items:
                pid = item.get("product_id", "")
                name = item.get("name", "")
                qty = item.get("quantity", 1)
                price = item.get("price", 0.0)
                subtotal = item.get("total", price * qty)
                lines.append(f"• {name} × {qty} = ${subtotal:.2f}")
                if pid:
                    cart_options.append(
                        {
                            "label": f"{name} ×{qty}",
                            "value": pid,
                            "description": f"${price:.2f} each · Subtotal ${subtotal:.2f}",
                            "actions": [
                                {"label": "Remove", "value": f"remove_{pid}"},
                            ],
                        }
                    )
            cart_options.append(
                {
                    "label": "✅ Checkout",
                    "value": "checkout",
                    "description": f"Place order · ${total:.2f} total",
                }
            )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": cart_options,
                "free_input_allowed": True,
            }

        # ── 2. Fulfillment queue result ─────────────────────────────────
        # Must be checked BEFORE orders-list (both are lists with status+total keys)
        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
            and results[0].get("fulfillment_queue")
        ):
            count = len(results)
            status_counts: dict[str, int] = {}
            for row in results:
                s = row.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
            summary_parts = [
                f"{v} {k.replace('_', ' ')}" for k, v in status_counts.items()
            ]
            lines = [
                f"**📋 Fulfillment Queue** — {count} order{'s' if count != 1 else ''}"
                + (f" ({', '.join(summary_parts)})" if summary_parts else "")
                + "\n"
            ]
            fq_options: list[dict[str, Any]] = []
            for row in results:
                oid_short = row.get("order_id_short", "")
                status_label = row.get("status_label", row.get("status", "").upper())
                total = row.get("total", 0.0)
                created = (row.get("created_at") or "")[:10]
                item_count = row.get("my_items_count", 0)
                my_items = row.get("my_items", [])
                item_names = ", ".join(
                    f"{it.get('product_name', '?')} ×{it.get('quantity', 1)}"
                    for it in my_items[:2]
                )
                if len(my_items) > 2:
                    item_names += f" +{len(my_items) - 2} more"
                lines.append(
                    f"• #{oid_short}… · {status_label} · ${total:.2f} · {created} · {item_count} item{'s' if item_count != 1 else ''}"
                )
                actions = []
                if row.get("advance_value") and row.get("next_action_label"):
                    actions.append(
                        {
                            "label": row["next_action_label"],
                            "value": row["advance_value"],
                        }
                    )
                fq_options.append(
                    {
                        "label": f"#{oid_short}… — {status_label}",
                        "value": row.get("order_id", ""),
                        "description": item_names or f"${total:.2f}",
                        "actions": actions,
                        "card_variant": "fulfillment_queue",
                    }
                )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": fq_options,
                "free_input_allowed": True,
                "card_variant": "fulfillment_queue",
            }

        # ── 3. Orders result (customer) ─────────────────────────────────
        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
            and "status" in results[0]
            and "total" in results[0]
        ):
            options = []
            lines = [
                f"**📦 Your Orders** ({len(results)} order{'s' if len(results) != 1 else ''})\n"
            ]
            for order in results:
                oid = order.get("id", "")[:8]
                status = order.get("status", "").upper()
                total = order.get("total", 0.0)
                created = (order.get("created_at") or "")[:10]
                items_list = order.get("items", [])
                item_names = ", ".join(
                    f"{i.get('product_name', '?')} ×{i.get('quantity', 1)}"
                    for i in items_list[:3]
                )
                if len(items_list) > 3:
                    item_names += f" +{len(items_list) - 3} more"
                lines.append(f"• #{oid}… · {status} · ${total:.2f} · {created}")
                options.append(
                    {
                        "label": f"#{oid}… — {status}",
                        "value": order.get("id", ""),
                        "description": item_names or "No items",
                        "actions": [
                            {
                                "label": "View Details",
                                "value": f"order_detail_{order.get('id', '')}",
                            }
                        ],
                    }
                )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": options,
                "free_input_allowed": True,
            }

        # ── 2b. Single order detail result ──────────────────────────────
        if isinstance(results, dict) and results.get("order_detail"):
            oid_short = results.get("id", "")[:8]
            status = results.get("status", "").upper()
            total = results.get("total", 0.0)
            items_list = results.get("items", [])
            addr = results.get("delivery_address", {})

            # Status timeline
            status_steps = ["placed", "packed", "out_for_delivery", "delivered"]
            status_labels = {
                "placed": "Placed",
                "packed": "Packed",
                "out_for_delivery": "Out for Delivery",
                "delivered": "Delivered",
            }
            status_ts_keys = {
                "placed": "created_at",
                "packed": "packed_at",
                "out_for_delivery": "out_for_delivery_at",
                "delivered": "delivered_at",
            }
            current_status = results.get("status", "placed")
            timeline_parts = []
            for step in status_steps:
                ts_key = status_ts_keys[step]
                ts = (results.get(ts_key) or "")[:10]
                if step == current_status:
                    marker = "● "
                elif status_steps.index(step) < status_steps.index(current_status):
                    marker = "✓ "
                else:
                    marker = "○ "
                label = status_labels[step]
                timeline_parts.append(f"{marker}{label}" + (f" ({ts})" if ts else ""))

            # Items table
            item_lines = []
            for it in items_list:
                name = it.get("product_name", "?")
                qty = it.get("quantity", 1)
                price = it.get("price_at_purchase", 0.0)
                sub = it.get("subtotal", price * qty)
                item_lines.append(f"  • {name} × {qty}  @${price:.2f}  = ${sub:.2f}")

            # Delivery address
            addr_line = ", ".join(
                filter(
                    None,
                    [
                        addr.get("line1", ""),
                        addr.get("line2", ""),
                        addr.get("city", ""),
                        addr.get("state", ""),
                        addr.get("postal_code", ""),
                    ],
                )
            )

            text_parts = [
                f"**Order #{oid_short}…** — {status} — **${total:.2f}**\n",
                "**Status:** " + " → ".join(timeline_parts),
                "",
                "**Items:**",
            ] + item_lines

            if addr_line:
                text_parts += [
                    "",
                    f"**Delivery to:** {addr.get('label', '')}: {addr_line}",
                ]

            return {
                "type": "options_response",
                "text": "\n".join(text_parts),
                "options": None,
                "free_input_allowed": True,
            }

        # ── 3. Addresses result ─────────────────────────────────────────
        if isinstance(results, dict) and "addresses" in results:
            addresses = results["addresses"]
            if not addresses:
                return {
                    "type": "response",
                    "text": 'You have no saved addresses. You can add one by saying "add address".',
                    "options": None,
                }
            options = []
            lines = [f"**📍 Your Addresses** ({len(addresses)})\n"]
            for addr in addresses:
                aid = addr.get("id", "")
                label = addr.get("label") or "Home"
                line1 = addr.get("line1", "")
                city = addr.get("city", "")
                state = addr.get("state", "")
                postal_code = addr.get("postal_code", "")
                is_default = addr.get("is_default", False)
                default_tag = " 🏠 Default" if is_default else ""
                display = (
                    f"{label}: {line1}, {city}, {state} {postal_code}{default_tag}"
                )
                lines.append(f"• {display}")
                options.append(
                    {
                        "label": label,
                        "value": aid,
                        "description": f"{line1}, {city}, {state} {postal_code}{default_tag}",
                        "actions": [
                            {
                                "label": "Set Default",
                                "value": f"set_default_address_{aid}",
                            },
                            {"label": "Edit", "value": f"update_address_{aid}"},
                            {"label": "Delete", "value": f"delete_address_{aid}"},
                        ],
                    }
                )
            options.append(
                {
                    "label": "➕ Add New Address",
                    "value": "add_address",
                    "description": "Save a delivery address",
                }
            )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": options,
                "free_input_allowed": True,
            }

        # ── 4. Facts / preferences result ────────────────────────────────
        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
            and "fact_text" in results[0]
        ):
            lines = ["**🧠 Your Preferences & Facts**\n"]
            for f in results:
                cat = f.get("category", "other")
                text = f.get("fact_text", "")
                lines.append(f"• [{cat}] {text}")
            return {"type": "response", "text": "\n".join(lines), "options": None}

        # ── 5. Seller catalog result ─────────────────────────────────────
        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
            and "is_active" in results[0]
            and "sold_count" in results[0]
        ):
            active = [p for p in results if p.get("is_active")]
            inactive = [p for p in results if not p.get("is_active")]
            lines = [
                f"**🏪 Your Products** ({len(active)} active, {len(inactive)} inactive)\n"
            ]
            options = []
            for p in results:
                pid = p.get("id", "")
                name = p.get("name", "")
                price = p.get("price", 0.0)
                stock = p.get("stock", 0)
                active_tag = "✅" if p.get("is_active") else "❌"
                sold = p.get("sold_count", 0)
                lines.append(
                    f"• {active_tag} {name} — ${price:.2f} · Stock: {stock} · Sold: {sold}"
                )
                options.append(
                    {
                        "label": f"{active_tag} {name}",
                        "value": pid,
                        "description": f"${price:.2f} · Stock {stock} · {sold} sold",
                        "actions": [
                            {"label": "Edit", "value": f"seller_edit_{pid}"},
                            {
                                "label": "Deactivate",
                                "value": f"seller_deactivate_{pid}",
                            },
                        ],
                    }
                )
            options.append(
                {
                    "label": "➕ Create Product",
                    "value": "seller_create",
                    "description": "List a new product",
                }
            )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": options,
                "free_input_allowed": True,
            }

        # ── 6. Inventory result ──────────────────────────────────────────
        # Detected by: list of dicts with 'stock_status' key (set by inventory_search tool)
        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
            and "stock_status" in results[0]
        ):
            # Header stats — the tool returns a summary dict as the first element
            summary = results[0] if results[0].get("_summary") else None
            products = [r for r in results if not r.get("_summary")]
            count = len(products)
            header_parts = [
                f"**📦 Inventory** — {count} product{'s' if count != 1 else ''}"
            ]
            if summary:
                header_parts.append(
                    f"(🟢 {summary.get('in_stock_count', 0)} in stock · "
                    f"🟡 {summary.get('low_stock_count', 0)} low · "
                    f"🔴 {summary.get('out_of_stock_count', 0)} out of stock)"
                )
            lines = [" ".join(header_parts) + "\n"]
            inv_options: list[dict[str, Any]] = []
            stock_badge = {"in_stock": "🟢", "low_stock": "🟡", "out_of_stock": "🔴"}
            for p in products:
                pid = p.get("id", "")
                name = p.get("name", "")
                price = p.get("price", 0.0)
                stock = p.get("stock", 0)
                rating = p.get("avg_rating", 0.0)
                sold = p.get("sold_count", 0)
                ss = p.get("stock_status", "in_stock")
                badge = stock_badge.get(ss, "")
                lines.append(
                    f"• {badge} {name} — ${price:.2f} · Stock: {stock} · ⭐{rating:.1f} · Sold: {sold}"
                )
                inv_options.append(
                    {
                        "label": f"{badge} {name}",
                        "value": pid,
                        "description": f"${price:.2f} · Stock {stock} · ⭐{rating:.1f} · {sold} sold",
                        "actions": [
                            {"label": "Edit", "value": f"seller_edit_{pid}"},
                            {
                                "label": "Deactivate",
                                "value": f"seller_deactivate_{pid}",
                            },
                        ],
                        "card_variant": "inventory",
                    }
                )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": inv_options,
                "free_input_allowed": True,
                "card_variant": "inventory",
            }

        # ── 7. Search products result ────────────────────────────────────
        # Detected by: plain list of dicts each containing 'avg_rating' and 'category'
        # (seller catalog has 'is_active'+'sold_count' and is caught above first)
        _is_search_result = isinstance(results, list) and (
            len(results) == 0
            or (
                isinstance(results[0], dict)
                and "avg_rating" in results[0]
                and "category" in results[0]
                and "is_active" not in results[0]
            )
        )
        if _is_search_result:
            # Empty search result
            if not results:
                return {
                    "type": "response",
                    "text": "No products found matching your search. Try different keywords or broaden your filters.",
                    "options": None,
                }
            count = len(results)
            result_summary = f"Found {count} product{'s' if count != 1 else ''}:"
            search_options: list[dict[str, Any]] = []
            for p in results:
                pid = p.get("id", "")
                name = p.get("name", "")
                price = p.get("price", 0.0)
                stock = p.get("stock", 0)
                rating = p.get("avg_rating", 0.0)
                category = p.get("category", "")
                in_stock = stock > 0
                stock_label = f"Stock: {stock}" if in_stock else "Out of stock"
                desc = f"${price:.2f} · {category} · ⭐ {rating:.1f} · {stock_label}"
                actions = []
                if in_stock and pid:
                    actions.append({"label": "Add to Cart", "value": f"add_{pid}"})
                if pid:
                    actions.append({"label": "View Details", "value": f"view_{pid}"})
                search_options.append(
                    {
                        "label": name,
                        "value": pid,
                        "description": desc,
                        "actions": actions,
                    }
                )
            return {
                "type": "options_response",
                "text": result_summary,
                "options": search_options,
                "free_input_allowed": True,
            }

        results_str = json.dumps(results, indent=2)[:2000]  # Truncate for LLM context

        # LLM fallback for any genuinely unstructured result (rare)
        response_text = await call_llm(
            system_prompt="You are a friendly grocery assistant.",
            user_prompt=RESPONSE_PROMPT.format(query=query, results=results_str),
            temperature=0.3,
            max_tokens=512,
            call_type="response_format",
        )

        if not response_text:
            return {
                "type": "response",
                "text": "Here are the results.",
                "options": None,
            }

        try:
            formatted = json.loads(extract_json_from_response(response_text))
            return {
                "type": "options_response" if formatted.get("options") else "response",
                "text": formatted.get("text", "Here are the results."),
                "options": formatted.get("options"),
                "free_input_allowed": True,
            }
        except (json.JSONDecodeError, KeyError):
            # If the LLM returned raw JSON text instead of a structured response,
            # try to strip it; otherwise fall back to a safe generic message.
            stripped = response_text.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                logger.warning(
                    "LLM fallback formatter returned raw JSON — using generic message"
                )
                return {
                    "type": "response",
                    "text": "Here are the results. (Use the buttons above to interact.)",
                    "options": None,
                }
            return {"type": "response", "text": stripped[:1000], "options": None}

    async def _format_response_stream(
        self, query: str, results: Any
    ) -> AsyncGenerator[str, None]:
        """Format tool results into a natural response, yielding tokens via LLM streaming.
        For built-in formatters (non-LLM), yields the full text.
        """
        # If the tool already returned a message, yield it directly
        if isinstance(results, dict) and "message" in results and "success" in results:
            yield results["message"]
            return

        # If empty results
        if isinstance(results, dict) and results.get("empty"):
            yield results.get("message", "No results found.")
            return

        # For built-in formatters, yield the full text
        built_in_result = await self._format_response(query, results)
        if built_in_result.get("type") == "response":
            text = built_in_result.get("text", "")
            if text and not built_in_result.get("options"):
                yield text
                return

        # For options_response, yield the text but don't stream (options need full text)
        text = built_in_result.get("text", "")
        if text:
            yield text

    async def run_turn_voice_stream(
        self, user_message: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Voice-optimized turn execution that yields sentences progressively.
        Instead of waiting for the full LLM response, this method:
        1. Runs intent classification (blocking - needs full JSON)
        2. Executes tool (blocking - needs full result)
        3. Streams the response formatting via call_llm_stream()
        4. Buffers tokens into sentences and yields each sentence immediately

        Yields:
            dict with keys:
            - type: "sentence" | "options_response" | "permission_request" | "role_switch_request" | "error"
            - text: The sentence text or response text
            - options: Optional list of options
            - free_input_allowed: bool
        """
        turn_start_time = time.perf_counter()
        logger.info(
            f"[VOICE STREAM] Starting turn for user {self.user_id}, session {self.session_id}..."
        )

        redis_client = get_redis_client()

        # Check for pending state (address, quantity, narrowing, role switch, permission)
        # Same checks as run_turn() but yield the result directly
        addr_collect_key = f"chat:session:{self.session_id}:address_collect"
        addr_collect_str = await redis_client.get(addr_collect_key)
        if addr_collect_str:
            collect_ctx = json.loads(addr_collect_str)
            await redis_client.delete(addr_collect_key)
            result = await self._handle_address_collect_response(
                user_message, collect_ctx
            )
            yield result
            return

        # Check for pending address update
        addr_update_key = f"chat:session:{self.session_id}:address_update_pending"
        addr_update_str = await redis_client.get(addr_update_key)
        if addr_update_str:
            update_ctx = json.loads(addr_update_str)
            await redis_client.delete(addr_update_key)
            response = await self._handle_address_update_response(
                user_message, update_ctx
            )
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response.get("text", "")
            )
            yield response
            return

        quantity_key = f"chat:session:{self.session_id}:pending_quantity"
        pending_quantity_str = await redis_client.get(quantity_key)
        if pending_quantity_str:
            self._pending_quantity_context = json.loads(pending_quantity_str)
            await redis_client.delete(quantity_key)
            result = await self._handle_quantity_response(user_message)
            yield result
            return
        if self._pending_quantity_context:
            result = await self._handle_quantity_response(user_message)
            yield result
            return

        narrowing_key = f"chat:session:{self.session_id}:narrowing_context"
        narrowing_str = await redis_client.get(narrowing_key)
        if narrowing_str:
            self._narrowing_context = json.loads(narrowing_str)
            await redis_client.delete(narrowing_key)
            result = await self._handle_narrowing_response(user_message)
            yield result
            return
        if self._narrowing_context:
            result = await self._handle_narrowing_response(user_message)
            yield result
            return

        # Check for pending role switch
        role_switch_key = f"chat:session:{self.session_id}:pending_role_switch"
        role_switch_str = await redis_client.get(role_switch_key)
        if role_switch_str:
            role_switch_data = json.loads(role_switch_str)
            msg_lower = user_message.strip().lower()
            is_confirm = msg_lower in (
                "yes",
                "sure",
                "ok",
                "do it",
                "proceed",
                "confirm",
                "yeah",
                "yep",
            )
            is_deny = msg_lower in (
                "no",
                "stop",
                "cancel",
                "never mind",
                "don't",
                "dont",
                "nah",
            )
            if user_message.startswith("switch_role:"):
                is_confirm = True
                needed_role = user_message.split("switch_role:")[1].strip()
                role_switch_data["needed_role"] = needed_role

            if is_confirm:
                await redis_client.delete(role_switch_key)
                needed_role = role_switch_data.get("needed_role", "seller")
                switch_result = await self._execute_tool(
                    "switch_role", {"role": needed_role}
                )
                if isinstance(switch_result, dict) and switch_result.get("success"):
                    with contextlib.suppress(ValueError):
                        self.user_role = UserRole(needed_role)
                    tool_name = role_switch_data.get("tool_name", "")
                    original_message = role_switch_data.get("original_message", "")
                    if tool_name:
                        result = await self._execute_tool(tool_name, {})
                        response = await self._format_response(original_message, result)
                        response["text"] = (
                            f"Role switched to '{needed_role}'. "
                            + response.get("text", "")
                        )
                        yield response
                        return
                yield {
                    "type": "response",
                    "text": f"Switched to '{needed_role}' role. How can I help?",
                    "options": None,
                }
                return
            if is_deny:
                await redis_client.delete(role_switch_key)
                yield {
                    "type": "response",
                    "text": "No problem. Please ask for something else.",
                    "options": None,
                }
                return
            await redis_client.delete(role_switch_key)

        # Check for pending permission action
        pending_key = f"chat:session:{self.session_id}:pending_action"
        pending_data_str = await redis_client.get(pending_key)
        if pending_data_str:
            pending_data = json.loads(pending_data_str)
            msg_lower = user_message.strip().lower()
            is_confirm = msg_lower in (
                "yes",
                "sure",
                "ok",
                "do it",
                "proceed",
                "confirm",
                "yeah",
                "yep",
                "approve",
            )
            is_deny = msg_lower in (
                "no",
                "stop",
                "cancel",
                "never mind",
                "don't",
                "dont",
                "nah",
            )
            if is_confirm:
                await redis_client.delete(pending_key)
                result = await self._execute_tool(
                    pending_data["action_type"],
                    {
                        "product_id": pending_data.get("product_id", ""),
                        "quantity": pending_data.get("quantity", 1),
                    },
                )
                response = await self._format_response(user_message, result)
                yield response
                return
            if is_deny:
                await redis_client.delete(pending_key)
                yield {
                    "type": "response",
                    "text": "Cancelled that action.",
                    "options": None,
                }
                return
            await redis_client.delete(pending_key)

        # Check for pending seller_create_product slot-fill
        seller_partial_key = f"chat:session:{self.session_id}:seller_create_partial"
        seller_partial_str = await redis_client.get(seller_partial_key)
        if seller_partial_str:
            response = await self._handle_seller_create_followup(user_message)
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response.get("text", "")
            )
            yield response
            return

        # Check fast path
        fast_result = await self._check_fast_path(user_message)
        if fast_result is not None:
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", fast_result.get("text", "")
            )
            yield fast_result
            return

        # Step 1: Intent classification (blocking - needs full JSON)
        step_start = time.perf_counter()
        facts_str = await self._get_facts(user_message)
        history = await get_session_history(str(self.session_id))
        history_str = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in history[-4:]]
        )
        tool_descs = _build_role_scoped_tool_descs(self.user_role)

        intent_response = await call_llm(
            system_prompt="You are a precise intent classifier.",
            user_prompt=INTENT_PROMPT.format(
                tool_descriptions=tool_descs, facts=facts_str, history=history_str
            )
            + f"\n\nUser message: '{user_message}'",
            temperature=0.0,
            max_tokens=512,
            call_type="intent_classifier",
        )

        if not intent_response:
            yield {
                "type": "response",
                "text": "I had trouble understanding that. Could you rephrase?",
                "options": None,
            }
            return

        try:
            extracted = extract_json_from_response(intent_response)
            intent_data = json.loads(extracted)
        except (json.JSONDecodeError, ValueError):
            yield {
                "type": "response",
                "text": "I had trouble understanding that. Could you rephrase?",
                "options": None,
            }
            return

        selected_tool = intent_data.get("tool", "out_of_scope")
        params = intent_data.get("params", {})
        fact_to_remember = intent_data.get("fact_to_remember")
        fact_category = intent_data.get("fact_category")

        logger.info(
            f"[VOICE STREAM] Intent: {selected_tool} ({time.perf_counter() - step_start:.2f}s)"
        )

        # Handle toggle_theme
        if selected_tool == "toggle_theme":
            yield {"type": "toggle_theme", "text": "Theme toggled.", "options": None}
            return

        # Handle out of scope
        if selected_tool == "out_of_scope":
            out_prompt = (
                f"The user said: '{user_message}'. "
                "You are GroceryGenie, a friendly AI grocery shopping assistant. "
                "Briefly acknowledge what the user said in 1 warm sentence, then politely offer to help."
            )
            response_text = await call_llm(
                system_prompt="You are GroceryGenie, a helpful grocery shopping assistant.",
                user_prompt=out_prompt,
                temperature=0.3,
                max_tokens=150,
                call_type="out_of_scope_response",
            )
            if not response_text or not response_text.strip():
                response_text = "I'm your GroceryGenie shopping assistant! How can I help you today?"
            yield {"type": "response", "text": response_text.strip(), "options": None}
            return

        # Store fact if found
        if (
            fact_to_remember
            and isinstance(fact_to_remember, str)
            and fact_to_remember.strip()
        ):
            await self._store_fact(fact_to_remember, fact_category)

        # RBAC check
        if selected_tool != "out_of_scope":
            try:
                check_tool_permission(selected_tool, self.user_role)
            except ValueError:
                # Unknown tool name — LLM hallucinated something not in the registry.
                logger.warning(
                    f"[VOICE STREAM] LLM returned unknown tool name '{selected_tool}' — not in TOOL_REGISTRY"
                )
                yield {
                    "type": "response",
                    "text": "I'm not sure how to do that. Could you rephrase your request?",
                    "options": None,
                }
                return
            except PermissionError as e:
                err_str = str(e)
                needed_role = "seller"
                if "requires '" in err_str:
                    needed_role = err_str.split("requires '")[1].split("'", maxsplit=1)[
                        0
                    ]
                result = await self._handle_role_switch_request(
                    user_message, selected_tool, needed_role
                )
                yield result
                return

        # Handle quantity-pending for add_to_cart
        if selected_tool == "add_to_cart":
            quantity = params.get("quantity")
            if quantity is None:
                product_id = params.get("product_id", "")
                result = await self._ask_for_quantity(product_id, user_message)
                yield result
                return

        # Handle missing product_id for update_cart_quantity or remove_from_cart
        if selected_tool in ("update_cart_quantity", "remove_from_cart"):
            pid = params.get("product_id")
            if not pid:
                cart_res = await self._execute_tool("view_cart", {})
                if (
                    isinstance(cart_res, dict)
                    and "items" in cart_res
                    and cart_res["items"]
                ):
                    options = []
                    for item in cart_res["items"]:
                        item_pid = item.get("product_id", "")
                        item_name = item.get("name", "")
                        if item_pid:
                            options.append(
                                {
                                    "label": item_name,
                                    "value": item_pid,
                                    "description": f"Currently {item.get('quantity', 1)} in cart",
                                }
                            )
                    action_label = (
                        "update the quantity for"
                        if selected_tool == "update_cart_quantity"
                        else "remove"
                    )
                    yield {
                        "type": "options_response",
                        "text": f"Which item would you like to {action_label}?",
                        "options": options,
                        "free_input_allowed": True,
                    }
                    return
                yield {
                    "type": "response",
                    "text": "Your cart is currently empty.",
                    "options": None,
                }
                return

        # Handle address collection
        if selected_tool == "manage_addresses":
            action = params.get("action", "list")
            if action == "add":
                addr_data = params.get("address_data") or {}
                result = await self._start_address_collect_flow(addr_data, user_message)
                yield result
                return
            if action == "update" and not params.get("address_id"):
                list_result = await self._execute_tool(
                    "manage_addresses", {"action": "list"}
                )
                if isinstance(list_result, dict) and list_result.get("addresses"):
                    addr_list = list_result["addresses"]
                    options = [
                        {
                            "label": a.get("label", "Home"),
                            "value": f"update_address_{a['id']}",
                            "description": f"{a.get('line1', '')}, {a.get('city', '')}",
                        }
                        for a in addr_list
                    ]
                    yield {
                        "type": "options_response",
                        "text": "Which address would you like to update?",
                        "options": options,
                        "free_input_allowed": False,
                    }
                    return
                yield {
                    "type": "response",
                    "text": "You have no saved addresses yet.",
                    "options": None,
                }
                return

        # Handle seller_create_product — slot-fill all required fields before hitting DB
        if selected_tool == "seller_create_product":
            result = await self._handle_seller_create_slot_fill(params, user_message)
            yield result
            return

        # Step 2: Execute tool (blocking)
        step_start = time.perf_counter()
        result = await self._execute_tool(selected_tool, params)
        logger.info(
            f"[VOICE STREAM] Tool executed ({selected_tool}) in {time.perf_counter() - step_start:.2f}s"
        )

        # Check for too_many results
        if isinstance(result, dict) and result.get("too_many"):
            narrowing_result = await self._handle_too_many_results(result, user_message)
            yield narrowing_result
            return

        # Step 3: Stream response formatting via LLM, buffering into sentences
        # For built-in formatters (cart, orders, addresses, etc.), yield the full text
        if isinstance(result, dict) and "message" in result and "success" in result:
            yield {"type": "response", "text": result["message"], "options": None}
            return

        if isinstance(result, dict) and result.get("empty"):
            yield {
                "type": "response",
                "text": result.get("message", "No results found."),
                "options": None,
            }
            return

        # Check for built-in formatters
        built_in = await self._format_response(user_message, result)
        if built_in.get("type") == "options_response":
            yield built_in
            return

        text = built_in.get("text", "")
        if text:
            # For voice, yield the full text as a single sentence event
            # The TTS will handle sentence-level synthesis
            yield {"type": "response", "text": text, "options": None}

        # Store in session
        await append_message_to_session(str(self.session_id), "user", user_message)
        await append_message_to_session(str(self.session_id), "assistant", text)

        total_time = time.perf_counter() - turn_start_time
        logger.info(f"[VOICE STREAM] Turn completed in {total_time:.2f}s")

    async def execute_approved_mutation(
        self, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a pre-approved mutation (e.g., after user grants permission)."""
        product_id = payload.get("product_id", "")
        quantity = payload.get("quantity", 1)
        result = await self._execute_tool(
            action, {"product_id": product_id, "quantity": quantity}
        )
        return await self._format_response("", result)
