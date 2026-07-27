"""
ResponseFormatter — pure-Python tool-result → response dict converter.

No LLM calls anywhere in this module. Every tool has a known return shape;
if something unrecognised arrives, we log a warning and return a safe "Done."
message rather than calling an LLM to guess.

Discriminator check order (CRITICAL — do not reorder):
  1.  success/failure dict  (message + success)
  2.  empty dict            (empty flag)
  3.  order_detail          ← MUST be before cart (both have 'items' + 'total')
  4.  compare               (compare_products)
  5.  already_rated / submit_rating success
  6.  bulk_deactivate        (seller_bulk_deactivate)
  7.  bulk_status_update     (update_order_status bulk)
  8.  facts_list             (manage_facts list)
  9.  cart                  (items + total)
  10. fulfillment_queue      (list with fulfillment_queue flag)
  11. orders list            (list with status + total)
  12. addresses              (addresses key)
  13. seller catalog         (is_active + sold_count)
  14. inventory              (stock_status key)
  15. search results         (avg_rating + category, no is_active)
  16. unknown               → generic "Done." + warning log
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("app.services.agent.response_formatter")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def format_response(result: Any, tool_name: str = "") -> dict[str, Any]:  # noqa: PLR0912, PLR0911
    """Convert a tool result into a frontend-ready response dict.

    Args:
        result:    The raw return value from a tool.
        tool_name: The tool that produced *result* (used for logging only).

    Returns:
        A dict with at minimum ``{"type": ..., "text": ...}``.
        type is one of: "response" | "options_response"
    """

    # ── 1. Success / failure dict ─────────────────────────────────────────
    if isinstance(result, dict) and "success" in result and "message" in result:
        return {"type": "response", "text": result["message"], "options": None}

    # ── 2. Empty result ───────────────────────────────────────────────────
    if isinstance(result, dict) and result.get("empty"):
        return {
            "type": "response",
            "text": result.get("message", "No results found."),
            "options": None,
        }

    # ── 3. Order detail  (MUST be before cart — both have 'items'+'total') ─
    if isinstance(result, dict) and result.get("order_detail"):
        return _format_order_detail(result)

    # ── 4. Product comparison ──────────────────────────────────────────────
    if isinstance(result, dict) and result.get("compare"):
        return _format_compare(result)

    # ── 5. Rating / review ────────────────────────────────────────────────
    if isinstance(result, dict) and result.get("already_rated"):
        return {
            "type": "response",
            "text": result.get("message", "You already reviewed this item."),
            "options": None,
        }

    # ── 6. Bulk deactivate ────────────────────────────────────────────────
    if isinstance(result, dict) and result.get("bulk_deactivate"):
        return _format_bulk_deactivate(result)

    # ── 7. Bulk status update ─────────────────────────────────────────────
    if isinstance(result, dict) and result.get("bulk_status_update"):
        return _format_bulk_status_update(result)

    # ── 8. Facts list ─────────────────────────────────────────────────────
    if isinstance(result, dict) and result.get("facts_list"):
        return _format_facts_list(result)

    # ── 9. Cart ───────────────────────────────────────────────────────────
    if isinstance(result, dict) and "items" in result and "total" in result:
        return _format_cart(result)

    # ── 10. Fulfillment queue (list with fulfillment_queue discriminator) ──
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and result[0].get("fulfillment_queue")
    ):
        return _format_fulfillment_queue(result)

    # ── 11. Orders list ────────────────────────────────────────────────────
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and "status" in result[0]
        and "total" in result[0]
        and not result[0].get("fulfillment_queue")
    ):
        return _format_orders_list(result)

    # ── 12. Addresses ──────────────────────────────────────────────────────
    if isinstance(result, dict) and "addresses" in result:
        return _format_addresses(result)

    # ── 13. Seller catalog (is_active + sold_count) ────────────────────────
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and "is_active" in result[0]
        and "sold_count" in result[0]
        and "stock_status" not in result[0]
    ):
        return _format_seller_catalog(result)

    # ── 14. Inventory (stock_status key) ──────────────────────────────────
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and "stock_status" in result[0]
    ):
        return _format_inventory(result)

    # ── 15. Search results (avg_rating + category, no is_active) ──────────
    if isinstance(result, list):
        if not result:
            return {
                "type": "response",
                "text": "No products found matching your search. Try different keywords or broaden your filters.",
                "options": None,
            }
        if isinstance(result[0], dict) and "avg_rating" in result[0]:
            return _format_search_results(result)

    # ── 16. Unknown shape ─────────────────────────────────────────────────
    logger.warning(
        f"[ResponseFormatter] Unrecognised result shape from tool '{tool_name}': "
        f"type={type(result).__name__}, keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}"
    )
    return {"type": "response", "text": "Done.", "options": None}


# ---------------------------------------------------------------------------
# Private formatters
# ---------------------------------------------------------------------------


def _format_order_detail(result: dict[str, Any]) -> dict[str, Any]:
    oid_short = str(result.get("id", ""))[:8]
    status = result.get("status", "").upper()
    total = result.get("total", 0.0)
    items_list: list[dict[str, Any]] = result.get("items", [])
    addr: dict[str, Any] = result.get("delivery_address") or {}

    status_steps = ["placed", "packed", "out_for_delivery", "delivered"]
    status_labels = {
        "placed": "Placed",
        "packed": "Packed",
        "out_for_delivery": "Out for Delivery",
        "delivered": "Delivered",
    }
    ts_keys = {
        "placed": "created_at",
        "packed": "packed_at",
        "out_for_delivery": "out_for_delivery_at",
        "delivered": "delivered_at",
    }
    current_status = result.get("status", "placed")

    timeline = []
    for step in status_steps:
        ts = (result.get(ts_keys[step]) or "")[:10]
        if step == current_status:
            marker = "● "
        elif status_steps.index(step) < status_steps.index(current_status):
            marker = "✓ "
        else:
            marker = "○ "
        label = status_labels[step]
        timeline.append(f"{marker}{label}" + (f" ({ts})" if ts else ""))

    item_lines = []
    for it in items_list:
        name = it.get("product_name", "?")
        qty = it.get("quantity", 1)
        price = it.get("price_at_purchase", 0.0)
        sub = it.get("subtotal", float(price) * qty)
        item_lines.append(
            f"  • {name} × {qty}  @${float(price):.2f}  = ${float(sub):.2f}"
        )

    addr_parts = [
        addr.get("line1", ""),
        addr.get("line2", ""),
        addr.get("city", ""),
        addr.get("state", ""),
        addr.get("postal_code", ""),
    ]
    addr_line = ", ".join(p for p in addr_parts if p)

    text_parts = [
        f"**Order #{oid_short}…** — {status} — **${float(total):.2f}**\n",
        "**Status:** " + " → ".join(timeline),
        "",
        "**Items:**",
        *item_lines,
    ]
    if addr_line:
        text_parts += ["", f"**Delivery to:** {addr.get('label', '')}: {addr_line}"]

    return {
        "type": "options_response",
        "text": "\n".join(text_parts),
        "options": None,
        "free_input_allowed": True,
        "card_variant": "order_detail",
    }


def _format_compare(result: dict[str, Any]) -> dict[str, Any]:
    products: list[dict[str, Any]] = result.get("products", [])
    if not products:
        return {"type": "response", "text": "No products to compare.", "options": None}

    # Header row
    names = [p.get("name", "?") for p in products]
    header = "**Product Comparison**\n"

    rows = []
    fields: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Price", lambda p: f"${p.get('price', 0.0):.2f}"),
        ("Category", lambda p: str(p.get("category", ""))),
        ("Rating", lambda p: f"⭐ {float(p.get('avg_rating', 0.0)):.1f}"),
        ("Stock", lambda p: str(p.get("stock", 0))),
        ("Sold", lambda p: str(p.get("sold_count", 0))),
    ]
    for label, fn in fields:
        row_vals = " | ".join(fn(p) for p in products)
        rows.append(f"**{label}:** {row_vals}")

    text = header + " vs ".join(names) + "\n\n" + "\n".join(rows)

    # Options: allow user to add either product to cart
    options = []
    for p in products:
        pid = p.get("id", "")
        stock = p.get("stock", 0)
        actions = []
        if stock > 0 and pid:
            actions.append({"label": "Add to Cart", "value": f"add_{pid}"})
        if pid:
            actions.append({"label": "View Details", "value": f"view_{pid}"})
        options.append(
            {
                "label": p.get("name", "?"),
                "value": pid,
                "description": f"${p.get('price', 0.0):.2f} · ⭐{float(p.get('avg_rating', 0.0)):.1f} · Stock: {stock}",
                "actions": actions,
            }
        )

    return {
        "type": "options_response",
        "text": text,
        "options": options,
        "free_input_allowed": True,
        "card_variant": "compare",
    }


def _format_bulk_deactivate(result: dict[str, Any]) -> dict[str, Any]:
    succeeded: list[dict[str, str]] = result.get("succeeded", [])
    failed: list[dict[str, str]] = result.get("failed", [])

    lines = [
        f"**Bulk Deactivate** — {len(succeeded)} succeeded, {len(failed)} failed\n"
    ]
    for s in succeeded:
        lines.append(f"  ✅ {s.get('name', s.get('id', '?')[:8] + '…')}")
    for f in failed:
        lines.append(
            f"  ❌ #{f.get('id', '?')[:8]}… — {f.get('reason', 'unknown error')}"
        )

    return {"type": "response", "text": "\n".join(lines), "options": None}


def _format_bulk_status_update(result: dict[str, Any]) -> dict[str, Any]:
    succeeded: list[dict[str, str]] = result.get("succeeded", [])
    failed: list[dict[str, str]] = result.get("failed", [])

    lines = [
        f"**Order Status Update** — {len(succeeded)} updated, {len(failed)} failed\n"
    ]
    for s in succeeded:
        lines.append(f"  ✅ #{s.get('id', '?')[:8]}…")
    for f in failed:
        lines.append(
            f"  ❌ #{f.get('id', '?')[:8]}… — {f.get('reason', 'unknown error')}"
        )

    return {"type": "response", "text": "\n".join(lines), "options": None}


def _format_facts_list(result: dict[str, Any]) -> dict[str, Any]:
    facts: list[dict[str, Any]] = result.get("facts", [])
    if not facts:
        return {
            "type": "response",
            "text": result.get("message", "You have no saved preferences yet."),
            "options": None,
        }

    lines = [f"**🧠 Your Preferences & Facts** ({len(facts)})\n"]
    options = []
    for f in facts:
        idx = f.get("index", "?")
        cat = f.get("category", "other")
        text = f.get("fact_text", "")
        fid = f.get("id", "")
        lines.append(f"  {idx}. [{cat}] {text}")
        options.append(
            {
                "label": f"{idx}. {text}",
                "value": fid,
                "description": f"Category: {cat}",
                "actions": [{"label": "Delete", "value": f"delete_fact_{fid}"}],
            }
        )

    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": options,
        "free_input_allowed": True,
        "card_variant": "facts",
    }


def _format_cart(result: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = result.get("items", [])
    total: float = result.get("total", 0.0)

    # NOTE: the dead `if not items` branch is intentionally removed here.
    # get_cart never returns {"items": [], "total": 0} for an empty cart —
    # it returns {"empty": True, "message": "..."} which is caught by check 2.

    lines = [f"**🛒 Your Cart** (Total: **${float(total):.2f}**)\n"]
    cart_options: list[dict[str, Any]] = []
    for item in items:
        pid = item.get("product_id", "")
        name = item.get("name", "")
        qty = item.get("quantity", 1)
        price = item.get("price", 0.0)
        subtotal = item.get("total", float(price) * qty)
        lines.append(f"• {name} × {qty} = ${float(subtotal):.2f}")
        if pid:
            cart_options.append(
                {
                    "label": f"{name} ×{qty}",
                    "value": pid,
                    "description": f"${float(price):.2f} each · Subtotal ${float(subtotal):.2f}",
                    "actions": [{"label": "Remove", "value": f"remove_{pid}"}],
                }
            )

    cart_options.append(
        {
            "label": "✅ Checkout",
            "value": "checkout",
            "description": f"Place order · ${float(total):.2f} total",
        }
    )
    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": cart_options,
        "free_input_allowed": True,
        "card_variant": "cart",
    }


def _format_fulfillment_queue(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    status_counts: dict[str, int] = {}
    for row in results:
        s = row.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    summary_parts = [f"{v} {k.replace('_', ' ')}" for k, v in status_counts.items()]

    lines = [
        f"**📋 Fulfillment Queue** — {count} order{'s' if count != 1 else ''}"
        + (f" ({', '.join(summary_parts)})" if summary_parts else "")
        + "\n"
    ]
    fq_options: list[dict[str, Any]] = []
    for row in results:
        oid_short = row.get("order_id_short", "")
        status_label = row.get("status_label", row.get("status", "").upper())
        total = row.get("total", 0.0)
        created = (row.get("created_at") or "")[:10]
        item_count = row.get("my_items_count", 0)
        my_items: list[dict[str, Any]] = row.get("my_items", [])
        item_names = ", ".join(
            f"{it.get('product_name', '?')} ×{it.get('quantity', 1)}"
            for it in my_items[:2]
        )
        if len(my_items) > 2:
            item_names += f" +{len(my_items) - 2} more"
        lines.append(
            f"• #{oid_short}… · {status_label} · ${float(total):.2f} · {created}"
            + (
                f" · {item_count} item{'s' if item_count != 1 else ''}"
                if item_count
                else ""
            )
        )
        actions = []
        if row.get("advance_value") and row.get("next_action_label"):
            actions.append(
                {
                    "label": row["next_action_label"],
                    "value": row["advance_value"],
                }
            )
        fq_options.append(
            {
                "label": f"#{oid_short}… — {status_label}",
                "value": row.get("order_id", ""),
                "description": item_names or f"${float(total):.2f}",
                "actions": actions,
                "card_variant": "fulfillment_queue",
            }
        )

    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": fq_options,
        "free_input_allowed": True,
        "card_variant": "fulfillment_queue",
    }


def _format_orders_list(results: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        f"**📦 Your Orders** ({len(results)} order{'s' if len(results) != 1 else ''})\n"
    ]
    options = []
    for order in results:
        oid = str(order.get("id", ""))[:8]
        status = order.get("status", "").upper()
        total = order.get("total", 0.0)
        created = (order.get("created_at") or "")[:10]
        items_list: list[dict[str, Any]] = order.get("items", [])
        item_names = ", ".join(
            f"{i.get('product_name', '?')} ×{i.get('quantity', 1)}"
            for i in items_list[:3]
        )
        if len(items_list) > 3:
            item_names += f" +{len(items_list) - 3} more"
        lines.append(f"• #{oid}… · {status} · ${float(total):.2f} · {created}")
        options.append(
            {
                "label": f"#{oid}… — {status}",
                "value": order.get("id", ""),
                "description": item_names or "No items",
                "actions": [
                    {
                        "label": "View Details",
                        "value": f"order_detail_{order.get('id', '')}",
                    }
                ],
            }
        )
    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": options,
        "free_input_allowed": True,
        "card_variant": "orders",
    }


def _format_addresses(result: dict[str, Any]) -> dict[str, Any]:
    addresses: list[dict[str, Any]] = result.get("addresses", [])
    if not addresses:
        return {
            "type": "response",
            "text": 'You have no saved addresses. You can add one by saying "add address".',
            "options": None,
        }
    lines = [f"**📍 Your Addresses** ({len(addresses)})\n"]
    options = []
    for addr in addresses:
        aid = addr.get("id", "")
        label = addr.get("label") or "Home"
        line1 = addr.get("line1", "")
        city = addr.get("city", "")
        state = addr.get("state", "")
        postal = addr.get("postal_code", "")
        default_tag = " 🏠 Default" if addr.get("is_default") else ""
        lines.append(f"• {label}: {line1}, {city}, {state} {postal}{default_tag}")
        options.append(
            {
                "label": label,
                "value": aid,
                "description": f"{line1}, {city}, {state} {postal}{default_tag}",
                "actions": [
                    {"label": "Set Default", "value": f"set_default_address_{aid}"},
                    {"label": "Edit", "value": f"update_address_{aid}"},
                    {"label": "Delete", "value": f"delete_address_{aid}"},
                ],
            }
        )
    options.append(
        {
            "label": "➕ Add New Address",
            "value": "add_address",
            "description": "Save a delivery address",
        }
    )
    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": options,
        "free_input_allowed": True,
        "card_variant": "addresses",
    }


def _format_seller_catalog(results: list[dict[str, Any]]) -> dict[str, Any]:
    active = [p for p in results if p.get("is_active")]
    inactive = [p for p in results if not p.get("is_active")]
    lines = [f"**🏪 Your Products** ({len(active)} active, {len(inactive)} inactive)\n"]
    options = []
    for p in results:
        pid = p.get("id", "")
        name = p.get("name", "")
        price = p.get("price", 0.0)
        stock = p.get("stock", 0)
        sold = p.get("sold_count", 0)
        active_tag = "✅" if p.get("is_active") else "❌"
        lines.append(
            f"• {active_tag} {name} — ${float(price):.2f} · Stock: {stock} · Sold: {sold}"
        )
        options.append(
            {
                "label": f"{active_tag} {name}",
                "value": pid,
                "description": f"${float(price):.2f} · Stock {stock} · {sold} sold",
                "actions": [
                    {"label": "Edit", "value": f"seller_edit_{pid}"},
                    {"label": "Deactivate", "value": f"seller_deactivate_{pid}"},
                ],
            }
        )
    options.append(
        {
            "label": "➕ Create Product",
            "value": "seller_create",
            "description": "List a new product",
        }
    )
    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": options,
        "free_input_allowed": True,
        "card_variant": "seller_catalog",
    }


def _format_inventory(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = next((r for r in results if r.get("_summary")), None)
    products = [r for r in results if not r.get("_summary")]

    header_parts = [
        f"**📦 Inventory** — {len(products)} product{'s' if len(products) != 1 else ''}"
    ]
    if summary:
        header_parts.append(
            f"(🟢 {summary.get('in_stock_count', 0)} in stock · "
            f"🟡 {summary.get('low_stock_count', 0)} low · "
            f"🔴 {summary.get('out_of_stock_count', 0)} out of stock)"
        )
    lines = [" ".join(header_parts) + "\n"]
    inv_options: list[dict[str, Any]] = []
    stock_badge = {"in_stock": "🟢", "low_stock": "🟡", "out_of_stock": "🔴"}

    for p in products:
        pid = p.get("id", "")
        name = p.get("name", "")
        price = p.get("price", 0.0)
        stock = p.get("stock", 0)
        rating = p.get("avg_rating", 0.0)
        sold = p.get("sold_count", 0)
        ss = p.get("stock_status", "in_stock")
        badge = stock_badge.get(ss, "")
        lines.append(
            f"• {badge} {name} — ${float(price):.2f} · Stock: {stock} · ⭐{float(rating):.1f} · Sold: {sold}"
        )
        inv_options.append(
            {
                "label": f"{badge} {name}",
                "value": pid,
                "description": f"${float(price):.2f} · Stock {stock} · ⭐{float(rating):.1f} · {sold} sold",
                "actions": [
                    {"label": "Edit", "value": f"seller_edit_{pid}"},
                    {"label": "Deactivate", "value": f"seller_deactivate_{pid}"},
                ],
                "card_variant": "inventory",
            }
        )

    return {
        "type": "options_response",
        "text": "\n".join(lines),
        "options": inv_options,
        "free_input_allowed": True,
        "card_variant": "inventory",
    }


def _format_search_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    result_summary = f"Found {count} product{'s' if count != 1 else ''}:"
    search_options: list[dict[str, Any]] = []
    for p in results:
        pid = p.get("id", "")
        name = p.get("name", "")
        price = p.get("price", 0.0)
        stock = p.get("stock", 0)
        rating = p.get("avg_rating", 0.0)
        category = p.get("category", "")
        in_stock = stock > 0
        stock_label = f"Stock: {stock}" if in_stock else "Out of stock"
        desc = (
            f"${float(price):.2f} · {category} · ⭐ {float(rating):.1f} · {stock_label}"
        )
        actions = []
        if in_stock and pid:
            actions.append({"label": "Add to Cart", "value": f"add_{pid}"})
        if pid:
            actions.append({"label": "View Details", "value": f"view_{pid}"})
        search_options.append(
            {"label": name, "value": pid, "description": desc, "actions": actions}
        )
    return {
        "type": "options_response",
        "text": result_summary,
        "options": search_options,
        "free_input_allowed": True,
        "card_variant": "search",
    }
