import uiautomator2 as u2

d = u2.connect()

buttons = d(className="android.widget.Button", clickable=True)
print(f"Found {len(buttons)} buttons")
for btn in buttons:
    print(btn.info.get("bounds"))

buttons[0].click()