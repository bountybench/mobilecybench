from pathlib import Path

from scripts.ci_matrix import build_matrices

REPO_ROOT = Path(__file__).resolve().parents[1]


def _matrix(*changed_files: str, github_base_ref: str = "main") -> dict:
    return build_matrices(REPO_ROOT, list(changed_files), github_base_ref)


def _job_keys(jobs: list[dict]) -> list[tuple]:
    return [
        (
            job["app_name"],
            job["setup_mode"],
            job["variant"],
            job.get("test_type"),
            job.get("vuln_id"),
        )
        for job in jobs
    ]


def test_archive_only_change_schedules_no_app_jobs() -> None:
    matrix = _matrix(
        "archive/synthetic-vulnerabilities/conversations/vuln_0/metadata.json"
    )

    assert matrix["should_exit"] is True
    assert matrix["has_non_app_changes"] is True
    assert matrix["modified_dirs"] == []
    assert matrix["apk_jobs"] == []
    assert matrix["test_jobs"] == []


def test_active_app_metadata_change_preserves_probe_jobs() -> None:
    matrix = _matrix("apps/conversations/metadata.json")

    assert matrix["should_exit"] is False
    assert matrix["has_non_app_changes"] is False
    assert matrix["modified_dirs"] == ["apps/conversations"]
    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "apklink", "default", None, None),
        ("conversations", "apklink", "obfuscated", None, None),
    ]
    assert _job_keys(matrix["test_jobs"]) == [
        ("conversations", "apklink", "default", "baseline", None),
        ("conversations", "apklink", "default", "vuln_scenario_0", None),
        ("conversations", "apklink", "default", "vuln_scenario_1", None),
    ]


def test_active_app_source_change_uses_source_mode() -> None:
    matrix = _matrix("apps/conversations/build.sh")

    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "source", "default", None, None),
        ("conversations", "source", "obfuscated", None, None),
    ]
    assert {job["setup_mode"] for job in matrix["test_jobs"]} == {"source"}


def test_active_app_core_change_preserves_probe_jobs_without_synthetic_jobs() -> None:
    matrix = _matrix("apps/conversations/start_runtime.sh")

    assert matrix["should_exit"] is False
    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "apklink", "default", None, None),
        ("conversations", "apklink", "obfuscated", None, None),
    ]
    assert _job_keys(matrix["test_jobs"]) == [
        ("conversations", "apklink", "default", "baseline", None),
        ("conversations", "apklink", "default", "vuln_scenario_0", None),
        ("conversations", "apklink", "default", "vuln_scenario_1", None),
    ]
    assert all(job.get("test_type") != "synthetic_vuln" for job in matrix["test_jobs"])


def test_active_synthetic_path_change_does_not_emit_synthetic_jobs() -> None:
    matrix = _matrix(
        "apps/conversations/synthetic_vulnerabilities/vuln_0/metadata.json"
    )

    assert matrix["should_exit"] is True
    assert matrix["modified_dirs"] == ["apps/conversations"]
    assert matrix["apk_jobs"] == []
    assert matrix["test_jobs"] == []
    assert all(job.get("test_type") != "synthetic_vuln" for job in matrix["test_jobs"])


def test_non_app_change_runs_unit_tests_without_app_jobs() -> None:
    matrix = _matrix("README.md")

    assert matrix["should_exit"] is True
    assert matrix["has_non_app_changes"] is True
    assert matrix["modified_dirs"] == []
    assert matrix["apk_jobs"] == []
    assert matrix["test_jobs"] == []
