import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.addresses import AddressCreate, AddressUpdate
from app.assistant.schema import (
    AddressAdd,
    AddressEdit,
    AddressRemove,
    Cart,
    Checkout,
    Plan,
    Read,
    Search,
)
from app.catalog.products import SearchFilters, search_products
from app.db.models.address import Address
from app.db.models.memory import PersistentFact

ADDRESS_FIELDS = ("label", "line1", "city", "state", "postal_code")
ADDRESS_QUESTIONS = {
    "label": "What label should I use for this address?",
    "line1": "What is the complete delivery street address?",
    "city": "What is the city?",
    "state": "What is the state?",
    "postal_code": "What is the postal code?",
}
ADDRESS_COMMANDS = {
    "add an address": "add",
    "add address": "add",
    "save an address": "add",
    "save address": "add",
    "update my delivery address": "edit",
    "update address": "edit",
    "edit address": "edit",
    "remove address": "remove",
    "delete address": "remove",
    "place my order": "checkout",
    "checkout": "checkout",
    "check out": "checkout",
    "place order": "checkout",
}


@dataclass
class LocalPlan:
    plan: Plan
    draft: dict[str, str] | None = None


async def address_plan(
    db: AsyncSession, user_id: UUID, message: str, previous: dict[str, str] | None
) -> LocalPlan | None:
    command = message.casefold().strip(" .!?")
    operation = ADDRESS_COMMANDS.get(command)
    if operation is None and previous is None:
        return None
    state = {"operation": operation} if operation is not None else dict(previous or {})
    action = state["operation"]
    if command in {"cancel", "start over"}:
        return LocalPlan(Plan(question="Address entry cancelled."))
    asked = state.get("asked")
    if asked in ADDRESS_FIELDS:
        if not message.strip() or len(message.strip()) > 100:
            return LocalPlan(Plan(question=ADDRESS_QUESTIONS[asked]), state)
        if asked == "postal_code" and not re.fullmatch(r"[0-9A-Za-z -]{3,20}", message):
            return LocalPlan(Plan(question=ADDRESS_QUESTIONS[asked]), state)
        state[asked] = message.strip()
        state.pop("asked", None)
    if action != "add" and "id" not in state:
        addresses = list(
            await db.scalars(
                select(Address)
                .where(Address.user_id == user_id)
                .order_by(Address.created_at.desc())
                .limit(15)
            )
        )
        if not addresses:
            return LocalPlan(
                Plan(
                    question="You have no saved delivery address. Say “add address” to create one."
                )
            )
        id_by_label = [a.id for a in addresses if a.label.casefold() == command]
        selected = id_by_label[0] if len(id_by_label) == 1 else None
        if selected is None and len(addresses) == 1 and action == "checkout":
            selected = addresses[0].id
        if selected is None:
            return LocalPlan(
                Plan(
                    steps=[Read(tool="addresses")],
                    question="Which saved address label should I use?",
                ),
                state,
            )
        state["id"] = str(selected)
    if action == "remove":
        return LocalPlan(
            Plan(
                steps=[
                    AddressRemove(tool="remove_address", address_id=UUID(state["id"]))
                ]
            )
        )
    if action == "checkout":
        return LocalPlan(
            Plan(steps=[Checkout(tool="checkout", address_id=UUID(state["id"]))])
        )
    fields = ADDRESS_FIELDS if action == "add" else ADDRESS_FIELDS[1:]
    for field in fields:
        if field not in state:
            return LocalPlan(
                Plan(question=ADDRESS_QUESTIONS[field]), state | {"asked": field}
            )
    values = {field: state[field] for field in fields}
    if action == "add":
        return LocalPlan(
            Plan(
                steps=[
                    AddressAdd(
                        tool="add_address", address=AddressCreate.model_validate(values)
                    )
                ]
            )
        )
    return LocalPlan(
        Plan(
            steps=[
                AddressEdit(
                    tool="edit_address",
                    address_id=UUID(state["id"]),
                    changes=AddressUpdate.model_validate(values),
                )
            ]
        )
    )


