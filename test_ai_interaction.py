"""
Mobile Cybench AI Interaction Playground

This script demonstrates AI tool-calling using local Python tools and an MCP server
to interact with an Android emulator, capture screenshots, execute remote commands,
and log interactions end-to-end.

Prerequisites:
- Docker: `kali-container` (with ADB) and `mcp-server` (with ngrok tunnel)
- Android emulator connected via ADB

Environment Variables:
- `OPENAI_API_KEY` (required)
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from utils.logger import logger
from utils.mcp_utils import get_mcp_server_config

load_dotenv()


def main():
    logger.info("=" * 60)
    logger.info("MCP/AI INTERACTION PLAYGROUND")
    logger.info("=" * 60)

    try:
        mcp_tool_config = get_mcp_server_config()
        logger.info(f"✓ MCP server configured: {mcp_tool_config['server_url']}")
    except Exception as e:
        logger.error(f"MCP server not reachable or misconfigured: {e}")
        return

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    user_text = input(
        "Give a command to the agent, or type 'quit'/'exit'/'q' to quit... \n"
    )
    messages = []

    while user_text.lower() not in ["quit", "exit", "q"]:
        messages.append({"role": "user", "content": user_text})
        response = client.responses.create(
            model="gpt-5-nano",
            tools=[
                mcp_tool_config,
            ],
            input=messages,
        )

        logger.info("=" * 60)
        response_dict = vars(response)
        logger.info(
            f"""Response: {json.dumps(response_dict, indent=2, default=str)}
 Input token count: {response.usage.input_tokens}
 Output token count: {response.usage.output_tokens}"""
        )
        logger.info("=" * 60)
        # Append message and reasoning blocks to messages
        for block in response.output:
            if block.type == "message" or block.type == "reasoning":
                messages.append(block)

        # Print all the messages
        for i, message in enumerate(messages):
            logger.info("=" * 60)
            logger.info(f"MESSAGE {i}: {message}")
            logger.info("=" * 60)
        user_text = input(
            "Give a command to the agent, or type 'quit'/'exit'/'q' to quit... \n"
        )


if __name__ == "__main__":
    main()
