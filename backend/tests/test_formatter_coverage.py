"""
Task 6 — Formatter coverage tests.

Calls every single formatter path once with representative data.
Runs as part of the normal pytest suite going forward.

Explicit regression for BUG-02:
    format_response({"order_detail": True, "items": [...], "total": 4.99, ...})
    must return an order detail card, NOT a cart card.
"""

from __future__ import annotations

import uuid

from app.services.agent.response_formatter import format_response

# ── Helpers ──────────────────────────────────────────────────────────────────


def _order_detail_result(**overrides):
    base = {
        "order_detail": True,
        "id": str(uuid.uuid4()),
        "status": "delivered",
        "total": 4.99,
        "created_at": "2026-07-24T10:00:00",
        "packed_at": "2026-07-24T11:00:00",
        "out_for_delivery_at": "2026-07-24T12:00:00",
        "delivered_at": "2026-07-24T14:00:00",
        "delivery_address": {
            "label": "Home",
            "line1": "B-63 Street 5",
            "city": "Bhuj",
            "state": "Gujarat",
            "postal_code": "370001",
        },
        "items": [
            {
                "product_name": "Organic Milk",
                "product_id": str(uuid.uuid4()),
                "quantity": 1,
                "price_at_purchase": 2.49,
                "subtotal": 2.49,
            },
            {
                "product_name": "Fresh Mango",
                "product_id": str(uuid.uuid4()),
                "quantity": 2,
                "price_at_purchase": 1.25,
                "subtotal": 2.50,
            },
        ],
    }
    base.update(overrides)
    return base


def _cart_result():
    return {
        "items": [
            {
                "product_id": str(uuid.uuid4()),
                "name": "Organic Milk",
                "price": 2.49,
                "quantity": 1,
                "total": 2.49,
            },
        ],
        "total": 2.49,
    }


def _fulfillment_row(**overrides):
    oid = str(uuid.uuid4())
    base = {
        "fulfillment_queue": True,
        "order_id": oid,
        "order_id_short": oid[:8],
        "status": "placed",
        "status_label": "Placed",
        "total": 9.99,
        "created_at": "2026-07-25T10:00:00",
        "my_items": [
            {"product_name": "Fresh Mango", "quantity": 2, "price_at_purchase": 4.49}
        ],
        "my_items_count": 1,
        "next_status": "packed",
        "next_action_label": "Mark Packed",
        "advance_value": f"fulfillment_status_{oid}_packed",
        "delivery_address": {},
    }
    base.update(overrides)
    return base


# ── BUG-02 regression ─────────────────────────────────────────────────────────


def test_bug02_order_detail_not_formatted_as_cart():
    """
    REGRESSION BUG-02:
    A result with order_detail=True AND 'items'+'total' keys must return
    an order detail card, never a cart card.
    """
    result = _order_detail_result()
    # Sanity check: it has both 'items' AND 'total' — the old bug would match cart
    assert "items" in result and "total" in result

    response = format_response(result, "get_order_detail")

    # Must NOT be a cart
    assert response.get("card_variant") != "cart", (
        "BUG-02 REGRESSION: order_detail result was formatted as cart!"
    )
    # Must be an order detail card
    assert response.get("card_variant") == "order_detail", (
        f"Expected card_variant='order_detail', got {response.get('card_variant')!r}"
    )
    assert response["type"] == "options_response"
    # Timeline must appear in text
    assert "Placed" in response["text"]
    assert "Delivered" in response["text"]


# ── Path 1: success/failure dict ──────────────────────────────────────────────


def test_format_success_message():
    result = {"success": True, "message": "Added to cart."}
    r = format_response(result, "add_to_cart")
    assert r["type"] == "response"
    assert r["text"] == "Added to cart."


def test_format_failure_message():
    result = {"success": False, "message": "Product not found."}
    r = format_response(result, "add_to_cart")
    assert r["type"] == "response"
    assert r["text"] == "Product not found."


# ── Path 2: empty ─────────────────────────────────────────────────────────────


