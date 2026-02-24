#!/usr/bin/env python3
import os
import runpy
import sys

SCRIPT_DIR = os.path.dirname(__file__)
TARGET = os.path.join(SCRIPT_DIR, "verify_files", "test_synthetic.py")

# Preserve optional exploit log arg contract used by synthetic runners.
sys.argv = [TARGET] + sys.argv[1:]
runpy.run_path(TARGET, run_name="__main__")
