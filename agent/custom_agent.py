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
from utils.agent_utils import take_screenshot
from utils.logger import agent_logger, logger_manager
from utils.mcp_utils import get_mcp_server_config
from utils.token_tracker import TokenTracker


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
        if system_prompt:
            self.system_prompt = {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            }
        else:
            self.system_prompt = self._get_default_system_prompt()

        # Initialize conversation with system prompt
        self.conversation_id = None
        if not self.dry_run:
            system_content = self.system_prompt["content"][0]["text"]
            conversation = self.provider.client.conversations.create(
                metadata={"app_name": self.app_name, "model": self.model},
                items=[
                    {"type": "message", "role": "system", "content": system_content}
                ],
            )
            self.conversation_id = conversation.id
            agent_logger.info(f"Created conversation: {self.conversation_id}")

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_agent_log_file_name()

        # Initialize token tracker (writes per-call JSONL by default)
        self.token_tracker = TokenTracker()

        agent_logger.info("Agent Run Started")
        agent_logger.info(f"Dry Run: {self.dry_run}")

        agent_logger.info(f"Model: {self.model}")
        agent_logger.info(f"Max Iterations: {self.max_iterations}")
        agent_logger.info(
            f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}"
        )
        agent_logger.info("=" * 80)

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

    def run(self) -> dict:
        if self.dry_run:
            print("[Agent] Dry run - returning immediately")
            agent_logger.info("Dry run: Quick return without execution")
            return {
                "status": "This is a dry run. No OpenAI API calls were made.",
                "turns": 0,
                "final_message": None,
                "log_file": self.log_file,
            }

        for turn in range(self.max_iterations):
            print(f"[Agent] Starting turn {turn + 1}/{self.max_iterations}")

            agent_logger.info(f"{'=' * 20} TURN {turn + 1}/{self.max_iterations} {'=' * 20}")

            print(f"[Agent] Making OpenAI API call with model {self.model}")
            print(
                f"[Agent] MCP config: {self.mcp_config.get('server_url', 'No server_url')}"
            )
            print(f"[Agent] Using conversation_id: {self.conversation_id}")

            agent_logger.info(f"[API CALL - Turn {turn + 1}]")
            agent_logger.info(f"Conversation ID: {self.conversation_id}")
            agent_logger.info("-" * 40)

            # conversation_id handles context
            # can also pass input_messages to add new messages if needed
            screenshot_input = None
            if self.screenshot_enabled:
                try:
                    screenshot_result = take_screenshot()
                    if screenshot_result.get("success"):
                        screenshot_input = {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": f"data:image/png;base64,{screenshot_result.get('image_data', '')}",
                                }
                            ],
                        }
                        agent_logger.info(
                            "Screenshot taken successfully. Including screenshot in input messages"
                        )
                except Exception as e:
                    agent_logger.error(f"Error taking screenshot: {e}")

            resp = self.provider.call(
                model=self.model,
                conversation_id=self.conversation_id,
                input_messages=[screenshot_input] if screenshot_input else None,
                tools=[self.mcp_config],
                max_output_tokens=self.max_model_response_tokens,
                timeout_ms=self.timeout_ms,
            )
            print("[Agent] API call completed")

            # Record token usage and cost
            try:
                self.token_tracker.record_from_openai_response(resp, model=self.model)
            except Exception as e:
                agent_logger.warning(f"Token tracking failed: {e}")

            # Process response
            assistant_response = resp.output_text
            print(f"[Agent] Response length: {len(assistant_response)} chars")

            agent_logger.info(f"[API RESPONSE - {len(assistant_response)} chars]")
            agent_logger.info(assistant_response)
            agent_logger.info("-" * 40)

            # Log all tool outputs from response
            if hasattr(resp, "tool_outputs") and resp.tool_outputs:
                agent_logger.info(f"[TOOL OUTPUTS - {len(resp.tool_outputs)} outputs]")
                for i, tool_output in enumerate(resp.tool_outputs):
                    agent_logger.info(f"Tool Output {i + 1}:")
                    agent_logger.info(str(tool_output))
                agent_logger.info("-" * 40)

            # Log MCP interactions if any
            if hasattr(resp, "output") and resp.output:
                agent_logger.info("[MCP INTERACTIONS]")

                for output_item in resp.output:
                    if (
                        hasattr(output_item, "type")
                        and output_item.type == "mcp_list_tools"
                    ):
                        tools_count = len(getattr(output_item, "tools", []))
                        print(f"[Agent] MCP tools listed: {tools_count} tools")

                        agent_logger.info(f"MCP Tools Listed: {tools_count} tools")
                        tools = getattr(output_item, "tools", [])
                        for tool in tools:
                            tool_name = getattr(tool, "name", "unknown")
                            tool_desc = getattr(tool, "description", "No description")
                            agent_logger.info(f"  - {tool_name}: {tool_desc}")

                    elif (
                        hasattr(output_item, "type") and output_item.type == "mcp_call"
                    ):
                        name = getattr(output_item, "name", "unknown")
                        arguments = getattr(output_item, "arguments", "")
                        output = getattr(output_item, "output", "")
                        error = getattr(output_item, "error", None)

                        print(f"[Agent] MCP call: {name} -> {str(output)}...")

                        agent_logger.info(f"MCP Call: {name}")
                        agent_logger.info(f"  Arguments: {arguments}")
                        agent_logger.info(f"  Output: {output}")
                        if error:
                            agent_logger.info(f"  Error: {error}")

                agent_logger.info("-" * 40)

            # Try to parse as JSON for command handling
            if assistant_response.strip():
                try:
                    msg = json.loads(assistant_response)
                except Exception:
                    msg = {}

                if msg.get("command") == "FinalSubmissionCommand":
                    print("[Agent] Final submission received - stopping execution")

                    agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
                    agent_logger.info("Status: Final submission received")
                    agent_logger.info(f"Total turns: {turn + 1}")
                    agent_logger.info(f"Final message: {json.dumps(msg, indent=2)}")
                    agent_logger.info(
                        f"Token totals: {json.dumps(self.token_tracker.totals())}"
                    )
                    agent_logger.info(f"Log file: {self.log_file}")

                    print(f"[Agent] Full log saved to: {self.log_file}")

                    # Clean up conversation
                    if self.conversation_id:
                        self.provider.client.conversations.delete(
                            conversation_id=self.conversation_id
                        )
                        agent_logger.info(f"Deleted conversation: {self.conversation_id}")

                    return {
                        "status": "completed",
                        "turns": turn + 1,
                        "final_message": msg,
                        "token_totals": self.token_tracker.totals(),
                        "log_file": self.log_file,
                    }

        print(f"[Agent] Reached maximum iterations ({self.max_iterations})")

        # Log completion
        with open(self.log_file, "a") as f:
            f.write(f"\n{'=' * 20} RUN COMPLETED {'=' * 20}\n")
            f.write("Status: Maximum iterations reached\n")
            f.write(f"Total turns: {self.max_iterations}\n")
            f.write(f"Token totals: {json.dumps(self.token_tracker.totals())}\n")
            f.write(f"Log file: {self.log_file}\n")

        print(f"[Agent] Full log saved to: {self.log_file}")

        # Clean up conversation
        if self.conversation_id:
            self.provider.client.conversations.delete(
                conversation_id=self.conversation_id
            )
            agent_logger.info(f"Deleted conversation: {self.conversation_id}")

        return {
            "status": "max_iterations_reached",
            "turns": self.max_iterations,
            "final_message": None,
            "token_totals": self.token_tracker.totals(),
            "log_file": self.log_file,
        }
