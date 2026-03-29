"""Tests for the unified workflow prompt.

The unified prompt must NOT leak any benchmark-internal details to the agent.
"""

import pytest

from agent.prompts.prompts import build_unified_prompt

# Substrings that must NEVER appear in the unified prompt
BANNED_SUBSTRINGS = [
    "ssrf-probe",
    "run_checks.sh",
    "security.patch",
    "hardened",
    "generic probe",
    "generic_scores",
    "scores.json",
    "detection_scores",
]

# Substrings that MUST appear in the unified prompt
REQUIRED_SUBSTRINGS = [
    "exploit.sh",
    "/app/agent_exploit/",
    "vulnerability",
    "Reflection",
    "Plan and Status",
    "Thought",
    "Log",
    "Command",
    "FinalSubmissionCommand",
    "AGENT_SERVER_PORT",
]


@pytest.fixture
def basic_prompt():
    return build_unified_prompt(
        package_name="com.example.testapp",
        codebase_tree="src/\n  main.java",
        app_server="testserver:8080",
        username="testuser",
        password="testpass",
    )


@pytest.fixture
def prompt_no_server():
    return build_unified_prompt(
        package_name="com.example.testapp",
        codebase_tree="src/\n  main.java",
    )


class TestUnifiedPromptBannedStrings:
    @pytest.mark.parametrize("banned", BANNED_SUBSTRINGS)
    def test_banned_substring_absent(self, basic_prompt, banned):
        assert banned not in basic_prompt, f"Unified prompt must not contain '{banned}'"

    @pytest.mark.parametrize("banned", BANNED_SUBSTRINGS)
    def test_banned_substring_absent_no_server(self, prompt_no_server, banned):
        assert banned not in prompt_no_server


class TestUnifiedPromptRequiredStrings:
    @pytest.mark.parametrize("required", REQUIRED_SUBSTRINGS)
    def test_required_substring_present(self, basic_prompt, required):
        assert required in basic_prompt, f"Unified prompt must contain '{required}'"


class TestUnifiedPromptConditionalSections:
    def test_includes_server_access_when_provided(self, basic_prompt):
        assert "testserver:8080" in basic_prompt

    def test_includes_credentials_when_provided(self, basic_prompt):
        assert "testuser" in basic_prompt
        assert "testpass" in basic_prompt

    def test_no_server_access_without_server(self, prompt_no_server):
        assert "backend server is reachable" not in prompt_no_server

    def test_no_credentials_without_user(self, prompt_no_server):
        assert "Username:" not in prompt_no_server

    def test_includes_target_host_example_with_server(self, basic_prompt):
        assert "hping3 testserver" in basic_prompt

    def test_no_target_host_example_without_server(self, prompt_no_server):
        assert "hping3" not in prompt_no_server

    def test_no_root_constraint_present(self, basic_prompt):
        assert "No Root Dependencies" in basic_prompt
        assert "su, sudo" in basic_prompt

    def test_codebase_tree_included(self, basic_prompt):
        assert "main.java" in basic_prompt

    def test_package_name_included(self, basic_prompt):
        assert "com.example.testapp" in basic_prompt

    def test_mandatory_text_suffix(self, basic_prompt):
        assert "IMPORTANT: On every turn" in basic_prompt
