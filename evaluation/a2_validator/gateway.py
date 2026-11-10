"""Read-only device/backend gateway for the A2-style Task Validator.

Runs on the HOST (it owns the adb client and docker CLI). The Validator agent
runs in a container on an `internal` Docker network with no adb binary and no
route to the host; its only path to the device is HTTP to this gateway via the
egress proxy. Every request is policy-checked here and appended to an audit
log, so the read-only guarantee is identical for every agent CLI.

Ops mirror the Validator's read-only tools in A2 Table 2 (Wang & Zhou 2025):
  shell    execute_shell_command (allowlisted read-only commands only)
  ls       list_directory_contents
  exists   check_file_existence
  pull     pull_device_file (returns base64 content)
  grep     analyze_file_content
  sqlite   read-only SELECT on a host-side COPY of a device database
  ui_dump  capture_ui_layout
  ui_find  find_ui_elements / verify_element_exists
  logcat   search_system_logs
  http_get (remote-attacker only) GET to the app backend
  db_query (remote-attacker only) read-only query on the backend database
Code navigation (extract_source_code, search_code_patterns,
enumerate_source_files) needs no gateway: the app source is mounted read-only
into the Validator's workdir.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shlex
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MAX_OUT = 200_000  # bytes returned per op; the agent can narrow with grep
# Command separators, pipes, redirects and substitutions. Globs, quotes and
# parentheses are fine: every argv token is shlex.quote()d before it reaches
# the device shell, so they arrive as literal arguments.
SHELL_META = re.compile(r"[;&|<>`$\\\n\r]")
PATH_META = re.compile(r"[;&|<>`$\\\n\r(){}*?!'\" ]")

# Read-only shell commands. Each value is a predicate over argv[1:] that
# returns an error string (refuse) or None (allow).
_FIND_BAD = {
    "-delete",
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
    "-fprint",
    "-fprint0",
    "-fprintf",
    "-fls",
}
_DUMPSYS_SERVICES = {
    "activity",
    "window",
    "package",
    "notification",
    "alarm",
    "account",
    "content",
    "connectivity",
    "input_method",
    "media_session",
    "usagestats",
    "power",
    "appops",
    "meminfo",
    "cpuinfo",
    "user",
    "jobscheduler",
    "clipboard",
    "netstats",
    "role",
    "permission",
    "telecom",
    "location",
    "dropbox",
    "batterystats",
    "deviceidle",
    "procstats",
    "gfxinfo",
    "dbinfo",
    "uimode",
    "display",
    "statusbar",
    "wifi",
}
_STATE_VERBS = {
    "set",
    "reset",
    "unplug",
    "enable",
    "disable",
    "force-idle",
    "unforce",
    "step",
    "clear",
    "kill",
    "write",
    "put",
    "delete",
    "insert",
    "update",
    "run",
    "start",
    "stop",
    "broadcast",
    "grant",
    "revoke",
    "whitelist",
    "tempwhitelist",
    "except-idle-whitelist",
    "--reset",
    "--charged",
    "--write",
    "--clear",
    "-c",
}


def _no_state_verbs(args: list[str]) -> str | None:
    bad = [a for a in args if a.lower() in _STATE_VERBS]
    return f"state-changing argument(s) {bad}" if bad else None


def _dumpsys(args: list[str]) -> str | None:
    if not args:
        return "dumpsys needs a service name"
    if args[0] not in _DUMPSYS_SERVICES:
        return f"dumpsys service {args[0]!r} not in read-only allowlist"
    return _no_state_verbs(args[1:])


def _find(args: list[str]) -> str | None:
    bad = [a for a in args if a in _FIND_BAD]
    return f"find action(s) {bad} not allowed" if bad else None


def _logcat(args: list[str]) -> str | None:
    if "-d" not in args:
        return "logcat must be non-blocking dump (-d)"
    bad = [
        a
        for a in args
        if a
        in {
            "-c",
            "--clear",
            "-G",
            "-P",
            "-f",
            "--file",
            "-r",
            "-n",
            "--prune",
            "--buffer-size",
        }
    ]
    return f"logcat option(s) {bad} not allowed" if bad else None


def _settings(args: list[str]) -> str | None:
    return (
        None
        if args and args[0] in {"get", "list"}
        else "only `settings get|list` allowed"
    )


def _content(args: list[str]) -> str | None:
    return None if args and args[0] == "query" else "only `content query` allowed"


def _pm(args: list[str]) -> str | None:
    if args[:2] == ["list", "packages"] or (args and args[0] in {"path", "dump"}):
        return None
    return "only `pm list packages`, `pm path` and `pm dump` are allowed"


def _any(_args: list[str]) -> str | None:
    return None


SHELL_ALLOW = {
    "ls": _any,
    "cat": _any,
    "head": _any,
    "tail": _any,
    "wc": _any,
    "stat": _any,
    "file": _any,
    "readlink": _any,
    "realpath": _any,
    "md5sum": _any,
    "sha256sum": _any,
    "grep": _any,
    "egrep": _any,
    "strings": _any,
    "xxd": _any,
    "od": _any,
    "find": _find,
    "id": _any,
    "whoami": _any,
    "date": _any,
    "uptime": _any,
    "ps": _any,
    "pidof": _any,
    "df": _any,
    "du": _any,
    "netstat": _any,
    "getprop": lambda a: None if len(a) <= 1 else "getprop takes at most one key",
    "dumpsys": _dumpsys,
    "logcat": _logcat,
    "pm": _pm,
    "settings": _settings,
    "content": _content,
}


def check_shell(cmd: str) -> tuple[list[str] | None, str | None]:
    """Return (argv, None) if the command is allowed, else (None, reason)."""
    if SHELL_META.search(cmd):
        return None, (
            "pipes, redirects, command separators and substitutions (; & | < > ` $ \\ newline) "
            "are not allowed; run one command and filter its output locally"
        )
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return None, f"unparseable command: {e}"
    if not argv:
        return None, "empty command"
    prog = argv[0].rsplit("/", 1)[-1]
    rule = SHELL_ALLOW.get(prog)
    if rule is None:
        return (
            None,
            f"{prog!r} is not a read-only command (allowed: {sorted(SHELL_ALLOW)})",
        )
    err = rule(argv[1:])
    return (None, err) if err else ([prog, *argv[1:]], None)


def _check_path(p: str) -> str | None:
    if not isinstance(p, str) or not p.startswith("/"):
        return "path must be absolute"
    if PATH_META.search(p):
        return "path contains disallowed characters"
    return None


SQL_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _sql_authorizer(action, *_):
    if action in SQL_ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA:  # PRAGMA table_info etc. are reads on a copy
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _select_on_copy(local: Path, sql: str) -> dict[str, Any]:
    """Run one read-only statement on a local copy of an SQLite database."""
    con = sqlite3.connect(local)
    try:
        con.execute("PRAGMA wal_checkpoint")  # fold WAL into the copy
        con.set_authorizer(_sql_authorizer)
        try:
            cur = con.execute(sql)
        except (sqlite3.DatabaseError, sqlite3.ProgrammingError) as e:
            if "not authorized" in str(e) or "one statement" in str(e):
                raise PermissionError(
                    f"read-only: only SELECT queries are allowed ({e})"
                )
            raise
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(500)
    finally:
        con.close()
    return {"columns": cols, "rows": [[_jsonable(v) for v in r] for r in rows]}


class Gateway:
    def __init__(
        self,
        serial: str,
        packages: list[str],
        audit_path: Path,
        backend: dict[str, Any] | None = None,
    ):
        self.serial = serial
        self.packages = packages
        self.audit_path = audit_path
        self.backend = backend or {}
        self._lock = threading.Lock()

    # -- adb plumbing (gateway-internal; never exposed raw) --------------------
    def _adb(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["adb", "-s", self.serial, *args], capture_output=True, timeout=timeout
        )

    def _sh(self, argv: list[str], timeout: int = 60) -> tuple[int, bytes]:
        # adb joins argv into one string for the device shell: quote each arg.
        r = self._adb(
            "exec-out", " ".join(shlex.quote(a) for a in argv), timeout=timeout
        )
        return r.returncode, r.stdout + r.stderr

    # -- ops -------------------------------------------------------------------
    def op_shell(self, a):
        argv, err = check_shell(a.get("cmd", ""))
        if err:
            raise PermissionError(err)
        rc, out = self._sh(argv)
        return {"exit_code": rc, "output": out.decode(errors="replace")}

    def op_ls(self, a):
        p = a.get("path", "")
        if e := _check_path(p):
            raise PermissionError(e)
        rc, out = self._sh(["ls", "-la", p])
        return {"exit_code": rc, "output": out.decode(errors="replace")}

    def op_exists(self, a):
        p = a.get("path", "")
        if e := _check_path(p):
            raise PermissionError(e)
        rc, out = self._sh(["stat", "-c", "%F %s %y", p])
        return {"exists": rc == 0, "detail": out.decode(errors="replace").strip()}

    def op_pull(self, a):
        p = a.get("path", "")
        if e := _check_path(p):
            raise PermissionError(e)
        rc, out = self._sh(["cat", p])
        if rc != 0:
            return {"exit_code": rc, "error": out.decode(errors="replace")}
        return {
            "exit_code": 0,
            "size": len(out),
            "content_b64": base64.b64encode(out).decode(),
        }

    def op_grep(self, a):
        p, pat = a.get("path", ""), a.get("pattern", "")
        if e := _check_path(p):
            raise PermissionError(e)
        rc, out = self._sh(["grep", "-rnE", "--", pat, p])
        return {"exit_code": rc, "output": out.decode(errors="replace")}

    def op_sqlite(self, a):
        p, sql = a.get("path", ""), a.get("sql", "")
        if e := _check_path(p):
            raise PermissionError(e)
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "db.sqlite"
            for suffix in ("", "-wal", "-shm"):
                rc, out = self._sh(["cat", p + suffix])
                if rc == 0:
                    (Path(td) / ("db.sqlite" + suffix)).write_bytes(out)
                elif suffix == "":
                    return {"exit_code": rc, "error": out.decode(errors="replace")}
            res = _select_on_copy(local, sql)
        return {**res, "note": "query ran on a host-side copy; device file untouched"}

    def op_ui_dump(self, _a):
        r = self._adb("exec-out", "uiautomator dump /dev/tty", timeout=60)
        xml = r.stdout.decode(errors="replace")
        return {
            "xml": xml.split("UI hierchary dumped")[0].split("UI hierarchy dumped")[0]
        }

    def op_ui_find(self, a):
        text = a.get("text", "")
        xml = self.op_ui_dump({})["xml"]
        nodes = re.findall(r"<node [^>]*>", xml)
        hits = [n for n in nodes if text.lower() in n.lower()]
        return {"exists": bool(hits), "matches": hits[:50]}

    def op_logcat(self, a):
        args = ["logcat", "-d", "-v", "time"]
        rc, out = self._sh(args, timeout=60)
        lines = out.decode(errors="replace").splitlines()
        if a.get("pattern"):
            rx = re.compile(a["pattern"])
            lines = [line for line in lines if rx.search(line)]
        return {"output": "\n".join(lines[-int(a.get("max_lines", 2000)) :])}

    def op_http_get(self, a):
        url = a.get("url", "")
        allowed = self.backend.get("http_prefixes", [])
        if not any(url.startswith(p) for p in allowed):
            raise PermissionError(f"URL not under the backend allowlist {allowed}")
        deny = self.backend.get(
            "http_deny_regex"
        )  # e.g. ntfy publishes via GET /<topic>/publish
        if deny and re.search(deny, url):
            raise PermissionError(
                "this GET endpoint changes server state on this backend"
            )
        req = urllib.request.Request(url, method="GET", headers=a.get("headers") or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read(MAX_OUT)
                return {
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": body.decode(errors="replace"),
                }
        except urllib.error.HTTPError as e:
            return {"status": e.code, "body": e.read(MAX_OUT).decode(errors="replace")}

    def op_db_query(self, a):
        db = self.backend.get("db")
        if not db:
            raise PermissionError("no backend database configured for this run")
        sql = a.get("sql", "")
        if not re.match(
            r"^\s*(select|with|show|describe|explain)\b", sql, re.I
        ) or ";" in sql.strip().rstrip(";"):
            raise PermissionError(
                "read-only: a single SELECT/WITH/SHOW/DESCRIBE statement only"
            )
        if db["engine"] == "postgres":
            # default_transaction_read_only makes the server reject any write.
            cmd = [
                "docker",
                "exec",
                "-e",
                "PGOPTIONS=-c default_transaction_read_only=on",
                db["container"],
                "psql",
                "-U",
                db["user"],
                "-d",
                db["database"],
                "-A",
                "-F",
                "\t",
                "-c",
                sql,
            ]
        elif db["engine"] == "mysql":
            cmd = [
                "docker",
                "exec",
                db["container"],
                "mysql",
                f"-u{db['user']}",
                f"-p{db['password']}",
                db["database"],
                "-B",
                "-e",
                f"SET SESSION TRANSACTION READ ONLY; START TRANSACTION; {sql.rstrip(';')}; ROLLBACK;",
            ]
        elif (
            db["engine"] == "sqlite"
        ):  # copy out (image may lack sqlite3), query the copy
            with tempfile.TemporaryDirectory() as td:
                for suffix in ("", "-wal", "-shm"):
                    subprocess.run(
                        [
                            "docker",
                            "cp",
                            f"{db['container']}:{db['path']}{suffix}",
                            f"{td}/db.sqlite{suffix}",
                        ],
                        capture_output=True,
                        timeout=60,
                    )
                if not Path(td, "db.sqlite").exists():
                    return {"exit_code": 1, "error": "could not copy backend database"}
                return _select_on_copy(Path(td, "db.sqlite"), sql)
        else:
            raise PermissionError(f"unsupported engine {db['engine']}")
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        return {
            "exit_code": r.returncode,
            "output": (r.stdout + r.stderr).decode(errors="replace"),
        }

    # -- state hash (called by the runner, not by the agent) -------------------
    def state_hash(self) -> dict[str, Any]:
        files: dict[str, str] = {}
        for pkg in self.packages:
            for root in (
                f"/data/data/{pkg}",
                f"/data/user_de/0/{pkg}",
                f"/sdcard/Android/data/{pkg}",
            ):
                r = self._adb(
                    "exec-out",
                    f"find {root} -type f -exec sha256sum {{}} + 2>/dev/null",
                    timeout=120,
                )
                for line in r.stdout.decode(errors="replace").splitlines():
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        files[parts[1]] = parts[0]
        r = self._adb("exec-out", "pm list packages", timeout=60)
        pkgs = sorted(r.stdout.decode(errors="replace").split())
        top = self._adb(
            "exec-out", "dumpsys activity activities", timeout=60
        ).stdout.decode(errors="replace")
        resumed = [
            ln.strip()
            for ln in top.splitlines()
            if "mResumedActivity" in ln or "topResumedActivity" in ln
        ]
        out: dict[str, Any] = {
            "files": files,
            "installed_packages": pkgs,
            "resumed_activity": resumed,
        }
        db = self.backend.get("db")
        if db and db.get("dump_cmd"):
            d = subprocess.run(db["dump_cmd"], capture_output=True, timeout=300)
            out["backend_db_sha256"] = hashlib.sha256(d.stdout).hexdigest()
        out["digest"] = hashlib.sha256(
            json.dumps(out, sort_keys=True).encode()
        ).hexdigest()
        return out

    def handle(self, op: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = getattr(self, f"op_{op}", None)
        t0 = time.time()
        if fn is None:
            res = {"ok": False, "refused": True, "error": f"unknown op {op!r}"}
        else:
            try:
                res = {"ok": True, **fn(args)}
            except PermissionError as e:
                res = {
                    "ok": False,
                    "refused": True,
                    "error": f"REFUSED (read-only gateway): {e}",
                }
            except Exception as e:  # report tool errors to the agent, keep serving
                res = {
                    "ok": False,
                    "refused": False,
                    "error": f"{type(e).__name__}: {e}",
                }
        for k in ("output", "body", "xml"):
            if isinstance(res.get(k), str) and len(res[k]) > MAX_OUT:
                res[k] = res[k][:MAX_OUT] + f"\n...[truncated to {MAX_OUT} chars]"
        with self._lock, self.audit_path.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "t": t0,
                        "dur_s": round(time.time() - t0, 3),
                        "op": op,
                        "args": args,
                        "ok": res["ok"],
                        "refused": res.get("refused", False),
                        "error": res.get("error"),
                    }
                )
                + "\n"
            )
        return res


def _jsonable(v):
    return base64.b64encode(v).decode() if isinstance(v, bytes) else v


def serve(gw: Gateway, host: str, port: int) -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                res = gw.handle(req.get("op", ""), req.get("args") or {})
            except json.JSONDecodeError:
                res = {"ok": False, "error": "bad JSON"}
            body = json.dumps(res).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default="emulator-5554")
    ap.add_argument("--package", action="append", default=[])
    ap.add_argument("--audit", default="gateway_audit.jsonl")
    ap.add_argument(
        "--backend-json",
        help="JSON file: {http_prefixes:[..], db:{engine,container,...}}",
    )
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    backend = json.loads(Path(a.backend_json).read_text()) if a.backend_json else None
    serve(Gateway(a.serial, a.package, Path(a.audit), backend), "127.0.0.1", a.port)
    print(f"gateway on 127.0.0.1:{a.port}", flush=True)
    threading.Event().wait()
