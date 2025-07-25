import subprocess
import sys

def detect_DOS() -> bool:
    """Return True if no crash or ANR detected, False otherwise."""
    logs = adb(["adb", "logcat", "-d"])
    return "FATAL EXCEPTION" not in logs and "ANR in" not in logs


def check_container_health(container_name: str) -> bool:
    """Return True if the container health status is 'healthy', False otherwise."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name],
            capture_output=True,
            text=True,
            check=True
        )
        health_status = result.stdout.strip()
        return health_status == "healthy"
    except subprocess.CalledProcessError:
        print(f"Error: Could not inspect container '{container_name}'. Is it running?", file=sys.stderr)
        return False
