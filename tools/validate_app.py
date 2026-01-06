#!/usr/bin/env python3
"""Validate an app directory against mobilecybench expectations.

Examples:
  python tools/validate_app.py apps/home-assistant-android
  python tools/validate_app.py apps/foo --check-apk
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "app_metadata_schema.json"

REQUIRED_FILES = [
    "metadata.json",
    "secrets.json",
    "setup.sh",
    "setup_app_source.sh",
    "cleanup.sh",
    "test_access_control.py",
    "test_availability.py",
    "test_confidentiality.py",
    "test_integrity.py",
    "vuln_scenarios/vuln_scenario_0/vuln.sh",
    "vuln_scenarios/vuln_scenario_0/expected_scores.json",
]

SERVERFUL_FILES = [
    "vuln_scenarios/vuln_scenario_1/vuln.sh",
    "vuln_scenarios/vuln_scenario_1/expected_scores.json",
]


class ValidationError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate app folder")
    parser.add_argument("app_path", help="Path to apps/<app>")
    parser.add_argument(
        "--check-apk", action="store_true", help="Require APK file to exist"
    )
    return parser.parse_args()


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise ValidationError(f"Failed to read {path}: {exc}")


def validate_metadata(meta: dict, schema: dict) -> List[str]:
    problems: List[str] = []
    required_keys = schema.get("required", [])
    for key in required_keys:
        if key not in meta:
            problems.append(f"metadata missing required key '{key}'")
    for key, val in meta.items():
        if key == "container_names":
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                problems.append("metadata.container_names must be a list of strings")
        elif key in required_keys or key in schema.get("properties", {}):
            if schema.get("properties", {}).get(key, {}).get(
                "type"
            ) == "string" and not isinstance(val, str):
                problems.append(f"metadata.{key} must be a string")
    return problems


def require_files(base: Path, files: List[str]) -> List[str]:
    missing = []
    for rel in files:
        candidate = base / rel
        if not candidate.exists():
            missing.append(rel)
    return missing


def has_codebase(base: Path) -> bool:
    codebase = base / "codebase"
    return codebase.exists()


def has_compose(base: Path) -> bool:
    return (base / "docker-compose.yml").exists() or (
        base / "docker-compose.yaml"
    ).exists()


def find_apk(base: Path) -> bool:
    apk_dir = base / "apk"
    return (
        any(p.suffix == ".apk" for p in apk_dir.glob("*.apk"))
        if apk_dir.exists()
        else False
    )


def main() -> int:
    args = parse_args()
    app_dir = Path(args.app_path).resolve()
    if not app_dir.exists():
        raise SystemExit(f"App path not found: {app_dir}")

    issues: List[str] = []

    schema = load_json(SCHEMA_PATH)
    meta_path = app_dir / "metadata.json"
    meta = load_json(meta_path)
    issues.extend(validate_metadata(meta, schema))

    issues.extend([f"missing {f}" for f in require_files(app_dir, REQUIRED_FILES)])

    if not has_codebase(app_dir):
        issues.append("missing codebase/ (expected git submodule)")

    serverful = bool(meta.get("app_server")) or bool(meta.get("container_names"))
    if serverful:
        # Require compose and vuln_scenario_1 files
        if not has_compose(app_dir):
            issues.append(
                "docker-compose.yml or docker-compose.yaml is required for server-backed apps"
            )
        issues.extend([f"missing {f}" for f in require_files(app_dir, SERVERFUL_FILES)])

    if args.check_apk:
        if not find_apk(app_dir) and not meta.get("download_link"):
            issues.append("No APK present in apk/ and no download_link set")

    if issues:
        print("Validation failed:")
        for item in issues:
            print(f" - {item}")
        return 1

    print("Validation passed. App folder looks good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