async def shopping_plan(
    db: AsyncSession,
    user_id: UUID,
    message: str,
    previous: dict[str, str] | None,
) -> LocalPlan | None:
    normalized = message.casefold().strip(" .?!")
    if previous and previous["operation"] == "select_cart":
        if normalized in {"cancel", "start over"}:
            return LocalPlan(Plan(question="Cart selection cancelled."))
        choice = re.fullmatch(r"(?:(?:pick|choose|option|number) )?(\d)", normalized)
        candidates = previous["ids"].split(",")
        if choice and 1 <= int(choice[1]) <= len(candidates):
            return LocalPlan(
                Plan(
                    steps=[
                        Cart(
                            tool="cart",
                            product_id=UUID(candidates[int(choice[1]) - 1]),
                            quantity=int(previous["quantity"]),
                            operation="add",
                            max_package_price=Decimal(previous["max_price"]),
                        )
                    ]
                )
            )
        return LocalPlan(
            Plan(question="Choose a listed product number or say “cancel”."), previous
        )

    if previous and previous["operation"] == "cart_budget":
        if normalized in {"cancel", "start over"}:
            return LocalPlan(Plan(question="Cart selection cancelled."))
        if normalized not in {"total", "per package"}:
            return LocalPlan(
                Plan(question="Say “total” or “per package”, or say “cancel”."),
                previous,
            )
        return await shopping_options(
            db,
            previous["search"],
            int(previous["quantity"]),
            Decimal(previous["budget"]),
            per_package=normalized == "per package",
        )
    if normalized in {
        "show products using my preferences",
        "find products using my preferences",
    }:
        saved = list(
            await db.scalars(
                select(PersistentFact.fact_text)
                .where(
                    PersistentFact.user_id == user_id,
                )
                .order_by(PersistentFact.updated_at.desc())
                .limit(20)
            )
        )
        for tag in ("vegan", "vegetarian"):
            if any(
                re.fullmatch(
                    rf"(?:i am |i prefer |i only eat )?{tag}(?: products)?",
                    item.strip(" .").lower(),
                )
                for item in saved
            ):
                return LocalPlan(
                    Plan(
                        steps=[
                            Search(
                                tool="search",
                                filters=SearchFilters(
                                    dietary_tag=tag, stock_quantity=1
                                ),
                            )
                        ]
                    )
                )
        return LocalPlan(
            Plan(
                question="No supported dietary label is saved. Try “remember that I prefer vegetarian products”."
            )
        )

    purchase = re.fullmatch(
        r"find (\d{1,3}|one|two|three|four|five) (?:packages?|packs?) of ([a-z -]{2,45}) under (?:₹|rs )?(\d{1,6}(?:\.\d{1,2})?)(?: rupees)? and add (?:them|it) to my cart",
        normalized,
    )
    if purchase is None:
        return None
    quantity = (
        int(purchase[1])
        if purchase[1].isdigit()
        else ("one", "two", "three", "four", "five").index(purchase[1]) + 1
    )
    budget = Decimal(purchase[3])
    if quantity < 1 or budget <= 0:
        return LocalPlan(
            Plan(question="Enter a positive quantity and a positive budget.")
        )
    if quantity > 1:
        return LocalPlan(
            Plan(
                question=f"Is ₹{budget} your total budget or your budget for each package? Say “total” or “per package”."
            ),
            {
                "operation": "cart_budget",
                "quantity": str(quantity),
                "search": purchase[2].strip(),
                "budget": str(budget),
            },
        )
    return await shopping_options(
        db, purchase[2].strip(), quantity, budget, per_package=True
    )


async def shopping_options(
    db: AsyncSession,
    name: str,
    quantity: int,
    budget: Decimal,
    *,
    per_package: bool,
) -> LocalPlan:
    cap = ((budget - Decimal("0.01")) / (1 if per_package else quantity)).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    filters = SearchFilters(
        query=name, stock_quantity=quantity, max_price=cap, sort="cheapest"
    )
    products = await search_products(db, filters, limit=5)
    if not products:
        return LocalPlan(
            Plan(
                question="No matching packages fit those quantities and price. Try a higher budget or fewer packages."
            )
        )
    choices = "\n".join(
        f"{index}. {p.brand[:40]} {p.name[:96]}, {p.package[:45]} · ₹{p.price} each · ₹{p.price * quantity} total"
        for index, p in enumerate(products, start=1)
    )
    return LocalPlan(
        Plan(question=f"{choices}\nWhich product number should I add?"),
        {
            "operation": "select_cart",
            "quantity": str(quantity),
            "max_price": str(cap),
            "ids": ",".join(str(p.id) for p in products),
        },
    )
