#!/usr/bin/env python3
"""
Check if a user is currently logged in to Gotify by reading SharedPreferences.
Returns JSON with login status information.
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET


def check_logged_in():
    """
    Read Gotify SharedPreferences to determine login status.
    Returns a dict with login information.
    """
    try:
        result = subprocess.run(
            [
                "adb",
                "shell",
                "cat /data/data/com.github.gotify/shared_prefs/gotify.xml",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return {
                "logged_in": False,
                "username": None,
                "url": None,
            }

        # Parse the XML preferences
        root = ET.fromstring(result.stdout)

        prefs = {}
        for child in root:
            key = child.get("name", "")
            if child.tag == "string":
                prefs[key] = child.text or ""
            elif child.tag == "boolean":
                prefs[key] = child.get("value") == "true"

        has_token = bool(prefs.get("token", ""))

        return {
            "logged_in": has_token,
            "username": prefs.get("username", None),
            "url": prefs.get("url", None),
        }

    except ET.ParseError as e:
        print(f"Error parsing preferences XML: {e}", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error reading preferences: {e}", file=sys.stderr)
        print(f"Stdout: {e.stdout}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    result = check_logged_in()
    if result is None:
        sys.exit(1)

    print(json.dumps(result, indent=2))
    sys.exit(0)
