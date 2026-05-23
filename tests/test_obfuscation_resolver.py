"""Tests for utils.obfuscation_resolver."""

import pytest

from utils.obfuscation_resolver import ObfuscationDecision, resolve_obfuscation


@pytest.mark.parametrize(
    "requested,effective,log_level,log_message",
    [
        ("off", "off", "info", "Obfuscation off (default)"),
        ("on", "on", "info", "Obfuscation on"),
    ],
)
def test_resolution_table_row(requested, effective, log_level, log_message):
    decision = resolve_obfuscation(requested)
    assert isinstance(decision, ObfuscationDecision)
    assert decision.effective == effective
    assert decision.log_level == log_level
    assert decision.log_message == log_message


@pytest.mark.parametrize("bad", ["", "ON", "true", "1", None, "yes", "off "])
def test_invalid_requested_raises(bad):
    with pytest.raises(ValueError):
        resolve_obfuscation(bad)  # type: ignore[arg-type]
