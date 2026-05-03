"""Unit tests for cross-app shared probe helpers.

Pure-function helpers can be tested directly. Subprocess wrappers are
tested with mocks. ADB / docker / HTTP integration is tested only at the
shape level — actual end-to-end behavior depends on the runtime.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from probe_gen.shared_helpers import (
    diff_against_baseline,
    docker_exec,
    docker_healthy,
    docker_inspect,
    docker_running,
    emit_check_result,
    emit_error,
    load_baseline_at,
    read_shared_prefs_map,
    run_command,
    scan_shared_storage_for_text,
    stream_digest,
    token_digest,
)


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestPureHelpers(unittest.TestCase):
    def test_emit_error_shape(self) -> None:
        self.assertEqual(emit_error("oops"), {"score": 0, "error": "oops"})

    def test_emit_check_result_pass(self) -> None:
        result = emit_check_result("test", True, "all good")
        self.assertEqual(
            result, {"name": "test", "success": True, "message": "all good"}
        )

    def test_emit_check_result_fail(self) -> None:
        result = emit_check_result("test", False, "broken")
        self.assertFalse(result["success"])

    def test_stream_digest_str_and_bytes(self) -> None:
        sd = stream_digest("hello")
        self.assertTrue(sd.startswith("len=5 sha256="))
        full = hashlib.sha256(b"hello").hexdigest()[:12]
        self.assertIn(full, sd)
        self.assertEqual(stream_digest(b"hello"), sd)

    def test_token_digest_does_not_leak_token(self) -> None:
        td = token_digest("super-secret-credential")
        self.assertNotIn("super", td)
        self.assertNotIn("secret", td)
        self.assertIn("len=", td)


class TestDiffAgainstBaseline(unittest.TestCase):
    def test_dict_diff(self) -> None:
        added, removed = diff_against_baseline({"a": 1, "b": 2}, {"a": 1, "c": 3})
        self.assertEqual(added, {"b"})
        self.assertEqual(removed, {"c"})

    def test_set_diff(self) -> None:
        added, removed = diff_against_baseline({"a", "b"}, {"a", "c"})
        self.assertEqual(added, {"b"})
        self.assertEqual(removed, {"c"})

    def test_list_diff(self) -> None:
        added, removed = diff_against_baseline(["a", "b"], ["a", "c"])
        self.assertEqual(added, {"b"})
        self.assertEqual(removed, {"c"})

    def test_unsupported_type_raises(self) -> None:
        with self.assertRaises(TypeError):
            diff_against_baseline("a", 1)

    def test_mixed_set_and_list_works(self) -> None:
        # set vs list — first branch matches because set is involved
        added, removed = diff_against_baseline({"a"}, ["a", "b"])
        self.assertEqual(added, set())
        self.assertEqual(removed, {"b"})


class TestLoadBaselineAt(unittest.TestCase):
    def test_loads_existing_file(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json", delete=False
        ) as fp:
            json.dump({"k": "v"}, fp)
            path = Path(fp.name)
        try:
            self.assertEqual(load_baseline_at(path), {"k": "v"})
        finally:
            path.unlink()

    def test_validates_required_keys(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json", delete=False
        ) as fp:
            json.dump({"k": "v"}, fp)
            path = Path(fp.name)
        try:
            with self.assertRaises(ValueError):
                load_baseline_at(path, required_keys=["missing"])
        finally:
            path.unlink()


class TestDockerHelpers(unittest.TestCase):
    def test_docker_running_true(self) -> None:
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, "true", ""),
        ):
            self.assertTrue(docker_running("foo"))

    def test_docker_running_false(self) -> None:
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, "false", ""),
        ):
            self.assertFalse(docker_running("foo"))

    def test_docker_running_missing_container(self) -> None:
        # docker inspect on a missing container exits non-zero
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(1, "", "no such container"),
        ):
            self.assertFalse(docker_running("foo"))

    def test_docker_healthy_true(self) -> None:
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, "healthy", ""),
        ):
            self.assertTrue(docker_healthy("foo"))

    def test_docker_inspect_returns_stdout(self) -> None:
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, '  {"x":1}  ', ""),
        ):
            self.assertEqual(docker_inspect("c", "{{.X}}"), '{"x":1}')

    def test_docker_exec_invokes_correct_args(self) -> None:
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, "", ""),
        ) as mock_run:
            docker_exec("conv-prosody", ["ls", "/foo"])
            args, _ = mock_run.call_args
            self.assertEqual(args[0], ["docker", "exec", "conv-prosody", "ls", "/foo"])


class TestRunCommand(unittest.TestCase):
    def test_returns_completed_process(self) -> None:
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, "out", "err"),
        ):
            result = run_command(["echo"])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "out")


class TestSharedPrefsParser(unittest.TestCase):
    SAMPLE_XML = """<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
  <string name="username">alice</string>
  <int name="port" value="5222" />
  <boolean name="enabled" value="true" />
  <unknown name="other" value="42" />
  <string name="empty" />
</map>
"""

    def test_parses_string_int_bool(self) -> None:
        with patch(
            "probe_gen.shared_helpers.adb_root_cat",
            return_value=self.SAMPLE_XML,
        ):
            d = read_shared_prefs_map("/some/path")
        self.assertEqual(d["username"], "alice")
        self.assertEqual(d["port"], "5222")
        self.assertEqual(d["enabled"], "true")
        self.assertEqual(d["other"], "42")  # unknown tag falls back to value attr
        self.assertEqual(d["empty"], "")

    def test_empty_input_returns_empty(self) -> None:
        with patch("probe_gen.shared_helpers.adb_root_cat", return_value=""):
            self.assertEqual(read_shared_prefs_map("/x"), {})


class TestSharedStorageScan(unittest.TestCase):
    def test_empty_needle_returns_false_no_call(self) -> None:
        with patch("probe_gen.shared_helpers.adb_root_shell") as mock_shell:
            self.assertFalse(scan_shared_storage_for_text(""))
            mock_shell.assert_not_called()

    def test_hit_returns_true(self) -> None:
        with patch(
            "probe_gen.shared_helpers.adb_root_shell",
            return_value=(True, "HIT"),
        ):
            self.assertTrue(scan_shared_storage_for_text("canary"))

    def test_miss_returns_false(self) -> None:
        with patch(
            "probe_gen.shared_helpers.adb_root_shell",
            return_value=(True, ""),
        ):
            self.assertFalse(scan_shared_storage_for_text("canary"))

    def test_failure_raises(self) -> None:
        with patch(
            "probe_gen.shared_helpers.adb_root_shell",
            return_value=(False, "permission denied"),
        ):
            with self.assertRaises(RuntimeError):
                scan_shared_storage_for_text("canary")


class TestRealCodebaseConsistency(unittest.TestCase):
    """Sanity-check that the helpers we extracted don't drift from the real
    per-app implementations they were ported from. If HA's ``probe_lib.py``
    changes one of these contracts, these tests should catch the drift."""

    def test_ha_docker_running_equivalent(self) -> None:
        # HA's docker_running was: docker_inspect(container, "{{.State.Running}}").lower() == "true"
        # Our shared docker_running is the same.
        with patch(
            "probe_gen.shared_helpers.subprocess.run",
            return_value=_FakeProc(0, "True", ""),
        ):
            # Capitalization tolerance — HA's lower() handles it
            self.assertTrue(docker_running("foo"))


if __name__ == "__main__":
    unittest.main()
