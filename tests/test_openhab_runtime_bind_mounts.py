from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openhab_sanitizes_bind_mount_files_before_compose_up():
    """openHAB file bind mounts fail if Docker created a missing source as a dir."""
    script = (ROOT / "apps/openhab/start_runtime.sh").read_text(encoding="utf-8")
    main_body = script.split("main() {", 1)[1]

    assert "ensure_openhab_bind_mount_sources()" in script
    assert main_body.index("ensure_openhab_bind_mount_sources") < main_body.index(
        "docker compose up -d"
    )
    assert main_body.index("update_runtime_cfg") < main_body.index(
        "docker compose up -d"
    )
