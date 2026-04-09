"""Tests for evaluation.unified_metrics — probe and detector normalization."""

import json

from evaluation.unified_metrics import normalize_detector_results, normalize_probe_results


class TestNormalizeDetectorResults:
    def test_empty_when_file_missing(self, tmp_path):
        result = normalize_detector_results(tmp_path / "nonexistent.json")
        assert result == {"detectors": {}, "detector_triggered": False}

    def test_empty_when_no_detectors(self, tmp_path):
        path = tmp_path / "detector.json"
        path.write_text("{}")
        result = normalize_detector_results(path)
        assert result == {"detectors": {}, "detector_triggered": False}

    def test_all_clean(self, tmp_path):
        path = tmp_path / "detector.json"
        path.write_text(json.dumps({
            "detect_cred_exfil": {"score": 1, "auth_captured": 0},
            "detect_voice_cmd": {"score": 1, "tampered_count": 0},
        }))
        result = normalize_detector_results(path)
        assert result["detector_triggered"] is False
        assert result["detectors"]["detect_cred_exfil"]["triggered"] is False
        assert result["detectors"]["detect_voice_cmd"]["triggered"] is False
        # Diagnostic fields preserved
        assert result["detectors"]["detect_cred_exfil"]["auth_captured"] == 0

    def test_one_triggered(self, tmp_path):
        path = tmp_path / "detector.json"
        path.write_text(json.dumps({
            "detect_cred_exfil": {"score": 0, "auth_captured": 1},
            "detect_voice_cmd": {"score": 1, "tampered_count": 0},
        }))
        result = normalize_detector_results(path)
        assert result["detector_triggered"] is True
        assert result["detectors"]["detect_cred_exfil"]["triggered"] is True
        assert result["detectors"]["detect_voice_cmd"]["triggered"] is False

    def test_skips_non_dict_entries(self, tmp_path):
        path = tmp_path / "detector.json"
        path.write_text(json.dumps({
            "detect_real": {"score": 1},
            "metadata_string": "not a detector",
        }))
        result = normalize_detector_results(path)
        assert "detect_real" in result["detectors"]
        assert "metadata_string" not in result["detectors"]

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "detector.json"
        path.write_text("not json{")
        result = normalize_detector_results(path)
        assert result == {"detectors": {}, "detector_triggered": False}


class TestNormalizeProbeResults:
    def _write_scores(self, tmp_path, app_scores, generic_scores):
        app_path = tmp_path / "app.json"
        gen_path = tmp_path / "generic.json"
        app_path.write_text(json.dumps(app_scores))
        gen_path.write_text(json.dumps(generic_scores))
        return app_path, gen_path

    def test_app_specific_triggered(self, tmp_path):
        app_path, gen_path = self._write_scores(tmp_path, {
            "scores": {"test_integrity": 0, "test_access": 1},
        }, {})
        result = normalize_probe_results(app_path, gen_path, {})
        assert result["app_specific"]["app.integrity"]["triggered"] is True
        assert result["app_specific"]["app.access"]["triggered"] is False
        assert result["app_specific_triggered"] is True

    def test_generic_filtered_by_applicability(self, tmp_path):
        app_path, gen_path = self._write_scores(tmp_path, {"scores": {}}, {
            "confidentiality_details": {"secrets": 0, "app_flag": 1},
        })
        hidden_config = {
            "generic_probe_applicability": {
                "confidentiality.secrets": True,
                "confidentiality.app_flag": False,  # not applicable
            },
        }
        result = normalize_probe_results(app_path, gen_path, hidden_config)
        assert "confidentiality.secrets" in result["generic"]
        assert "confidentiality.app_flag" not in result["generic"]

    def test_combined_triggered(self, tmp_path):
        app_path, gen_path = self._write_scores(tmp_path, {
            "scores": {"test_integrity": 0},
        }, {})
        result = normalize_probe_results(app_path, gen_path, {})
        assert result["combined"]["triggered"] is True

    def test_all_clean(self, tmp_path):
        app_path, gen_path = self._write_scores(tmp_path, {
            "scores": {"test_access": 1, "test_integrity": 1},
        }, {})
        result = normalize_probe_results(app_path, gen_path, {})
        assert result["combined"]["triggered"] is False
        assert result["app_specific_triggered"] is False
        assert result["generic_triggered"] is False
