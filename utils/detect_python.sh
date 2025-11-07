#!/bin/bash

# Detects Python 3 command and outputs the command name
# Usage: PYTHON=$(utils/detect_python.sh)

# Use python3 if available, otherwise use python
if command -v python3 &>/dev/null; then
    echo "python3"
    exit 0
fi

# Check if python is available and is Python 3
if command -v python &>/dev/null; then
    if python -c "import sys; exit(0 if sys.version_info >= (3,) else 1)" &>/dev/null; then
        echo "python"
        exit 0
    else
        echo "Error: Python 3 is required but 'python' command is Python 2" >&2
        exit 1
    fi
fi

# No Python found
echo "Error: Python 3 is not installed. Please install Python 3.x" >&2
exit 1
