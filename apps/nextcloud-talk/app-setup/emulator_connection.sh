#!/bin/bash

#Export the user a info
export USER_A_USERNAME=$(grep '^USER_A_USERNAME=' ../.env | cut -d '=' -f2- | tr -d "'")
export USER_A_PASSWORD=$(grep '^USER_A_PASSWORD=' ../.env | cut -d '=' -f2- | tr -d "'")

#Launch app
adb shell monkey -p com.nextcloud.talk2 -c android.intent.category.LAUNCHER 1
sleep 10

# #Initialize server
adb shell input text "http://10.0.2.2:8080"

# #Pass first page
source ../venv/bin/activate
cd ../../..
sleep 10
python -m apps.nextcloud-talk.app-setup.ui_util_bridge click_id com.nextcloud.talk2:id/text_input_end_icon

sleep 15
python -m apps.nextcloud-talk.app-setup.ui_util_bridge click_text "Log in"
python -m apps.nextcloud-talk.app-setup.ui_util_bridge click_text "Log in"
sleep 10

#Log in page 2
adb shell input text "${USER_A_USERNAME}"
adb shell input keyevent 61
adb shell input text "${USER_A_PASSWORD}"
sleep 10
python -m apps.nextcloud-talk.app-setup.ui_util_bridge click_text "Log in"

#Grant Access page
sleep 5
python -m apps.nextcloud-talk.app-setup.ui_util_bridge click_text "Grant access"