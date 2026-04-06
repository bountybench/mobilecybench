from pathlib import Path

import pytest

from utils.vuln_utils import get_vuln_output_name, resolve_vuln_dir


def test_resolve_vuln_dir_supports_explicit_zero_day_path(tmp_path):
    app_dir = tmp_path / "apps" / "test_app"
    vuln_dir = app_dir / "zero_day_vulnerabilities" / "vuln_0"
    vuln_dir.mkdir(parents=True)

    resolved = resolve_vuln_dir(app_dir, "zero_day_vulnerabilities/vuln_0")

    assert resolved == vuln_dir


def test_resolve_vuln_dir_rejects_ambiguous_bare_id(tmp_path):
    app_dir = tmp_path / "apps" / "test_app"
    (app_dir / "synthetic_vulnerabilities" / "vuln_0").mkdir(parents=True)
    (app_dir / "zero_day_vulnerabilities" / "vuln_0").mkdir(parents=True)

    with pytest.raises(ValueError, match="Ambiguous vulnerability reference"):
        resolve_vuln_dir(app_dir, "vuln_0")


def test_get_vuln_output_name_uses_basename():
    assert get_vuln_output_name("zero_day_vulnerabilities/vuln_7") == "vuln_7"
    assert (
        get_vuln_output_name(str(Path("/tmp/zero_day_vulnerabilities/vuln_9")))
        == "vuln_9"
    )
