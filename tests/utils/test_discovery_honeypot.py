"""Tests for discovery honeypot source injection."""

from utils.discovery_honeypot import inject_discovery_honeypot
from utils.honeypot_spec import get_activity_class


def test_injects_honeypot_into_standard_android_layout(tmp_path):
    package_name = "com.example.app"
    cls_name = get_activity_class(package_name)
    codebase_dir = tmp_path / "codebase"
    manifest_dir = codebase_dir / "app" / "src" / "main"
    source_dir = manifest_dir / "java" / "com" / "example" / "app"
    source_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "AndroidManifest.xml"
    manifest_path.write_text(
        '<manifest package="com.example.app"><application></application></manifest>',
        encoding="utf-8",
    )

    inject_discovery_honeypot(codebase_dir, "com.example.app")

    activity_path = (
        manifest_dir
        / "java"
        / "com"
        / "example"
        / "app"
        / "internal"
        / f"{cls_name}.java"
    )
    assert activity_path.exists()
    assert "package com.example.app.internal;" in activity_path.read_text(
        encoding="utf-8"
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert f"com.example.app.internal.{cls_name}" in manifest_text
    assert 'android:exported="false"' in manifest_text


def test_prefers_matching_package_root_over_unrelated_manifests(tmp_path):
    package_name = "net.thunderbird.android"
    cls_name = get_activity_class(package_name)
    codebase_dir = tmp_path / "codebase"

    unrelated_main = codebase_dir / "core" / "android" / "network" / "src" / "main"
    unrelated_main.mkdir(parents=True)
    (unrelated_main / "AndroidManifest.xml").write_text(
        "<manifest><application></application></manifest>",
        encoding="utf-8",
    )
    (unrelated_main / "java").mkdir()

    app_main = codebase_dir / "app-thunderbird" / "src" / "main"
    app_source = app_main / "kotlin" / "net" / "thunderbird" / "android"
    app_source.mkdir(parents=True)
    app_manifest = app_main / "AndroidManifest.xml"
    app_manifest.write_text(
        "<manifest><application></application></manifest>",
        encoding="utf-8",
    )

    inject_discovery_honeypot(codebase_dir, package_name)

    assert (app_source / "internal" / f"{cls_name}.java").exists()
    assert f"net.thunderbird.android.internal.{cls_name}" in app_manifest.read_text(
        encoding="utf-8"
    )
    assert f"net.thunderbird.android.internal.{cls_name}" not in (
        unrelated_main / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")


def test_injection_is_idempotent(tmp_path):
    package_name = "com.example.app"
    cls_name = get_activity_class(package_name)
    codebase_dir = tmp_path / "codebase"
    manifest_dir = codebase_dir / "app" / "src" / "main"
    source_dir = manifest_dir / "java" / "com" / "example" / "app"
    source_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "AndroidManifest.xml"
    manifest_path.write_text(
        "<manifest><application></application></manifest>",
        encoding="utf-8",
    )

    inject_discovery_honeypot(codebase_dir, package_name)
    inject_discovery_honeypot(codebase_dir, package_name)

    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert manifest_text.count(cls_name) == 1
