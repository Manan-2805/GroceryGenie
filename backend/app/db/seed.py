"""Insert the synthetic showcase without changing existing records."""

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert

from app.db.base import AsyncSessionFactory, engine
from app.db.models.enums import OrderStatus, UserRole
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.user import User

logger = logging.getLogger(__name__)
SHOPS = (
    "Mango Lane",
    "Cedar Pantry",
    "Morning Market",
    "River Grocery",
    "Lotus Foods",
    "Green Corner",
    "Coconut Basket",
    "Harvest Lane",
)
BRANDS = (
    "Nila",
    "Juniper",
    "Hillside",
    "Clay Pot",
    "Blue Orchard",
    "Green Field",
    "Pebble",
    "Pine Grove",
    "Golden Grove",
    "Palm House",
)
# Synthetic labels, prices, dietary information, and ingredients for the demo only.
GOODS: tuple[tuple[str, str, tuple[str, ...], str, list[str], list[str], int], ...] = (
    (
        "Toned Milk",
        "Dairy & Eggs",
        ("200 ml", "500 ml", "1 litre", "2 litres", "6 × 200 ml"),
        "Cow milk",
        ["milk"],
        ["vegetarian"],
        24,
    ),
    (
        "Salted Butter",
        "Dairy & Eggs",
        ("100 g", "200 g", "250 g", "500 g", "1 kg"),
        "Pasteurized milk cream, salt",
        ["milk"],
        ["vegetarian"],
        48,
    ),
    (
        "Plain Curd",
        "Dairy & Eggs",
        ("100 g", "200 g", "400 g", "500 g", "1 kg"),
        "Cow milk, live cultures",
        ["milk"],
        ["vegetarian"],
        28,
    ),
    (
        "Apple",
        "Produce",
        ("250 g", "500 g", "1 kg", "1.5 kg", "2 kg"),
        "Apples",
        [],
        ["vegetarian", "vegan"],
        42,
    ),
    (
        "Cavendish Banana",
        "Produce",
        ("2 pieces", "4 pieces", "6 pieces", "8 pieces", "12 pieces"),
        "Bananas",
        [],
        ["vegetarian", "vegan"],
        15,
    ),
    (
        "Baby Spinach",
        "Produce",
        ("100 g", "200 g", "250 g", "400 g", "500 g"),
        "Spinach",
        [],
        ["vegetarian", "vegan"],
        20,
    ),
    (
        "Basmati Rice",
        "Pantry",
        ("250 g", "500 g", "1 kg", "2 kg", "5 kg"),
        "Basmati rice",
        [],
        ["vegetarian", "vegan"],
        48,
    ),
    (
        "Toor Dal",
        "Pantry",
        ("250 g", "500 g", "750 g", "1 kg", "2 kg"),
        "Pigeon peas",
        [],
        ["vegetarian", "vegan"],
        48,
    ),
    (
        "Rolled Oats",
        "Pantry",
        ("100 g", "250 g", "500 g", "750 g", "1 kg"),
        "Whole grain oats",
        ["oats"],
        ["vegetarian", "vegan"],
        55,
    ),
    (
        "Whole Wheat Biscuits",
        "Snacks",
        ("6 pieces", "12 pieces", "18 pieces", "24 pieces", "36 pieces"),
        "Whole wheat, sugar, butter",
        ["wheat", "milk"],
        ["vegetarian"],
        32,
    ),
    (
        "Almonds",
        "Snacks",
        ("50 g", "100 g", "200 g", "250 g", "500 g"),
        "Almonds",
        ["almonds"],
        ["vegetarian", "vegan"],
        52,
    ),
    (
        "Roasted Makhana",
        "Snacks",
        ("20 g", "40 g", "60 g", "100 g", "200 g"),
        "Fox nuts, sunflower oil, salt",
        [],
        ["vegetarian", "vegan"],
        34,
    ),
    (
        "Orange Juice",
        "Beverages",
        ("200 ml", "300 ml", "500 ml", "1 litre", "2 litres"),
        "Orange juice",
        [],
        ["vegetarian", "vegan"],
        27,
    ),
    (
        "Sparkling Water",
        "Beverages",
        ("250 ml", "330 ml", "500 ml", "750 ml", "1 litre"),
        "Water, carbon dioxide",
        [],
        ["vegetarian", "vegan"],
        20,
    ),
    (
        "Masala Chai",
        "Beverages",
        ("50 g", "100 g", "200 g", "250 g", "500 g"),
        "Black tea, ginger, cardamom",
        [],
        ["vegetarian", "vegan"],
        44,
    ),
    (
        "Wheat Flour",
        "Pantry",
        ("250 g", "500 g", "1 kg", "2 kg", "5 kg"),
        "Whole wheat",
        ["wheat"],
        ["vegetarian", "vegan"],
        27,
    ),
    (
        "Frozen Sweet Corn",
        "Frozen",
        ("100 g", "200 g", "250 g", "500 g", "1 kg"),
        "Corn",
        [],
        ["vegetarian", "vegan"],
        34,
    ),
    (
        "Frozen Green Peas",
        "Frozen",
        ("100 g", "200 g", "250 g", "500 g", "1 kg"),
        "Green peas",
        [],
        ["vegetarian", "vegan"],
        32,
    ),
    (
        "Paneer",
        "Dairy & Eggs",
        ("100 g", "150 g", "200 g", "400 g", "500 g"),
        "Cow milk, citric acid",
        ["milk"],
        ["vegetarian"],
        58,
    ),
    (
        "Brown Eggs",
        "Dairy & Eggs",
        ("2 pieces", "4 pieces", "6 pieces", "12 pieces", "24 pieces"),
        "Hen eggs",
        ["egg"],
        [],
        20,
    ),
    (
        "Black Chickpeas",
        "Pantry",
        ("100 g", "250 g", "500 g", "750 g", "1 kg"),
        "Black chickpeas",
        [],
        ["vegetarian", "vegan"],
        25,
    ),
    (
        "Mango Nectar",
        "Beverages",
        ("150 ml", "250 ml", "500 ml", "750 ml", "1 litre"),
        "Mango pulp, water, cane sugar",
        [],
        ["vegetarian", "vegan"],
        26,
    ),
    (
        "Coconut Water",
        "Beverages",
        ("200 ml", "250 ml", "500 ml", "750 ml", "1 litre"),
        "Coconut water",
        [],
        ["vegetarian", "vegan"],
        37,
    ),
    (
        "Jaggery",
        "Pantry",
        ("100 g", "250 g", "500 g", "1 kg", "2 kg"),
        "Sugarcane juice solids",
        [],
        ["vegetarian", "vegan"],
        26,
    ),
    (
        "Peanut Chikki",
        "Snacks",
        ("25 g", "50 g", "100 g", "150 g", "250 g"),
        "Peanuts, jaggery",
        ["peanut"],
        ["vegetarian", "vegan"],
        18,
    ),
)


