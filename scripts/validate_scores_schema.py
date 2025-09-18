#!/usr/bin/env python3
"""
Validate scores.json schema consistency across apps.

This script enforces the standardized schema:
{
  "scores": {
    "test_access": <0|1>,
    "test_availability": <0|1>, 
    "test_integrity": <0|1>,
    "test_confidentiality": <0|1>
  },
  "access_details": {...},
  "availability_details": {...},
  "integrity_details": {...},
  "confidentiality_details": {...}
}
"""

import json
import os
import sys
from pathlib import Path


def validate_scores_schema(app_dir):
    """Validate scores.json schema for a specific app."""
    scores_file = Path(app_dir) / "scores.json"

    if not scores_file.exists():
        print(f"❌ ERROR: {scores_file} does not exist")
        return False

    try:
        with open(scores_file, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ ERROR: Invalid JSON in {scores_file}: {e}")
        return False

    errors = []

    # Check main scores key
    if "scores" not in data:
        errors.append("Missing required 'scores' key")
    else:
        scores = data["scores"]

        # Check required score keys
        required_score_keys = [
            "test_access",
            "test_availability",
            "test_integrity",
            "test_confidentiality",
        ]

        for key in required_score_keys:
            if key not in scores:
                errors.append(f"Missing required score key: '{key}'")
            elif not isinstance(scores[key], int) or scores[key] not in [0, 1]:
                errors.append(f"Invalid score value for '{key}': must be 0 or 1")

    # Check required detail keys
    required_detail_keys = [
        "access_details",
        "availability_details",
        "integrity_details",
        "confidentiality_details",
    ]

    for key in required_detail_keys:
        if key not in data:
            errors.append(f"Missing required detail key: '{key}'")
        elif not isinstance(data[key], dict):
            errors.append(f"Invalid detail value for '{key}': must be a dictionary")

    if errors:
        print(f"❌ SCHEMA VALIDATION FAILED for {app_dir}:")
        for error in errors:
            print(f"   - {error}")
        return False
    else:
        print(f"✅ Schema validation passed for {app_dir}")
        return True


def main():
    """Main function to validate scores.json schemas."""
    if len(sys.argv) != 2:
        print("Usage: python validate_scores_schema.py <app_directory>")
        sys.exit(1)

    app_dir = sys.argv[1]

    if not os.path.isdir(app_dir):
        print(f"❌ ERROR: Directory {app_dir} does not exist")
        sys.exit(1)

    success = validate_scores_schema(app_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
