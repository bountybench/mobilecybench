#!/bin/bash
set -x

echo "Executing verify.py"
python verify.py

if [[ $? -eq 0 ]]; then
    exit 0
else
    exit 1
fi