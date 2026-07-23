import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import UserRole
from app.services.agent.llm import call_llm, extract_json_from_response
from app.services.agent.memory import get_user_facts
from app.services.agent.tools import TOOL_DESCRIPTIONS, TOOL_REGISTRY
from app.services.memory import (
    append_message_to_session,
    get_redis_client,
    get_session_history,
)

logger = logging.getLogger("app.services.agent.orchestrator")

# Single prompt for intent classification + parameter extraction
INTENT_PROMPT = """You are a grocery assistant. Determine what the user wants to do and extract parameters.

Available tools and their parameters (tool_name: parameters):
{tool_descriptions}

User facts/preferences: {facts}
Recent conversation: {history}

If the user's request is completely unrelated to grocery shopping (e.g. sports, politics, coding, general knowledge), set tool to "out_of_scope".
If the user's request expresses a durable personal fact (dietary restriction, strong preference, allergy), include it in "fact_to_remember".
Do NOT extract one-off purchase requests or search queries as facts.

Return ONLY JSON:
{{
  "tool": "tool_name or out_of_scope",
  "params": {{ "param1": "value1", ... }},
  "fact_to_remember": "fact summary or null",
  "fact_category": "dietary/preference/instruction/other or null",
  "out_of_scope_reason": "reason string or null (only if tool is out_of_scope)"
}}

For 'search_products': params can include query, category, min_price, max_price, min_rating, in_stock_only.
  IMPORTANT: If the user mentions any filter like "less than $5", "under $10", "cheaper than", "more than $X",
  "price range", "minimum rating", "organic only", "in stock", extract them into the appropriate params.
  For price comparisons, convert them to min_price and max_price numeric values.

For 'add_to_cart'/'remove_from_cart'/'update_cart_quantity': params need product_id, quantity.
  IMPORTANT: If the user did NOT specify a quantity, set quantity to null (the system will ask for it).

For 'switch_role': params need role ("customer" or "seller").
For 'manage_addresses': params need action ("list"/"add"/"update"/"delete") and optionally address_data.
For 'seller_create_product': params need name, description, category, price, stock.
For 'seller_update_product': params need product_id, and optionally name/description/category/price/stock.
For 'seller_delete_product': params need product_id.
For 'place_order': no params needed (uses cart + default address).
For 'view_cart'/'view_orders'/'view_facts'/'seller_list_products': no params needed.

Output ONLY raw JSON. No markdown code blocks, no prose."""

