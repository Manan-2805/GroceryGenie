"""Tool registry for the agent - pure Python functions, no LLM calls."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db.models.enums import UserRole
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

# Role-based permission map: which roles can use which tools
# 'all' means any authenticated user
ROLE_TOOL_PERMISSIONS: dict[str | UserRole, list[str]] = {
    "all": [
        "search_products",
        "add_to_cart",
        "remove_from_cart",
        "update_cart_quantity",
        "view_cart",
        "place_order",
        "view_orders",
        "switch_role",
        "manage_addresses",
        "view_facts",
    ],
    UserRole.seller: [
        "seller_list_products",
        "seller_create_product",
        "seller_update_product",
        "seller_delete_product",
    ],
}

# Tools that require explicit permission confirmation (destructive actions)
PERMISSION_REQUIRED_TOOLS: set[str] = {
    "place_order",
    "seller_delete_product",
    "remove_from_cart",
    "manage_addresses",  # only for delete/update actions
}

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

# Role-to-seller-tool mapping for the LLM intent prompt
ROLE_RESTRICTED_TOOLS: dict[str, str] = dict.fromkeys(
    ROLE_TOOL_PERMISSIONS.get(UserRole.seller, []), "seller"
)

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
    "seller_list_products": "[SELLER] List seller's own products",
    "seller_create_product": "[SELLER] Create a new product as seller (name, description, category, price, stock)",
    "seller_update_product": "[SELLER] Update a product as seller (product_id, name?, description?, category?, price?, stock?)",
    "seller_delete_product": "[SELLER] Deactivate a product as seller (product_id)",
}


def check_tool_permission(tool_name: str, user_role: UserRole) -> None:
    """Check if the user's role is allowed to use the given tool.
    Raises PermissionError if not allowed.
    """
    # Check if tool is in the 'all' permission list
    all_tools = ROLE_TOOL_PERMISSIONS.get("all", [])
    if tool_name in all_tools:
        return

    # Check if tool is in the user's role-specific permission list
    role_tools = ROLE_TOOL_PERMISSIONS.get(user_role, [])
    if tool_name in role_tools:
        return

    # Not authorized - determine which role is needed
    needed_role = None
    for role, tools in ROLE_TOOL_PERMISSIONS.items():
        if role != "all" and tool_name in tools:
            needed_role = role.value if hasattr(role, "value") else str(role)
            break

    if needed_role:
        raise PermissionError(
            f"Tool '{tool_name}' requires '{needed_role}' role. "
            f"Current role is '{user_role.value if hasattr(user_role, 'value') else user_role}'."
        )
    raise PermissionError(f"Tool '{tool_name}' is not available for any role.")


def get_role_restricted_tools_prompt(user_role: UserRole) -> str:
    """Generate a prompt addition informing the LLM which tools are available."""
    all_tools = list(TOOL_REGISTRY.keys())
    seller_tools = ROLE_TOOL_PERMISSIONS.get(UserRole.seller, [])
    available_tools = [
        t for t in all_tools if t not in seller_tools or user_role == UserRole.seller
    ]
    role_name = user_role.value if hasattr(user_role, "value") else str(user_role)
    return f"Available tools for your role ({role_name}): {', '.join(available_tools)}"
