"""Tests for the auth_attacker prompt builder."""

import pytest

from agent.prompts.prompts import build_auth_attacker_prompt, build_redteam_prompt


@pytest.fixture
def prompt():
    return build_auth_attacker_prompt(
        package_name="com.example.app",
        codebase_tree="src/...",
        app_server="http://server:8080",
        emulator_server="http://10.0.2.2:8080",
        username="attacker_user",
        password="attacker_pass",
    )


class TestAuthAttackerPromptContent:
    """Verify auth_attacker prompt has correct role framing and deliverables."""

    def test_frames_as_rogue_user(self, prompt):
        assert "rogue authenticated user" in prompt

    def test_deliverable_is_exploit_sh(self, prompt):
        assert "exploit.sh" in prompt
        assert "exploit_apk" not in prompt

    def test_attacker_credentials_present(self, prompt):
        assert "attacker_user" in prompt
        assert "attacker_pass" in prompt

    def test_credentials_labeled_as_attacker(self, prompt):
        assert "YOUR credentials (the attacker)" in prompt

    def test_no_victim_credentials(self, prompt):
        """The prompt must not reveal the victim's credentials."""
        assert "victim" in prompt.lower()  # mentions victim concept
        # But should NOT contain any second set of actual credentials
        # (only the attacker's credentials are passed to the builder)

    def test_separate_devices_constraint(self, prompt):
        """Prompt frames attacker/victim as separate devices sharing only backend."""
        assert "separate devices" in prompt.lower()

    def test_server_side_persistence(self, prompt):
        assert (
            "stored server-side" in prompt.lower()
            or "persistent effect on the backend" in prompt.lower()
        )

    def test_no_env_vars_for_credentials(self, prompt):
        """Prompt must tell agent to hardcode credentials — container gets none."""
        assert "No credentials" in prompt or "No environment variables" in prompt

    def test_no_pipeline_internals(self, prompt):
        """Prompt must not leak pipeline internals (pm clear, probe details)."""
        assert "pm clear" not in prompt
        assert "probes check" not in prompt.lower()
        # Agent SHOULD know a victim uses the app, but not HOW (prepare_victim.sh, etc.)
        assert "prepare_victim" not in prompt

    def test_not_biased_toward_specific_vuln(self, prompt):
        """Prompt should describe threat model broadly, not steer toward a single vuln class."""
        # Should mention multiple vuln categories
        assert (
            "authorization" in prompt.lower()
            or "privilege escalation" in prompt.lower()
        )
        assert "injection" in prompt.lower()
        assert "idor" in prompt.lower()
        # XSS may appear as one example among many, but should not dominate
        assert prompt.lower().count("xss") <= 2

    def test_forbidden_actions(self, prompt):
        for forbidden in ["root", "su", "sudo", "run-as"]:
            assert forbidden in prompt

    def test_no_root_constraint(self, prompt):
        assert "CANNOT" in prompt


class TestAuthAttackerVsMaliciousApk:
    """Ensure the two redteam prompts are distinct where they should be."""

    def test_different_descriptions(self):
        aa = build_auth_attacker_prompt("com.x", "tree")
        mapk = build_redteam_prompt("com.x", "tree")
        # Both should mention the package name but have different framing
        assert "rogue authenticated user" in aa
        assert "rogue authenticated user" not in mapk
        assert "malicious APK" in mapk
        assert "malicious APK" not in aa

    def test_same_signature(self):
        """Both builders accept the same kwargs — they're interchangeable."""
        kwargs = dict(
            package_name="com.x",
            codebase_tree="tree",
            app_server="http://s:80",
            emulator_server="http://10.0.2.2:80",
            username="u",
            password="p",
        )
        aa = build_auth_attacker_prompt(**kwargs)
        mapk = build_redteam_prompt(**kwargs)
        assert isinstance(aa, str) and len(aa) > 100
        assert isinstance(mapk, str) and len(mapk) > 100
