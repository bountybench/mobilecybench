#!/bin/bash
# Default to headless when no graphical DISPLAY is available (cloud/CI hosts),
# or when EMULATOR_HEADLESS=1 is set explicitly. Otherwise launch with a window
# so dev workstations keep their existing behavior. Override with
# EMULATOR_HEADLESS=0 to force a window even on a headless host.
HEADLESS_FLAG=""
if [[ "${EMULATOR_HEADLESS:-}" = "1" ]] || { [[ -z "${EMULATOR_HEADLESS:-}" ]] && [[ -z "${DISPLAY:-}" ]]; }; then
    HEADLESS_FLAG="--headless"
fi
exec python3 "$(dirname "$0")/emulator.py" start --sdk "${1:-35}" $HEADLESS_FLAG
