#!/usr/bin/env python3
"""Build GitHub Actions matrices for app CI jobs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROBE_FILES = (
    "test_access_control.py",
    "test_availability.py",
    "test_confidentiality.py",
    "test_integrity.py",
)


def git_changed_files(base_ref: str, head_ref: str = "HEAD") -> list[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--diff-filter=ACMDR",
            "--name-only",
            f"{base_ref}...{head_ref}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def app_dirs_for_changes(project_root: Path, changed_files: list[str]) -> list[str]:
    dirs = []
    for path in changed_files:
        parts = Path(path).parts
        if len(parts) < 2 or parts[0] != "apps":
            continue
        app_dir = f"{parts[0]}/{parts[1]}"
        if (project_root / app_dir / "metadata.json").is_file():
            dirs.append(app_dir)
    return sorted(set(dirs))


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{path} not found") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object in {path}")
    return payload


def has_obfuscation_optin(build_sh: Path) -> bool:
    return build_sh.is_file() and "MCB_OBFUSCATE_INIT_SCRIPT" in build_sh.read_text(
        encoding="utf-8"
    )


def setup_modes_for_app(
    app_dir: str,
    metadata: dict[str, Any],
    changed_files: list[str],
    project_root: Path,
) -> list[str]:
    has_source = (project_root / app_dir / "build.sh").is_file()
    has_apklink = bool(metadata.get("download_link"))
    if not has_source and not has_apklink:
        raise ValueError(
            f"Neither build.sh nor download_link found in {app_dir}. "
            "If this app builds from source, create a build.sh file."
        )

    source_modified = f"{app_dir}/build.sh" in changed_files
    apklink_modified = f"{app_dir}/metadata.json" in changed_files
    if has_source and has_apklink:
        if source_modified and apklink_modified:
            return ["source", "apklink"]
        if source_modified:
            return ["source"]
        if apklink_modified:
            return ["apklink"]
        return ["apklink"]
    if has_source:
        return ["source"]
    return ["apklink"]


def app_test_types(app_path: Path, metadata: dict[str, Any]) -> list[str]:
    has_probes = any((app_path / name).is_file() for name in PROBE_FILES)
    if not has_probes:
        return ["simple"]
    test_types = ["baseline", "vuln_scenario_0"]
    if metadata.get("app_server"):
        test_types.append("vuln_scenario_1")
    return test_types


def is_app_core_file(app_dir: str, path: str) -> bool:
    return path in {
        f"{app_dir}/build.sh",
        f"{app_dir}/start_runtime.sh",
        f"{app_dir}/cleanup.sh",
        f"{app_dir}/metadata.json",
        f"{app_dir}/docker-compose.yml",
        f"{app_dir}/security.patch",
    }


def build_matrices(
    project_root: Path,
    changed_files: list[str],
    github_base_ref: str,
) -> dict[str, Any]:
    modified_dirs = app_dirs_for_changes(project_root, changed_files)
    has_non_app_changes = any(not path.startswith("apps/") for path in changed_files)
    apk_jobs: list[dict[str, str]] = []
    test_jobs: list[dict[str, str]] = []

    obfuscate_init_changed = "gradle/obfuscate.init.gradle" in changed_files
    targets_main = github_base_ref == "main"

    for app_dir in modified_dirs:
        app_path = project_root / app_dir
        app_name = Path(app_dir).name
        metadata = read_json(app_path / "metadata.json")
        sdk = metadata.get("sdk")
        if sdk is None or sdk == "":
            raise ValueError(f"Could not extract SDK from {app_path / 'metadata.json'}")
        java = str(metadata.get("java", 17))
        system_image = str(metadata.get("system_image", "google_atd"))
        setup_modes = setup_modes_for_app(
            app_dir, metadata, changed_files, project_root
        )

        app_changes = [path for path in changed_files if path.startswith(f"{app_dir}/")]
        non_synth_changes = [
            path
            for path in app_changes
            if not path.startswith(f"{app_dir}/synthetic_vulnerabilities/")
        ]
        if not non_synth_changes:
            continue

        for mode in setup_modes:
            apk_jobs.append(
                {
                    "app_dir": app_dir,
                    "app_name": app_name,
                    "java": java,
                    "setup_mode": mode,
                    "variant": "default",
                }
            )

        test_types = app_test_types(app_path, metadata)
        for mode in setup_modes:
            for test_type in test_types:
                test_jobs.append(
                    {
                        "app_dir": app_dir,
                        "app_name": app_name,
                        "sdk": str(sdk),
                        "system_image": system_image,
                        "setup_mode": mode,
                        "test_type": test_type,
                        "variant": "default",
                    }
                )

        obfuscation_optin = has_obfuscation_optin(app_path / "build.sh")
        app_obfuscation_changed = any(
            path.startswith(f"{app_dir}/obfuscation/") for path in changed_files
        )
        core_modified = any(is_app_core_file(app_dir, path) for path in changed_files)
        if obfuscation_optin:
            run_obfuscated_build = (
                bool(non_synth_changes)
                or obfuscate_init_changed
                or app_obfuscation_changed
                or targets_main
                or core_modified
            )
            run_obfuscated_test = obfuscate_init_changed or app_obfuscation_changed
            if run_obfuscated_build:
                for mode in setup_modes:
                    apk_jobs.append(
                        {
                            "app_dir": app_dir,
                            "app_name": app_name,
                            "java": java,
                            "setup_mode": mode,
                            "variant": "obfuscated",
                        }
                    )
            if run_obfuscated_test:
                for mode in setup_modes:
                    for test_type in test_types:
                        test_jobs.append(
                            {
                                "app_dir": app_dir,
                                "app_name": app_name,
                                "sdk": str(sdk),
                                "system_image": system_image,
                                "setup_mode": mode,
                                "test_type": test_type,
                                "variant": "obfuscated",
                            }
                        )

    return {
        "should_exit": not apk_jobs,
        "has_non_app_changes": has_non_app_changes,
        "modified_dirs": modified_dirs,
        "apk_jobs": apk_jobs,
        "test_jobs": test_jobs,
    }


def write_github_output(output_path: Path, matrix: dict[str, Any]) -> None:
    lines = [
        f"should_exit={str(matrix['should_exit']).lower()}",
        f"has_non_app_changes={str(matrix['has_non_app_changes']).lower()}",
        "modified_dirs<<EOF",
        "\n".join(matrix["modified_dirs"]),
        "EOF",
        f"apk_jobs={json.dumps(matrix['apk_jobs'], separators=(',', ':'))}",
        f"test_jobs={json.dumps(matrix['test_jobs'], separators=(',', ':'))}",
    ]
    with output_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--github-base-ref", default="")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--changed-file", action="append", dest="changed_files")
    args = parser.parse_args(argv)

    project_root = Path.cwd()
    changed_files = args.changed_files
    if changed_files is None:
        changed_files = git_changed_files(args.base_ref, args.head_ref)

    try:
        matrix = build_matrices(project_root, changed_files, args.github_base_ref)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(matrix, indent=2, sort_keys=True))
    if args.github_output:
        write_github_output(args.github_output, matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
