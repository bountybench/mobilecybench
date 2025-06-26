import uiautomator2 as u2

d = u2.connect()  # automatically connects to device via USB
d(resourceId="com.brave.browser:id/btn_negative").click()

d(text="Continue").click()

d.click(30, 30)