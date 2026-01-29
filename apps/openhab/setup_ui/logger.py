"""
Logging utilities for openHAB UI automation.
"""

import sys

from .constants import SCRIPT_NAME


def log(message: str) -> None:
    """Print log message to stderr with script name prefix."""
    print(f"[{SCRIPT_NAME}] {message}", file=sys.stderr)
