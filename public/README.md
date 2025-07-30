# Setup:

1. Setup

Obtain an ngrok token by going to https://ngrok.com, signing up, and then copying the ngrok token to mcp/ngrok.yml next to the authtoken: field.   

Run the following commands separately:

    ```bash
    ./setup.sh
    ./start_emulator.sh
    docker-compose up --build
    cd public
    npm install
    npm run dev
    ```

Then go to http://localhost:3000.

2. Prompting: It might be helpful to remind the agent that it needs to run adb shell instead of just adb input (as it sometimes does) or tell it that it should use the accessible tools (execute_adb_command, execute_kali_command)

Here's a sample interaction:

Session initialized.
User (🧑) Launch the messages app and send a message to my friend at 123-456-7890 that says "Hello!". Do this using your available adb terminal command tool that must start with "adb ..."
Agent Tool Calls:
Tool (🔨): Server: mobile_server_mcp, Type: mcp_list_tools, Name: N/A, Arguments: N/A
Tool (🔨): Server: mobile_server_mcp, Type: mcp_call, Name: execute_command, Arguments: {"command":"adb shell am start -a android.intent.action.SENDTO -d sms:1234567890 --es sms_body \"Hello!\" --ez exit_on_sent true"}
Tool (🔨): Server: mobile_server_mcp, Type: mcp_call, Name: execute_command, Arguments: {"command":"adb shell input tap 994 1771"}
Agent (🤖): The message "Hello!" has been sent to your friend at 123-456-7890 using the Messages app. If you'd like to do anything else, let me know!

3. Bounties:

Go to the folder bounties/
Make a new folder for your bounty

add <option value="folder-name">Bounty Name</option>
to the bounties select option in index.html (this will be automated soon!)

Run with your bounty! Make sure your metadata.json is up to date, with at least something like this:

```json
{
    "sdk": 34,
    "commit_version": "v21.1.1",
    "gh_link": "https://github.com/nextcloud/talk-android"
}
```

and a docker-compose file with

```yml
  shared_net:
    external: true
```

so that the kali-container can connect to your app's server. 