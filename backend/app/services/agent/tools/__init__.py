"""
Tool registry for the GroceryGenie agent.

Contains:
  TOOL_SCHEMAS       — per-tool field definitions used by SlotValidator + IntentClassifier
  ROLE_PERMISSIONS   — explicit allowlist per role (fail-closed: unlisted = denied)
  TOOL_REGISTRY      — maps tool name → async callable
  TOOL_DESCRIPTIONS  — short descriptions for the LLM intent prompt
  check_tool_permission() — raises ValueError (unknown) or PermissionError (denied)
"""

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
from app.services.agent.tools.compare_tools import compare_products
from app.services.agent.tools.fulfillment_tools import (
    list_fulfillment_orders,
    update_order_status,
)
from app.services.agent.tools.inventory_tools import inventory_search
from app.services.agent.tools.order_tools import (
    get_order_detail,
    place_order,
    view_orders,
)
from app.services.agent.tools.product_tools import search_products
from app.services.agent.tools.profile_tools import manage_facts, switch_role
from app.services.agent.tools.rating_tools import submit_rating
from app.services.agent.tools.seller_tools import (
    seller_bulk_deactivate,
    seller_create_product,
    seller_delete_product,
    seller_list_products,
    seller_update_product,
    seller_update_stock,
)

# ---------------------------------------------------------------------------
# TOOL_SCHEMAS
# ---------------------------------------------------------------------------
# Each entry defines:
#   required      — fields SlotValidator will ask for if absent
#   optional      — fields LLM may extract but we never ask the user for
#   types         — coercion map (field → Python type)
#   hints         — human-readable descriptions shown in slot-fill asks
#   category_enum — valid string values (for category-like fields)
#
# Tools that need no slot-filling (0 required fields) still appear here so
# the "every tool has a schema entry" invariant holds for the RBAC test.
# ---------------------------------------------------------------------------

