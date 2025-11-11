import json
import sys

from utils.availability_utils import check_container_health

if __name__ == "__main__":
    results_summary = {}

    # Check health of all critical Funkwhale containers
    results_summary["check_api_health"] = (
        1 if check_container_health("api") else 0
    )
    results_summary["check_front_health"] = (
        1 if check_container_health("front") else 0
    )
    results_summary["check_postgres_health"] = (
        1 if check_container_health("postgres") else 0
    )
    results_summary["check_redis_health"] = (
        1 if check_container_health("redis") else 0
    )

    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome tests failed.", file=sys.stderr)
    else:
        print("\nAll tests passed successfully.", file=sys.stderr)

    sys.exit(0)
