import hashlib
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from utils.apk_utils import (
    _extract_zip,
    check_releases,
    download_apk,
    ensure_apk_file_available,
    ensure_resolved_apk_available,
    get_download_url,
)

GITHUB_URL = "https://github.com/owner/repo/releases/download/v1/app.apk"
BUNDLE_URL = "https://github.com/owner/repo/releases/download/v1/apk-bundle.zip"


# --- get_download_url ---


def test_get_download_url_returns_link(tmp_path):
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(json.dumps({"download_link": GITHUB_URL}))
    assert get_download_url("myapp", tmp_path) == GITHUB_URL


def test_get_download_url_missing_key(tmp_path):
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(json.dumps({"gh_link": "x"}))
    assert get_download_url("myapp", tmp_path) is None


def test_get_download_url_obfuscated_returns_obfuscated_link(tmp_path):
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    obfuscated_url = (
        "https://github.com/owner/repo/releases/download/v1/"
        "apk-myapp-obfuscated-bundle.zip"
    )
    (app_dir / "metadata.json").write_text(
        json.dumps(
            {
                "download_link": GITHUB_URL,
                "download_link_obfuscated": obfuscated_url,
            }
        )
    )
    assert get_download_url("myapp", tmp_path, obfuscated=True) == obfuscated_url


def test_get_download_url_obfuscated_missing_link_fails_fast(tmp_path, caplog):
    app_dir = tmp_path / "apps" / "myapp"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(json.dumps({"download_link": GITHUB_URL}))

    assert get_download_url("myapp", tmp_path, obfuscated=True) is None
    assert any("refusing to fall back" in message for message in caplog.messages)


def test_get_download_url_no_metadata(tmp_path):
    assert get_download_url("nonexistent", tmp_path) is None


# --- _extract_zip ---


def _make_zip(tmp_path, entries: dict[str, bytes], *, prefix: str = "") -> Path:
    """Create a zip file with given {name: content} entries."""
    zp = tmp_path / "test.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for name, data in entries.items():
            zf.writestr(prefix + name, data)
    return zp


def test_extract_creates_missing_files(tmp_path):
    zp = _make_zip(tmp_path, {"a.apk": b"aaa", "b.apk": b"bbb"})
    apk_dir = tmp_path / "apk"
    apk_dir.mkdir()
    with zipfile.ZipFile(zp) as zf:
        _extract_zip(zf, apk_dir)
    assert (apk_dir / "a.apk").read_bytes() == b"aaa"
    assert (apk_dir / "b.apk").read_bytes() == b"bbb"


def test_extract_skips_existing_files_and_warns(tmp_path, caplog):
    zp = _make_zip(tmp_path, {"a.apk": b"new"})
    apk_dir = tmp_path / "apk"
    apk_dir.mkdir()
    (apk_dir / "a.apk").write_bytes(b"old")
    with zipfile.ZipFile(zp) as zf:
        _extract_zip(zf, apk_dir)
    assert (apk_dir / "a.apk").read_bytes() == b"old"
    warns = [m for m in caplog.messages if "Skipped 1 existing" in m]
    assert warns
    assert "--force" in warns[0]


def test_extract_force_overwrites_existing(tmp_path):
    zp = _make_zip(tmp_path, {"a.apk": b"new"})
    apk_dir = tmp_path / "apk"
    apk_dir.mkdir()
    (apk_dir / "a.apk").write_bytes(b"old")
    with zipfile.ZipFile(zp) as zf:
        _extract_zip(zf, apk_dir, force=True)
    assert (apk_dir / "a.apk").read_bytes() == b"new"


def test_extract_replaces_empty_files(tmp_path, caplog):
    """Empty files are replaced automatically (likely interrupted download)."""
    zp = _make_zip(tmp_path, {"a.apk": b"fresh"})
    apk_dir = tmp_path / "apk"
    apk_dir.mkdir()
    (apk_dir / "a.apk").write_bytes(b"")  # 0 bytes = broken
    with zipfile.ZipFile(zp) as zf:
        _extract_zip(zf, apk_dir)
    assert (apk_dir / "a.apk").read_bytes() == b"fresh"
    assert any("Replacing empty file" in m for m in caplog.messages)


def test_extract_strips_apk_prefix(tmp_path):
    zp = _make_zip(tmp_path, {"test.apk": b"data"}, prefix="apk/")
    apk_dir = tmp_path / "apk"
    apk_dir.mkdir()
    with zipfile.ZipFile(zp) as zf:
        _extract_zip(zf, apk_dir)
    assert (apk_dir / "test.apk").read_bytes() == b"data"


