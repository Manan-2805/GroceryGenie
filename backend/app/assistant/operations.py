from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.addresses import add_address, modify_address, owned_address, remove_address
from app.api.orders import advance_fulfillment
from app.api.ratings import add_rating, reply_to_rating
from app.api.reports import seller_report
from app.assistant.schema import (
    AddressAdd,
    AddressEdit,
    AddressRemove,
    Cart,
    Checkout,
    Fulfill,
    Preference,
    ProductAdd,
    ProductEdit,
    Rate,
    Read,
    Reply,
    Report,
    Search,
    Step,
    Stock,
)
from app.catalog.products import (
    create_product,
    increase_stock,
    search_products,
    seller_product,
    write_product,
)
from app.commerce.cart import change_cart
from app.commerce.checkout import (
    DeliveryAddress,
    QuoteSnapshot,
    confirm_checkout,
    create_quote,
)
from app.db.models.address import Address
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus, UserRole
from app.db.models.fulfillment import Fulfillment
from app.db.models.memory import PersistentFact
from app.db.models.order import Order
from app.db.models.product import Product
from app.db.models.user import User

READS = (Search, Read, Report)
SELLER = (ProductAdd, ProductEdit, Stock, Fulfill, Report, Reply)
CUSTOMER = (AddressAdd, AddressEdit, AddressRemove, Checkout, Cart, Rate)


def authorize(user: User, step: Step) -> None:
    if (
        isinstance(step, SELLER) or isinstance(step, Read) and step.tool == "inventory"
    ) and user.role != UserRole.seller:
        raise HTTPException(403, "Switch to seller mode to do that.")
    if (
        isinstance(step, CUSTOMER)
        or isinstance(step, Read)
        and step.tool in {"view_cart", "addresses"}
    ) and user.role != UserRole.customer:
        raise HTTPException(403, "Switch to customer mode to do that.")


async def read(
    db: AsyncSession, user: User, step: Search | Read | Report
) -> tuple[str, list[dict[str, Any]]]:
    authorize(user, step)
    if isinstance(step, Search):
        products = await search_products(db, step.filters, limit=6)
        records: list[dict[str, Any]] = [
            {
                "id": str(p.id),
                "name": p.name,
                "brand": p.brand,
                "price": str(p.price),
                "package": p.package,
                "stock": p.stock,
                "dietary_tags": p.dietary_tags,
                "allergens": p.allergens,
                "ingredients": p.ingredients,
                "nutrition": p.nutrition,
            }
            for p in products
        ]
        results = [
            f"{p.name} ({p.package}) — ₹{p.price}, {p.stock} available. "
            f"Dietary labels: {', '.join(p.dietary_tags or []) or 'unavailable'}. "
            f"Allergen information: {', '.join(p.allergens) if p.allergens else 'see product label' if p.allergens == [] else 'unavailable'}."
            for p in products
        ]
        return "\n".join(
            results
        ) or "No products match those filters. Try relaxing a filter.", records
    if isinstance(step, Report):
        report = await seller_report(db, user.id, step.period)
        return (
            f"Delivered: {report.orders} orders, {report.units} units, "
            f"₹{report.revenue:.2f} sales and ₹{report.profit:.2f} gross profit. "
            f"{report.low_stock} products are low on stock. "
            f"Repeat customers: {report.repeat_customers} of {report.unique_customers}.",
            [],
        )
    if step.tool == "view_cart":
        cart = await db.execute(
            select(Product, CartItem.quantity)
            .join(CartItem)
            .where(
                CartItem.user_id == user.id,
            )
            .order_by(Product.name)
            .limit(25)
        )
        records = [{"id": str(p.id), "name": p.name, "quantity": q} for p, q in cart]
        return "\n".join(
            f"{r['name']} × {r['quantity']}" for r in records
        ) or "Your cart is empty.", records
    if step.tool == "addresses":
        addresses = await db.scalars(
            select(Address)
            .where(Address.user_id == user.id)
            .order_by(Address.is_default.desc())
            .limit(15)
        )
        records = [{"id": str(a.id), "name": a.label} for a in addresses]
        return "\n".join(
            r["name"] for r in records
        ) or "You have no saved addresses.", records
    if step.tool == "inventory":
        items = await db.scalars(
            select(Product)
            .where(Product.seller_id == user.id)
            .order_by(Product.stock, Product.id)
            .limit(15)
        )
        records = [{"id": str(p.id), "name": p.name, "stock": p.stock} for p in items]
        return "\n".join(
            f"{r['name']} — {r['stock']} available" for r in records
        ) or "Your shop has no products.", records
    if user.role == UserRole.seller:
        scope = Fulfillment.seller_id == user.id
        if step.pending_only:
            scope &= Fulfillment.status != OrderStatus.delivered
        children = await db.scalars(
            select(Fulfillment)
            .where(scope)
            .order_by(Fulfillment.created_at.desc())
            .limit(10)
        )
        records = [
            {
                "id": str(x.id),
                "status": x.status.value,
                "name": f"Fulfillment {str(x.id)[:8]}",
            }
            for x in children
        ]
    else:
        scope = Order.customer_id == user.id
        if step.pending_only:
            scope &= Order.status != OrderStatus.delivered
        orders = await db.scalars(
            select(Order).where(scope).order_by(Order.created_at.desc()).limit(10)
        )
        records = [
            {
                "id": str(x.id),
                "status": x.status.value,
                "name": f"Order {str(x.id)[:8]}",
            }
            for x in orders
        ]
    return "\n".join(
        f"{r['name']} — {r['status'].replace('_', ' ')}" for r in records
    ) or "No orders found.", records


