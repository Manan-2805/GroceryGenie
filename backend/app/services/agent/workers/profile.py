import json
import logging
from typing import Any

from sqlalchemy import select

from app.db.models.user import User
from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.profile")

PROFILE_DECIDER_PROMPT = """You are a shopping assistant that manages user profiles.
Based on the user's goal, decide what profile action to perform.

Available actions:
1. "view_profile" - Show user profile information (name, email, role)
2. "update_name" - Update the user's display name
3. "switch_to_seller" - Switch account to seller role
4. "switch_to_customer" - Switch account to customer role
5. "view_facts" - Show saved persistent facts/preferences
6. "delete_fact" - Delete a saved fact by its text content

User's current profile:
{profile_context}

User's saved facts:
{facts_context}

User's goal:
{goal}

You MUST return a JSON object:
{{
  "action": "view_profile" | "update_name" | "switch_to_seller" | "switch_to_customer" | "view_facts" | "delete_fact",
  "new_name": "New display name or null",
  "fact_text": "Fact text to delete or null",
  "reason": "Brief explanation"
}}

Output ONLY raw JSON. No markdown formatting."""


class ProfileWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"ProfileWorker starting subgoal: '{goal}'")

        db = self.context.get("db")
        user_id = self.context.get("user_id")
        user_role = self.context.get("user_role")

        if not db or not user_id:
            raise RuntimeError(
                "Database session or user ID missing from worker context"
            )

        # Get user profile
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return {"status": "failed", "message": "User not found."}

        profile_context = json.dumps(
            {
                "name": user.name,
                "email": user.email,
                "role": user_role.value if user_role else user.role.value,
            },
            indent=2,
        )

        # Get saved facts
        from app.db.models.memory import PersistentFact

        fact_result = await db.execute(
            select(PersistentFact)
            .where(PersistentFact.user_id == user_id)
            .order_by(PersistentFact.created_at.desc())
        )
        facts = list(fact_result.scalars().all())
        facts_context = (
            json.dumps(
                [
                    {
                        "id": str(f.id),
                        "fact_text": f.fact_text,
                        "category": f.category.value if f.category else "other",
                    }
                    for f in facts
                ],
                indent=2,
            )
            if facts
            else "No saved facts."
        )

        # Ask LLM to decide action
        try:
            response_str = await call_llm(
                system_prompt="You are a precise JSON profile manager.",
                user_prompt=PROFILE_DECIDER_PROMPT.format(
                    profile_context=profile_context,
                    facts_context=facts_context,
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
            logger.error(f"ProfileWorker failed to decide action: {e}")
            return {
                "status": "failed",
                "message": "Could not determine profile action.",
            }

        action = decision.get("action", "view_profile")

        if action == "view_profile":
            return {
                "status": "success",
                "action": "view_profile",
                "profile": {
                    "name": user.name,
                    "email": user.email,
                    "role": user.role.value,
                },
                "facts": [
                    {
                        "id": str(f.id),
                        "fact_text": f.fact_text,
                        "category": f.category.value if f.category else "other",
                    }
                    for f in facts
                ],
            }

        if action == "update_name":
            new_name = decision.get("new_name")
            if not new_name:
                return {"status": "failed", "message": "No name provided."}

            user.name = new_name
            await db.commit()
            return {
                "status": "success",
                "action": "update_name",
                "message": f"Name updated to '{new_name}'.",
                "profile": {
                    "name": user.name,
                    "email": user.email,
                    "role": user.role.value,
                },
            }

        if action in ("switch_to_seller", "switch_to_customer"):
            new_role = "seller" if action == "switch_to_seller" else "customer"
            if user.role.value == new_role:
                return {
                    "status": "success",
                    "action": action,
                    "message": f"You are already in {new_role} mode.",
                }

            return {
                "status": "success",
                "action": action,
                "needs_permission": True,
                "summary": f"Switch your account to {new_role} mode?",
                "new_role": new_role,
            }

        if action == "view_facts":
            return {
                "status": "success",
                "action": "view_facts",
                "facts": [
                    {
                        "id": str(f.id),
                        "fact_text": f.fact_text,
                        "category": f.category.value if f.category else "other",
                    }
                    for f in facts
                ],
            }

        if action == "delete_fact":
            fact_text = decision.get("fact_text", "").strip().lower()
            if not fact_text:
                return {
                    "status": "failed",
                    "message": "No fact text provided for deletion.",
                }

            target = None
            for f in facts:
                if fact_text in f.fact_text.lower():
                    target = f
                    break

            if not target:
                return {"status": "failed", "message": "Fact not found."}

            await db.delete(target)
            await db.commit()
            return {
                "status": "success",
                "action": "delete_fact",
                "message": f"Fact deleted: '{target.fact_text}'",
            }

        return {"status": "failed", "message": f"Unknown action: {action}"}
