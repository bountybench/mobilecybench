from pathlib import Path

from utils.run_synthetic_checks import discover_synthetic_probes, run_synthetic_checks


def _write_probe(path: Path, payload: str) -> None:
    path.write_text(
        "\n".join(
            [
                "import json",
                "import sys",
                "print('probe running', file=sys.stderr)",
                f"print(json.dumps({payload}))",
            ]
        )
        + "\n"
    )


def test_discovers_single_synthetic_probe(tmp_path: Path) -> None:
    probe = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "test_synthetic.py"
    probe.parent.mkdir(parents=True)
    _write_probe(probe, "{'score': 1}")
    probes = discover_synthetic_probes(tmp_path)
    assert [p.as_posix() for p in probes] == [probe.as_posix()]


def test_runs_single_probe_and_parses_score(tmp_path: Path) -> None:
    probe = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "test_synthetic.py"
    probe.parent.mkdir(parents=True)
    _write_probe(probe, "{'score': 1, 'check_a': 1}")
    result = run_synthetic_checks(tmp_path)
    assert result["status"] == "ok"
    assert result["scores"]["vuln_0"] == 1
    assert result["details"]["vuln_0"]["score"] == 1


def test_aggregates_multiple_probes_by_min_score(tmp_path: Path) -> None:
    probe1 = tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "test_synthetic.py"
    probe1.parent.mkdir(parents=True)
    _write_probe(probe1, "{'score': 1}")
    probe2 = tmp_path / "synthetic_vulnerabilities" / "vuln_1" / "test_synthetic.py"
    probe2.parent.mkdir(parents=True)
    _write_probe(probe2, "{'score': 0}")

    result = run_synthetic_checks(tmp_path)
    assert result["scores"]["vuln_0"] == 1
    assert result["scores"]["vuln_1"] == 0


def test_no_probes_found_returns_error_status(tmp_path: Path) -> None:
    result = run_synthetic_checks(tmp_path)
    assert result["status"] == "no_probes_found"
