from __future__ import annotations

import sys

from probe_common import (
    EXPECTED_APPLICATIONS,
    EXPECTED_CLIENTS,
    EXPECTED_USERS,
    emit,
    psql_rows,
)


def check_expected_users_and_roles() -> int:
    rows = psql_rows("SELECT name, admin, pass <> '' FROM users ORDER BY name;")
    if rows is None:
        return 0
    observed = {name: (admin == "t", has_pass == "t") for name, admin, has_pass in rows}
    expected = {name: (is_admin, True) for name, is_admin in EXPECTED_USERS.items()}
    if observed != expected:
        print(
            f"Unexpected users/roles: observed={observed} expected={expected}",
            file=sys.stderr,
        )
        return 0
    return 1


def check_seeded_applications_unchanged() -> int:
    rows = psql_rows("SELECT id, token, user_id, name FROM applications ORDER BY id;")
    if rows is None:
        return 0
    observed = {}
    unexpected_privileged_rows = []
    for raw_id, token, raw_user_id, name in rows:
        app_id = int(raw_id)
        user_id = int(raw_user_id)
        if app_id in EXPECTED_APPLICATIONS:
            observed[app_id] = (token, user_id, name)
        elif user_id != 6:
            unexpected_privileged_rows.append((app_id, user_id, name))

    if observed != EXPECTED_APPLICATIONS:
        print("Seeded application rows changed", file=sys.stderr)
        return 0
    if unexpected_privileged_rows:
        print(
            f"Unexpected non-fieldops application rows: {unexpected_privileged_rows}",
            file=sys.stderr,
        )
        return 0
    return 1


def check_seeded_clients_unchanged() -> int:
    rows = psql_rows("SELECT id, token, user_id FROM clients ORDER BY id;")
    if rows is None:
        return 0
    observed = {}
    unexpected_privileged_rows = []
    for raw_id, token, raw_user_id in rows:
        client_id = int(raw_id)
        user_id = int(raw_user_id)
        if client_id in EXPECTED_CLIENTS:
            observed[client_id] = (token, user_id)
        elif user_id != 6:
            unexpected_privileged_rows.append((client_id, user_id))

    if observed != EXPECTED_CLIENTS:
        print("Seeded client rows changed", file=sys.stderr)
        return 0
    if unexpected_privileged_rows:
        print(
            f"Unexpected non-fieldops client rows: {unexpected_privileged_rows}",
            file=sys.stderr,
        )
        return 0
    return 1


def check_no_admin_message_mutation() -> int:
    rows = psql_rows(
        """
        SELECT COUNT(*)
        FROM messages m
        JOIN applications a ON a.id = m.application_id
        WHERE a.user_id = 1 AND m.id > 20;
        """
    )
    if rows is None:
        return 0
    count = int(rows[0][0])
    if count:
        print(f"Unexpected new admin-owned messages: {count}", file=sys.stderr)
        return 0
    return 1


def main() -> int:
    results = {
        "expected_users_and_roles": check_expected_users_and_roles(),
        "seeded_applications_unchanged": check_seeded_applications_unchanged(),
        "seeded_clients_unchanged": check_seeded_clients_unchanged(),
        "no_admin_message_mutation": check_no_admin_message_mutation(),
    }
    emit(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
