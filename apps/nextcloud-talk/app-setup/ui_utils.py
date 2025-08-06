import sys
import uiautomator2 as u2


def click_by_resource_id(device, resource_id):
    el = device(resourceId=resource_id)
    if el.exists():
        el.click()
        print(f"Clicked element with resource-id: {resource_id}")
    else:
        print(f"Element with resource-id {resource_id} not found.")


def click_by_desc(device, content_desc):
    el = device(description=content_desc)
    if el.exists():
        el.click()
        print(f"Clicked element with content-desc: {content_desc}")
    else:
        print(f"Element with content-desc {content_desc} not found.")


def click_by_text(device, text):
    el = device(text=text)
    # time.sleep(2)
    if el.exists():
        el.click()
        print(f"Clicked element with text: {text}")
    else:
        print(f"Element with text {text} not found.")


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
        click_by_resource_id(d, value)
    elif action == "click_desc":
        click_by_desc(d, value)
    elif action == "click_text":
        click_by_text(d, value)
    else:
        print(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
