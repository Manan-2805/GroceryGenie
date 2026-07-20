import os
import sys
import uuid
from typing import Any, Dict, List, Optional

# Add backend directory to sys.path to enable imports
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from mcp.server.fastmcp import FastMCP
from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload, selectinload

from app.db.base import AsyncSessionFactory
from app.db.models.address import Address
from app.db.models.cart import CartItem
from app.db.models.enums import OrderStatus, UserRole
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.user import User
from app.services.rag.graph import get_adjacent_products, get_neo4j_driver

# Initialize FastMCP Server
mcp = FastMCP("GroceryGenie")


# Helper to run async db sessions inside sync FastMCP tools
# Note: FastMCP handles async tool functions natively if they are defined with 'async def'


@mcp.tool()
async def search_products(
    query: str,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search products using filters and keyword matches."""
    async with AsyncSessionFactory() as session:
        db_query = select(Product).where(Product.is_active == True)

        if category:
            db_query = db_query.where(Product.category == category)
        if min_price is not None:
            db_query = db_query.where(Product.price >= min_price)
        if max_price is not None:
            db_query = db_query.where(Product.price <= max_price)

        if query:
            db_query = db_query.where(
                Product.name.ilike(f"%{query}%") | Product.description.ilike(f"%{query}%")
            )

        if sort_by == "price_asc":
            db_query = db_query.order_by(Product.price.asc())
        elif sort_by == "price_desc":
            db_query = db_query.order_by(Product.price.desc())
        elif sort_by == "rating":
            db_query = db_query.order_by(Product.avg_rating.desc())
        elif sort_by == "popularity":
            db_query = db_query.order_by(Product.sold_count.desc())
        else:
            db_query = db_query.order_by(Product.name.asc())

        result = await session.execute(db_query)
        products = result.scalars().all()

        return [
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "price": float(p.price),
                "stock": p.stock,
                "avg_rating": float(p.avg_rating),
                "sold_count": p.sold_count,
            }
            for p in products
        ]


@mcp.tool()
async def get_product(product_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve detailed information for a single product by ID."""
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        return None

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Product).where(Product.id == pid))
        p = result.scalar_one_or_none()
        if not p:
            return None

        return {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "category": p.category,
            "price": float(p.price),
            "stock": p.stock,
            "avg_rating": float(p.avg_rating),
            "sold_count": p.sold_count,
            "is_active": p.is_active,
        }


@mcp.tool()
async def compare_products(product_ids: List[str]) -> List[Dict[str, Any]]:
    """Compare prices, ratings, and features of multiple products."""
    pids = []
    for pid_str in product_ids:
        try:
            pids.append(uuid.UUID(pid_str))
        except ValueError:
            continue

    if not pids:
        return []

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Product).where(Product.id.in_(pids)))
        products = result.scalars().all()

        return [
            {
                "id": str(p.id),
                "name": p.name,
                "price": float(p.price),
                "avg_rating": float(p.avg_rating),
                "stock": p.stock,
                "category": p.category,
                "description": p.description,
            }
            for p in products
        ]


