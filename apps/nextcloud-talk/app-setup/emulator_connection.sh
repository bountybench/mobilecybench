#!/bin/bash

#Export the user a info
export USER_A_USERNAME=$(grep '^USER_A_USERNAME=' ../.env | cut -d '=' -f2- | tr -d "'")
export USER_A_PASSWORD=$(grep '^USER_A_PASSWORD=' ../.env | cut -d '=' -f2- | tr -d "'")

#Launch app
adb shell monkey -p com.nextcloud.talk2 -c android.intent.category.LAUNCHER 1
sleep 2

#Initialize server
adb shell input text "http://10.0.2.2:8080"

#Pass first page
source ../venv/bin/activate
sleep 1
python ui_utils.py click_id com.nextcloud.talk2:id/text_input_end_icon

sleep 3
# Submit server address (press Enter)
adb shell input keyevent 66  # KEYCODE_ENTER
adb shell input keyevent 23  # KEYCODE_DPAD_CENTER
sleep 1

# Login Page
echo "Logging in..."

# Enter username
adb shell input text "${USER_A_USERNAME}"
sleep 1

# Move to password field (2x Tab/Next)
adb shell input keyevent 61
adb shell input keyevent 61
sleep 1

# Enter password
adb shell input text "${USER_A_PASSWORD}"
sleep 1

echo "hiii"
adb shell input keyevent 61
sleep 1
adb shell input keyevent 61
sleep 1
adb shell input keyevent 61
sleep 1
adb shell input keyevent 61
sleep 3

echo "input 23"
adb shell input keyevent 23  # Move focus and press
sleep 3

echo "input 23"
adb shell input keyevent 23
adb shell input keyevent 61
adb shell input keyevent 23

echo "Login automation complete."