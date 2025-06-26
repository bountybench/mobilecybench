import uiautomator2 as u2
import time

d = u2.connect() 
d(resourceId="com.brave.browser:id/btn_negative").click()
d(text="Continue").click()
time.sleep(3)