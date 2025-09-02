#!/usr/bin/env python3
"""
JSON Score Formatter for Injected Vulnerability Test Suite

This script takes raw JSON strings for module scores and details,
validates them, and outputs a properly formatted JSON file.

Usage:
    python3 format_json_scores.py <output_file> <module_scores_json> <details_json>

Args:
    output_file: Path to write the formatted JSON output
    module_scores_json: JSON string containing module-level scores
    details_json: JSON string containing test-level details

Example:
    python3 format_json_scores.py scores.json '{"test_module": 1}' '{"test_module": {"test_func": 1}}'
"""

import json
import sys
from typing import Any, Dict


def format_scores_json(
    output_file: str, module_scores_raw: str, details_raw: str
) -> None:
    """
    Format and write vulnerability test scores to JSON file.

    Args:
        output_file: Path to output JSON file
        module_scores_raw: Raw JSON string with module scores
        details_raw: Raw JSON string with test details

    Raises:
        json.JSONDecodeError: If input JSON strings are invalid
        OSError: If output file cannot be written
    """
    try:
        module_scores = json.loads(module_scores_raw)
        details = json.loads(details_raw)

        # Validate that both are dictionaries
        if not isinstance(module_scores, dict):
            raise ValueError("module_scores must be a JSON object/dictionary")
        if not isinstance(details, dict):
            raise ValueError("details must be a JSON object/dictionary")

        result = {"module_scores": module_scores, "details": details}
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input - {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(
            f"Error: Cannot write to output file '{output_file}' - {e}", file=sys.stderr
        )
        sys.exit(1)


def main() -> None:
    """Main entry point for the script."""
    if len(sys.argv) != 4:
        print(
            "Usage: python3 format_json_scores.py <output_file> <module_scores_json> <details_json>",
            file=sys.stderr,
        )
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    output_file = sys.argv[1]
    module_scores_raw = sys.argv[2]
    details_raw = sys.argv[3]
    format_scores_json(output_file, module_scores_raw, details_raw)


if __name__ == "__main__":
    main()
