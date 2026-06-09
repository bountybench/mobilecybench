#!/usr/bin/env python3
"""Generate ``schemas/batch_runner_config.schema.json`` from code.

The batch schema is the normal runner config schema plus a required top-level
``batch`` block. Regenerate after editing ``models/config.py`` batch fields:

    python scripts/generate_batch_runner_config_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.config import BatchRunnerConfig  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "schemas" / "batch_runner_config.schema.json"


def main() -> int:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(BatchRunnerConfig.render_json_schema(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
