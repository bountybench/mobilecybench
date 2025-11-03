import subprocess

def _ensure_root() -> bool:
    try:
        subprocess.run(["adb", "root"], capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _unroot() -> bool:
    try:
        subprocess.run(["adb", "unroot"], capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False
    

def check_app_privileged_file(package_name: str, filename: str) -> bool:
    if not package_name:
        return False

    file_path = f"/data/data/{package_name}/files/{filename}"

    if not _ensure_root():
        return False

    try:
        # Verify file exists
        verify_result = subprocess.run(
            ["adb", "shell", "test", "-f", file_path], capture_output=True, text=True
        )
        return verify_result.returncode == 0

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False
    finally:
        _unroot()
