import json
import sys

from utils.availability_utils import check_container_health

if __name__ == "__main__":
    results_summary = {}
    # Use container names from metadata.json for consistency
    with open("metadata.json") as f:
        metadata = json.load(f)
    container_names = metadata.get("container_names", ["joplin-app"])
    
    # Check all containers listed in metadata
    container_health_passed = all(check_container_health(container) for container in container_names)
    results_summary["check_container_health"] = 1 if container_health_passed else 0
    
    # Add overall score (1 if all tests pass, 0 if any fail)
    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0
    
    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome availability tests failed.", file=sys.stderr)
    else:
        print("\nAll availability tests passed successfully.", file=sys.stderr)
    
    # Always exit with 0 for CI compatibility
    sys.exit(0)
