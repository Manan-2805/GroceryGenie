import json
import logging
from typing import Any

from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker
from app.services.search import search_products

logger = logging.getLogger("app.services.agent.workers.product")

PARSER_SYSTEM_PROMPT = """You are a search parameter extractor.
Given a subgoal description for a product query, extract the parameters needed to search the product database.

The search parameters to extract are:
{
  "query": "The product search query terms (e.g. 'oat milk' or 'apple')",
  "category": "The product category (e.g. 'Dairy', 'Produce', 'Beverages') or null if not specified",
  "min_price": float value or null if not specified,
  "max_price": float value or null if not specified,
  "sort_by": "price_asc", "price_desc", "rating", "popularity" or null if not specified
}

Output ONLY raw JSON. No markdown backticks, no prose."""


class ProductQueryWorker(BaseWorker):
    async def run(self, goal: str) -> list[dict[str, Any]]:
        logger.info(f"ProductQueryWorker starting subgoal: '{goal}'")

        # 1. Parse subgoal goal via LLM into search filters
        try:
            parsed_str = await call_llm(
                system_prompt=PARSER_SYSTEM_PROMPT,
                user_prompt=goal,
                temperature=0.0,
                max_tokens=256,
            )

            # Clean markdown code block if present
            cleaned = parsed_str.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines).strip()

            params = json.loads(cleaned)
        except Exception as e:
            logger.error(f"ProductQueryWorker failed to parse subgoal: {e}")
            params = {
                "query": goal,
                "category": None,
                "min_price": None,
                "max_price": None,
                "sort_by": None,
            }

        # 2. Run hybrid search
        db = self.context.get("db")
        if not db:
            raise RuntimeError("Database session missing from worker context")

        query_text = params.get("query", "")
        category = params.get("category")
        min_price = params.get("min_price")
        max_price = params.get("max_price")

        # Map sort_by from parsed options
        params.get("sort_by")

        # Perform hybrid search
        products = await search_products(
            db=db,
            query_text=query_text,
            category=category,
            min_price=min_price,
            max_price=max_price,
            limit=10,
        )

        logger.info(
            f"ProductQueryWorker found {len(products)} products matching search."
        )

        # Serialize products for output
        return [
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "price": float(p.price),
                "stock": p.stock,
                "avg_rating": float(p.avg_rating),
                "sold_count": p.sold_count,
            }
            for p in products
        ]