def test_format_empty_result():
    result = {"empty": True, "message": "You have no orders yet."}
    r = format_response(result, "view_orders")
    assert r["type"] == "response"
    assert "no orders" in r["text"].lower()


# ── Path 3: order detail ──────────────────────────────────────────────────────


def test_format_order_detail_full():
    result = _order_detail_result()
    r = format_response(result, "get_order_detail")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "order_detail"
    assert "Organic Milk" in r["text"]
    assert "Bhuj" in r["text"]


def test_format_order_detail_minimal():
    """Order detail with no timestamps or address still renders cleanly."""
    result = {
        "order_detail": True,
        "id": str(uuid.uuid4()),
        "status": "placed",
        "total": 5.00,
        "items": [
            {
                "product_name": "Apple",
                "quantity": 1,
                "price_at_purchase": 5.00,
                "subtotal": 5.00,
            }
        ],
        "delivery_address": {},
    }
    r = format_response(result, "get_order_detail")
    assert r["card_variant"] == "order_detail"
    assert "Apple" in r["text"]


# ── Path 4: compare ───────────────────────────────────────────────────────────


def test_format_compare():
    pid1, pid2 = str(uuid.uuid4()), str(uuid.uuid4())
    result = {
        "compare": True,
        "products": [
            {
                "id": pid1,
                "name": "Mango",
                "category": "Fruits",
                "price": 4.99,
                "stock": 20,
                "avg_rating": 4.5,
                "sold_count": 10,
                "description": "Juicy",
            },
            {
                "id": pid2,
                "name": "Apple",
                "category": "Fruits",
                "price": 2.99,
                "stock": 40,
                "avg_rating": 4.2,
                "sold_count": 5,
                "description": "Crisp",
            },
        ],
    }
    r = format_response(result, "compare_products")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "compare"
    assert "Mango" in r["text"]
    assert "Apple" in r["text"]
    assert "$4.99" in r["text"]
    # Both products should be in options
    assert len(r["options"]) == 2


def test_format_compare_empty():
    r = format_response({"compare": True, "products": []}, "compare_products")
    assert r["type"] == "response"


# ── Path 5: already_rated ─────────────────────────────────────────────────────


def test_format_already_rated():
    result = {
        "already_rated": True,
        "stars": 4,
        "comment": "Good product",
        "submitted_at": "2026-07-24T10:00:00",
        "message": 'You already reviewed this on 2026-07-24: 4★ — "Good product".',
    }
    r = format_response(result, "submit_rating")
    assert r["type"] == "response"
    assert "already" in r["text"].lower()


# ── Path 6: bulk_deactivate ───────────────────────────────────────────────────


def test_format_bulk_deactivate_success():
    pid1 = str(uuid.uuid4())
    result = {
        "bulk_deactivate": True,
        "succeeded": [{"id": pid1, "name": "Mango"}],
        "failed": [],
        "message": "Deactivated 1 of 1 products.",
    }
    r = format_response(result, "seller_bulk_deactivate")
    assert r["type"] == "response"
    assert "1 succeeded" in r["text"]
    assert "Mango" in r["text"]


def test_format_bulk_deactivate_partial_failure():
    pid1, pid2 = str(uuid.uuid4()), str(uuid.uuid4())
    result = {
        "bulk_deactivate": True,
        "succeeded": [{"id": pid1, "name": "Mango"}],
        "failed": [{"id": pid2, "reason": "Not found"}],
        "message": "Deactivated 1 of 2 products.",
    }
    r = format_response(result, "seller_bulk_deactivate")
    assert "1 succeeded" in r["text"]
    assert "1 failed" in r["text"]
    assert "Not found" in r["text"]


# ── Path 7: bulk_status_update ────────────────────────────────────────────────


