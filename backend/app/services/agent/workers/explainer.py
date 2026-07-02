import logging

from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.explainer")

EXPLAINER_SYSTEM_PROMPT = """You are a shopping explanation assistant.
Your job is to summarize technical or structured data (such as product details, comparison results, or order status timelines) into simple, friendly, plain language that a customer can easily understand.

Answer the user's question directly based on the context provided. Keep it concise, helpful and clear."""


class ExplainerWorker(BaseWorker):
    async def run(self, goal: str) -> str:
        logger.info(f"ExplainerWorker starting subgoal: '{goal}'")

        # Format preceding subgoal results as context
        context_parts = []
        for sg_id, sg_res in self.subgoal_results.items():
            context_parts.append(f"Subgoal {sg_id} ({sg_res.get('status')}):")
            context_parts.append(str(sg_res.get("output", "")))

        context_str = "\n\n".join(context_parts)
        user_prompt = f"Context data:\n{context_str}\n\nGoal: {goal}"

        return await call_llm(
            system_prompt=EXPLAINER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=512,
        )
