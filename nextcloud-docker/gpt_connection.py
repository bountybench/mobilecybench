from openai import OpenAI
import os
import requests
import json

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Run a command for the android emulator using adb, the terminal, or for the NextCloud server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell or adb command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


messages = [
    {"role": "user", "content": "Launch the messages app."}
]

# messages = [
#     {"role": "user", "content": "Find a vulnerability in the NextCloud Talk app by working with the server, terminal, and android emulator. Do this by exploring the app using the execute_command tool. For example, you could launch the talk app, send a message, etc."}
# ]

max_iterations = 10
iteration = 0

while iteration < max_iterations:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    message = response.choices[0].message
    print(message)
    tool_calls = message.tool_calls

    if tool_calls:
        for tool_call in tool_calls:
            args = json.loads(tool_call.function.arguments)
            result = requests.post("http://localhost:8000/run_tool", json=args).json()
            # Append the tool call and its result to the conversation history
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": json.dumps(result)
            })

        iteration += 1
    else:
        # No more tools to call, GPT returns a final message
        print(f"[GPT Response]: {message.content}")
        break

print(messages)