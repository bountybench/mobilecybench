import uuid
import xml.etree.ElementTree as ET
from typing import Dict, List

from docker_setup import HOST_ADB_SERVER, get_kali


def run_adb_shell(command: str) -> str:
    """
    Runs ADB shell commands for better seeing the screen state
    """
    container = get_kali()
    cmd = f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb shell {command}"
    result = container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)
    return result.output.decode("utf-8")


def run_adb_pull(remote_path: str, local_path: str) -> bool:
    """
    Copies emulator files in a remote path to a local path.
    """
    container = get_kali()
    cmd = (
        f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb shell cat {remote_path}"
    )
    result = container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)
    output = result.output
    if result.exit_code != 0 or not output:
        print("ADB pull failed.")
        return False
    with open(local_path, "wb") as f:
        f.write(output)
    return True


def calculate_location(bounds):
    """
    Generates the location for an element so that the agent knows where to click
    """
    try:
        points = [
            int(num)
            for num in bounds.replace("[", "").replace("]", ",").split(",")
            if num.strip().isdigit()
        ]
        x = (points[0] + points[2]) // 2
        y = (points[1] + points[3]) // 2
        return [x, y]
    except Exception:
        return [0, 0]


class UIElement:
    """
    Each element on the emulator screen is a UI element.
    """

    def __init__(
        self,
        index: int,
        text: str = "",
        resource_id: str = "",
        class_name: str = "",
        package: str = "",
        content_desc: str = "",
        fields: Dict[str, bool] = None,
        bounds: str = "",
    ):
        self.id = str(uuid.uuid4())
        self.index = index
        self.text = text
        self.resource_id = resource_id
        self.class_name = class_name
        self.package = package
        self.content_desc = content_desc
        self.fields = fields
        self.bounds = bounds
        self.location = calculate_location(bounds)

    def to_dict(self):
        return {
            "id": self.id,
            "index": self.index,
            "text": self.text,
            "resource_id": self.resource_id,
            "class_name": self.class_name,
            "package": self.package,
            "content_desc": self.content_desc,
            "fields": self.fields,
            "bounds": self.bounds,
            "location": self.location,
        }


def obtain_UI_elements() -> List[UIElement]:
    """
    This collects a UI dump of all the elements in the android emulator for agentic use.
    """
    remote_path = "/sdcard/window_dump.xml"
    local_path = "window_dump.xml"

    run_adb_shell(f"uiautomator dump {remote_path}")
    if not run_adb_pull(remote_path, local_path):
        return []

    try:
        tree = ET.parse(local_path)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing XML: {e}")
        return []

    ui_elements = []
    for node in root.iter("node"):
        fields = {
            "checkable": node.get("checkable") == "true",
            "checked": node.get("checked") == "true",
            "clickable": node.get("clickable") == "true",
            "enabled": node.get("enabled") == "true",
            "focusable": node.get("focusable") == "true",
            "focused": node.get("focused") == "true",
            "scrollable": node.get("scrollable") == "true",
            "long-clickable": node.get("long-clickable") == "true",
            "password": node.get("password") == "true",
            "selected": node.get("selected") == "true",
        }
        ui_elements.append(
            UIElement(
                index=node.get("index"),
                text=node.get("text"),
                resource_id=node.get("resource-id"),
                class_name=node.get("class"),
                package=node.get("package"),
                content_desc=node.get("content-desc"),
                fields=fields,
                bounds=node.get("bounds"),
            )
        )
    return ui_elements


def get_ui_state() -> dict:
    """Get current UI state with all interactive elements"""
    ui_elements = obtain_UI_elements()
    return {"ui_elements": [el.to_dict() for el in ui_elements]}
