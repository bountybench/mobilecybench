#!/usr/bin/env python3
import base64
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPO_ROOT = "/mobilecybench"
UDS_SOCK = os.path.join(REPO_ROOT, "mcb.sock")
BRIDGE_PORT = os.environ.get("MCB_BRIDGE_PORT", "52888")
TCP_URL = f"http://host.docker.internal:{BRIDGE_PORT}"
UDS_URL = "http://localhost"
TOKEN_FILE = os.path.join(REPO_ROOT, "ssh_key")


def read_token():
    try:
        return open(TOKEN_FILE).read().strip()
    except Exception:
        return ""


def shutil_which(name):
    from shutil import which

    return which(name)


def is_uds_socket():
    try:
        return os.path.exists(UDS_SOCK) and stat.S_ISSOCK(os.stat(UDS_SOCK).st_mode)
    except Exception:
        return False


def call_via_unix_raw(path, payload_json_str):
    if not shutil_which("curl"):
        return "", "curl not found in container", 2
    try:
        cp = subprocess.run(
            [
                "curl",
                "-sS",
                "--unix-socket",
                UDS_SOCK,
                "-H",
                "Content-Type: application/json",
                "-X",
                "POST",
                f"{UDS_URL}{path}",
                "-d",
                payload_json_str,
            ],
            capture_output=True,
            text=True,
        )
        return cp.stdout, cp.stderr, cp.returncode
    except Exception as e:
        return "", str(e), 2


def call_via_tcp_json(path, payload_bytes, token):
    req = urllib.request.Request(
        f"{TCP_URL}{path}",
        data=payload_bytes,
        headers={"Content-Type": "application/json", "X-MCB-TOKEN": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read().decode()
            return body, "", 0
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
            return body, f"HTTPError: {e}", 1
        except Exception:
            return "", str(e), 1
    except Exception as e:
        return "", str(e), 2


def upload_file_to_host(local_path):
    if not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)
    filename = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode()
    payload = {"filename": filename, "data_b64": data_b64}
    payload_str = json.dumps(payload)

    if is_uds_socket():
        out, err, rc = call_via_unix_raw("/push_file", payload_str)
        if rc == 0 and out:
            try:
                obj = json.loads(out)
                return obj.get("path")
            except Exception:
                return out.strip()
    token = read_token()
    if not token:
        sys.stderr.write(
            "host bridge token is missing; run the host-side setup to create the token.\n"
        )
        raise SystemExit(1)
    out, err, rc = call_via_tcp_json("/push_file", payload_str.encode(), token)
    if rc == 0 and out:
        try:
            obj = json.loads(out)
            return obj.get("path")
        except Exception:
            return out.strip()
    raise RuntimeError(f"upload failed: rc={rc} err={err} out={out}")


def call_adb(args):
    payload = {"args": args, "token": read_token()}
    payloadb = json.dumps(payload).encode()

    if is_uds_socket():
        out, err, rc = call_via_unix_raw("/adb", json.dumps(payload))
        if rc == 0:
            try:
                obj = json.loads(out)
                sys.stdout.write(obj.get("stdout", ""))
                sys.stderr.write(obj.get("stderr", ""))
                raise SystemExit(int(obj.get("exit_code", 0) or 0))
            except Exception:
                sys.stdout.write(out)
                raise SystemExit(0)

    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                f"{TCP_URL}/adb",
                data=payloadb,
                headers={
                    "Content-Type": "application/json",
                    "X-MCB-TOKEN": read_token(),
                },
                method="POST",
            ),
            timeout=300,
        ) as resp:
            body = resp.read().decode()
            try:
                obj = json.loads(body)
                sys.stdout.write(obj.get("stdout", ""))
                sys.stderr.write(obj.get("stderr", ""))
                raise SystemExit(int(obj.get("exit_code", 0) or 0))
            except Exception:
                sys.stdout.write(body)
                raise SystemExit(0)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
            ob = json.loads(body)
            sys.stdout.write(ob.get("stdout", ""))
            sys.stderr.write(ob.get("stderr", ""))
            raise SystemExit(int(ob.get("exit_code", 1) or 1))
        except Exception:
            sys.stderr.write(f"HTTPError: {e}\n")
            raise SystemExit(1)
    except Exception as e:
        sys.stderr.write(f"Error contacting host bridge: {e}\n")
        raise SystemExit(2)


def is_local_file_arg(arg):
    return arg.startswith("/") or (arg and os.path.exists(arg))


def main():
    args = sys.argv[1:]
    if not args:
        call_adb(args)
        return

    if "install" in args or any(a.startswith("install") for a in args):
        new_args = []
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("install", "install-multiple", "install-multi") or a.startswith(
                "install"
            ):
                new_args.append(a)
                i += 1
                continue
            if a.startswith("-"):
                new_args.append(a)
                i += 1
                continue
            if is_local_file_arg(a) and os.path.exists(a):
                try:
                    host_path = upload_file_to_host(a)
                    if not host_path:
                        raise RuntimeError("no host path returned")
                    new_args.append(host_path)
                except Exception as e:
                    sys.stderr.write(f"Failed to upload {a} to host: {e}\n")
                    raise SystemExit(1)
                i += 1
                continue
            else:
                new_args.append(a)
                i += 1
                continue
        call_adb(new_args)
        return
    call_adb(args)


if __name__ == "__main__":
    main()
