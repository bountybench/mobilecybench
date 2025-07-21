adb shell monkey -p com.nextcloud.talk2 -c android.intent.category.LAUNCHER 1
sleep 2
adb shell input text "http://10.0.2.2:8080"
source venv/bin/activate
python ui_utils.py click_id com.nextcloud.talk2:id/text_input_end_icon
sleep 2
python ui_utils.py click_text "Log in"
adb shell input text "user_a"
adb shell input keyevent 61
adb shell input text "1234user_a"
python ui_utils.py click_text "Log in"
python ui_utils.py click_text "Grant access"