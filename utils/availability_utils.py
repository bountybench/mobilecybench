import json
import subprocess
import sys


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def check_container_health(container_name: str) -> bool:
    """Return True if a container is healthy, or running without a health check."""
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
            check=True,
        )
        containers = json.loads(result.stdout)
        if not containers:
            print(
                f"[ERROR] Could not inspect container '{container_name}'. Is it running?",
                file=sys.stderr,
            )
            return False

        state = containers[0].get("State", {})
        health = state.get("Health")
        if isinstance(health, dict):
            health_status = health.get("Status", "")
            if health_status == "healthy":
                print(
                    f"[PASS] Container '{container_name}' is healthy.",
                    file=sys.stderr,
                )
                return True
            print(
                f"[FAIL] Container '{container_name}' is not healthy (status: {health_status}).",
                file=sys.stderr,
            )
            return False

        if state.get("Running"):
            print(f"[PASS] Container '{container_name}' is healthy.", file=sys.stderr)
            return True

        container_status = state.get("Status", "unknown")
        print(
            f"[FAIL] Container '{container_name}' is not running (status: {container_status}).",
            file=sys.stderr,
        )
        return False

    except (json.JSONDecodeError, subprocess.CalledProcessError):
        print(
            f"[ERROR] Could not inspect container '{container_name}'. Is it running?",
            file=sys.stderr,
        )
        return False
