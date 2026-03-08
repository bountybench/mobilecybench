"""Integration checks that both honeypot injection paths share one definition."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from utils.discovery_honeypot import inject_discovery_honeypot
from utils.honeypot_spec import (
    ACTIVITY_CLASS,
    activity_name,
    java_source,
    manifest_activity_tag,
    smali_source,
)


def test_real_app_source_injection_matches_shared_spec(tmp_path):
    package_name = "com.github.gotify"
    copied_codebase = tmp_path / "codebase"
    
    # Create a mocked Android app structure
    manifest_dir = copied_codebase / "app" / "src" / "main"
    source_dir = manifest_dir / "java" / "com" / "github" / "gotify"
    source_dir.mkdir(parents=True)
    
    manifest_path = manifest_dir / "AndroidManifest.xml"
    manifest_path.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application></application></manifest>',
        encoding="utf-8",
    )

    inject_discovery_honeypot(copied_codebase, package_name)

    activity_matches = list(
        copied_codebase.glob(
            f"**/src/main/*/{package_name.replace('.', '/')}/internal/{ACTIVITY_CLASS}.java"
        )
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert activity_name(package_name) in manifest_text
    assert 'android:taskAffinity="com.benchmark.flag"' in manifest_text
    assert len(activity_matches) == 1
    activity_path = activity_matches[0]
    assert activity_path.read_text(encoding="utf-8") == java_source(package_name)


def test_cli_outputs_match_shared_spec_for_apk_path():
    repo_root = Path(__file__).resolve().parents[2]
    package_name = "com.github.gotify"

    manifest_output = subprocess.run(
        [
            sys.executable,
            "-m",
            "utils.honeypot_spec",
            "--format",
            "manifest-tag",
            "--package",
            package_name,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    smali_output = subprocess.run(
        [
            sys.executable,
            "-m",
            "utils.honeypot_spec",
            "--format",
            "smali",
            "--package",
            package_name,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert manifest_output == manifest_activity_tag(package_name)
    assert smali_output == smali_source(package_name)
