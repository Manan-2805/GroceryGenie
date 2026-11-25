from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select

from app.api import chat, products
from app.assistant import runner
from app.core import dependencies
from app.core.config import settings
from app.core.security import SESSION_COOKIE, create_login_session
from app.db import seed
from app.db.models.enums import UserRole
from app.db.models.order import Order
from app.db.models.product import Product
from app.db.models.user import User
from app.main import app

pytestmark = pytest.mark.postgres

PRODUCT = {
    "name": "Test Salted Butter",
    "brand": "Test Brand",
    "category": "Dairy & Eggs",
    "package": "200 g",
    "description": "Creamery butter",
    "price": "80.25",
    "stock": 12,
    "cost_price": "53.10",
    "ingredients": "Milk cream, salt",
    "dietary_tags": ["Vegetarian"],
    "allergens": ["milk"],
}
ADDRESS = {
    "label": "Home",
    "line1": "12 Test Road",
    "city": "Pune",
    "state": "Maharashtra",
    "postal_code": "411001",
}


@pytest.fixture
async def clients(sessions, monkeypatch) -> AsyncIterator[list[AsyncClient]]:
    from contextlib import AsyncExitStack

    monkeypatch.setattr(dependencies, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(runner, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(chat, "AsyncSessionFactory", sessions)
    from app import main

    monkeypatch.setattr(main, "AsyncSessionFactory", sessions)
    async with sessions.begin() as db:
        users = [
            User(
                name=f"Fixture {index}",
                email=f"{uuid4()}@example.invalid",
                google_sub=f"fixture:{uuid4()}",
                role=role,
            )
            for index, role in enumerate(
                [UserRole.customer, UserRole.customer, UserRole.seller, UserRole.seller]
            )
        ]
        db.add_all(users)
        await db.flush()
        tokens = [create_login_session(db, user) for user in users]

    async with AsyncExitStack() as stack:
        result = [
            await stack.enter_async_context(
                AsyncClient(
                    base_url="http://test",
                    transport=ASGITransport(app=app),
                    headers={"Origin": settings.parsed_origins[0]},
                    cookies={SESSION_COOKIE: token} if token else {},
                )
            )
            for token in [*tokens, None]
        ]
        yield result


@pytest.mark.asyncio
async def test_catalog_and_marketplace_workflow(clients, monkeypatch, tmp_path):
    buyer, other, seller, second, guest = clients
    assert (await guest.get("/api/v1/health")).json()["db_ok"]
    assert (await guest.get("/health/ready")).status_code == 200
    assert (await guest.get("/api/v1/auth/me")).status_code == 401
    assert (await buyer.post("/api/v1/products", json=PRODUCT)).status_code == 403
    assert (
        await buyer.patch("/api/v1/users/me/role", json={"role": "admin"})
    ).status_code == 400
    assert (
        await buyer.patch(
            "/api/v1/users/me/role",
            headers={"Origin": "https://example.invalid"},
            json={"role": "seller"},
        )
    ).status_code == 403

    async def add_product(account, data):
        res = await account.post("/api/v1/products", json=data)
        assert res.status_code == 201, res.text
        return res.json()["id"]

    first_id = await add_product(seller, PRODUCT)
    second_id = await add_product(
        second, PRODUCT | {"name": "Test Toned Milk", "price": "49.75"}
    )
    assert (
        await second.put(f"/api/v1/products/{first_id}", json={"price": "12.50"})
    ).status_code == 404
    assert (
        await seller.put(
            f"/api/v1/products/{first_id}", json={"stock": 2, "expected_stock": 4}
        )
    ).status_code == 409
    assert (
        await seller.post(
            f"/api/v1/products/{first_id}/stock",
            json={"quantity": 3},
            headers={"Idempotency-Key": str(uuid4())},
        )
    ).json()["stock"] == 15
    assert (
        await seller.put(f"/api/v1/products/{first_id}", json={"cost_price": "55"})
    ).status_code == 200
    assert (
        await seller.get("/api/v1/products/seller", params={"stock_level": "low"})
    ).json()["total"] == 0
    public = await guest.get(f"/api/v1/products/{first_id}")
    assert public.status_code == 200 and "cost_price" not in public.json()
    found = await guest.get(
        "/api/v1/products",
        params={"search": "test salted butter", "stock_quantity": 1, "limit": 20},
    )
    assert first_id in {p["id"] for p in found.json()["items"]}
    assert (
        await guest.get(
            "/api/v1/products", params={"search": "Test Toned Milk", "max_price": 45}
        )
    ).json()["total"] == 0

    monkeypatch.setattr(products, "UPLOADS_DIR", tmp_path)
    img = BytesIO()
    Image.new("RGB", (16, 16)).save(img, format="PNG")
    image_res = await seller.post(
        "/api/v1/products/upload",
        files={"file": ("milk.png", img.getvalue(), "image/png")},
    )
    assert image_res.status_code == 200 and image_res.json()["url"].endswith(".jpg")
    assert (
        await seller.post(
            "/api/v1/products/upload",
            files={"file": ("bad.png", b"not an image", "image/png")},
        )
    ).status_code == 415

    saved = await buyer.post("/api/v1/addresses", json=ADDRESS)
    assert saved.status_code == 201 and saved.json()["is_default"]
    address_id = saved.json()["id"]
    alternate = await buyer.post(
        "/api/v1/addresses", json=ADDRESS | {"label": "Work", "line2": "Suite 4"}
    )
    alternate_id = alternate.json()["id"]
    assert (
        await other.put(f"/api/v1/addresses/{address_id}", json={"city": "Mumbai"})
    ).status_code == 404
    assert (
        await buyer.put(f"/api/v1/addresses/{alternate_id}", json={"is_default": True})
    ).status_code == 200
    assert (await buyer.delete(f"/api/v1/addresses/{alternate_id}")).status_code == 200
    assert (await buyer.get("/api/v1/addresses")).json()[0]["is_default"]
    assert (
        await buyer.post(
            "/api/v1/cart",
            headers={"Idempotency-Key": str(uuid4())},
            json={"product_id": first_id, "quantity": 0},
        )
    ).status_code == 422
    assert (
        await buyer.post(
            "/api/v1/cart",
            headers={"Idempotency-Key": str(uuid4())},
            json={"product_id": first_id, "quantity": 2},
        )
    ).status_code == 201
    assert (
        await buyer.put(f"/api/v1/cart/{first_id}", json={"quantity": 3})
    ).status_code == 200
    assert (
        await buyer.post(
            "/api/v1/cart",
            headers={"Idempotency-Key": str(uuid4())},
            json={"product_id": second_id, "quantity": 1},
        )
    ).status_code == 201
    assert len((await buyer.get("/api/v1/cart")).json()) == 2
    assert (await other.get("/api/v1/cart")).json() == []

    quote = await buyer.post("/api/v1/orders/quotes", json={"address_id": address_id})
    assert quote.status_code == 201 and quote.json()["total"] == "290.50"
    key = str(uuid4())
    order_data = {"quote_id": quote.json()["id"]}
    order = await buyer.post(
        "/api/v1/orders", json=order_data, headers={"Idempotency-Key": key}
    )
    assert order.status_code == 201
    placed = order.json()
    order_url = f"/api/v1/orders/{placed['id']}"
    assert len(placed["fulfillments"]) == 2
    assert (
        await buyer.post(
            "/api/v1/orders", json=order_data, headers={"Idempotency-Key": key}
        )
    ).json()["id"] == placed["id"]
    assert (
        await buyer.post(
            "/api/v1/orders", json=order_data, headers={"Idempotency-Key": str(uuid4())}
        )
    ).status_code == 409
    assert (await other.get(order_url)).status_code == 404
    assert (await seller.get(order_url)).status_code == 403
    assert (await buyer.get("/api/v1/orders")).json()["total"] == 1

    review = {
        "order_id": placed["id"],
        "product_id": first_id,
        "stars": 4,
        "comment": "Good butter.",
    }
    assert (await buyer.post("/api/v1/ratings", json=review)).status_code == 404
    child = (await seller.get("/api/v1/orders/seller/queue")).json()["items"][0]
    queue_url = f"/api/v1/orders/{child['id']}/status"
    assert len(child["items"]) == 1 and child["items"][0]["product_id"] == first_id
    assert (await second.put(queue_url, json={"status": "packed"})).status_code == 404
    assert (
        await seller.put(queue_url, json={"status": "delivered"})
    ).status_code == 409
    for state in ("packed", "out_for_delivery", "delivered"):
        assert (await seller.put(queue_url, json={"status": state})).json()[
            "status"
        ] == state
    assert (await buyer.get(order_url)).json()["status"] == "placed"
    rated = await buyer.post("/api/v1/ratings", json=review)
    assert rated.status_code == 201, rated.text
    assert (await buyer.post("/api/v1/ratings", json=review)).status_code == 409
    reply_url = f"/api/v1/ratings/{rated.json()['id']}/reply"
    assert (
        await second.post(reply_url, json={"reply": "Not my product."})
    ).status_code == 404
    assert (
        await seller.post(reply_url, json={"reply": "Thank you!"})
    ).status_code == 200
    assert (await seller.post(reply_url, json={"reply": "Again"})).status_code == 409
    reviews = (await guest.get(f"/api/v1/ratings/product/{first_id}")).json()
    assert reviews["total"] == 1 and reviews["items"][0]["reply"] == "Thank you!"
    assert (await seller.get("/api/v1/ratings/seller")).json()[0]["stars"] == 4
    assert (await second.get("/api/v1/ratings/seller")).json() == []
    report = (await seller.get("/api/v1/seller/reports?period=day")).json()
    assert report["revenue"] == "240.75" and report["profit"] == "75.75"
    assert (await second.get("/api/v1/seller/reports")).json()["orders"] == 0
    assert "240.75,75.75" in (await seller.get("/api/v1/seller/reports/csv")).text
    assert (await buyer.get("/api/v1/seller/reports")).status_code == 403

    assert (await seller.delete(f"/api/v1/products/{first_id}")).status_code == 200
    assert (await guest.get(f"/api/v1/products/{first_id}")).status_code == 404
    assert (await buyer.post("/api/v1/auth/logout")).status_code == 200
    assert (await buyer.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_owned_chat_history_and_explicit_preferences(clients):
    buyer, other, _, _, _ = clients
    response = await buyer.post(
        "/api/v1/chat/text", json={"message": "remember that I prefer apples"}
    )
    assert response.status_code == 200 and "permission_request" in response.text
    ident = response.headers["X-Session-ID"]
    assert (await buyer.get("/api/v1/users/facts")).json() == []
    history = (
        await buyer.get("/api/v1/chat/history", params={"session_id": ident})
    ).json()
    confirmation_id = history["messages"][-1]["confirmation_id"]
    assert (
        await other.get("/api/v1/chat/history", params={"session_id": ident})
    ).status_code == 404
    answer = await buyer.post(
        "/api/v1/chat/text",
        json={
            "session_id": ident,
            "confirmation_id": confirmation_id,
            "approved": True,
        },
    )
    assert "Completed" in answer.text
    facts = (await buyer.get("/api/v1/users/facts")).json()
    assert facts[0]["fact_text"] == "I prefer apples"
    assert (
        await other.delete(f"/api/v1/users/facts/{facts[0]['id']}")
    ).status_code == 404
    assert (
        await buyer.delete(f"/api/v1/users/facts/{facts[0]['id']}")
    ).status_code == 200
    assert (await buyer.get("/api/v1/chat/conversations")).json()[0]["id"] == ident
    assert (
        await buyer.delete(f"/api/v1/chat/conversations/{ident}")
    ).status_code == 204


@pytest.mark.asyncio
async def test_showcase_seed_preserves_existing_records(sessions, monkeypatch):
    monkeypatch.setattr(seed, "AsyncSessionFactory", sessions)
    anchor = datetime.now(UTC).date()
    await seed.seed_data(anchor)
    product_id = seed.demo_id("product/0/0/0/0")
    async with sessions.begin() as db:
        product = await db.get(Product, product_id)
        assert product is not None
        product.stock = 404
    await seed.seed_data(anchor)
    async with sessions() as db:
        product = await db.get(Product, product_id)
        assert product is not None and product.stock == 404
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.label_source == "Synthetic demonstration label")
            )
            == 10_000
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.checkout_key.startswith("order/"))
            )
            == 192
        )


