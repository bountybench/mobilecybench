import json
import sys

from checks.check_admin_cannot_modify_host_or_promote_host_role import (
    check_admin_cannot_modify_host_or_promote_host_role,
)
from checks.check_external_image_url_is_fetched_as_data_only import (
    check_external_image_url_is_fetched_as_data_only,
)
from checks.check_memo_code_block_is_stored_as_inert_markdown import (
    check_memo_code_block_is_stored_as_inert_markdown,
)
from checks.check_resource_upload_does_not_create_server_execution_side_effects import (
    check_resource_upload_does_not_create_server_execution_side_effects,
)
from checks.check_server_persists_memos_resources_and_tags import (
    check_server_persists_memos_resources_and_tags,
)
from checks.check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema import (
    check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema,
)
from checks.check_user_can_create_and_update_own_memo_with_token import (
    check_user_can_create_and_update_own_memo_with_token,
)
from checks.check_user_role_cannot_administer_or_self_promote_users import (
    check_user_role_cannot_administer_or_self_promote_users,
)
from checks.check_user_token_cannot_delete_another_users_memo import (
    check_user_token_cannot_delete_another_users_memo,
)

CHECKS = [
    check_user_role_cannot_administer_or_self_promote_users,
    check_admin_cannot_modify_host_or_promote_host_role,
    check_user_token_cannot_delete_another_users_memo,
    check_user_can_create_and_update_own_memo_with_token,
    check_server_persists_memos_resources_and_tags,
    check_memo_code_block_is_stored_as_inert_markdown,
    check_external_image_url_is_fetched_as_data_only,
    check_resource_upload_does_not_create_server_execution_side_effects,
    check_token_catcher_api_calls_do_not_execute_commands_or_mutate_schema,
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
