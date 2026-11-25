import asyncio
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import operations
from app.assistant.local import address_plan, shopping_plan
from app.assistant.provider import admit_cloud_turn, interpret
from app.assistant.schema import Checkout, Plan, Preference, Search, Step
from app.catalog.products import SearchFilters
from app.core.security import authenticated_user
from app.db.base import AsyncSessionFactory, utc_now
from app.db.models.enums import ChatMode, UserRole
from app.db.models.session import AgentApproval, ChatSession
from app.db.models.user import User

YES = {"yes", "yes proceed", "confirm", "approve", "go ahead"}
NO = {"no", "cancel", "decline"}


class Turn(BaseModel):
    text: str
    confirmation_id: UUID | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    local_address_draft: dict[str, str] | None = Field(default=None, exclude=True)
    private_input: bool = Field(default=False, exclude=True)

    def event(self) -> dict[str, Any]:
        if self.confirmation_id:
            return {
                "type": "permission_request",
                "summary": self.text,
                "confirmation_id": str(self.confirmation_id),
            }
        return {"type": "response", "text": self.text, "records": self.records}


class Proposal(BaseModel):
    plan: Plan
    summaries: list[str]
    checkout_quote: UUID | None = None
    explicit_memory: bool = False


async def owned_conversation(
    db: AsyncSession, user_id: UUID, conversation_id: UUID, *, lock: bool = False
) -> ChatSession:
    query = select(ChatSession).where(
        ChatSession.id == conversation_id, ChatSession.user_id == user_id
    )
    if lock:
        query = query.with_for_update()
    row = (await db.scalars(query)).one_or_none()
    if row is None:
        raise HTTPException(404, "Conversation not found.")
    return row


async def open_conversation(
    db: AsyncSession, user_id: UUID, conversation_id: UUID | None, mode: ChatMode
) -> UUID:
    if conversation_id is not None:
        return (await owned_conversation(db, user_id, conversation_id)).id
    row = ChatSession(user_id=user_id, mode=mode)
    db.add(row)
    await db.flush()
    return row.id


def fast_plan(message: str, role: UserRole) -> Plan | None:
    normalized = message.strip(" .?!").lower()
    reads = {
        "show my orders": "orders",
        "my orders": "orders",
        "show my pending orders": "orders",
        "show my cart": "view_cart",
        "my cart": "view_cart",
        "show my addresses": "addresses",
        "my addresses": "addresses",
        "show inventory": "inventory",
        "show low stock": "inventory",
    }
    if normalized in reads:
        return Plan.model_validate(
            {
                "steps": [
                    {"tool": reads[normalized], "pending_only": "pending" in normalized}
                ]
            }
        )
    memory = re.fullmatch(
        r"remember (?:that )?(.{1,200})", message, flags=re.IGNORECASE
    )
    if memory:
        return Plan(steps=[Preference(tool="remember", value=memory[1])])
    if role == UserRole.customer:
        if normalized in {"show dairy products", "find dairy products"}:
            return Plan(
                steps=[
                    Search(
                        tool="search",
                        filters=SearchFilters(
                            category="Dairy & Eggs", stock_quantity=1
                        ),
                    )
                ]
            )
        if normalized in {"show vegetarian products", "find vegetarian products"}:
            return Plan(
                steps=[
                    Search(
                        tool="search",
                        filters=SearchFilters(
                            dietary_tag="vegetarian", stock_quantity=1
                        ),
                    )
                ]
            )
        search = re.fullmatch(
            r"(?:(?:find|search for|show) (?:me )?)?(?:(cheap|cheapest|available) )?([a-z][a-z -]{0,45})(?: under (?:₹|rs\.? *)?(\d{1,6}(?:\.\d{1,2})?)(?: rupees)?)?",
            normalized,
        )
        if search and (
            search[1]
            or search[3]
            or normalized.startswith(("find ", "show ", "search for "))
        ):
            name = search[2].strip()
            if " and " not in name and not name.startswith(("my ", "pending ")):
                ceiling = (
                    max(Decimal(0), Decimal(search[3]) - Decimal("0.01"))
                    if search[3]
                    else None
                )
                return Plan(
                    steps=[
                        Search(
                            tool="search",
                            filters=SearchFilters(
                                query=name,
                                stock_quantity=1,
                                max_price=ceiling,
                                sort="cheapest"
                                if search[1] in {"cheap", "cheapest"}
                                else "relevance",
                            ),
                        )
                    ]
                )
    return None


