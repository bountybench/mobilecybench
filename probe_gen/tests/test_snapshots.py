"""Snapshot module unit tests.

Mocks ``subprocess.run`` so the tests run without a real emulator.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from probe_gen.pipeline.gates import GateContext
from probe_gen.pipeline.snapshots import (
    SnapshotError,
    SnapshotInfo,
    avd_snapshot_delete,
    avd_snapshot_list,
    avd_snapshot_load,
    avd_snapshot_save,
    has_snapshot,
    make_snapshot_restore_setup_hook,
)


class _FakeProc:
    """Minimal stand-in for subprocess.run's return value."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _expect_call(args: list[str]) -> list[str]:
    """Return the full adb command we expect to see."""
    return ["adb", "emu", *args]


class TestSnapshotNameValidation(unittest.TestCase):
    def test_empty_name_rejected(self) -> None:
        with self.assertRaises(SnapshotError):
            avd_snapshot_save("")

    def test_invalid_chars_rejected(self) -> None:
        for bad in ("has space", "has/slash", "has\\back", "has;semi", "öther"):
            with self.subTest(name=bad):
                with self.assertRaises(SnapshotError):
                    avd_snapshot_save(bad)

    def test_valid_names_accepted(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "OK", ""),
        ) as mock_run:
            for ok in ("warm", "warm-state", "warm_state", "warm.v1", "Warm123"):
                with self.subTest(name=ok):
                    avd_snapshot_save(ok)
            self.assertEqual(mock_run.call_count, 5)


class TestSaveLoadDelete(unittest.TestCase):
    def test_save_invokes_adb_emu(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "OK", ""),
        ) as mock_run:
            avd_snapshot_save("warm")
            args, kwargs = mock_run.call_args
            self.assertEqual(args[0], _expect_call(["avd", "snapshot", "save", "warm"]))
            self.assertEqual(kwargs.get("timeout"), 300)

    def test_load_invokes_adb_emu(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "OK", ""),
        ) as mock_run:
            avd_snapshot_load("warm")
            args, _ = mock_run.call_args
            self.assertEqual(args[0], _expect_call(["avd", "snapshot", "load", "warm"]))

    def test_delete_invokes_adb_emu(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "OK", ""),
        ) as mock_run:
            avd_snapshot_delete("warm")
            args, _ = mock_run.call_args
            self.assertEqual(args[0], _expect_call(["avd", "snapshot", "del", "warm"]))

    def test_nonzero_exit_raises(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(1, "", "snapshot already exists"),
        ):
            with self.assertRaises(SnapshotError) as ctx:
                avd_snapshot_save("warm")
            self.assertIn("snapshot already exists", str(ctx.exception))

    def test_adb_missing_raises(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            side_effect=FileNotFoundError("adb"),
        ):
            with self.assertRaises(SnapshotError) as ctx:
                avd_snapshot_save("warm")
            self.assertIn("adb not on PATH", str(ctx.exception))

    def test_timeout_raises_snapshot_error(self) -> None:
        import subprocess as _sp

        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            side_effect=_sp.TimeoutExpired(cmd="adb", timeout=10),
        ):
            with self.assertRaises(SnapshotError) as ctx:
                avd_snapshot_save("warm")
            self.assertIn("timed out", str(ctx.exception))


class TestList(unittest.TestCase):
    def test_empty_listing_no_snapshots_message(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "No snapshots\nOK", ""),
        ):
            self.assertEqual(avd_snapshot_list(), [])

    def test_empty_listing_blank_output(self) -> None:
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "OK\n", ""),
        ):
            self.assertEqual(avd_snapshot_list(), [])

    def test_list_with_two_snapshots(self) -> None:
        # Plausible adb-emu output (varies across versions; parser is permissive)
        sample = "\n".join(
            [
                "ID    NAME    SIZE    DATE",
                "1     warm    132M    2026-05-01",
                "2     vuln    140M    2026-05-01",
                "OK",
            ]
        )
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, sample, ""),
        ):
            snapshots = avd_snapshot_list()
        names = [s.name for s in snapshots]
        self.assertIn("warm", names)
        self.assertIn("vuln", names)

    def test_list_with_simple_format(self) -> None:
        sample = "warm    132M    2026-05-01\nvuln    140M    2026-05-01\nOK"
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, sample, ""),
        ):
            self.assertEqual({s.name for s in avd_snapshot_list()}, {"warm", "vuln"})

    def test_has_snapshot_true_when_present(self) -> None:
        sample = "warm    132M    2026-05-01\nOK"
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, sample, ""),
        ):
            self.assertTrue(has_snapshot("warm"))
            self.assertFalse(has_snapshot("vuln"))


class TestSetupHook(unittest.TestCase):
    def test_hook_calls_load(self) -> None:
        hook = make_snapshot_restore_setup_hook("warm", settle_seconds=0.0)
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(0, "OK", ""),
        ) as mock_run:
            ctx = GateContext(repo_root=Path("."), app_dir=Path("."), run_dir=Path("."))
            hook(ctx)
            args, _ = mock_run.call_args
            self.assertEqual(args[0], _expect_call(["avd", "snapshot", "load", "warm"]))

    def test_hook_propagates_error_to_caller(self) -> None:
        hook = make_snapshot_restore_setup_hook("warm", settle_seconds=0.0)
        with patch(
            "probe_gen.pipeline.snapshots.subprocess.run",
            return_value=_FakeProc(1, "", "snapshot not found"),
        ):
            ctx = GateContext(repo_root=Path("."), app_dir=Path("."), run_dir=Path("."))
            with self.assertRaises(SnapshotError):
                hook(ctx)


class TestSnapshotInfoDataclass(unittest.TestCase):
    def test_construction(self) -> None:
        info = SnapshotInfo(name="warm", size_bytes=None, created_iso=None)
        self.assertEqual(info.name, "warm")
        self.assertIsNone(info.size_bytes)


if __name__ == "__main__":
    unittest.main()
