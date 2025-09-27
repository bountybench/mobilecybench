#!/bin/bash

set -e
# create venv for py
sudo apt install python3-venv
python3 -m venv .
source ./bin/activate

exit 0
