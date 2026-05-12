import json
import sys

from checks.check_malicious_app_cannot_overwrite_settings_pb import (
    check_malicious_app_cannot_overwrite_settings_pb,
)
from checks.check_malicious_image_share_upload_is_route_bound import (
    check_malicious_image_share_upload_is_route_bound,
)
from checks.check_malicious_share_intent_does_not_create_memo_without_post import (
    check_malicious_share_intent_does_not_create_memo_without_post,
)
from checks.check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading import (
    check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading,
)

CHECKS = [
    check_malicious_app_cannot_overwrite_settings_pb,
    check_malicious_share_intent_does_not_create_memo_without_post,
    check_malicious_image_share_upload_is_route_bound,
    check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading,
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
