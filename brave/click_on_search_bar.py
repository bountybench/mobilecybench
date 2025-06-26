import uiautomator2 as u2
import time

d = u2.connect()
d(text="Search or type URL").click()