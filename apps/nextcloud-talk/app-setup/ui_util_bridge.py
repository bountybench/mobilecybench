import sys

import uiautomator2 as u2

from utils import ui_utils


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python ui_utils.py <action> <value>")
        print("  Actions: click_id, click_desc, click_text")
        sys.exit(1)

    action = sys.argv[1]
    value = sys.argv[2]

    d = u2.connect()  # automatically connects to device

    if action == "click_id":
        ui_utils.wait_and_click(d, d(resourceId=value), timeout=10)
    elif action == "click_desc":
        ui_utils.wait_and_click(d, d(description=value), timeout=10)
    elif action == "click_text":
        ui_utils.wait_and_click(d, d(text=value), timeout=10)
    else:
        print(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
