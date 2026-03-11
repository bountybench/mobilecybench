import pytest

from utils import db_container_utils


def test_render_query_replaces_placeholders_with_sql_literals():
    query = (
        "SELECT * FROM users WHERE email = %s AND active = %s "
        "AND attempts > %s AND note IS %s"
    )

    rendered = db_container_utils._render_query(
        query,
        ("o'hara\\test@example.com", True, 3, None),
    )

    assert (
        rendered == "SELECT * FROM users WHERE email = 'o''hara\\\\test@example.com' "
        "AND active = 1 AND attempts > 3 AND note IS NULL"
    )


def test_render_query_raises_for_placeholder_mismatch():
    with pytest.raises(ValueError, match="Placeholder count"):
        db_container_utils._render_query("SELECT %s, %s", ("only-one",))


def test_query_container_mysql_builds_expected_command_and_parses_rows(monkeypatch):
    captured = {}

    def fake_run(container_name, command, timeout, **kwargs):
        captured["container_name"] = container_name
        captured["command"] = command
        captured["timeout"] = timeout
        captured["environment"] = kwargs.get("environment")
        return "id\tname\tactive\tcount\n1\talice\t1\t0\n2\t\\N\t0\t12\n", "", 0

    monkeypatch.setattr(db_container_utils, "run_command_in_container", fake_run)

    rows = db_container_utils.query_container(
        "mysql-db",
        "SELECT id, name, active, count FROM users WHERE email = %s",
        ("alice@example.com",),
        db_type="mysql",
        user="app",
        password="secret",
        database="main_db",
        timeout=9.5,
    )

    assert captured["container_name"] == "mysql-db"
    assert captured["timeout"] == 9.5
    assert captured["environment"] == {"MYSQL_PWD": "secret"}
    assert captured["command"] == [
        "mysql",
        "--batch",
        "--raw",
        "-u",
        "app",
        "-D",
        "main_db",
        "-e",
        "SELECT id, name, active, count FROM users WHERE email = 'alice@example.com'",
    ]
    assert rows == [
        {"id": "1", "name": "alice", "active": "1", "count": "0"},
        {"id": "2", "name": None, "active": "0", "count": "12"},
    ]


def test_query_container_postgres_wraps_select_in_copy_and_parses_csv(monkeypatch):
    captured = {}

    def fake_run(container_name, command, timeout, **kwargs):
        captured["container_name"] = container_name
        captured["command"] = command
        captured["timeout"] = timeout
        captured["environment"] = kwargs.get("environment")
        return (
            "email,activated,count\nuser@example.com,true,7\nother@example.com,NULL,0\n",
            "",
            0,
        )

    monkeypatch.setattr(db_container_utils, "run_command_in_container", fake_run)

    rows = db_container_utils.query_container(
        "pg-db",
        "SELECT email, activated, count FROM users WHERE email = %s;",
        ("user@example.com",),
        db_type="postgres",
        user="postgres_user",
        password="postgres_pw",
        database="app_db",
    )

    assert captured["container_name"] == "pg-db"
    assert captured["environment"] == {"PGPASSWORD": "postgres_pw"}
    assert captured["command"] == [
        "psql",
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres_user",
        "-d",
        "app_db",
        "-c",
        "COPY (SELECT email, activated, count FROM users WHERE email = 'user@example.com') "
        "TO STDOUT WITH (FORMAT CSV, HEADER TRUE, NULL 'NULL')",
    ]
    assert rows == [
        {"email": "user@example.com", "activated": "true", "count": "7"},
        {"email": "other@example.com", "activated": None, "count": "0"},
    ]


def test_query_container_preserves_digit_strings_without_lossy_int_coercion(
    monkeypatch,
):
    def fake_run(container_name, command, timeout, **kwargs):
        return "code\n00123\n", "", 0

    monkeypatch.setattr(db_container_utils, "run_command_in_container", fake_run)

    rows = db_container_utils.query_container(
        "mysql-db",
        "SELECT code FROM users",
        db_type="mysql",
    )

    assert rows == [{"code": "00123"}]


def test_execute_in_container_postgres_uses_plain_psql_command(monkeypatch):
    captured = {}

    def fake_run(container_name, command, timeout, **kwargs):
        captured["container_name"] = container_name
        captured["command"] = command
        captured["timeout"] = timeout
        captured["environment"] = kwargs.get("environment")
        return "", "", 0

    monkeypatch.setattr(db_container_utils, "run_command_in_container", fake_run)

    db_container_utils.execute_in_container(
        "pg-db",
        "UPDATE users SET activated = %s WHERE email = %s",
        (False, "user@example.com"),
        db_type="postgres",
        user="postgres_user",
        password="postgres_pw",
        database="app_db",
        timeout=4,
    )

    assert captured["container_name"] == "pg-db"
    assert captured["timeout"] == 4
    assert captured["environment"] == {"PGPASSWORD": "postgres_pw"}
    assert captured["command"] == [
        "psql",
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres_user",
        "-d",
        "app_db",
        "-c",
        "UPDATE users SET activated = 0 WHERE email = 'user@example.com'",
    ]


def test_query_container_raises_runtime_error_on_command_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        return "", "database exploded", 1

    monkeypatch.setattr(db_container_utils, "run_command_in_container", fake_run)

    with pytest.raises(RuntimeError, match="database exploded"):
        db_container_utils.query_container(
            "pg-db",
            "SELECT 1",
            db_type="postgres",
        )


def test_query_container_rejects_unsupported_database_type():
    with pytest.raises(ValueError, match="Unsupported db_type"):
        db_container_utils.query_container(
            "db",
            "SELECT 1",
            db_type="sqlite",
        )