@mcp.tool()
async def get_dietary_facts(product_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve ingredient details and dietary warnings for a product."""
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        return None

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Product).where(Product.id == pid))
        p = result.scalar_one_or_none()
        if not p:
            return None

        # For a production application, dietary facts are extracted from description or specialized fields.
        # Here we return a structured analysis of the description for ingredient matching.
        desc_lower = p.description.lower()
        contains_peanuts = "peanut" in desc_lower or "groundnut" in desc_lower
        contains_milk = "milk" in desc_lower or "dairy" in desc_lower or "lactose" in desc_lower or "whey" in desc_lower
        contains_gluten = "wheat" in desc_lower or "gluten" in desc_lower or "flour" in desc_lower
        is_vegan = "vegan" in desc_lower or (not contains_milk and "meat" not in desc_lower and "chicken" not in desc_lower and "beef" not in desc_lower and "fish" not in desc_lower)

        return {
            "product_id": str(p.id),
            "product_name": p.name,
            "description": p.description,
            "allergens": {
                "peanuts": contains_peanuts,
                "milk_dairy": contains_milk,
                "gluten": contains_gluten,
            },
            "dietary_flags": {
                "vegan": is_vegan,
                "vegetarian": is_vegan or ("meat" not in desc_lower),
            }
        }


@mcp.tool()
async def add_to_cart(product_id: str, quantity: int, user_id: str) -> Dict[str, Any]:
    """[SENSITIVE] Add a product to a user's shopping cart."""
    try:
        pid = uuid.UUID(product_id)
        uid = uuid.UUID(user_id)
    except ValueError:
        return {"status": "error", "message": "Invalid UUID format"}

    async with AsyncSessionFactory() as session:
        # Check product existence & stock
        p_result = await session.execute(select(Product).where(Product.id == pid))
        product = p_result.scalar_one_or_none()
        if not product:
            return {"status": "error", "message": "Product not found"}
        if product.stock < quantity:
            return {"status": "error", "message": f"Insufficient stock. Available: {product.stock}"}

        # Check existing item
        c_result = await session.execute(
            select(CartItem).where(CartItem.user_id == uid, CartItem.product_id == pid)
        )
        cart_item = c_result.scalar_one_or_none()

        if cart_item:
            cart_item.quantity += quantity
        else:
            cart_item = CartItem(user_id=uid, product_id=pid, quantity=quantity)
            session.add(cart_item)

        await session.commit()
        return {"status": "success", "message": f"Added {quantity} of '{product.name}' to cart."}


@mcp.tool()
async def remove_from_cart(product_id: str, user_id: str) -> Dict[str, Any]:
    """[SENSITIVE] Remove a product from a user's shopping cart."""
    try:
        pid = uuid.UUID(product_id)
        uid = uuid.UUID(user_id)
    except ValueError:
        return {"status": "error", "message": "Invalid UUID format"}

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            delete(CartItem).where(CartItem.user_id == uid, CartItem.product_id == pid)
        )
        await session.commit()

        if result.rowcount == 0:
            return {"status": "error", "message": "Item not found in cart"}
        return {"status": "success", "message": "Item removed from cart."}


@mcp.tool()
async def update_cart_quantity(product_id: str, quantity: int, user_id: str) -> Dict[str, Any]:
    """[SENSITIVE] Update the quantity of a product in a user's cart."""
    try:
        pid = uuid.UUID(product_id)
        uid = uuid.UUID(user_id)
    except ValueError:
        return {"status": "error", "message": "Invalid UUID format"}

    if quantity <= 0:
        return {"status": "error", "message": "Quantity must be greater than zero"}

    async with AsyncSessionFactory() as session:
        # Check stock
        p_result = await session.execute(select(Product).where(Product.id == pid))
        product = p_result.scalar_one_or_none()
        if not product or product.stock < quantity:
            return {"status": "error", "message": "Insufficient stock"}

        c_result = await session.execute(
            select(CartItem).where(CartItem.user_id == uid, CartItem.product_id == pid)
        )
        cart_item = c_result.scalar_one_or_none()
        if not cart_item:
            return {"status": "error", "message": "Item not found in cart"}

        cart_item.quantity = quantity
        await session.commit()
        return {"status": "success", "message": "Cart updated."}


