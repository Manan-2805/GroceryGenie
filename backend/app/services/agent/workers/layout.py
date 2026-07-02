import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.db.models.product import Product
from app.services.agent.workers.base import BaseWorker
from app.services.rag.graph import get_adjacent_products

logger = logging.getLogger("app.services.agent.workers.layout")


class StoreLayoutWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"StoreLayoutWorker starting subgoal: '{goal}'")

        db = self.context.get("db")
        if not db:
            raise RuntimeError("Database session missing from worker context")

        # 1. Try to find product ID from previous subgoal outputs
        product_id: uuid.UUID | None = None
        product_name = ""
        
        for sg_res in self.subgoal_results.values():
            if sg_res.get("status") == "success" and isinstance(sg_res.get("output"), list):
                outputs = sg_res["output"]
                if outputs:
                    product_id = uuid.UUID(outputs[0]["id"])
                    product_name = outputs[0]["name"]
                    break

        # 2. If not found in previous subgoals, search product database by name
        if not product_id:
            # Try to extract potential product name from goal (e.g. "what's near oat milk")
            # We can run a simple query matching keywords
            words = [w for w in goal.split() if w.lower() not in ["what's", "near", "the", "find", "layout", "aisle"]]
            if words:
                keyword = " ".join(words)
                logger.info(f"Searching database for layout reference product: '{keyword}'")
                result = await db.execute(
                    select(Product)
                    .where(Product.is_active, Product.name.ilike(f"%{keyword}%"))
                    .limit(1)
                )
                product = result.scalar_one_or_none()
                if product:
                    product_id = product.id
                    product_name = product.name

        if not product_id:
            return {
                "status": "not_found",
                "message": "Could not identify which product to locate in store layout.",
            }

        # 3. Query Neo4j for adjacent items
        try:
            adjacent = get_adjacent_products(product_id)
            return {
                "status": "found",
                "product_name": product_name,
                "adjacent_products": adjacent,
            }
        except Exception as e:
            logger.error(f"StoreLayoutWorker Neo4j query failed: {e}")
            return {
                "status": "error",
                "message": f"Store layout service unavailable: {e}",
            }
