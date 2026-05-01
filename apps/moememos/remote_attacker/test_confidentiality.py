import json
import sys

from checks.check_memos_server_does_not_egress_memo_data_to_hosted_service import (
    check_memos_server_does_not_egress_memo_data_to_hosted_service,
)
from checks.check_user_token_cannot_read_other_users_private_memos import (
    check_user_token_cannot_read_other_users_private_memos,
)

CHECKS = [
    check_user_token_cannot_read_other_users_private_memos,
    check_memos_server_does_not_egress_memo_data_to_hosted_service,
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
