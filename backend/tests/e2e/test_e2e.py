import os
import re
import time

import pytest
from playwright.sync_api import Page, sync_playwright

FRONTEND_URL = os.getenv("TEST_FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("TEST_BACKEND_URL", "http://localhost:8000")
HEADLESS = False
SLOW_MO = int(os.getenv("PLAYWRIGHT_SLOW_MO", "300"))
DEFAULT_TIMEOUT = 3_000

DEV_EMAIL = "dev@GroceryGenie.com"
DEV_PASSWORD = "pass123"


@pytest.fixture(scope="module")
def browser_context():
    """Playwright browser context for all E2E tests."""
    if os.getenv("RUN_E2E", "0") != "1":
        pytest.skip("E2E tests are disabled. Set RUN_E2E=1 to enable.")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
        )
        context = browser.new_context()
        context.set_default_timeout(DEFAULT_TIMEOUT)
        yield context
        browser.close()


def _login(page: Page) -> None:
    """Login through backend dev bypass endpoint to avoid OAuth UI coupling."""
    response = page.request.post(f"{BACKEND_URL}/api/v1/auth/dev-bypass")
    assert response.ok, f"Dev bypass failed with status {response.status}"

    page.goto(FRONTEND_URL)
    page.wait_for_selector("header button#logout-btn")


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
        # Wait for seller dashboard nav link
        page.get_by_role("link", name="Dashboard").wait_for()
    else:
        page.locator("button:has-text('Customer View')").click()
        # Orders and Cart links re-appear
        page.wait_for_selector("a[href='/orders']")


def _clear_cart_after_login(page: Page) -> None:
    """Clear all existing cart items so the scenario starts from a clean cart using the UI."""
    page.locator("a[href='/cart']").click()
    page.wait_for_selector("h1:has-text('Shopping Cart')")

    while True:
        if page.locator("text=Your shopping cart is empty.").count() > 0:
            break

        trash_btn = page.locator("tbody tr button:has(svg.lucide-trash-2)").first
        if trash_btn.count() == 0:
            break

        trash_btn.click()
        page.wait_for_timeout(500)


def _clear_addresses_after_login(page: Page) -> None:
    """Delete all existing addresses using the UI."""
    page.locator("a[href='/settings']").click()
    page.wait_for_selector("h1:has-text('Settings')")

    if page.locator("h3:has-text('Saved Addresses')").count() == 0:
        return

    while True:
        delete_btn = page.locator("tbody tr button[title='Delete Address']").first
        if delete_btn.count() == 0:
            break

        delete_btn.click()
        page.wait_for_timeout(500)


def _create_and_select_new_address(page: Page, label: str, line1: str) -> None:
    """Create a fresh address in settings and mark it as default for checkout."""
    page.locator("a[href='/settings']").click()
    page.wait_for_selector("h1:has-text('Settings')")

    page.get_by_role("button", name="Add New", exact=True).click()
    page.locator("input[placeholder='Home']").fill(label)
    page.locator("input[placeholder='123 Main St']").fill(line1)
    page.locator("input[placeholder='Apt 4B']").fill("Suite 9")
    page.locator("input[placeholder='Dublin']").fill("Test City")
    page.locator("input[placeholder='Leinster']").fill("Leinster")
    page.locator("input[placeholder='D02 X285']").fill("TC9 9TC")
    page.locator("input[placeholder='Ireland']").fill("Ireland")
    page.get_by_role("button", name="Save Address", exact=True).click()

    # Wait for the row in the DataTable
    address_row = page.locator(f"tbody tr:has-text('{label}'):has-text('{line1}')")
    address_row.wait_for(state="visible")

    set_default_btn = address_row.locator("button[title='Set Default']")
    if set_default_btn.count() > 0:
        set_default_btn.click()

    address_row.locator("text=Default").wait_for(state="visible")


def _extract_order_id_from_dialog(page: Page) -> str:
    """Extract a full UUID order ID from checkout success dialog text."""
    dialog_message = page.locator(".fixed.inset-0 p").inner_text()
    match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        dialog_message,
        re.IGNORECASE,
    )
    assert match is not None, (
        f"Unable to extract order ID from dialog: {dialog_message}"
    )
    return match.group(0)


def _order_row_by_short_id(page: Page, order_short_id: str):
    row = page.locator(f"tbody tr:has-text('{order_short_id}')")
    row.wait_for(state="visible")
    return row


def _open_customer_order_details(page: Page, order_short_id: str) -> None:
    row = _order_row_by_short_id(page, order_short_id)
    row.get_by_role("button", name="View", exact=True).click()
    page.wait_for_selector(f"h3:has-text('#{order_short_id}')")


def _advance_order_status_in_fulfillment(
    page: Page,
    order_short_id: str,
    action_label: str,
    next_label: str | None,
) -> None:
    row = _order_row_by_short_id(page, order_short_id)
    row.get_by_role("button", name="Fulfill", exact=True).click()

    page.get_by_role("button", name=action_label, exact=True).click()
    page.wait_for_selector(".fixed.inset-0")
    page.get_by_role("button", name="OK", exact=True).click()

    if next_label is not None:
        page.get_by_role("button", name=next_label, exact=True).wait_for()
    else:
        page.wait_for_selector("text=Delivered Successfully")


