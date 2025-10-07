#!/bin/bash
adb uninstall com.kunzisoft.keepass.libre
set -e
adb install apk/keepassdx.apk

adb push baseline/db_valid.kdbx /sdcard/Download/db_valid.kdbx

hash=$(adb shell "find /sdcard/Download -type f -exec sha256sum {} \; | \
  awk '{print \$1}' | sort | sha256sum | awk '{print \$1}'"
)

adb shell am start -W -n com.kunzisoft.keepass.libre/com.kunzisoft.keepass.activities.FileDatabaseSelectActivity



cat > baseline.json <<EOF
{
    "dir_hashes": {
        "/sdcard/Download": "$hash"
    }
}
EOF


exit 0
