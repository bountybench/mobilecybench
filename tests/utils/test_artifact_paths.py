from pathlib import Path
from unittest.mock import patch

from utils.artifact_paths import relative_artifact_path


def test_none_input_returns_none(tmp_path):
    assert relative_artifact_path(None, tmp_path) is None


def test_empty_string_returns_none(tmp_path):
    assert relative_artifact_path("", tmp_path) is None


def test_absolute_path_under_root_relativizes(tmp_path):
    nested = tmp_path / "replays" / "probe" / "replay_evidence.log"
    assert (
        relative_artifact_path(nested, tmp_path) == "replays/probe/replay_evidence.log"
    )


def test_absolute_root_self_relativizes_to_dot(tmp_path):
    assert relative_artifact_path(tmp_path, tmp_path) == "."


def test_absolute_path_outside_root_uses_dotdot(tmp_path):
    sibling = tmp_path.parent / "elsewhere.log"
    result = relative_artifact_path(sibling, tmp_path)
    assert result == "../elsewhere.log"


def test_already_relative_passthrough_when_missing(tmp_path):
    # CWD-independent behavior: a non-absolute, nonexistent path is returned
    # unchanged (POSIX-normalized).
    assert (
        relative_artifact_path("replays/probe/replay_evidence.log", tmp_path)
        == "replays/probe/replay_evidence.log"
    )


def test_relpath_value_error_returns_original_string(tmp_path):
    # Simulate the Windows cross-drive case where os.path.relpath raises
    # ValueError. The helper must keep the original absolute pointer rather
    # than dropping it.
    absolute = tmp_path / "evidence.log"
    with patch("utils.artifact_paths.os.path.relpath", side_effect=ValueError):
        result = relative_artifact_path(absolute, tmp_path)
    assert result == str(absolute)


def test_accepts_path_or_string(tmp_path):
    nested = tmp_path / "a" / "b.txt"
    from_str = relative_artifact_path(str(nested), tmp_path)
    from_path = relative_artifact_path(nested, tmp_path)
    assert from_str == from_path == "a/b.txt"


def test_returns_posix_separators_on_all_platforms(tmp_path):
    nested = tmp_path / "x" / "y" / "z.log"
    result = relative_artifact_path(nested, tmp_path)
    assert "\\" not in result
    assert result == "x/y/z.log"
    assert isinstance(Path(result), Path)
