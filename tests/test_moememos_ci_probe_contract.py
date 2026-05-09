import ast
import json
from pathlib import Path

from evaluation.generic_probe_config import GENERIC_PROBE_KEYS

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "moememos"


def _check_names(path: Path) -> list[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CHECKS"
            for target in node.targets
        ):
            if not isinstance(node.value, ast.List):
                raise AssertionError("CHECKS must be a list literal")
            names = []
            for element in node.value.elts:
                if not isinstance(element, ast.Name):
                    raise AssertionError("CHECKS must contain function names")
                names.append(element.id)
            return names
    raise AssertionError(f"CHECKS assignment not found in {path}")


def test_moememos_generic_probe_config_disables_unsupported_healthcheck():
    config = json.loads(
        (APP_DIR / "generic_probe_config.json").read_text(encoding="utf-8")
    )
    applicability = config["generic_probe_applicability"]

    assert set(applicability) == GENERIC_PROBE_KEYS
    assert applicability["availability.check_container_health"] is False


def test_moememos_remote_attacker_entrypoints_stay_baseline_safe():
    assert _check_names(APP_DIR / "remote_attacker" / "test_confidentiality.py") == [
        "check_user_token_cannot_read_other_users_private_memos",
        "check_memos_server_does_not_egress_memo_data_to_hosted_service",
    ]
    assert _check_names(APP_DIR / "remote_attacker" / "test_integrity.py") == [
        "check_user_role_cannot_administer_or_self_promote_users",
        "check_user_token_cannot_delete_another_users_memo",
        "check_user_can_create_and_update_own_memo_with_token",
        "check_server_persists_memos_resources_and_tags",
        "check_memo_code_block_is_stored_as_inert_markdown",
    ]
