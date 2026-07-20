import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.models.enums import UserRole
from app.db.models.product import Product
from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.seller_product")

SELLER_PRODUCT_DECIDER_PROMPT = """You are a seller dashboard assistant that manages products.
Based on the user's goal, decide what product action to perform.

Available actions:
1. "list_products" - List all products owned by the seller
2. "get_product" - Get details of a specific product by name or ID
3. "create_product" - Create a new product (requires: name, description, category, price, stock)
4. "update_product" - Update an existing product (requires: product_id and fields)
5. "deactivate_product" - Soft-delete/deactivate a product

Seller's current products:
{products_context}

User's goal:
{goal}

You MUST return a JSON object:
{{
  "action": "list_products" | "get_product" | "create_product" | "update_product" | "deactivate_product",
  "product_id": "UUID or null",
  "product_data": {{
    "name": "...",
    "description": "...",
    "category": "...",
    "price": 0.0,
    "stock": 0
  }} or null,
  "reason": "Brief explanation"
}}

Output ONLY raw JSON. No markdown formatting."""


class SellerProductWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"SellerProductWorker starting subgoal: '{goal}'")

        db = self.context.get("db")
        seller_id = self.context.get("user_id")
        user_role = self.context.get("user_role")

        if not db or not seller_id:
            raise RuntimeError(
                "Database session or seller ID missing from worker context"
            )

        # Security check
        if user_role != UserRole.seller:
            return {
                "status": "forbidden",
                "message": "Access denied. Seller role required for product management.",
            }

        # Get seller's products
        result = await db.execute(
            select(Product)
            .where(Product.seller_id == seller_id)
            .order_by(Product.name.asc())
        )
        products = list(result.scalars().all())
        products_context = (
            json.dumps(
                [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "description": p.description[:100] if p.description else "",
                        "category": p.category,
                        "price": float(p.price),
                        "stock": p.stock,
                        "is_active": p.is_active,
                    }
                    for p in products
                ],
                indent=2,
            )
            if products
            else "No products yet."
        )

        # Ask LLM to decide action
        try:
            response_str = await call_llm(
                system_prompt="You are a precise JSON seller product manager.",
                user_prompt=SELLER_PRODUCT_DECIDER_PROMPT.format(
                    products_context=products_context,
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
            logger.error(f"SellerProductWorker failed to decide action: {e}")
            return {
                "status": "failed",
                "message": "Could not determine product action.",
            }

        action = decision.get("action", "list_products")

        if action == "list_products":
            return {
                "status": "success",
                "action": "list_products",
                "products": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "category": p.category,
                        "price": float(p.price),
                        "stock": p.stock,
                        "is_active": p.is_active,
                    }
                    for p in products
                ],
                "total_products": len(products),
            }

        if action == "get_product":
            product_id_str = decision.get("product_id")
            if product_id_str:
                try:
                    pid = uuid.UUID(product_id_str)
                    for p in products:
                        if p.id == pid:
                            return {
                                "status": "success",
                                "action": "get_product",
                                "product": {
                                    "id": str(p.id),
                                    "name": p.name,
                                    "description": p.description,
                                    "category": p.category,
                                    "price": float(p.price),
                                    "stock": p.stock,
                                    "is_active": p.is_active,
                                },
                            }
                except ValueError:
                    pass
            return {"status": "failed", "message": "Product not found."}

        if action == "create_product":
            prod_data = decision.get("product_data", {})
            if not prod_data.get("name") or not prod_data.get("price"):
                return {
                    "status": "failed",
                    "message": "Product name and price are required.",
                }

            product = Product(
                seller_id=seller_id,
                name=prod_data["name"],
                description=prod_data.get("description", ""),
                category=prod_data.get("category", "General"),
                price=Decimal(str(prod_data["price"])),
                stock=prod_data.get("stock", 0),
            )
            db.add(product)
            await db.commit()
            await db.refresh(product)

            return {
                "status": "success",
                "action": "create_product",
                "message": f"Product '{product.name}' created successfully.",
                "product": {
                    "id": str(product.id),
                    "name": product.name,
                    "price": float(product.price),
                    "stock": product.stock,
                },
            }

        if action == "update_product":
            product_id_str = decision.get("product_id")
            if not product_id_str:
                return {
                    "status": "failed",
                    "message": "Product ID required for update.",
                }

            try:
                pid = uuid.UUID(product_id_str)
                target = next((p for p in products if p.id == pid), None)
            except ValueError:
                target = None

            if not target:
                return {"status": "failed", "message": "Product not found."}

            prod_data = decision.get("product_data", {})
            if prod_data.get("name"):
                target.name = prod_data["name"]
            if prod_data.get("description") is not None:
                target.description = prod_data["description"]
            if prod_data.get("category"):
                target.category = prod_data["category"]
            if prod_data.get("price") is not None:
                target.price = Decimal(str(prod_data["price"]))
            if prod_data.get("stock") is not None:
                target.stock = prod_data["stock"]

            await db.commit()
            await db.refresh(target)

            return {
                "status": "success",
                "action": "update_product",
                "message": f"Product '{target.name}' updated.",
                "product": {
                    "id": str(target.id),
                    "name": target.name,
                    "price": float(target.price),
                    "stock": target.stock,
                },
            }

        if action == "deactivate_product":
            product_id_str = decision.get("product_id")
            if not product_id_str:
                return {"status": "failed", "message": "Product ID required."}

            try:
                pid = uuid.UUID(product_id_str)
                target = next((p for p in products if p.id == pid), None)
            except ValueError:
                target = None

            if not target:
                return {"status": "failed", "message": "Product not found."}

            target.is_active = False
            await db.commit()

            return {
                "status": "success",
                "action": "deactivate_product",
                "message": f"Product '{target.name}' has been deactivated.",
            }

        return {"status": "failed", "message": f"Unknown action: {action}"}
