# server.py
from mcp.server.fastmcp import FastMCP
import subprocess
import os
import time
import base64

# Create an MCP server
mcp = FastMCP("Demo")

# ADB_PATH = os.path.expanduser("~/.android-sdk/platform-tools/adb")

ANDROID_HOME = os.path.expanduser("~/.android-sdk")
adb_env = os.environ.copy()
adb_env["PATH"] = f"{ANDROID_HOME}/platform-tools:{adb_env['PATH']}"

@mcp.tool()
def return_count_adb_devices():
    result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, env=adb_env)
    return len(result.stdout.splitlines()) - 2

@mcp.tool()
def get_app_list():
    result = subprocess.run(["adb", "shell", "cmd", "package", "query-activities", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"], capture_output=True, text=True, env=adb_env)
    return result.stdout.splitlines()

@mcp.tool()
def launch_app(package_name: str):
    activity_result = subprocess.run(["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package_name], capture_output=True, text=True, env=adb_env)
    activity = activity_result.stdout.strip().splitlines()[-1]
    result = subprocess.run(["adb", "shell", "am", "start", "-W", "-n", f'{package_name}/{activity}'], capture_output=True, text=True, env=adb_env)
    return result.stdout.splitlines()

@mcp.tool()
def type_text(text: str):
    result = subprocess.run(["adb", "shell", "input", "text", text], capture_output=True, text=True, env=adb_env)
    return result.stdout.splitlines(), screenshot_emulator()

@mcp.tool()
def press_key(key: str):
    button_map = {
        "BACK": "KEYCODE_BACK",
        "HOME": "KEYCODE_HOME",
        "VOLUME_UP": "KEYCODE_VOLUME_UP",
        "VOLUME_DOWN": "KEYCODE_VOLUME_DOWN",
        "ENTER": "KEYCODE_ENTER",
        "DPAD_CENTER": "KEYCODE_DPAD_CENTER",
        "DPAD_UP": "KEYCODE_DPAD_UP",
        "DPAD_DOWN": "KEYCODE_DPAD_DOWN",
        "DPAD_LEFT": "KEYCODE_DPAD_LEFT",
        "DPAD_RIGHT": "KEYCODE_DPAD_RIGHT",
    }
    result = subprocess.run(["adb", "shell", "input", "keyevent", button_map[key]], capture_output=True, text=True, env=adb_env)
    return result.stdout.splitlines(), screenshot_emulator()

#@mcp.tool()
def screenshot_emulator():
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    local_path = f"/tmp/android_screen_{timestamp}.png"
    remote_path = "/sdcard/screen.png"

    subprocess.run(["adb", "shell", "screencap", "-p", remote_path], env=adb_env)
    subprocess.run(["adb", "pull", remote_path, local_path], env=adb_env)
    
    with open(local_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    
    return {
        "file_path": local_path,
        "base64_image": encoded
    }

#should get screenshot be a tool or a resource?
#resource is better because it can be used by multiple tools
