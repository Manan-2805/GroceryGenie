"""
AgentOrchestrator — thin coordinator (~150 lines).

Sequence per turn:
  1. StateRouter   — resume any pending multi-turn flow (slot_fill, address, role_switch)
  2. FastPath      — zero-LLM prefix dispatch + fuzzy option matching
  3. IntentClassifier — 1 LLM call → {tool, params, fact}
  4. Special cases — toggle_theme, out_of_scope, follow_up (stream LLM)
  5. RBAC guard    — fail-closed; PermissionError → role-switch offer
  6. SlotValidator — check required fields; incomplete → ask + store pending
  7. ToolExecutor  — pure Python, no LLM
  8. ResponseFormatter — pure Python result → response dict
  9. History       — append user + assistant turn to Redis

run_turn_voice_stream() is intentionally absent. ws.py calls run_turn() directly
and handles TTS synthesis from the returned dict.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import UserRole
from app.services.agent import fast_path as fp
from app.services.agent import intent as intent_mod
from app.services.agent import slot_validator as sv
from app.services.agent import state_manager as sm
from app.services.agent.llm import call_llm_stream
from app.services.agent.prompts import FOLLOWUP_PROMPT
from app.services.agent.response_formatter import format_response
from app.services.agent.tools import TOOL_REGISTRY, check_tool_permission
from app.services.memory import Mem0

logger = logging.getLogger("app.services.agent.orchestrator")


class AgentOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        user_role: UserRole,
    ):
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.user_role = user_role

    # ──────────────────────────────────────────────────────────────────────
    # Public entry point — text and voice both call this
    # ──────────────────────────────────────────────────────────────────────

    async def run_turn(self, user_message: str) -> dict[str, Any]:
        sid = str(self.session_id)

        # ── 1. StateRouter ───────────────────────────────────────────────
        pending = await sm.get_pending(sid)
        if pending:
            try:
                response = await sm.resume(pending, user_message, self)
            except sm.ConcurrentMessageError:
                return {
                    "type": "response",
                    "text": "Please wait for my previous response to finish.",
                    "options": None,
                }
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", response.get("text", ""))
            return response

        # ── 2. FastPath ──────────────────────────────────────────────────
        fast = await fp.handle(user_message, self)
        if fast is not None:
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", fast.get("text", ""))
            # Cache options for fuzzy matching on next turn
            if fast.get("options"):
                await sm.set_last_options(sid, fast["options"])
            return fast

        # ── 3. Intent ────────────────────────────────────────────────────
        intent = await intent_mod.classify(
            user_message=user_message,
            user_role=self.user_role,
            session_id=sid,
            db=self.db,
            user_id=self.user_id,
        )

        # ── 4a. toggle_theme ─────────────────────────────────────────────
        if intent.tool == "toggle_theme":
            response = {
                "type": "toggle_theme",
                "text": "Theme toggled.",
                "options": None,
            }
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", response["text"])
            return response

        # ── 4b. out_of_scope / follow_up — streaming LLM ─────────────────
        if intent.tool in ("out_of_scope", "follow_up"):
            facts_str = await self._get_facts_str(user_message)
            prompt = FOLLOWUP_PROMPT.format(
                user_message=user_message,
                facts=facts_str,
            )
            # call_llm_stream is an async generator; collect for non-streaming callers
            full_text = ""
            async for token in call_llm_stream(
                system_prompt="You are GroceryGenie, a helpful grocery shopping assistant.",
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=200,
                call_type="followup_response",
            ):
                full_text += token
            if not full_text.strip():
                full_text = (
                    "I'm your GroceryGenie assistant! I can help you find products, "
                    "manage your cart, check orders, and more."
                )
            # Prepend greeting if first message
            if intent.is_first_message and intent.greeting:
                full_text = intent.greeting + "\n\n" + full_text
            response = {"type": "response", "text": full_text.strip(), "options": None}
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", full_text.strip())
            return response

        # ── 4c. Store durable fact if LLM extracted one ──────────────────
        if intent.fact_to_remember:
            await self._store_fact(intent.fact_to_remember, intent.fact_category)

        # ── 4d. Clear pending state AND last_options on switch_role so
        #        stale slot-fill from a different role never survives ────────
        if intent.tool == "switch_role":
            await sm.clear_pending(sid)
            # Also clear cached last_options so fuzzy match doesn't fire
            # stale inventory/product labels after a role change
            try:
                from app.services.agent.state_manager import _options_key
                from app.services.memory import get_redis_client
                await get_redis_client().delete(_options_key(sid))
            except Exception:
                pass

        # ── 5. RBAC ──────────────────────────────────────────────────────
        try:
            check_tool_permission(intent.tool, self.user_role)
        except ValueError:
            # Unknown tool — LLM hallucinated
            logger.warning(f"[Orchestrator] Unknown tool '{intent.tool}' from LLM")
            return {
                "type": "response",
                "text": "I'm not sure how to do that. Could you rephrase?",
                "options": None,
            }
        except PermissionError as exc:
            needed_role = _extract_needed_role(str(exc))
            return await self._role_switch_offer(
                user_message, intent.tool, needed_role, intent.params
            )

        # ── 6. Slot validation ───────────────────────────────────────────
        # manage_facts needs session_id injected so index lookups work
        if intent.tool == "manage_facts":
            intent.params["session_id"] = sid

        is_complete, _missing, ask_text = sv.validate(intent.tool, intent.params)
        if not is_complete:
            await sm.set_pending(
                sid,
                "slot_fill",
                {
                    "tool": intent.tool,
                    "partial": intent.params,
                    "original_message": user_message,
                },
            )
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", ask_text)
            return {"type": "response", "text": ask_text, "options": None}

        # ── 7. Tool execution ────────────────────────────────────────────
        result = await self._execute_tool(intent.tool, intent.params)

        # ── 8. Format ────────────────────────────────────────────────────
        response = format_response(result, intent.tool)

        # Prepend greeting on first message
        if intent.is_first_message and intent.greeting:
            response["text"] = intent.greeting + "\n\n" + response.get("text", "")

        # Cache options for fuzzy matching on next turn
        if response.get("options"):
            await sm.set_last_options(sid, response["options"])

        # ── 9. History ───────────────────────────────────────────────────
        await sm.append_history(sid, "user", user_message)
        await sm.append_history(sid, "assistant", response.get("text", ""))

        return response

    # ──────────────────────────────────────────────────────────────────────
    # Streaming entry point — yields (type, text) for SSE / voice
    # ──────────────────────────────────────────────────────────────────────

    async def run_turn_stream(
        self, user_message: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Async generator version of run_turn for SSE chat.py.

        Yields dicts:
          {"type": "delta",           "text": token}       — streaming LLM tokens
          {"type": "options_response"/"response"/..., ...} — complete structured result
        """
        sid = str(self.session_id)

        # Check pending state first (same as run_turn but as generator)
        pending = await sm.get_pending(sid)
        if pending:
            try:
                response = await sm.resume(pending, user_message, self)
            except sm.ConcurrentMessageError:
                yield {
                    "type": "response",
                    "text": "Please wait for my previous response to finish.",
                    "options": None,
                }
                return
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", response.get("text", ""))
            yield response
            return

        # FastPath
        fast = await fp.handle(user_message, self)
        if fast is not None:
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", fast.get("text", ""))
            if fast.get("options"):
                await sm.set_last_options(sid, fast["options"])
            yield fast
            return

        # Intent
        intent = await intent_mod.classify(
            user_message=user_message,
            user_role=self.user_role,
            session_id=sid,
            db=self.db,
            user_id=self.user_id,
        )

        # ── Clear stale pending state + last_options on switch_role ──────
        if intent.tool == "switch_role":
            await sm.clear_pending(sid)
            try:
                from app.services.agent.state_manager import _options_key
                from app.services.memory import get_redis_client
                await get_redis_client().delete(_options_key(sid))
            except Exception:
                pass

        # toggle_theme
        if intent.tool == "toggle_theme":
            yield {"type": "toggle_theme", "text": "Theme toggled.", "options": None}
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", "Theme toggled.")
            return

        # out_of_scope / follow_up — real token streaming
        if intent.tool in ("out_of_scope", "follow_up"):
            facts_str = await self._get_facts_str(user_message)
            prompt = FOLLOWUP_PROMPT.format(user_message=user_message, facts=facts_str)
            prefix = (
                (intent.greeting + "\n\n")
                if intent.is_first_message and intent.greeting
                else ""
            )
            if prefix:
                yield {"type": "delta", "text": prefix}
            full_text = prefix
            async for token in call_llm_stream(
                system_prompt="You are GroceryGenie, a helpful grocery shopping assistant.",
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=200,
                call_type="followup_stream",
            ):
                full_text += token
                yield {"type": "delta", "text": token}
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", full_text.strip())
            return

        # Store fact
        if intent.fact_to_remember:
            await self._store_fact(intent.fact_to_remember, intent.fact_category)

        # RBAC
        try:
            check_tool_permission(intent.tool, self.user_role)
        except ValueError:
            yield {
                "type": "response",
                "text": "I'm not sure how to do that. Could you rephrase?",
                "options": None,
            }
            return
        except PermissionError as exc:
            needed_role = _extract_needed_role(str(exc))
            offer = await self._role_switch_offer(
                user_message, intent.tool, needed_role, intent.params
            )
            yield offer
            return

        # manage_facts session_id injection
        if intent.tool == "manage_facts":
            intent.params["session_id"] = sid

        # Slot validation
        is_complete, _missing, ask_text = sv.validate(intent.tool, intent.params)
        if not is_complete:
            await sm.set_pending(
                sid,
                "slot_fill",
                {
                    "tool": intent.tool,
                    "partial": intent.params,
                    "original_message": user_message,
                },
            )
            await sm.append_history(sid, "user", user_message)
            await sm.append_history(sid, "assistant", ask_text)
            yield {"type": "response", "text": ask_text, "options": None}
            return

        # Tool execution + format
        result = await self._execute_tool(intent.tool, intent.params)
        response = format_response(result, intent.tool)
        if intent.is_first_message and intent.greeting:
            response["text"] = intent.greeting + "\n\n" + response.get("text", "")
        if response.get("options"):
            await sm.set_last_options(sid, response["options"])
        await sm.append_history(sid, "user", user_message)
        await sm.append_history(sid, "assistant", response.get("text", ""))
        yield response

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers (called by fast_path.py and state_manager.resume)
    # ──────────────────────────────────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Execute a registered tool. Returns error dict on failure."""
        tool_params = dict(params)
        tool_params["db"] = self.db
        tool_params["user_id"] = self.user_id
        if tool_name in TOOL_REGISTRY:
            try:
                return await TOOL_REGISTRY[tool_name](**tool_params)
            except Exception as exc:
                logger.error(f"[Orchestrator] Tool '{tool_name}' raised: {exc}")
                return {"success": False, "message": _sanitize_error(str(exc))}
        return {"success": False, "message": f"Unknown tool: {tool_name}"}

    def _format_response_sync(self, query: str, result: Any) -> dict[str, Any]:
        """Synchronous wrapper around format_response (used by fast_path)."""
        return format_response(result, query)

    async def _format_response(self, query: str, result: Any) -> dict[str, Any]:
        """Async-compatible wrapper (used by state_manager.resume)."""
        return format_response(result, query)

    async def _role_switch_offer(
        self,
        user_message: str,
        tool_name: str,
        needed_role: str,
        original_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Store role-switch pending state and return the offer card."""
        await sm.set_pending(
            str(self.session_id),
            "role_switch",
            {
                "tool_name": tool_name,
                "original_message": user_message,
                "original_params": original_params,  # BUG-05 fix: preserve params
                "needed_role": needed_role,
            },
        )
        await sm.append_history(str(self.session_id), "user", user_message)
        current = (
            self.user_role.value
            if hasattr(self.user_role, "value")
            else str(self.user_role)
        )
        return {
            "type": "role_switch_request",
            "text": (
                f"This action requires you to be a {needed_role}. "
                f"Your current role is '{current}'. Would you like to switch?"
            ),
            "summary": f"switch to '{needed_role}' role",
            "options": [
                {
                    "label": f"Yes, switch to {needed_role}",
                    "value": f"switch_role:{needed_role}",
                    "description": "Change role and retry",
                },
                {
                    "label": "No, cancel",
                    "value": "cancel",
                    "description": "Stay as current role",
                },
            ],
            "free_input_allowed": False,
            "needed_role": needed_role,
            "original_tool": tool_name,
        }

    async def _start_address_update_flow(self, address_id: str) -> dict[str, Any]:
        """Fetch current address and store update pending state."""
        from app.db.models.address import Address

        try:
            addr_uuid = uuid.UUID(address_id)
            a_res = await self.db.execute(
                select(Address).where(
                    Address.id == addr_uuid, Address.user_id == self.user_id
                )
            )
            address = a_res.scalar_one_or_none()
            if not address:
                return {
                    "type": "response",
                    "text": "Address not found.",
                    "options": None,
                }

            current = {
                "label": address.label,
                "line1": address.line1,
                "line2": address.line2 or "",
                "city": address.city,
                "state": address.state,
                "postal_code": address.postal_code,
                "country": address.country,
            }
            await sm.set_pending(
                str(self.session_id),
                "address_update",
                {"address_id": address_id, "current": current},
            )
            lines = [
                f"**{address.label}** — current details:",
                f"  Street: {address.line1}",
                f"  City: {address.city}, {address.state} {address.postal_code}",
                f"  Country: {address.country}",
                "\nWhat would you like to change? e.g. 'city to Surat, pin 395001'",
            ]
            return {"type": "response", "text": "\n".join(lines), "options": None}
        except Exception as exc:
            logger.warning(f"[Orchestrator] _start_address_update_flow: {exc}")
            return {
                "type": "response",
                "text": "I couldn't find that address.",
                "options": None,
            }

    async def _start_address_add_flow(
        self, initial_data: dict[str, Any], user_message: str
    ) -> dict[str, Any]:
        """Start slot-fill flow for adding a new address."""
        params = {"action": "add", "address_data": initial_data or {}}
        is_complete, _missing, ask_text = sv.validate("manage_addresses", params)
        if is_complete:
            result = await self._execute_tool("manage_addresses", params)
            return format_response(result, "manage_addresses")
        await sm.set_pending(
            str(self.session_id),
            "slot_fill",
            {
                "tool": "manage_addresses",
                "partial": params,
                "original_message": user_message,
            },
        )
        return {"type": "response", "text": ask_text, "options": None}

    async def _start_seller_edit_flow(self, product_id: str) -> dict[str, Any]:
        """Show current product details and ask what to change."""
        from app.db.models.product import Product

        try:
            prod_uuid = uuid.UUID(product_id)
            p_res = await self.db.execute(
                select(Product).where(
                    Product.id == prod_uuid, Product.seller_id == self.user_id
                )
            )
            product = p_res.scalar_one_or_none()
            if not product:
                return {
                    "type": "response",
                    "text": "Product not found.",
                    "options": None,
                }
            lines = [
                f"**{product.name}** — current details:",
                f"  Price: ${float(product.price):.2f}",
                f"  Stock: {product.stock}",
                f"  Category: {product.category}",
                f"  Description: {product.description or '(none)'}",
                "\nWhat would you like to change? e.g. 'price to 5.99' or 'stock to 50'",
            ]
            # Store pending slot_fill for seller_update_product
            await sm.set_pending(
                str(self.session_id),
                "slot_fill",
                {
                    "tool": "seller_update_product",
                    "partial": {"product_id": product_id},
                    "original_message": f"edit product {product_id}",
                },
            )
            return {"type": "response", "text": "\n".join(lines), "options": None}
        except Exception as exc:
            logger.warning(f"[Orchestrator] _start_seller_edit_flow: {exc}")
            return {"type": "response", "text": "Product not found.", "options": None}

    async def _handle_address_collect_response(
        self, user_message: str, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        """Resume address_add slot-fill with user's answer (called by StateRouter)."""
        partial = ctx.get("partial", {})
        merged = await sv.merge("manage_addresses", partial, user_message)
        is_complete, _missing, ask_text = sv.validate("manage_addresses", merged)
        if not is_complete:
            await sm.set_pending(
                str(self.session_id),
                "slot_fill",
                {
                    "tool": "manage_addresses",
                    "partial": merged,
                    "original_message": ctx.get("original_message", user_message),
                },
            )
            return {"type": "response", "text": ask_text, "options": None}
        await sm.clear_pending(str(self.session_id))
        result = await self._execute_tool("manage_addresses", merged)
        return format_response(result, "manage_addresses")

    async def _handle_address_update_response(
        self, user_message: str, ctx: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract delta fields from user message and show a confirm card."""
        from app.services.agent.slot_validator import _extract_address_fields

        delta = await _extract_address_fields(user_message)
        if not delta:
            return {
                "type": "response",
                "text": (
                    "I couldn't extract any address fields. "
                    "Try: 'city to Surat' or 'pin to 395001'"
                ),
                "options": None,
            }
        current = ctx.get("current", {})
        updated = {**current, **delta}
        changes = [
            f"  **{k}**: {current.get(k, '(empty)')} → {v}"
            for k, v in delta.items()
            if str(current.get(k, "")) != str(v)
        ]
        if not changes:
            return {
                "type": "response",
                "text": "The values you provided are already saved. No changes needed.",
                "options": None,
            }
        await sm.set_pending(
            str(self.session_id),
            "address_update_confirm",
            {"address_id": ctx["address_id"], "current": current, "updated": updated},
        )
        changes_text = "\n".join(changes)
        return {
            "type": "options_response",
            "text": f"I'll make these changes:\n{changes_text}\n\nConfirm?",
            "options": [
                {
                    "label": "✅ Yes, update",
                    "value": "confirm_address_update",
                    "description": "Save changes",
                },
                {
                    "label": "❌ Cancel",
                    "value": "cancel",
                    "description": "Keep existing address",
                },
            ],
            "free_input_allowed": True,
        }

    async def _get_facts_str(self, query: str) -> str:
        try:
            mem0 = Mem0(db=self.db, user_id=self.user_id)
            facts = await mem0.search(query=query, limit=3)
            if facts:
                return "; ".join(f["fact_text"] for f in facts)
        except Exception as exc:
            logger.warning(f"[Orchestrator] _get_facts_str: {exc}")
        return "None"

    async def _store_fact(self, fact_text: str, fact_category: str | None) -> None:
        try:
            mem0 = Mem0(db=self.db, user_id=self.user_id)
            await mem0.add(text=fact_text.strip(), category=fact_category or "other")
        except Exception as exc:
            logger.warning(f"[Orchestrator] _store_fact failed: {exc}")

    # ── Legacy shim for ws.py execute_approved_mutation ───────────────────
    async def execute_approved_mutation(
        self, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self._execute_tool(action, payload)
        return format_response(result, action)


# ── Module-level helpers ──────────────────────────────────────────────────────


def _extract_needed_role(error_str: str) -> str:
    if "requires '" in error_str:
        return error_str.split("requires '")[1].split("'", maxsplit=1)[0]
    return "seller"


def _sanitize_error(raw: str) -> str:
    low = raw.lower()
    if "uuid" in low or "badly formed" in low:
        return "I couldn't find that item. Please search for it first."
    if "json" in low or "decode" in low:
        return "I had trouble understanding that. Could you rephrase?"
    if "timeout" in low:
        return "The request took too long. Please try again."
    if "api key" in low or "auth" in low:
        return "I'm having connection issues. Please try again later."
    return "Something went wrong. Please try again."
