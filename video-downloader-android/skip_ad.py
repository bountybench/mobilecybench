import uiautomator2 as u2
import time

d = u2.connect()

def wait_for_allow():
    print("Waiting for the app to initialize")
    
    while True:
        if d(text="ALLOW").exists:
            print("Popup found; starting search")
            break
        else:
            print("App hasn't finished opening yet")

        time.sleep(2)

# Call the function to wait for the word 'allow'
wait_for_allow()