def test_format_bulk_status_update():
    oid1, oid2 = str(uuid.uuid4()), str(uuid.uuid4())
    result = {
        "bulk_status_update": True,
        "succeeded": [{"id": oid1, "message": "Marked packed"}],
        "failed": [{"id": oid2, "reason": "Already delivered"}],
        "message": "Updated 1 of 2 orders.",
    }
    r = format_response(result, "update_order_status")
    assert r["type"] == "response"
    assert "1 updated" in r["text"]
    assert "1 failed" in r["text"]


# ── Path 8: facts_list ────────────────────────────────────────────────────────


def test_format_facts_list():
    fid = str(uuid.uuid4())
    result = {
        "facts_list": True,
        "facts": [
            {
                "index": 1,
                "id": fid,
                "fact_text": "Vegan",
                "category": "dietary",
                "created_at": "2026-07-24T10:00:00",
            },
        ],
        "count": 1,
    }
    r = format_response(result, "manage_facts")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "facts"
    assert "Vegan" in r["text"]
    assert len(r["options"]) == 1
    assert r["options"][0]["actions"][0]["value"] == f"delete_fact_{fid}"


def test_format_facts_list_empty():
    result = {"facts_list": True, "facts": [], "message": "No saved preferences."}
    r = format_response(result, "manage_facts")
    assert r["type"] == "response"
    assert "no" in r["text"].lower()


# ── Path 9: cart ──────────────────────────────────────────────────────────────


def test_format_cart():
    result = _cart_result()
    r = format_response(result, "view_cart")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "cart"
    assert "$2.49" in r["text"]
    assert "Checkout" in r["options"][-1]["label"]


def test_format_cart_never_triggered_by_order_detail():
    """
    If a result has BOTH order_detail=True AND items+total,
    cart formatter must NOT fire. (Duplicate of BUG-02 check from a different angle.)
    """
    result = _order_detail_result()
    r = format_response(result, "get_order_detail")
    assert r.get("card_variant") != "cart"


# ── Path 10: fulfillment queue ────────────────────────────────────────────────


def test_format_fulfillment_queue():
    result = [
        _fulfillment_row(),
        _fulfillment_row(status="packed", status_label="Packed"),
    ]
    r = format_response(result, "list_fulfillment_orders")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "fulfillment_queue"
    assert len(r["options"]) == 2
    # Advance button should appear for placed orders
    placed_opt = next(o for o in r["options"] if "Placed" in o["label"])
    assert any(a["label"] == "Mark Packed" for a in placed_opt["actions"])


# ── Path 11: orders list ──────────────────────────────────────────────────────


def test_format_orders_list():
    oid = str(uuid.uuid4())
    result = [
        {
            "id": oid,
            "status": "placed",
            "total": 5.99,
            "created_at": "2026-07-25T10:00:00",
            "items": [
                {"product_name": "Milk", "quantity": 1, "price_at_purchase": 5.99}
            ],
        }
    ]
    r = format_response(result, "view_orders")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "orders"
    assert "PLACED" in r["text"]
    assert r["options"][0]["actions"][0]["value"] == f"order_detail_{oid}"


# ── Path 12: addresses ────────────────────────────────────────────────────────


def test_format_addresses():
    aid = str(uuid.uuid4())
    result = {
        "addresses": [
            {
                "id": aid,
                "label": "Home",
                "line1": "B-63 Street 5",
                "city": "Bhuj",
                "state": "Gujarat",
                "postal_code": "370001",
                "country": "India",
                "is_default": True,
            },
        ]
    }
    r = format_response(result, "manage_addresses")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "addresses"
    assert "Bhuj" in r["text"]
    assert any(
        a["value"] == f"delete_address_{aid}" for a in r["options"][0]["actions"]
    )


def test_format_addresses_empty():
    r = format_response({"addresses": []}, "manage_addresses")
    assert r["type"] == "response"
    assert "no saved" in r["text"].lower()


# ── Path 13: seller catalog ───────────────────────────────────────────────────


