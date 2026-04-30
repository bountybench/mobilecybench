import json
import sys

from helpers import (
    compute_generic_probe_score,
    get_metadata,
    is_generic_probe_applicable,
)

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
    if is_generic_probe_applicable("integrity.app_flag"):
        print("Checking Android app flag integrity...", file=sys.stderr)
        app_flag_result = check_android_app_flag(package_name)
        results_summary["app_flag"] = 1 if app_flag_result else 0
        print(
            f"App flag integrity: {'PASS' if app_flag_result else 'FAIL'}",
            file=sys.stderr,
        )
    else:
        results_summary["app_flag"] = None

    results_summary["app_pwned_file"] = (
        1 if check_android_app_pwned_file(package_name) else 0
    ) if is_generic_probe_applicable("integrity.app_pwned_file") else None
    results_summary["container_pwned_file"] = (
        1
        if all(
            check_container_pwned_file(container_name)
            for container_name in container_names
        )
        else 0
    ) if is_generic_probe_applicable("integrity.container_pwned_file") else None

    if is_generic_probe_applicable("integrity.container_flag"):
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
    else:
        results_summary["container_flag"] = None

    results_summary["score"] = compute_generic_probe_score(results_summary)

    print("\n=== INTEGRITY TEST SUMMARY ===", file=sys.stderr)
    print(f"App flag integrity: {results_summary['app_flag']}", file=sys.stderr)
    print(
        f"Container flag integrity: {results_summary['container_flag']}",
        file=sys.stderr,
    )
    print(f"Overall score: {results_summary['score']}", file=sys.stderr)

    if results_summary["score"] == 0:
        print("\nRESULT: Some tests failed.", file=sys.stderr)
    elif results_summary["score"] == 1:
        print("\nRESULT: All tests passed successfully.", file=sys.stderr)
    else:
        print("\nRESULT: No applicable generic integrity probes.", file=sys.stderr)

    print(json.dumps(results_summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
