"""Address tools - pure Python CRUD, no LLM calls."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.address import Address


async def manage_addresses(
    db: AsyncSession,
    user_id: UUID,
    action: str = "list",
    address_data: dict[str, Any] | None = None,
    address_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Manage addresses. Actions: list, add, update, delete."""
    if action == "list":
        result = await db.execute(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.is_default.desc())
        )
        addresses = list(result.scalars().all())
        return {
            "addresses": [
                {
                    "id": str(a.id),
                    "label": a.label or "",
                    "street": a.street,
                    "city": a.city,
                    "state": a.state,
                    "zip_code": a.zip_code,
                    "is_default": a.is_default,
                }
                for a in addresses
            ]
        }

    if action == "add" and address_data:
        is_default = address_data.get("is_default", False)
        if is_default:
            # Reset other defaults
            await _reset_defaults(db, user_id)

        address = Address(
            user_id=user_id,
            label=address_data.get("label", ""),
            street=address_data["street"],
            city=address_data["city"],
            state=address_data.get("state", ""),
            zip_code=address_data.get("zip_code", ""),
            is_default=is_default,
        )
        db.add(address)
        await db.commit()
        return {"success": True, "message": "Address added successfully."}

    if action == "update" and address_id and address_data:
        addr_uuid = UUID(address_id)
        result = await db.execute(
            select(Address).where(Address.id == addr_uuid, Address.user_id == user_id)
        )
        address = result.scalar_one_or_none()
        if not address:
            return {"success": False, "message": "Address not found."}

        if address_data.get("is_default"):
            await _reset_defaults(db, user_id)

        if "street" in address_data:
            address.street = address_data["street"]
        if "city" in address_data:
            address.city = address_data["city"]
        if "state" in address_data:
            address.state = address_data["state"]
        if "zip_code" in address_data:
            address.zip_code = address_data["zip_code"]
        if "label" in address_data:
            address.label = address_data["label"]
        if "is_default" in address_data:
            address.is_default = address_data["is_default"]

        await db.commit()
        return {"success": True, "message": "Address updated."}

    if action == "delete" and address_id:
        addr_uuid = UUID(address_id)
        await db.execute(
            select(Address).where(Address.id == addr_uuid, Address.user_id == user_id)
        )
        from sqlalchemy import delete

        await db.execute(
            delete(Address).where(Address.id == addr_uuid, Address.user_id == user_id)
        )
        await db.commit()
        return {"success": True, "message": "Address deleted."}

    return {"success": False, "message": f"Invalid action: {action}"}


async def _reset_defaults(db: AsyncSession, user_id: UUID) -> None:
    """Reset all addresses to non-default."""
    from sqlalchemy import update

    await db.execute(
        update(Address).where(Address.user_id == user_id).values(is_default=False)
    )
