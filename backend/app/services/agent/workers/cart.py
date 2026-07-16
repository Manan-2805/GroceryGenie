import json
import logging
from typing import Any

from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.cart")

CART_DECIDER_PROMPT = """You are a shopping assistant decider.
Your task is to analyze prior product query results and decide which product(s) and quantities the user wants to add or modify in their cart, based on the current goal.

Example goals:
- "add chosen item to cart" (choose the product discussed or found)
- "add the cheaper one to cart" (compare prices of products in prior results and choose the lower price)
- "add 2 packs of oat milk" (choose oat milk and quantity 2)

Prior subgoal results containing product lists:
{products_context}

User's goal:
{goal}

You MUST return a JSON object containing:
{{
  "action": "add_to_cart" or "remove_from_cart" or "update_cart_quantity",
  "product_id": "UUID string of the chosen product",
  "product_name": "Name of the chosen product",
  "quantity": integer quantity,
  "price": float price of the chosen product,
  "reason": "Brief reason for choosing this product (e.g. 'Cheapest option found')"
}}

Output ONLY raw JSON. No markdown formatting, no code blocks."""


class CartActionWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"CartActionWorker starting subgoal: '{goal}'")

        # 1. Gather products context from previous subgoals
        products_list: list[dict[str, Any]] = []
        for sg_res in self.subgoal_results.values():
            if sg_res.get("status") == "success" and isinstance(
                sg_res.get("output"), list
            ):
                products_list.extend(sg_res["output"])

        context_str = json.dumps(products_list, indent=2)
        user_prompt = CART_DECIDER_PROMPT.format(
            products_context=context_str, goal=goal
        )

        # 2. Ask LLM to make the decision
        try:
            response_str = await call_llm(
                system_prompt="You are a precise JSON decider.",
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=256,
            )

            cleaned = response_str.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            decision = json.loads(cleaned)
        except Exception as e:
            logger.error(f"CartActionWorker failed to decide action: {e}")
            # Fallback if parsing fails or no products present
            return {
                "needs_permission": False,
                "status": "failed",
                "message": "Could not determine cart action from context.",
            }

        action_type = decision.get("action", "add_to_cart")
        product_id = decision.get("product_id")
        product_name = decision.get("product_name", "Unknown Product")
        quantity = decision.get("quantity", 1)
        price = decision.get("price", 0.0)

        if not product_id:
            return {
                "needs_permission": False,
                "status": "failed",
                "message": "No product was selected for cart action.",
            }

        # 3. Return the proposed action payload with needs_permission=True
        # This will be intercepted by the Orchestrator to trigger the permission gate
        summary = f"Add {quantity}x {product_name} (€{price:.2f} each) to your cart?"
        if action_type == "remove_from_cart":
            summary = f"Remove {product_name} from your cart?"
        elif action_type == "update_cart_quantity":
            summary = f"Update {product_name} quantity in your cart to {quantity}?"

        return {
            "needs_permission": True,
            "action_type": action_type,
            "product_id": product_id,
            "product_name": product_name,
            "quantity": quantity,
            "price": price,
            "summary": summary,
            "reason": decision.get("reason", ""),
        }
