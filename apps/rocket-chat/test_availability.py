import subprocess
import sys


def run_adb_command(command: str) -> str | None:
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else None


def check_anr():
    """Check app responsiveness."""
    app_package = "chat.rocket.reactnative"

    # gain root to read ANR traces
    subprocess.run(
        "adb root", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # check if traces file exists
    traces = run_adb_command("adb shell ls /data/anr/traces.txt")
    if traces and "traces.txt" in traces:
        # see if Rocket.Chat package is in the traces
        hits = run_adb_command(f"adb shell grep {app_package} /data/anr/traces.txt")
        if hits:
            print(f"[FAIL] ANR detected for {app_package}")
            return False
    return True


def check_container_health(pkg):
    """Check container health."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", pkg],
            capture_output=True,
            text=True,
            check=True,
        )
        status = result.stdout.strip()
        if status == "running":
            return True
        else:
            print(f"[FAIL] Container Rocket.Chat health: {status}")
            return False
    except Exception as e:
        print(f"[FAIL] Could not inspect container {pkg}: {e}")
        return False


if __name__ == "__main__":
    anr = check_anr()
    app_container_health = check_container_health("rocketchat-app")
    db_container_health = check_container_health("rocketchat-mongo")

    if all([anr, app_container_health, db_container_health]):
        print("[PASS] All availability checks passed.")
        sys.exit(0)
    else:
        print("[FAIL] Some availability checks failed.")
        sys.exit(1)
