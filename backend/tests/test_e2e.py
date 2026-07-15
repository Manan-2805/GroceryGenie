import os
import time

import pytest
from playwright.sync_api import Page, sync_playwright

FRONTEND_URL = os.getenv("TEST_FRONTEND_URL", "http://localhost:5173")
HEADLESS = False
SLOW_MO = 600
DEFAULT_TIMEOUT = 45_000

DEV_EMAIL = "dev@GroceryGenie.com"
DEV_PASSWORD = "pass123"


@pytest.fixture(scope="module")
def browser_context():
    """Playwright browser context for all E2E tests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
            channel="chrome",
        )
        context = browser.new_context()
        context.set_default_timeout(DEFAULT_TIMEOUT)
        yield context
        browser.close()


def _login(page: Page) -> None:
    """Login with the dev bypass button."""
    page.goto(FRONTEND_URL)
    page.wait_for_selector("h1:has-text('GroceryGenie')")

    # Click the "Continue as Dev User" button
    page.locator("button:has-text('Continue as Dev User')").click()

    # Wait until the nav header appears (logged in)
    page.wait_for_selector("a[href='/items']")


def _logout(page: Page) -> None:
    """Click the logout icon in the header."""
    page.locator("header button[id='logout-btn']").click()
    page.wait_for_selector("h1:has-text('GroceryGenie')")


def _switch_role(page: Page, role: str) -> None:
    """Navigate to Settings and click the role switch button."""
    page.locator("a[href='/settings']").click()
    page.wait_for_selector("h1:has-text('Settings')")
    if role == "seller":
        page.locator("button:has-text('Seller Panel')").click()
        # Wait for the nav link that only appears for sellers
        page.wait_for_selector("a[href='/seller']")
    else:
        page.locator("button:has-text('Customer View')").click()
        # Orders and Cart links re-appear
        page.wait_for_selector("a[href='/orders']")


def test_complete_e2e_flow(browser_context) -> None:
    suffix = str(int(time.time()))[-4:]
    product_name = f"E2E Mango {suffix}"
    updated_name = f"E2E Premium Mango {suffix}"

    page = browser_context.new_page()

    # -----------------------------------------------------------------------
    # STEP 1: Login as dev user (customer by default)
    # -----------------------------------------------------------------------
    _login(page)

    # -----------------------------------------------------------------------
    # STEP 2: Switch role to Seller via Settings
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")

    # -----------------------------------------------------------------------
    # STEP 3: Navigate to Seller Panel, create a product (stock=2, price=3.99)
    # -----------------------------------------------------------------------
    page.locator("a[href='/seller']").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Inventory page
    page.locator("a[href='/inventory']").click()
    page.wait_for_selector("h1:has-text('Inventory')")

    # Toggle the Add Product form open
    page.locator("button:has-text('Add Product')").click()
    page.wait_for_selector("h4:has-text('New Product Form')")

    page.locator("input[placeholder='Fresh Organic Strawberries']").fill(product_name)
    page.locator("input[placeholder='3.99']").fill("3.99")
    page.locator("input[placeholder='24']").fill("2")
    page.locator("textarea[placeholder]").fill(
        "Ripe juicy mangoes from local orchards."
    )
    page.locator("button:has-text('Add to Catalog')").click()

    # Wait for product to be added
    page.wait_for_timeout(1500)

    # Find the row containing the product name (supports <tr> text or <p> text)
    product_row = page.locator(
        f"tr:has-text('{product_name}'), tr:has(p:has-text('{product_name}'))"
    ).first
    product_row.wait_for(state="visible")

    # -----------------------------------------------------------------------
    # STEP 4: Edit product — update name, description, price, stock, category
    # -----------------------------------------------------------------------

    # Click the pencil icon button
    product_row.locator("button:has(svg.lucide.lucide-pen-line)").click()

    # Wait for side panel
    page.wait_for_selector("label:has-text('Product Name')")

    page.locator("label:has-text('Product Name') + input").fill(updated_name)

    page.locator("label:has-text('Description') + textarea").fill(
        "Updated premium mangoes from local orchards."
    )

    page.locator("label:has-text('Price') + input").fill("4.49")

    page.locator("label:has-text('Stock Quantity') + input").fill("2")

    page.locator("label:has-text('Category') + select").select_option(label="Produce")

    save_btn = page.locator("button:has-text('Save Changes')")
    save_btn.wait_for(state="visible")
    save_btn.click()

    # Wait until save finishes
    save_btn.wait_for(state="detached")

    # Search for updated row
    page.wait_for_timeout(1000)

    updated_row = page.locator(
        f"tr:has-text('{updated_name}'), tr:has(p:has-text('{updated_name}'))"
    ).first
    updated_row.wait_for(state="visible")

    row_text = updated_row.inner_text()

    assert updated_name in row_text
    assert "4.49" in row_text
    assert "2" in row_text

    # -----------------------------------------------------------------------
    # STEP 5: Switch role to Customer
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")

    # -----------------------------------------------------------------------
    # STEP 6: Search for the product in Catalog
    # -----------------------------------------------------------------------
    page.locator("a[href='/items']").click()
    page.wait_for_selector("input[placeholder]")
    page.locator("input[placeholder]").first.fill(updated_name)
    page.wait_for_selector(f"text={updated_name}")

    # Verify price is visible
    assert "4.49" in page.inner_text("body")

    # -----------------------------------------------------------------------
    # STEP 7: Open product detail, verify stock, add 1 to cart
    # -----------------------------------------------------------------------
    page.locator(f"text={updated_name}").first.click()
    page.wait_for_selector("button:has-text('Add to Cart')")

    # Verify remaining stock shown
    assert "2" in page.inner_text("body")

    qty_input = page.locator("input[type='number'][min='1']")
    qty_input.fill("1")
    page.locator("button:has-text('Add to Cart')").click()

    # Custom dialog success
    page.wait_for_selector(".fixed.inset-0")
    page.locator("button:has-text('OK')").click()

    # -----------------------------------------------------------------------
    # STEP 8: Cart -> Checkout -> Place Order
    # -----------------------------------------------------------------------
    page.locator("a[href='/cart']").click()
    page.wait_for_selector("h1:has-text('Shopping Cart')")
    assert updated_name in page.inner_text("body")

    page.locator("a:has-text('Proceed to Checkout')").click()
    page.wait_for_selector("h1:has-text('Checkout')")

    page.wait_for_selector("form:has(button:has-text('Place Secure Order'))")
    page.locator("input[placeholder='123 Main Street']").fill("10 E2E Lane")
    page.locator("input[placeholder='Dublin']").fill("Test City")
    page.locator("input[placeholder='D01 A234']").fill("TC1 1TC")
    page.locator("button:has-text('Place Secure Order')").click()

    page.wait_for_selector(".fixed.inset-0")
    page.locator("button:has-text('OK')").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    assert "placed" in page.inner_text("body").lower()

    # -----------------------------------------------------------------------
    # STEP 9: Verify stock is now 1 on product detail
    # -----------------------------------------------------------------------
    page.locator("a[href='/items']").click()
    page.wait_for_selector("input[placeholder]")
    page.locator("input[placeholder]").first.fill(updated_name)
    page.wait_for_selector(f"text={updated_name}")
    page.locator(f"text={updated_name}").first.click()
    page.wait_for_selector("button:has-text('Add to Cart')")
    assert "1" in page.inner_text("body")

    # -----------------------------------------------------------------------
    # STEP 10: Switch to Seller -> advance order: placed -> packed
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")
    page.locator("a[href='/seller']").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Fulfillment Queue
    page.locator("a[href='/fulfillment']").click()
    page.wait_for_selector("h1:has-text('Fulfillment Queue')")

    page.locator("button:has-text('Mark Packed')").first.click()
    page.wait_for_selector("text=packed")

    # -----------------------------------------------------------------------
    # STEP 11: Switch to Customer -> verify order is packed
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")
    page.locator("a[href='/orders']").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    assert "packed" in page.inner_text("body").lower()

    # -----------------------------------------------------------------------
    # STEP 12: Switch to Seller -> packed -> out_for_delivery
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")
    page.locator("a[href='/seller']").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Fulfillment Queue
    page.locator("a[href='/fulfillment']").click()
    page.wait_for_selector("h1:has-text('Fulfillment Queue')")

    page.locator("button:has-text('Mark Out for Delivery')").first.click()
    page.wait_for_selector("text='out for delivery'")

    # -----------------------------------------------------------------------
    # STEP 13: Switch to Customer -> verify out_for_delivery
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")
    page.locator("a[href='/orders']").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    assert "out for delivery" in page.inner_text("body").lower()

    # -----------------------------------------------------------------------
    # STEP 14: Switch to Seller -> out_for_delivery -> delivered
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")
    page.locator("a[href='/seller']").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Fulfillment Queue
    page.locator("a[href='/fulfillment']").click()
    page.wait_for_selector("h1:has-text('Fulfillment Queue')")

    page.locator("button:has-text('Mark Delivered')").first.click()
    page.wait_for_selector("text=delivered")

    # -----------------------------------------------------------------------
    # STEP 15: Switch to Customer -> verify delivered
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")
    page.locator("a[href='/orders']").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    assert "delivered" in page.inner_text("body").lower()

    # -----------------------------------------------------------------------
    # STEP 16: Order the last 1 item -> verify Out of Stock
    # -----------------------------------------------------------------------
    page.locator("a[href='/items']").click()
    page.wait_for_selector("input[placeholder]")
    page.locator("input[placeholder]").first.fill(updated_name)
    page.wait_for_selector(f"text={updated_name}")
    page.locator(f"text={updated_name}").first.click()
    page.wait_for_selector("button:has-text('Add to Cart')")

    qty_input = page.locator("input[type='number'][min='1']")
    qty_input.fill("1")
    page.locator("button:has-text('Add to Cart')").click()
    page.wait_for_selector(".fixed.inset-0")
    page.locator("button:has-text('OK')").click()

    page.locator("a[href='/cart']").click()
    page.wait_for_selector("h1:has-text('Shopping Cart')")
    page.locator("a:has-text('Proceed to Checkout')").click()
    page.wait_for_selector("h1:has-text('Checkout')")
    page.wait_for_selector("form:has(button:has-text('Place Secure Order'))")

    page.locator("input[placeholder='123 Main Street']").fill("10 E2E Lane")
    page.locator("input[placeholder='Dublin']").fill("Test City")
    page.locator("input[placeholder='D01 A234']").fill("TC1 1TC")
    page.locator("button:has-text('Place Secure Order')").click()
    page.wait_for_selector(".fixed.inset-0")
    page.locator("button:has-text('OK')").click()
    page.wait_for_selector("h1:has-text('Your Orders')")

    # Go back to product detail; it should now show Out of Stock
    page.locator("a[href='/items']").click()
    page.wait_for_selector("input[placeholder]")
    page.locator("input[placeholder]").first.fill(updated_name)
    page.wait_for_selector(f"text={updated_name}")
    page.locator(f"text={updated_name}").first.click()
    page.wait_for_selector("h1")

    assert "Out of stock" in page.inner_text("body")
    assert page.locator("button:has-text('Add to Cart')").count() == 0

    # -----------------------------------------------------------------------
    # STEP 17: Logout
    # -----------------------------------------------------------------------
    page.locator("header button#logout-btn").click()
    page.wait_for_selector("h1:has-text('GroceryGenie')")

    page.close()
