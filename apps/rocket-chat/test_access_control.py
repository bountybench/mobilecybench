import subprocess
import sys

def launch_app():
    result = subprocess.run(
        ["adb", "shell", "monkey", "-p", "chat.rocket.reactnative", "-c", "android.intent.category.LAUNCHER", "1"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and "Error" not in result.stderr:
        print("App started successfully", file=sys.stderr)
        return True
    else:
        print("Could not launch app", file=sys.stderr)
        return False

if __name__ == "__main__":
    app_launch = launch_app()
    if app_launch:
        print("[PASS] App is running", file=sys.stderr)
        sys.exit(0)
    else:
        print("[FAIL] App failed to start", file=sys.stderr)
        sys.exit(1)
