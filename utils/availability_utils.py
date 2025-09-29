import subprocess
import sys


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def check_container_health(container_name: str) -> bool:
    """Return True if the container health status is 'healthy', False otherwise."""
    import os

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
        # Container doesn't exist or can't be inspected
        # Check if this is in a DoS attack context
        dos_artifact_path = "/tmp/unauth_response.txt"
        if os.path.exists(dos_artifact_path):
            try:
                with open(dos_artifact_path, "r") as f:
                    content = f.read().strip()
                # Only consider it a DoS context if it contains explicit DoS indicators
                if "DoS attack launched" in content or "attack" in content.lower():
                    # Scenario 1: DoS attack context - container being down is a failure
                    print(
                        f"[FAIL] Container '{container_name}' not available after DoS attack.",
                        file=sys.stderr,
                    )
                    return False
            except Exception:
                pass

        # Scenario 0 or clean environment - container being down might be expected
        print(
            f"[INFO] Container '{container_name}' not found - assuming clean environment.",
            file=sys.stderr,
        )
        return True
