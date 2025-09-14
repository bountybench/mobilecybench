"""
# AI Interaction Test with Custom Functions and MCP Server

This file demonstrates a comprehensive test of AI tool-calling capabilities using both:
1. **Custom Python Functions** - Direct function calls within the same process
2. **MCP (Model Context Protocol) Server** - External tool execution via HTTP

## Overview

The script creates an interactive AI agent that can:
- Take screenshots of an Android emulator using ADB
- Execute terminal commands via MCP server
- Process mathematical operations
- Provide detailed logging of all interactions

## Architecture

### Custom Functions
- `take_screenshot()` - Captures and compresses Android emulator screenshots as PNG
- `add_numbers()` - A second dummy tool that adds two numbers
- `process_python_tool_call()` - Handles execution of local Python functions

### MCP Server Integration
- Connects to a remote MCP server running in Docker
- Executes commands like `adb devices`, `adb shell`, etc.
- Uses ngrok for secure tunneling to the MCP server

## Logging System

The logging system provides comprehensive tracking:

### Log Configuration
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler(f"ai_interaction_{timestamp}.log")  # File output
    ]
)
```

### Log Outputs
- **Console**: Real-time feedback during execution
- **File**: Persistent log saved as `ai_interaction_YYYYMMDD_HHMMSS.log`
- **Level**: INFO and above (INFO, WARNING, ERROR, CRITICAL)

### What Gets Logged
- Screenshot capture attempts and results
- MCP server connection status
- Tool call executions and responses
- Error messages and debugging information
- Token usage statistics

## Prerequisites

1. **Docker Environment**:
   - `kali-container` running with ADB access
   - `mcp-server` container with ngrok tunnel
   - Android emulator connected via ADB

2. **Environment Variables**:
   - `OPENAI_API_KEY` - Your OpenAI API key

3. **Python Dependencies**:
   - openai
   - docker
   - pillow
   - python-dotenv

## Running the Script

```bash
python test_ai_interaction.py
```

The script will:
1. Connect to the MCP server via ngrok
2. Start an interactive chat loop
3. Process your commands using AI + tools
4. Log all interactions to console and file

## Example Commands

* "take a screenshot and describe what you see"
* "capture the current screen and tell me what apps are visible"
* "what adb devices are available"
* "add 123 + 456 using the add_numbers tool"

## Tool Call Flow

1. **User Input** → AI processes the request
2. **Tool Selection** → AI chooses appropriate tools (custom functions or MCP)
3. **Tool Execution** → Functions run locally or via MCP server
4. **Result Processing** → AI analyzes tool outputs
5. **Response Generation** → AI provides final answer to user

## File Structure

- `screenshots/` - Directory where screenshots are saved (PNG format)
- `ai_interaction_*.log` - Detailed execution logs
- Console output - Real-time interaction feedback
"""

import base64
import io
import json
import logging
import os
import subprocess
from datetime import datetime

import docker
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image as PILImage

load_dotenv()

# Docker configuration
DOCKER_CLIENT = docker.from_env()
KALI_CONTAINER_NAME = "kali-container"  # from docker-compose.yml
HOST_ADB_SERVER = "host.docker.internal:5037"  # from docker-compose.yml

# Logs get written to a file with the name "ai_interaction_<current_timestamp>.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"ai_interaction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)
logger = logging.getLogger(__name__)


def get_ngrok_url():
    """Get ngrok URL from mcp-server docker container with error handling"""
    try:
        obtain_url_command = (
            "docker exec -it mcp-server curl http://localhost:4040/api/tunnels"
        )
        url_response = subprocess.run(
            obtain_url_command.split(" "), capture_output=True, text=True
        )

        if url_response.returncode != 0:
            logger.error(f"❌ Error getting ngrok URL: {url_response.stderr}")
            return None

        tunnels_data = json.loads(url_response.stdout)
        if not tunnels_data.get("tunnels"):
            logger.error("❌ No ngrok tunnels found")
            return None

        url = tunnels_data["tunnels"][0]["public_url"]
        logger.info(f"✅ Ngrok URL: {url}")
        return url
    except Exception as e:
        logger.error(f"❌ Error getting ngrok URL: {e}")
        return None


