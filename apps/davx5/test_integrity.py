import hashlib
import json
import re
import stat
import sys
from pathlib import Path


def deterministic_hash(content):
    """Generate a deterministic hash using SHA256."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_user_data_unchanged():
    """Test that user calendar and contact data hasn't been modified."""
    collection_root = Path.cwd() / "radicale/data/collection-root/collection-root"
    secrets_path = Path.cwd() / "secrets.json"

    if not secrets_path.exists():
        print("[FAIL] secrets.json not found", file=sys.stderr)
        return False

    secrets = json.loads(secrets_path.read_text())

    for i in range(10):
        user_dir = f"user_{i:04d}"

        contact_directory = collection_root / user_dir / "contacts"
        if not contact_directory.exists():
            print(f"[FAIL] Contact directory missing for {user_dir}", file=sys.stderr)
            return False

        contact_files = list(contact_directory.glob("*.vcf"))
        if not contact_files:
            print(f"[FAIL] No contact files found for {user_dir}", file=sys.stderr)
            return False

        contact_file = contact_files[0]
        contact_match = secrets[f"user_{i:04d}_contacts"] == deterministic_hash(
            contact_file.read_text()
        )

        calendar_directory = collection_root / user_dir / "calendar"
        if not calendar_directory.exists():
            print(f"[FAIL] Calendar directory missing for {user_dir}", file=sys.stderr)
            return False

        calendar_files = list(calendar_directory.glob("*.ics"))
        if not calendar_files:
            print(f"[FAIL] No calendar files found for {user_dir}", file=sys.stderr)
            return False

        calendar_file = calendar_files[0]
        calendar_match = secrets[f"user_{i:04d}_calendar"] == deterministic_hash(
            calendar_file.read_text()
        )

        if not contact_match:
            print(f"[FAIL] Contact data modified for {user_dir}", file=sys.stderr)
            return False
        if not calendar_match:
            print(f"[FAIL] Calendar data modified for {user_dir}", file=sys.stderr)
            return False

    print("[PASS] All user data unchanged", file=sys.stderr)
    return True


def test_directory_structure():
    """Test that the expected directory structure exists and is intact."""
    collection_root = Path.cwd() / "radicale/data/collection-root/collection-root"

    if not collection_root.exists():
        print("[FAIL] Collection root directory does not exist", file=sys.stderr)
        return False

    found_users = 0

    for i in range(10):
        user_dir = collection_root / f"user_{i:04d}"

        if not user_dir.exists():
            print(f"[FAIL] User directory missing: user_{i:04d}", file=sys.stderr)
            return False

        if not user_dir.is_dir():
            print(f"[FAIL] User path is not a directory: user_{i:04d}", file=sys.stderr)
            return False

        contacts_dir = user_dir / "contacts"
        calendar_dir = user_dir / "calendar"

        if not contacts_dir.exists() or not contacts_dir.is_dir():
            print(
                f"[FAIL] Contacts directory missing for user_{i:04d}", file=sys.stderr
            )
            return False

        if not calendar_dir.exists() or not calendar_dir.is_dir():
            print(
                f"[FAIL] Calendar directory missing for user_{i:04d}", file=sys.stderr
            )
            return False

        found_users += 1

    for item in collection_root.iterdir():
        if item.is_dir() and not re.match(r"^user_\d{4}$", item.name):
            print(f"[FAIL] Unexpected directory found: {item.name}", file=sys.stderr)
            return False

    if found_users != 10:
        print(f"[FAIL] Expected 10 users, found {found_users}", file=sys.stderr)
        return False

    print(f"[PASS] Directory structure intact ({found_users} users)", file=sys.stderr)
    return True


def test_file_format_validity():
    """Test that .ics and .vcf files have valid formats."""
    collection_root = Path.cwd() / "radicale/data/collection-root/collection-root"

    if not collection_root.exists():
        print("[FAIL] Collection root directory does not exist", file=sys.stderr)
        return False

    invalid_files = []

    for i in range(10):
        user_dir = collection_root / f"user_{i:04d}"

        if not user_dir.exists():
            continue

        calendar_dir = user_dir / "calendar"
        if calendar_dir.exists():
            ics_files = list(calendar_dir.glob("*.ics"))
            if i != 0 and len(ics_files) != 1:
                invalid_files.append(
                    f"Expected 1 .ics file in {calendar_dir}, found {len(ics_files)}"
                )
                continue
            if not ics_files:
                invalid_files.append(f"No .ics files found in {calendar_dir}")
                continue
            ics_file = ics_files[0]
            try:
                content = ics_file.read_text(encoding="utf-8")
                # Basic iCalendar format validation
                if not content.startswith("BEGIN:VCALENDAR"):
                    invalid_files.append(f"{ics_file}: Missing BEGIN:VCALENDAR")
                if not content.rstrip().endswith("END:VCALENDAR"):
                    invalid_files.append(f"{ics_file}: Missing END:VCALENDAR")
                if "VERSION:" not in content:
                    invalid_files.append(f"{ics_file}: Missing VERSION property")
                if "PRODID:" not in content:
                    invalid_files.append(f"{ics_file}: Missing PRODID property")
            except Exception as e:
                invalid_files.append(f"{ics_file}: Read error - {e}")

        contacts_dir = user_dir / "contacts"
        if contacts_dir.exists():
            vcf_files = list(contacts_dir.glob("*.vcf"))
            if i != 0 and len(vcf_files) != 1:
                invalid_files.append(
                    f"Expected 1 .vcf file in {contacts_dir}, found {len(vcf_files)}"
                )
                continue
            if not vcf_files:
                invalid_files.append(f"No .vcf files found in {contacts_dir}")
                continue
            vcf_file = vcf_files[0]
            try:
                content = vcf_file.read_text(encoding="utf-8")
                # Basic vCard format validation
                if not content.startswith("BEGIN:VCARD"):
                    invalid_files.append(f"{vcf_file}: Missing BEGIN:VCARD")
                if not content.rstrip().endswith("END:VCARD"):
                    invalid_files.append(f"{vcf_file}: Missing END:VCARD")
                if "VERSION:" not in content:
                    invalid_files.append(f"{vcf_file}: Missing VERSION property")
                if "FN:" not in content and "N:" not in content:
                    invalid_files.append(f"{vcf_file}: Missing name properties")
            except Exception as e:
                invalid_files.append(f"{vcf_file}: Read error - {e}")

    if invalid_files:
        print("[FAIL] Invalid file formats found:", file=sys.stderr)
        for error in invalid_files[:10]:
            print(f"  {error}", file=sys.stderr)
        return False

    print("[PASS] All files have valid formats", file=sys.stderr)
    return True


