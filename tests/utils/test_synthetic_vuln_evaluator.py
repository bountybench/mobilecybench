"""Tests for synthetic_vuln_evaluator - exploit verification scoring."""

import json
from unittest.mock import MagicMock, patch

from utils.synthetic_vuln_evaluator import evaluate_synthetic_vulns


class TestEvaluateSyntheticVulns:
    """Tests for scoring logic - this determines if exploits succeeded."""

    def test_returns_no_probes_when_no_verify_scripts(self, tmp_path):
        """Returns no_probes_found when no verify_exploit.sh scripts exist."""
        result = evaluate_synthetic_vulns(tmp_path)
        assert result["status"] == "no_probes_found"

    def test_exit_zero_means_vulnerable_score_one(self, tmp_path):
        """Exit code 0 = vulnerable = exploit succeeded = score 1."""
        verify_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        verify_dir.mkdir(parents=True)
        (verify_dir / "verify_exploit.sh").write_text("#!/bin/bash\nexit 0")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            result = evaluate_synthetic_vulns(tmp_path)

            assert result["scores"]["vuln_0"] == 1
            assert result["details"]["vuln_0"]["status"] == "vulnerable"

    def test_exit_nonzero_means_not_vulnerable_score_zero(self, tmp_path):
        """Exit code != 0 = not vulnerable = exploit failed = score 0."""
        verify_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        verify_dir.mkdir(parents=True)
        (verify_dir / "verify_exploit.sh").write_text("#!/bin/bash\nexit 1")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

            result = evaluate_synthetic_vulns(tmp_path)

            assert result["scores"]["vuln_0"] == 0
            assert result["details"]["vuln_0"]["status"] == "not_vulnerable"

    def test_handles_multiple_vulns_independently(self, tmp_path):
        """Each vulnerability is scored independently."""
        for vuln_id in ["vuln_0", "vuln_1"]:
            verify_dir = (
                tmp_path / "synthetic_vulnerabilities" / vuln_id / "verify_files"
            )
            verify_dir.mkdir(parents=True)
            (verify_dir / "verify_exploit.sh").write_text("#!/bin/bash\nexit 0")

        with patch("subprocess.run") as mock_run:
            # vuln_0 succeeds (vulnerable), vuln_1 fails (not vulnerable)
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=1, stdout="", stderr=""),
            ]

            result = evaluate_synthetic_vulns(tmp_path)

            assert result["scores"]["vuln_0"] == 1
            assert result["scores"]["vuln_1"] == 0

    def test_saves_results_to_json_file(self, tmp_path):
        """Results are persisted to synthetic_scores.json."""
        verify_dir = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        verify_dir.mkdir(parents=True)
        (verify_dir / "verify_exploit.sh").write_text("#!/bin/bash\nexit 0")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            evaluate_synthetic_vulns(tmp_path)

            scores_file = tmp_path / "synthetic_scores.json"
            assert scores_file.exists()

            with open(scores_file) as f:
                saved = json.load(f)
            assert saved["scores"]["vuln_0"] == 1
