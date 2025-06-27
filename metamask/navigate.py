import uiautomator2 as u2
import time

d = u2.connect()

print(d.dump_hierarchy())

# Navigate past intros
d(text="Get started").click_exists(timeout=3)
time.sleep(2)
d(text="Create a new wallet").click_exists(timeout=3)
time.sleep(2)
d(text="I agree").click_exists(timeout=3)
time.sleep(2)

#print(d.dump_hierarchy())

d(resourceId="terms-of-use-scroll-end-arrow-button-id").click()
d(text="I agree to the Terms of Use, which apply to my use of MetaMask and all of its features").click_exists(timeout=3)
d(text="Accept").click_exists(timeout=3)
time.sleep(2)

# Password page
d(resourceId="create-password-first-input-field").click()
d.send_keys("MyPassword123", clear=True)
d.press("enter")
d(resourceId="create-password-second-input-field").click()
d.send_keys("MyPassword123", clear=True)
d(resourceId="create-password-second-input-field").click()

width, height = d.window_size()
x = width // 2
y = height // 4
d.click(x, y)
d.click(x, y)

d(resourceId="password-understand-box").click()
time.sleep(5)
d(description="submit-button").click()
time.sleep(4)

# Skip past unecessary safety
d(text="Remind me later").click_exists(timeout=3)
time.sleep(4)
d(resourceId="skip-backup-check").click()
time.sleep(2)
d(text="Skip").click_exists(timeout=3)

time.sleep(2)
d(text="Done").click_exists(timeout=3)
time.sleep(2)
d(text="No thanks").click_exists(timeout=3)
time.sleep(2)

d(text="No thanks").click_exists(timeout=3)
time.sleep(2)
scrollview = d(className="android.widget.ScrollView")
scrollview.scroll.toEnd()
time.sleep(2)
d(text="Got it").click_exists(timeout=3)