RESPONSE_PROMPT = """You are a friendly grocery shopping assistant. Format the tool execution results into a natural response.

CRITICAL RULES:
- ONLY mention products/data that actually appear in the results below.
- Do NOT invent products, names, or prices.
- If there are 0 results, say so honestly.
- Keep responses concise and helpful.
- NEVER show raw UUIDs or technical identifiers to the user.

User query: {query}
Results: {results}

If the results include product data and making sense, offer structured options for the user to take actions (add to cart, view details).
Each option can have "actions" for quick actions:
{{
  "text": "Your response text",
  "options": [
    {{"label": "Product Name", "value": "product_id", "description": "Price info", "actions": [{{"label": "Add to Cart", "value": "add_product_id"}}, {{"label": "View Details", "value": "view_product_id"}}]}},
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

    async def _get_facts(self) -> str:
        if self._facts_cache is not None:
            return self._facts_cache
        facts = await get_user_facts(self.db, self.user_id)
        facts_str = "; ".join([f.fact_text for f in facts]) if facts else "None"
        self._facts_cache = facts_str
        return facts_str

    async def run_turn(self, user_message: str) -> dict[str, Any]:
        turn_start_time = time.perf_counter()
        logger.info(
            f"AgentOrchestrator starting turn for user {self.user_id}, session {self.session_id}..."
        )

        redis_client = get_redis_client()

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
        facts_str = await self._get_facts()
        history = await get_session_history(str(self.session_id))
        history_str = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in history[-6:]]
        )

        tool_descs = "\n".join(
            [f"  - {name}: {desc}" for name, desc in TOOL_DESCRIPTIONS.items()]
        )

        intent_response = await call_llm(
            system_prompt="You are a precise intent classifier.",
            user_prompt=INTENT_PROMPT.format(
                tool_descriptions=tool_descs,
                facts=facts_str,
                history=history_str,
            )
            + f"\n\nUser message: '{user_message}'",
            temperature=0.0,
            max_tokens=1024,
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

        # Handle out of scope immediately
        if selected_tool == "out_of_scope":
            response_text = "I'm your GroceryGenie shopping assistant! I can help you find products, manage your cart, check orders, manage delivery addresses, or handle seller operations. How can I assist you with your groceries today?"
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response_text
            )
            return {"type": "response", "text": response_text, "options": None}

        # Store fact if found
        if (
            fact_to_remember
            and isinstance(fact_to_remember, str)
            and fact_to_remember.strip()
        ):
            await self._store_fact(fact_to_remember, fact_category)

        # Handle quantity-pending for add_to_cart
        if selected_tool == "add_to_cart":
            quantity = params.get("quantity")
            if quantity is None:
                # User didn't specify quantity, need to ask
                product_id = params.get("product_id", "")
                return await self._ask_for_quantity(product_id, user_message)

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

    async def _store_fact(self, fact_text: str, fact_category: str | None) -> None:
        """Store a persistent fact for the user."""
        try:
            from sqlalchemy import select

            from app.db.models.enums import FactCategory
            from app.db.models.memory import PersistentFact

            dup = await self.db.execute(
                select(PersistentFact).where(
                    PersistentFact.user_id == self.user_id,
                    PersistentFact.fact_text.ilike(fact_text.strip()),
                )
            )
            if not dup.scalar_one_or_none():
                try:
                    cat = (
                        FactCategory(fact_category)
                        if fact_category
                        else FactCategory.other
                    )
                except ValueError:
                    cat = FactCategory.other
                fact = PersistentFact(
                    user_id=self.user_id, fact_text=fact_text.strip(), category=cat
                )
                self.db.add(fact)
                await self.db.commit()
                self._facts_cache = None
        except Exception as e:
            logger.warning(f"Failed to store fact: {e}")

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

        # 3. Handle view_<product_id>
        if msg.startswith("view_"):
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
                                    "description": f"${float(product.price):.2f} • Stock: {product.stock} • Rating: {float(product.avg_rating):.1f}⭐",
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
                    pass  # nosec: B110 - UUID lookup failure is non-critical

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

        # 13. Handle direct checkout / place order
        if msg_lower in ("place_order", "checkout", "place order", "buy now"):
            result = await self._execute_tool("place_order", {})
            return await self._format_response(user_message, result)

        return None

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

        # Fast 0ms Python formatting for product lists (search_products)
        if isinstance(results, list):
            if not results:
                return {
                    "type": "response",
                    "text": "No matching products were found in our store.",
                    "options": None,
                }
            options = []
            for p in results:
                if isinstance(p, dict) and "name" in p and "id" in p:
                    pid = p["id"]
                    price_val = p.get("price", 0.0)
                    stock_val = p.get("stock", 0)
                    options.append(
                        {
                            "label": p["name"],
                            "value": pid,
                            "description": f"${price_val:.2f} • Stock: {stock_val}",
                            "actions": [
                                {"label": "Add to Cart", "value": f"add_{pid}"},
                                {"label": "View Details", "value": f"view_{pid}"},
                            ],
                        }
                    )
            count = len(results)
            text = f"Found {count} matching product{'s' if count != 1 else ''}:"
            return {
                "type": "options_response" if options else "response",
                "text": text,
                "options": options if options else None,
                "free_input_allowed": True,
            }

        # If empty results
        if isinstance(results, dict) and results.get("empty"):
            return {
                "type": "response",
                "text": results.get("message", "No results found."),
                "options": None,
            }

        # ── Cart result ─────────────────────────────────────────────
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

        # ── Orders result ────────────────────────────────────────────
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
                    }
                )
            return {
                "type": "options_response",
                "text": "\n".join(lines),
                "options": options,
                "free_input_allowed": True,
            }

        # ── Addresses result ─────────────────────────────────────────
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
                label = addr.get("label") or ""
                street = addr.get("street", "")
                city = addr.get("city", "")
                state = addr.get("state", "")
                is_default = addr.get("is_default", False)
                default_tag = " 🏠 Default" if is_default else ""
                display = f"{label or street}, {city}, {state}{default_tag}"
                lines.append(f"• {display}")
                options.append(
                    {
                        "label": label or street,
                        "value": aid,
                        "description": f"{street}, {city}, {state}{default_tag}",
                        "actions": [
                            {
                                "label": "Set Default",
                                "value": f"set_default_address_{aid}",
                            },
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

        # ── Facts / preferences result ────────────────────────────────
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

        # ── Seller catalog result ─────────────────────────────────────
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
            clean_text = response_text[:1000]
            return {"type": "response", "text": clean_text, "options": None}

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
