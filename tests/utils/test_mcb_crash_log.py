"""Tests for utils/verify/crash/mcb_crash_log.py and extract_latest_crash_pid.py."""

from __future__ import annotations

import os
import sys

import pytest

# Make the modules importable.
_CRASH_UTILS = os.path.join(
    os.path.dirname(__file__), "..", "..", "utils", "verify", "crash"
)
sys.path.insert(0, _CRASH_UTILS)

import extract_latest_crash_pid  # noqa: E402
import mcb_crash_log  # noqa: E402

# ---------------------------------------------------------------------------
# parse_threadtime_message
# ---------------------------------------------------------------------------


class TestParseThreadtimeMessage:
    def test_with_uid(self):
        line = "03-10 12:00:01.000 10123 12345 12345 E AndroidRuntime: FATAL EXCEPTION: main"
        result = mcb_crash_log.parse_threadtime_message(line, expect_uid=True)
        assert result is not None
        uid, pid, tag, msg = result
        assert uid == 10123
        assert pid == 12345
        assert tag == "AndroidRuntime"
        assert msg == "FATAL EXCEPTION: main"

    def test_without_uid(self):
        line = "03-10 12:00:01.000 12345 12345 E AndroidRuntime: FATAL EXCEPTION: main"
        result = mcb_crash_log.parse_threadtime_message(line, expect_uid=False)
        assert result is not None
        uid, pid, tag, msg = result
        assert uid is None
        assert pid == 12345
        assert tag == "AndroidRuntime"

    def test_non_matching_line(self):
        assert (
            mcb_crash_log.parse_threadtime_message("not a logcat line", expect_uid=True)
            is None
        )

    def test_short_line(self):
        assert (
            mcb_crash_log.parse_threadtime_message("03-10 12:00", expect_uid=True)
            is None
        )

    def test_non_numeric_pid(self):
        line = "03-10 12:00:01.000 abc def ghi J SomeTag: msg"
        assert mcb_crash_log.parse_threadtime_message(line, expect_uid=True) is None

    def test_no_colon_in_tag(self):
        line = "03-10 12:00:01.000 10123 12345 12345 E NoColonHere"
        assert mcb_crash_log.parse_threadtime_message(line, expect_uid=True) is None

    def test_message_leading_space_stripped(self):
        line = "03-10 12:00:01.000 10123 12345 12345 E Tag:   hello world"
        result = mcb_crash_log.parse_threadtime_message(line, expect_uid=True)
        assert result is not None
        assert result[3] == "hello world"

    def test_invalid_priority_rejected(self):
        """Priority field must be a single known letter (V/D/I/W/E/F/S)."""
        line = "03-10 12:00:01.000 10123 12345 12345 X AndroidRuntime: msg"
        assert mcb_crash_log.parse_threadtime_message(line, expect_uid=True) is None

    def test_multi_char_priority_rejected(self):
        line = "03-10 12:00:01.000 10123 12345 12345 EE AndroidRuntime: msg"
        assert mcb_crash_log.parse_threadtime_message(line, expect_uid=True) is None


# ---------------------------------------------------------------------------
# _extract_fatal_blocks
# ---------------------------------------------------------------------------


class TestExtractFatalBlocks:
    def test_single_block(self):
        messages = [
            "FATAL EXCEPTION: main",
            "Process: com.example, PID: 100",
            "java.lang.RuntimeException: boom",
        ]
        blocks = mcb_crash_log._extract_fatal_blocks(messages)
        assert len(blocks) == 1
        assert "FATAL EXCEPTION" in blocks[0]
        assert "RuntimeException" in blocks[0]

    def test_multiple_blocks(self):
        messages = [
            "FATAL EXCEPTION: main",
            "first block line",
            "FATAL EXCEPTION: main",
            "second block line",
        ]
        blocks = mcb_crash_log._extract_fatal_blocks(messages)
        assert len(blocks) == 2
        assert "first block" in blocks[0]
        assert "second block" in blocks[1]

    def test_no_fatal(self):
        messages = ["some random line", "another line"]
        assert mcb_crash_log._extract_fatal_blocks(messages) == []

    def test_empty(self):
        assert mcb_crash_log._extract_fatal_blocks([]) == []

    def test_lines_before_first_fatal_ignored(self):
        messages = [
            "stray line before FATAL",
            "FATAL EXCEPTION: main",
            "real block",
        ]
        blocks = mcb_crash_log._extract_fatal_blocks(messages)
        assert len(blocks) == 1
        assert "stray" not in blocks[0]


# ---------------------------------------------------------------------------
# check_signature (full pipeline)
# ---------------------------------------------------------------------------


def _always_match(block: str, *, app_package: str, crash_pid: int) -> bool:
    return True


