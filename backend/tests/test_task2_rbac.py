"""
Task 2 verification tests:
  1. seller tool denied for customer
  2. view_orders denied for seller
  3. Every key in TOOL_SCHEMAS has an explicit entry in at least one role's allowlist
"""

import pytest

from app.db.models.enums import UserRole
from app.services.agent.tools import (
    ROLE_PERMISSIONS,
    TOOL_SCHEMAS,
    check_tool_permission,
)


def test_seller_tool_denied_for_customer() -> None:
    """seller_create_product must raise PermissionError for a customer."""
    with pytest.raises(PermissionError, match="requires 'seller'"):
        check_tool_permission("seller_create_product", UserRole.customer)


def test_view_orders_denied_for_seller() -> None:
    """view_orders must raise PermissionError for a seller."""
    with pytest.raises(PermissionError, match="requires 'customer'"):
        check_tool_permission("view_orders", UserRole.seller)


def test_unknown_tool_raises_value_error() -> None:
    """A hallucinated tool name must raise ValueError, not PermissionError."""
    with pytest.raises(ValueError, match="Unknown tool"):
        check_tool_permission("view_products", UserRole.customer)


def test_every_schema_tool_has_role_entry() -> None:
    """Every tool in TOOL_SCHEMAS must appear in at least one role's allowlist.

    This is the 'no unassigned tool' invariant from the plan.
    Exceptions: toggle_theme and switch_role are shared tools listed under _SHARED_TOOLS
    and appear in every role's list — they pass automatically.
    """
    all_permitted: set[str] = set()
    for tools in ROLE_PERMISSIONS.values():
        all_permitted.update(tools)

    unassigned = [t for t in TOOL_SCHEMAS if t not in all_permitted]
    assert unassigned == [], (
        f"Tools in TOOL_SCHEMAS with no role entry: {unassigned}\n"
        "Add them to ROLE_PERMISSIONS or they will always be denied."
    )


def test_shared_tools_available_for_all_roles() -> None:
    """toggle_theme, switch_role, manage_facts must work for both roles."""
    for shared in ("toggle_theme", "switch_role", "manage_facts"):
        for role in UserRole:
            check_tool_permission(shared, role)  # must not raise


def test_customer_tools_denied_for_seller() -> None:
    """Customer-only tools (place_order, view_orders, submit_rating) must be denied for seller."""
    customer_only = [
        "place_order",
        "view_orders",
        "submit_rating",
        "view_cart",
        "add_to_cart",
        "get_order_detail",
        "compare_products",
    ]
    for tool in customer_only:
        with pytest.raises(PermissionError):
            check_tool_permission(tool, UserRole.seller)


def test_seller_tools_denied_for_customer() -> None:
    """Seller-only tools must be denied for customer."""
    seller_only = [
        "seller_create_product",
        "seller_update_product",
        "seller_delete_product",
        "seller_bulk_deactivate",
        "seller_update_stock",
        "inventory_search",
        "list_fulfillment_orders",
        "update_order_status",
        "seller_list_products",
    ]
    for tool in seller_only:
        with pytest.raises(PermissionError):
            check_tool_permission(tool, UserRole.customer)