@pytest.mark.asyncio
async def test_google_callback_session_rotation_and_role_isolation(
    clients, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.api import auth

    _, _, _, _, guest = clients
    identity = {
        "sub": f"google-fixture:{uuid4()}",
        "email": "fixture@example.invalid",
        "name": "Fixture",
        "email_verified": True,
    }
    exchange = AsyncMock(
        return_value={"userinfo": identity | {"email_verified": False}}
    )
    monkeypatch.setattr(
        auth.oauth,
        "create_client",
        lambda _: SimpleNamespace(authorize_access_token=exchange),
    )
    unverified = await guest.get("/api/v1/auth/google/callback")
    assert unverified.headers["Location"] == "/login?error=unverified_identity"
    assert (await guest.get("/api/v1/auth/me")).status_code == 401
    exchange.return_value = {"userinfo": identity}
    login = await guest.get("/api/v1/auth/google/callback")
    assert login.status_code in (302, 307) and "HttpOnly" in login.headers["Set-Cookie"]
    profile = (await guest.get("/api/v1/auth/me")).json()
    assert profile["role"] == "customer"
    changed = await guest.patch("/api/v1/users/me/role", json={"role": "seller"})
    assert changed.json()["role"] == "seller"
    assert (await guest.get("/api/v1/cart")).status_code == 403
    assert (await guest.get("/api/v1/products/seller")).json()["total"] == 0
    again = await guest.get("/api/v1/auth/google/callback")
    assert again.status_code in (302, 307)
    refreshed = (await guest.get("/api/v1/auth/me")).json()
    assert refreshed["id"] == profile["id"] and refreshed["role"] == "seller"


@pytest.mark.asyncio
async def test_assistant_local_address_collects_and_confirms_exact_values(
    clients, monkeypatch
):
    from unittest.mock import AsyncMock

    cloud = AsyncMock()
    monkeypatch.setattr(runner, "interpret", cloud)
    buyer, _, _, _, _ = clients

    async def send(message, session_id=None):
        result = await buyer.post(
            "/api/v1/chat/text", json={"message": message, "session_id": session_id}
        )
        assert result.status_code == 200
        return result.text, result.headers["X-Session-ID"]

    start, session_id = await send("add address")
    assert "What label" in start
    for given, expected in (
        ("Home", "complete delivery street address"),
        ("12 Demo Road", "city"),
        ("Pune", "state"),
        ("Maharashtra", "postal code"),
        ("4", "postal code"),
        ("411001", "Review and confirm these changes"),
    ):
        text, _ = await send(given, session_id)
        assert expected in text
    assert all(
        part in text for part in ("12 Demo Road", "Pune", "Maharashtra", "411001")
    )
    assert (await buyer.get("/api/v1/addresses")).json() == []
    confirm, _ = await send("yes", session_id)
    assert "Completed" in confirm
    assert (await buyer.get("/api/v1/addresses")).json()[0]["postal_code"] == "411001"
    cloud.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_transport_sessions_share_scope_and_wait_for_playback_ack(
    sessions, monkeypatch
):
    import asyncio
    import json
    from types import SimpleNamespace

    from app.api import ws

    monkeypatch.setattr(ws, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(
        ws,
        "get_piper_voice",
        lambda: SimpleNamespace(config=SimpleNamespace(sample_rate=22050)),
    )
    monkeypatch.setattr(ws, "synthesize_text_to_pcm", lambda _: b"\x00\x00" * 80)
    monkeypatch.setattr(ws, "transcribe_pcm_chunk", lambda _: "show my orders")
    monkeypatch.setattr(runner, "AsyncSessionFactory", sessions)
    async with sessions.begin() as db:
        fixture = User(
            google_sub=f"voice-test:{uuid4()}",
            email="voice-test@example.invalid",
            name="Voice test",
        )
        db.add(fixture)
        await db.flush()
        token = create_login_session(db, fixture)

    class Socket:
        def __init__(self, origin):
            self.headers = {"origin": origin}
            self.cookies = {SESSION_COOKIE: token}
            self.query_params = {}
            self.events = asyncio.Queue()
            self.inbox = asyncio.Queue()

        async def accept(self):
            await self.events.put("accepted")

        async def close(self, code):
            await self.events.put(code)

        async def send_json(self, event):
            await self.events.put(event)

        async def send_bytes(self, pcm):
            await self.events.put(pcm)

        async def receive(self):
            return await self.inbox.get()

        async def control(self, kind):
            await self.inbox.put(
                {"type": "websocket.receive", "text": json.dumps({"type": kind})}
            )

    denied = Socket("https://outside.example.invalid")
    await ws.voice(denied)
    assert await denied.events.get() == 1008

    local = Socket(settings.parsed_origins[0])
    task = asyncio.create_task(ws.voice(local))
    async with asyncio.timeout(6):
        assert await local.events.get() == "accepted"
        connection = await local.events.get()
        assert connection["type"] == "session_started"
        assert (await local.events.get())["sample_rate"] == 22050
        assert isinstance(await local.events.get(), bytes)
        assert (await local.events.get())["type"] == "playback_ended"
        await local.control("playback_complete")
        for pcm in [b"\x00\x05" * 1024] * 5 + [b"\x00\x00" * 1024] * 12:
            await local.inbox.put({"type": "websocket.receive", "bytes": pcm})
        assert (await local.events.get())["status"] == "transcribing"
        assert (await local.events.get())["text"] == "show my orders"
        assert (await local.events.get())["status"] == "thinking"
        assert (await local.events.get())["text"] == "No orders found."
        await local.control("interrupt")
        await local.control("end_session")
        await task


@pytest.mark.asyncio
async def test_assistant_retains_quantity_and_total_budget_through_choice(
    clients, monkeypatch
):
    from unittest.mock import AsyncMock

    cloud = AsyncMock()
    monkeypatch.setattr(runner, "interpret", cloud)
    buyer, _, seller, _, _ = clients
    inventory = PRODUCT | {"name": "Budget Test Butter", "price": "40", "stock": 5}
    product = (await seller.post("/api/v1/products", json=inventory)).json()
    first = await buyer.post(
        "/api/v1/chat/text",
        json={
            "message": "Find two packages of budget test butter under ₹90 and add them to my cart"
        },
    )
    assert "total budget" in first.text
    session_id = first.headers["X-Session-ID"]
    second = await buyer.post(
        "/api/v1/chat/text", json={"message": "total", "session_id": session_id}
    )
    assert "80.00 total" in second.text
    third = await buyer.post(
        "/api/v1/chat/text", json={"message": "pick 1", "session_id": session_id}
    )
    assert "permission_request" in third.text and "2 packages" in third.text
    assert (await buyer.get("/api/v1/cart")).json() == []
    confirmed = await buyer.post(
        "/api/v1/chat/text", json={"message": "yes", "session_id": session_id}
    )
    assert "Completed" in confirmed.text
    cart = (await buyer.get("/api/v1/cart")).json()
    assert any(
        item["product_id"] == product["id"] and item["quantity"] == 2 for item in cart
    )
    cloud.assert_not_awaited()
