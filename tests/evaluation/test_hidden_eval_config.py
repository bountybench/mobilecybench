"""Tests for hidden evaluation config loader/validator."""

import json

import pytest

from evaluation.hidden_eval_config import (
    HiddenEvalConfigError,
    load_hidden_eval_config,
    validate_hidden_eval_config,
)


def _make_config(**overrides):
    """Build a valid config, optionally overriding probe keys."""
    probes = {
        "access.ssrf_detected": False,
        "confidentiality.secrets": True,
        "confidentiality.app_flag": True,
        "confidentiality.container_flag": False,
        "integrity.app_flag": True,
        "integrity.app_pwned_file": True,
        "integrity.container_flag": False,
        "integrity.container_pwned_file": False,
        "availability.check_container_health": False,
    }
    probes.update(overrides)
    return {"version": 1, "generic_probe_applicability": probes}


class TestValidConfig:
    def test_valid_config_no_containers(self):
        config = _make_config()
        validate_hidden_eval_config(config, container_names=[], app_server="")

    def test_valid_config_with_containers(self):
        config = _make_config(
            **{
                "access.ssrf_detected": True,
                "confidentiality.container_flag": True,
                "integrity.container_flag": True,
                "integrity.container_pwned_file": True,
                "availability.check_container_health": True,
            }
        )
        validate_hidden_eval_config(
            config,
            container_names=["backend"],
            app_server="backend:8080",
        )


class TestUnknownKeys:
    def test_typo_key_rejected(self):
        config = _make_config()
        config["generic_probe_applicability"]["integrity.app_pwn_file"] = True
        with pytest.raises(HiddenEvalConfigError, match="Unknown probe keys"):
            validate_hidden_eval_config(config)

    def test_extra_key_rejected(self):
        config = _make_config()
        config["generic_probe_applicability"]["custom.new_probe"] = True
        with pytest.raises(HiddenEvalConfigError, match="Unknown probe keys"):
            validate_hidden_eval_config(config)


class TestMissingKeys:
    def test_missing_key_rejected(self):
        config = _make_config()
        del config["generic_probe_applicability"]["integrity.app_flag"]
        with pytest.raises(HiddenEvalConfigError, match="Missing probe keys"):
            validate_hidden_eval_config(config)

    def test_empty_probes_rejected(self):
        config = {"version": 1, "generic_probe_applicability": {}}
        with pytest.raises(HiddenEvalConfigError, match="Missing probe keys"):
            validate_hidden_eval_config(config)


class TestContainerConstraints:
    def test_ssrf_enabled_without_containers_rejected(self):
        config = _make_config(**{"access.ssrf_detected": True})
        with pytest.raises(
            HiddenEvalConfigError, match="ssrf_detected.*container_names is empty"
        ):
            validate_hidden_eval_config(config, container_names=[], app_server="")

    def test_container_flag_enabled_without_containers_rejected(self):
        config = _make_config(**{"confidentiality.container_flag": True})
        with pytest.raises(
            HiddenEvalConfigError, match="container_flag.*container_names is empty"
        ):
            validate_hidden_eval_config(config, container_names=[])

    def test_container_health_enabled_without_containers_rejected(self):
        config = _make_config(**{"availability.check_container_health": True})
        with pytest.raises(
            HiddenEvalConfigError,
            match="check_container_health.*container_names is empty",
        ):
            validate_hidden_eval_config(config, container_names=[])


class TestServerConstraints:
    def test_ssrf_enabled_without_server_rejected(self):
        config = _make_config(**{"access.ssrf_detected": True})
        with pytest.raises(
            HiddenEvalConfigError, match="ssrf_detected.*app_server is empty"
        ):
            validate_hidden_eval_config(
                config,
                container_names=["backend"],
                app_server="",
            )


class TestVersionValidation:
    def test_wrong_version_rejected(self):
        config = _make_config()
        config["version"] = 2
        with pytest.raises(HiddenEvalConfigError, match="version"):
            validate_hidden_eval_config(config)

    def test_missing_version_rejected(self):
        config = _make_config()
        del config["version"]
        with pytest.raises(HiddenEvalConfigError, match="version"):
            validate_hidden_eval_config(config)


class TestNonBooleanValues:
    def test_integer_value_rejected(self):
        config = _make_config()
        config["generic_probe_applicability"]["confidentiality.secrets"] = 1
        with pytest.raises(HiddenEvalConfigError, match="must be a boolean"):
            validate_hidden_eval_config(config)


class TestLoadFromFile:
    def test_load_valid_file(self, tmp_path):
        config = _make_config()
        config_path = tmp_path / "hidden_eval_config.json"
        config_path.write_text(json.dumps(config))
        loaded = load_hidden_eval_config(config_path)
        assert loaded["version"] == 1

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_hidden_eval_config(tmp_path / "missing.json")

    def test_load_invalid_file(self, tmp_path):
        config = _make_config()
        config["generic_probe_applicability"]["typo.key"] = True
        config_path = tmp_path / "hidden_eval_config.json"
        config_path.write_text(json.dumps(config))
        with pytest.raises(HiddenEvalConfigError):
            load_hidden_eval_config(config_path)
