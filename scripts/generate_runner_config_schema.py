#!/usr/bin/env python3
"""Generate ``schemas/runner_config.schema.json`` from ``RunnerConfig``.

The committed schema is the contract `runner_config.json` editors / IDEs
read for autocomplete and hover-docs. Run this script after editing
``models/config.py`` and commit the regenerated file. CI fails if the
two drift (see ``tests/test_runner_config_schema.py``).

    python scripts/generate_runner_config_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.config import RunnerConfig  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "schemas" / "runner_config.schema.json"


def main() -> int:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(RunnerConfig.render_json_schema(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
