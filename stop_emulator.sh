#!/bin/bash
exec python3 "$(dirname "$0")/emulator.py" stop "$@"