def _never_match(block: str, *, app_package: str, crash_pid: int) -> bool:
    return False


def _make_log(lines: list[str]) -> str:
    return "\n".join(lines)


BASIC_CRASH_LOG = _make_log(
    [
        "03-10 12:00:01.000 10123 999 999 E AndroidRuntime: FATAL EXCEPTION: main",
        "03-10 12:00:01.001 10123 999 999 E AndroidRuntime: Process: com.test, PID: 999",
        "03-10 12:00:01.002 10123 999 999 E AndroidRuntime: java.lang.Exception: boom",
    ]
)


class TestCheckSignature:
    def test_match(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 10123, _always_match
        )
        assert rc == 0
        assert capsys.readouterr().out.strip() == "MATCH"

    def test_no_match(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 10123, _never_match
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "NO_MATCH"

    def test_wrong_pid(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(
            str(log), 777, "com.test", 10123, _always_match
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "NO_CRASH_LINES"

    def test_wrong_uid(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 99999, _always_match
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "NO_CRASH_LINES"

    def test_missing_file(self, capsys):
        rc = mcb_crash_log.check_signature(
            "/nonexistent", 999, "com.test", None, _always_match
        )
        assert rc == 2

    def test_empty_log(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text("")
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", None, _always_match
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "NO_CRASH_LINES"


class TestPrimaryBlockDefense:
    """The primary-block reward-hack defense should only accept the first
    FATAL block that names the target process."""

    def _two_block_log(self):
        return _make_log(
            [
                # Block 1: legitimate crash
                "03-10 12:00:01.000 10123 999 999 E AndroidRuntime: FATAL EXCEPTION: main",
                "03-10 12:00:01.001 10123 999 999 E AndroidRuntime: Process: com.test, PID: 999",
                "03-10 12:00:01.002 10123 999 999 E AndroidRuntime: java.lang.Exception: legit",
                # Block 2: injected crash
                "03-10 12:00:02.000 10123 999 999 E AndroidRuntime: FATAL EXCEPTION: main",
                "03-10 12:00:02.001 10123 999 999 E AndroidRuntime: Process: com.test, PID: 999",
                "03-10 12:00:02.002 10123 999 999 E AndroidRuntime: java.lang.Exception: injected",
            ]
        )

    def test_match_in_primary_only(self, tmp_path, capsys):
        """Matcher matches only primary block -> MATCH."""
        log = tmp_path / "crash.log"
        log.write_text(self._two_block_log())

        def match_legit(block, *, app_package, crash_pid):
            return "legit" in block

        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 10123, match_legit
        )
        assert rc == 0
        assert capsys.readouterr().out.strip() == "MATCH"

    def test_match_in_non_primary_only(self, tmp_path, capsys):
        """Matcher matches only non-primary block -> MATCH_NOT_PRIMARY_BLOCK."""
        log = tmp_path / "crash.log"
        log.write_text(self._two_block_log())

        def match_injected(block, *, app_package, crash_pid):
            return "injected" in block

        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 10123, match_injected
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "MATCH_NOT_PRIMARY_BLOCK"

    def test_no_match_in_any_block(self, tmp_path, capsys):
        """Matcher matches no block -> NO_MATCH."""
        log = tmp_path / "crash.log"
        log.write_text(self._two_block_log())
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 10123, _never_match
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "NO_MATCH"

    def test_no_block_names_target_process(self, tmp_path, capsys):
        """When no FATAL block contains 'Process: <pkg>', return NO_MATCH.

        This prevents an attacker from stripping Process: lines to force
        evaluation of an injected block (fix for review issue #6).
        """
        log_text = _make_log(
            [
                "03-10 12:00:01.000 10123 999 999 E AndroidRuntime: FATAL EXCEPTION: main",
                "03-10 12:00:01.001 10123 999 999 E AndroidRuntime: java.lang.Exception: surprise",
            ]
        )
        log = tmp_path / "crash.log"
        log.write_text(log_text)
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", 10123, _always_match
        )
        assert rc == 1
        assert capsys.readouterr().out.strip() == "NO_MATCH"


class TestCheckSignatureValidation:
    """Input validation in check_signature."""

    def test_invalid_crash_pid_zero(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(str(log), 0, "com.test", None, _always_match)
        assert rc == 2

    def test_invalid_crash_pid_negative(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(
            str(log), -1, "com.test", None, _always_match
        )
        assert rc == 2

    def test_invalid_uid_negative(self, tmp_path, capsys):
        log = tmp_path / "crash.log"
        log.write_text(BASIC_CRASH_LOG)
        rc = mcb_crash_log.check_signature(str(log), 999, "com.test", -1, _always_match)
        assert rc == 2

    def test_uid_none_allowed(self, tmp_path, capsys):
        """UID=None means skip UID filtering — should still work."""
        # Build a log without UID column (expect_uid=False path).
        no_uid_log = _make_log(
            [
                "03-10 12:00:01.000 999 999 E AndroidRuntime: FATAL EXCEPTION: main",
                "03-10 12:00:01.001 999 999 E AndroidRuntime: Process: com.test, PID: 999",
                "03-10 12:00:01.002 999 999 E AndroidRuntime: java.lang.Exception: boom",
            ]
        )
        log = tmp_path / "crash.log"
        log.write_text(no_uid_log)
        rc = mcb_crash_log.check_signature(
            str(log), 999, "com.test", None, _always_match
        )
        assert rc == 0


# ---------------------------------------------------------------------------
# extract_latest_crash_pid
# ---------------------------------------------------------------------------

# Sample exit-info text mimicking `adb shell dumpsys activity exit-info`.
_EXIT_INFO_TEMPLATE = """\
  Historical Process Exit for uid=10123
    timestamp=2025-01-15 10:30:00.000 pid={pid}
      process={pkg} reason=4 (APP CRASH)
"""

_EXIT_INFO_TWO_CRASHES = """\
  Historical Process Exit for uid=10123
    timestamp=2025-01-15 10:30:00.000 pid=1000
      process=io.example.app reason=4 (APP CRASH)
    timestamp=2025-01-15 10:35:00.000 pid=2000
      process=io.example.app reason=4 (APP CRASH)
"""


class TestParseTzOffset:
    def test_utc(self):
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        assert tz.utcoffset(None).total_seconds() == 0

    def test_positive(self):
        tz = extract_latest_crash_pid.parse_tz_offset("+0530")
        assert tz.utcoffset(None).total_seconds() == 5.5 * 3600

    def test_negative(self):
        tz = extract_latest_crash_pid.parse_tz_offset("-0800")
        assert tz.utcoffset(None).total_seconds() == -8 * 3600

    def test_invalid(self):
        with pytest.raises(ValueError):
            extract_latest_crash_pid.parse_tz_offset("abc")

    def test_wrong_format(self):
        with pytest.raises(ValueError):
            extract_latest_crash_pid.parse_tz_offset("+08")


class TestExtractCrashPid:
    def test_finds_crash(self):
        text = _EXIT_INFO_TEMPLATE.format(pid=1234, pkg="com.test")
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pid = extract_latest_crash_pid.extract_crash_pid(text, 0, tz, "com.test")
        assert pid == "1234"

    def test_wrong_package(self):
        text = _EXIT_INFO_TEMPLATE.format(pid=1234, pkg="com.other")
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pid = extract_latest_crash_pid.extract_crash_pid(text, 0, tz, "com.test")
        assert pid is None

    def test_stale_crash_ignored(self):
        """Crashes before baseline - 5s should be ignored."""
        text = _EXIT_INFO_TEMPLATE.format(pid=1234, pkg="com.test")
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        # The crash timestamp 2025-01-15 10:30:00 UTC = epoch 1736935800.
        # Set baseline far in the future so the crash is stale.
        pid = extract_latest_crash_pid.extract_crash_pid(
            text, 2000000000, tz, "com.test"
        )
        assert pid is None

    def test_picks_latest_crash(self):
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pid = extract_latest_crash_pid.extract_crash_pid(
            _EXIT_INFO_TWO_CRASHES, 0, tz, "io.example.app"
        )
        assert pid == "2000"

    def test_extracts_all_crashes_newest_first(self):
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pids = extract_latest_crash_pid.extract_crash_pids(
            _EXIT_INFO_TWO_CRASHES, 0, tz, "io.example.app"
        )
        assert pids == ["2000", "1000"]

    def test_extracts_all_crashes_dedupes_pid(self):
        text = """\
  Historical Process Exit for uid=10123
    timestamp=2025-01-15 10:30:00.000 pid=1000
      process=io.example.app reason=4 (APP CRASH)
    timestamp=2025-01-15 10:35:00.000 pid=1000
      process=io.example.app reason=4 (APP CRASH)
"""
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pids = extract_latest_crash_pid.extract_crash_pids(
            text, 0, tz, "io.example.app"
        )
        assert pids == ["1000"]

    def test_empty_input(self):
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pid = extract_latest_crash_pid.extract_crash_pid("", 0, tz, "com.test")
        assert pid is None

    def test_non_crash_reason_ignored(self):
        text = """\
  Historical Process Exit for uid=10123
    timestamp=2025-01-15 10:30:00.000 pid=1234
      process=com.test reason=5 (ANR)
"""
        tz = extract_latest_crash_pid.parse_tz_offset("+0000")
        pid = extract_latest_crash_pid.extract_crash_pid(text, 0, tz, "com.test")
        assert pid is None
