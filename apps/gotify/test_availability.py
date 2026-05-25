from __future__ import annotations

import sys

from probe_common import (
    DB_CONTAINER,
    SERVER_CONTAINER,
    android_package_installed,
    docker_health,
    emit,
    gotify_get,
    metadata_credentials,
    psql_rows,
    response_json,
)


def check_server_container_healthy() -> int:
    return 1 if docker_health(SERVER_CONTAINER) else 0


def check_database_container_healthy() -> int:
    return 1 if docker_health(DB_CONTAINER) else 0


def check_http_health() -> int:
    response = gotify_get("/health")
    if response is None:
        return 0
    return 1 if response.status_code == 200 else 0


def check_database_query() -> int:
    rows = psql_rows("SELECT 1;")
    return 1 if rows == [["1"]] else 0


def check_fieldops_login() -> int:
    username, password = metadata_credentials()
    response = gotify_get("/current/user", auth=(username, password))
    if response is None or response.status_code != 200:
        return 0
    data = response_json(response)
    if not isinstance(data, dict):
        return 0
    return 1 if data.get("name") == username else 0


def check_android_package() -> int:
    return 1 if android_package_installed() else 0


def main() -> int:
    results = {
        "server_container_healthy": check_server_container_healthy(),
        "database_container_healthy": check_database_container_healthy(),
        "http_health": check_http_health(),
        "database_query": check_database_query(),
        "fieldops_login": check_fieldops_login(),
        "android_package_installed": check_android_package(),
    }
    emit(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
