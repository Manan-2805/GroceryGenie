import logging
from typing import Any

from sqlalchemy import func, select

from app.db.models.enums import OrderStatus, UserRole
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.seller")


class SellerDashboardWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"SellerDashboardWorker starting subgoal: '{goal}'")

        db = self.context.get("db")
        seller_id = self.context.get("user_id")
        user_role = self.context.get("user_role")

        if not db or not seller_id:
            raise RuntimeError(
                "Database session or seller ID missing from worker context"
            )

        # Security check: must be a seller
        if user_role != UserRole.seller:
            return {
                "status": "forbidden",
                "message": "Access denied. Seller role required for dashboard details.",
            }

        # 1. Fetch low stock items (stock <= 5)
        low_stock_query = select(Product).where(
            Product.seller_id == seller_id,
            Product.is_active,
            Product.stock <= 5,
        )
        low_stock_result = await db.execute(low_stock_query)
        low_stock_products = low_stock_result.scalars().all()

        # 2. Fetch pending orders count
        pending_orders_query = (
            select(func.count(Order.id.distinct()))
            .join(OrderItem)
            .join(Product)
            .where(
                Product.seller_id == seller_id,
                Order.status != OrderStatus.delivered,
            )
        )
        pending_orders_result = await db.execute(pending_orders_query)
        pending_count = pending_orders_result.scalar() or 0

        # 3. Fetch summary stats (total products, total sold)
        stats_query = select(
            func.count(Product.id), func.sum(Product.sold_count)
        ).where(
            Product.seller_id == seller_id,
            Product.is_active,
        )
        stats_result = await db.execute(stats_query)
        stats_row = stats_result.first()
        total_products = stats_row[0] if stats_row and stats_row[0] else 0
        total_sold = stats_row[1] if stats_row and stats_row[1] else 0

        return {
            "status": "success",
            "pending_orders_count": pending_count,
            "low_stock_items": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "stock": p.stock,
                }
                for p in low_stock_products
            ],
            "stats": {
                "total_products": total_products,
                "total_sold": total_sold,
            },
        }
