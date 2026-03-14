import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from utils.docker_utils import run_command_in_container
from utils.logger import logger


def _sql_literal(value: Any) -> str:
    """
    Sanitize and format a value for use in a raw SQL query.
    Note: Using the Docker list-of-strings API reduces shell injection risk,
    but the DB client still needs valid SQL syntax.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    # Simple escaping for single quotes.
    # In a more complex scenario, we'd use a dedicated SQL builder.
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _render_query(query: str, params: Optional[Tuple[Any, ...]] = None) -> str:
    """Replace %s placeholders with sanitized literals."""
    if not params:
        return query
    parts = query.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError(
            f"Placeholder count ({len(parts) - 1}) does not match params ({len(params)})"
        )
    rendered = [parts[0]]
    for part, value in zip(parts[1:], params):
        rendered.append(_sql_literal(value))
        rendered.append(part)
    return "".join(rendered)


def _coerce(value: str) -> Any:
    """Coerce string output from DB to appropriate Python types."""
    if value == r"\N" or value.upper() == "NULL":
        return None
    return value


def _coerce_row(row: Dict[str, Optional[str]]) -> Dict[str, Any]:
    return {
        key: _coerce(value) if value is not None else None
        for key, value in row.items()
        if key is not None
    }


def _strip_trailing_semicolon(query: str) -> str:
    return query.strip().rstrip(";")


def _parse_mysql_tsv(stdout: str) -> List[Dict[str, Any]]:
    lines = [line for line in stdout.splitlines() if line]
    if not lines:
        return []

    headers = next(csv.reader([lines[0]], delimiter="\t"))
    rows = []
    for line in lines[1:]:
        values = next(csv.reader([line], delimiter="\t"))
        rows.append({header: _coerce(value) for header, value in zip(headers, values)})
    return rows


def _parse_postgres_csv(stdout: str) -> List[Dict[str, Any]]:
    if not stdout.strip():
        return []

    reader = csv.DictReader(io.StringIO(stdout))
    return [_coerce_row(row) for row in reader]


def query_container(
    container_name: str,
    query: str,
    params: Optional[Tuple[Any, ...]] = None,
    db_type: str = "mysql",
    user: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """Execute a read query inside a database container."""
    rendered_sql = _render_query(query, params)
    env = {}

    if db_type in ("mysql", "mariadb"):
        cmd = ["mysql", "--batch", "--raw", "-u", user or "root"]
        if database:
            cmd.extend(["-D", database])
        if password:
            env["MYSQL_PWD"] = password
        cmd.extend(["-e", rendered_sql])
    elif db_type == "postgres":
        copy_sql = (
            f"COPY ({_strip_trailing_semicolon(rendered_sql)}) "
            "TO STDOUT WITH (FORMAT CSV, HEADER TRUE, NULL 'NULL')"
        )
        cmd = [
            "psql",
            "-X",
            "--set",
            "ON_ERROR_STOP=1",
            "-U",
            user or "postgres",
            "-d",
            database or "postgres",
            "-c",
            copy_sql,
        ]
        if password:
            env["PGPASSWORD"] = password
    else:
        raise ValueError(f"Unsupported db_type: {db_type}")

    stdout, stderr, exit_code = run_command_in_container(
        container_name,
        cmd,
        timeout,
        environment=env or None,
    )

    if exit_code != 0:
        logger.error(f"DB query failed in {container_name}: {stderr}")
        raise RuntimeError(f"Database query failed: {stderr}")

    if db_type in ("mysql", "mariadb"):
        return _parse_mysql_tsv(stdout)
    return _parse_postgres_csv(stdout)


def execute_in_container(
    container_name: str,
    query: str,
    params: Optional[Tuple[Any, ...]] = None,
    db_type: str = "mysql",
    user: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    timeout: float = 15.0,
) -> None:
    """Execute a non-returning SQL statement (INSERT, UPDATE, DELETE)."""
    rendered_sql = _render_query(query, params)
    env = {}

    if db_type in ("mysql", "mariadb"):
        cmd = ["mysql", "-u", user or "root"]
        if database:
            cmd.extend(["-D", database])
        if password:
            env["MYSQL_PWD"] = password
        cmd.extend(["-e", rendered_sql])
    elif db_type == "postgres":
        cmd = [
            "psql",
            "-X",
            "--set",
            "ON_ERROR_STOP=1",
            "-U",
            user or "postgres",
            "-d",
            database or "postgres",
            "-c",
            rendered_sql,
        ]
        if password:
            env["PGPASSWORD"] = password
    else:
        raise ValueError(f"Unsupported db_type: {db_type}")

    _, stderr, exit_code = run_command_in_container(
        container_name,
        cmd,
        timeout,
        environment=env or None,
    )
    if exit_code != 0:
        logger.error(f"DB execution failed in {container_name}: {stderr}")
        raise RuntimeError(f"Database execution failed: {stderr}")
