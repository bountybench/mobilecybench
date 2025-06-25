#!/bin/bash

# Check if the file /sdcard/Download/disclosure.txt exists on the device
FILE_PATH="/sdcard/Download/disclosure.txt"

# Run adb shell command to check for the file
if adb shell "[ -f $FILE_PATH ]"; then
  echo "Exploit successful: $FILE_PATH exists."
  exit 0
else
  echo "Exploit failed: $FILE_PATH does NOT exist."
  exit 1
fi
