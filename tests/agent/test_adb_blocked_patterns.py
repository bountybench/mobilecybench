"""Tests for ADB blocked pattern enforcement.

Covers both is_adb_command_allowed() (runtime command validation) and
check_shell_script_content() (static exploit.sh validation), ensuring that
BLOCKED_SERVICES are only matched in ADB command context — not in paths or
variable names.
"""

import pytest

from agent.custom.backend.docker_ops import check_shell_script_content, is_adb_command_allowed

# ---------------------------------------------------------------------------
# is_adb_command_allowed  (runtime, single-command validation)
# ---------------------------------------------------------------------------


class TestIsAdbCommandAllowed:
    """Runtime check — every ADB command goes through this before execution."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "adb root",
            "adb  root",
            "adb backup",
            "adb unroot",
        ],
    )
    def test_blocked_services(self, cmd):
        assert is_adb_command_allowed(cmd) is False

    @pytest.mark.parametrize(
        "cmd",
        [
            "adb shell su",
            "adb shell /system/xbin/su",
            "adb shell /system/bin/su",
            "adb shell run-as com.example",
        ],
    )
    def test_blocked_shell_patterns(self, cmd):
        assert is_adb_command_allowed(cmd) is False

    @pytest.mark.parametrize(
        "cmd",
        [
            "adb shell ls /sdcard",
            "adb install app.apk",
            "adb push exploit.sh /data/local/tmp/",
            "adb shell pm list packages",
        ],
    )
    def test_allowed_commands(self, cmd):
        assert is_adb_command_allowed(cmd) is True


# ---------------------------------------------------------------------------
# check_shell_script_content  (static script validation)
# ---------------------------------------------------------------------------


class TestCheckShellScriptContent:
    """Static validation of exploit.sh — must avoid false positives on paths."""

    # -- Should be BLOCKED in scripts ---

    def test_blocks_adb_root_in_script(self):
        script = "adb root\nadb shell ls /data\n"
        allowed, violations = check_shell_script_content(script)
        assert not allowed
        assert len(violations) == 1
        assert violations[0]["matched_pattern"] == "adb root"

    def test_blocks_adb_backup_in_script(self):
        script = "adb backup -all\n"
        allowed, violations = check_shell_script_content(script)
        assert not allowed
        assert violations[0]["matched_pattern"] == "adb backup"

    def test_blocks_su_in_script(self):
        script = 'su -c "id"\n'
        allowed, violations = check_shell_script_content(script)
        assert not allowed
        assert violations[0]["matched_pattern"] == r"\bsu\b"

    def test_blocks_run_as_in_script(self):
        script = "adb shell run-as com.example cat db\n"
        allowed, violations = check_shell_script_content(script)
        assert not allowed

    # -- Should be ALLOWED in scripts (false-positive regression tests) ---

    def test_allows_root_in_path(self):
        """'/root/.android-sdk' must not be blocked (termux exploit)."""
        script = "adb push exploit.apk /root/.android-sdk/platform-tools/\n"
        allowed, violations = check_shell_script_content(script)
        assert allowed, f"False positive: {violations}"

    def test_allows_backup_in_variable_name(self):
        """'BACKUP_DIR=...' must not be blocked (openvpn exploit)."""
        script = 'BACKUP_DIR="/sdcard/Download/backup"\n'
        allowed, violations = check_shell_script_content(script)
        assert allowed, f"False positive: {violations}"

    def test_allows_backup_in_path(self):
        script = "cp /data/data/com.app/backup/db.sqlite3 /sdcard/\n"
        allowed, violations = check_shell_script_content(script)
        assert allowed, f"False positive: {violations}"

    def test_allows_root_in_variable(self):
        script = 'ROOT_CERT="/sdcard/cert.pem"\n'
        allowed, violations = check_shell_script_content(script)
        assert allowed, f"False positive: {violations}"

    def test_skips_comments(self):
        script = "# adb root\n# su\nadb shell ls\n"
        allowed, violations = check_shell_script_content(script)
        assert allowed

    def test_skips_blank_lines(self):
        script = "\n\nadb shell ls\n\n"
        allowed, violations = check_shell_script_content(script)
        assert allowed

    def test_mixed_script_only_flags_violations(self):
        script = (
            "#!/bin/bash\n"
            "# Setup\n"
            'BACKUP_DIR="/sdcard/backup"\n'
            "adb push exploit.sh /root/.local/\n"
            "adb shell chmod +x /data/local/tmp/exploit.sh\n"
            "adb root\n"  # <- this line should be caught
        )
        allowed, violations = check_shell_script_content(script)
        assert not allowed
        assert len(violations) == 1
        assert violations[0]["line_number"] == 6
        assert violations[0]["matched_pattern"] == "adb root"
