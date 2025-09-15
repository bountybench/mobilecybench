import datetime
import json
import os

from dotenv import load_dotenv

from agent.model_providers import get_model_provider
from agent.prompts.prompts import (
    APP_SERVER_ACCESS,
    BASE_EXAMPLES,
    BASE_INSTRUCTIONS,
    BASE_RESPONSE_FORMAT,
    DETECT_DESCRIPTION,
    SEPARATOR,
    STOP_TOKEN,
    SUBMISSION_INSTRUCTIONS,
    TARGET_HOST_EXAMPLE,
)
from utils.logger import logger
from utils.mcp_utils import get_mcp_server_config


class CustomAgent:
    def __init__(
        self,
        model: str,
        max_iterations: int,
        max_model_response_tokens: int,
        max_kali_message_tokens: int,
        # TODO need to enforce this before sending off requests
        max_context_length: int,
        screenshot_enabled: bool,
        app_name: str,
        dry_run: bool,
        mcp_config: dict = None,
        system_prompt: str = None,
        timeout_ms: int = 600_000,
        app_server: str = None,
        network_access: bool = True,
    ):
        self.dry_run = dry_run
        # Load environment variables from .env file in the agent directory
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        self.provider = get_model_provider("openai")
        self.provider.validate()
        self.model = model
        self.max_iterations = max_iterations
        self.max_model_response_tokens = max_model_response_tokens
        self.max_kali_message_tokens = max_kali_message_tokens
        self.max_context_length = max_context_length
        self.timeout_ms = timeout_ms
        self.screenshot_enabled = screenshot_enabled
        self.app_server = app_server
        self.network_access = network_access
        self.app_name = app_name

        # Set up MCP configuration
        self.mcp_config = mcp_config or get_mcp_server_config()

        # Set up system prompt
        self.system_prompt = system_prompt or self._get_default_system_prompt()

        # Initialize agent state
        self.rolling_summary = ""
        self.history_items = [self.system_prompt]

        # Set up logging
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = f"agent_run_{timestamp}.log"

        logger.info("Agent Run Started")
        logger.info(f"Dry Run: {self.dry_run}")

        logger.info(f"Model: {self.model}")
        logger.info(f"Max Iterations: {self.max_iterations}")
        logger.info(
            f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}"
        )
        logger.info("=" * 80)

    def _get_default_system_prompt(self) -> dict:
        prompt_parts = [
            DETECT_DESCRIPTION,
        ]

        # Add app server information if network access is enabled and app_server is provided
        if self.network_access and self.app_server:
            prompt_parts.extend(
                [SEPARATOR, APP_SERVER_ACCESS.format(app_server=self.app_server)]
            )

        prompt_parts.extend(
            [
                SEPARATOR,
                BASE_RESPONSE_FORMAT.format(stop_token=STOP_TOKEN),
                SEPARATOR,
                BASE_INSTRUCTIONS.format(stop_token=STOP_TOKEN),
                SEPARATOR,
                BASE_EXAMPLES.format(stop_token=STOP_TOKEN),
            ]
        )

        # Add target host example if provided
        if self.app_server:
            prompt_parts.extend(
                [
                    SEPARATOR,
                    TARGET_HOST_EXAMPLE.format(
                        resolved_host=self.app_server, stop_token=STOP_TOKEN
                    ),
                ]
            )

        prompt_parts.extend([SEPARATOR, SUBMISSION_INSTRUCTIONS])

        full_prompt = "".join(prompt_parts)

        return {
            "role": "system",
            "content": [{"type": "input_text", "text": full_prompt}],
        }

    def add_message(self, role: str, text: str):
        self.history_items.append(
            {"role": role, "content": [{"type": "input_text", "text": text}]}
        )
        logger.info(f"[{role.upper()}] {text}")

    def run(self) -> dict:
        if self.dry_run:
            print("[Agent] Dry run - returning immediately")
            logger.info("Dry run: Quick return without execution")
            return {
                "status": "This is a dry run. No OpenAI API calls were made.",
                "turns": 0,
                "final_message": None,
                "log_file": self.log_file,
            }

        for turn in range(self.max_iterations):
            print(f"[Agent] Starting turn {turn + 1}/{self.max_iterations}")

            logger.info(f"{'='*20} TURN {turn + 1}/{self.max_iterations} {'='*20}")

            # Create input for the model
            print(
                f"[Agent] Preparing model input with {len(self.history_items)} history items"
            )
            model_input = self.history_items.copy()
            if self.rolling_summary:
                print(
                    f"[Agent] Adding rolling summary ({len(self.rolling_summary)} chars)"
                )
                model_input.append(
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"Summary:\n{self.rolling_summary}",
                            }
                        ],
                    }
                )

            # Make API call
            print(f"[Agent] Making OpenAI API call with model {self.model}")
            print(
                f"[Agent] MCP config: {self.mcp_config.get('server_url', 'No server_url')}"
            )

            # Convert complex message format to simple string format like test script
            input_text = ""
            for item in model_input:
                if item.get("role") == "system":
                    content = item.get("content", [])
                    if isinstance(content, list) and content:
                        input_text += content[0].get("text", "") + "\n"
                elif item.get("role") in ["user", "assistant"]:
                    content = item.get("content", [])
                    if isinstance(content, list) and content:
                        input_text += content[0].get("text", "") + "\n"

            logger.info(f"[INPUT TEXT - {len(input_text)} chars]")
            logger.info(input_text.strip())
            logger.info("-" * 40)

            resp = self.provider.call(
                model=self.model,
                input_text=input_text.strip(),
                tools=[self.mcp_config],
                max_output_tokens=self.max_model_response_tokens,
                timeout_ms=self.timeout_ms,
            )
            print("[Agent] API call completed")

            # Process response
            assistant_response = resp.output_text
            print(f"[Agent] Response length: {len(assistant_response)} chars")

            logger.info(f"[API RESPONSE - {len(assistant_response)} chars]")
            logger.info(assistant_response)
            logger.info("-" * 40)

            # Log all tool outputs from response
            if hasattr(resp, "tool_outputs") and resp.tool_outputs:
                logger.info(f"[TOOL OUTPUTS - {len(resp.tool_outputs)} outputs]")
                for i, tool_output in enumerate(resp.tool_outputs):
                    logger.info(f"Tool Output {i+1}:")
                    logger.info(str(tool_output))
                logger.info("-" * 40)

            # Log MCP interactions if any
            if hasattr(resp, "output") and resp.output:
                logger.info("[MCP INTERACTIONS]")

                for output_item in resp.output:
                    if (
                        hasattr(output_item, "type")
                        and output_item.type == "mcp_list_tools"
                    ):
                        tools_count = len(getattr(output_item, "tools", []))
                        print(f"[Agent] MCP tools listed: {tools_count} tools")

                        logger.info(f"MCP Tools Listed: {tools_count} tools")
                        tools = getattr(output_item, "tools", [])
                        for tool in tools:
                            tool_name = getattr(tool, "name", "unknown")
                            tool_desc = getattr(tool, "description", "No description")
                            logger.info(f"  - {tool_name}: {tool_desc}")

                    elif (
                        hasattr(output_item, "type") and output_item.type == "mcp_call"
                    ):
                        name = getattr(output_item, "name", "unknown")
                        arguments = getattr(output_item, "arguments", "")
                        output = getattr(output_item, "output", "")
                        error = getattr(output_item, "error", None)

                        print(f"[Agent] MCP call: {name} -> {str(output)}...")

                        logger.info(f"MCP Call: {name}")
                        logger.info(f"  Arguments: {arguments}")
                        logger.info(f"  Output: {output}")
                        if error:
                            logger.info(f"  Error: {error}")

                logger.info("-" * 40)

            # Add assistant response to history
            if assistant_response.strip():
                self.add_message("assistant", assistant_response.strip())

                # Try to parse as JSON for command handling
                try:
                    msg = json.loads(assistant_response)
                except Exception:
                    msg = {}

                if msg.get("command") == "FinalSubmissionCommand":
                    print("[Agent] Final submission received - stopping execution")

                    logger.info(f"{'='*20} RUN COMPLETED {'='*20}")
                    logger.info("Status: Final submission received")
                    logger.info(f"Total turns: {turn + 1}")
                    logger.info(f"Final message: {json.dumps(msg, indent=2)}")
                    logger.info(f"Log file: {self.log_file}")

                    print(f"[Agent] Full log saved to: {self.log_file}")

                    return {
                        "status": "completed",
                        "turns": turn + 1,
                        "final_message": msg,
                        "log_file": self.log_file,
                    }

        print(f"[Agent] Reached maximum iterations ({self.max_iterations})")

        # Log completion
        with open(self.log_file, "a") as f:
            f.write(f"\n{'='*20} RUN COMPLETED {'='*20}\n")
            f.write("Status: Maximum iterations reached\n")
            f.write(f"Total turns: {self.max_iterations}\n")
            f.write(f"Log file: {self.log_file}\n")

        print(f"[Agent] Full log saved to: {self.log_file}")

        return {
            "status": "max_iterations_reached",
            "turns": self.max_iterations,
            "final_message": None,
            "log_file": self.log_file,
        }
