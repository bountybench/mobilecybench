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

from utils.agent_utils import screenshot_tool, take_screenshot
from utils.logger import logger
from utils.mcp_utils import get_mcp_server_config

load_dotenv()


def process_python_tool_call(tool_name: str, arguments: dict) -> dict:
    """Process a tool call with given arguments"""
    logger.info("=" * 60)
    logger.info("PROCESSING TOOL CALL")
    logger.info(f"Tool: {tool_name}")
    logger.info(f"Arguments: {arguments}")
    if tool_name == "take_screenshot":
        take_screenshot_result = take_screenshot(**arguments)
        logger.info("✓ Screenshot captured")
        result = take_screenshot_result.get("image_data", "")
    else:
        logger.error(f"Unknown tool: {tool_name}")
        result = {"success": False, "error": f"Unknown tool: {tool_name}"}

    logger.info("Tool call processed")
    logger.info("=" * 60)
    return result


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
                screenshot_tool,
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

        loop_iterations = 0
        tool_calls = [
            block for block in response.output if block.type == "function_call"
        ]
        # If any tool calls were made, process them in a tool call loop
        if len(tool_calls) > 0:
            # Use separate message list for the tool call loop to avoid
            # making the outer messages too long and exceeding the context window

            # Append initial user text to the tool call loop messages
            tool_call_loop_messages = [
                {"role": "user", "content": user_text},
            ]

            # Process tool calls in a loop
            while loop_iterations < 10 and len(tool_calls) > 0:
                # Process each tool call
                for tool_call in tool_calls:
                    tool_name = tool_call.name
                    arguments = json.loads(tool_call.arguments)
                    tool_result = process_python_tool_call(tool_name, arguments)

                    if tool_name == "take_screenshot":
                        # Append images using special format for openai to process
                        tool_call_loop_messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_image",
                                        "image_url": f"data:image/png;base64,{tool_result}",
                                    }
                                ],
                            }
                        )
                    else:
                        # Append original function call to the tool call loop messages
                        tool_call_loop_messages.append(
                            {
                                "type": "function_call",
                                "call_id": tool_call.id,
                                "name": tool_name,
                                "arguments": str(arguments),
                            }
                        )
                        # Append function call output to the tool call loop messages
                        tool_call_loop_messages.append(
                            {
                                "type": "function_call_output",
                                "call_id": tool_call.id,
                                "output": str(tool_result),
                            }
                        )

                # Generate next response from the model with the results of the tool calls
                response = client.responses.create(
                    model="gpt-5-nano",
                    tools=[
                        screenshot_tool,
                        mcp_tool_config,
                    ],
                    input=tool_call_loop_messages,
                )
                logger.info("=" * 60)
                logger.info(
                    f"""Response: {json.dumps(vars(response), indent=2, default=str)}
 Input token count: {response.usage.input_tokens}
 Output token count: {response.usage.output_tokens}"""
                )
                logger.info("=" * 60)

                loop_iterations += 1
                tool_calls = [
                    block for block in response.output if block.type == "function_call"
                ]

            post_tool_call_response = response

            # Append message and reasoning blocks after the tool call loop to messages
            for block in post_tool_call_response.output:
                if block.type == "message" or block.type == "reasoning":
                    messages.append(block)
        else:
            # Get the content of the first message block in the response output
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
