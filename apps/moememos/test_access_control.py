import json
import sys

from checks.check_declared_shortcut_intents_launch_only_expected_routes import (
    check_declared_shortcut_intents_launch_only_expected_routes,
)
from checks.check_malicious_app_cannot_browse_fileprovider_without_grant import (
    check_malicious_app_cannot_browse_fileprovider_without_grant,
)
from checks.check_malicious_app_entrypoints_match_declared_routes import (
    check_malicious_app_entrypoints_match_declared_routes,
)
from checks.check_malicious_app_fileprovider_grant_is_exact_uri_only import (
    check_malicious_app_fileprovider_grant_is_exact_uri_only,
)

CHECKS = [
    check_malicious_app_fileprovider_grant_is_exact_uri_only,
    check_malicious_app_cannot_browse_fileprovider_without_grant,
    check_malicious_app_entrypoints_match_declared_routes,
    check_declared_shortcut_intents_launch_only_expected_routes,
]


def main() -> int:
    results: dict[str, int] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            success, message = fn()
        except Exception as e:  # noqa: BLE001
            success = False
            message = f"infra error: {e!r}"
        prefix = "[PASS]" if success else "[FAIL]"
        print(f"{prefix} {fn.__name__}: {message}", file=sys.stderr)
        results[fn.__name__] = 1 if success else 0
        overall_secure = overall_secure and success
    results_with_score = {"score": 1 if overall_secure else 0, **results}
    print(json.dumps(results_with_score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
