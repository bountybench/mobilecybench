from mcp.server.fastmcp import FastMCP
import subprocess
import os
import time
import base64
import uuid
from typing import List, Dict, Any
from PIL import Image
import xml.etree.ElementTree as ET
import json

#Create the MCP server
mcp = FastMCP("mcp_emulator")

ANDROID_HOME = os.path.expanduser("~/.android-sdk")
adb_env = os.environ.copy()
adb_env["PATH"] = f"{ANDROID_HOME}/platform-tools:{adb_env['PATH']}"

#Define the classes for communication
def calculate_location(bounds):
    try:
        points = [int(num) for num in bounds.replace("[", "").replace("]", ",").split(",") if num.strip().isdigit()]
        x = (points[0] + points[2]) // 2
        y = (points[1] + points[3]) // 2
        return [x, y]
    except:
        return [0, 0]

class UIElement:
    #all parameters are optional in cases of particular bad UI elements
    def __init__(self, index: int, text: str = "", resource_id: str = "", class_name: str = "", package: str = "", content_desc: str = "", fields: Dict[str, bool] = {}, bounds: str=""):
        self.id = str(uuid.uuid4())
        self.index = index
        self.text = text
        self.resource_id = resource_id
        self.class_name = class_name
        self.package = package
        self.content_desc = content_desc
        self.fields = fields
        self.bounds = bounds
        self.location = calculate_location(self.bounds)

    def __repr__(self):
        return (
            f"UIElement(\n"
            f"  id: {self.id}\n"
            f"  index: {self.index}\n"
            f"  text: '{self.text}'\n"
            f"  resource_id: '{self.resource_id}'\n"
            f"  class_name: '{self.class_name}'\n"
            f"  package: '{self.package}'\n"
            f"  content_desc: '{self.content_desc}'\n"
            f"  fields: {self.fields}\n"
            f"  bounds: '{self.bounds}'\n"
            f"  location: {self.location}\n"
            f")"
        )

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



class EmulatorState:
    def __init__(self, response: str, ui_elements: List[UIElement], img: str):
        self.response = response
        self.ui_elements = ui_elements
        # self.img = img

    def __repr__(self):
        ui_elements_repr = "\n    ".join(repr(el).replace("\n", "\n    ") for el in self.ui_elements)
        return (
            f"EmulatorState(\n"
            f"  response: '{self.response}'\n"
            f"  ui_elements: [\n    {ui_elements_repr}\n  ]\n"
            f")"
        )

    def to_dict(self):
        return {
            "response": self.response,
            "ui_elements": [el.to_dict() for el in self.ui_elements],
            # "img": self.img,
        }

#Responding to any command functions:
def run_command(cmd: str):
    command = cmd.split(" ")
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=adb_env)
        return result
    except subprocess.CalledProcessError as e:
        print(f"{cmd} failed due to {e}")

def run_docker_command(cmd: str):
    docker_command = "docker exec -it kali-container bash -c"
    command = docker_command.split(" ")
    command.append(cmd)
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=adb_env)
        return result
    except subprocess.CalledProcessError as e:
        print(f"{cmd} failed due to {e}")

def obtain_UI_elements() -> List[UIElement]:
    remote_path = "/sdcard/window_dump.xml"
    local_path = "window_dump.xml"
    result = run_command(f'adb shell uiautomator dump {remote_path}')
    result = run_command(f'adb pull {remote_path} {local_path}')
    tree = ET.parse(local_path)
    root = tree.getroot()
    ui_elements = []
    for node in root.iter("node"):
        if node.tag == 'node':
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
            ui_elements.append(UIElement(
                    index=node.get("index"),
                    text=node.get("text"),
                    resource_id=node.get("resource-id"),
                    class_name=node.get("class"),
                    package=node.get("package"),
                    content_desc=node.get("content-desc"),
                    fields=fields,
                    bounds=node.get("bounds")
            ))
    #print(ui_elements[0])
    return ui_elements

def get_ui_state(response_text: str) -> EmulatorState:
    return EmulatorState(response_text, obtain_UI_elements(), obtain_b64_screenshot())

def obtain_b64_screenshot():
    remote_path = "/sdcard/screenshot.png"
    local_path = "screenshot.png"
    run_command(f'adb shell screencap -p {remote_path}')
    run_command(f'adb pull {remote_path} {local_path}')

    with open(local_path, "rb") as f:
        encoded_img = base64.b64encode(f.read()).decode("utf-8")

    # print(encoded_img)
    return encoded_img

def is_json_serializable(obj) -> bool:
    try:
        json.dumps(obj)
        return True
    except (TypeError, OverflowError):
        return False

@mcp.tool(description="Run a command for the android emulator using adb, the terminal, or for the NextCloud server.")
def execute_command(command: str): 
    response = run_docker_command(command)
    return get_ui_state(response.stdout).to_dict()

if __name__ == "__main__":
    mcp.run()
    # response = run_docker_command("adb shell am start -n com.android.mms/com.android.mms.ui.ConversationList")
    # answer = get_ui_state(response.stdout).to_dict()
    # print(is_json_serializable(answer))
    # data = get_ui_state(response.stdout).to_dict()
    # print(json.dumps(data))     