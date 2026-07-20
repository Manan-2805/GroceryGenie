import json
import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from app.db.models.address import Address
from app.services.agent.llm import call_llm
from app.services.agent.workers.base import BaseWorker

logger = logging.getLogger("app.services.agent.workers.address")

ADDRESS_DECIDER_PROMPT = """You are a shopping assistant that manages saved addresses.
Based on the user's goal, decide what address action to perform.

Available actions:
1. "list_addresses" - List all saved addresses
2. "get_address" - Get details of a specific address by label or ID
3. "create_address" - Create a new address (requires: label, line1, city, state, postal_code, country)
4. "update_address" - Update an existing address (requires: address_id and fields to update)
5. "delete_address" - Delete an address (requires: address_id or label)

Existing addresses:
{addresses_context}

User's goal:
{goal}

You MUST return a JSON object:
{{
  "action": "list_addresses" | "get_address" | "create_address" | "update_address" | "delete_address",
  "address_id": "UUID or null",
  "address_data": {{
    "label": "...",
    "line1": "...",
    "line2": null,
    "city": "...",
    "state": "...",
    "postal_code": "...",
    "country": "...",
    "is_default": false
  }} or null,
  "reason": "Brief explanation"
}}

Output ONLY raw JSON. No markdown formatting."""


class AddressWorker(BaseWorker):
    async def run(self, goal: str) -> dict[str, Any]:
        logger.info(f"AddressWorker starting subgoal: '{goal}'")

        db = self.context.get("db")
        user_id = self.context.get("user_id")

        if not db or not user_id:
            raise RuntimeError(
                "Database session or user ID missing from worker context"
            )

        # Get existing addresses for context
        result = await db.execute(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.is_default.desc(), Address.created_at.desc())
        )
        existing_addresses = list(result.scalars().all())
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
                for a in existing_addresses
            ],
            indent=2,
        )

        # Ask LLM to decide action
        try:
            response_str = await call_llm(
                system_prompt="You are a precise JSON address manager.",
                user_prompt=ADDRESS_DECIDER_PROMPT.format(
                    addresses_context=addresses_context, goal=goal
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
            logger.error(f"AddressWorker failed to decide action: {e}")
            return {
                "status": "failed",
                "message": "Could not determine address action.",
            }

        action = decision.get("action", "list_addresses")

        if action == "list_addresses":
            return {
                "status": "success",
                "action": "list_addresses",
                "addresses": [
                    {
                        "id": str(a.id),
                        "label": a.label,
                        "line1": a.line1,
                        "line2": a.line2,
                        "city": a.city,
                        "state": a.state,
                        "postal_code": a.postal_code,
                        "country": a.country,
                        "is_default": a.is_default,
                    }
                    for a in existing_addresses
                ],
            }

        if action == "get_address":
            address_id_str = decision.get("address_id")
            if address_id_str:
                try:
                    aid = uuid.UUID(address_id_str)
                    for a in existing_addresses:
                        if a.id == aid:
                            return {
                                "status": "success",
                                "action": "get_address",
                                "address": {
                                    "id": str(a.id),
                                    "label": a.label,
                                    "line1": a.line1,
                                    "line2": a.line2,
                                    "city": a.city,
                                    "state": a.state,
                                    "postal_code": a.postal_code,
                                    "country": a.country,
                                    "is_default": a.is_default,
                                },
                            }
                except ValueError:
                    pass
            return {"status": "failed", "message": "Address not found."}

        if action == "create_address":
            addr_data = decision.get("address_data", {})
            if not addr_data.get("label") or not addr_data.get("line1"):
                return {
                    "status": "failed",
                    "message": "Address label and line1 are required.",
                }

            # Check if this is first address -> make default
            is_first = len(existing_addresses) == 0
            is_default = addr_data.get("is_default", False) or is_first

            if is_default and existing_addresses:
                await db.execute(
                    update(Address)
                    .where(Address.user_id == user_id)
                    .values(is_default=False)
                )

            address = Address(
                user_id=user_id,
                label=addr_data["label"],
                line1=addr_data["line1"],
                line2=addr_data.get("line2"),
                city=addr_data.get("city", ""),
                state=addr_data.get("state", ""),
                postal_code=addr_data.get("postal_code", ""),
                country=addr_data.get("country", ""),
                is_default=is_default,
            )
            db.add(address)
            await db.commit()
            await db.refresh(address)

            return {
                "status": "success",
                "action": "create_address",
                "message": f"Address '{address.label}' created successfully.",
                "address": {
                    "id": str(address.id),
                    "label": address.label,
                    "line1": address.line1,
                    "city": address.city,
                    "state": address.state,
                    "postal_code": address.postal_code,
                    "country": address.country,
                    "is_default": address.is_default,
                },
            }

        if action in ("update_address", "delete_address"):
            address_id_str = decision.get("address_id")
            target_address = None
            if address_id_str:
                try:
                    aid = uuid.UUID(address_id_str)
                    for a in existing_addresses:
                        if a.id == aid:
                            target_address = a
                            break
                except ValueError:
                    pass

            if not target_address:
                return {"status": "failed", "message": "Address not found."}

            if action == "delete_address":
                await db.delete(target_address)
                await db.commit()
                return {
                    "status": "success",
                    "action": "delete_address",
                    "message": f"Address '{target_address.label}' deleted.",
                }

            # update_address
            addr_data = decision.get("address_data", {})
            if addr_data.get("is_default"):
                await db.execute(
                    update(Address)
                    .where(Address.user_id == user_id)
                    .values(is_default=False)
                )

            for field in [
                "label",
                "line1",
                "line2",
                "city",
                "state",
                "postal_code",
                "country",
                "is_default",
            ]:
                if field in addr_data and addr_data[field] is not None:
                    setattr(target_address, field, addr_data[field])

            await db.commit()
            await db.refresh(target_address)
            return {
                "status": "success",
                "action": "update_address",
                "message": f"Address '{target_address.label}' updated.",
                "address": {
                    "id": str(target_address.id),
                    "label": target_address.label,
                    "line1": target_address.line1,
                    "city": target_address.city,
                    "state": target_address.state,
                    "postal_code": target_address.postal_code,
                    "country": target_address.country,
                    "is_default": target_address.is_default,
                },
            }

        return {"status": "failed", "message": f"Unknown action: {action}"}
