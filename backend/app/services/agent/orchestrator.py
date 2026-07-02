import json
import logging
import uuid
from typing import Any

from langfuse import Langfuse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.cart import CartItem
from app.db.models.enums import UserRole
from app.db.models.product import Product
from app.services.agent.dag import execute_subgoal_dag
from app.services.agent.llm import call_llm
from app.services.agent.memory import classify_and_store_fact, get_user_facts
from app.services.agent.workers.cart import CartActionWorker
from app.services.agent.workers.dietary import DietaryFactWorker
from app.services.agent.workers.explainer import ExplainerWorker
from app.services.agent.workers.layout import StoreLayoutWorker
from app.services.agent.workers.order import OrderStatusWorker
from app.services.agent.workers.product import ProductQueryWorker
from app.services.agent.workers.seller import SellerDashboardWorker
from app.services.memory import append_message_to_session, get_session_history

logger = logging.getLogger("app.services.agent.orchestrator")

# Initialize Langfuse client
langfuse_client = Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=settings.LANGFUSE_HOST,
)

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

Respond in this JSON format:
{{
  "text": "Your friendly conversational response to the user",
  "navigate_to": "/path/to/page" or null,
  "navigate_label": "Label describing the navigation (e.g. 'Opening your cart...')" or null
}}

Output ONLY raw JSON. No markdown backticks, no prose."""


class AgentOrchestrator:
    def __init__(self, db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, user_role: UserRole):
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.user_role = user_role

    async def run_turn(self, user_message: str) -> dict[str, Any]:
        logger.info(f"AgentOrchestrator starting turn for user {self.user_id}, session {self.session_id}...")

        # 1. Load user's persistent facts
        facts = await get_user_facts(self.db, self.user_id)
        facts_str = "; ".join([f.fact_text for f in facts])

        # 2. Run fact classifier turn-by-turn
        await classify_and_store_fact(self.db, self.user_id, user_message)

        # 3. Load Chat History from Redis
        history = await get_session_history(str(self.session_id))
        history_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

        # 4. Decompose user message into sub-goals
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
            )
            
            cleaned_decomp = decomp_response.strip()
            if cleaned_decomp.startswith("```"):
                lines = cleaned_decomp.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned_decomp = "\n".join(lines).strip()

            subgoals = json.loads(cleaned_decomp)
        except Exception as e:
            logger.error(f"Orchestrator failed to decompose query: {e}")
            subgoals = []

        # 5. Initialize Langfuse Trace
        trace = langfuse_client.trace(
            name="grocerygenie-orchestrator-turn",
            user_id=str(self.user_id),
            session_id=str(self.session_id),
            input=user_message,
        )

        # 6. Execute Subgoal DAG
        worker_classes = {
            "ProductQueryWorker": ProductQueryWorker,
            "DietaryFactWorker": DietaryFactWorker,
            "OrderStatusWorker": OrderStatusWorker,
            "CartActionWorker": CartActionWorker,
            "ExplainerWorker": ExplainerWorker,
            "StoreLayoutWorker": StoreLayoutWorker,
            "SellerDashboardWorker": SellerDashboardWorker,
        }

        context = {
            "db": self.db,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "user_facts": facts_str,
        }

        async def worker_runner(subgoal: dict[str, Any], results: dict[str, Any]) -> Any:
            worker_type = subgoal["type"]
            goal_text = subgoal["goal"]
            subgoal_id = subgoal["id"]

            if worker_type not in worker_classes:
                raise ValueError(f"Unknown worker type: {worker_type}")

            # Instantiate child span in Langfuse
            span = trace.span(
                name=f"worker-{worker_type}-{subgoal_id}",
                input=goal_text,
            )

            worker_inst = worker_classes[worker_type](context, results)
            
            # Retry mechanism (max 2)
            retries = 2
            while retries >= 0:
                try:
                    res = await worker_inst.run(goal_text)
                    span.end(output=str(res))
                    return res
                except Exception as exc:
                    if retries == 0:
                        span.end(output=f"Error after retries: {exc}", level="ERROR")
                        raise
                    retries -= 1
                    logger.warning(f"Worker {worker_type} failed, retrying... ({retries} left)")
            return None

        dag_results = await execute_subgoal_dag(subgoals, worker_runner, context)

        # 7. Check if any worker proposed a sensitive cart/checkout mutation
        proposed_mutation: dict[str, Any] | None = None
        for res in dag_results.values():
            if res.get("status") == "success" and isinstance(res.get("output"), dict):
                output = res["output"]
                if output.get("needs_permission"):
                    proposed_mutation = output
                    break

        # 8. Emit permission request if needed
        if proposed_mutation:
            # Append turn info to Redis history
            await append_message_to_session(str(self.session_id), "user", user_message)
            await append_message_to_session(
                str(self.session_id), "assistant", f"[Permission Required] {proposed_mutation['summary']}"
            )
            
            trace.end(output="PAUSED: Permission Required")
            
            return {
                "type": "permission_request",
                "action": proposed_mutation["action_type"],
                "summary": proposed_mutation["summary"],
                "payload": {
                    "product_id": proposed_mutation["product_id"],
                    "quantity": proposed_mutation["quantity"],
                    "action_type": proposed_mutation["action_type"],
                }
            }

        # 9. Perform Synthesis
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
            )
            
            cleaned_synth = synthesis_response.strip()
            if cleaned_synth.startswith("```"):
                lines = cleaned_synth.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned_synth = "\n".join(lines).strip()

            synth_data = json.loads(cleaned_synth)
        except Exception as e:
            logger.error(f"Failed to synthesize final answer: {e}")
            synth_data = {
                "text": "I processed your request, but was unable to format the final answer. How else can I help you?",
                "navigate_to": None,
                "navigate_label": None,
            }

        # 10. Update Redis Session Buffer
        await append_message_to_session(str(self.session_id), "user", user_message)
        await append_message_to_session(str(self.session_id), "assistant", synth_data["text"])

        trace.end(output=synth_data["text"])

        return {
            "type": "response",
            "text": synth_data["text"],
            "navigate_to": synth_data.get("navigate_to"),
            "navigate_label": synth_data.get("navigate_label"),
        }

    async def execute_approved_mutation(self, action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Executes a cart mutation after user approval."""
        logger.info(f"Orchestrator executing approved mutation: {action_type}...")
        
        # We can implement direct execution using database logic
        
        product_id = uuid.UUID(payload["product_id"])
        quantity = payload.get("quantity", 1)
        
        # Instantiate trace
        trace = langfuse_client.trace(
            name="grocerygenie-execute-mutation",
            user_id=str(self.user_id),
            session_id=str(self.session_id),
            input=f"approved_mutation: {action_type}",
        )

        try:
            if action_type == "add_to_cart":
                # Execute db cart addition
                
                # Check product stock
                p_res = await self.db.execute(select(Product).where(Product.id == product_id))
                product = p_res.scalar_one_or_none()
                if not product or product.stock < quantity:
                    return {"type": "response", "text": "Sorry, that product is no longer in stock."}
                
                cart_res = await self.db.execute(
                    select(CartItem).where(CartItem.user_id == self.user_id, CartItem.product_id == product_id)
                )
                cart_item = cart_res.scalar_one_or_none()
                if cart_item:
                    cart_item.quantity += quantity
                else:
                    cart_item = CartItem(user_id=self.user_id, product_id=product_id, quantity=quantity)
                    self.db.add(cart_item)
                
                await self.db.commit()
                response_text = f"I've added {quantity}x {product.name} to your cart."

            elif action_type == "remove_from_cart":
                await self.db.execute(
                    delete(CartItem).where(CartItem.user_id == self.user_id, CartItem.product_id == product_id)
                )
                await self.db.commit()
                response_text = "I've removed that item from your cart."
            else:
                response_text = "I processed the approved action."

            # Update Redis session buffer
            await append_message_to_session(
                str(self.session_id), "assistant", response_text
            )
            trace.end(output=response_text)
            return {"type": "response", "text": response_text}
            
        except Exception as e:
            logger.error(f"Failed to execute approved mutation: {e}")
            trace.end(output=f"Error: {e}", level="ERROR")
            return {"type": "response", "text": "I encountered an error trying to complete that action."}
