import logging
import uuid
from typing import Any

from neo4j import GraphDatabase

from app.core.config import settings

logger = logging.getLogger("app.services.rag.graph")

_neo4j_driver: GraphDatabase | None = None


def get_neo4j_driver() -> Any:
    global _neo4j_driver
    if _neo4j_driver is None:
        logger.info(f"Connecting to Neo4j at {settings.NEO4J_URI}...")
        _neo4j_driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _neo4j_driver


def close_neo4j_driver() -> None:
    global _neo4j_driver
    if _neo4j_driver is not None:
        _neo4j_driver.close()
        _neo4j_driver = None


def seed_store_layout() -> None:
    driver = get_neo4j_driver()
    
    # 2-3 Sections
    sections = [
        {"name": "Fresh Foods", "desc": "Fruits, vegetables and bakery"},
        {"name": "Pantry", "desc": "Canned items, spices and dry goods"},
        {"name": "Dairy & Beverages", "desc": "Milk, cheese, eggs and drinks"},
    ]

    # 5-6 Aisles
    aisles = [
        {"name": "Aisle 1 (Produce)", "section": "Fresh Foods"},
        {"name": "Aisle 2 (Bakery)", "section": "Fresh Foods"},
        {"name": "Aisle 3 (Canned Goods)", "section": "Pantry"},
        {"name": "Aisle 4 (Spices & Oils)", "section": "Pantry"},
        {"name": "Aisle 5 (Milk & Eggs)", "section": "Dairy & Beverages"},
        {"name": "Aisle 6 (Cold Drinks)", "section": "Dairy & Beverages"},
    ]

    with driver.session() as session:
        # Create Sections
        for s in sections:
            session.run(
                "MERGE (sec:Section {name: $name}) SET sec.description = $desc",
                name=s["name"],
                desc=s["desc"],
            )

        # Create Aisles and link to Sections
        for a in aisles:
            session.run(
                """
                MERGE (aisle:Aisle {name: $name})
                WITH aisle
                MATCH (sec:Section {name: $section_name})
                MERGE (aisle)-[:IN_SECTION]->(sec)
                """,
                name=a["name"],
                section_name=a["section"],
            )
            
    logger.info("Successfully seeded Neo4j store layout sections and aisles.")


def determine_aisle_for_category(category: str) -> str:
    cat = category.lower()
    if any(k in cat for k in ["fruit", "vegetable", "produce", "tomato", "spinach", "salad"]):
        return "Aisle 1 (Produce)"
    if any(k in cat for k in ["bread", "bakery", "pastry", "loaf", "cake"]):
        return "Aisle 2 (Bakery)"
    if any(k in cat for k in ["can", "soup", "canned", "bean", "sauce"]):
        return "Aisle 3 (Canned Goods)"
    if any(k in cat for k in ["spice", "oil", "salt", "pepper", "condiment"]):
        return "Aisle 4 (Spices & Oils)"
    if any(k in cat for k in ["milk", "dairy", "egg", "cheese", "butter", "yogurt", "vegan", "oat", "almond"]):
        return "Aisle 5 (Milk & Eggs)"
    if any(k in cat for k in ["drink", "beverage", "soda", "juice", "water", "coke", "tea", "coffee"]):
        return "Aisle 6 (Cold Drinks)"
    return "Aisle 3 (Canned Goods)"  # Default fallback


def link_product_to_aisle(product_id: uuid.UUID, name: str, category: str) -> None:
    driver = get_neo4j_driver()
    aisle_name = determine_aisle_for_category(category)

    with driver.session() as session:
        session.run(
            """
            MERGE (p:Product {id: $product_id})
            SET p.name = $name, p.category = $category
            WITH p
            MATCH (a:Aisle {name: $aisle_name})
            MERGE (p)-[:LOCATED_IN]->(a)
            """,
            product_id=str(product_id),
            name=name,
            category=category,
            aisle_name=aisle_name,
        )
    logger.info(f"Linked product {product_id} to {aisle_name} in Neo4j.")


def get_adjacent_products(product_id: uuid.UUID) -> list[dict[str, str]]:
    driver = get_neo4j_driver()
    pid_str = str(product_id)

    # Query 1: Find products in the same Aisle
    query_aisle = """
        MATCH (p:Product {id: $product_id})-[:LOCATED_IN]->(a:Aisle)<-[:LOCATED_IN]-(other:Product)
        WHERE other.id <> $product_id
        RETURN other.id AS id, other.name AS name LIMIT 5
    """
    
    with driver.session() as session:
        result = session.run(query_aisle, product_id=pid_str)
        products = [{"id": record["id"], "name": record["name"]} for record in result]
        if products:
            return products

        # Query 2: Fallback to same Section
        query_section = """
            MATCH (p:Product {id: $product_id})-[:LOCATED_IN]->(a:Aisle)-[:IN_SECTION]->(s:Section)
            MATCH (s)<-[:IN_SECTION]-(other_a:Aisle)<-[:LOCATED_IN]-(other:Product)
            WHERE other.id <> $product_id
            RETURN other.id AS id, other.name AS name LIMIT 5
        """
        result = session.run(query_section, product_id=pid_str)
        return [{"id": record["id"], "name": record["name"]} for record in result]