def remember_turn(
    row: ChatSession, message: str, result: Turn, role: UserRole, mode_version: int
) -> None:
    row.history = [
        *row.history[-38:],
        {
            "role": "user",
            "content": message,
            "private": result.private_input
            or bool(
                re.search(
                    r"\b(address|street|postal code|pincode|preference|remember)\b|\b\d{6,}\b|@",
                    message,
                    flags=re.I,
                )
            ),
        },
        {
            "role": "assistant",
            "content": result.text,
            "records": result.records,
            "confirmation_id": str(result.confirmation_id)
            if result.confirmation_id
            else None,
            "mode": role.value,
            "local_address_draft": result.local_address_draft,
            "mode_version": mode_version,
        },
    ]
    row.active_turn = None
    row.lease_until = None


def grounded_context(row: ChatSession, role: UserRole, mode_version: int) -> str:
    facts = [
        {
            key: value
            for key, value in item.items()
            if key in {"id", "name", "status", "price", "quantity", "stock", "package"}
        }
        for turn in row.history[-12:]
        if turn.get("mode") == role.value and turn.get("mode_version") == mode_version
        for item in turn.get("records", [])
    ]
    requests = [
        str(turn.get("content", ""))[:400]
        for turn in row.history[-8:]
        if turn.get("role") == "user" and not turn.get("private")
    ]
    return str({"recent_requests": requests, "results": facts[-20:]})[:3500]


async def approval_turn(
    db: AsyncSession,
    row: ChatSession,
    user: User,
    approval_id: UUID | None,
    approved: bool,
) -> Turn:
    query = select(AgentApproval).where(AgentApproval.conversation_id == row.id)
    if approval_id:
        query = query.where(AgentApproval.id == approval_id)
    else:
        query = (
            query.where(AgentApproval.outcome.is_(None))
            .order_by(AgentApproval.created_at.desc())
            .limit(1)
        )
    patch = (await db.scalars(query.with_for_update())).one_or_none()
    if patch is None or patch.mode_version != user.mode_version:
        return Turn(text="There is no matching confirmation in this conversation.")
    if patch.outcome:
        return Turn(text=patch.outcome)
    if patch.expires_at <= utc_now():
        return Turn(text="This confirmation expired. Ask for a new preview.")
    if not approved:
        patch.outcome = "Cancelled. No changes were made."
        return Turn(text=patch.outcome)

    proposal = Proposal.model_validate(patch.proposal)
    try:
        async with db.begin_nested():
            if proposal.checkout_quote:
                result = await operations.finish_checkout(
                    db, user, proposal.checkout_quote, patch.id
                )
            else:
                summaries = [
                    await operations.mutate(
                        db, user, step, explicit_memory=proposal.explicit_memory
                    )
                    for step in proposal.plan.steps
                ]
                if summaries != proposal.summaries:
                    raise HTTPException(
                        409, "The values have changed. Request a fresh preview."
                    )
                result = "Completed.\n" + "\n".join(summaries)
    except HTTPException as exc:
        result = f"No changes were made. {exc.detail}"
    patch.outcome = result
    return Turn(text=result)


async def evaluate_plan(
    db: AsyncSession, row: ChatSession, user: User, plan: Plan, message: str
) -> Turn:
    texts: list[str] = []
    records: list[dict[str, Any]] = []
    mutations: list[Step] = []
    for step in plan.steps:
        if isinstance(step, operations.READS):
            text, items = await operations.read(db, user, step)
            texts.append(text)
            records.extend(items)
        else:
            mutations.append(step)

    if plan.question or not mutations:
        return Turn(
            text="\n".join([*texts, *([plan.question] if plan.question else [])])
            or "I can help with grocery shopping or your seller dashboard.",
            records=records[:25],
        )
    if any(isinstance(step, Checkout) for step in mutations) and len(mutations) != 1:
        return Turn(
            text="Review and confirm other changes first, then request checkout."
        )
    explicitly_save = bool(
        re.search(r"\b(remember|save (?:my |this )?preference)\b", message, flags=re.I)
    )
    quote_id = None
    if len(mutations) == 1 and isinstance(mutations[0], Checkout):
        quote_id, summary = await operations.prepare_checkout(db, user, mutations[0])
        summaries = [summary]
    else:
        preview = await db.begin_nested()
        try:
            summaries = [
                await operations.mutate(db, user, step, explicit_memory=explicitly_save)
                for step in mutations
            ]
        finally:
            await preview.rollback()
        await db.refresh(user)
    proposal = Proposal(
        plan=Plan(steps=mutations),
        summaries=summaries,
        checkout_quote=quote_id,
        explicit_memory=explicitly_save,
    )
    approval = AgentApproval(
        conversation_id=row.id,
        mode_version=user.mode_version,
        expires_at=utc_now() + timedelta(minutes=4),
        proposal=proposal.model_dump(mode="json"),
    )
    db.add(approval)
    await db.flush()
    return Turn(
        text="Review and confirm these changes.\n" + "\n".join(summaries),
        confirmation_id=approval.id,
        records=records[:25],
    )


