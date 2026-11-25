from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.addresses import AddressCreate, AddressUpdate
from app.api.ratings import RatingCreate, ReviewReply
from app.api.reports import Period
from app.catalog.products import ProductCreate, ProductUpdate, SearchFilters
from app.db.models.enums import OrderStatus


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Search(Input):
    tool: Literal["search"]
    filters: SearchFilters


class Cart(Input):
    tool: Literal["cart"]
    product_id: UUID
    quantity: int = Field(ge=0, le=1000, strict=True)
    operation: Literal["add", "set"]
    max_package_price: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )


class Checkout(Input):
    tool: Literal["checkout"]
    address_id: UUID


class AddressAdd(Input):
    tool: Literal["add_address"]
    address: AddressCreate


class AddressEdit(Input):
    tool: Literal["edit_address"]
    address_id: UUID
    changes: AddressUpdate


class AddressRemove(Input):
    tool: Literal["remove_address"]
    address_id: UUID


class ProductAdd(Input):
    tool: Literal["create_product"]
    product: ProductCreate


class ProductEdit(Input):
    tool: Literal["edit_product"]
    product_id: UUID
    changes: ProductUpdate


class Stock(Input):
    tool: Literal["add_stock"]
    product_id: UUID
    quantity: int = Field(ge=1, le=1_000_000, strict=True)


class Fulfill(Input):
    tool: Literal["fulfill"]
    fulfillment_id: UUID
    status: OrderStatus


class Rate(Input):
    tool: Literal["rate"]
    review: RatingCreate


class Reply(Input):
    tool: Literal["reply"]
    rating_id: UUID
    reply: ReviewReply


class Report(Input):
    tool: Literal["report"]
    period: Period = "month"


class Preference(Input):
    tool: Literal["remember"]
    value: str = Field(min_length=1, max_length=200)


class Read(Input):
    tool: Literal["orders", "inventory", "view_cart", "addresses"]
    pending_only: bool = False


Step = Annotated[
    Search
    | Cart
    | Checkout
    | AddressAdd
    | AddressEdit
    | AddressRemove
    | ProductAdd
    | ProductEdit
    | Stock
    | Fulfill
    | Rate
    | Reply
    | Report
    | Preference
    | Read,
    Field(discriminator="tool"),
]


class Plan(Input):
    steps: list[Step] = Field(default_factory=list, max_length=5)
    question: str | None = Field(default=None, max_length=1200)
