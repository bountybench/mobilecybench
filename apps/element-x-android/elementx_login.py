#!/usr/bin/env python3
import argparse
import sys
import time

import uiautomator2 as u2


def parse_args():
    parser = argparse.ArgumentParser(description="Direct Element X Android login")
    parser.add_argument(
        "--server", default="http://10.0.2.2:8008", help="Matrix server URL"
    )
    parser.add_argument("--username", default="agent", help="Matrix username")
    parser.add_argument("--password", default="agentpass", help="Matrix password")
    return parser.parse_args()


def main():
    args = parse_args()

    print("🚀 Direct Element X login starting...", file=sys.stderr)

    try:
        d = u2.connect()

        # Clear app data to ensure fresh start
        print("✅ Clearing app data for fresh login attempt", file=sys.stderr)
        d.app_stop("io.element.android.x.debug")
        d.app_clear("io.element.android.x.debug")
        time.sleep(2)

        # Start app fresh
        d.app_start("io.element.android.x.debug")
        time.sleep(5)  # Wait longer for fresh app startup

        # Check if already logged in
        if d(text="Messages").exists or d(text="Rooms").exists:
            print("✅ Already logged in!", file=sys.stderr)
            return

        # Debug: Check what screen we're starting from
        print("🔍 Checking initial screen state...", file=sys.stderr)

        # Handle different starting screens
        if d(text="You're signed out").exists or d(text="Sign in again").exists:
            print(
                "✅ On 'signed out' screen, clicking 'Sign in again'", file=sys.stderr
            )
            if d(text="Sign in again").exists:
                d(text="Sign in again").click()
                time.sleep(3)
            elif d(text="Sign in").exists:
                d(text="Sign in").click()
                time.sleep(3)
        elif d(text="Sign in manually").exists:
            print("✅ On welcome screen, clicking 'Sign in manually'", file=sys.stderr)
            d(text="Sign in manually").click()
            time.sleep(3)
        elif d(text="Continue").exists and d(text="Get started").exists:
            # Sometimes Element X shows a "Get started" screen first
            print("✅ On get started screen, clicking 'Continue'", file=sys.stderr)
            d(text="Continue").click()
            time.sleep(3)
            # After clicking Continue, look for Sign in manually
            if d(text="Sign in manually").exists:
                print("✅ Now clicking 'Sign in manually'", file=sys.stderr)
                d(text="Sign in manually").click()
                time.sleep(3)
        else:
            # Try to find any sign in related buttons
            sign_in_options = ["Sign in", "Log in", "Continue", "Get started"]
            found_option = False
            for option in sign_in_options:
                if d(text=option).exists:
                    print(f"✅ Found '{option}' button, clicking it", file=sys.stderr)
                    d(text=option).click()
                    time.sleep(3)
                    found_option = True
                    break

            if not found_option:
                print(
                    "⚠️ Unknown starting screen, checking visible elements...",
                    file=sys.stderr,
                )
                try:
                    text_elements = d(className="android.widget.TextView")
                    visible_texts = []
                    for i in range(min(10, text_elements.count)):
                        try:
                            text = text_elements[i].get_text()
                            if text and len(text.strip()) > 0:
                                visible_texts.append(text.strip())
                        except Exception:
                            pass
                    print(f"🔍 Visible texts: {visible_texts[:5]}", file=sys.stderr)
                except Exception as e:
                    print(f"⚠️ Could not analyze screen: {e}", file=sys.stderr)

        # Handle server selection screen
        if d(text="Change account provider").exists:
            print(
                "✅ On server confirmation screen, clicking 'Change account provider'",
                file=sys.stderr,
            )
            d(text="Change account provider").click()
            time.sleep(3)

        # Handle provider selection screen
        if d(text="Other").exists:
            print("✅ On provider selection screen, clicking 'Other'", file=sys.stderr)
            d(text="Other").click()
            time.sleep(3)

        # If on "Find an account provider" screen, enter server directly
        if d(text="Find an account provider").exists:
            print("✅ On provider search screen", file=sys.stderr)
            # Enter server in the search field
            edit_field = d(className="android.widget.EditText")
            if edit_field.exists:
                edit_field.click()
                time.sleep(0.5)
                edit_field.clear_text()
                edit_field.set_text(args.server)
                print(f"✅ Entered server: {args.server}", file=sys.stderr)
                time.sleep(2)

                # Dismiss/zoom out of keyboard to make magnifying glass icon visible
                print(
                    "✅ Dismissing keyboard to reveal magnifying glass icon",
                    file=sys.stderr,
                )
                d.press("back")  # Dismiss keyboard
                time.sleep(2)  # Wait for UI to settle after keyboard dismissal

                # Now look for the magnifying glass icon that should be visible
                print("✅ Looking for magnifying glass icon", file=sys.stderr)
                search_clicked = False

                # Method 1: Look for search icon by description
                search_descriptions = [
                    "Search",
                    "search",
                    "Search icon",
                    "Magnifying glass",
                    "search button",
                ]
                for desc in search_descriptions:
                    if d(description=desc).exists:
                        print(
                            f"✅ Found magnifying glass by description: {desc}",
                            file=sys.stderr,
                        )
                        d(description=desc).click()
                        search_clicked = True
                        break

                if not search_clicked:
                    # Method 2: Look for ImageView/ImageButton elements that could be the magnifying glass
                    print(
                        "🔍 Searching for magnifying glass icon elements",
                        file=sys.stderr,
                    )

                    # Focus on image elements that are most likely to be the search icon
                    search_element_types = [
                        "android.widget.ImageView",
                        "android.widget.ImageButton",
                    ]

                    for elem_type in search_element_types:
                        elements = d(className=elem_type)
                        if elements.exists:
                            print(
                                f"🔍 Found {elements.count} {elem_type} elements after keyboard dismissal",
                                file=sys.stderr,
                            )

                            # Try clicking each image element to see if it's the search icon
                            for i in range(elements.count):
                                try:
                                    element = elements[i]
                                    element_info = element.info
                                    element_bounds = element_info["bounds"]
                                    content_desc = element_info.get(
                                        "contentDescription", ""
                                    )
                                    is_clickable = element_info.get(
                                        "clickable", True
                                    )  # Assume clickable for images

                                    print(
                                        f"🔍 Trying {elem_type}[{i}]: bounds={element_bounds}, "
                                        f"desc='{content_desc}', clickable={is_clickable}",
                                        file=sys.stderr,
                                    )
                                    element.click()
                                    time.sleep(2)

                                    # Check if clicking this element moved us off the search screen
                                    if not d(text="Find an account provider").exists:
                                        print(
                                            f"✅ SUCCESS! {elem_type}[{i}] was the magnifying glass icon!",
                                            file=sys.stderr,
                                        )
                                        search_clicked = True
                                        break
                                    else:
                                        print(
                                            f"⚠️ {elem_type}[{i}] wasn't the search icon",
                                            file=sys.stderr,
                                        )

                                except Exception as e:
                                    print(
                                        f"⚠️ Error clicking {elem_type}[{i}]: {e}",
                                        file=sys.stderr,
                                    )

                            if search_clicked:
                                break

                if not search_clicked:
                    # Method 3: Try ALL clickable elements but avoid the text field area
                    print(
                        "🔍 Trying all clickable elements to find magnifying glass (avoiding text field)",
                        file=sys.stderr,
                    )

                    # Get text field bounds to avoid clicking it
                    edit_bounds = edit_field.info["bounds"]
                    print(f"🔍 Text field to avoid: {edit_bounds}", file=sys.stderr)

                    # Get all clickable elements
                    all_clickable = d(clickable=True)
                    if all_clickable.exists:
                        print(
                            f"🔍 Found {all_clickable.count} clickable elements",
                            file=sys.stderr,
                        )

                        for i in range(
                            min(10, all_clickable.count)
                        ):  # Try first 10 clickable elements
                            try:
                                element = all_clickable[i]
                                element_info = element.info
                                element_bounds = element_info["bounds"]
                                content_desc = element_info.get(
                                    "contentDescription", ""
                                )
                                class_name = element_info.get("className", "")

                                print(
                                    f"🔍 Clickable element {i}: class={class_name}, "
                                    f"bounds={element_bounds}, desc='{content_desc}'",
                                    file=sys.stderr,
                                )

                                # Skip if it's clearly not a search icon
                                if (
                                    element_bounds["top"] < 300
                                ):  # Skip top navigation elements
                                    print(
                                        f"⚠️ Skipping top element {i}", file=sys.stderr
                                    )
                                    continue

                                # Skip if it's the text field itself (avoid re-clicking it)
                                if class_name == "android.widget.EditText" or (
                                    element_bounds["left"] >= edit_bounds["left"] - 10
                                    and element_bounds["right"]
                                    <= edit_bounds["right"] + 10
                                    and element_bounds["top"] >= edit_bounds["top"] - 10
                                    and element_bounds["bottom"]
                                    <= edit_bounds["bottom"] + 10
                                ):
                                    print(
                                        f"⚠️ Skipping text field element {i}",
                                        file=sys.stderr,
                                    )
                                    continue

                                print(
                                    f"✅ Trying clickable element {i}", file=sys.stderr
                                )
                                element.click()
                                time.sleep(3)  # Wait longer for response

                                # Check if keyboard came back (means we clicked the text field accidentally)
                                if d(
                                    className="android.inputmethodservice.Keyboard"
                                ).exists:
                                    print(
                                        f"⚠️ Element {i} brought back keyboard - dismissing again",
                                        file=sys.stderr,
                                    )
                                    d.press("back")
                                    time.sleep(1)
                                    continue

                                # Check if this took us to login or server confirmation
                                if (
                                    d(textContains="You're about to sign in to").exists
                                    or d(text="Username").exists
                                    or d(text="Enter your details").exists
                                ):
                                    print(
                                        f"✅ SUCCESS! Clickable element {i} was the magnifying glass!",
                                        file=sys.stderr,
                                    )
                                    search_clicked = True
                                    break
                                elif not d(text="Find an account provider").exists:
                                    print(
                                        f"✅ Element {i} moved us somewhere - checking if it's progress",
                                        file=sys.stderr,
                                    )
                                    search_clicked = True
                                    break
                                else:
                                    print(f"⚠️ Element {i} didn't work", file=sys.stderr)

                            except Exception as e:
                                print(
                                    f"⚠️ Error clicking element {i}: {e}",
                                    file=sys.stderr,
                                )

                if not search_clicked:
                    # Fallback: precise coordinate clicking outside text field area
                    print(
                        "⚠️ Trying precise coordinate positions for magnifying glass (avoiding text field)",
                        file=sys.stderr,
                    )
                    edit_bounds = edit_field.info["bounds"]

                    # Based on the screenshot, try positions to the LEFT of the text field
                    # The magnifying glass should be clearly to the left, not overlapping with text
                    search_positions = [
                        # Try positions well to the left of the text field
                        (
                            edit_bounds["left"] - 60,
                            edit_bounds["top"]
                            + (edit_bounds["bottom"] - edit_bounds["top"]) // 2,
                        ),  # Far left
                        (
                            edit_bounds["left"] - 40,
                            edit_bounds["top"]
                            + (edit_bounds["bottom"] - edit_bounds["top"]) // 2,
                        ),  # Medium left
                        (
                            edit_bounds["left"] - 80,
                            edit_bounds["top"]
                            + (edit_bounds["bottom"] - edit_bounds["top"]) // 2,
                        ),  # Very far left
                        # Try some fixed positions based on typical search icon placement
                        (
                            60,
                            edit_bounds["top"]
                            + (edit_bounds["bottom"] - edit_bounds["top"]) // 2,
                        ),  # Fixed left position
                        (
                            80,
                            edit_bounds["top"]
                            + (edit_bounds["bottom"] - edit_bounds["top"]) // 2,
                        ),  # Fixed left position 2
                    ]

                    for i, (x, y) in enumerate(search_positions):
                        # Skip positions that might be too close to or inside the text field
                        if x >= edit_bounds["left"] - 20:  # Too close to text field
                            print(
                                f"⚠️ Skipping position {i+1} - too close to text field: ({x}, {y})",
                                file=sys.stderr,
                            )
                            continue

                        print(
                            f"🔍 Trying magnifying glass position {i+1}: ({x}, {y})",
                            file=sys.stderr,
                        )
                        d.click(x, y)
                        time.sleep(3)  # Wait longer for response

                        # Check if keyboard came back (means we accidentally clicked text field area)
                        if d(className="android.inputmethodservice.Keyboard").exists:
                            print(
                                f"⚠️ Position {i+1} brought back keyboard - dismissing",
                                file=sys.stderr,
                            )
                            d.press("back")
                            time.sleep(1)
                            continue

                        # Check if we progressed from the search screen
                        if (
                            d(textContains="You're about to sign in to").exists
                            or d(text="Username").exists
                            or d(text="Enter your details").exists
                        ):
                            print(
                                f"✅ SUCCESS! Position {i+1} found the magnifying glass!",
                                file=sys.stderr,
                            )
                            search_clicked = True
                            break
                        elif not d(text="Find an account provider").exists:
                            print(
                                f"✅ Position {i+1} moved us off search screen",
                                file=sys.stderr,
                            )
                            search_clicked = True
                            break
                        else:
                            print(
                                f"⚠️ Position {i+1} didn't work, still on provider search screen",
                                file=sys.stderr,
                            )

                    if not search_clicked:
                        print("❌ All coordinate attempts failed", file=sys.stderr)

                if search_clicked:
                    print(
                        "✅ Search button clicked, waiting for server confirmation screen",
                        file=sys.stderr,
                    )
                    time.sleep(4)  # Wait a bit longer for the transition

                    # Debug: check what screen we're on now
                    print(
                        "🔍 Checking current screen after magnifying glass click:",
                        file=sys.stderr,
                    )
                    if d(textContains="You're about to sign in to").exists:
                        print(
                            "✅ SUCCESS! Reached server confirmation screen",
                            file=sys.stderr,
                        )
                        # The main logic below will handle the Continue button
                    elif d(text="Find an account provider").exists:
                        print(
                            "⚠️ Still on provider search screen - magnifying glass click didn't work",
                            file=sys.stderr,
                        )
                        # Continue with the existing logic to try other methods
                    elif (
                        d(text="Username").exists or d(text="Enter your details").exists
                    ):
                        print(
                            "✅ Directly reached login form - skipping server confirmation",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            "🔍 Unknown screen after magnifying glass click, checking visible elements:",
                            file=sys.stderr,
                        )
                        try:
                            # Get some visible text to understand current state
                            text_elements = d(className="android.widget.TextView")
                            visible_texts = []
                            for i in range(min(8, text_elements.count)):
                                try:
                                    text = text_elements[i].get_text()
                                    if text and len(text.strip()) > 0:
                                        visible_texts.append(text.strip())
                                except Exception:
                                    pass
                            print(f"🔍 Visible texts: {visible_texts}", file=sys.stderr)
                        except Exception as e:
                            print(
                                f"⚠️ Could not get text elements: {e}", file=sys.stderr
                            )
                else:
                    print("❌ Could not click magnifying glass icon", file=sys.stderr)

        # Handle server confirmation screen - this is crucial step after magnifying glass click
        # Check for Continue button directly since we know it exists from debug output
        if d(text="Continue").exists and d(text="Change account provider").exists:
            print(
                "✅ Found server confirmation screen (Continue + Change account provider buttons)",
                file=sys.stderr,
            )
            print("✅ Found Continue button, clicking it", file=sys.stderr)
            d(text="Continue").click()
            print(
                "✅ Continue button clicked - should proceed to login form",
                file=sys.stderr,
            )
            time.sleep(4)  # Wait longer for login form to load
        elif d(textContains="You're about to sign in").exists:
            print(
                "✅ Found server confirmation screen with 'You're about to sign in'",
                file=sys.stderr,
            )

            # Look for Continue button and click it
            if d(text="Continue").exists:
                print("✅ Found Continue button, clicking it", file=sys.stderr)
                d(text="Continue").click()
                print(
                    "✅ Continue button clicked - should proceed to login form",
                    file=sys.stderr,
                )
                time.sleep(4)  # Wait longer for login form to load
            else:
                print(
                    "❌ Continue button not found on server confirmation screen",
                    file=sys.stderr,
                )
        else:
            print(
                "🔍 Not on server confirmation screen, checking if we're already at login form",
                file=sys.stderr,
            )

        # Wait for and handle login form
        print("⏳ Waiting for login form...", file=sys.stderr)
        for attempt in range(15):  # Try for 15 seconds with better detection
            if d(text="Username").exists:
                print("✅ Found Username field", file=sys.stderr)
                break
            elif d(text="Enter your details").exists:
                print("✅ Found login details prompt", file=sys.stderr)
                break
            elif d(className="android.widget.EditText").count >= 2:
                print("✅ Found login form with 2+ fields", file=sys.stderr)
                break
            time.sleep(1)
        else:
            print("❌ Could not find login form", file=sys.stderr)
            sys.exit(1)

        # Fill username
        edits = d(className="android.widget.EditText")
        if edits.count >= 1:
            username_field = edits[0]
            username_field.click()
            time.sleep(0.5)
            username_field.clear_text()
            username_field.set_text(args.username)
            print("✅ Username entered", file=sys.stderr)

        # Fill password
        if edits.count >= 2:
            password_field = edits[1]
            password_field.click()
            time.sleep(0.5)
            password_field.clear_text()
            password_field.set_text(args.password)
            print("✅ Password entered", file=sys.stderr)

        # Dismiss keyboard after entering password to reveal Continue button
        print("✅ Dismissing keyboard after password entry", file=sys.stderr)
        d.press("back")  # Dismiss keyboard
        time.sleep(2)

        # Trigger form validation to enable Continue button
        print("⏳ Triggering form validation...", file=sys.stderr)
        d.press(66)  # KEYCODE_ENTER
        time.sleep(2)

        # Dismiss keyboard again as form validation may have brought it back
        print("✅ Dismissing keyboard again after form validation", file=sys.stderr)
        d.press("back")  # Dismiss keyboard again
        time.sleep(2)

        # Wait for Continue button to appear and click it
        print("⏳ Looking for Continue button...", file=sys.stderr)
        if d(text="Continue").wait(timeout=10):
            d(text="Continue").click()
            print("✅ Login submitted - waiting for authentication", file=sys.stderr)
            time.sleep(8)  # Wait longer for Matrix server authentication
        else:
            print("❌ Continue button not found", file=sys.stderr)
            sys.exit(1)

        # Check for success or handle post-login screens
        print("⏳ Checking for successful login...", file=sys.stderr)
        for i in range(20):  # Extended timeout for Matrix authentication
            # Check for main app screens
            if (
                d(text="Messages").exists
                or d(text="Rooms").exists
                or d(textContains="Room").exists
            ):
                print("🎉 LOGIN SUCCESSFUL! Reached main app", file=sys.stderr)
                return

            # Handle analytics/telemetry prompt
            if (
                d(text="Help improve Element X").exists
                or d(text="Share anonymous usage data").exists
            ):
                print("✅ Handling analytics prompt", file=sys.stderr)
                if d(text="Not now").exists:
                    d(text="Not now").click()
                    time.sleep(3)
                    continue

            # Check for login errors
            if (
                d(text="Invalid username or password").exists
                or d(text="Login failed").exists
            ):
                print("❌ Login failed - invalid credentials", file=sys.stderr)
                sys.exit(1)

            # Check if still on login screen (authentication failed)
            if d(text="Continue").exists and d(text="Username").exists:
                print(
                    "❌ Still on login screen - authentication may have failed",
                    file=sys.stderr,
                )
                sys.exit(1)

            time.sleep(2)  # Wait longer between checks

        print(
            "⚠️ Login timeout - couldn't verify success after 40 seconds",
            file=sys.stderr,
        )
        print(
            "🔍 This may indicate slow Matrix server response or network issues",
            file=sys.stderr,
        )

    except Exception as e:
        print(f"❌ Login failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