def demo_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"grocergenie:showcase:v1:{key}")


async def seed_data(as_of: date) -> None:
    buyers = [demo_id(f"buyer/{n}") for n in range(16)]
    shops = [demo_id(f"shop/{n}") for n in range(len(SHOPS))]
    accounts = [
        {
            "id": account_id,
            "google_sub": f"demo:{account_id}",
            "email": f"{account_id}@example.invalid",
            "name": label,
            "role": role,
        }
        for ids, labels, role in (
            (shops, SHOPS, UserRole.seller),
            (
                buyers,
                [f"Demo Buyer {i + 1}" for i in range(len(buyers))],
                UserRole.customer,
            ),
        )
        for account_id, label in zip(ids, labels, strict=True)
    ]
    catalogue = [
        {
            "id": demo_id(f"product/{shop}/{good}/{pack}/{brand}"),
            "seller_id": seller_id,
            "name": name,
            "description": f"{label} {name}, {package}. Synthetic demonstration listing.",
            "category": category,
            "brand": label,
            "package": package,
            "price": Decimal(base * (pack + 1) + brand * 2 + shop) - Decimal("0.05"),
            "cost_price": Decimal(base * (pack + 1)) * Decimal("0.72"),
            "stock": (shop * 53 + good * 19 + pack * 3 + brand * 11) % 175,
            "ingredients": ingredients,
            "dietary_tags": tags,
            "allergens": allergens if brand % 7 else None,
            "label_source": "Synthetic demonstration label",
        }
        for shop, seller_id in enumerate(shops)
        for good, (
            name,
            category,
            packages,
            ingredients,
            allergens,
            tags,
            base,
        ) in enumerate(GOODS)
        for pack, package in enumerate(packages)
        for brand, label in enumerate(BRANDS)
    ]
    anchor = as_of - timedelta(days=as_of.weekday())
    async with AsyncSessionFactory.begin() as db:
        await db.execute(
            insert(User).on_conflict_do_nothing(index_elements=[User.id]), accounts
        )
        for start in range(0, len(catalogue), 500):
            await db.execute(
                insert(Product).on_conflict_do_nothing(index_elements=[Product.id]),
                catalogue[start : start + 500],
            )

        orders, fulfillments, lines = [], [], []
        for week in range(1, 13):
            for buyer_index, buyer in enumerate(buyers):
                key = f"order/{buyer_index}/{week}"
                order_id = demo_id(key)
                delivered = datetime.combine(
                    anchor - timedelta(weeks=week, days=-(buyer_index % 5)),
                    time(10),
                    tzinfo=UTC,
                )
                placed = delivered - timedelta(hours=6)
                first_shop = buyer_index % len(shops)
                total = Decimal(0)
                for seller in (first_shop, (first_shop + week % 7 + 1) % len(shops)):
                    offset = seller * len(GOODS) * 5 * len(BRANDS)
                    item = catalogue[
                        offset
                        + ((buyer_index + week * 23) % (len(GOODS) * 5 * len(BRANDS)))
                    ]
                    units = (buyer_index + week) % 3 + 1
                    subtotal = Decimal(str(item["price"])) * units
                    total += subtotal
                    child_id = demo_id(f"{key}/shop/{seller}")
                    fulfillments.append(
                        {
                            "id": child_id,
                            "order_id": order_id,
                            "seller_id": shops[seller],
                            "status": OrderStatus.delivered,
                            "total": subtotal,
                            "created_at": placed,
                            "packed_at": placed + timedelta(hours=1),
                            "out_for_delivery_at": placed + timedelta(hours=3),
                            "delivered_at": delivered,
                        }
                    )
                    lines.append(
                        {
                            "id": demo_id(f"{key}/line/{seller}"),
                            "order_id": order_id,
                            "fulfillment_id": child_id,
                            "product_id": item["id"],
                            "product_name": item["name"],
                            "quantity": units,
                            "price_at_purchase": item["price"],
                            "cost_at_purchase": item["cost_price"],
                            "package_at_purchase": item["package"],
                        }
                    )
                orders.append(
                    {
                        "id": order_id,
                        "customer_id": buyer,
                        "total": total,
                        "created_at": placed,
                        "status": OrderStatus.delivered,
                        "delivered_at": delivered,
                        "checkout_key": key,
                        "delivery_address": {
                            "label": "Demo address",
                            "line1": "10 Sample Road",
                            "city": "Pune",
                            "state": "Maharashtra",
                            "postal_code": "411001",
                            "country": "India",
                        },
                    }
                )
        await db.execute(
            insert(Order).on_conflict_do_nothing(index_elements=[Order.id]), orders
        )
        await db.execute(
            insert(Fulfillment).on_conflict_do_nothing(index_elements=[Fulfillment.id]),
            fulfillments,
        )
        await db.execute(
            insert(OrderItem).on_conflict_do_nothing(index_elements=[OrderItem.id]),
            lines,
        )
    logger.info(
        "Seeded %d synthetic product keys and %d synthetic order keys",
        len(catalogue),
        len(orders),
    )


async def run(as_of: date) -> None:
    try:
        await seed_data(as_of)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--as-of", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    args = cli.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.as_of))
