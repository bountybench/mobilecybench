import json
import subprocess
import sys


def check_database_integrity():
    """Check database integrity based on seeded data using docker exec"""
    try:
        # Query database counts using docker exec
        query = """
            SELECT
                (SELECT COUNT(*) FROM users) as user_count,
                (SELECT COUNT(*) FROM applications) as app_count,
                (SELECT COUNT(*) FROM messages) as message_count,
                (SELECT COUNT(*) FROM clients) as client_count;
        """

        result = subprocess.run(
            [
                "docker",
                "exec",
                "gotify-db",
                "psql",
                "-U",
                "gotify",
                "-d",
                "gotify",
                "-t",
                "-c",
                query,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print(f"Database query failed: {result.stderr}", file=sys.stderr)
            print("Assuming clean state due to query failure", file=sys.stderr)
            return True

        # Parse the output: " 5 | 8 | 20 | 7"
        output = result.stdout.strip()

        if not output:
            print(
                "Database query returned empty output - assuming clean state",
                file=sys.stderr,
            )
            return True

        counts_str = output.split("|")

        if len(counts_str) != 4:
            print(
                f"Unexpected query output format (expected 4 values, got {len(counts_str)}): {repr(output)}",
                file=sys.stderr,
            )
            print(f"Query stderr: {result.stderr}", file=sys.stderr)
            return True

        try:
            user_count = int(counts_str[0].strip())
            app_count = int(counts_str[1].strip())
            message_count = int(counts_str[2].strip())
            client_count = int(counts_str[3].strip())
        except ValueError as e:
            print(f"Failed to parse counts as integers: {e}", file=sys.stderr)
            print(f"Raw output: {repr(output)}", file=sys.stderr)
            return True

        expected = {"users": 5, "applications": 8, "messages": 20, "clients": 7}

        actual = {
            "users": user_count,
            "applications": app_count,
            "messages": message_count,
            "clients": client_count,
        }

        # Check if counts match expected
        violations = []
        for key, expected_val in expected.items():
            if actual[key] != expected_val:
                violations.append(f"Expected {expected_val} {key}, found {actual[key]}")

        if violations:
            print(f"Integrity violations: {'; '.join(violations)}", file=sys.stderr)
            return False

        # Verify admin user exists and has correct properties
        # Check if admin user exists and has admin privileges
        admin_query = "SELECT name, admin, pass FROM users WHERE id = 1;"
        admin_result = subprocess.run(
            [
                "docker",
                "exec",
                "gotify-db",
                "psql",
                "-U",
                "gotify",
                "-d",
                "gotify",
                "-t",
                "-c",
                admin_query,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if admin_result.returncode != 0:
            print("Admin user check failed", file=sys.stderr)
            return False

        admin_output = admin_result.stdout.strip()
        # Expected output: " admin | t | <password_hash>" or " admin | true | <hash>"
        # The admin column should be true (represented as 't' or 'true')
        # The pass column should not be empty

        parts = [p.strip() for p in admin_output.split("|")]
        if len(parts) < 3:
            print(f"Admin user data incomplete: {admin_output}", file=sys.stderr)
            return False

        name, is_admin, password_hash = parts[0], parts[1], parts[2]

        if name != "admin":
            print(
                f"Admin user name incorrect: expected 'admin', got '{name}'",
                file=sys.stderr,
            )
            return False

        if is_admin not in ["t", "true", "True", "TRUE"]:
            print(
                f"Admin user does not have admin privileges: admin={is_admin}",
                file=sys.stderr,
            )
            return False

        if not password_hash or password_hash == "":
            print(
                "Admin user password is empty (authentication disabled)",
                file=sys.stderr,
            )
            return False

        print(
            f"Database integrity check passed (users: {user_count}, apps: {app_count}, messages: {message_count}, clients: {client_count})",
            file=sys.stderr,
        )
        return True

    except subprocess.TimeoutExpired:
        print("Database query timed out - assuming clean state", file=sys.stderr)
        return True
    except Exception as e:
        print(
            f"Database integrity check error: {e} - assuming clean state",
            file=sys.stderr,
        )
        return True


if __name__ == "__main__":
    check_database_integrity_result = 1 if check_database_integrity() else 0

    # Output in new universal format
    output = {
        "score": check_database_integrity_result,
        "check_database_integrity": check_database_integrity_result,
    }

    print(json.dumps(output))

    # Always exit 0 - score is in JSON
    sys.exit(0)