def _find_table_row_across_pages(page: Page, row_text: str):
    """Find a DataTable row by text, scanning paginated pages from the first page."""
    prev_button = page.get_by_role("button", name="Previous", exact=True)
    while prev_button.count() > 0 and prev_button.is_enabled():
        prev_button.click()
        page.wait_for_timeout(300)

    for _ in range(30):
        row = page.locator(f"tbody tr:has-text('{row_text}')")
        if row.count() > 0:
            row.wait_for(state="visible")
            return row

        next_button = page.get_by_role("button", name="Next", exact=True)
        if next_button.count() == 0 or not next_button.is_enabled():
            break
        next_button.click()
        page.wait_for_timeout(500)

    raise AssertionError(f"Unable to find table row containing: {row_text}")


@pytest.mark.e2e
def test_complete_e2e_flow(browser_context) -> None:
    suffix = str(int(time.time()))[-4:]
    product_name = f"E2E Mango {suffix}"
    updated_name = f"E2E Premium Mango {suffix}"
    address_label = f"E2E Address {suffix}"
    address_line1 = f"{suffix} Test Lane"
    rating_comment = f"E2E review {suffix}"
    created_order_id = ""
    created_order_short = ""

    page = browser_context.new_page()

    # -----------------------------------------------------------------------
    # STEP 1: Login as dev user (customer by default)
    # -----------------------------------------------------------------------
    _login(page)

    # Clean cart and create a new reusable address in customer settings
    _switch_role(page, "customer")
    _clear_cart_after_login(page)
    _clear_addresses_after_login(page)
    _create_and_select_new_address(page, address_label, address_line1)

    # -----------------------------------------------------------------------
    # STEP 2: Switch role to Seller via Settings
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")

    # -----------------------------------------------------------------------
    # STEP 3: Navigate to Seller Panel, create a product (stock=2, price=3.99)
    # -----------------------------------------------------------------------
    page.get_by_role("link", name="Dashboard").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Inventory page
    page.get_by_role("link", name="Inventory", exact=True).click()
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

    page.locator("button:has-text('OK')").click()

    product_row = _find_table_row_across_pages(page, product_name)

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

    page.locator("button:has-text('OK')").click()

    updated_row = _find_table_row_across_pages(page, updated_name)

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
    page.get_by_role("link", name="Catalog", exact=True).click()
    page.wait_for_selector("input[placeholder='Apple, Milk...']")
    page.locator("input[placeholder='Apple, Milk...']").fill(updated_name)
    page.wait_for_selector(f"a:has(h3:has-text('{updated_name}'))")

    # Verify price is visible
    assert "4.49" in page.inner_text("body")

    # -----------------------------------------------------------------------
    # STEP 7: Open product detail, verify stock, add 1 to cart
    # -----------------------------------------------------------------------
    page.locator(f"a:has(h3:has-text('{updated_name}'))").click()
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

    # Explicitly select the new address created in Settings
    page.locator(
        f"xpath=//div[contains(@class,'cursor-pointer')][.//*[contains(normalize-space(),'{address_label}')]][.//*[contains(normalize-space(),'{address_line1}')]]"
    ).click()

    page.locator("button:has-text('Place Secure Order')").click()

    page.wait_for_selector(".fixed.inset-0")
    created_order_id = _extract_order_id_from_dialog(page)
    created_order_short = created_order_id[:8]
    page.get_by_role("button", name="OK", exact=True).click()
    page.wait_for_selector("h1:has-text('Your Orders')")

    placed_row = _order_row_by_short_id(page, created_order_short)
    assert "placed" in placed_row.inner_text().lower()
    _open_customer_order_details(page, created_order_short)
    assert updated_name in page.inner_text("body")

    # -----------------------------------------------------------------------
    # STEP 9: Verify stock is now 1 on product detail
    # -----------------------------------------------------------------------
    page.get_by_role("link", name="Catalog", exact=True).click()
    page.wait_for_selector("input[placeholder='Apple, Milk...']")
    page.locator("input[placeholder='Apple, Milk...']").fill(updated_name)
    page.wait_for_selector(f"a:has(h3:has-text('{updated_name}'))")
    page.locator(f"a:has(h3:has-text('{updated_name}'))").click()
    page.wait_for_selector("button:has-text('Add to Cart')")
    assert "1" in page.inner_text("body")

    # -----------------------------------------------------------------------
    # STEP 10: Switch to Seller -> advance order: placed -> packed
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")
    page.get_by_role("link", name="Dashboard").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Fulfillment Queue
    page.get_by_role("link", name="Fulfillment Queue", exact=True).click()
    page.wait_for_selector("h1:has-text('Fulfillment Queue')")
    _advance_order_status_in_fulfillment(
        page,
        created_order_short,
        action_label="Mark Packed",
        next_label="Mark Out for Delivery",
    )

    # -----------------------------------------------------------------------
    # STEP 11: Switch to Customer -> verify order is packed
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")
    page.locator("a[href='/orders']").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    packed_row = _order_row_by_short_id(page, created_order_short)
    assert "packed" in packed_row.inner_text().lower()

    # -----------------------------------------------------------------------
    # STEP 12: Switch to Seller -> packed -> out_for_delivery
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")
    page.get_by_role("link", name="Dashboard").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Fulfillment Queue
    page.get_by_role("link", name="Fulfillment Queue", exact=True).click()
    page.wait_for_selector("h1:has-text('Fulfillment Queue')")
    _advance_order_status_in_fulfillment(
        page,
        created_order_short,
        action_label="Mark Out for Delivery",
        next_label="Mark Delivered",
    )

    # -----------------------------------------------------------------------
    # STEP 13: Switch to Customer -> verify out_for_delivery
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")
    page.locator("a[href='/orders']").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    out_row = _order_row_by_short_id(page, created_order_short)
    assert "out for delivery" in out_row.inner_text().lower()

    # -----------------------------------------------------------------------
    # STEP 14: Switch to Seller -> out_for_delivery -> delivered
    # -----------------------------------------------------------------------
    _switch_role(page, "seller")
    page.get_by_role("link", name="Dashboard").click()
    page.wait_for_selector("h1:has-text('Seller Dashboard')")

    # Navigate to Fulfillment Queue
    page.get_by_role("link", name="Fulfillment Queue", exact=True).click()
    page.wait_for_selector("h1:has-text('Fulfillment Queue')")
    _advance_order_status_in_fulfillment(
        page,
        created_order_short,
        action_label="Mark Delivered",
        next_label=None,
    )

    # -----------------------------------------------------------------------
    # STEP 15: Switch to Customer -> verify delivered
    # -----------------------------------------------------------------------
    _switch_role(page, "customer")
    page.locator("a[href='/orders']").click()
    page.wait_for_selector("h1:has-text('Your Orders')")
    delivered_row = _order_row_by_short_id(page, created_order_short)
    assert "delivered" in delivered_row.inner_text().lower()

    # Submit rating for the delivered order item
    _open_customer_order_details(page, created_order_short)
    item_row = page.locator(
        f"xpath=//div[contains(@class,'md:flex-row') and contains(@class,'justify-between')][.//p[contains(normalize-space(),'{updated_name}')]]"
    )
    item_row.wait_for(state="visible")

    star_buttons = item_row.locator("button:has(svg.lucide-star)")
    star_count = star_buttons.count()
    assert star_count >= 5, "Expected rating star buttons for delivered item"
    star_buttons.nth(star_count - 1).click()

    comment_input = item_row.locator("input[placeholder='Add comments (optional)']")
    comment_input.fill(rating_comment)
    item_row.get_by_role("button", name="Submit Review", exact=True).click()
    page.wait_for_selector("text=Rated 5 Stars")

    # -----------------------------------------------------------------------
    # STEP 16: Order the last 1 item -> verify Out of Stock
    # -----------------------------------------------------------------------
    page.get_by_role("link", name="Catalog", exact=True).click()
    page.wait_for_selector("input[placeholder='Apple, Milk...']")
    page.locator("input[placeholder='Apple, Milk...']").fill(updated_name)
    page.wait_for_selector(f"a:has(h3:has-text('{updated_name}'))")
    page.locator(f"a:has(h3:has-text('{updated_name}'))").click()
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

    page.locator(
        f"xpath=//div[contains(@class,'cursor-pointer')][.//*[contains(normalize-space(),'{address_label}')]][.//*[contains(normalize-space(),'{address_line1}')]]"
    ).click()
    page.locator("button:has-text('Place Secure Order')").click()
    page.wait_for_selector(".fixed.inset-0")
    page.locator("button:has-text('OK')").click()
    page.wait_for_selector("h1:has-text('Your Orders')")

    # Go back to product detail; it should now show Out of Stock
    page.get_by_role("link", name="Catalog", exact=True).click()
    page.wait_for_selector("input[placeholder='Apple, Milk...']")
    page.locator("input[placeholder='Apple, Milk...']").fill(updated_name)
    page.wait_for_selector(f"a:has(h3:has-text('{updated_name}'))")
    page.locator(f"a:has(h3:has-text('{updated_name}'))").click()
    page.wait_for_selector("h1")

    assert "Out of stock" in page.inner_text("body")
    assert page.locator("button:has-text('Add to Cart')").count() == 0
    page.wait_for_selector(f"text={rating_comment}")

    # -----------------------------------------------------------------------
    # STEP 17: Cleanup (Clear Cart and Addresses)
    # -----------------------------------------------------------------------
    _clear_cart_after_login(page)
    _clear_addresses_after_login(page)

    # -----------------------------------------------------------------------
    # STEP 18: Logout
    # -----------------------------------------------------------------------
    page.locator("header button#logout-btn").click()
    page.wait_for_selector("h1:has-text('GroceryGenie')")

    page.close()
