#!/bin/bash

set -e
# create venv for py
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate

adb install apk/keepassdx.apk

adb push baseline/db_valid.kdbx /sdcard/Download

exit 0