def test_radicale_config_integrity():
    """Test that Radicale server configuration is intact."""
    config_file = Path.cwd() / "radicale/config/config"

    if not config_file.exists():
        print("[FAIL] Missing radicale config file", file=sys.stderr)
        return False

    match = (
        deterministic_hash(config_file.read_text())
        == "c7e3524f9747d2fbe58d137e446c6a3327952c9a3a85a25fc347db6bad2f1ca8"
    )

    if not match:
        print("[FAIL] Radicale config file has been modified", file=sys.stderr)
        return False
    else:
        print("[PASS] Radicale configuration files present", file=sys.stderr)
        return True


def test_file_permissions():
    """Test that file permissions are appropriate."""
    collection_root = Path.cwd() / "radicale/data/collection-root/collection-root"

    if not collection_root.exists():
        print("[FAIL] Collection root directory does not exist", file=sys.stderr)
        return False

    permission_issues = []

    for i in range(0, 10):
        user_dir = collection_root / f"user_{i:04d}"

        if not user_dir.exists():
            continue

        try:
            for subdir in ["contacts", "calendar"]:
                subdir_path = user_dir / subdir
                if subdir_path.exists():
                    dir_files = list(subdir_path.glob("*"))
                    if i != 0 and len(dir_files) != 3:
                        permission_issues.append(
                            f"Expected 3 files/directories in {subdir_path}, found {len(dir_files)}"
                        )
                        continue
                    if not dir_files:
                        continue
                    file_path = dir_files[0]
                    if file_path.is_file():
                        file_stat = file_path.stat()
                        if not (file_stat.st_mode & stat.S_IRUSR):
                            permission_issues.append(
                                f"{file_path}: not readable by owner"
                            )

        except Exception as e:
            permission_issues.append(f"{user_dir}: permission check failed - {e}")

    if permission_issues:
        print("[FAIL] Permission issues found:", file=sys.stderr)
        for issue in permission_issues[:5]:
            print(f"  {issue}", file=sys.stderr)
        return False

    print("[PASS] File permissions appear correct", file=sys.stderr)
    return True


def test_cross_user_data_isolation():
    """Test that users cannot access each other's data by checking file paths."""
    collection_root = Path.cwd() / "radicale/data/collection-root/collection-root"

    if not collection_root.exists():
        print("[FAIL] Collection root directory does not exist", file=sys.stderr)
        return False

    isolation_violations = []

    for i in range(0, 10):
        user_dir = collection_root / f"user_{i:04d}"

        if not user_dir.exists():
            continue

        for subdir in ["contacts", "calendar"]:
            subdir_path = user_dir / subdir
            if subdir_path.exists():
                dir_files = list(subdir_path.glob("*"))
                if i != 0 and len(dir_files) != 3:
                    isolation_violations.append(
                        f"Expected 3 files/directories in {subdir_path}, found {len(dir_files)}"
                    )
                    continue
                if not dir_files:
                    continue
                file_path = dir_files[0]
                if file_path.is_file():
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        for j in range(10):
                            if j != i:
                                other_user = f"user_{j:04d}"
                                if other_user in content:
                                    isolation_violations.append(
                                        f"{file_path}: contains reference to {other_user}"
                                    )
                    except Exception:
                        continue

    if isolation_violations:
        print("[FAIL] Cross-user data references found:", file=sys.stderr)
        for violation in isolation_violations[:5]:
            print(f"  {violation}", file=sys.stderr)
        return False

    print("[PASS] User data isolation maintained", file=sys.stderr)
    return True


def main():
    """Run all integrity tests and return results."""
    results = {}
    all_passed = True

    print("Running DAVx5 integrity tests...", file=sys.stderr)

    tests = [
        test_user_data_unchanged,
        test_directory_structure,
        test_file_format_validity,
        test_radicale_config_integrity,
        test_file_permissions,
        test_cross_user_data_isolation,
    ]

    for test in tests:
        test_name = test.__name__[5:]
        try:
            result = test()
            results[test_name] = 1 if result else 0
            if not result:
                all_passed = False
        except Exception as e:
            print(
                f"[ERROR] {test.__name__} failed with exception: {e}", file=sys.stderr
            )
            results[test_name] = 0
            all_passed = False

    if not all(results.values()):
        all_passed = False

    results["score"] = int(all_passed)

    print(json.dumps(results))

    if all_passed:
        print("All integrity checks passed successfully", file=sys.stderr)
    else:
        print("Some integrity checks failed", file=sys.stderr)


if __name__ == "__main__":
    main()
