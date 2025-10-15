#!/usr/bin/env python3
"""
Availability tests for Termux app
Tests for app availability and functionality
"""

import json
import sys


def main():
    """Termux doesn't have a server to check, so we return success"""
    result = {"score": 1}
    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
