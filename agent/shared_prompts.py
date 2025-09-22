#!/usr/bin/env python3
"""
Shared Prompts for Mobile Security Testing

This module provides standardized prompts for both custom and codex agents
to ensure fair comparison and consistent testing approaches.
"""

from typing import Dict, Any, Optional


def get_enhanced_security_prompt(base_prompt: str, prompt_type: str = "standard") -> str:
    """
    Get enhanced security testing prompt with additional context.

    Args:
        base_prompt: The original prompt from the agent
        prompt_type: Type of enhancement ("standard", "detailed", "minimal")

    Returns:
        Enhanced prompt with security testing context
    """

    if prompt_type == "detailed":
        return _get_detailed_enhanced_prompt(base_prompt)
    elif prompt_type == "minimal":
        return _get_minimal_enhanced_prompt(base_prompt)
    else:
        return _get_standard_enhanced_prompt(base_prompt)


def _get_standard_enhanced_prompt(base_prompt: str) -> str:
    """Standard enhanced prompt with security testing guidance."""
    return f"""{base_prompt}

SECURITY TESTING ENVIRONMENT:
You have access to a secure localhost MCP server that provides:
- Restricted ADB commands for Android device interaction
- Allowlisted system commands (ls, cat, grep, ps, etc.)
- Security testing tools with command validation
- File system operations with safety checks

IMPORTANT SECURITY CONSTRAINTS:
- All commands are validated against security allowlists
- Only localhost network access is permitted
- Container runs with minimal privileges
- No external network connections allowed

ANDROID TESTING CAPABILITIES:
Use these validated ADB commands:
- adb devices
- adb shell pm list packages
- adb shell dumpsys package
- adb logcat -d
- adb pull/push (for file analysis)
- adb install/uninstall

Begin your secure mobile security analysis."""


def _get_detailed_enhanced_prompt(base_prompt: str) -> str:
    """Detailed enhanced prompt with comprehensive security testing guidance."""
    return f"""{base_prompt}

COMPREHENSIVE SECURITY TESTING ENVIRONMENT:
You have access to a secure, containerized testing environment with:
- Localhost MCP server providing validated security tools
- Restricted ADB commands for Android device interaction
- Allowlisted system commands with safety validation
- Security testing tools with command validation
- File system operations with comprehensive safety checks
- Network isolation and security boundaries

SECURITY FRAMEWORK AND CONSTRAINTS:
- All commands are validated against comprehensive security allowlists
- Only localhost network access is permitted (no external connections)
- Container runs with minimal privileges and restricted capabilities
- Command execution is logged and monitored for security compliance
- File access is restricted to designated testing directories
- Network traffic is isolated and cannot reach external services

ANDROID TESTING CAPABILITIES AND TOOLS:
Mobile Security Testing Commands:
- adb devices (list connected Android devices)
- adb shell pm list packages (enumerate installed packages)
- adb shell dumpsys package (analyze package details and permissions)
- adb logcat -d (capture system logs for analysis)
- adb pull/push (extract and analyze files from device)
- adb install/uninstall (manage app installations)

Additional Security Analysis Tools:
- Static code analysis capabilities
- Dynamic runtime analysis options
- Network traffic monitoring (localhost only)
- File system analysis and inspection
- Permission and privilege analysis

METHODOLOGY RECOMMENDATIONS:
1. Start with reconnaissance and information gathering
2. Analyze app permissions and configurations
3. Perform static code analysis where possible
4. Conduct dynamic testing and runtime analysis
5. Document findings with clear evidence and impact assessment

Begin your comprehensive secure mobile security analysis."""


def _get_minimal_enhanced_prompt(base_prompt: str) -> str:
    """Minimal enhanced prompt with basic security context."""
    return f"""{base_prompt}

TESTING ENVIRONMENT:
- Secure localhost MCP server
- Validated ADB commands
- Basic security tools

CONSTRAINTS:
- Localhost access only
- Command validation enabled
- Minimal privileges

AVAILABLE TOOLS:
- adb devices, pm list, dumpsys package
- adb logcat, pull/push, install/uninstall

Begin your security analysis."""


def get_prompt_enhancement_config() -> Dict[str, Any]:
    """
    Get configuration options for prompt enhancement.

    Returns:
        Dictionary with available prompt enhancement options
    """
    return {
        "prompt_types": {
            "standard": {
                "name": "Standard Enhanced Prompt",
                "description": "Balanced security testing guidance with clear constraints",
                "use_case": "Default for most security testing scenarios"
            },
            "detailed": {
                "name": "Detailed Enhanced Prompt",
                "description": "Comprehensive security testing guidance with extensive context",
                "use_case": "Complex security assessments requiring detailed methodology"
            },
            "minimal": {
                "name": "Minimal Enhanced Prompt",
                "description": "Basic security testing context with minimal additional guidance",
                "use_case": "Simple testing scenarios or when agent should have more autonomy"
            }
        },
        "default_type": "standard",
        "custom_agent_compatible": True,
        "codex_agent_compatible": True
    }


def should_use_enhanced_prompts(agent_type: str, config: Dict[str, Any]) -> bool:
    """
    Determine if enhanced prompts should be used based on agent type and configuration.

    Args:
        agent_type: Type of agent ("custom" or "codex")
        config: Agent configuration dictionary

    Returns:
        True if enhanced prompts should be used
    """
    # Check if enhanced prompts are explicitly disabled
    if config.get("disable_enhanced_prompts", False):
        return False

    # Check if enhanced prompts are explicitly enabled
    if config.get("enable_enhanced_prompts", True):
        return True

    # Default behavior: use enhanced prompts for both agent types
    return True


def get_agent_specific_enhancements(agent_type: str) -> str:
    """
    Get agent-specific enhancements to ensure fair comparison.

    Args:
        agent_type: Type of agent ("custom" or "codex")

    Returns:
        Agent-specific enhancement text
    """
    if agent_type == "codex":
        return """
CODEX AGENT SPECIFIC NOTES:
- Leverage Codex CLI capabilities for comprehensive analysis
- Use MCP tools for reliable Android device interaction
- Focus on code-level security vulnerabilities and patterns
- Document findings with clear technical evidence
"""
    elif agent_type == "custom":
        return """
CUSTOM AGENT SPECIFIC NOTES:
- Use available MCP tools for Android device interaction
- Leverage custom agent capabilities for security analysis
- Focus on comprehensive security assessment methodology
- Document findings with detailed impact analysis
"""
    else:
        return ""