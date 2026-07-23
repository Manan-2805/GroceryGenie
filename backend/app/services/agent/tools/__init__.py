"""Tool registry for the agent - pure Python functions, no LLM calls."""

from collections.abc import Callable
from typing import Any

from app.services.agent.tools.address_tools import manage_addresses
from app.services.agent.tools.cart_tools import (
    add_to_cart,
    get_cart,
    remove_from_cart,
    update_cart_quantity,
)
from app.services.agent.tools.order_tools import place_order, view_orders
from app.services.agent.tools.product_tools import search_products
from app.services.agent.tools.profile_tools import get_facts, switch_role
from app.services.agent.tools.seller_tools import (
    seller_create_product,
    seller_delete_product,
    seller_list_products,
    seller_update_product,
)

# Tool registry: maps tool names to their async callable
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "search_products": search_products,
    "add_to_cart": add_to_cart,
    "remove_from_cart": remove_from_cart,
    "update_cart_quantity": update_cart_quantity,
    "view_cart": get_cart,
    "place_order": place_order,
    "view_orders": view_orders,
    "switch_role": switch_role,
    "manage_addresses": manage_addresses,
    "view_facts": get_facts,
    "seller_list_products": seller_list_products,
    "seller_create_product": seller_create_product,
    "seller_update_product": seller_update_product,
    "seller_delete_product": seller_delete_product,
}

# Tool descriptions for the LLM intent classifier
TOOL_DESCRIPTIONS = {
    "search_products": "Search for products with filters (query, category, min_price, max_price, in_stock_only, min_rating)",
    "add_to_cart": "Add a product to cart (product_id, quantity)",
    "remove_from_cart": "Remove a product from cart (product_id)",
    "update_cart_quantity": "Update quantity of a cart item (product_id, quantity)",
    "view_cart": "View the current cart contents",
    "place_order": "Place an order using current cart and default address",
    "view_orders": "View order history",
    "switch_role": "Switch between customer and seller role (role: 'customer' or 'seller')",
    "manage_addresses": "Manage addresses (action: 'list'/'add'/'update'/'delete'; address_data object with label, line1, line2, city, state, postal_code, country, is_default)",
    "view_facts": "View persistent facts/preferences about the user",
    "seller_list_products": "List seller's own products",
    "seller_create_product": "Create a new product as seller (name, description, category, price, stock)",
    "seller_update_product": "Update a product as seller (product_id, name?, description?, category?, price?, stock?)",
    "seller_delete_product": "Deactivate a product as seller (product_id)",
}