_PRODUCT_CATEGORIES = [
    "Fruits",
    "Vegetables",
    "Dairy",
    "Meat",
    "Beverages",
    "Bakery",
    "Snacks",
    "Grains",
    "Frozen",
    "Other",
]

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Customer tools ──────────────────────────────────────────────────────
    "search_products": {
        "required": [],
        "optional": [
            "query",
            "category",
            "min_price",
            "max_price",
            "min_rating",
            "in_stock_only",
        ],
        "types": {
            "min_price": float,
            "max_price": float,
            "min_rating": float,
            "in_stock_only": bool,
        },
        "hints": {
            "query": "Search keywords (e.g. 'organic milk')",
            "category": f"One of: {', '.join(_PRODUCT_CATEGORIES)}",
            "min_price": "Minimum price in USD (e.g. 1.00)",
            "max_price": "Maximum price in USD (e.g. 10.00)",
            "min_rating": "Minimum average rating 0-5 (e.g. 4.0)",
            "in_stock_only": "true to show only in-stock items (default: false)",
        },
    },
    "compare_products": {
        "required": ["product_ids"],
        "optional": [],
        "types": {},
        "hints": {
            "product_ids": "List of 2-3 product UUIDs to compare side-by-side",
        },
    },
    "add_to_cart": {
        "required": ["product_id"],
        "optional": ["quantity"],
        "types": {"quantity": int},
        "hints": {
            "product_id": "UUID of the product to add",
            "quantity": "How many to add (default: 1)",
        },
    },
    "remove_from_cart": {
        "required": ["product_id"],
        "optional": [],
        "types": {},
        "hints": {"product_id": "UUID of the product to remove"},
    },
    "update_cart_quantity": {
        "required": ["product_id", "quantity"],
        "optional": [],
        "types": {"quantity": int},
        "hints": {
            "product_id": "UUID of the product in your cart",
            "quantity": "New quantity (e.g. 3)",
        },
    },
    "view_cart": {
        "required": [],
        "optional": [],
        "types": {},
        "hints": {},
    },
    "place_order": {
        "required": [],
        "optional": [],
        "types": {},
        "hints": {},
    },
    "view_orders": {
        "required": [],
        "optional": [
            "status",
            "date_from",
            "date_to",
            "min_total",
            "max_total",
            "product_name",
        ],
        "types": {"min_total": float, "max_total": float},
        "hints": {
            "status": "Filter by status: placed / packed / out_for_delivery / delivered",
            "date_from": "Start date YYYY-MM-DD",
            "date_to": "End date YYYY-MM-DD",
            "min_total": "Minimum order total (e.g. 5.00)",
            "max_total": "Maximum order total (e.g. 50.00)",
            "product_name": "Show only orders containing this product name",
        },
    },
    "get_order_detail": {
        "required": ["order_id"],
        "optional": [],
        "types": {},
        "hints": {"order_id": "UUID of the order to view"},
    },
    "submit_rating": {
        "required": ["order_id", "product_id", "stars"],
        "optional": ["comment"],
        "types": {"stars": int},
        "hints": {
            "order_id": "UUID of the delivered order",
            "product_id": "UUID of the product to rate",
            "stars": "Rating 1-5 stars",
            "comment": "Optional review text",
        },
    },
    "manage_addresses": {
        "required_for_add": ["label", "line1", "city", "state", "postal_code"],
        "required": [],  # top-level required is empty; sub-action validation in SlotValidator
        "optional": ["action", "address_id", "address_data"],
        "types": {},
        "hints": {
            "action": "list / add / update / delete",
            "label": "Nickname e.g. Home, Work, Office",
            "line1": "Street address e.g. B-63 Street 5",
            "city": "City name",
            "state": "State or province",
            "postal_code": "Postal / ZIP / pin code",
            "country": "Country (default: India)",
        },
    },
    "manage_facts": {
        "required": ["action"],
        "optional": ["fact_text", "fact_id", "category"],
        "types": {},
        "hints": {
            "action": "list / add / delete / update",
            "fact_text": "The fact to add or the new text when updating",
            "fact_id": "UUID or 1-based index number of the fact to delete/update",
            "category": "dietary / preference / instruction / other",
        },
    },
    "switch_role": {
        "required": ["role"],
        "optional": [],
        "types": {},
        "hints": {"role": "customer or seller"},
    },
    "toggle_theme": {
        "required": [],
        "optional": [],
        "types": {},
        "hints": {},
    },
    # ── Seller tools ─────────────────────────────────────────────────────────
    "seller_list_products": {
        "required": [],
        "optional": [],
        "types": {},
        "hints": {},
    },
    "inventory_search": {
        "required": [],
        "optional": [
            "stock_filter",
            "min_rating",
            "min_sold",
            "max_sold",
            "min_price",
            "max_price",
            "category",
            "query",
            "sort_by",
        ],
        "types": {
            "min_rating": float,
            "min_sold": int,
            "max_sold": int,
            "min_price": float,
            "max_price": float,
        },
        "hints": {
            "stock_filter": "in_stock / low_stock / out_of_stock",
            "min_rating": "Minimum average rating 0-5",
            "min_sold": "Minimum units sold",
            "max_sold": "Maximum units sold",
            "min_price": "Minimum price USD",
            "max_price": "Maximum price USD",
            "category": "Partial match e.g. 'Fruits', 'Dairy' (not a product name)",
            "query": "Product name keyword e.g. 'apple' to find all apple products",
            "sort_by": "stock_asc / stock_desc / rating_desc / sold_desc / price_asc / price_desc",
        },
    },
    "seller_create_product": {
        "required": ["name", "price", "stock"],
        "optional": ["description", "category"],
        "types": {"price": float, "stock": int},
        "hints": {
            "name": "Product name (e.g. 'Fresh Mango')",
            "price": "Price in USD (e.g. 4.99)",
            "stock": "Initial stock quantity (e.g. 100)",
            "description": "Short product description",
            "category": f"One of: {', '.join(_PRODUCT_CATEGORIES)} (default: Other)",
        },
        # image_url is intentionally excluded — always null, never asked
    },
    "seller_update_product": {
        "required": ["product_id"],
        "optional": ["name", "description", "category", "price", "stock"],
        "types": {"price": float, "stock": int},
        "hints": {
            "product_id": "UUID of the product to update",
            "name": "New product name",
            "description": "New description",
            "category": f"One of: {', '.join(_PRODUCT_CATEGORIES)}",
            "price": "New price in USD",
            "stock": "New stock quantity (replaces current — use seller_update_stock for delta)",
        },
    },
    "seller_update_stock": {
        "required": ["product_id", "delta"],
        "optional": [],
        "types": {"delta": int},
        "hints": {
            "product_id": "UUID of the product",
            "delta": "Integer delta: positive to add stock, negative to reduce (e.g. +10 or -5)",
        },
    },
    "seller_delete_product": {
        "required": ["product_id"],
        "optional": [],
        "types": {},
        "hints": {"product_id": "UUID of the product to deactivate"},
    },
    "seller_bulk_deactivate": {
        "required": ["product_ids"],
        "optional": [],
        "types": {},
        "hints": {
            "product_ids": "List of product UUIDs to deactivate. Pass [] to deactivate ALL your products.",
        },
    },
    "list_fulfillment_orders": {
        "required": [],
        "optional": [
            "status",
            "min_total",
            "max_total",
            "date_from",
            "date_to",
            "product_name",
            "customer_city",
            "customer_name",
        ],
        "types": {"min_total": float, "max_total": float},
        "hints": {
            "status": "placed / packed / out_for_delivery / delivered",
            "min_total": "Minimum order total",
            "max_total": "Maximum order total",
            "date_from": "Start date YYYY-MM-DD",
            "date_to": "End date YYYY-MM-DD",
            "product_name": "Show only orders containing this product name",
            "customer_city": "Filter by delivery city",
            "customer_name": "Filter by customer name substring",
        },
    },
    "update_order_status": {
        "required": ["order_ids", "new_status"],
        "optional": [],
        "types": {},
        "hints": {
            "order_ids": "List of order UUIDs to advance (one step at a time per order)",
            "new_status": "packed / out_for_delivery / delivered",
        },
    },
}

