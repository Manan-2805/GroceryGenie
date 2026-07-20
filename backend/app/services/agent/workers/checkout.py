import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from app.db.models.address import Address
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.checkout")

CHECKOUT_DECIDER_PROMPT = """You are a shopping assistant that handles checkout operations.
Based on the user's goal, decide what checkout action to perform.

Available actions:
1. "view_cart_summary" - Show the current cart contents and total
2. "select_address" - Choose a delivery address (from saved addresses)
3. "place_order" - Place the order with the selected delivery address
4. "cancel_checkout" - Cancel the checkout process

Cart contents:
{cart_context}

Saved addresses:
{addresses_context}

User's goal:
{goal}

You MUST return a JSON object:
{{
  "action": "view_cart_summary" | "select_address" | "place_order" | "cancel_checkout",
  "address_id": "UUID of selected address or null",
  "reason": "Brief explanation"
}}

Output ONLY raw JSON. No markdown formatting."""


class CheckoutWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"CheckoutWorker starting subgoal: '{goal}'")

        db = self.context.get("db")
        user_id = self.context.get("user_id")

        if not db or not user_id:
            raise RuntimeError(
                "Database session or user ID missing from worker context"
            )

        # Get cart contents
        cart_result = await db.execute(
            select(CartItem)
            .options(joinedload(CartItem.product))
            .where(CartItem.user_id == user_id)
        )
        cart_items = list(cart_result.scalars().all())
        cart_context = json.dumps(
            [
                {
                    "product_id": str(ci.product_id),
                    "name": ci.product.name if ci.product else "Unknown",
                    "price": float(ci.product.price) if ci.product else 0,
                    "quantity": ci.quantity,
                    "total": float(ci.product.price * ci.quantity) if ci.product else 0,
                }
                for ci in cart_items
            ],
            indent=2,
        )

        # Get saved addresses
        addr_result = await db.execute(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.is_default.desc())
        )
        saved_addresses = list(addr_result.scalars().all())
        addresses_context = json.dumps(
            [
                {
                    "id": str(a.id),
                    "label": a.label,
                    "line1": a.line1,
                    "city": a.city,
                    "state": a.state,
                    "postal_code": a.postal_code,
                    "country": a.country,
                    "is_default": a.is_default,
                }
                for a in saved_addresses
            ],
            indent=2,
        )

        # Get cart total
        cart_total = sum(
            float(ci.product.price * ci.quantity) for ci in cart_items if ci.product
        )

        # Ask LLM to decide action
        try:
            response_str = await call_llm(
                system_prompt="You are a precise JSON checkout assistant.",
                user_prompt=CHECKOUT_DECIDER_PROMPT.format(
                    cart_context=cart_context,
                    addresses_context=addresses_context,
                    goal=goal,
                ),
                temperature=0.0,
                max_tokens=512,
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
            logger.error(f"CheckoutWorker failed to decide action: {e}")
            return {
                "status": "failed",
                "message": "Could not determine checkout action.",
                "cart_total": cart_total,
                "items_count": len(cart_items),
            }

        action = decision.get("action", "view_cart_summary")

        if action == "view_cart_summary":
            return {
                "status": "success",
                "action": "view_cart_summary",
                "cart": {
                    "items": [
                        {
                            "product_id": str(ci.product_id),
                            "name": ci.product.name if ci.product else "Unknown",
                            "price": float(ci.product.price) if ci.product else 0,
                            "quantity": ci.quantity,
                        }
                        for ci in cart_items
                    ],
                    "total": cart_total,
                    "items_count": len(cart_items),
                },
                "needs_permission": False,
            }

        if action == "select_address":
            address_id_str = decision.get("address_id")
            if not address_id_str:
                return {
                    "status": "success",
                    "action": "select_address",
                    "addresses": [
                        {
                            "id": str(a.id),
                            "label": a.label,
                            "line1": a.line1,
                            "city": a.city,
                            "state": a.state,
                            "country": a.country,
                        }
                        for a in saved_addresses
                    ],
                    "needs_selection": True,
                    "message": "Please select a delivery address.",
                }

            try:
                aid = uuid.UUID(address_id_str)
                selected = next((a for a in saved_addresses if a.id == aid), None)
                if selected:
                    return {
                        "status": "success",
                        "action": "address_selected",
                        "address": {
                            "id": str(selected.id),
                            "label": selected.label,
                            "line1": selected.line1,
                            "city": selected.city,
                            "state": selected.state,
                            "country": selected.country,
                        },
                        "needs_permission": True,
                        "summary": f"Deliver to {selected.label}: {selected.line1}, {selected.city}",
                    }
            except ValueError:
                pass

            return {"status": "failed", "message": "Selected address not found."}

        if action == "place_order":
            if not cart_items:
                return {"status": "failed", "message": "Cart is empty."}

            # Find the address (use decision address_id or default)
            address_id_str = decision.get("address_id")
            delivery_address = None
            if address_id_str:
                try:
                    aid = uuid.UUID(address_id_str)
                    delivery_address = next(
                        (a for a in saved_addresses if a.id == aid), None
                    )
                except ValueError:
                    pass

            if not delivery_address:
                delivery_address = next(
                    (a for a in saved_addresses if a.is_default), None
                )

            if not delivery_address:
                return {
                    "status": "failed",
                    "message": "No delivery address selected or set as default.",
                }

            # Calculate total and validate stock
            total = Decimal("0.00")
            order_items_to_create = []

            for cart_item in cart_items:
                product = cart_item.product
                if not product or not product.is_active:
                    return {
                        "status": "failed",
                        "message": f"Product '{cart_item.product_id}' is no longer active.",
                    }

                if product.stock < cart_item.quantity:
                    return {
                        "status": "failed",
                        "message": f"Insufficient stock for '{product.name}'. Available: {product.stock}",
                    }

                # Deduct stock
                stmt = (
                    update(Product)
                    .where(Product.id == product.id)
                    .where(Product.stock >= cart_item.quantity)
                    .values(
                        stock=Product.stock - cart_item.quantity,
                        sold_count=Product.sold_count + cart_item.quantity,
                    )
                    .returning(Product.id)
                )
                update_result = await db.execute(stmt)
                updated = update_result.scalar_one_or_none()

                if updated is None:
                    return {
                        "status": "failed",
                        "message": f"Failed to reserve stock for '{product.name}'.",
                    }

                item_total = product.price * cart_item.quantity
                total += item_total

                order_items_to_create.append(
                    OrderItem(
                        product_id=product.id,
                        quantity=cart_item.quantity,
                        price_at_purchase=product.price,
                    )
                )

            # Create order
            order = Order(
                customer_id=user_id,
                status=OrderStatus.placed,
                total=total,
                delivery_address={
                    "label": delivery_address.label,
                    "line1": delivery_address.line1,
                    "city": delivery_address.city,
                    "state": delivery_address.state,
                    "postal_code": delivery_address.postal_code,
                    "country": delivery_address.country,
                },
                items=order_items_to_create,
            )
            db.add(order)

            # Clear cart
            for cart_item in cart_items:
                await db.delete(cart_item)

            await db.commit()

            return {
                "status": "success",
                "action": "order_placed",
                "needs_permission": True,
                "order_id": str(order.id),
                "total": float(total),
                "delivery_address": delivery_address.label,
                "summary": f"Place order for €{float(total):.2f} to {delivery_address.label}?",
            }

        if action == "cancel_checkout":
            return {
                "status": "success",
                "action": "cancelled",
                "message": "Checkout has been cancelled.",
            }

        return {"status": "failed", "message": f"Unknown action: {action}"}
