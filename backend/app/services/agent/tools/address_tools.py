"""Address tools - pure Python CRUD, no LLM calls."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.address import Address


def _normalize_address_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize incoming dict keys to match Address DB model column names."""
    norm = dict(raw_data)
    # Normalize street / line_1 / house_number -> line1
    if "line1" not in norm:
        for alias in ("street", "line_1", "house_number", "street_address", "address"):
            if alias in norm and norm[alias]:
                norm["line1"] = norm[alias]
                break

    # Normalize postal_code / zip_code / pin_code / zip -> postal_code
    if "postal_code" not in norm:
        for alias in ("zip_code", "pin_code", "zip", "pincode", "postal"):
            if alias in norm and norm[alias]:
                norm["postal_code"] = str(norm[alias])
                break

    # Default country to India if missing
    if "country" not in norm or not norm["country"]:
        norm["country"] = "India"

    # Default label to Home if missing
    if "label" not in norm or not norm["label"]:
        norm["label"] = "Home"

    return norm


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
                    "label": a.label or "Home",
                    "line1": a.line1,
                    "line2": a.line2 or "",
                    "city": a.city,
                    "state": a.state,
                    "postal_code": a.postal_code,
                    "country": a.country,
                    "is_default": a.is_default,
                }
                for a in addresses
            ]
        }

    if action == "add" and address_data:
        norm = _normalize_address_data(address_data)
        line1 = norm.get("line1")
        city = norm.get("city")
        if not line1 or not city:
            return {
                "success": False,
                "message": "Missing required address fields (street/line1 and city are required).",
            }

        is_default = norm.get("is_default", False)
        if is_default:
            await _reset_defaults(db, user_id)

        address = Address(
            user_id=user_id,
            label=norm.get("label", "Home"),
            line1=line1,
            line2=norm.get("line2", ""),
            city=city,
            state=norm.get("state", ""),
            postal_code=norm.get("postal_code", ""),
            country=norm.get("country", "India"),
            is_default=is_default,
        )
        db.add(address)
        await db.commit()
        return {
            "success": True,
            "message": f"Address '{address.label}' added successfully.",
        }

    if action == "update" and address_id and address_data:
        addr_uuid = UUID(address_id)
        result = await db.execute(
            select(Address).where(Address.id == addr_uuid, Address.user_id == user_id)
        )
        address = result.scalar_one_or_none()
        if not address:
            return {"success": False, "message": "Address not found."}

        norm = _normalize_address_data(address_data)
        if norm.get("is_default"):
            await _reset_defaults(db, user_id)

        if "line1" in norm:
            address.line1 = norm["line1"]
        if "line2" in norm:
            address.line2 = norm["line2"]
        if "city" in norm:
            address.city = norm["city"]
        if "state" in norm:
            address.state = norm["state"]
        if "postal_code" in norm:
            address.postal_code = norm["postal_code"]
        if "country" in norm:
            address.country = norm["country"]
        if "label" in norm:
            address.label = norm["label"]
        if "is_default" in norm:
            address.is_default = norm["is_default"]

        await db.commit()
        return {"success": True, "message": "Address updated successfully."}

    if action == "delete" and address_id:
        addr_uuid = UUID(address_id)
        from sqlalchemy import delete

        await db.execute(
            delete(Address).where(Address.id == addr_uuid, Address.user_id == user_id)
        )
        await db.commit()
        return {"success": True, "message": "Address deleted."}

    return {
        "success": False,
        "message": f"Invalid action or missing address data: {action}",
    }


async def _reset_defaults(db: AsyncSession, user_id: UUID) -> None:
    """Reset all addresses to non-default."""
    from sqlalchemy import update

    await db.execute(
        update(Address).where(Address.user_id == user_id).values(is_default=False)
    )