@mcp.tool()
async def get_cart(user_id: str) -> Dict[str, Any]:
    """Retrieve all items in a user's cart."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return {"status": "error", "message": "Invalid UUID format"}

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(CartItem)
            .options(joinedload(CartItem.product))
            .where(CartItem.user_id == uid)
        )
        items = result.scalars().all()
        
        cart_items = []
        total = 0.0
        for item in items:
            p = item.product
            item_total = float(p.price) * item.quantity
            total += item_total
            cart_items.append({
                "product_id": str(p.id),
                "name": p.name,
                "price": float(p.price),
                "quantity": item.quantity,
                "item_total": item_total,
            })
            
        return {"items": cart_items, "cart_total": total}


@mcp.tool()
async def initiate_checkout(user_id: str, delivery_address: Dict[str, Any]) -> Dict[str, Any]:
    """[SENSITIVE] Fulfill cart items and place an order."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return {"status": "error", "message": "Invalid UUID format"}

    async with AsyncSessionFactory() as session:
        # Get cart items
        c_result = await session.execute(
            select(CartItem).options(joinedload(CartItem.product)).where(CartItem.user_id == uid)
        )
        cart_items = c_result.scalars().all()
        if not cart_items:
            return {"status": "error", "message": "Cart is empty"}

        # Validate stock and calculate total
        total = 0.0
        order_items = []
        for item in cart_items:
            product = item.product
            if product.stock < item.quantity:
                return {"status": "error", "message": f"Product '{product.name}' is out of stock"}
            
            product.stock -= item.quantity
            product.sold_count += item.quantity
            item_total = float(product.price) * item.quantity
            total += item_total
            
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    price_at_purchase=product.price,
                )
            )

        # Create Order
        order = Order(
            customer_id=uid,
            status=OrderStatus.placed,
            total=total,
            delivery_address=delivery_address,
            items=order_items,
        )
        session.add(order)

        # Clear cart
        for item in cart_items:
            await session.delete(item)

        await session.commit()
        return {"status": "success", "order_id": str(order.id), "total": total}


