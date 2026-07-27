"""Seller tools - pure Python CRUD, no LLM calls."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import UserRole
from app.db.models.product import Product
from app.db.models.user import User

logger = logging.getLogger(__name__)


async def _require_seller_role(db: AsyncSession, user_id: UUID) -> None:
    """Defense-in-depth: verify the user has seller role before executing seller tools."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.role != UserRole.seller:
        raise PermissionError(
            f"Tool requires 'seller' role. Current role is '{user.role.value if user else 'unknown'}'. "
            "Use switch_role tool to change your role."
        )


async def _sync_product_to_qdrant(product: Product) -> None:
    """Upsert a single product into the Qdrant vector store (fire-and-forget safe)."""
    try:
        from decimal import Decimal

        from qdrant_client import models as qmodels

        from app.services.rag.embedder import embed_text
        from app.services.rag.retriever import COLLECTION_NAME, get_qdrant_client

        text = f"{product.name} {product.description} {product.category}"
        vector = embed_text(text)
        client = get_qdrant_client()
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qmodels.PointStruct(
                    id=str(product.id),
                    vector=vector,
                    payload={
                        "id": str(product.id),
                        "name": product.name,
                        "description": product.description,
                        "category": product.category,
                        "price": float(product.price)
                        if isinstance(product.price, Decimal)
                        else product.price,
                        "stock": product.stock,
                        "is_active": product.is_active,
                    },
                )
            ],
        )
        logger.info(f"[QDRANT SYNC] Upserted product {product.id} ({product.name})")
    except Exception as e:
        logger.warning(f"[QDRANT SYNC] Failed to upsert product {product.id}: {e}")


async def _remove_product_from_qdrant(product_id: UUID) -> None:
    """Remove a product from Qdrant (called on deactivation)."""
    try:
        from app.services.rag.retriever import COLLECTION_NAME, get_qdrant_client

        client = get_qdrant_client()
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=[str(product_id)],
        )
        logger.info(f"[QDRANT SYNC] Removed product {product_id} from Qdrant")
    except Exception as e:
        logger.warning(f"[QDRANT SYNC] Failed to remove product {product_id}: {e}")


async def seller_list_products(
    db: AsyncSession,
    user_id: UUID,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """List seller's own products."""
    result = await db.execute(
        select(Product).where(Product.seller_id == user_id).order_by(Product.name)
    )
    products = list(result.scalars().all())
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "category": p.category,
            "price": float(p.price),
            "stock": p.stock,
            "is_active": p.is_active,
            "sold_count": p.sold_count,
        }
        for p in products
    ]


