import json
import sys

from checks.check_host_and_admin_user_administration_positive_paths import (
    check_host_and_admin_user_administration_positive_paths,
)
from checks.check_token_catcher_is_ordinary_peer_without_privileged_credentials import (
    check_token_catcher_is_ordinary_peer_without_privileged_credentials,
)
from checks.check_unauthenticated_peer_cannot_read_non_public_memos import (
    check_unauthenticated_peer_cannot_read_non_public_memos,
)

CHECKS = [
    check_unauthenticated_peer_cannot_read_non_public_memos,
    check_token_catcher_is_ordinary_peer_without_privileged_credentials,
    check_host_and_admin_user_administration_positive_paths,
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
