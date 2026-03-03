import re
import subprocess
from typing import Any

DB_CONTAINER = "owncloud_mariadb"
DB_NAME = "owncloud"
DB_USER = "owncloud"
DB_PASSWORD = "owncloud"

_INT_RE = re.compile(r"^-?\d+$")


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


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
    def __init__(self, dictionary: bool = True) -> None:
        self._dictionary = dictionary
        self._rows: list[Any] = []

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        rendered = _render_query(query, params)
        cmd = [
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "mysql",
            "-u",
            DB_USER,
            f"-p{DB_PASSWORD}",
            "-D",
            DB_NAME,
            "--batch",
            "--raw",
            "-e",
            rendered,
        ]
        if not self._dictionary:
            cmd.insert(-2, "--skip-column-names")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line for line in result.stdout.splitlines() if line]
        if not lines:
            self._rows = []
            return
        if self._dictionary:
            headers = lines[0].split("\t")
            self._rows = []
            for line in lines[1:]:
                values = [_coerce(cell) for cell in line.split("\t")]
                self._rows.append(dict(zip(headers, values)))
            return
        self._rows = [
            tuple(_coerce(cell) for cell in line.split("\t")) for line in lines
        ]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self) -> None:
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


class Connection:
    def cursor(self, dictionary: bool = True) -> Cursor:
        return Cursor(dictionary=dictionary)

    def close(self) -> None:
        return None


def connect_db() -> Connection:
    return Connection()


def exec_sql(query: str, params: tuple[Any, ...] | None = None) -> None:
    rendered = _render_query(query, params)
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            DB_CONTAINER,
            "mysql",
            "-u",
            DB_USER,
            f"-p{DB_PASSWORD}",
            "-D",
            DB_NAME,
            "-e",
            rendered,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