def test_format_seller_catalog():
    pid = str(uuid.uuid4())
    result = [
        {
            "id": pid,
            "name": "Mango",
            "category": "Fruits",
            "price": 4.99,
            "stock": 20,
            "is_active": True,
            "sold_count": 5,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Old Item",
            "category": "Other",
            "price": 1.99,
            "stock": 0,
            "is_active": False,
            "sold_count": 0,
        },
    ]
    r = format_response(result, "seller_list_products")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "seller_catalog"
    assert "1 active" in r["text"]
    assert "1 inactive" in r["text"]
    assert "Create Product" in r["options"][-1]["label"]


# ── Path 14: inventory ────────────────────────────────────────────────────────


def test_format_inventory():
    result = [
        {
            "_summary": True,
            "stock_status": "summary",
            "in_stock_count": 1,
            "low_stock_count": 1,
            "out_of_stock_count": 0,
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Mango",
            "price": 4.99,
            "stock": 20,
            "avg_rating": 4.5,
            "sold_count": 3,
            "is_active": True,
            "stock_status": "in_stock",
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Apple",
            "price": 2.99,
            "stock": 5,
            "avg_rating": 3.8,
            "sold_count": 1,
            "is_active": True,
            "stock_status": "low_stock",
        },
    ]
    r = format_response(result, "inventory_search")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "inventory"
    assert "🟢" in r["text"]
    assert "🟡" in r["text"]
    assert len(r["options"]) == 2  # summary row excluded from options


# ── Path 15: search results ───────────────────────────────────────────────────


def test_format_search_results():
    pid = str(uuid.uuid4())
    result = [
        {
            "id": pid,
            "name": "Organic Milk",
            "category": "Dairy",
            "price": 2.49,
            "stock": 50,
            "avg_rating": 4.7,
            "sold_count": 100,
            "description": "Fresh milk",
        },
    ]
    r = format_response(result, "search_products")
    assert r["type"] == "options_response"
    assert r["card_variant"] == "search"
    assert "Found 1 product" in r["text"]
    assert r["options"][0]["actions"][0]["value"] == f"add_{pid}"


def test_format_search_results_empty_list():
    r = format_response([], "search_products")
    assert r["type"] == "response"
    assert "no products" in r["text"].lower()


def test_format_search_out_of_stock_no_add_button():
    """Out-of-stock products should not have an Add to Cart action."""
    pid = str(uuid.uuid4())
    result = [
        {
            "id": pid,
            "name": "Sold Out Item",
            "category": "Dairy",
            "price": 3.99,
            "stock": 0,
            "avg_rating": 4.0,
            "sold_count": 50,
            "description": "Out of stock",
        },
    ]
    r = format_response(result, "search_products")
    opt = r["options"][0]
    assert not any(a["value"].startswith("add_") for a in opt.get("actions", []))


# ── Path 16: unknown shape → generic "Done." ─────────────────────────────────


def test_format_unknown_shape():
    result = {"some_weird_key": "some_value", "another_key": 42}
    r = format_response(result, "unknown_tool")
    assert r["type"] == "response"
    assert r["text"] == "Done."


# ── card_variant present in options_response (BUG-10 regression) ─────────────


def test_card_variant_present_on_all_options_responses():
    """Every options_response must carry a card_variant key (BUG-10 fix verification)."""
    cases = [
        (_order_detail_result(), "get_order_detail"),
        (_cart_result(), "view_cart"),
        ([_fulfillment_row()], "list_fulfillment_orders"),
        (
            [
                {
                    "id": str(uuid.uuid4()),
                    "status": "placed",
                    "total": 5.0,
                    "created_at": None,
                    "items": [],
                }
            ],
            "view_orders",
        ),
        (
            {
                "addresses": [
                    {
                        "id": str(uuid.uuid4()),
                        "label": "Home",
                        "line1": "St 1",
                        "city": "City",
                        "state": "State",
                        "postal_code": "12345",
                        "is_default": False,
                    }
                ]
            },
            "manage_addresses",
        ),
    ]
    for result, tool in cases:
        r = format_response(result, tool)
        if r["type"] == "options_response":
            assert "card_variant" in r, (
                f"card_variant missing from options_response for tool '{tool}'"
            )
