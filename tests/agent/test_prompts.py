"""Tests for system-prompt construction.

Pins the contract that ``build_synthetic_prompt`` honors ``vuln_id``: the
rendered path in the prompt must match the runtime bind mount in
``agent/runtime/container.py:_setup_verify_files`` (``/app/verify_files/{vuln_id}``).

The agent-class wrapper tests (``CodexAgent._get_system_prompt_text``,
``ClaudeCodeAgent._get_system_prompt_text``) were removed in the BYO-contract
consolidation. Those wrappers are gone; the prompt is built directly by
``workflows/base.py:Workflow._build_agent_prompt`` and passed via task.json.
``build_synthetic_prompt`` is the single source of truth and is covered here.
"""

from agent.prompts.prompts import build_synthetic_prompt


def test_synthetic_prompt_renders_provided_vuln_id():
    prompt = build_synthetic_prompt(
        package_name="com.example.app",
        vuln_id="vuln_1",
    )
    assert "/app/verify_files/vuln_1" in prompt
    assert "/app/verify_files/vuln_0" not in prompt


def test_synthetic_prompt_default_is_vuln_0_for_back_compat():
    """If a caller forgets to pass vuln_id, fall back to vuln_0 — matches
    the historic default and the most common selector in the test suite."""
    prompt = build_synthetic_prompt(package_name="com.example.app")
    assert "/app/verify_files/vuln_0" in prompt


def test_synthetic_prompt_distinct_per_vuln_id():
    prompts = {
        vuln_id: build_synthetic_prompt(package_name="com.example.app", vuln_id=vuln_id)
        for vuln_id in ("vuln_0", "vuln_1", "vuln_2")
    }
    for vuln_id, p in prompts.items():
        assert f"/app/verify_files/{vuln_id}" in p
        for other in prompts:
            if other != vuln_id:
                assert f"/app/verify_files/{other}" not in p


def test_synthetic_prompt_renders_vuln_id_in_both_locations():
    """The prompt mentions the verify_files path twice — once in the
    resource bullets and once in the step list. Both must use the
    selected vuln_id."""
    prompt = build_synthetic_prompt(
        package_name="com.example.app",
        vuln_id="vuln_2",
    )
    occurrences = prompt.count("/app/verify_files/vuln_2")
    assert (
        occurrences == 2
    ), f"expected 2 references to /app/verify_files/vuln_2, got {occurrences}"
