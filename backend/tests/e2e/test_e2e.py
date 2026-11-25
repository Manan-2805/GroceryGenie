"""Desktop browser scenarios served by the real app and a disposable PostgreSQL database."""

import asyncio
import os
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, expect, sync_playwright
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.security import SESSION_COOKIE, create_login_session
from app.db.models.enums import UserRole
from app.db.models.user import User

pytestmark = pytest.mark.e2e
BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5173")


async def create_fixture_login() -> str:
    url = os.environ["TEST_DATABASE_URL"]
    if "test" not in url.rsplit("/", 1)[-1].lower():
        raise ValueError("Use a disposable test database for browser fixtures.")
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            user = User(
                google_sub=f"browser-test:{uuid4()}",
                name="Browser Fixture",
                email=f"{uuid4()}@example.invalid",
                role=UserRole.customer,
            )
            db.add(user)
            await db.flush()
            return create_login_session(db, user)
    finally:
        await engine.dispose()


@pytest.fixture
def browser():
    if os.environ.get("RUN_E2E") != "1":
        pytest.skip(
            "Run through make test-e2e against the disposable browser fixture stack."
        )
    with sync_playwright() as playwright:
        application = playwright.chromium.launch()
        yield application
        application.close()


def test_public_catalog_browsing_and_google_only_login(browser: Browser):
    with browser.new_context(base_url=BASE_URL) as context:
        page = context.new_page()
        page.goto("/items")
        expect(
            page.get_by_role("heading", name="Catalog", exact=False).first
        ).to_be_visible()
        page.goto("/login")
        expect(
            page.get_by_text("Sign in with Google", exact=False).first
        ).to_be_visible()
        expect(page.locator("input[type=password]")).to_have_count(0)


@pytest.fixture
def token():
    return asyncio.run(create_fixture_login())


def test_assistant_confirms_and_saves_explicit_preference(token: str, browser: Browser):
    with browser.new_context(base_url=BASE_URL) as context:
        context.add_cookies([{"name": SESSION_COOKIE, "value": token, "url": BASE_URL}])
        page = context.new_page()
        page.goto("/agent")
        page.get_by_role("button", name="Text Mode").click()
        page.get_by_role("textbox", name="Message").fill(
            "remember that I prefer apples"
        )
        page.get_by_role("button", name="Send", exact=True).click()
        expect(page.get_by_text("Review and confirm", exact=False)).to_be_visible()
        page.get_by_role("button", name="Confirm action").click()
        expect(page.get_by_text("Completed.", exact=False)).to_be_visible()
        page.goto("/settings")
        expect(page.get_by_text("I prefer apples", exact=False)).to_be_visible()
        page.get_by_role("button", name="Delete preference").click()
        expect(
            page.get_by_text("No preferences saved yet.", exact=False)
        ).to_be_visible()


def test_browser_checkout_reviews_cost_before_simulated_payment(
    token: str, browser: Browser
):
    from app.db.seed import demo_id

    with browser.new_context(base_url=BASE_URL) as context:
        context.add_cookies([{"name": SESSION_COOKIE, "value": token, "url": BASE_URL}])
        db = context.request
        origin = {"Origin": BASE_URL}
        saved = db.post(
            "/api/v1/addresses",
            headers=origin,
            data={
                "label": "Browser home",
                "line1": "8 Sample Road",
                "city": "Pune",
                "state": "Maharashtra",
                "postal_code": "411001",
            },
        )
        assert saved.ok
        for index in (1, 2):
            product_id = str(demo_id(f"product/{index}/0/0/0"))
            added = db.post(
                "/api/v1/cart",
                headers=origin | {"Idempotency-Key": str(uuid4())},
                data={"product_id": product_id, "quantity": 1},
            )
            assert added.ok
        page = context.new_page()
        page.goto("/checkout")
        page.get_by_role("button", name="Review order", exact=False).click()
        expect(
            page.get_by_text("Payment is simulated", exact=False).first
        ).to_be_visible()
        assert db.get("/api/v1/orders").json()["total"] == 0
        page.get_by_role("button", name="Place order", exact=False).click()
        expect(page.get_by_text("Order placed", exact=False).first).to_be_visible()
        assert len(db.get("/api/v1/orders").json()["items"][0]["fulfillments"]) == 2


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_VOICE") != "1", reason="Requires local voice weights."
)
def test_browser_hands_free_voice_lifecycle(token: str, tmp_path):
    import wave

    from app.services.voice.tts import get_piper_voice

    voice = get_piper_voice()
    wav = tmp_path / "english-command.wav"
    with wave.open(str(wav), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(voice.config.sample_rate)
        spoken = b"".join(
            chunk.audio_int16_bytes for chunk in voice.synthesize("Show my orders.")
        )
        silence = bytes(voice.config.sample_rate * 3)
        audio.writeframes(silence + spoken + silence)
    with sync_playwright() as playwright:
        application = playwright.chromium.launch(
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={wav}",
            ]
        )
        try:
            with application.new_context(
                base_url=BASE_URL, permissions=["microphone"]
            ) as context:
                context.add_cookies(
                    [{"name": SESSION_COOKIE, "value": token, "url": BASE_URL}]
                )
                page = context.new_page()
                page.goto("/agent")
                page.get_by_role("button", name="Voice Mode").click()
                page.get_by_role("button", name="Start voice session").click()
                expect(page.get_by_text("No orders found.").first).to_be_visible(
                    timeout=35000
                )
                page.get_by_role("button", name="End voice session").click()
                expect(page.get_by_text("Microphone is off")).to_be_visible()
        finally:
            application.close()
