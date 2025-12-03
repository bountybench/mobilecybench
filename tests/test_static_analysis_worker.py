"""
Unit tests for static_analysis_worker.py

Tests the static analysis worker configuration and utilities.
"""

import pytest

from agent.hierarchical_agent.static_analysis_worker import (
    STATIC_ANALYSIS_SYSTEM_PROMPT,
    create_static_analysis_worker_prompt,
)


class TestStaticAnalysisConfiguration:
    """Test suite for static analysis worker configuration."""

    def test_static_analysis_system_prompt_exists(self):
        """Test that system prompt is defined."""
        assert STATIC_ANALYSIS_SYSTEM_PROMPT is not None
        assert len(STATIC_ANALYSIS_SYSTEM_PROMPT) > 0

    def test_static_analysis_prompt_contains_key_instructions(self):
        """Test that prompt contains essential instructions."""
        prompt = STATIC_ANALYSIS_SYSTEM_PROMPT

        # Check for workflow steps
        assert "Semgrep" in prompt
        assert "MobSF" in prompt or "mobsfscan" in prompt.lower()
        assert "QARK" in prompt
        assert "static_vuln_reports" in prompt
        assert "vulnerabilities" in prompt.lower()
        assert "attack vectors" in prompt.lower()
        assert "exploit" in prompt.lower()

        # Check for analysis requirements
        assert "deep analysis" in prompt.lower() or "Deep Analysis" in prompt
        assert "code snippet" in prompt.lower()
        assert "HIGH SEVERITY" in prompt

    def test_static_analysis_prompt_output_format(self):
        """Test that prompt specifies output format."""
        prompt = STATIC_ANALYSIS_SYSTEM_PROMPT

        # Should specify structured output format
        assert "Location:" in prompt
        assert "Code Snippet:" in prompt
        assert "Attack Scenarios:" in prompt
        assert "Exploitability:" in prompt
        assert "Verdict:" in prompt

    def test_prompt_mentions_deduplication(self):
        """Prompt should mention deduping / tracking covered findings."""
        prompt = STATIC_ANALYSIS_SYSTEM_PROMPT
        assert "deduplicate" in prompt.lower() or "avoid re-analyzing" in prompt.lower()
        assert "track" in prompt.lower() or "checklist" in prompt.lower()


class TestStaticAnalysisPromptGeneration:
    """Test suite for prompt generation function."""

    def test_create_prompt_basic(self):
        """Test basic prompt generation."""
        task = "Analyze the codebase for vulnerabilities"
        prompt = create_static_analysis_worker_prompt(task)

        assert task in prompt
        assert "Semgrep" in prompt
        assert "Configuration:" in prompt

    def test_create_prompt_with_context(self):
        """Test prompt generation with context."""
        task = "Analyze codebase"
        context = {
            "target_path": "./test_codebase",
            "semgrep_config": "p/security-audit",
            "severity": ["ERROR"],
            "exclude": ["tests/*"],
        }

        prompt = create_static_analysis_worker_prompt(task, context)

        assert "./test_codebase" in prompt
        assert "p/security-audit" in prompt
        assert "['ERROR']" in prompt
        assert "['tests/*']" in prompt

    def test_create_prompt_default_values(self):
        """Test prompt generation with default values."""
        task = "Analyze codebase"
        prompt = create_static_analysis_worker_prompt(task)

        # Should contain defaults
        assert "." in prompt  # Default target path
        assert "auto" in prompt  # Default semgrep config

    def test_create_prompt_contains_mission(self):
        """Test that generated prompt contains mission statement."""
        task = "Test task"
        prompt = create_static_analysis_worker_prompt(task, None)

        assert "Your Mission:" in prompt or "Task from Supervisor:" in prompt
        assert "HIGH SEVERITY" in prompt
        assert "REJECT" in prompt

    def test_create_prompt_contains_validation_instructions(self):
        """Test that prompt includes validation instructions."""
        task = "Test task"
        prompt = create_static_analysis_worker_prompt(task)

        assert "Exploit Worker" in prompt
        assert "validation" in prompt.lower()
        assert "attack vectors" in prompt.lower()


class TestStaticAnalysisIntegration:
    """Test suite for static analysis worker integration."""

    def test_system_prompt_high_severity_focus(self):
        """Test that system prompt emphasizes high severity vulnerabilities."""
        prompt = STATIC_ANALYSIS_SYSTEM_PROMPT

        # Should emphasize high severity
        high_severity_mentions = prompt.count("HIGH SEVERITY")
        assert high_severity_mentions >= 2

        # Should mention rejection of low-impact
        assert "REJECT" in prompt or "reject" in prompt
        assert "low-impact" in prompt.lower() or "low impact" in prompt.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
