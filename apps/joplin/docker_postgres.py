import csv
import io
import re
import subprocess
from typing import Any

DB_CONTAINER = "joplin-postgres"

_INT_RE = re.compile(r"^-?\d+$")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _render_query(query: str, params: tuple[Any, ...] | None) -> str:
    if not params:
        return query
    parts = query.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError("Placeholder count does not match params")
    rendered = [parts[0]]
    for part, value in zip(parts[1:], params):
        rendered.append(_sql_literal(value))
        rendered.append(part)
    return "".join(rendered)


def _coerce(value: str) -> Any:
    if _INT_RE.fullmatch(value):
        return int(value)
    return value


class Cursor:
    def __init__(self, dbname: str, user: str) -> None:
        self._dbname = dbname
        self._user = user
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        rendered = _render_query(query, params)
        copy_sql = f"COPY ({rendered}) TO STDOUT WITH CSV"
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                DB_CONTAINER,
                "psql",
                "-q",
                "-A",
                "-t",
                "-U",
                self._user,
                "-d",
                self._dbname,
                "-c",
                copy_sql,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        reader = csv.reader(io.StringIO(result.stdout))
        self._rows = [tuple(_coerce(cell) for cell in row) for row in reader if row]

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def close(self) -> None:
        self._rows = []


class Connection:
    def __init__(self, dbname: str, user: str) -> None:
        self._dbname = dbname
        self._user = user

    def cursor(self) -> Cursor:
        return Cursor(self._dbname, self._user)

    def close(self) -> None:
        return None


def connect_db(dbname: str, user: str) -> Connection:
    return Connection(dbname, user)