def test_extract_creates_subdirs(tmp_path):
    zp = _make_zip(tmp_path, {"sub/nested.apk": b"deep"})
    apk_dir = tmp_path / "apk"
    apk_dir.mkdir()
    with zipfile.ZipFile(zp) as zf:
        _extract_zip(zf, apk_dir)
    assert (apk_dir / "sub" / "nested.apk").read_bytes() == b"deep"


# --- download_apk ---


def test_download_apk_invalid_url(tmp_path):
    with pytest.raises(ValueError, match="Invalid GitHub release URL"):
        download_apk("myapp", "https://example.com/not-github", tmp_path)


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_single_file(mock_run, tmp_path):
    """Single non-zip APK is moved into place."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk"

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        (Path(tmpdir) / "app.apk").write_bytes(b"fake-apk-data")

    mock_run.side_effect = fake_gh_download
    result = download_apk("myapp", GITHUB_URL, tmp_path)

    assert result == apk_dir
    assert (apk_dir / "myapp.apk").read_bytes() == b"fake-apk-data"
    # Verify gh CLI was called with correct args
    call_args = mock_run.call_args[0][0]
    assert call_args[:3] == ["gh", "release", "download"]
    assert "v1" in call_args
    assert "owner/repo" in call_args


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_apk_is_valid_zip(mock_run, tmp_path):
    """APK files are valid zips — must not be treated as zip bundles."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk"

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        # Create a real zip file but with .apk extension (like all real APKs)
        apk_path = Path(tmpdir) / "app.apk"
        with zipfile.ZipFile(apk_path, "w") as zf:
            zf.writestr("classes.dex", b"dex data")
            zf.writestr("AndroidManifest.xml", b"manifest")

    mock_run.side_effect = fake_gh_download
    download_apk("myapp", GITHUB_URL, tmp_path)

    # Should be treated as single APK, not extracted
    assert (apk_dir / "myapp.apk").exists()
    assert not (apk_dir / "classes.dex").exists()


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_zip_bundle(mock_run, tmp_path):
    """Zip bundle is extracted into apk dir."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk"

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        zp = Path(tmpdir) / "apk-bundle.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("apk/myapp.apk", b"zip-apk")
            zf.writestr("apk/extra.apk", b"zip-extra")

    mock_run.side_effect = fake_gh_download
    result = download_apk("myapp", BUNDLE_URL, tmp_path)

    assert result == apk_dir
    assert (apk_dir / "myapp.apk").read_bytes() == b"zip-apk"
    assert (apk_dir / "extra.apk").read_bytes() == b"zip-extra"


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_obfuscated_zip_bundle_lands_under_obfuscated(mock_run, tmp_path):
    """Obfuscated bundles are zipped from apk/obfuscated/, so extraction
    should not create apk/obfuscated/obfuscated/.
    """
    apk_dir = tmp_path / "apps" / "myapp" / "apk" / "obfuscated"
    obfuscated_bundle_url = (
        "https://github.com/owner/repo/releases/download/v1/"
        "apk-myapp-obfuscated-bundle.zip"
    )

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        zp = Path(tmpdir) / "apk-myapp-obfuscated-bundle.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("./", b"")
            zf.writestr("myapp.apk", b"obfuscated-apk")
            zf.writestr("vuln_0/myapp.apk", b"obfuscated-vuln-apk")

    mock_run.side_effect = fake_gh_download
    result = download_apk("myapp", obfuscated_bundle_url, tmp_path, obfuscated=True)

    assert result == apk_dir
    assert (apk_dir / "myapp.apk").read_bytes() == b"obfuscated-apk"
    assert (apk_dir / "vuln_0" / "myapp.apk").read_bytes() == b"obfuscated-vuln-apk"
    assert not (apk_dir / "obfuscated").exists()


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_obfuscated_zip_bundle_strips_full_obfuscated_prefix(
    mock_run, tmp_path
):
    """Bundles zipped from apk/obfuscated should not double-nest obfuscated/."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk" / "obfuscated"
    obfuscated_bundle_url = (
        "https://github.com/owner/repo/releases/download/v1/"
        "apk-myapp-obfuscated-bundle.zip"
    )

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        zp = Path(tmpdir) / "apk-myapp-obfuscated-bundle.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("apk/obfuscated/myapp.apk", b"obfuscated-apk")
            zf.writestr("apk/obfuscated/vuln_0/myapp.apk", b"obfuscated-vuln-apk")

    mock_run.side_effect = fake_gh_download
    result = download_apk("myapp", obfuscated_bundle_url, tmp_path, obfuscated=True)

    assert result == apk_dir
    assert (apk_dir / "myapp.apk").read_bytes() == b"obfuscated-apk"
    assert (apk_dir / "vuln_0" / "myapp.apk").read_bytes() == b"obfuscated-vuln-apk"
    assert not (apk_dir / "obfuscated").exists()


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_bundle_missing_primary_apk_raises(mock_run, tmp_path):
    """A bundle with only nested APKs is not enough for probe-only redteam setup."""

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        zp = Path(tmpdir) / "apk-bundle.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("apk/vuln_0/myapp.apk", b"nested-only")

    mock_run.side_effect = fake_gh_download
    with pytest.raises(FileNotFoundError, match="expected APK"):
        download_apk("myapp", BUNDLE_URL, tmp_path)


