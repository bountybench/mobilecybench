"""Tests for utils.obfuscation_resolver.

Covers every row of the resolution table in
``documentation/APK_OBFUSCATION.md`` plus argument validation and the
``None == "never"`` normalization rule.
"""

import pytest

from utils.obfuscation_resolver import ObfuscationDecision, resolve_obfuscation

# Every row of the resolution table, expressed as
# (requested, metadata_value, effective, log_level, expected_log_message).
_TABLE_CASES = [
    (
        "off",
        None,
        "off",
        "debug",
        "Obfuscation off (default)",
    ),
    (
        "off",
        "never",
        "off",
        "debug",
        "Obfuscation off (default)",
    ),
    (
        "off",
        "default",
        "off",
        "debug",
        "Obfuscation off (app supports it but operator chose off)",
    ),
    (
        "off",
        "force_on",
        "on",
        "warning",
        "Operator requested obfuscation off, but app metadata sets force_on "
        "— honoring force_on",
    ),
    (
        "off",
        "upstream_forced",
        "on",
        "info",
        "Operator requested obfuscation off, but app's upstream forces minify "
        "on — cannot disable",
    ),
    (
        "on",
        None,
        "off",
        "warning",
        "Operator requested obfuscation on, but app does not support it "
        "(metadata: never) — falling back to default APK",
    ),
    (
        "on",
        "never",
        "off",
        "warning",
        "Operator requested obfuscation on, but app does not support it "
        "(metadata: never) — falling back to default APK",
    ),
    (
        "on",
        "default",
        "on",
        "info",
        "Obfuscation on",
    ),
    (
        "on",
        "force_on",
        "on",
        "info",
        "Obfuscation on (matches force_on)",
    ),
    (
        "on",
        "upstream_forced",
        "on",
        "info",
        "Obfuscation on (matches upstream_forced)",
    ),
]


@pytest.mark.parametrize(
    "requested,metadata_value,effective,log_level,log_message",
    _TABLE_CASES,
)
def test_resolution_table_row(
    requested, metadata_value, effective, log_level, log_message
):
    decision = resolve_obfuscation(requested, metadata_value)
    assert isinstance(decision, ObfuscationDecision)
    assert decision.effective == effective
    assert decision.log_level == log_level
    assert decision.log_message == log_message
    # Every override case must produce a non-empty log_message.
    assert decision.log_message


def test_none_metadata_equivalent_to_never():
    for requested in ("off", "on"):
        assert resolve_obfuscation(requested, None) == resolve_obfuscation(
            requested, "never"
        )


def test_override_cases_are_info_or_warning():
    """Override cases (operator request differs from honored outcome) must
    surface at info or warning level — never silently at debug."""
    override_cases = [
        ("off", "force_on"),
        ("off", "upstream_forced"),
        ("on", "never"),
        ("on", None),
    ]
    for requested, meta in override_cases:
        decision = resolve_obfuscation(requested, meta)
        assert decision.log_level in ("info", "warning")
        assert decision.log_message


@pytest.mark.parametrize("bad", ["", "ON", "true", "1", None, "yes", "off "])
def test_invalid_requested_raises(bad):
    with pytest.raises(ValueError):
        resolve_obfuscation(bad, "default")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad", ["", "Default", "force-on", "upstream", "on", "off", "always"]
)
def test_invalid_metadata_raises(bad):
    with pytest.raises(ValueError):
        resolve_obfuscation("off", bad)  # type: ignore[arg-type]
