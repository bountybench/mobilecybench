#!/usr/bin/env python3
"""
This script serves as a robust gate to ensure the Android emulator is fully
booted, stable, and ready for interaction before other scripts proceed.

It leverages the intelligent probing mechanisms within ui_utils to check for
core system services, preventing the race conditions and DeadSystemException
errors that can occur in CI environments when scripts interact with an
emulator that is not yet fully stabilized.
"""

import logging
import os
import sys
import time

# Ensure the project root is in the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.ui_utils import initialize_ui_automation

# Configure a simple logger for this script
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)


def main():
    """
    Initializes a connection to the UI automation service, which implicitly
    runs all the necessary readiness and stability checks.
    """
    logging.info("Starting emulator readiness check...")
    start_time = time.time()

    # The initialize_ui_automation function contains all the necessary logic
    # to wait for the device and probe for core service stability. We don't
    # need to do anything with the returned 'device' object; we just need
    # this call to succeed.
    initialize_ui_automation()

    duration = time.time() - start_time
    logging.info("Emulator is ready. (Check completed in %.1fs)", duration)


if __name__ == "__main__":
    main()
