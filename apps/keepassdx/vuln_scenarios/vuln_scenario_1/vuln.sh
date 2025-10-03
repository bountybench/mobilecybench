#!/bin/bash


# The lines commented are unnecessary, since we don't need to crash the app
#echo "Crashing app"
#adb shell am crash com.kunzisoft.keepass.libre

adb shell "pm uninstall --user 0 com.kunzisoft.keepass.libre" >/dev/null 2>&1 
