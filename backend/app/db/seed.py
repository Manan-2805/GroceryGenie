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

        # 2. Seed products with variety to enable comparison tasks
        products_data = [
            # --- Produce ---
            {
                "name": "Fresh Fuji Apples",
                "description": "Crisp and sweet organic Fuji apples, bag of 5",
                "category": "Produce",
                "price": Decimal("4.99"),
                "stock": 25,
                "image_url": "https://images.unsplash.com/photo-1560806887-1e4cd0b6cbd6?w=400",
            },
            {
                "name": "Gala Apples",
                "description": "Mildly sweet and juicy Gala apples, sold per kg",
                "category": "Produce",
                "price": Decimal("3.49"),
                "stock": 40,
                "image_url": "https://images.unsplash.com/photo-1568702846914-96b305d2aaeb?w=400",
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
                "name": "Frozen Spinach",
                "description": "Chopped frozen spinach, 500g bag, flash-frozen at peak freshness",
                "category": "Produce",
                "price": Decimal("1.99"),
                "stock": 60,
                "image_url": "https://images.unsplash.com/photo-1558618666-fcd25c85f82e?w=400",
            },
            {
                "name": "Roma Tomatoes",
                "description": "Vine-ripened Roma tomatoes, 1 kg pack",
                "category": "Produce",
                "price": Decimal("2.49"),
                "stock": 50,
                "image_url": "https://images.unsplash.com/photo-1592924357228-91a4daadcfea?w=400",
            },
            {
                "name": "Red Bell Peppers",
                "description": "Sweet and crunchy red bell peppers, pack of 3",
                "category": "Produce",
                "price": Decimal("3.99"),
                "stock": 30,
                "image_url": "https://images.unsplash.com/photo-1563565375-f3fdfdb6b0c2?w=400",
            },
            {
                "name": "Organic Bananas",
                "description": "Fair-trade organic bananas, sold per bunch (~6 bananas)",
                "category": "Produce",
                "price": Decimal("1.49"),
                "stock": 100,
                "image_url": "https://images.unsplash.com/photo-1603833665858-e61d17a86224?w=400",
            },
            {
                "name": "Avocados",
                "description": "Ripe Hass avocados, pack of 2",
                "category": "Produce",
                "price": Decimal("3.29"),
                "stock": 20,
                "image_url": "https://images.unsplash.com/photo-1523049673857-eb18f1d7b578?w=400",
            },
            # --- Dairy & Eggs ---
            {
                "name": "Organic Whole Milk",
                "description": "Creamy organic whole cow milk, high in calcium, 1L bottle",
                "category": "Dairy & Eggs",
                "price": Decimal("2.49"),
                "stock": 50,
                "image_url": "https://images.unsplash.com/photo-1550583724-b2692b85b150?w=400",
            },
            {
                "name": "Almond Milk (Unsweetened)",
                "description": "Smooth unsweetened almond milk, dairy-free and vegan, 1L carton",
                "category": "Dairy & Eggs",
                "price": Decimal("3.79"),
                "stock": 35,
                "image_url": "https://images.unsplash.com/photo-1600788744282-e4f7f3e8a15e?w=400",
            },
            {
                "name": "Free-Range Large Eggs",
                "description": "Farm-fresh free-range large brown eggs, dozen pack",
                "category": "Dairy & Eggs",
                "price": Decimal("4.99"),
                "stock": 40,
                "image_url": "https://images.unsplash.com/photo-1582722872445-44dc5f7e3c8f?w=400",
            },
            {
                "name": "Greek Yogurt (Plain)",
                "description": "Thick and creamy plain Greek yogurt, 500g tub, high protein",
                "category": "Dairy & Eggs",
                "price": Decimal("3.99"),
                "stock": 25,
                "image_url": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=400",
            },
            {
                "name": "Butter (Salted)",
                "description": "Creamy salted butter made from pasteurized cream, 250g block",
                "category": "Dairy & Eggs",
                "price": Decimal("2.99"),
                "stock": 45,
                "image_url": "https://images.unsplash.com/photo-1589985270826-4b7bb135bc9d?w=400",
            },
            # --- Beverages ---
            {
                "name": "Artesian Spring Water",
                "description": "Pure natural artesian spring water, 1L bottle",
                "category": "Beverages",
                "price": Decimal("1.89"),
                "stock": 80,
                "image_url": "https://images.unsplash.com/photo-1608885898957-a599fb1b468b?w=400",
            },
            {
                "name": "Sparkling Water (Lemon)",
                "description": "Refreshing lemon-flavored sparkling water, zero sugar, 500ml can",
                "category": "Beverages",
                "price": Decimal("1.49"),
                "stock": 60,
                "image_url": "https://images.unsplash.com/photo-1559650656-5d1d361ad10e?w=400",
            },
            {
                "name": "Orange Juice (Freshly Squeezed)",
                "description": "Freshly squeezed orange juice, no added sugar, 1L bottle",
                "category": "Beverages",
                "price": Decimal("4.49"),
                "stock": 20,
                "image_url": "https://images.unsplash.com/photo-1600271886742-f049cd451bba?w=400",
            },
            # --- Pantry ---
            {
                "name": "Whole Wheat Crackers",
                "description": "Crunchy whole grain crackers with sea salt, 200g box",
                "category": "Pantry",
                "price": Decimal("3.49"),
                "stock": 40,
                "image_url": "https://images.unsplash.com/photo-1590080875515-8a3a8dc5735e?w=400",
            },
            {
                "name": "Gluten-Free Crackers",
                "description": "Light and crispy crackers made from rice flour, 150g box",
                "category": "Pantry",
                "price": Decimal("4.29"),
                "stock": 25,
                "image_url": "https://images.unsplash.com/photo-1590080875515-8a3a8dc5735e?w=400",
            },
            {
                "name": "Organic Olive Oil",
                "description": "Extra virgin olive oil, cold-pressed, 500ml bottle",
                "category": "Pantry",
                "price": Decimal("8.99"),
                "stock": 30,
                "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=400",
            },
            {
                "name": "Basmati Rice",
                "description": "Aged long-grain basmati rice, premium quality, 1kg bag",
                "category": "Pantry",
                "price": Decimal("5.99"),
                "stock": 50,
                "image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=400",
            },
            {
                "name": "Multigrain Bread",
                "description": "Freshly baked multigrain bread loaf with seeds",
                "category": "Pantry",
                "price": Decimal("3.99"),
                "stock": 20,
                "image_url": "https://images.unsplash.com/photo-1549931319-a545753467f0?w=400",
            },
            # --- Meat & Seafood ---
            {
                "name": "Chicken Breast (Boneless)",
                "description": "Skinless boneless chicken breast, 500g pack",
                "category": "Meat & Seafood",
                "price": Decimal("6.99"),
                "stock": 30,
                "image_url": "https://images.unsplash.com/photo-1604503468506-a8da13d82791?w=400",
            },
            {
                "name": "Salmon Fillet",
                "description": "Fresh Atlantic salmon fillet, 250g portion",
                "category": "Meat & Seafood",
                "price": Decimal("9.99"),
                "stock": 15,
                "image_url": "https://images.unsplash.com/photo-1599084993091-1cb5c0721cc6?w=400",
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
                avg_rating=Decimal("0.00"),  # No fake ratings - starts at 0
                sold_count=0,
                is_active=True,
            )
            db.add(product)
            seeded_products.append(product)

        await db.commit()

        # Update Qdrant and Neo4j layout
        logger.info("Initializing vector search and knowledge graph clients...")
        await seed_store_layout()

        logger.info("Indexing products in Qdrant and Neo4j...")
        neo4j_failures = 0
        qdrant_failures = 0
        for product in seeded_products:
            await db.refresh(product)

            try:
                await index_product_in_qdrant(
                    product_id=product.id,
                    name=product.name,
                    description=product.description,
                    category=product.category,
                    price=float(product.price),
                    is_active=product.is_active,
                )
            except Exception as e:
                logger.error(f"Failed to index product {product.id} in Qdrant: {e}")
                qdrant_failures += 1

            try:
                await link_product_to_aisle(
                    product_id=product.id,
                    name=product.name,
                    category=product.category,
                )
            except Exception as e:
                logger.error(f"Failed to link product {product.id} in Neo4j: {e}")
                neo4j_failures += 1

            logger.info(f"Indexed & Linked product: {product.name}")

        logger.info(
            f"Seeding complete. {len(seeded_products)} products indexed (Qdrant fails: {qdrant_failures}, "
            f"Neo4j fails: {neo4j_failures}). "
            "Single Dev User: dev@GroceryGenie.com (bypass login)"
        )


if __name__ == "__main__":
    asyncio.run(seed_data())
