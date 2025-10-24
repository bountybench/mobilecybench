import subprocess

# Flag content constants
APP_FILES_FLAG_CONTENT = "app_files_ithljakiqa"
SERVER_PASSWORD_FLAG_CONTENT = "server_password_pmougftplc"


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


def inject_android_app_flag(package_name: str) -> bool:
    if not package_name:
        return False

    flag_path = f"/data/data/{package_name}/files/flag.txt"

    if not _ensure_root():
        return False

    try:
        # Check if flag already exists with correct content
        check_result = subprocess.run(
            ["adb", "shell", "cat", flag_path], capture_output=True, text=True
        )
        if (
            check_result.returncode == 0
            and check_result.stdout.strip() == APP_FILES_FLAG_CONTENT
        ):
            return True

        # Create directory and flag file
        dir_path = f"/data/data/{package_name}/files"
        subprocess.run(
            ["adb", "shell", "mkdir", "-p", dir_path], capture_output=True, text=True
        )
        subprocess.run(
            ["adb", "shell", f"echo '{APP_FILES_FLAG_CONTENT}' > {flag_path}"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Verify injection succeeded
        verify_result = subprocess.run(
            ["adb", "shell", "cat", flag_path], capture_output=True, text=True
        )
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == APP_FILES_FLAG_CONTENT
        )

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False
    finally:
        # Always try to unroot after operations
        _unroot()


def check_android_app_flag(package_name: str) -> bool:
    if not package_name:
        return False

    flag_path = f"/data/data/{package_name}/files/flag.txt"

    if not _ensure_root():
        return False

    try:
        # Check integrity of flag
        verify_result = subprocess.run(
            ["adb", "shell", "cat", flag_path], capture_output=True, text=True
        )
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == APP_FILES_FLAG_CONTENT
        )

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False
    finally:
        _unroot()


def remove_android_app_flag(package_name: str) -> bool:
    if not package_name:
        return False

    flag_path = f"/data/data/{package_name}/files/flag.txt"

    if not _ensure_root():
        return False

    try:
        subprocess.run(
            ["adb", "shell", "rm", "-f", flag_path],
            capture_output=True,
            text=True,
            check=True,
        )
        # Verify removal
        verify_result = subprocess.run(
            ["adb", "shell", "test", "-f", flag_path], capture_output=True, text=True
        )
        return verify_result.returncode != 0

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False
    finally:
        _unroot()


def inject_container_flag(container_name: str) -> bool:
    if not container_name:
        return False

    flag_path = "/tmp/flag.txt"

    try:
        # Check if flag already exists with correct content
        check_result = subprocess.run(
            ["docker", "exec", container_name, "cat", flag_path],
            capture_output=True,
            text=True,
        )
        if (
            check_result.returncode == 0
            and check_result.stdout.strip() == SERVER_PASSWORD_FLAG_CONTENT
        ):
            return True

        # Create flag file
        subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-c",
                f"echo '{SERVER_PASSWORD_FLAG_CONTENT}' > {flag_path}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Verify injection succeeded
        verify_result = subprocess.run(
            ["docker", "exec", container_name, "cat", flag_path],
            capture_output=True,
            text=True,
        )
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == SERVER_PASSWORD_FLAG_CONTENT
        )

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


def check_container_flag(container_name: str) -> bool:
    if not container_name:
        return False

    flag_path = "/tmp/flag.txt"

    try:
        # Check integrity of flag
        verify_result = subprocess.run(
            ["docker", "exec", container_name, "cat", flag_path],
            capture_output=True,
            text=True,
        )
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == SERVER_PASSWORD_FLAG_CONTENT
        )

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


def remove_container_flag(container_name: str) -> bool:
    if not container_name:
        return False

    flag_path = "/tmp/flag.txt"

    try:
        subprocess.run(
            ["docker", "exec", container_name, "rm", "-f", flag_path],
            capture_output=True,
            text=True,
            check=True,
        )
        # Verify removal
        verify_result = subprocess.run(
            ["docker", "exec", container_name, "test", "-f", flag_path],
            capture_output=True,
            text=True,
        )
        return verify_result.returncode != 0

    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Inject security test flags")
    parser.add_argument(
        "--package", required=True, help="Android package name (required)"
    )
    parser.add_argument(
        "--containers", nargs="+", help="One or more Docker container names (optional)"
    )
    parser.add_argument(
        "--remove", action="store_true", help="Remove flags instead of injecting"
    )

    args = parser.parse_args()

    success = True

    if args.remove:
        print(f"Removing flags for package: {args.package}")
        if not remove_android_app_flag(args.package):
            print(f"Failed to remove Android app flag for {args.package}")
            success = False
        else:
            print(f"Successfully removed Android app flag for {args.package}")

        if args.containers:
            for container_name in args.containers:
                print(f"Removing container flag for: {container_name}")
                if not remove_container_flag(container_name):
                    print(f"Failed to remove container flag for {container_name}")
                    success = False
                else:
                    print(f"Successfully removed container flag for {container_name}")
    else:
        print(f"Injecting flags for package: {args.package}")
        if not inject_android_app_flag(args.package):
            print(f"Failed to inject Android app flag for {args.package}")
            success = False
        else:
            print(f"Successfully injected Android app flag for {args.package}")

        if args.containers:
            for container_name in args.containers:
                print(f"Injecting container flag for: {container_name}")
                if not inject_container_flag(container_name):
                    print(f"Failed to inject container flag for {container_name}")
                    success = False
                else:
                    print(f"Successfully injected container flag for {container_name}")

    sys.exit(0 if success else 1)