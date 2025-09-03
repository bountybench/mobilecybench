import json
import os
import subprocess

from openai import OpenAI
from dotenv import load_dotenv

obtain_url_command = "docker exec -it mcp-server curl http://localhost:4040/api/tunnels"
url_answer = subprocess.run(
    obtain_url_command.split(" "), capture_output=True, text=True
)
print(url_answer)
url = json.loads(url_answer.stdout)["tunnels"][0]["public_url"]

load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

user_text = input("quit to quit, Give a command to the agent... \n")
messages = []

while user_text.lower() != "quit":
    messages.append(user_text)

    resp = client.responses.create(
        model="gpt-5-nano",
        tools=[
            {
                "type": "mcp",
                "server_label": "mobile_server_mcp",
                "server_url": f"{url}/mcp/",
                "require_approval": "never",
            },
        ],
        input="\n".join(messages),
    )

    print(resp.output_text)
    print("=" * 100)
    print(f"tokens: {resp.usage.total_tokens}")
    print("=" * 100)

    messages.append(resp.output_text)
    user_text = input("quit to quit, Give a command to the agent... \n")