@mcp.tool()
async def get_order_status(order_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve status and details of an order."""
    try:
        oid = uuid.UUID(order_id)
        uid = uuid.UUID(user_id)
    except ValueError:
        return None

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items).joinedload(OrderItem.product))
            .where(Order.id == oid)
        )
        order = result.scalar_one_or_none()
        if not order:
            return None

        # Verify ownership
        if order.customer_id != uid:
            # Check if user is a seller for any product in this order
            # Verify if user_id is a seller of any product in this order
            u_result = await session.execute(select(User).where(User.id == uid))
            user = u_result.scalar_one_or_none()
            if not user or user.role != UserRole.seller:
                return None

        return {
            "order_id": str(order.id),
            "status": order.status.value,
            "total": float(order.total),
            "delivery_address": order.delivery_address,
            "created_at": order.created_at.isoformat(),
            "items": [
                {
                    "product_name": item.product.name if item.product else "Unknown Product",
                    "quantity": item.quantity,
                    "price_at_purchase": float(item.price_at_purchase),
                }
                for item in order.items
            ]
        }


@mcp.tool()
async def list_orders(user_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """List orders placed by a user, optionally filtered by status."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return []

    async with AsyncSessionFactory() as session:
        db_query = select(Order).where(Order.customer_id == uid)
        if status_filter:
            try:
                stat = OrderStatus(status_filter)
                db_query = db_query.where(Order.status == stat)
            except ValueError:
                pass

        db_query = db_query.order_by(Order.created_at.desc())
        result = await session.execute(db_query)
        orders = result.scalars().all()

        return [
            {
                "order_id": str(o.id),
                "status": o.status.value,
                "total": float(o.total),
                "created_at": o.created_at.isoformat(),
            }
            for o in orders
        ]


@mcp.tool()
async def get_aisle_location(product_id: str) -> Optional[Dict[str, Any]]:
    """Query Neo4j graph database for product store location and layout."""
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        return None

    # Fetch product category first to find aisle mapping if needed
    async with AsyncSessionFactory() as session:
        p_result = await session.execute(select(Product).where(Product.id == pid))
        product = p_result.scalar_one_or_none()
        if not product:
            return None
        
        name = product.name
        category = product.category

    driver = get_neo4j_driver()
    with driver.session() as n_session:
        # Fetch Aisle and Section
        result = n_session.run(
            """
            MATCH (p:Product {id: $product_id})-[:LOCATED_IN]->(a:Aisle)-[:IN_SECTION]->(s:Section)
            RETURN a.name AS aisle_name, s.name AS section_name
            """,
            product_id=str(pid),
        )
        record = result.single()
        if not record:
            return {
                "product_name": name,
                "aisle": "Unknown Aisle",
                "section": "Unknown Section",
                "adjacent_items": [],
            }

        aisle_name = record["aisle_name"]
        section_name = record["section_name"]

    adjacent = get_adjacent_products(pid)
    
    return {
        "product_id": str(pid),
        "product_name": name,
        "category": category,
        "aisle": aisle_name,
        "section": section_name,
        "adjacent_items": adjacent,
    }


@mcp.tool()
async def get_seller_pending_orders(seller_id: str) -> List[Dict[str, Any]]:
    """[SELLER ONLY] Get pending orders that contain products owned by the seller."""
    try:
        sid = uuid.UUID(seller_id)
    except ValueError:
        return []

    async with AsyncSessionFactory() as session:
        # Check seller role
        u_result = await session.execute(select(User).where(User.id == sid))
        user = u_result.scalar_one_or_none()
        if not user or user.role != UserRole.seller:
            return []

        result = await session.execute(
            select(Order)
            .join(OrderItem)
            .join(Product)
            .where(Product.seller_id == sid, Order.status != OrderStatus.delivered)
            .options(selectinload(Order.items).joinedload(OrderItem.product))
            .distinct()
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()

        return [
            {
                "order_id": str(o.id),
                "customer_id": str(o.customer_id),
                "status": o.status.value,
                "total": float(o.total),
                "created_at": o.created_at.isoformat(),
                "seller_items": [
                    {
                        "product_name": item.product.name,
                        "quantity": item.quantity,
                        "price": float(item.price_at_purchase),
                    }
                    for item in o.items if item.product and item.product.seller_id == sid
                ]
            }
            for o in orders
        ]


@mcp.tool()
async def update_order_status(order_id: str, new_status: str, seller_id: str) -> Dict[str, Any]:
    """[SELLER ONLY] Update status of an order."""
    try:
        oid = uuid.UUID(order_id)
        sid = uuid.UUID(seller_id)
        status_enum = OrderStatus(new_status)
    except ValueError:
        return {"status": "error", "message": "Invalid input format or status type"}

    async with AsyncSessionFactory() as session:
        # Check seller role
        u_result = await session.execute(select(User).where(User.id == sid))
        user = u_result.scalar_one_or_none()
        if not user or user.role != UserRole.seller:
            return {"status": "error", "message": "Forbidden. Seller role required."}

        # Fetch order
        o_result = await session.execute(
            select(Order).options(selectinload(Order.items).joinedload(OrderItem.product)).where(Order.id == oid)
        )
        order = o_result.scalar_one_or_none()
        if not order:
            return {"status": "error", "message": "Order not found"}

        # Verify seller ownership of at least one product
        owns_product = any(
            item.product.seller_id == sid for item in order.items if item.product
        )
        if not owns_product:
            return {"status": "error", "message": "Forbidden. This order has no products owned by you."}

        order.status = status_enum
        await session.commit()
        return {"status": "success", "message": f"Order status updated to '{status_enum.value}'."}


@mcp.tool()
async def manage_address(
    action: str,
    user_id: str,
    address_id: Optional[str] = None,
    label: Optional[str] = None,
    line1: Optional[str] = None,
    line2: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    postal_code: Optional[str] = None,
    country: Optional[str] = None,
    is_default: Optional[bool] = None,
) -> Dict[str, Any]:
    """Manage saved addresses. Actions: list, create, update, delete."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return {"status": "error", "message": "Invalid user ID"}

    async with AsyncSessionFactory() as session:
        if action == "list":
            result = await session.execute(
                select(Address).where(Address.user_id == uid).order_by(Address.is_default.desc())
            )
            addresses = result.scalars().all()
            return {
                "status": "success",
                "addresses": [
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
                    for a in addresses
                ],
            }

        if action == "create":
            if not label or not line1:
                return {"status": "error", "message": "Label and line1 are required"}
            
            # Check if first address
            count_res = await session.execute(select(Address).where(Address.user_id == uid))
            is_first = len(count_res.scalars().all()) == 0
            should_be_default = is_default or is_first

            if should_be_default:
                from sqlalchemy import update
                await session.execute(
                    update(Address).where(Address.user_id == uid).values(is_default=False)
                )

            address = Address(
                user_id=uid,
                label=label,
                line1=line1,
                line2=line2,
                city=city or "",
                state=state or "",
                postal_code=postal_code or "",
                country=country or "",
                is_default=should_be_default,
            )
            session.add(address)
            await session.commit()
            await session.refresh(address)
            return {"status": "success", "message": f"Address '{address.label}' created.", "id": str(address.id)}

        if action in ("update", "delete"):
            if not address_id:
                return {"status": "error", "message": "Address ID required"}
            try:
                aid = uuid.UUID(address_id)
            except ValueError:
                return {"status": "error", "message": "Invalid address ID"}

            result = await session.execute(
                select(Address).where(Address.id == aid, Address.user_id == uid)
            )
            address = result.scalar_one_or_none()
            if not address:
                return {"status": "error", "message": "Address not found"}

            if action == "delete":
                await session.delete(address)
                await session.commit()
                return {"status": "success", "message": "Address deleted"}

            # Update
            if is_default:
                from sqlalchemy import update
                await session.execute(
                    update(Address).where(Address.user_id == uid).values(is_default=False)
                )
            if label: address.label = label
            if line1: address.line1 = line1
            if line2 is not None: address.line2 = line2
            if city: address.city = city
            if state: address.state = state
            if postal_code: address.postal_code = postal_code
            if country: address.country = country
            if is_default is not None: address.is_default = is_default
            await session.commit()
            return {"status": "success", "message": "Address updated"}

        return {"status": "error", "message": f"Unknown action: {action}"}


@mcp.tool()
async def get_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve user profile information."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return None

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(User).where(User.id == uid))
        user = result.scalar_one_or_none()
        if not user:
            return None

        return {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
        }


@mcp.tool()
async def manage_seller_product(
    action: str,
    seller_id: str,
    product_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    price: Optional[float] = None,
    stock: Optional[int] = None,
) -> Dict[str, Any]:
    """[SELLER ONLY] Manage seller products. Actions: list, create, update, deactivate."""
    try:
        sid = uuid.UUID(seller_id)
    except ValueError:
        return {"status": "error", "message": "Invalid seller ID"}

    async with AsyncSessionFactory() as session:
        # Verify seller role
        u_result = await session.execute(select(User).where(User.id == sid))
        user = u_result.scalar_one_or_none()
        if not user or user.role != UserRole.seller:
            return {"status": "error", "message": "Forbidden. Seller role required."}

        if action == "list":
            result = await session.execute(
                select(Product).where(Product.seller_id == sid).order_by(Product.name.asc())
            )
            products = result.scalars().all()
            return {
                "status": "success",
                "products": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "category": p.category,
                        "price": float(p.price),
                        "stock": p.stock,
                        "is_active": p.is_active,
                    }
                    for p in products
                ],
            }

        if action == "create":
            if not name or price is None:
                return {"status": "error", "message": "Name and price are required"}
            from decimal import Decimal
            product = Product(
                seller_id=sid,
                name=name,
                description=description or "",
                category=category or "General",
                price=Decimal(str(price)),
                stock=stock or 0,
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)
            return {"status": "success", "message": f"Product '{product.name}' created.", "id": str(product.id)}

        if action in ("update", "deactivate"):
            if not product_id:
                return {"status": "error", "message": "Product ID required"}
            try:
                pid = uuid.UUID(product_id)
            except ValueError:
                return {"status": "error", "message": "Invalid product ID"}

            result = await session.execute(
                select(Product).where(Product.id == pid, Product.seller_id == sid)
            )
            product = result.scalar_one_or_none()
            if not product:
                return {"status": "error", "message": "Product not found"}

            if action == "deactivate":
                product.is_active = False
                await session.commit()
                return {"status": "success", "message": f"Product '{product.name}' deactivated"}

            # Update
            if name: product.name = name
            if description is not None: product.description = description
            if category: product.category = category
            if price is not None:
                from decimal import Decimal
                product.price = Decimal(str(price))
            if stock is not None: product.stock = stock
            await session.commit()
            return {"status": "success", "message": f"Product '{product.name}' updated"}

        return {"status": "error", "message": f"Unknown action: {action}"}


if __name__ == "__main__":
    # Start the FastMCP server
    mcp.run()
