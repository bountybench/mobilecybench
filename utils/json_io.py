import json
import os
from pathlib import Path
from typing import Any

import jsonschema


def load_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    """Load + precompile a JSON schema by its name under ``<repo>/schemas/``.

    Works in-container (under ``/opt/utils/`` + ``/opt/schemas/``) and on the
    host (under ``<repo>/utils/`` + ``<repo>/schemas/``) — same relative shape.
    """
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / schema_name
    with schema_path.open(encoding="utf-8") as f:
        return jsonschema.Draft202012Validator(json.load(f))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
