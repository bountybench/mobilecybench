"""Tests for synthetic vulnerability utilities."""

from unittest.mock import MagicMock, patch

import pytest

from utils.synthetic_utils import apply_synthetic_patch, find_synthetic_patches


class TestFindSyntheticPatches:
    """Tests for find_synthetic_patches() - patch discovery logic."""

    def test_returns_empty_when_no_synth_dir(self, tmp_path):
        """Returns empty list when synthetic_vulnerabilities dir doesn't exist."""
        result = find_synthetic_patches(tmp_path)
        assert result == []

    def test_finds_patches_sorted_by_vuln_id(self, tmp_path):
        """Finds patches and returns them sorted by vulnerability ID."""
        synth_dir = tmp_path / "synthetic_vulnerabilities"

        # Create out of order to verify sorting
        for vuln_id in ["vuln_2", "vuln_0", "vuln_1"]:
            vuln_dir = synth_dir / vuln_id
            vuln_dir.mkdir(parents=True)
            (vuln_dir / "vulnerability.patch").write_text(f"patch for {vuln_id}")

        result = find_synthetic_patches(tmp_path)

        assert len(result) == 3
        assert [p.parent.name for p in result] == ["vuln_0", "vuln_1", "vuln_2"]

    def test_ignores_dirs_without_patch_file(self, tmp_path):
        """Only returns directories that have vulnerability.patch."""
        synth_dir = tmp_path / "synthetic_vulnerabilities"

        # Dir with patch
        (synth_dir / "vuln_0").mkdir(parents=True)
        (synth_dir / "vuln_0" / "vulnerability.patch").write_text("patch")

        # Dir without patch
        (synth_dir / "vuln_1").mkdir(parents=True)
        (synth_dir / "vuln_1" / "other_file.txt").write_text("not a patch")

        result = find_synthetic_patches(tmp_path)

        assert len(result) == 1
        assert result[0].parent.name == "vuln_0"


class TestApplySyntheticPatch:
    """Tests for apply_synthetic_patch() - patch application logic."""

    def test_does_nothing_with_empty_patch_list(self, tmp_path):
        """Does nothing when patch_paths is empty."""
        with patch("subprocess.run") as mock_run:
            apply_synthetic_patch(tmp_path, [])
            mock_run.assert_not_called()

    def test_applies_to_codebase_subdir_when_exists(self, tmp_path):
        """Applies patch to codebase subdirectory when it exists."""
        codebase_dir = tmp_path / "codebase"
        codebase_dir.mkdir()
        patch_file = tmp_path / "test.patch"
        patch_file.write_text("patch content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            apply_synthetic_patch(tmp_path, [patch_file])

            assert mock_run.call_args[1]["cwd"] == codebase_dir

    def test_raises_when_patch_fails(self, tmp_path):
        """Raises RuntimeError when a patch fails to apply."""
        codebase_dir = tmp_path / "codebase"
        codebase_dir.mkdir()

        patch_file = tmp_path / "bad.patch"
        patch_file.write_text("patch content")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="patch failed")

            with pytest.raises(RuntimeError, match="Failed to apply patch"):
                apply_synthetic_patch(tmp_path, [patch_file])