def test_mcp_connection(server_url):
    """Test MCP server connection"""
    try:
        test_cmd = f"docker exec mcp-server curl -s {server_url}"
        result = subprocess.run(test_cmd.split(), capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"✅ MCP server is reachable at {server_url}")
            return True
        else:
            logger.error(f"❌ MCP server not reachable: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ Error testing MCP connection: {e}")
        return False


def print_separator(title=""):
    """Utility function to print a visual separator with optional title"""
    print("\n" + "=" * 80)
    if title:
        print(f" {title} ".center(80, "="))
        print("=" * 80)
    print()


def encode_image(image_data: bytes) -> str:
    """Encode image data as base64 string"""
    return base64.b64encode(image_data).decode("utf-8")


def take_screenshot(
    compress_level: int = 6, max_width: int = 300, save_to_file: bool = True
):
    """
    Takes a compressed screenshot of the emulator and returns it as base64 encoded image data.

    Args:
        compress_level (int): PNG compression level (0-9, default 6)
        max_width (int): Maximum width for resizing (default 300)
        save_to_file (bool): Whether to save screenshot to file (default True)

    Returns:
        dict: Contains success status, base64 encoded image data, and metadata
    """
    logger.info("📸 SCREENSHOT: Starting capture...")

    try:
        kali_container = DOCKER_CLIENT.containers.get(KALI_CONTAINER_NAME)
        cmd = f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb exec-out screencap -p"
        result = kali_container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)

        if result.exit_code != 0:
            error_msg = result.output.decode("utf-8")
            logger.error(f"❌ SCREENSHOT: Error - {error_msg}")
            return {
                "success": False,
                "error": f"Error taking screenshot: {error_msg}",
                "image_data": None,
            }

        # Process and compress image
        image = PILImage.open(io.BytesIO(result.output))

        # Resize if too wide
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height), PILImage.Resampling.LANCZOS)

        # Compress and encode as PNG
        output_buffer = io.BytesIO()
        image.save(
            output_buffer, format="PNG", optimize=True, compress_level=compress_level
        )
        image_bytes = output_buffer.getvalue()
        image_base64 = encode_image(image_bytes)

        result_data = {
            "success": True,
            "image_data": image_base64,
            "format": "png",
            "size_bytes": len(image_bytes),
            "dimensions": (image.width, image.height),
            "compress_level": compress_level,
        }

        # Save to file if requested
        if save_to_file:
            screenshots_dir = "./screenshots"
            os.makedirs(screenshots_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_filename = f"screenshot_{timestamp}.png"
            screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

            # Save the compressed image to file
            with open(screenshot_path, "wb") as f:
                f.write(image_bytes)

            logger.info(f"💾 SCREENSHOT: Saved to {screenshot_path}")
            result_data["file_path"] = screenshot_path

        logger.info(f"✅ SCREENSHOT: Success! Response size: {len(image_bytes)} bytes")
        return result_data

    except Exception as e:
        logger.error(f"❌ SCREENSHOT: Exception - {str(e)}")
        return {"success": False, "error": str(e), "image_data": None}


screenshot_tool = {
    "type": "function",
    "name": "take_screenshot",
    "description": "Takes a screenshot of the emulator and returns the image data as a base64 encoded string.",
    "parameters": {
        "type": "object",
        "properties": {
            "compress_level": {
                "type": "integer",
                "description": "PNG compression level (0-9, default 6)",
                "minimum": 0,
                "maximum": 9,
                "default": 6,
            },
            "max_width": {
                "type": "integer",
                "description": "Maximum width for resizing (default 300)",
                "default": 300,
            },
            "save_to_file": {
                "type": "boolean",
                "description": "Whether to save screenshot to file (default True)",
                "default": True,
            },
        },
        "required": [],
    },
}


def add_numbers(x, y):
    """Dummy tool to add two numbers"""
    return x + y


add_numbers_tool = {
    "type": "function",
    "name": "add_numbers",
    "description": "Add two numbers",
    "parameters": {
        "type": "object",
        "properties": {
            "x": {
                "type": "number",
                "description": "The first number",
            },
            "y": {
                "type": "number",
                "description": "The second number",
            },
        },
        "required": ["x", "y"],
    },
}


def process_python_tool_call(tool_name: str, arguments: dict) -> dict:
    """Process a tool call with given arguments"""
    print_separator("PROCESSING TOOL CALL")
    logger.info(f"TOOL NAME: {tool_name}")
    logger.info(f"ARGUMENTS: {arguments}")
    if tool_name == "take_screenshot":
        take_screenshot_result = take_screenshot(**arguments)
        logger.info(f"TAKE SCREENSHOT RESULT: {take_screenshot_result}")
        result = take_screenshot_result.get("image_data", "")
    elif tool_name == "add_numbers":
        add_numbers_result = add_numbers(**arguments)
        logger.info(f"ADD NUMBERS RESULT: {add_numbers_result}")
        result = add_numbers_result
    else:
        logger.error(f"UNKNOWN TOOL: {tool_name}")
        result = {"success": False, "error": f"Unknown tool: {tool_name}"}

    logger.info(f"TOOL CALL RESULT: {result}")
    return result


def main():
    print_separator("Testing playground for MCP/AI interactions")

    url = get_ngrok_url()
    if not test_mcp_connection(url):
        logger.error("❌ MCP server not reachable. Check if containers are running.")
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
                add_numbers_tool,
                {
                    "type": "mcp",
                    "server_label": "mobile_server_mcp",
                    "server_url": f"{url}/mcp/",
                    "require_approval": "never",
                },
            ],
            input=messages,
        )

        print("=" * 100)
        response_dict = vars(response)
        logger.info(
            f"""Response: {json.dumps(response_dict, indent=2, default=str)}
 INPUT TOKEN COUNT: {response.usage.input_tokens}
 OUTPUT TOKEN COUNT: {response.usage.output_tokens}"""
        )
        print("=" * 100)

        loop_iterations = 0
        tool_calls = [
            block for block in response.output if block.type == "function_call"
        ]
        # if any tool calls were made, process them in a tool call loop
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
                        add_numbers_tool,
                        {
                            "type": "mcp",
                            "server_label": "mobile_server_mcp",
                            "server_url": f"{url}/mcp/",
                            "require_approval": "never",
                        },
                    ],
                    input=tool_call_loop_messages,
                )
                print("=" * 100)
                logger.info(
                    f"""Response: {json.dumps(vars(response), indent=2, default=str)}
 INPUT TOKEN COUNT: {response.usage.input_tokens}
 OUTPUT TOKEN COUNT: {response.usage.output_tokens}"""
                )
                print("=" * 100)

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
            print("=" * 100)
            response_dict = vars(response)
            logger.info(
                f"""Response: {json.dumps(response_dict, indent=2, default=str)}
 INPUT TOKEN COUNT: {response.usage.input_tokens}
 OUTPUT TOKEN COUNT: {response.usage.output_tokens}"""
            )
            print("=" * 100)

            # Append message and reasoning blocks to messages
            for block in response.output:
                if block.type == "message" or block.type == "reasoning":
                    messages.append(block)

        # Print all the messages
        for i, message in enumerate(messages):
            print("=" * 100)
            print(f"MESSAGE {i}: {message}")
            print("=" * 100)
        user_text = input(
            "Give a command to the agent, or type 'quit'/'exit'/'q' to quit... \n"
        )


if __name__ == "__main__":
    main()
