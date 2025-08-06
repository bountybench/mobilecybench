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
sleep 2
python ui_utils.py click_id com.nextcloud.talk2:id/text_input_end_icon

sleep 3
python ui_utils.py click_text "Log in"
python ui_utils.py click_text "Log in"
sleep 4

#Log in page 2
adb shell input text "${USER_A_USERNAME}"
adb shell input keyevent 61
adb shell input text "${USER_A_PASSWORD}"
sleep 2
python ui_utils.py click_text "Log in"

#Grant Access page
sleep 5
python ui_utils.py click_text "Grant access"