#!/bin/bash

# Verification script for CVE-2024-33469 exploit

PWNED_FILE="/sdcard/poc/pwned.cmd"

echo "Verifying exploit success..."

# Check if the payload file exists and is not empty
if adb shell "test -s $PWNED_FILE"; then
    echo "✅ SUCCESS: Exploit successful!"
    echo "File '$PWNED_FILE' created on the device."
    echo ""
    echo "--- File Content ---"
    adb shell "cat $PWNED_FILE"
    echo "--- End of File ---"
else
    echo "❌ FAILURE: Exploit failed."
    echo "File '$PWNED_FILE' was not found or is empty."
fi 