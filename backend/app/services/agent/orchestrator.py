import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cart import CartItem
from app.db.models.enums import UserRole
from app.services.agent.dag import execute_subgoal_dag
from app.services.agent.llm import call_llm, extract_json_from_response
from app.services.agent.memory import classify_and_store_fact, get_user_facts
from app.services.agent.workers.address import AddressWorker
from app.services.agent.workers.cart import CartActionWorker
from app.services.agent.workers.checkout import CheckoutWorker
from app.services.agent.workers.dietary import DietaryFactWorker
from app.services.agent.workers.explainer import ExplainerWorker
from app.services.agent.workers.layout import StoreLayoutWorker
from app.services.agent.workers.order import OrderStatusWorker
from app.services.agent.workers.product import ProductQueryWorker
from app.services.agent.workers.profile import ProfileWorker
from app.services.agent.workers.seller import SellerDashboardWorker
from app.services.agent.workers.seller_product import SellerProductWorker
from app.services.memory import (
    append_message_to_session,
    get_redis_client,
    get_session_history,
)

logger = logging.getLogger("app.services.agent.orchestrator")

# Initialize Langfuse client lazily (not at module level) to prevent startup crashes
_langfuse_client = None


def _get_langfuse() -> Any:
    """Get or create Langfuse client lazily. Returns False if disabled."""
    global _langfuse_client
    _langfuse_client = False
    return False


def _safe_langfuse_trace(**kwargs: Any) -> Any:
    """Safe wrapper for Langfuse trace creation."""
    lf = _get_langfuse()
    if not lf:
        return _NullTrace()
    try:
        return lf.trace(**kwargs)
    except Exception as e:
        logger.warning(f"Langfuse trace creation failed: {e}")
        return _NullTrace()


def _safe_langfuse_span(trace: Any, **kwargs: Any) -> Any:
    """Safe wrapper for Langfuse span creation."""
    if trace is None or isinstance(trace, _NullTrace):
        return _NullSpan()
    try:
        return trace.span(**kwargs)
    except Exception as e:
        logger.warning(f"Langfuse span creation failed: {e}")
        return _NullSpan()


class _NullTrace:
    """Null object pattern for when Langfuse is disabled."""

    def update(self, **_kwargs: Any) -> None:
        pass

    def span(self, **_kwargs: Any) -> Any:
        return _NullSpan()


class _NullSpan:
    """Null object pattern for Langfuse spans."""

    def end(self, **_kwargs: Any) -> None:
        pass


DECOMPOSITION_SYSTEM_PROMPT = """You are a task decomposer for a grocery shopping AI assistant.
Your job is to break down the user's natural language request into a list of subgoals.

Available worker classes:
1. ProductQueryWorker: Searches products (use for finding products, comparing prices/ratings).
2. DietaryFactWorker: Analyzes dietary requirements and ingredients (depends on ProductQueryWorker to supply product details).
3. OrderStatusWorker: Checks the status of past orders.
4. CartActionWorker: Proposes adding, updating or removing items in the shopping cart (depends on ProductQueryWorker to find the correct product ID/price).
5. ExplainerWorker: Summarizes or explains structured data into friendly language (depends on other workers to supply the data).
6. StoreLayoutWorker: Finds product store locations (aisle/section) and neighboring items (depends on ProductQueryWorker to supply product ID).
7. SellerDashboardWorker: Retrieves seller business stats (only spawn if role is 'seller').
8. AddressWorker: Manages saved addresses (list, create, update, delete).
9. CheckoutWorker: Handles cart summary, address selection, and order placement.
10. ProfileWorker: Manages user profile (view, update name, switch role, manage facts).
11. SellerProductWorker: Manages seller products (list, create, update, deactivate - only for 'seller' role).

Available frontend routes (use navigate_to to send user to the right page):
- /items - Browse grocery catalog
- /items/:id - Product detail page
- /cart - Shopping cart
- /checkout - Checkout page
- /orders - Order history
- /seller - Seller dashboard
- /inventory - Inventory management
- /fulfillment - Fulfillment queue
- /analysis - Sales analysis
- /settings - User settings
- /agent - AI assistant

User's standing facts/preferences: {facts}
Chat history: {history}

You must return a JSON list of subgoals with dependencies. Format:
[
  {{
    "id": "unique subgoal ID (e.g. A, B, C)",
    "type": "WorkerClassName",
    "goal": "Description of what this worker should accomplish",
    "depends_on": ["List of subgoal IDs this task depends on, or empty list"]
  }}
]

Output ONLY raw JSON. No markdown backticks, no prose."""

