import subprocess
import sys


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def check_container_health(container_name: str) -> bool:
    """Return True if the container health status is 'healthy', False otherwise."""
    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        health_status = result.stdout.strip()
        if health_status == "healthy":
            print(f"[PASS] Container '{container_name}' is healthy.", file=sys.stderr)
            return True
        else:
            print(
                f"[FAIL] Container '{container_name}' is not healthy (status: {health_status}).",
                file=sys.stderr,
            )
            return False

    except subprocess.CalledProcessError:
        print(
            f"[ERROR] Could not inspect container '{container_name}'. Is it running?",
            file=sys.stderr,
        )
        return False