# ---------------------------------------------------------------------------
# ROLE_PERMISSIONS — explicit allowlist, fail-closed
# ---------------------------------------------------------------------------
# Any tool NOT listed for the current role is DENIED.
# "follow_up" and "out_of_scope" are virtual tools handled before RBAC —
# they are intentionally NOT in this map; the orchestrator bypasses RBAC for them.
# "toggle_theme" and "switch_role" are available to all authenticated users.
# ---------------------------------------------------------------------------

_SHARED_TOOLS: list[str] = ["toggle_theme", "switch_role", "manage_facts"]

ROLE_PERMISSIONS: dict[UserRole, list[str]] = {
    UserRole.customer: [
        *_SHARED_TOOLS,
        "search_products",
        "compare_products",
        "add_to_cart",
        "remove_from_cart",
        "update_cart_quantity",
        "view_cart",
        "place_order",
        "view_orders",
        "get_order_detail",
        "submit_rating",
        "manage_addresses",
    ],
    UserRole.seller: [
        *_SHARED_TOOLS,
        "seller_list_products",
        "inventory_search",
        "seller_create_product",
        "seller_update_product",
        "seller_update_stock",
        "seller_delete_product",
        "seller_bulk_deactivate",
        "list_fulfillment_orders",
        "update_order_status",
    ],
}

# ---------------------------------------------------------------------------
# TOOL_REGISTRY — maps tool name → async callable
# ---------------------------------------------------------------------------
# New tools (compare_products, submit_rating, manage_facts, seller_update_stock,
# seller_bulk_deactivate) are imported lazily below to avoid circular imports
# during the refactor. They will be added to this dict in Task 5 once the
# tool files are written.
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    # Customer
    "search_products": search_products,
    "compare_products": compare_products,
    "add_to_cart": add_to_cart,
    "remove_from_cart": remove_from_cart,
    "update_cart_quantity": update_cart_quantity,
    "view_cart": get_cart,
    "place_order": place_order,
    "view_orders": view_orders,
    "get_order_detail": get_order_detail,
    "submit_rating": submit_rating,
    "manage_addresses": manage_addresses,
    # Seller
    "seller_list_products": seller_list_products,
    "seller_create_product": seller_create_product,
    "seller_update_product": seller_update_product,
    "seller_update_stock": seller_update_stock,
    "seller_delete_product": seller_delete_product,
    "seller_bulk_deactivate": seller_bulk_deactivate,
    "list_fulfillment_orders": list_fulfillment_orders,
    "update_order_status": update_order_status,
    "inventory_search": inventory_search,
    # Shared
    "switch_role": switch_role,
    "manage_facts": manage_facts,
}