def test_ensure_resolved_apk_available_checks_obfuscated_path(tmp_path):
    apk_path = tmp_path / "apps" / "myapp" / "apk" / "obfuscated" / "myapp.apk"
    apk_path.parent.mkdir(parents=True)
    apk_path.write_bytes(b"apk")

    assert (
        ensure_resolved_apk_available(
            app_name="myapp",
            project_root=tmp_path,
            runner_obfuscation="on",
        )
        == apk_path
    )


def test_ensure_resolved_apk_available_logs_apk_sha256(tmp_path, caplog):
    apk_bytes = b"apk-under-test"
    apk_path = tmp_path / "apps" / "myapp" / "apk" / "obfuscated" / "myapp.apk"
    apk_path.parent.mkdir(parents=True)
    apk_path.write_bytes(apk_bytes)

    ensure_resolved_apk_available(
        app_name="myapp",
        project_root=tmp_path,
        runner_obfuscation="on",
    )

    assert str(apk_path) in caplog.text
    assert "apk_obfuscation=on" in caplog.text
    assert hashlib.sha256(apk_bytes).hexdigest() in caplog.text


def test_ensure_resolved_apk_available_fails_on_missing_obfuscated_path(tmp_path):
    default_apk = tmp_path / "apps" / "myapp" / "apk" / "myapp.apk"
    default_apk.parent.mkdir(parents=True)
    default_apk.write_bytes(b"default")

    with pytest.raises(FileNotFoundError, match="apk_obfuscation=on"):
        ensure_resolved_apk_available(
            app_name="myapp",
            project_root=tmp_path,
            runner_obfuscation="on",
        )


def test_ensure_apk_file_available_rejects_empty_file(tmp_path):
    apk_path = tmp_path / "empty.apk"
    apk_path.write_bytes(b"")

    with pytest.raises(FileNotFoundError, match="is empty"):
        ensure_apk_file_available(apk_path, description="Phase 2 APK")


def test_ensure_apk_file_available_logs_sha256(tmp_path, caplog):
    apk_bytes = b"standalone-apk"
    apk_path = tmp_path / "phase2.apk"
    apk_path.write_bytes(apk_bytes)

    ensure_apk_file_available(apk_path, description="Phase 2 APK")

    assert "Phase 2 APK" in caplog.text
    assert str(apk_path) in caplog.text
    assert hashlib.sha256(apk_bytes).hexdigest() in caplog.text


