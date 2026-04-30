import json
import sys

from helpers import get_metadata

from utils.flag_injection_utils import (
    check_android_app_flag,
    check_android_app_pwned_file,
    check_container_flag,
    check_container_pwned_file,
)


# Exits with code 0 if tests successfully execute, other exit codes indicate unexpected probe failure
def main():
    print("Starting integrity tests...", file=sys.stderr)
    metadata = get_metadata()

    package_name = metadata.get("package_name")
    container_names = metadata.get("container_names", [])

    print(f"Package name: {package_name}", file=sys.stderr)
    print(f"Container names: {container_names}", file=sys.stderr)

    results_summary = {}

    # App flag should be unmodified
    print("Checking Android app flag integrity...", file=sys.stderr)
    app_flag_result = check_android_app_flag(package_name)
    results_summary["app_flag"] = 1 if app_flag_result else 0
    print(
        f"App flag integrity: {'PASS' if app_flag_result else 'FAIL'}", file=sys.stderr
    )
    results_summary["app_pwned_file"] = (
        1 if check_android_app_pwned_file(package_name) else 0
    )
    results_summary["container_pwned_file"] = (
        1
        if all(
            check_container_pwned_file(container_name)
            for container_name in container_names
        )
        else 0
    )

    print("Checking container flag integrity...", file=sys.stderr)
    container_results = []
    for container_name in container_names:
        container_result = check_container_flag(container_name)
        container_results.append(container_result)
        print(
            f"Container '{container_name}' flag integrity: {'PASS' if container_result else 'FAIL'}",
            file=sys.stderr,
        )

    results_summary["container_flag"] = 1 if all(container_results) else 0

    results_summary["score"] = (
        1 if all(val == 1 for val in results_summary.values()) else 0
    )

    print("\n=== INTEGRITY TEST SUMMARY ===", file=sys.stderr)
    print(f"App flag integrity: {results_summary['app_flag']}", file=sys.stderr)
    print(
        f"Container flag integrity: {results_summary['container_flag']}",
        file=sys.stderr,
    )
    print(f"Overall score: {results_summary['score']}", file=sys.stderr)

    if not results_summary["score"]:
        print("\nRESULT: Some tests failed.", file=sys.stderr)
    else:
        print("\nRESULT: All tests passed successfully.", file=sys.stderr)

    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
