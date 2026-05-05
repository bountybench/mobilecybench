import json
import sys

from checks.check_disallowed_malicious_share_mime_does_not_crash_or_hang import (
    check_disallowed_malicious_share_mime_does_not_crash_or_hang,
)
from checks.check_malicious_app_widget_update_receiver_remains_available import (
    check_malicious_app_widget_update_receiver_remains_available,
)

CHECKS = [
    check_malicious_app_widget_update_receiver_remains_available,
    check_disallowed_malicious_share_mime_does_not_crash_or_hang,
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
