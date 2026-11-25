from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.commerce.checkout import DeliveryAddress, lock_customer
from app.core.dependencies import get_current_customer, get_db
from app.db.models.address import Address
from app.db.models.user import User

router = APIRouter(prefix="/addresses", tags=["Addresses"])


class AddressCreate(DeliveryAddress):
    is_default: bool = False


class AddressResponse(AddressCreate):
    id: UUID
    user_id: UUID


class AddressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    line1: Annotated[str, StringConstraints(min_length=1, max_length=255)] | None = None
    line2: Annotated[str, StringConstraints(max_length=255)] | None = None
    city: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    state: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    postal_code: (
        Annotated[str, StringConstraints(min_length=3, max_length=20)] | None
    ) = None
    country: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = (
        None
    )
    is_default: bool | None = None


async def owned_address(db: AsyncSession, user_id: UUID, address_id: UUID) -> Address:
    address = await db.scalar(
        select(Address).where(Address.id == address_id, Address.user_id == user_id)
    )
    if address is None:
        raise HTTPException(404, "Address not found.")
    return address


async def add_address(
    db: AsyncSession, user_id: UUID, payload: AddressCreate
) -> Address:
    await lock_customer(db, user_id)
    existing_id = await db.scalar(
        select(Address.id).where(Address.user_id == user_id).limit(1)
    )
    is_default = payload.is_default or existing_id is None
    if is_default:
        await db.execute(
            update(Address).where(Address.user_id == user_id).values(is_default=False)
        )
    address = Address(
        user_id=user_id,
        is_default=is_default,
        **payload.model_dump(exclude={"is_default"}),
    )
    db.add(address)
    await db.flush()
    return address


async def modify_address(
    db: AsyncSession, user_id: UUID, address_id: UUID, payload: AddressUpdate
) -> Address:
    await lock_customer(db, user_id)
    address = await owned_address(db, user_id, address_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None and key != "line2" for key, value in changes.items()):
        raise HTTPException(422, "Required address fields cannot be cleared.")
    if changes.get("is_default") is True and not address.is_default:
        await db.execute(
            update(Address).where(Address.user_id == user_id).values(is_default=False)
        )
    if address.is_default and changes.get("is_default") is False:
        raise HTTPException(409, "Choose a different default address instead.")
    normalized = DeliveryAddress.model_validate(
        DeliveryAddress.model_validate(address).model_dump()
        | {key: value for key, value in changes.items() if key != "is_default"}
    )
    for key, value in normalized.model_dump().items():
        setattr(address, key, value)
    if changes.get("is_default") is True:
        address.is_default = True
    await db.flush()
    return address


async def remove_address(db: AsyncSession, user_id: UUID, address_id: UUID) -> None:
    await lock_customer(db, user_id)
    address = await owned_address(db, user_id, address_id)
    was_default = address.is_default
    await db.delete(address)
    await db.flush()
    if was_default:
        replacement = await db.scalar(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.created_at, Address.id)
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True
            await db.flush()


@router.get("", response_model=list[AddressResponse])
async def list_addresses(
    user: User = Depends(get_current_customer), db: AsyncSession = Depends(get_db)
) -> list[Address]:
    return list(
        await db.scalars(
            select(Address)
            .where(Address.user_id == user.id)
            .order_by(Address.is_default.desc(), Address.created_at)
        )
    )


@router.post("", response_model=AddressResponse, status_code=201)
async def create_address(
    payload: AddressCreate,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> Address:
    address = await add_address(db, user.id, payload)
    await db.commit()
    return address


@router.put("/{address_id}", response_model=AddressResponse)
async def update_address(
    address_id: UUID,
    payload: AddressUpdate,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> Address:
    address = await modify_address(db, user.id, address_id, payload)
    await db.commit()
    return address


@router.delete("/{address_id}")
async def delete_address(
    address_id: UUID,
    user: User = Depends(get_current_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await remove_address(db, user.id, address_id)
    await db.commit()
    return {"status": "success"}
