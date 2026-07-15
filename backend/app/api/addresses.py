import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_customer, get_db
from app.db.models.address import Address
from app.db.models.user import User

router = APIRouter(prefix="/addresses", tags=["Addresses"])


# Pydantic Schemas
class AddressResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    label: str
    line1: str
    line2: str | None
    city: str
    state: str
    postal_code: str
    country: str
    is_default: bool

    class Config:
        from_attributes = True


class AddressCreate(BaseModel):
    label: str
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    is_default: bool | None = None


@router.get("", response_model=list[AddressResponse])
async def list_addresses(
    user: User = Depends(get_current_customer), db: AsyncSession = Depends(get_db)
) -> list[Address]:
    """Retrieve all addresses for the authenticated user."""
    result = await db.execute(
        select(Address)
        .where(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(
    payload: AddressCreate,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> Address:
    """Create a new address for the authenticated user."""
    # Check if this is the first address
    count_res = await db.execute(select(Address).where(Address.user_id == user.id))
    is_first = len(count_res.scalars().all()) == 0

    is_default = payload.is_default or is_first

    if is_default:
        # Set all other user addresses to not default
        await db.execute(
            update(Address).where(Address.user_id == user.id).values(is_default=False)
        )

    address = Address(
        user_id=user.id,
        label=payload.label,
        line1=payload.line1,
        line2=payload.line2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country,
        is_default=is_default,
    )
    db.add(address)
    await db.commit()
    await db.refresh(address)
    return address


@router.put("/{address_id}", response_model=AddressResponse)
async def update_address(
    address_id: uuid.UUID,
    payload: AddressUpdate,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> Address:
    """Update an existing address."""
    result = await db.execute(
        select(Address).where(Address.id == address_id, Address.user_id == user.id)
    )
    address = result.scalar_one_or_none()
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    # Check if default status is changing to True
    if payload.is_default is True:
        # Set all other user addresses to not default
        await db.execute(
            update(Address).where(Address.user_id == user.id).values(is_default=False)
        )

    # Apply updates
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(address, field, value)

    await db.commit()
    await db.refresh(address)
    return address


@router.delete("/{address_id}")
async def delete_address(
    address_id: uuid.UUID,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Delete an address."""
    result = await db.execute(
        select(Address).where(Address.id == address_id, Address.user_id == user.id)
    )
    address = result.scalar_one_or_none()
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found.",
        )

    was_default = address.is_default
    await db.delete(address)
    await db.commit()

    # If we deleted the default address, promote another one to default
    if was_default:
        fallback_res = await db.execute(
            select(Address)
            .where(Address.user_id == user.id)
            .order_by(Address.created_at.desc())
            .limit(1)
        )
        fallback = fallback_res.scalar_one_or_none()
        if fallback:
            fallback.is_default = True
            await db.commit()

    return {"status": "success", "detail": "Address deleted successfully."}
