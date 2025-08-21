import subprocess


def run_adb_command(command: str) -> str | None:
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else None


def no_sensitive_db_on_external_storage(package_name: str) -> bool:
    """Ensure the app hasn't created sensitive DB files on external storage."""
    # check for database files on external storage using ls + grep
    cmd = f"adb shell 'ls -R /sdcard/' 2>/dev/null | grep -i {package_name}"
    out = run_adb_command(cmd) or ""
    hits = [
        l.strip()
        for l in out.splitlines()
        if l.strip()
        and (package_name in l.lower())
        and (l.endswith(".db") or l.endswith(".sqlite") or l.endswith(".sql"))
    ]

    if hits:
        print("[FAIL] Potential sensitive DB files found on external storage:")
        for hit in hits:
            print(f"- {hit}")
        return False

    return True
