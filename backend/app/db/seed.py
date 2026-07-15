import asyncio
import logging
from decimal import Decimal

from sqlalchemy import delete

from app.db.base import AsyncSessionFactory
from app.db.models.enums import UserRole
from app.db.models.product import Product
from app.db.models.user import User
from app.services.rag.graph import (
    link_product_to_aisle,
    seed_store_layout,
)
from app.services.rag.retriever import (
    COLLECTION_NAME,
    get_qdrant_client,
    index_product_in_qdrant,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.db.seed")


async def seed_data() -> None:
    logger.info("Connecting to Postgres database...")
    async with AsyncSessionFactory() as db:
        # Wipe all users and products to start clean
        logger.info("Cleaning up old database data...")
        await db.execute(delete(Product))
        await db.execute(delete(User))
        await db.commit()

        # Wipe and recreate Qdrant collection to start clean
        logger.info("Resetting Qdrant collection...")
        try:
            client = get_qdrant_client()
            client.delete_collection(collection_name=COLLECTION_NAME)
            logger.info("Deleted Qdrant collection.")
            # Force recreate collection
            from app.services.rag import retriever

            retriever._qdrant_client = None
            get_qdrant_client()
            logger.info("Recreated Qdrant collection.")
        except Exception as e:
            logger.error(f"Error resetting Qdrant collection: {e}")

        # 1. Seed only one dev user (role: customer by default, switchable to seller)
        logger.info("Seeding dev user...")
        dev_user = User(
            google_sub="mock_dev_sub",
            email="dev@GroceryGenie.com",
            name="Dev User",
            role=UserRole.customer,
        )
        db.add(dev_user)
        await db.commit()
        await db.refresh(dev_user)

        # 2. Seed exactly 5 products, all owned by the dev user
        products_data = [
            {
                "name": "Fresh Fuji Apples",
                "description": "Crisp and sweet organic Fuji apples, bag of 5",
                "category": "Produce",
                "price": Decimal("4.99"),
                "stock": 25,
                "image_url": "https://images.unsplash.com/photo-1560806887-1e4cd0b6cbd6?w=400",
            },
            {
                "name": "Organic Spinach",
                "description": "Pre-washed baby spinach leaves, organic 250g pack",
                "category": "Produce",
                "price": Decimal("2.99"),
                "stock": 35,
                "image_url": "https://images.unsplash.com/photo-1576045057995-568f588f82fb?w=400",
            },
            {
                "name": "Artesian Spring Water",
                "description": "Pure natural artesian spring water, 1L bottle",
                "category": "Beverages",
                "price": Decimal("1.89"),
                "stock": 80,
                "image_url": "https://images.unsplash.com/photo-1608885898957-a599fb1b468b?w=400",
            },
            {
                "name": "Whole Wheat Crackers",
                "description": "Crunchy whole grain crackers with sea salt",
                "category": "Pantry",
                "price": Decimal("3.49"),
                "stock": 40,
                "image_url": "https://images.unsplash.com/photo-1590080875515-8a3a8dc5735e?w=400",
            },
            {
                "name": "Organic Whole Milk",
                "description": "Creamy organic whole cow milk, high in calcium",
                "category": "Dairy & Eggs",
                "price": Decimal("2.49"),
                "stock": 50,
                "image_url": "https://images.unsplash.com/photo-1550583724-b2692b85b150?w=400",
            },
        ]

        seeded_products = []
        for p in products_data:
            product = Product(
                seller_id=dev_user.id,
                name=p["name"],
                description=p["description"],
                category=p["category"],
                price=p["price"],
                stock=p["stock"],
                image_url=p["image_url"],
                avg_rating=Decimal("4.5"),
                sold_count=0,
                is_active=True,
            )
            db.add(product)
            seeded_products.append(product)

        await db.commit()

        # Update Qdrant and Neo4j layout
        logger.info("Initializing vector search and knowledge graph clients...")
        seed_store_layout()

        logger.info("Indexing products in Qdrant and Neo4j...")
        for product in seeded_products:
            await db.refresh(product)

            await index_product_in_qdrant(
                product_id=product.id,
                name=product.name,
                description=product.description,
                category=product.category,
                price=float(product.price),
                is_active=product.is_active,
            )

            link_product_to_aisle(
                product_id=product.id,
                name=product.name,
                category=product.category,
            )
            logger.info(f"Indexed & Linked product: {product.name}")

        logger.info(
            "Seeding complete. Single Dev User: dev@GroceryGenie.com (bypass login)"
        )


if __name__ == "__main__":
    asyncio.run(seed_data())