async def run_turn(
    conversation_id: UUID,
    user_id: UUID,
    token: str | None,
    message: str,
    approval_id: UUID | None = None,
    approved: bool | None = None,
) -> Turn:
    claim = uuid4()
    cleaned = re.sub(r"[^a-z ]", "", message.lower()).strip()
    async with AsyncSessionFactory.begin() as db:
        row = await owned_conversation(db, user_id, conversation_id, lock=True)
        user = await authenticated_user(db, token)
        if user is None or user.id != user_id:
            raise HTTPException(401, "Sign in again.")
        if (
            row.active_turn is not None
            and row.lease_until
            and row.lease_until > utc_now()
        ):
            raise HTTPException(409, "Wait for the current turn to finish.")
        role, version = user.role, user.mode_version
        latest = row.history[-1] if row.history else {}
        draft = (
            latest.get("local_address_draft")
            if latest.get("mode_version") == version
            else None
        )
        if approval_id is not None or (draft is None and cleaned in YES | NO):
            user = await db.get(
                User, user_id, with_for_update=True, populate_existing=True
            )
            if user is None:
                raise HTTPException(401, "Sign in again.")
            result = await approval_turn(
                db,
                row,
                user,
                approval_id,
                approved if approved is not None else cleaned in YES,
            )
            remember_turn(row, message, result, user.role, user.mode_version)
            return result
        await db.execute(
            update(AgentApproval)
            .where(
                AgentApproval.conversation_id == row.id,
                AgentApproval.outcome.is_(None),
            )
            .values(outcome="This confirmation was replaced. No changes were made.")
        )
        row.active_turn, row.lease_until = claim, utc_now() + timedelta(seconds=35)
        context = grounded_context(row, role, version)
        local = None
        if role == UserRole.customer:
            shopping = (
                draft
                if draft and draft.get("operation") in {"select_cart", "cart_budget"}
                else None
            )
            local = await shopping_plan(db, user_id, message, shopping)
            if local is None:
                local = await address_plan(
                    db, user_id, message, draft if shopping is None else None
                )

    try:
        plan = local.plan if local else fast_plan(message, role)
        if not plan:
            if re.search(
                r"\b(address|street|postal code|pincode|preference|remember)\b|\b\d{6,}\b|@",
                message,
                flags=re.I,
            ):
                plan = Plan(
                    question="Use the saved address form for private street details. Say “show my addresses” to select a saved address."
                )
            elif not admit_cloud_turn(user_id):
                plan = Plan(
                    question="The assistant is handling your requests too quickly. Wait a moment and retry."
                )
            else:
                async with asyncio.timeout(18):
                    plan = await interpret(message, role, context)
        async with AsyncSessionFactory.begin() as db:
            row = await owned_conversation(db, user_id, conversation_id, lock=True)
            user = await authenticated_user(db, token)
            if user is None or user.id != user_id:
                raise HTTPException(401, "Sign in again.")
            user = await db.get(
                User, user_id, with_for_update=True, populate_existing=True
            )
            if user is None or user.mode_version != version or row.active_turn != claim:
                raise HTTPException(
                    409, "The conversation or active mode changed. Try again."
                )
            try:
                async with db.begin_nested():
                    result = (
                        await evaluate_plan(db, row, user, plan, message)
                        if plan
                        else Turn(
                            text="Natural-language planning is unavailable. Try “show my cart”, “show my orders”, or use the marketplace pages."
                        )
                    )
            except HTTPException as exc:
                result = Turn(text=str(exc.detail))
            if local:
                result.local_address_draft = local.draft
                result.private_input = True
            remember_turn(row, message, result, role, version)
            return result
    finally:
        async with AsyncSessionFactory.begin() as db:
            await db.execute(
                update(ChatSession)
                .where(
                    ChatSession.id == conversation_id,
                    ChatSession.active_turn == claim,
                )
                .values(active_turn=None, lease_until=None)
            )
