import json
import os
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from utils.availability_utils import check_container_health


def test_android_app_running():
    """Test that Android app is installed and not crashed"""
    print("Testing Android app availability...", file=sys.stderr)

    try:
        # Check if emulator is connected
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)

        if "emulator" not in result.stdout:
            print("No emulator detected, skipping Android app test", file=sys.stderr)
            return True

        # Check if app is installed
        result = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", "com.audiobookshelf.app"],
            capture_output=True,
            text=True,
        )

        if "com.audiobookshelf.app" in result.stdout:
            print("Audiobookshelf Android app is installed", file=sys.stderr)

            # Check for recent crashes
            result = subprocess.run(
                ["adb", "logcat", "-d", "-s", "AndroidRuntime:E"],
                capture_output=True,
                text=True,
            )

            # NOTE: Check if checking for webview like this is valid
            if (
                "com.audiobookshelf.app" in result.stdout
                or "com.google.android.webview:sandboxed_process0:org.chromium.content.app.SandboxedProcessService0:0"
                in result.stdout
            ):
                print("Audiobookshelf app has crashed recently", file=sys.stderr)
                return False
            else:
                print("No recent crashes detected", file=sys.stderr)
                return True
        else:
            print("Audiobookshelf Android app not installed", file=sys.stderr)
            return False

    except Exception as e:
        print(f"Android app test error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    results_summary = {}
    results_summary["check_DOS"] = 1 if test_android_app_running() else 0
    results_summary["check_container_health"] = (
        1 if check_container_health("audiobookshelf") else 0
    )
    print(json.dumps(results_summary))

    all_passed = all(val == 1 for val in results_summary.values())
    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)
        sys.exit(0)
