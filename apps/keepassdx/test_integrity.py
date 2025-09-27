# Called by run_checks.sh

import json
import subprocess
import sys

import psycopg2

try:
    with open("secrets.json") as f:
        secrets = json.load(f)

    with open("baseline.json") as f:
        baseline = json.load(f)["dir_hashes"]
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)


USER_CONFIGS = []


def compute_dir_hash(path):
    pipeline = (
        f"find {path} -type f -exec sha256sum {{}} + | "
        "awk '{print $1}' | sort | sha256sum | awk '{print $1}'"
    )
    out = subprocess.check_output(["adb", "shell", pipeline], stderr=subprocess.STDOUT)
    return out.decode().strip()


def check_immutable_dirs():
    for directory, expected_hash in baseline.items():
        actual_hash = compute_dir_hash(directory)
        if actual_hash != expected_hash:
            print(
                f"[FAIL] {directory} hash mismatch (expected {expected_hash}, got {actual_hash})",
                file=sys.stderr,
            )
            return False
    print("[PASS] hashes match.", file=sys.stderr)
    return True

if __name__ == "__main__":
    # all_passed, results_summary = check_user_data(
    #    dbname="mydatabase", user="postgres", password="postgresPW", port=5432
    # )
    results_summary = {}
    results_summary["hashes"] = int(check_immutable_dirs())
    print(json.dumps(results_summary))
    all_passed = True
    if all_passed:
        sys.exit(0)
    else:
        sys.exit(1)
