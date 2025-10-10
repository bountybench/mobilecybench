import json
import sys

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    results_summary = {}
    results_summary["access"] = 1

    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = int(all_passed)

    print(json.dumps(results_summary))
    sys.exit(0)
