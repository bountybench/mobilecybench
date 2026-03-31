"""Tests for the malicious APK workflow prompt.

The prompt reuses the unified prompt and appends APK delivery instructions.
It must NOT leak benchmark internals, and MUST contain APK-specific sections.
"""

import pytest

from agent.prompts.prompts import build_malicious_apk_prompt

# Substrings that must NEVER appear (benchmark internals)
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

# APK-specific substrings that MUST appear (from the addendum)
APK_REQUIRED_SUBSTRINGS = [
    "malicious_apk_project",
    "ExploitRunner",
    "am instrument",
    "com.mobilecybench",
    "AndroidManifest.xml",
    "build.sh",
    "unprivileged",
    "finish(0",
    "finish(1",
    "INSTRUMENTATION_CODE",
]

# Unified prompt substrings that should still be present
UNIFIED_REQUIRED_SUBSTRINGS = [
    "Reflection",
    "Plan and Status",
    "Thought",
    "Log",
    "Command",
    "FinalSubmissionCommand",
    "AGENT_SERVER_PORT",
    "vulnerability",
]


@pytest.fixture
def basic_prompt():
    return build_malicious_apk_prompt(
        package_name="com.example.testapp",
        codebase_tree="src/\n  main.java",
        app_server="testserver:8080",
        username="testuser",
        password="testpass",
    )


@pytest.fixture
def prompt_no_server():
    return build_malicious_apk_prompt(
        package_name="com.example.testapp",
        codebase_tree="src/\n  main.java",
    )


class TestBannedStrings:
    @pytest.mark.parametrize("banned", BANNED_SUBSTRINGS)
    def test_banned_substring_absent(self, basic_prompt, banned):
        assert banned not in basic_prompt, f"Prompt must not contain '{banned}'"


class TestAPKRequiredStrings:
    @pytest.mark.parametrize("required", APK_REQUIRED_SUBSTRINGS)
    def test_apk_substring_present(self, basic_prompt, required):
        assert required in basic_prompt, f"Prompt must contain '{required}'"


class TestUnifiedRequiredStrings:
    @pytest.mark.parametrize("required", UNIFIED_REQUIRED_SUBSTRINGS)
    def test_unified_substring_present(self, basic_prompt, required):
        assert required in basic_prompt, f"Prompt must contain '{required}'"


class TestConditionalSections:
    def test_includes_server_when_provided(self, basic_prompt):
        assert "testserver:8080" in basic_prompt

    def test_includes_credentials_when_provided(self, basic_prompt):
        assert "testuser" in basic_prompt
        assert "testpass" in basic_prompt

    def test_no_server_without_server(self, prompt_no_server):
        assert "backend server is reachable" not in prompt_no_server

    def test_no_credentials_without_user(self, prompt_no_server):
        assert "Username:" not in prompt_no_server

    def test_hping3_example_with_server(self, basic_prompt):
        """APK mode includes hping3 example when server is provided (inherited from unified)."""
        assert "hping3" in basic_prompt

    def test_codebase_tree_included(self, basic_prompt):
        assert "main.java" in basic_prompt

    def test_package_name_included(self, basic_prompt):
        assert "com.example.testapp" in basic_prompt

    def test_mandatory_text_suffix(self, basic_prompt):
        assert "IMPORTANT: On every turn" in basic_prompt


class TestConstraintClarity:
    """The addendum must clearly communicate the unprivileged APK threat model."""

    def test_no_root(self, basic_prompt):
        assert "NO root access" in basic_prompt

    def test_victim_logged_in(self, basic_prompt):
        assert "victim account" in basic_prompt

    def test_replay_rebuilds_from_source(self, basic_prompt):
        assert "built from source" in basic_prompt

    def test_no_shell_in_replay(self, basic_prompt):
        assert "no shell scripts, no ADB commands" in basic_prompt
