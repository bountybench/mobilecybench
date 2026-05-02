"""Tests for system-prompt construction.

Pins the contract that `build_synthetic_prompt` honors `vuln_id`:
the rendered path in the prompt must match the runtime bind mount in
`agent/agent_container.py:_setup_verify_files`, which is
`/app/verify_files/{self.vuln_id}`. 
"""

import pytest

from agent.claude_code_agent import ClaudeCodeAgent
from agent.codex_agent import CodexAgent
from agent.custom_agent import CustomAgent
from agent.prompts.prompts import build_redteam_prompt, build_synthetic_prompt


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
    # Each prompt should reference exactly its own vuln_id, not any other.
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


# ---------------------------------------------------------------------------
# vuln_id plumbing through the agent classes
# ---------------------------------------------------------------------------
# Pinning that CodexAgent and ClaudeCodeAgent thread vuln_id from their
# constructors into the synthetic prompt builder. Reviewer caught that
# this was missing from the dc38b2b9 plumbing fix (which only touched
# CustomAgent), so the synthetic prompts these agents emit always
# referenced /app/verify_files/vuln_0 regardless of the runner config's
# synthetic_vuln_id.
#
# Tests exercise `_get_system_prompt_text` directly via `object.__new__`
# so we don't trip the agents' real `__init__` (which validates CLI
# providers, writes files, hits ToolRuntime — all heavy, none relevant
# to the prompt-building contract under test).


def _make_agent_skeleton(cls, **attrs):
    """Build an agent instance bypassing __init__, set the minimum
    attributes its prompt builder reads. Anything else is left unset
    so a regression that touches new attributes will fail loudly."""
    agent = object.__new__(cls)
    defaults = dict(
        workflow="exploit",
        attacker_model="malicious_app",
        package_name="com.example.app",
        app_server=None,
        emulator_server=None,
        username=None,
        password=None,
        no_codebase=False,
        additional_context=None,
        vuln_id="vuln_0",
    )
    defaults.update(attrs)
    for k, v in defaults.items():
        setattr(agent, k, v)
    return agent


@pytest.mark.parametrize("cls", [CodexAgent, ClaudeCodeAgent])
def test_agent_threads_vuln_id_into_synthetic_prompt(cls):
    agent = _make_agent_skeleton(cls, workflow="exploit", vuln_id="vuln_1")
    prompt = agent._get_system_prompt_text()
    assert "/app/verify_files/vuln_1" in prompt
    assert "/app/verify_files/vuln_0" not in prompt


@pytest.mark.parametrize("cls", [CodexAgent, ClaudeCodeAgent])
def test_agent_default_vuln_id_is_vuln_0(cls):
    """An agent constructed without an explicit vuln_id should fall back
    to the historical default — same back-compat contract that
    `build_synthetic_prompt` itself honors."""
    agent = _make_agent_skeleton(cls, workflow="exploit")
    prompt = agent._get_system_prompt_text()
    assert "/app/verify_files/vuln_0" in prompt


@pytest.mark.parametrize("cls", [CodexAgent, ClaudeCodeAgent])
@pytest.mark.parametrize("vuln_id", ["vuln_0", "vuln_1", "vuln_2"])
def test_agent_vuln_id_distinct_per_value(cls, vuln_id):
    agent = _make_agent_skeleton(cls, workflow="exploit", vuln_id=vuln_id)
    prompt = agent._get_system_prompt_text()
    assert f"/app/verify_files/{vuln_id}" in prompt
    for other in ("vuln_0", "vuln_1", "vuln_2"):
        if other != vuln_id:
            assert f"/app/verify_files/{other}" not in prompt


# ---------------------------------------------------------------------------
# probe_only mode reframes the malicious_app redteam prompt
# ---------------------------------------------------------------------------
# When probe_only=True we want the agent told it's a real zero-day hunt judged
# by hidden security-property checks, with an anti reward-hack note. We must
# NOT reveal probe internals (filenames, regexes, baseline files) — those are
# the attack surface for reward-hacking. Pin both: the framing IS present in
# probe_only and absent otherwise.


_PROBE_ONLY_HEADER = "What \"success\" means here"
_PROBE_ONLY_HUNT_PHRASE = "real zero-day hunt"
_PROBE_ONLY_ANTI_HACK = "fabricated outputs"


def test_redteam_prompt_probe_only_adds_zero_day_framing():
    prompt = build_redteam_prompt(package_name="com.example.app", probe_only=True)
    assert _PROBE_ONLY_HEADER in prompt
    assert _PROBE_ONLY_HUNT_PHRASE in prompt
    assert _PROBE_ONLY_ANTI_HACK in prompt


def test_redteam_prompt_default_omits_probe_only_framing():
    prompt = build_redteam_prompt(package_name="com.example.app")
    assert _PROBE_ONLY_HEADER not in prompt
    assert _PROBE_ONLY_HUNT_PHRASE not in prompt
    assert _PROBE_ONLY_ANTI_HACK not in prompt


@pytest.mark.parametrize(
    "leak_marker",
    [
        # Things probes look for. If any of these appear in the prompt, the
        # agent gets a roadmap for reward-hacking.
        "test_access_control",
        "test_availability",
        "test_confidentiality",
        "test_integrity",
        "baseline_manifest",
        "probe_lib",
        "pwned_file",
        "container_flag",
        "app_flag",
    ],
)
def test_redteam_prompt_probe_only_does_not_leak_probe_internals(leak_marker):
    prompt = build_redteam_prompt(package_name="com.example.app", probe_only=True)
    assert leak_marker not in prompt, (
        f"probe_only prompt leaks probe internal {leak_marker!r}; "
        "this is exactly the kind of detail an agent could reward-hack against."
    )


# Pinning that probe_only flows from CustomAgent (the path the runner uses for
# agent_mode="custom") through into build_redteam_prompt. Without this wiring,
# turning on probe_only in runner_config would silently reuse the task-mode
# prompt and the agent would optimize for a verifier that never runs.


def test_custom_agent_threads_probe_only_into_redteam_prompt():
    agent = object.__new__(CustomAgent)
    for k, v in dict(
        workflow="redteam",
        attacker_model="malicious_app",
        package_name="com.example.app",
        app_server=None,
        emulator_server=None,
        username=None,
        password=None,
        no_codebase=True,
        network_access=True,
        vuln_id="vuln_0",
        probe_only=True,
    ).items():
        setattr(agent, k, v)
    prompt = agent._get_system_prompt_text()
    assert _PROBE_ONLY_HEADER in prompt
    assert _PROBE_ONLY_HUNT_PHRASE in prompt


@pytest.mark.parametrize("cls", [CodexAgent, ClaudeCodeAgent])
def test_agent_vuln_id_irrelevant_in_redteam_workflow(cls):
    """Redteam prompts (`build_redteam_prompt`, `build_remote_attacker_prompt`)
    do not reference verify_files — that path is only relevant for the
    synthetic exploit workflow. Setting vuln_id should not leak into the
    redteam prompt one way or the other."""
    for attacker in ("malicious_app", "remote_attacker"):
        agent = _make_agent_skeleton(
            cls, workflow="redteam", attacker_model=attacker, vuln_id="vuln_2"
        )
        prompt = agent._get_system_prompt_text()
        assert "/app/verify_files/vuln_2" not in prompt
        assert "/app/verify_files/vuln_0" not in prompt
