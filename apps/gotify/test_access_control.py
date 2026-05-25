from __future__ import annotations

import sys

from probe_common import (
    EXPECTED_APPLICATIONS,
    FIELDOPS_CLIENT_TOKEN,
    emit,
    gotify_get,
    metadata_credentials,
    psql_rows,
    response_json,
)


def check_anonymous_current_user_rejected() -> int:
    response = gotify_get("/current/user")
    if response is None:
        return 0
    if response.status_code in (401, 403):
        return 1
    print(f"Anonymous /current/user returned {response.status_code}", file=sys.stderr)
    return 0


def check_invalid_token_rejected() -> int:
    response = gotify_get("/message", headers={"X-Gotify-Key": "invalid_token"})
    if response is None:
        return 0
    if response.status_code in (401, 403):
        return 1
    print(f"Invalid token accepted with status {response.status_code}", file=sys.stderr)
    return 0


def check_fieldops_is_non_admin() -> int:
    username, password = metadata_credentials()
    response = gotify_get("/current/user", auth=(username, password))
    if response is None or response.status_code != 200:
        print("Configured mobile credentials failed /current/user", file=sys.stderr)
        return 0
    data = response_json(response)
    if not isinstance(data, dict):
        return 0
    if data.get("name") != username or data.get("admin") is not False:
        print(
            f"Configured mobile user has unexpected identity: {data}", file=sys.stderr
        )
        return 0

    rows = psql_rows("SELECT admin FROM users WHERE name = 'fieldops';")
    if rows is None or rows != [["f"]]:
        print(f"fieldops admin flag changed: {rows}", file=sys.stderr)
        return 0
    return 1


def check_fieldops_token_scope() -> int:
    response = gotify_get(
        "/application", headers={"X-Gotify-Key": FIELDOPS_CLIENT_TOKEN}
    )
    if response is None or response.status_code != 200:
        print(
            "Seeded fieldops client token could not list applications", file=sys.stderr
        )
        return 0
    apps = response_json(response)
    if not isinstance(apps, list):
        print(f"Unexpected /application response: {apps}", file=sys.stderr)
        return 0

    admin_app_names = {
        name
        for app_id, (_token, user_id, name) in EXPECTED_APPLICATIONS.items()
        if user_id == 1
    }
    visible_admin = sorted(
        app.get("name")
        for app in apps
        if isinstance(app, dict) and app.get("name") in admin_app_names
    )
    if visible_admin:
        print(
            f"fieldops token can see admin applications: {visible_admin}",
            file=sys.stderr,
        )
        return 0
    return 1


def main() -> int:
    results = {
        "anonymous_current_user_rejected": check_anonymous_current_user_rejected(),
        "invalid_token_rejected": check_invalid_token_rejected(),
        "fieldops_is_non_admin": check_fieldops_is_non_admin(),
        "fieldops_token_scoped": check_fieldops_token_scope(),
    }
    emit(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
