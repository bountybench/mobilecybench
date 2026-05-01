"""OpenHAB remote-attacker integrity probe entrypoint."""

import json
import sys
from pathlib import Path
from typing import Callable, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from remote_attacker.checks.check_app_private_persistence_consistency import (  # noqa: E402
    check_app_private_persistence_consistency,
)
from remote_attacker.checks.check_jsondb_user_functional_consistency import (  # noqa: E402
    check_jsondb_user_functional_consistency,
)
from remote_attacker.checks.check_runtime_mount_topology import (  # noqa: E402
    check_runtime_mount_topology,
)
from remote_attacker.checks.check_sitemap_live_vs_mounted_consistency import (  # noqa: E402
    check_sitemap_live_vs_mounted_consistency,
)

CheckFn = Callable[[], Tuple[bool, str]]

CHECKS: list[CheckFn] = [
    check_jsondb_user_functional_consistency,
    check_sitemap_live_vs_mounted_consistency,
    check_runtime_mount_topology,
    check_app_private_persistence_consistency,
]


def main() -> int:
    results: dict[str, int] = {}
    overall_secure = True
    for fn in CHECKS:
        try:
            success, message = fn()
        except Exception as e:
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
