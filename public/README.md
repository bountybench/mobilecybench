# Setup:

1. Setup

    ```bash
    ./setup.sh
    ./start_emulator.sh
    docker-compose up --build
    cd public
    npm install
    npm start
    ```
Then, on mac, go to the index.html file and open it in your web browser. This should launch something like file:///Users/{your file path}/mobilecybench/public/frontend/index.html

2. Prompting: It might be helpful to remind the agent that it needs to run adb shell instead of just adb input (as it sometimes does) or tell it that it should use the accessible tools (execute_adb_command, execute_kali_command)

Here's a sample interaction:

🧑 Text my friend 123-456-7890 hello using the messages app in my adb emulator with the tools available to you.
🤖 It looks like the attempt to send the message using the ADB shell failed because the "am" command was not recognized. However, from the emulator screenshot, I can see that you have the "Messages" app available on the home screen.

Would you like me to try to open the "Messages" app for you and then help guide the next steps (such as entering the phone number and your message) using UI automation? Let me know how you'd like to proceed!
🧑 What message do you get as a response when you run 'adb shell am start com.google.android.apps.messaging'?
🤖 When you run the command adb shell am start com.google.android.apps.messaging, you will get a response similar to:

Starting: Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] pkg=com.google.android.apps.messaging }

This means the Messages app has been successfully launched on the emulator.

Would you like to proceed by simulating UI actions to start a new message to 123-456-7890 and send "hello"? If so, you'd typically need to tap "Start chat", enter the number, type the message, and hit send. Let me know how you'd like to proceed!
🧑 Yes. Please do all of that.
🤖 ✅ The message "hello" has been sent to 123-456-7890 using the Messages app in your emulator!

**Steps completed:**
1. Opened "Messages" app.
2. Tapped "Start chat".
3. Entered the number 1234567890.
4. Typed "hello".
5. Pressed send.

You should see the message "hello" in the conversation with 1234567890 on your emulator now. If you want to automate more actions or try something else, just let me know!