import logging
from typing import Any

from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.dietary")

DIETARY_SYSTEM_PROMPT = """You are a Dietary Fact Analyst.
Your task is to analyze product ingredients and description details, and provide factual dietary assessments (e.g., vegan/vegetarian/gluten-free status, allergen presence).

CRITICAL SAFETY GUARDRAILS:
1. NEVER assert or guarantee medical safety or allergy safety under any circumstances.
2. You may state ingredients or allergen facts (e.g., "contains wheat", "contains peanuts").
3. For any interpretation of safety, you MUST append a disclaimer redirecting the user to check the label or consult a professional.
   Disclaimer format: "Please check the product label or consult a qualified professional/medical practitioner before consuming if you have severe allergies."

Analyze the products data provided and answer the user's dietary question based ONLY on ingredients and description facts."""


class DietaryFactWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"DietaryFactWorker starting subgoal: '{goal}'")

        # Gather product details from previous subgoals
        products_to_analyze: list[dict[str, Any]] = []
        for _sg_id, sg_res in self.subgoal_results.items():
            if sg_res.get("status") == "success" and isinstance(sg_res.get("output"), list):
                products_to_analyze.extend(sg_res["output"])

        # Format products context
        context_str = ""
        if products_to_analyze:
            context_str += "Products to analyze:\n"
            for p in products_to_analyze:
                context_str += (
                    f"- Name: {p['name']}\n"
                    f"  Category: {p['category']}\n"
                    f"  Description/Ingredients: {p['description']}\n\n"
                )
        else:
            context_str = "No products found to analyze."

        user_prompt = f"Context:\n{context_str}\n\nGoal: {goal}"

        # Call LLM with strict safety prompt
        response = await call_llm(
            system_prompt=DIETARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=512,
        )

        # Force append the disclaimer if it wasn't returned by the LLM (double layer safety)
        safety_disclaimer = "Please check the product label or consult a qualified professional/medical practitioner before consuming if you have severe allergies."
        if safety_disclaimer.lower() not in response.lower():
            response += f"\n\n[Important Safety Notice]: {safety_disclaimer}"

        return {
            "dietary_analysis": response,
            "products_analyzed": [p["name"] for p in products_to_analyze],
        }
