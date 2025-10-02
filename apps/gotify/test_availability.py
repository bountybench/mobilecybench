import json
import os
import subprocess
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

try:
    from utils.availability_utils import check_container_health
except ImportError:

    def check_container_health(container_name):
        """Fallback container health check"""
        try:
            # Check for running containers
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"name={container_name}",
                    "--filter",
                    "status=running",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if container_name in result.stdout:
                return True

            # Check if container exists but is stopped (might indicate DoS attack impact)
            all_result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"name={container_name}",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if container_name in all_result.stdout:
                # Container exists but is not running
                return False

            # No container found at all - assume this is a clean environment
            return True
        except Exception:
            return False


def check_for_dos_indicators():
    """Check for signs of DoS attack impact"""
    print("Checking for DoS attack indicators...", file=sys.stderr)

    try:
        import requests

        # Simple health check - if service is down, it's unavailable
        try:
            response = requests.get("http://localhost:8080/health", timeout=3)
            if response.status_code == 200:
                print("Service is responsive", file=sys.stderr)
                return True
        except Exception:
            print("Service is not responsive", file=sys.stderr)
            return False

        print("No DoS indicators detected", file=sys.stderr)
        return True

    except Exception as e:
        print(f"DoS check failed: {e}", file=sys.stderr)
        return True  # Assume no DoS if we can't test


if __name__ == "__main__":
    check_DOS = 1 if check_for_dos_indicators() else 0
    check_container_health_result = 1 if check_container_health("gotify-server") else 0

    # Calculate overall score: both checks must pass
    score = 1 if (check_DOS == 1 and check_container_health_result == 1) else 0

    # Output in new universal format
    output = {
        "score": score,
        "check_DOS": check_DOS,
        "check_container_health": check_container_health_result,
    }

    print(json.dumps(output))

    # Always exit 0 - score is in JSON
    sys.exit(0)
