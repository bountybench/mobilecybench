"""Tests for discovery honeypot source injection."""

from utils.discovery_honeypot import inject_discovery_honeypot


def test_injects_honeypot_into_standard_android_layout(tmp_path):
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
        / "VulnFlagActivity.java"
    )
    assert activity_path.exists()
    assert "package com.example.app.internal;" in activity_path.read_text(
        encoding="utf-8"
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "com.example.app.internal.VulnFlagActivity" in manifest_text
    assert 'android:exported="false"' in manifest_text


def test_prefers_matching_package_root_over_unrelated_manifests(tmp_path):
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

    inject_discovery_honeypot(codebase_dir, "net.thunderbird.android")

    assert (app_source / "internal" / "VulnFlagActivity.java").exists()
    assert (
        "net.thunderbird.android.internal.VulnFlagActivity"
        in app_manifest.read_text(encoding="utf-8")
    )
    assert "net.thunderbird.android.internal.VulnFlagActivity" not in (
        unrelated_main / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")


def test_injection_is_idempotent(tmp_path):
    codebase_dir = tmp_path / "codebase"
    manifest_dir = codebase_dir / "app" / "src" / "main"
    source_dir = manifest_dir / "java" / "com" / "example" / "app"
    source_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "AndroidManifest.xml"
    manifest_path.write_text(
        "<manifest><application></application></manifest>",
        encoding="utf-8",
    )

    inject_discovery_honeypot(codebase_dir, "com.example.app")
    inject_discovery_honeypot(codebase_dir, "com.example.app")

    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert manifest_text.count("VulnFlagActivity") == 1
