import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_seller, get_db
from app.db.base import utc_now
from app.db.models.enums import OrderStatus
from app.db.models.fulfillment import Fulfillment
from app.db.models.order import Order, OrderItem
from app.db.models.product import Product
from app.db.models.user import User

router = APIRouter(prefix="/seller/reports", tags=["Seller reports"])
Period = Literal["day", "week", "month", "year"]


class SalesBucket(BaseModel):
    period: date
    orders: int
    units: int
    revenue: Decimal
    profit: Decimal


class BestSeller(BaseModel):
    name: str
    units: int


class SellerReport(BaseModel):
    revenue: Decimal
    profit: Decimal
    orders: int
    units: int
    repeat_customers: int
    unique_customers: int
    low_stock: int
    forecast_next_week: Decimal | None
    forecast_method: str
    buckets: list[SalesBucket]
    best_selling: list[BestSeller]


async def seller_report(
    db: AsyncSession, seller_id: UUID, period: Period
) -> SellerReport:
    scope = (
        Fulfillment.seller_id == seller_id,
        Fulfillment.status == OrderStatus.delivered,
    )
    local_time = func.timezone("Asia/Kolkata", Fulfillment.delivered_at)
    group = func.date_trunc(period, local_time)
    revenue = func.sum(OrderItem.quantity * OrderItem.price_at_purchase)
    profit = func.sum(
        OrderItem.quantity * (OrderItem.price_at_purchase - OrderItem.cost_at_purchase)
    )

    data = await db.execute(
        select(
            group,
            func.count(distinct(Fulfillment.id)),
            func.sum(OrderItem.quantity),
            revenue,
            profit,
        )
        .select_from(Fulfillment)
        .join(OrderItem, OrderItem.fulfillment_id == Fulfillment.id)
        .where(*scope)
        .group_by(group)
        .order_by(group)
    )
    buckets = [
        SalesBucket(
            period=day.date(), orders=orders, units=units, revenue=total, profit=margin
        )
        for day, orders, units, total, margin in data
        if isinstance(day, datetime)
    ]
    recurring = list(
        await db.scalars(
            select(func.count(Fulfillment.id))
            .select_from(Fulfillment)
            .join(Order, Order.id == Fulfillment.order_id)
            .where(*scope)
            .group_by(Order.customer_id)
        )
    )
    low_stock = (
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.seller_id == seller_id,
                Product.is_active.is_(True),
                Product.stock <= 10,
            )
        )
        or 0
    )
    winners = await db.execute(
        select(OrderItem.product_name, func.sum(OrderItem.quantity).label("units"))
        .join(Fulfillment, Fulfillment.id == OrderItem.fulfillment_id)
        .where(*scope)
        .group_by(OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.product_name)
        .limit(5)
    )

    today = (utc_now() + timedelta(hours=5, minutes=30)).date()
    week = today - timedelta(days=today.weekday())
    week_group = func.date_trunc("week", local_time)
    weekly = await db.execute(
        select(week_group, revenue)
        .select_from(Fulfillment)
        .join(OrderItem, OrderItem.fulfillment_id == Fulfillment.id)
        .where(*scope, local_time < datetime.combine(week, datetime.min.time()))
        .group_by(week_group)
        .order_by(week_group.desc())
        .limit(8)
    )
    weekly_revenue = {
        day.date(): total for day, total in weekly if isinstance(day, datetime)
    }
    forecast = None
    previous_weeks = [week - timedelta(weeks=n) for n in range(1, 9)]
    if all(day in weekly_revenue for day in previous_weeks):
        forecast = (
            sum(
                (weekly_revenue.get(day, Decimal("0")) for day in previous_weeks),
                Decimal("0"),
            )
            / 8
        ).quantize(Decimal("0.01"))

    return SellerReport(
        revenue=sum((row.revenue for row in buckets), Decimal("0")),
        profit=sum((row.profit for row in buckets), Decimal("0")),
        orders=sum(row.orders for row in buckets),
        units=sum(row.units for row in buckets),
        repeat_customers=sum(count > 1 for count in recurring),
        unique_customers=len(recurring),
        low_stock=low_stock,
        forecast_next_week=forecast,
        forecast_method="Eight-week rolling mean of completed sales periods. Seeded sales are simulated.",
        buckets=buckets,
        best_selling=[
            BestSeller(name=name or "Product", units=units) for name, units in winners
        ],
    )


@router.get("", response_model=SellerReport)
async def report(
    period: Period = "month",
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> SellerReport:
    return await seller_report(db, seller.id, period)


@router.get("/csv")
async def report_csv(
    period: Period = "month",
    seller: User = Depends(get_current_seller),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await seller_report(db, seller.id, period)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["period", "orders", "units", "revenue_inr", "gross_profit_inr"])
    for row in data.buckets:
        writer.writerow(
            [row.period.isoformat(), row.orders, row.units, row.revenue, row.profit]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=grocergenie-sales.csv"},
    )
