#!/bin/bash

set -e
# create venv for py
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate

adb install apk/keepassdx.apk

adb push baseline/db_valid.kdbx /sdcard/Download/db_valid.kdbx

#adb shell find /sdcard/Download -type f -exec sha256sum {} | awk '{print $1}' | sort | sha256sum | awk '{print $1}'
hash=$(adb shell find /sdcard/Download -type f -exec sha256sum {} \; \
  | awk '{print $1}' \
  | sort \
  | sha256sum \
  | awk '{print $1}')

cat > baseline.json <<EOF
{
    "dir_hashes": {
        "/sdcard/Download": "$hash"
    }
}
EOF


exit 0