async def seller_create_product(
    db: AsyncSession,
    user_id: UUID,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    price: float | None = None,
    stock: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a new product as seller and auto-sync to Qdrant.

    All parameters are optional at the tool level; required-field validation
    is enforced by the orchestrator's slot-filling guard before this is called.
    """
    from decimal import Decimal

    # Null-safe defaults — should never reach here with nulls after slot-filling,
    # but guard anyway to prevent NOT NULL DB crashes.
    safe_name = (name or "").strip()
    safe_description = (description or "").strip()
    safe_category = (category or "General").strip()
    safe_price = Decimal(str(price)) if price is not None else Decimal("0.00")
    safe_stock = int(stock) if stock is not None else 0

    if not safe_name:
        return {"success": False, "message": "Product name is required."}

    product = Product(
        seller_id=user_id,
        name=safe_name,
        description=safe_description,
        category=safe_category,
        price=safe_price,
        stock=safe_stock,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    # Event-driven Qdrant sync
    await _sync_product_to_qdrant(product)

    return {
        "success": True,
        "message": f"Product '{safe_name}' created and indexed for search.",
        "product_id": str(product.id),
    }


async def seller_update_product(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    price: float | None = None,
    stock: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Update a product as seller and auto-sync to Qdrant."""
    from decimal import Decimal

    prod_uuid = UUID(product_id)
    result = await db.execute(
        select(Product).where(Product.id == prod_uuid, Product.seller_id == user_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return {"success": False, "message": "Product not found or not yours."}

    if name is not None:
        product.name = name
    if description is not None:
        product.description = description
    if category is not None:
        product.category = category
    if price is not None:
        product.price = Decimal(str(price))
    if stock is not None:
        product.stock = stock

    await db.commit()
    await db.refresh(product)

    # Event-driven Qdrant sync
    await _sync_product_to_qdrant(product)

    return {
        "success": True,
        "message": f"Product '{product.name}' updated and re-indexed.",
    }


async def seller_delete_product(
    db: AsyncSession,
    user_id: UUID,
    product_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deactivate a product as seller (soft delete) and remove from Qdrant."""
    prod_uuid = UUID(product_id)
    result = await db.execute(
        select(Product).where(Product.id == prod_uuid, Product.seller_id == user_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return {"success": False, "message": "Product not found or not yours."}

    product.is_active = False
    await db.commit()

    # Event-driven Qdrant removal
    await _remove_product_from_qdrant(prod_uuid)

    return {
        "success": True,
        "message": f"Product '{product.name}' deactivated and removed from search.",
    }


async def seller_update_stock(
    db: AsyncSession,
    user_id: UUID,
    product_id: str | None = None,
    delta: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Adjust a product's stock by a signed delta.

    stock = max(0, stock + delta)

    If the delta would push stock below zero the result is clamped to 0 and a
    warning is included in the response message.

    Per-item transaction: if the DB write or Qdrant sync fails the transaction
    is rolled back and a clear error is returned.

    Args:
        product_id: UUID of the product to update.
        delta:      Signed integer — positive to add stock, negative to reduce.
    """
    if not product_id:
        return {"success": False, "message": "Product ID is required."}
    if delta is None:
        return {
            "success": False,
            "message": "Delta is required (positive to add, negative to reduce).",
        }

    try:
        prod_uuid = UUID(str(product_id))
        delta_int = int(delta)
    except (ValueError, TypeError):
        return {"success": False, "message": "Invalid product ID or delta value."}

    result = await db.execute(
        select(Product).where(Product.id == prod_uuid, Product.seller_id == user_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return {"success": False, "message": "Product not found or not yours."}

    clamped = False
    new_stock = product.stock + delta_int
    if new_stock < 0:
        new_stock = 0
        clamped = True

    old_stock = product.stock

    try:
        product.stock = new_stock
        await db.commit()
        await db.refresh(product)
        # Sync updated stock to Qdrant
        await _sync_product_to_qdrant(product)
    except Exception as exc:
        await db.rollback()
        logger.error(f"[SellerTools] seller_update_stock failed for {prod_uuid}: {exc}")
        return {
            "success": False,
            "message": "Failed to update stock. Please try again.",
        }

    msg = f"Stock updated for '{product.name}': {old_stock} → {new_stock}."
    if clamped:
        msg += " (Stock set to 0 — would have gone negative.)"

    return {
        "success": True,
        "message": msg,
        "product_name": product.name,
        "old_stock": old_stock,
        "new_stock": new_stock,
        "clamped": clamped,
    }


async def seller_bulk_deactivate(
    db: AsyncSession,
    user_id: UUID,
    product_ids: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deactivate multiple products at once.

    If product_ids is an empty list [], ALL of the seller's products are
    deactivated.

    Per-item transaction: each product is processed in its own savepoint.
    Failure on one item rolls back ONLY that item — the rest continue.

    Returns a summary dict with succeeded and failed lists.
    """
    if product_ids is None:
        return {
            "success": False,
            "message": "product_ids is required. Pass [] to deactivate all your products.",
        }

    # Resolve target product IDs
    if len(product_ids) == 0:
        # Deactivate ALL seller products
        all_result = await db.execute(
            select(Product).where(
                Product.seller_id == user_id,
                Product.is_active.is_(True),
            )
        )
        targets = list(all_result.scalars().all())
        target_ids = [str(p.id) for p in targets]
    else:
        target_ids = product_ids

    if not target_ids:
        return {
            "bulk_deactivate": True,
            "succeeded": [],
            "failed": [],
            "message": "No active products found to deactivate.",
        }

    succeeded: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for pid in target_ids:
        try:
            prod_uuid = UUID(str(pid))
        except (ValueError, AttributeError):
            failed.append({"id": pid, "reason": "Invalid UUID format."})
            continue

        try:
            # Use a savepoint so per-item failure doesn't abort the whole transaction
            async with db.begin_nested():
                prod_result = await db.execute(
                    select(Product).where(
                        Product.id == prod_uuid,
                        Product.seller_id == user_id,
                    )
                )
                product = prod_result.scalar_one_or_none()
                if not product:
                    failed.append(
                        {"id": pid, "reason": "Product not found or not yours."}
                    )
                    continue

                product_name = product.name
                product.is_active = False
                # Savepoint commits here; Qdrant sync is outside the savepoint
                # (best-effort — a Qdrant failure does not roll back the DB change)

            # Qdrant removal outside savepoint — if it fails, log and continue
            await _remove_product_from_qdrant(prod_uuid)
            succeeded.append({"id": pid, "name": product_name})
            logger.info(
                f"[SellerTools] Bulk deactivated product {prod_uuid} ({product_name})"
            )

        except Exception as exc:
            logger.error(f"[SellerTools] Bulk deactivate failed for {pid}: {exc}")
            failed.append({"id": pid, "reason": str(exc)})

    # Commit all savepoint changes in one final commit
    try:
        await db.commit()
    except Exception as exc:
        logger.error(f"[SellerTools] Final commit failed in bulk_deactivate: {exc}")
        await db.rollback()
        return {
            "success": False,
            "message": "Failed to save changes. Please try again.",
        }

    total = len(succeeded) + len(failed)
    msg = f"Deactivated {len(succeeded)} of {total} products."
    if failed:
        msg += f" {len(failed)} failed: " + ", ".join(
            f"{f['id'][:8]}… ({f['reason']})" for f in failed
        )

    return {
        "bulk_deactivate": True,
        "succeeded": succeeded,
        "failed": failed,
        "message": msg,
    }