async def prepare_checkout(
    db: AsyncSession, user: User, step: Checkout
) -> tuple[UUID, str]:
    authorize(user, step)
    quote = await create_quote(db, user.id, None, step.address_id)
    snapshot = QuoteSnapshot.model_validate(quote.snapshot)
    items = ", ".join(
        f"{line.quantity} × {line.name} at ₹{line.price}" for line in snapshot.lines
    )
    address = snapshot.address
    return quote.id, (
        f"Place a simulated order for {items}. Total ₹{snapshot.total}. Deliver to "
        f"{address.line1}, {address.line2 + ', ' if address.line2 else ''}"
        f"{address.city}, {address.state}, {address.postal_code}, {address.country}."
    )


async def mutate(
    db: AsyncSession, user: User, step: Step, *, explicit_memory: bool
) -> str:
    authorize(user, step)
    if isinstance(step, Cart):
        product = await db.get(
            Product, step.product_id, with_for_update=True, populate_existing=True
        )
        if product is None:
            raise HTTPException(404, "Product is unavailable.")
        if (
            step.max_package_price is not None
            and product.price > step.max_package_price
        ):
            raise HTTPException(
                409,
                "The selected product price changed. Search again to review current prices.",
            )
        await change_cart(
            db, user.id, product.id, step.quantity, add=step.operation == "add"
        )
        saved = await db.scalar(
            select(CartItem.quantity).where(
                CartItem.user_id == user.id, CartItem.product_id == product.id
            )
        )
        return f"Cart: {product.name} ({product.package}) → {saved or 0} packages at ₹{product.price} each."
    if isinstance(step, Stock):
        product = await seller_product(db, user.id, step.product_id)
        before = product.stock
        increase_stock(product, step.quantity)
        return (
            f"Stock for {product.name}: {before} → {product.stock} (+{step.quantity})."
        )
    if isinstance(step, ProductEdit):
        product = await seller_product(db, user.id, step.product_id)
        product_name = product.name
        write_product(product, step.changes)
        return f"Update {product_name}: {step.changes.model_dump_json(exclude_unset=True, exclude={'expected_stock'})}."
    if isinstance(step, ProductAdd):
        db.add(create_product(user.id, step.product))
        return f"Create product {step.product.model_dump_json()}."
    if isinstance(step, Fulfill):
        await advance_fulfillment(db, user.id, step.fulfillment_id, step.status)
        return f"Fulfillment {str(step.fulfillment_id)[:8]} → {step.status.value.replace('_', ' ')}."
    if isinstance(step, AddressAdd):
        address = await add_address(db, user.id, step.address)
        return (
            f"Save address {DeliveryAddress.model_validate(address).model_dump_json()}."
        )
    if isinstance(step, AddressEdit):
        address = await modify_address(db, user.id, step.address_id, step.changes)
        return f"Update address to {DeliveryAddress.model_validate(address).model_dump_json()}."
    if isinstance(step, AddressRemove):
        address = await owned_address(db, user.id, step.address_id)
        summary = DeliveryAddress.model_validate(address).model_dump_json()
        await remove_address(db, user.id, step.address_id)
        return f"Remove saved address {summary}."
    if isinstance(step, Rate):
        await add_rating(db, user.id, step.review)
        return f"Submit review {step.review.model_dump_json()}."
    if isinstance(step, Reply):
        await reply_to_rating(db, user.id, step.rating_id, step.reply)
        return f"Reply to review {str(step.rating_id)[:8]}: {step.reply.reply}"
    if isinstance(step, Preference) and explicit_memory:
        db.add(PersistentFact(user_id=user.id, fact_text=step.value))
        return f"Save preference: {step.value}."
    raise HTTPException(422, "That operation is unavailable.")


async def finish_checkout(
    db: AsyncSession, user: User, quote: UUID, approval: UUID
) -> str:
    order = await confirm_checkout(db, user.id, quote, str(approval))
    return f"Placed simulated order {order}."
