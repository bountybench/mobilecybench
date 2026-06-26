import json
from pathlib import Path

from scripts.ci_matrix import build_matrices, write_github_output

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


def _assert_no_synthetic_jobs(matrix: dict) -> None:
    for job in matrix["apk_jobs"] + matrix["test_jobs"]:
        assert job.get("test_type") != "synthetic_vuln"
        assert "vuln_id" not in job


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
    _assert_no_synthetic_jobs(matrix)


def test_non_obfuscation_app_change_keeps_default_variant_only() -> None:
    matrix = _matrix("apps/audiobookshelf/metadata.json")

    assert _job_keys(matrix["apk_jobs"]) == [
        ("audiobookshelf", "apklink", "default", None, None),
    ]
    assert {job["variant"] for job in matrix["test_jobs"]} == {"default"}
    _assert_no_synthetic_jobs(matrix)


def test_mixed_app_and_non_app_change_sets_unit_gate_and_keeps_app_jobs() -> None:
    matrix = _matrix("README.md", "apps/conversations/metadata.json")

    assert matrix["should_exit"] is False
    assert matrix["has_non_app_changes"] is True
    assert matrix["modified_dirs"] == ["apps/conversations"]
    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "apklink", "default", None, None),
        ("conversations", "apklink", "obfuscated", None, None),
    ]
    _assert_no_synthetic_jobs(matrix)


def test_multiple_active_apps_changed_share_one_matrix() -> None:
    matrix = _matrix(
        "apps/conversations/metadata.json",
        "apps/home-assistant-android/metadata.json",
    )

    assert matrix["should_exit"] is False
    assert matrix["modified_dirs"] == [
        "apps/conversations",
        "apps/home-assistant-android",
    ]
    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "apklink", "default", None, None),
        ("conversations", "apklink", "obfuscated", None, None),
        ("home-assistant-android", "apklink", "default", None, None),
    ]
    assert _job_keys(matrix["test_jobs"]) == [
        ("conversations", "apklink", "default", "baseline", None),
        ("conversations", "apklink", "default", "vuln_scenario_0", None),
        ("conversations", "apklink", "default", "vuln_scenario_1", None),
        ("home-assistant-android", "apklink", "default", "baseline", None),
        ("home-assistant-android", "apklink", "default", "vuln_scenario_0", None),
        ("home-assistant-android", "apklink", "default", "vuln_scenario_1", None),
    ]
    _assert_no_synthetic_jobs(matrix)


def test_active_app_source_change_uses_source_mode() -> None:
    matrix = _matrix("apps/conversations/build.sh")

    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "source", "default", None, None),
        ("conversations", "source", "obfuscated", None, None),
    ]
    assert {job["setup_mode"] for job in matrix["test_jobs"]} == {"source"}
    _assert_no_synthetic_jobs(matrix)


def test_active_app_source_and_metadata_change_uses_both_setup_modes() -> None:
    matrix = _matrix("apps/conversations/build.sh", "apps/conversations/metadata.json")

    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "source", "default", None, None),
        ("conversations", "apklink", "default", None, None),
        ("conversations", "source", "obfuscated", None, None),
        ("conversations", "apklink", "obfuscated", None, None),
    ]
    assert {job["setup_mode"] for job in matrix["test_jobs"]} == {"source", "apklink"}
    _assert_no_synthetic_jobs(matrix)


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
    _assert_no_synthetic_jobs(matrix)


def test_active_synthetic_path_change_does_not_emit_synthetic_jobs() -> None:
    matrix = _matrix(
        "apps/conversations/synthetic_vulnerabilities/vuln_0/metadata.json"
    )

    assert matrix["should_exit"] is True
    assert matrix["modified_dirs"] == ["apps/conversations"]
    assert matrix["apk_jobs"] == []
    assert matrix["test_jobs"] == []
    _assert_no_synthetic_jobs(matrix)


def test_mixed_active_app_and_synthetic_changes_keep_only_probe_jobs() -> None:
    matrix = _matrix(
        "apps/conversations/metadata.json",
        "apps/conversations/synthetic_vulnerabilities/vuln_0/metadata.json",
    )

    assert matrix["should_exit"] is False
    assert _job_keys(matrix["apk_jobs"]) == [
        ("conversations", "apklink", "default", None, None),
        ("conversations", "apklink", "obfuscated", None, None),
    ]
    assert [job["test_type"] for job in matrix["test_jobs"]] == [
        "baseline",
        "vuln_scenario_0",
        "vuln_scenario_1",
    ]
    _assert_no_synthetic_jobs(matrix)


def test_obfuscation_rule_change_preserves_obfuscated_test_fanout() -> None:
    matrix = _matrix("apps/nextcloud-talk/obfuscation/extra-keep.pro")

    assert _job_keys(matrix["apk_jobs"]) == [
        ("nextcloud-talk", "apklink", "default", None, None),
        ("nextcloud-talk", "apklink", "obfuscated", None, None),
    ]
    assert _job_keys(matrix["test_jobs"]) == [
        ("nextcloud-talk", "apklink", "default", "baseline", None),
        ("nextcloud-talk", "apklink", "default", "vuln_scenario_0", None),
        ("nextcloud-talk", "apklink", "default", "vuln_scenario_1", None),
        ("nextcloud-talk", "apklink", "obfuscated", "baseline", None),
        ("nextcloud-talk", "apklink", "obfuscated", "vuln_scenario_0", None),
        ("nextcloud-talk", "apklink", "obfuscated", "vuln_scenario_1", None),
    ]
    _assert_no_synthetic_jobs(matrix)


def test_non_app_change_runs_unit_tests_without_app_jobs() -> None:
    matrix = _matrix("README.md")

    assert matrix["should_exit"] is True
    assert matrix["has_non_app_changes"] is True
    assert matrix["modified_dirs"] == []
    assert matrix["apk_jobs"] == []
    assert matrix["test_jobs"] == []


def test_github_output_serializes_matrices_for_actions(tmp_path: Path) -> None:
    output = tmp_path / "github_output"
    matrix = _matrix("apps/conversations/metadata.json")

    write_github_output(output, matrix)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert "should_exit=false" in lines
    assert "has_non_app_changes=false" in lines
    assert (
        json.loads(
            next(
                line.removeprefix("apk_jobs=")
                for line in lines
                if line.startswith("apk_jobs=")
            )
        )
        == matrix["apk_jobs"]
    )
    assert (
        json.loads(
            next(
                line.removeprefix("test_jobs=")
                for line in lines
                if line.startswith("test_jobs=")
            )
        )
        == matrix["test_jobs"]
    )