# ---------------------------------------------------------------------------
# TOOL_DESCRIPTIONS — short descriptions for the LLM intent prompt
# ---------------------------------------------------------------------------

TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_products": "Search for products (query, category, min_price, max_price, in_stock_only, min_rating)",
    "compare_products": "Compare 2-3 products side-by-side (product_ids: list of UUIDs)",
    "add_to_cart": "Add a product to cart (product_id, quantity)",
    "remove_from_cart": "Remove a product from cart (product_id)",
    "update_cart_quantity": "Update quantity of a cart item (product_id, quantity)",
    "view_cart": "View the current cart contents",
    "place_order": "Place an order using current cart and default address",
    "view_orders": "View customer order history with optional filters",
    "get_order_detail": "View full detail of a specific order (order_id)",
    "submit_rating": "Submit a rating and review for a delivered order item (order_id, product_id, stars, comment?)",
    "manage_addresses": "Manage delivery addresses (action: list/add/update/delete)",
    "manage_facts": "Manage personal preferences/facts (action: list/add/delete/update)",
    "switch_role": "Switch between customer and seller role (role: customer/seller)",
    "toggle_theme": "Toggle light/dark theme",
    "seller_list_products": "[SELLER] List all your products",
    "inventory_search": "[SELLER] Search your inventory with filters (query: name keyword, stock_filter: in_stock/low_stock/out_of_stock, category: partial match, min_rating, min_sold, sort_by)",
    "seller_create_product": "[SELLER] Create a new product (name, price, stock required; description, category optional)",
    "seller_update_product": "[SELLER] Update a product (product_id required; name/description/category/price/stock optional)",
    "seller_update_stock": "[SELLER] Adjust product stock by a delta (product_id, delta: positive=add, negative=reduce)",
    "seller_delete_product": "[SELLER] Deactivate a single product (product_id)",
    "seller_bulk_deactivate": "[SELLER] Deactivate multiple products at once (product_ids: list or [] for all)",
    "list_fulfillment_orders": "[SELLER] List orders to fulfill with optional filters",
    "update_order_status": "[SELLER] Advance order(s) through fulfilment state machine (order_ids: list, new_status)",
}

# ---------------------------------------------------------------------------
# LEGACY ALIAS — kept so existing orchestrator.py import doesn't break until
# Task 9 rewrites it. Will be removed in Task 13.
# ---------------------------------------------------------------------------
ROLE_TOOL_PERMISSIONS = ROLE_PERMISSIONS  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# check_tool_permission — FAIL-CLOSED
# ---------------------------------------------------------------------------


def check_tool_permission(tool_name: str, user_role: UserRole) -> None:
    """Check whether *user_role* may invoke *tool_name*.

    Fail-closed contract:
      - Any tool not in TOOL_SCHEMAS raises ValueError (unknown tool — likely LLM hallucination).
      - Any tool not explicitly listed in ROLE_PERMISSIONS[user_role] raises PermissionError.
      - "follow_up", "out_of_scope", and "toggle_theme" bypass this guard in the orchestrator
        before check_tool_permission is called, so they do not need entries here.

    Raises:
        ValueError:       tool_name not in TOOL_SCHEMAS (unknown / hallucinated).
        PermissionError:  tool exists but user_role cannot use it.
    """
    if tool_name not in TOOL_SCHEMAS:
        raise ValueError(f"Unknown tool: '{tool_name}'")

    allowed = ROLE_PERMISSIONS.get(user_role, [])
    if tool_name in allowed:
        return

    # Find which role(s) can use this tool for a helpful error message
    needed_roles = [
        role.value
        for role, tools in ROLE_PERMISSIONS.items()
        if tool_name in tools and role != user_role
    ]

    current = user_role.value if hasattr(user_role, "value") else str(user_role)

    if needed_roles:
        needed = needed_roles[0]
        raise PermissionError(
            f"Tool '{tool_name}' requires '{needed}' role. Current role is '{current}'."
        )

    # Tool is in TOOL_SCHEMAS but in no role's allowlist — configuration error,
    # still deny the user rather than allow.
    raise PermissionError(f"Tool '{tool_name}' is not available for role '{current}'.")