def test_ensure_apk_file_available_persists_provenance_jsonl(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    class _FakeLoggerManager:
        @staticmethod
        def get_logs_dir():
            return logs_dir

    monkeypatch.setenv("MOBILECYBENCH_SESSION_ID", "session-123")
    monkeypatch.setattr("utils.logger.logger_manager", _FakeLoggerManager())

    apk_path = tmp_path / "phase2.apk"
    apk_path.write_bytes(b"standalone-apk")

    ensure_apk_file_available(apk_path, description="Phase 2 APK")

    provenance = (logs_dir / "apk_provenance.jsonl").read_text(encoding="utf-8")
    assert '"description": "Phase 2 APK"' in provenance
    assert '"session_id": "session-123"' in provenance


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_zip_no_apk_entries_raises(mock_run, tmp_path):
    """Zip bundle with no .apk files raises ValueError."""

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        zp = Path(tmpdir) / "apk-bundle.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("readme.txt", b"not an apk")

    mock_run.side_effect = fake_gh_download
    with pytest.raises(ValueError, match="contains no .apk files"):
        download_apk("myapp", BUNDLE_URL, tmp_path)


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_skips_existing(mock_run, tmp_path, caplog):
    """Single APK download skips if file already exists and warns about --force."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk"
    apk_dir.mkdir(parents=True)
    (apk_dir / "myapp.apk").write_bytes(b"existing")

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        (Path(tmpdir) / "app.apk").write_bytes(b"new-data")

    mock_run.side_effect = fake_gh_download
    download_apk("myapp", GITHUB_URL, tmp_path)
    assert (apk_dir / "myapp.apk").read_bytes() == b"existing"
    warns = [m for m in caplog.messages if "already exists" in m]
    assert warns
    assert "--force" in warns[0]


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_force_overwrites(mock_run, tmp_path):
    """With force=True, existing APK is overwritten."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk"
    apk_dir.mkdir(parents=True)
    (apk_dir / "myapp.apk").write_bytes(b"old")

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        (Path(tmpdir) / "app.apk").write_bytes(b"new-data")

    mock_run.side_effect = fake_gh_download
    download_apk("myapp", GITHUB_URL, tmp_path, force=True)
    assert (apk_dir / "myapp.apk").read_bytes() == b"new-data"


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_clean_target_removes_stale_default_tree_preserving_obfuscated(
    mock_run, tmp_path
):
    apk_dir = tmp_path / "apps" / "myapp" / "apk"
    apk_dir.mkdir(parents=True)
    (apk_dir / "myapp.apk").write_bytes(b"stale-default")
    (apk_dir / "vuln_0").mkdir()
    (apk_dir / "vuln_0" / "myapp.apk").write_bytes(b"stale-vuln")
    (apk_dir / "obfuscated").mkdir()
    (apk_dir / "obfuscated" / "myapp.apk").write_bytes(b"keep-obfuscated")

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        zp = Path(tmpdir) / "apk-bundle.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("apk/myapp.apk", b"fresh-default")

    mock_run.side_effect = fake_gh_download
    download_apk(
        "myapp",
        BUNDLE_URL,
        tmp_path,
        force=True,
        clean_target=True,
    )

    assert (apk_dir / "myapp.apk").read_bytes() == b"fresh-default"
    assert not (apk_dir / "vuln_0").exists()
    assert (apk_dir / "obfuscated" / "myapp.apk").read_bytes() == b"keep-obfuscated"


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_replaces_empty_existing(mock_run, tmp_path, caplog):
    """Empty existing APK is replaced without --force (clearly broken)."""
    apk_dir = tmp_path / "apps" / "myapp" / "apk"
    apk_dir.mkdir(parents=True)
    (apk_dir / "myapp.apk").write_bytes(b"")

    def fake_gh_download(*args, **kwargs):
        cmd = args[0]
        tmpdir = cmd[cmd.index("--dir") + 1]
        (Path(tmpdir) / "app.apk").write_bytes(b"good-data")

    mock_run.side_effect = fake_gh_download
    download_apk("myapp", GITHUB_URL, tmp_path)
    assert (apk_dir / "myapp.apk").read_bytes() == b"good-data"
    assert any("empty file" in m.lower() for m in caplog.messages)


@patch("utils.apk_utils.subprocess.run")
def test_download_apk_file_not_found_after_gh(mock_run, tmp_path):
    """Fail clearly if gh succeeds but expected file is missing."""
    mock_run.return_value = None  # gh exits 0 but writes nothing
    with pytest.raises(FileNotFoundError, match="not found in output"):
        download_apk("myapp", GITHUB_URL, tmp_path)


# --- check_releases ---


@patch("utils.apk_utils.subprocess.run")
def test_check_releases(mock_run, tmp_path):
    # App with valid link
    app1 = tmp_path / "apps" / "good"
    app1.mkdir(parents=True)
    (app1 / "metadata.json").write_text(json.dumps({"download_link": GITHUB_URL}))

    # App with no link
    app2 = tmp_path / "apps" / "nolink"
    app2.mkdir(parents=True)
    (app2 / "metadata.json").write_text(json.dumps({}))

    mock_run.return_value.returncode = 0
    results = check_releases(["good", "nolink", "missing_dir"], tmp_path)

    assert results["good"] == "ok"
    assert results["nolink"] == "no_link"
    assert results["missing_dir"] == "no_link"
