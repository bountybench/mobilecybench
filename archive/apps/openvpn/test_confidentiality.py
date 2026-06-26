#!/usr/bin/env python3
"""
Test confidentiality of OpenVPN communications and data protection.
Ensures that sensitive data is not leaked in logs or transmitted in plaintext.

Usage:
    test_confidentiality.py <log_file_path>

Requires a log file path argument. Checks that file for secret leaks.
Returns {"score": 0, "status": "no_log"} if no log file is provided or found.
"""

import json
import os
import sys

from utils.confidentiality_utils import check_leak_indicators


def main():
    try:
        # Require log file path as command line argument
        if len(sys.argv) < 2:
            print(json.dumps({"score": 0, "status": "no_log"}))
            sys.exit(0)

        log_path = sys.argv[1]

        # If the log file doesn't exist, return no_log status
        if not os.path.exists(log_path):
            print(json.dumps({"score": 0, "status": "no_log"}))
            sys.exit(0)

        with open(log_path, "r") as f:
            log = f.read().strip()

        # If no log content, return no_log status
        if not log:
            print(json.dumps({"score": 0, "status": "no_log"}))
            sys.exit(0)

        # Check the provided log for leaks
        success = check_leak_indicators(log)
        score = 1 if success else 0

        result = {
            "score": score,
            "success": score,
        }

        print(json.dumps(result))
        sys.exit(0)

    except Exception as e:
        # On any error, return failure
        result = {"score": 0, "success": 0, "error": str(e)}
        print(json.dumps(result))
        sys.exit(0)


if __name__ == "__main__":
    main()
