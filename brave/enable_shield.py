import uiautomator2 as u2

d = u2.connect()
shields_button = d(description="Enable/Disable Brave Shields")
    
if shields_button.exists:
    shields_button.click()
    print("Clicked Brave Shields button")
else:
    print("Brave Shields button not found")