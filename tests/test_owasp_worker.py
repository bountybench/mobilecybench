"""
Unit tests for owasp_worker.py

Tests the OWASP Mobile Top 10 worker configuration and utilities.
"""

import pytest

from agent.hierarchical_agent.owasp_worker import (
    OWASP_WORKER_SYSTEM_PROMPT,
    create_owasp_worker_prompt,
    create_owasp_worker_system_prompt,
)


class TestOWASPWorkerConfiguration:
    """Test suite for OWASP worker configuration."""

    def test_owasp_worker_system_prompt_exists(self):
        """Test that system prompt is defined."""
        assert OWASP_WORKER_SYSTEM_PROMPT is not None
        assert len(OWASP_WORKER_SYSTEM_PROMPT) > 0

    def test_owasp_worker_prompt_contains_key_instructions(self):
        """Test that prompt contains essential instructions."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Check for OWASP categories
        assert "OWASP Mobile Top 10" in prompt
        assert "M1:" in prompt
        assert "M10:" in prompt

        # Check for analysis requirements
        assert "vulnerabilities" in prompt.lower()
        assert "attack vectors" in prompt.lower()
        assert "exploit" in prompt.lower()
        assert "HIGH SEVERITY" in prompt

    def test_owasp_worker_prompt_all_categories(self):
        """Test that prompt lists all 10 OWASP categories."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        categories = [
            "M1: Improper Credential Usage",
            "M2: Inadequate Supply Chain Security",
            "M3: Insecure Authentication/Authorization",
            "M4: Insufficient Input/Output Validation",
            "M5: Insecure Communication",
            "M6: Inadequate Privacy Controls",
            "M7: Insufficient Binary Protections",
            "M8: Security Misconfiguration",
            "M9: Insecure Data Storage",
            "M10: Insufficient Cryptography",
        ]

        for category in categories:
            assert category in prompt

    def test_owasp_worker_search_strategy_examples(self):
        """Test that prompt includes search strategy examples."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Should include grep/find examples
        assert "grep" in prompt.lower()
        assert "find" in prompt.lower()

        # Should include examples for specific categories
        assert "For M1" in prompt or "M1:" in prompt
        assert "For M4" in prompt or "M4:" in prompt
        assert "For M9" in prompt or "M9:" in prompt

    def test_owasp_worker_prompt_output_format(self):
        """Test that prompt specifies output format."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Should specify structured output format (same as static analysis)
        assert "Location:" in prompt
        assert "Code Snippet:" in prompt
        assert "Attack Scenarios:" in prompt
        assert "Exploitability:" in prompt
        assert "Verdict:" in prompt

    def test_owasp_worker_verdict_format(self):
        """Test that verdict section matches static analysis format."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Should have same verdict options as static analysis
        assert "CONFIRMED HIGH SEVERITY" in prompt
        assert "NEEDS VALIDATION" in prompt

        # Should NOT have REJECT option
        assert "REJECT - LOW IMPACT" not in prompt


class TestOWASPWorkerPromptGeneration:
    """Test suite for OWASP worker prompt generation."""

    def test_create_prompt_basic(self):
        """Test basic prompt generation."""
        task = "M9: Insecure Data Storage"
        prompt = create_owasp_worker_prompt(task)

        assert task in prompt
        assert "OWASP Mobile Top 10" in prompt
        assert "Configuration:" in prompt

    def test_create_prompt_with_context(self):
        """Test prompt generation with context."""
        task = "M4: Insufficient Input/Output Validation"
        context = {
            "target_path": "/test/codebase",
        }

        prompt = create_owasp_worker_prompt(task, context)

        assert "/test/codebase" in prompt
        assert task in prompt

    def test_create_prompt_default_values(self):
        """Test prompt generation with default values."""
        task = "M1: Improper Credential Usage"
        prompt = create_owasp_worker_prompt(task)

        # Should contain default target path
        assert "/app/codebase" in prompt

    def test_create_prompt_contains_mission(self):
        """Test that generated prompt contains mission statement."""
        task = "M5: Insecure Communication"
        prompt = create_owasp_worker_prompt(task)

        assert "Your Mission:" in prompt or "Task from Supervisor:" in prompt
        assert "HIGH SEVERITY" in prompt
        # Should NOT tell agents to report rejected vulnerabilities
        assert "REJECT - LOW IMPACT" not in prompt

    def test_create_prompt_search_instructions(self):
        """Test that prompt includes search approach."""
        task = "M9: Insecure Data Storage"
        prompt = create_owasp_worker_prompt(task)

        assert "Search Approach:" in prompt or "search" in prompt.lower()
        assert "grep" in prompt.lower()
        assert "find" in prompt.lower()


class TestOWASPWorkerSystemPromptCustomization:
    """Test suite for category-specific system prompt generation."""

    def test_create_customized_system_prompt(self):
        """Test creating customized system prompt for specific category."""
        category = "M9: Insecure Data Storage"
        prompt = create_owasp_worker_system_prompt(category)

        # Should include base prompt
        assert "OWASP Mobile Top 10" in prompt

        # Should include category assignment
        assert "ASSIGNED CATEGORY" in prompt or category in prompt
        assert category in prompt

    def test_create_customized_system_prompt_all_categories(self):
        """Test creating customized prompts for all 10 categories."""
        categories = [
            "M1: Improper Credential Usage",
            "M2: Inadequate Supply Chain Security",
            "M3: Insecure Authentication/Authorization",
            "M4: Insufficient Input/Output Validation",
            "M5: Insecure Communication",
            "M6: Inadequate Privacy Controls",
            "M7: Insufficient Binary Protections",
            "M8: Security Misconfiguration",
            "M9: Insecure Data Storage",
            "M10: Insufficient Cryptography",
        ]

        for category in categories:
            prompt = create_owasp_worker_system_prompt(category)
            assert category in prompt
            assert len(prompt) > len(OWASP_WORKER_SYSTEM_PROMPT)


class TestOWASPWorkerIntegration:
    """Test suite for OWASP worker integration."""

    def test_system_prompt_high_severity_focus(self):
        """Test that system prompt emphasizes high severity vulnerabilities."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Should emphasize high severity
        high_severity_mentions = prompt.count("HIGH SEVERITY")
        assert high_severity_mentions >= 2

        # Should mention silently skipping low-impact
        assert "silently skip" in prompt.lower() or "Silently skip" in prompt

    def test_system_prompt_codebase_analysis(self):
        """Test that system prompt focuses on direct codebase analysis."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Should analyze codebase directly (not semgrep_results.json)
        assert "grep" in prompt.lower()
        assert "semgrep_results.json" not in prompt

        # Should mention execute_command for searching
        assert "execute_command" in prompt

    def test_no_reject_documentation_instructions(self):
        """Test that prompt does not instruct agents to document rejected findings."""
        prompt = OWASP_WORKER_SYSTEM_PROMPT

        # Should NOT tell agents to document rejections
        assert "[REJECT" not in prompt

        # Should tell agents to skip silently
        assert "silently skip" in prompt.lower() or "Silently skip" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
