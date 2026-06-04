import sys

import pytest

import download_apk as download_apk_cli


def _run_main(monkeypatch, args, results) -> int:
    monkeypatch.setattr(
        download_apk_cli,
        "check_releases",
        lambda app_names, project_root, *, obfuscated=False: results,
    )
    monkeypatch.setattr(sys, "argv", ["download_apk.py", *args])

    with pytest.raises(SystemExit) as exc:
        download_apk_cli.main()
    return exc.value.code


def test_check_default_allows_missing_download_link(monkeypatch):
    assert _run_main(monkeypatch, ["--check", "myapp"], {"myapp": "no_link"}) == 0


def test_check_obfuscated_fails_on_missing_obfuscated_link(monkeypatch, capsys):
    assert (
        _run_main(
            monkeypatch,
            ["--check", "--obfuscated", "myapp"],
            {"myapp": "no_link"},
        )
        == 1
    )

    stderr = capsys.readouterr().err
    assert "download_link_obfuscated" in stderr


def test_check_fails_on_missing_release_asset(monkeypatch):
    assert (
        _run_main(monkeypatch, ["--check", "myapp"], {"myapp": "missing_asset"})
        == 1
    )
