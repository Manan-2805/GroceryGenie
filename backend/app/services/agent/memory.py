import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.models.enums import FactCategory
from app.db.models.memory import PersistentFact
from app.services.agent.llm import call_llm, extract_json_from_response

logger = logging.getLogger("app.services.agent.memory")

CLASSIFIER_SYSTEM_PROMPT = """You are an accurate, rule-based text classifier.
Your task is to analyze a user statement and extract any durable personal facts or standing instructions that are intended to be remembered long-term.

A durable personal fact or standing instruction includes:
1. Dietary requirements or restrictions ("I am vegan", "lactose intolerant").
2. Serious allergies ("I'm highly allergic to tree nuts").
3. Strong standing shopping preferences ("I prefer organic items", "never suggest brand X").
4. Clear standing instructions for actions ("Always compare by unit price first").

Do NOT extract:
1. One-off purchase requests ("add tomatoes to my cart").
2. Ordinary search queries ("find lactose-free milk").
3. Ephemeral questions ("what is the price of almond milk?").
4. Conversational filler ("hello", "thanks", "that sounds good").

You MUST return a JSON object with the following fields:
{
  "has_fact": true if a durable fact is present else false,
  "fact_text": "A concise, clean summary of the fact (e.g. 'Allergic to peanuts' or 'Is vegan' or 'Prefers organic products')",
  "category": "dietary" or "preference" or "instruction" or "other" (set to null if has_fact is false)
}

Output ONLY the raw JSON object. Do not include markdown code block formatting (like ```json), and do not include any explanatory prose."""


async def classify_and_store_fact(
    db: AsyncSession, user_id: uuid.UUID, user_message: str
) -> PersistentFact | None:
    """Analyzes user turn, extracts durable facts, and persists them to Postgres."""
    try:
        response_str = await call_llm(
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
            user_prompt=user_message,
            temperature=0.0,
            max_tokens=256,
            call_type="fact_classifier",
        )

        # Use robust JSON extraction
        cleaned_response = extract_json_from_response(response_str)
        data = json.loads(cleaned_response)
        if not data.get("has_fact"):
            return None

        fact_text = data.get("fact_text", "").strip()
        category_str = data.get("category", "other")

        if not fact_text:
            return None

        # Convert category string to enum
        try:
            category = FactCategory(category_str)
        except ValueError:
            category = FactCategory.other

        # Check if this user already has an identical fact text to prevent duplicate writes
        dup_query = select(PersistentFact).where(
            PersistentFact.user_id == user_id,
            PersistentFact.fact_text.ilike(fact_text),
        )
        dup_result = await db.execute(dup_query)
        existing = dup_result.scalar_one_or_none()
        if existing:
            return existing

        fact = PersistentFact(
            user_id=user_id,
            fact_text=fact_text,
            category=category,
        )
        db.add(fact)
        await db.commit()
        await db.refresh(fact)
        logger.info(f"Stored persistent memory fact for user {user_id}: '{fact_text}'")
        return fact

    except Exception as e:
        logger.error(f"Error classifying or storing fact: {e}")
        return None


async def get_user_facts(db: AsyncSession, user_id: uuid.UUID) -> list[PersistentFact]:
    """Retrieve all persistent facts for a given user."""
    result = await db.execute(
        select(PersistentFact)
        .where(PersistentFact.user_id == user_id)
        .order_by(PersistentFact.created_at.desc())
    )
    return list(result.scalars().all())
