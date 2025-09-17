import argparse
import asyncio
import sys

from get_llat_from_token import login_with_llat
from playwright.async_api import TimeoutError as PWTimeoutError
from playwright.async_api import async_playwright


def parse_args():
    parser = argparse.ArgumentParser(description="Home Assistant login script")
    parser.add_argument("--username", required=True, help="username")
    parser.add_argument("--password", required=True, help="password")
    parser.add_argument(
        "--hostname", required=True, help="Host address where HA is running"
    )

    return parser.parse_args()


async def fill_field(locator, value: str, label: str):
    try:
        await locator.fill(value)
        return True
    except Exception as e:
        print(f"(debug) Failed to fill {label} via direct fill: {e}; trying JS set.")
        try:
            handle = await locator.element_handle()
            if handle:
                await handle.evaluate(
                    "(el, val) => { el.value = val; el.dispatchEvent(new Event('input', {bubbles:true})); }",
                    value,
                )
                return True
        except Exception as e2:
            print(f"(debug) JS set failed for {label}: {e2}")
    return False


async def login(page, hostname, username, password):
    print("Navigating to login page ...")
    await page.goto(f"http://{hostname}:8123", wait_until="load")

    try:
        await page.wait_for_selector("ha-sidebar", timeout=3000)
        print("Already authenticated (sidebar detected).")
        return
    except PWTimeoutError:
        pass

    try:
        provider_item = await page.wait_for_selector(
            "mwc-list-item, ha-list-item, .provider-list mwc-list-item", timeout=4000
        )
        if provider_item:
            items = await page.locator("mwc-list-item, ha-list-item").all()
            chosen = False
            for it in items:
                text = (await it.inner_text()).lower()
                if any(k in text for k in ["home", "local", "assistant"]):
                    await it.click()
                    chosen = True
                    break
            if not chosen:
                await provider_item.click()
            await page.wait_for_timeout(500)
    except PWTimeoutError:
        pass

    username_field = None
    password_field = None
    attempts = 3
    for attempt in range(1, attempts + 1):
        username_locators = [
            page.get_by_label("Username"),
            page.locator("input#username"),
            page.locator("input[name=username]"),
            page.locator("mwc-textfield#username"),
            page.locator("ha-auth-flow input#username"),
        ]
        password_locators = [
            page.get_by_label("Password"),
            page.locator("input#password"),
            page.locator("input[type=password]"),
            page.locator("mwc-textfield#password"),
            page.locator("ha-auth-flow input#password"),
        ]

        async def first_visible(locators):
            for loc in locators:
                try:
                    await loc.wait_for(timeout=1500)
                    return loc
                except Exception:
                    continue
            return None

        username_field = await first_visible(username_locators)
        password_field = await first_visible(password_locators)
        if username_field and password_field:
            break
        else:
            print(
                f"(debug) Login fields not ready (attempt {attempt}/{attempts}); retrying..."
            )
            await page.wait_for_timeout(1000)

    if not username_field or not password_field:
        print("Could not locate login input fields after retries.")
        raise RuntimeError("Login fields not found")

    if not await fill_field(username_field, username, "username"):
        raise RuntimeError("Failed to set username")
    if not await fill_field(password_field, password, "password"):
        raise RuntimeError("Failed to set password")

    await password_field.press("Enter")

    # Wait for either successful login or error
    try:
        await page.wait_for_selector("ha-sidebar", timeout=10000)
        print("Login successful - dashboard loaded")
    except PWTimeoutError:
        print("Login may have failed - no dashboard detected")
        # Check for error messages
        error = await page.locator(
            ".error, .alert-error, [role=alert]"
        ).first.inner_text(timeout=1000)
        print(f"Login error: {error}")


async def extract_access_token(captured_tokens):
    for _, token_data in captured_tokens.items():
        if "access_token" in token_data:
            return token_data["access_token"]
    return None


async def main(args):

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Set up request/response interception to capture auth tokens
        captured_tokens = {}

        async def handle_response(response):
            # Capture access token from auth endpoint
            if "/auth/token" in response.url:
                try:
                    json_data = await response.json()
                    if "access_token" in json_data:
                        captured_tokens[response.url] = json_data
                        print(f"Captured access token from {response.url}")
                except Exception:
                    pass

        page.on("response", handle_response)

        await login(page, args.hostname, args.username, args.password)

        # Wait a bit to ensure all network requests are complete
        await page.wait_for_timeout(2000)

        # Extract just the access token
        access_token = await extract_access_token(captured_tokens)

        await browser.close()
        return access_token


def retrieve_llat(hostname: str, username: str, password: str) -> str | None:
    """
    Retrieve a Long-Lived Access Token (LLAT) for Home Assistant.

    Args:
        hostname: Host address where HA is running
        username: Username for login
        password: Password for login

    Returns:
        The LLAT string if successful, None if failed
    """

    # Create a simple args object
    class Args:
        def __init__(self, hostname, username, password):
            self.hostname = hostname
            self.username = username
            self.password = password

    args = Args(hostname, username, password)

    try:
        access_token = asyncio.run(main(args))
        if access_token:
            llat = login_with_llat(args.hostname, access_token)
            return llat
        else:
            return None
    except Exception as e:
        print(f"Error retrieving LLAT: {e}")
        return None


if __name__ == "__main__":
    args = parse_args()
    access_token = asyncio.run(main(args))

    if access_token:
        print(f"\nAccess token: {access_token}")
        print("Now retrieving LLAT via WebSocket...")
        llat = login_with_llat(args.hostname, access_token)
        if llat:
            print(f"LLAT created successfully: {llat}")
        else:
            print("Failed to create LLAT")
    else:
        print("Failed to obtain access token")
        sys.exit(1)
