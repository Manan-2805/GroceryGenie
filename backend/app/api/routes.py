"""
Route registry API endpoint.
Provides the frontend route information so the AI agent can navigate correctly.
"""

import logging
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/routes", tags=["Route Registry"])
logger = logging.getLogger("app.api.routes")

# Available frontend routes with metadata
FRONTEND_ROUTES = [
    {
        "path": "/",
        "label": "Home",
        "roles": ["customer", "seller"],
        "description": "Home page - shows role-based landing",
    },
    {
        "path": "/items",
        "label": "Catalog",
        "roles": ["customer"],
        "description": "Browse all available grocery products",
    },
    {
        "path": "/items/:id",
        "label": "Product Detail",
        "roles": ["customer"],
        "description": "View details of a specific product",
    },
    {
        "path": "/cart",
        "label": "Shopping Cart",
        "roles": ["customer"],
        "description": "View and manage your shopping cart",
    },
    {
        "path": "/checkout",
        "label": "Checkout",
        "roles": ["customer"],
        "description": "Complete your order and checkout",
    },
    {
        "path": "/orders",
        "label": "Order History",
        "roles": ["customer"],
        "description": "View your past orders and their status",
    },
    {
        "path": "/seller",
        "label": "Seller Dashboard",
        "roles": ["seller"],
        "description": "Seller analytics and business overview",
    },
    {
        "path": "/inventory",
        "label": "Inventory Management",
        "roles": ["seller"],
        "description": "Manage your product inventory",
    },
    {
        "path": "/fulfillment",
        "label": "Fulfillment Queue",
        "roles": ["seller"],
        "description": "Process and fulfill customer orders",
    },
    {
        "path": "/analysis",
        "label": "Sales Analysis",
        "roles": ["seller"],
        "description": "View sales data and analytics",
    },
    {
        "path": "/settings",
        "label": "Settings",
        "roles": ["customer", "seller"],
        "description": "User profile and application settings",
    },
    {
        "path": "/agent",
        "label": "AI Assistant",
        "roles": ["customer", "seller"],
        "description": "Chat with the GroceryGenie AI assistant",
    },
]


@router.get("")
async def get_routes() -> dict[str, Any]:
    """Get all available frontend routes with metadata."""
    return {
        "routes": FRONTEND_ROUTES,
        "total": len(FRONTEND_ROUTES),
    }