SYNTHESIS_SYSTEM_PROMPT = """You are a grocery shopping assistant.
Your job is to synthesize a friendly, natural language response to the user based on the results of several sub-tasks.

User's standing facts/preferences: {facts}
User's query: {query}

Sub-task results:
{results_context}

Create a friendly, helpful, conversational response. If any sub-task failed, explain gracefully.
If the results suggest navigating to a specific page (e.g. catalog, product detail, checkout, orders), you can propose a navigation intent.

If you need to ask the user a question with structured options, include them in the response:
{{
  "text": "Your question or response to the user",
  "navigate_to": "/path/to/page" or null,
  "navigate_label": "Label describing the navigation" or null,
  "options": [
    {{"label": "Option 1", "value": "option1", "description": "What this option does"}},
    {{"label": "Option 2", "value": "option2", "description": "What this option does"}}
  ] or null (if no options needed),
  "free_input_allowed": true or false (whether user can type custom response)
}}

If no options are needed, set "options" to null.
If you are just providing information (not asking a question), set both "options" and "free_input_allowed" to null/false.

Output ONLY raw JSON. No markdown backticks, no prose."""


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
        # Cache for user facts to avoid repeated DB calls
        self._facts_cache: str | None = None

    async def _get_facts(self) -> str:
        """Get user facts with caching within a turn."""
        if self._facts_cache is not None:
            return self._facts_cache
        facts = await get_user_facts(self.db, self.user_id)
        facts_str = "; ".join([f.fact_text for f in facts]) if facts else "None"
        self._facts_cache = facts_str
        return facts_str

    async def _emit_status(self, _status: str) -> dict[str, Any] | None:
        """Emit a status update to be sent as SSE event. Returns None if no streaming connection."""
        # Status events are handled at the SSE generator level
        return None

    async def run_turn(self, user_message: str) -> dict[str, Any]:
        turn_start_time = time.perf_counter()
        logger.info(
            f"AgentOrchestrator starting turn for user {self.user_id}, session {self.session_id}..."
        )

        redis_client = get_redis_client()

        # Check for pending action in Redis
        pending_key = f"chat:session:{self.session_id}:pending_action"
        pending_data_str = await redis_client.get(pending_key)

        start_step = time.perf_counter()
        if pending_data_str:
            pending_data = json.loads(pending_data_str)
            classification_prompt = f"""Analyze the user's input: '{user_message}'
We previously asked them to confirm this action: '{pending_data.get("summary", "an action")}'

Decide if the user is confirming (agreeing to proceed, e.g. "yes", "sure", "do it"), denying (declining/canceling, e.g. "no", "stop", "cancel"), or if their message is unrelated to this action.
Return JSON ONLY:
{{
  "intent": "confirm" or "deny" or "unrelated"
}}"""
            try:
                class_res = await call_llm(
                    system_prompt="You are a precise user intent classifier.",
                    user_prompt=classification_prompt,
                    temperature=0.0,
                    max_tokens=64,
                    call_type="intent_classifier",
                )
                cleaned_class = extract_json_from_response(class_res)
                class_data = json.loads(cleaned_class)
                intent = class_data.get("intent", "unrelated")
            except Exception as e:
                logger.error(f"Failed to classify pending action verbal response: {e}")
                intent = "unrelated"

            if intent == "confirm":
                await redis_client.delete(pending_key)
                logger.info(
                    f"[TIMING] Step 1: Handled confirmed pending action - Time: {time.perf_counter() - start_step:.4f}s"
                )
                return await self.execute_approved_mutation(
                    pending_data["action_type"],
                    {
                        "product_id": pending_data.get("product_id", ""),
                        "quantity": pending_data.get("quantity", 1),
                    },
                )

            if intent == "deny":
                await redis_client.delete(pending_key)
                cancel_text = "I've cancelled that action."
                await append_message_to_session(
                    str(self.session_id), "user", user_message
                )
                await append_message_to_session(
                    str(self.session_id), "assistant", cancel_text
                )
                logger.info(
                    f"[TIMING] Step 1: Handled denied pending action - Time: {time.perf_counter() - start_step:.4f}s"
                )
                return {
                    "type": "response",
                    "text": cancel_text,
                    "navigate_to": None,
                    "navigate_label": None,
                    "options": None,
                    "free_input_allowed": False,
                }

            # Unrelated turn: clear pending state and fall through to normal execution
            await redis_client.delete(pending_key)

        logger.info(
            f"[TIMING] Step 1: Checked pending action - Time: {time.perf_counter() - start_step:.4f}s"
        )

        # Check for multi-turn conversation state
        state_key = f"chat:session:{self.session_id}:state"
        state_data_str = await redis_client.get(state_key)

        if state_data_str:
            state_data = json.loads(state_data_str)
            state_type = state_data.get("type", "normal")

            if state_type == "awaiting_option_response":
                await redis_client.delete(state_key)

            elif state_type == "awaiting_confirmation":
                pass

        # 1. Load user's persistent facts (with caching)
        start_step = time.perf_counter()
        facts_str = await self._get_facts()

        # 2. Run fact classifier turn-by-turn
        await classify_and_store_fact(self.db, self.user_id, user_message)
        logger.info(
            f"[TIMING] Step 2: Fact retrieval & memory classification - Time: {time.perf_counter() - start_step:.4f}s"
        )

        # 3. Load Chat History from Redis
        start_step = time.perf_counter()
        history = await get_session_history(str(self.session_id))
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

        # 4. Quick scope check - detect out-of-scope queries early
        scope_check_prompt = f"""Determine if the following user query is related to grocery shopping, product management, order management, account/profile management, or general assistance within a grocery app.

User query: "{user_message}"

Return JSON ONLY:
{{
  "in_scope": true or false,
  "reason": "Brief explanation if out of scope, or empty string if in scope"
}}"""
        scope_check = None
        try:
            scope_response = await call_llm(
                system_prompt="You are a precise scope classifier.",
                user_prompt=scope_check_prompt,
                temperature=0.0,
                max_tokens=128,
                call_type="scope_check",
            )
            scope_data = json.loads(extract_json_from_response(scope_response))
            if scope_data.get("in_scope") is False:
                scope_check = scope_data.get(
                    "reason", "That's outside my capabilities."
                )
        except Exception as e:
            logger.debug(f"Scope check failed, proceeding normally: {e}")

        logger.info(
            f"[TIMING] Step 3: History loading & Scope check - Time: {time.perf_counter() - start_step:.4f}s"
        )

        if scope_check:
            response_text = f"I'm a grocery shopping assistant, so I can't help with that. {scope_check} Is there anything related to our grocery catalog, your cart, orders, or account that I can assist you with?"
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", response_text
            )
            logger.info(
                f"[TIMING] Total turn execution time (out of scope): {time.perf_counter() - turn_start_time:.4f}s"
            )
            return {
                "type": "response",
                "text": response_text,
                "navigate_to": None,
                "navigate_label": None,
                "options": None,
                "free_input_allowed": False,
            }

        # 5. Decompose user message into sub-goals
        start_step = time.perf_counter()
        facts_context = facts_str if facts_str else "None"
        history_context = history_str if history_str else "None"

        decomposition_prompt = DECOMPOSITION_SYSTEM_PROMPT.format(
            facts=facts_context, history=history_context
        )

        try:
            decomp_response = await call_llm(
                system_prompt="You are a precise task decomposer.",
                user_prompt=f"Decompose this request: '{user_message}'\n\nContext:\n{decomposition_prompt}",
                temperature=0.0,
                max_tokens=512,
                call_type="decomposition",
            )

            cleaned_decomp = extract_json_from_response(decomp_response)
            subgoals = json.loads(cleaned_decomp)
        except Exception as e:
            logger.error(f"Orchestrator failed to decompose query: {e}")
            subgoals = []

        logger.info(
            f"[TIMING] Step 4: Subgoal decomposition - Time: {time.perf_counter() - start_step:.4f}s (spawning {len(subgoals)} subgoals)"
        )

        # 5. Initialize Langfuse Trace (safe)
        trace = _safe_langfuse_trace(
            name="grocerygenie-orchestrator-turn",
            user_id=str(self.user_id),
            session_id=str(self.session_id),
            input=user_message,
        )

        # 6. Execute Subgoal DAG
        start_step = time.perf_counter()
        worker_classes = {
            "ProductQueryWorker": ProductQueryWorker,
            "DietaryFactWorker": DietaryFactWorker,
            "OrderStatusWorker": OrderStatusWorker,
            "CartActionWorker": CartActionWorker,
            "ExplainerWorker": ExplainerWorker,
            "StoreLayoutWorker": StoreLayoutWorker,
            "SellerDashboardWorker": SellerDashboardWorker,
            "AddressWorker": AddressWorker,
            "CheckoutWorker": CheckoutWorker,
            "ProfileWorker": ProfileWorker,
            "SellerProductWorker": SellerProductWorker,
        }

        context = {
            "db": self.db,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "user_facts": facts_str,
        }

        async def worker_runner(
            subgoal: dict[str, Any], results: dict[str, Any]
        ) -> Any:
            worker_type = subgoal["type"]
            goal_text = subgoal["goal"]
            subgoal_id = subgoal["id"]

            if worker_type not in worker_classes:
                raise ValueError(f"Unknown worker type: {worker_type}")

            span = _safe_langfuse_span(
                trace,
                name=f"worker-{worker_type}-{subgoal_id}",
                input=goal_text,
            )

            worker_inst = worker_classes[worker_type](context, results)

            logger.info(
                f"[TIMING] Subgoal {subgoal_id} ({worker_type}) starting: '{goal_text}'"
            )
            worker_start = time.perf_counter()
            retries = 2
            while retries >= 0:
                try:
                    res = await worker_inst.run(goal_text)
                    span.end(output=str(res))
                    elapsed = time.perf_counter() - worker_start
                    logger.info(
                        f"[TIMING] Subgoal {subgoal_id} ({worker_type}) finished in {elapsed:.4f}s"
                    )
                    return res
                except Exception as exc:
                    if retries == 0:
                        span.end(output=f"Error after retries: {exc}", level="ERROR")
                        elapsed = time.perf_counter() - worker_start
                        logger.error(
                            f"[TIMING] Subgoal {subgoal_id} ({worker_type}) failed after retries in {elapsed:.4f}s: {exc}"
                        )
                        raise
                    retries -= 1
                    logger.warning(
                        f"Worker {worker_type} failed, retrying... ({retries} left)"
                    )
            return None

        # Progress callback for logging worker progress
        async def progress_callback(message: str) -> None:
            logger.debug(f"DAG Progress: {message}")

        dag_results = await execute_subgoal_dag(
            subgoals,
            worker_runner,
            context,
            progress_callback=progress_callback,
        )
        logger.info(
            f"[TIMING] Step 5: Executing subgoal DAG - Time: {time.perf_counter() - start_step:.4f}s"
        )

        # 7. Check if any worker proposed a sensitive cart/checkout/profile mutation
        start_step = time.perf_counter()
        proposed_mutation: dict[str, Any] | None = None
        for res in dag_results.values():
            if res.get("status") == "success" and isinstance(res.get("output"), dict):
                output = res["output"]
                if output.get("needs_permission"):
                    proposed_mutation = output
                    break

        logger.info(
            f"[TIMING] Step 6: Checked proposed mutations - Time: {time.perf_counter() - start_step:.4f}s"
        )

        # 8. Emit permission request if needed
        if proposed_mutation:
            pending_key = f"chat:session:{self.session_id}:pending_action"
            await redis_client.set(
                pending_key,
                json.dumps(
                    {
                        "action_type": proposed_mutation.get(
                            "action_type", proposed_mutation.get("action", "unknown")
                        ),
                        "product_id": proposed_mutation.get("product_id", ""),
                        "quantity": proposed_mutation.get("quantity", 1),
                        "summary": proposed_mutation["summary"],
                    }
                ),
                ex=600,
            )

            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id),
                "assistant",
                f"[Permission Required] {proposed_mutation['summary']}",
            )

            trace.update(output="PAUSED: Permission Required")
            logger.info(
                f"[TIMING] Total turn execution time (permission paused): {time.perf_counter() - turn_start_time:.4f}s"
            )

            return {
                "type": "permission_request",
                "action": proposed_mutation.get(
                    "action_type", proposed_mutation.get("action", "unknown")
                ),
                "summary": proposed_mutation["summary"],
                "payload": proposed_mutation.get("payload", proposed_mutation),
            }

        # 9. Perform Synthesis
        start_step = time.perf_counter()
        results_str = json.dumps(dag_results, indent=2)
        synthesis_prompt = SYNTHESIS_SYSTEM_PROMPT.format(
            facts=facts_context, query=user_message, results_context=results_str
        )

        try:
            synthesis_response = await call_llm(
                system_prompt="You are a helpful synthesizer.",
                user_prompt=synthesis_prompt,
                temperature=0.2,
                max_tokens=512,
                call_type="synthesis",
            )

            cleaned_synth = extract_json_from_response(synthesis_response)
            synth_data = json.loads(cleaned_synth)

            # Handle structured options
            if synth_data.get("options") and len(synth_data["options"]) > 0:
                # Store state so next turn can handle the option response
                state_key = f"chat:session:{self.session_id}:state"
                await redis_client.set(
                    state_key,
                    json.dumps(
                        {
                            "type": "awaiting_option_response",
                            "question": synth_data.get("text", ""),
                            "options": synth_data["options"],
                        }
                    ),
                    ex=600,
                )

                response_data = {
                    "type": "options_response",
                    "text": synth_data["text"],
                    "options": synth_data["options"],
                    "free_input_allowed": synth_data.get("free_input_allowed", True),
                    "navigate_to": synth_data.get("navigate_to"),
                    "navigate_label": synth_data.get("navigate_label"),
                }
            else:
                response_data = {
                    "type": "response",
                    "text": synth_data["text"],
                    "navigate_to": synth_data.get("navigate_to"),
                    "navigate_label": synth_data.get("navigate_label"),
                    "options": None,
                    "free_input_allowed": False,
                }

        except Exception as e:
            logger.error(f"Failed to synthesize final answer: {e}")
            response_data = {
                "type": "response",
                "text": "I processed your request, but was unable to format the final answer. How else can I help you?",
                "navigate_to": None,
                "navigate_label": None,
                "options": None,
                "free_input_allowed": False,
            }

        logger.info(
            f"[TIMING] Step 7: Answer synthesis - Time: {time.perf_counter() - start_step:.4f}s"
        )

        # 10. Update Redis Session Buffer
        start_step = time.perf_counter()
        await append_message_to_session(str(self.session_id), "user", user_message)
        await append_message_to_session(
            str(self.session_id), "assistant", response_data["text"]
        )

        trace.update(output=response_data["text"])
        logger.info(
            f"[TIMING] Step 8: Updated session buffer - Time: {time.perf_counter() - start_step:.4f}s"
        )

        total_time = time.perf_counter() - turn_start_time
        logger.info(f"[TIMING] Total turn execution time: {total_time:.4f}s")

        return response_data

    async def execute_approved_mutation(
        self, action_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Executes a mutation after user approval. Supports both cart and profile actions."""
        logger.info(f"Orchestrator executing approved mutation: {action_type}...")

        trace = _safe_langfuse_trace(
            name="grocerygenie-execute-mutation",
            user_id=str(self.user_id),
            session_id=str(self.session_id),
            input=f"approved_mutation: {action_type}",
        )

        try:
            # Handle role/profile mutations
            if action_type in ("switch_to_seller", "switch_to_customer", "switch_role"):
                new_role = (
                    UserRole.seller if "seller" in action_type else UserRole.customer
                )
                from app.db.models.user import User

                user_result = await self.db.execute(
                    select(User).where(User.id == self.user_id)
                )
                user = user_result.scalar_one_or_none()
                if user:
                    user.role = new_role
                    await self.db.commit()
                    self.user_role = new_role
                    response_text = (
                        f"Your role has been switched to '{new_role.value}'."
                    )
                else:
                    response_text = "User not found."
                trace.update(output=response_text)
                await append_message_to_session(
                    str(self.session_id), "assistant", response_text
                )
                return {"type": "response", "text": response_text}

            # Handle create_product mutation
            if action_type == "create_product":
                from decimal import Decimal

                from app.db.models.product import Product

                prod_data = payload.get("product_data", payload)
                product = Product(
                    seller_id=self.user_id,
                    name=prod_data.get("name", "Unknown Product"),
                    description=prod_data.get("description", ""),
                    category=prod_data.get("category", "General"),
                    price=Decimal(str(prod_data.get("price", 0))),
                    stock=prod_data.get("stock", 0),
                )
                self.db.add(product)
                await self.db.commit()
                await self.db.refresh(product)
                response_text = (
                    f"Product '{product.name}' has been created successfully."
                )
                trace.update(output=response_text)
                await append_message_to_session(
                    str(self.session_id), "assistant", response_text
                )
                return {"type": "response", "text": response_text}

            # Handle update_product mutation
            if action_type == "update_product":
                from decimal import Decimal

                from app.db.models.product import Product

                product_id_str = payload.get("product_id", "")
                if not product_id_str:
                    return {
                        "type": "response",
                        "text": "Product ID is required for update.",
                    }
                product_id = uuid.UUID(product_id_str)
                p_res = await self.db.execute(
                    select(Product).where(
                        Product.id == product_id, Product.seller_id == self.user_id
                    )
                )
                db_product = p_res.scalar_one_or_none()
                if not db_product:
                    return {"type": "response", "text": "Product not found."}
                prod_data = payload.get("product_data", payload)
                if prod_data.get("name"):
                    db_product.name = prod_data["name"]
                if prod_data.get("description") is not None:
                    db_product.description = prod_data["description"]
                if prod_data.get("price") is not None:
                    db_product.price = Decimal(str(prod_data["price"]))
                if prod_data.get("stock") is not None:
                    db_product.stock = prod_data["stock"]
                await self.db.commit()
                response_text = f"Product '{db_product.name}' has been updated."
                trace.update(output=response_text)
                await append_message_to_session(
                    str(self.session_id), "assistant", response_text
                )
                return {"type": "response", "text": response_text}

            # Handle cart actions (require product_id)
            product_id_str = payload.get("product_id", "")
            if not product_id_str:
                return {
                    "type": "response",
                    "text": "No product specified for this action.",
                }

            product_id = uuid.UUID(product_id_str)
            quantity = payload.get("quantity", 1)

            if action_type == "add_to_cart":
                p_res = await self.db.execute(
                    select(Product).where(Product.id == product_id)
                )
                db_product = p_res.scalar_one_or_none()
                if not db_product or db_product.stock < quantity:
                    return {
                        "type": "response",
                        "text": "Sorry, that product is no longer in stock.",
                    }

                cart_res = await self.db.execute(
                    select(CartItem).where(
                        CartItem.user_id == self.user_id,
                        CartItem.product_id == product_id,
                    )
                )
                cart_item = cart_res.scalar_one_or_none()
                if cart_item:
                    cart_item.quantity += quantity
                else:
                    cart_item = CartItem(
                        user_id=self.user_id, product_id=product_id, quantity=quantity
                    )
                    self.db.add(cart_item)

                await self.db.commit()
                response_text = (
                    f"I've added {quantity}x {db_product.name} to your cart."
                )

            elif action_type == "remove_from_cart":
                await self.db.execute(
                    delete(CartItem).where(
                        CartItem.user_id == self.user_id,
                        CartItem.product_id == product_id,
                    )
                )
                await self.db.commit()
                response_text = "I've removed that item from your cart."
            else:
                response_text = "I processed the approved action."

            await append_message_to_session(
                str(self.session_id), "assistant", response_text
            )
            trace.update(output=response_text)
            return {"type": "response", "text": response_text}

        except Exception as e:
            logger.error(f"Failed to execute approved mutation: {e}")
            trace.update(output=f"Error: {e}")
            return {
                "type": "response",
                "text": f"I encountered an error trying to complete that action: {str(e)}",
            }
