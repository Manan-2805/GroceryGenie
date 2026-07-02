import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.order import Order, OrderItem
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.order")


class OrderStatusWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"OrderStatusWorker starting subgoal: '{goal}'")
        
        db = self.context.get("db")
        user_id = self.context.get("user_id")
        
        if not db or not user_id:
            raise RuntimeError("Database session or user ID missing from worker context")

        # Parse order ID if specified, otherwise fetch the most recent order
        order_id: uuid.UUID | None = None
        words = goal.split()
        for word in words:
            # Simple check to see if word is a UUID
            cleaned_word = word.replace(",", "").replace(".", "").strip()
            try:
                order_id = uuid.UUID(cleaned_word)
                break
            except ValueError:
                continue

        if order_id:
            query = (
                select(Order)
                .options(selectinload(Order.items).joinedload(OrderItem.product))
                .where(Order.id == order_id, Order.customer_id == user_id)
            )
        else:
            # Fetch the most recent order
            query = (
                select(Order)
                .options(selectinload(Order.items).joinedload(OrderItem.product))
                .where(Order.customer_id == user_id)
                .order_by(Order.created_at.desc())
                .limit(1)
            )

        result = await db.execute(query)
        order = result.scalar_one_or_none()

        if not order:
            return {"status": "not_found", "message": "No matching order found."}

        return {
            "status": "found",
            "order_id": str(order.id),
            "order_status": order.status.value,
            "total": float(order.total),
            "created_at": order.created_at.isoformat(),
            "items": [
                {
                    "name": item.product.name if item.product else "Unknown Product",
                    "quantity": item.quantity,
                    "price": float(item.price_at_purchase),
                }
                for item in order.items
            ]
        }
