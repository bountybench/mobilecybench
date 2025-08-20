#!/bin/bash
set -euo pipefail

REPO_ROOT="/mobilecybench"
AGENT_PORT="${MCB_AGENT_PORT:-52888}"
AGENT_TOKEN_FILE="${REPO_ROOT}/ssh_key"
UDS_PATH="${REPO_ROOT}/mcb.sock"
TCP_AGENT_URL="http://host.docker.internal:${AGENT_PORT}"
UDS_AGENT_URL="http://localhost"
AGENT_TOKEN="$(cat "${AGENT_TOKEN_FILE}" 2>/dev/null || true)"

call_start_via_uds() {
    if ! command -v curl >/dev/null 2>&1; then
        echo "[start_emulator_host] curl not available in container; cannot use UDS transport"
        return 1
    fi
    echo "[start_emulator_host] calling host agent via UDS ${UDS_PATH}"
    curl -sS --unix-socket "${UDS_PATH}" -H "Content-Type: application/json" -X POST "${UDS_AGENT_URL}/start" -d '{"token":""}' -w "\n%{http_code}" || return 1
}

call_start_via_tcp() {
    if [[ -z "${AGENT_TOKEN}" ]]; then
        echo "[start_emulator_host] No agent token found at ${AGENT_TOKEN_FILE}; cannot use TCP transport"
        return 1
    fi
    echo "[start_emulator_host] calling host agent via TCP ${TCP_AGENT_URL}"
    curl -sS -H "Content-Type: application/json" -H "X-MCB-TOKEN: ${AGENT_TOKEN}" -X POST "${TCP_AGENT_URL}/start" -d "{\"token\":\"${AGENT_TOKEN}\"}" -w "\n%{http_code}" || return 1
}

echo "[start_emulator_host] Starting host-agent start request..."

# Choose UDS if socket exists (repo is mounted into container so it will be visible)
if [[ -S "${UDS_PATH}" ]]; then
    RESP="$(call_start_via_uds || true)"
else
    RESP="$(call_start_via_tcp || true)"
fi

if [[ -z "${RESP}" ]]; then
    echo "[start_emulator_host] ERROR: no response from host agent"
    exit 1
fi

HTTP_BODY=$(echo "${RESP}" | sed '$d')
HTTP_STATUS=$(echo "${RESP}" | tail -n1)

echo "[start_emulator_host] HTTP ${HTTP_STATUS} response from host agent:"
echo "${HTTP_BODY}"

if [[ "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
    echo "[start_emulator_host] Agent accepted start request (HTTP ${HTTP_STATUS})."
    sleep 2

    # Install adb shim that prefers UDS (curl) but falls back to TCP (Python)
    SHIM_PATH="/usr/local/bin/adb"
    echo "[start_emulator_host] Installing adb shim at ${SHIM_PATH}"
    cat > "${SHIM_PATH}" <<'PYSHIM'
#!/usr/bin/env python3
"""
adb shim: forwards adb commands to host-agent, but will upload local files (e.g. APK)
to the host first when needed (adb install <local-path>).

Transport:
 - UDS (preferred): uses curl --unix-socket <repo>/mcb.sock to POST JSON to /push_file and /adb
 - TCP fallback: posts to http://host.docker.internal:52888 with X-MCB-TOKEN header
"""
import os, sys, json, subprocess, urllib.request, urllib.error, base64, tempfile

REPO_ROOT = "/mobilecybench"
UDS_SOCK = os.path.join(REPO_ROOT, "mcb.sock")
AGENT_PORT = os.environ.get("MCB_AGENT_PORT", "52888")
TCP_URL = f"http://host.docker.internal:{AGENT_PORT}"
UDS_URL = "http://localhost"
TOKEN_FILE = os.path.join(REPO_ROOT, "ssh_key")

def read_token():
    try:
        return open(TOKEN_FILE).read().strip()
    except:
        return ""

def shutil_which(name):
    from shutil import which
    return which(name)

def call_via_unix_raw(path, payload_json_str):
    # Use curl --unix-socket to POST JSON and return (stdout, stderr, rc)
    if not shutil_which("curl"):
        return "", "curl not found in container", 2
    try:
        cp = subprocess.run([
            "curl", "-sS", "--unix-socket", UDS_SOCK,
            "-H", "Content-Type: application/json",
            "-X", "POST",
            f"{UDS_URL}{path}", "-d", payload_json_str
        ], capture_output=True, text=True)
        return cp.stdout, cp.stderr, cp.returncode
    except Exception as e:
        return "", str(e), 2

def call_via_tcp_json(path, payload_bytes, token):
    req = urllib.request.Request(f"{TCP_URL}{path}", data=payload_bytes, headers={
        "Content-Type": "application/json",
        "X-MCB-TOKEN": token
    }, method="POST")
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
    # Reads local_path (container) and uploads to host via /push_file. Returns host_path on success.
    if not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)
    filename = os.path.basename(local_path)
    # read and base64 encode in memory (ok for typical APK sizes; if huge, switch to streaming multipart)
    with open(local_path, "rb") as f:
        data_b64 = base64.b64encode(f.read()).decode()
    payload = {"filename": filename, "data_b64": data_b64}
    payload_str = json.dumps(payload)

    # Try UDS first
    if os.path.exists(UDS_SOCK) and os.path.S_ISSOCK(os.stat(UDS_SOCK).st_mode):
        out, err, rc = call_via_unix_raw("/push_file", payload_str)
        if rc == 0 and out:
            try:
                obj = json.loads(out)
                return obj.get("path")
            except Exception:
                # try to parse non-json success
                return out.strip()
        # otherwise fall through to TCP
    # TCP path
    token = read_token()
    out, err, rc = call_via_tcp_json("/push_file", payload_str.encode(), token)
    if rc == 0 and out:
        try:
            obj = json.loads(out)
            return obj.get("path")
        except Exception:
            return out.strip()
    raise RuntimeError(f"upload failed: rc={rc} err={err} out={out}")

def call_adb(args):
    # For regular adb calls, call /adb with JSON {"args": [...], "token": ...}
    payload = {"args": args, "token": read_token()}
    payloadb = json.dumps(payload).encode()

    # UDS first
    if os.path.exists(UDS_SOCK) and os.path.S_ISSOCK(os.stat(UDS_SOCK).st_mode):
        out, err, rc = call_via_unix_raw("/adb", json.dumps(payload))
        if rc == 0:
            # we expect host returns JSON encoded stdout/stderr/exit_code; try to parse
            try:
                obj = json.loads(out)
                sys.stdout.write(obj.get("stdout",""))
                sys.stderr.write(obj.get("stderr",""))
                raise SystemExit(int(obj.get("exit_code",0) or 0))
            except Exception:
                # if host returned plain text, print and exit 0
                sys.stdout.write(out)
                raise SystemExit(0)
        else:
            # fall back to TCP below
            pass

    # TCP fallback
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{TCP_URL}/adb", data=payloadb, headers={
            "Content-Type": "application/json",
            "X-MCB-TOKEN": read_token()
        }, method="POST"), timeout=300) as resp:
            body = resp.read().decode()
            try:
                obj = json.loads(body)
                sys.stdout.write(obj.get("stdout",""))
                sys.stderr.write(obj.get("stderr",""))
                raise SystemExit(int(obj.get("exit_code",0) or 0))
            except Exception:
                sys.stdout.write(body)
                raise SystemExit(0)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
            ob = json.loads(body)
            sys.stdout.write(ob.get("stdout",""))
            sys.stderr.write(ob.get("stderr",""))
            raise SystemExit(int(ob.get("exit_code",1) or 1))
        except Exception:
            sys.stderr.write(f"HTTPError: {e}\n")
            raise SystemExit(1)
    except Exception as e:
        sys.stderr.write(f"Error contacting host agent: {e}\n")
        raise SystemExit(2)

def is_local_file_arg(arg):
    # treat absolute paths inside container as local files; relative paths could also be local
    return arg.startswith("/") or (arg and os.path.exists(arg))

def main():
    args = sys.argv[1:]
    if not args:
        # passthrough: 'adb' with no args: show help
        call_adb(args)
        return

    # detect install commands that include local file paths and upload them first
    # common patterns: adb install [-r] <apk>, adb install-multiple <apk1> <apk2>
    if "install" in args or any(a.startswith("install") for a in args):
        # find indexes of potential file arguments (non-switches)
        new_args = []
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("install", "install-multiple", "install-multi") or a.startswith("install"):
                new_args.append(a)
                i += 1
                continue
            # switches like -r, -d, -g have no file arg
            if a.startswith("-"):
                new_args.append(a)
                i += 1
                continue
            # treat this as a potential file path
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
                # leave untouched (could be remote path already)
                new_args.append(a)
                i += 1
                continue
        # call with replaced args
        call_adb(new_args)
        return

    # default: forward as-is
    call_adb(args)

if __name__ == "__main__":
    main()

PYSHIM

    chmod +x "${SHIM_PATH}"
    # ensure curl exists if we intend to use UDS (container images typically have curl)
    echo "[start_emulator_host] Attempting remote adb server start (proxied to host) ..."
    "${SHIM_PATH}" -a -P 5037 server start || true
    echo "[start_emulator_host] done (container will proxy adb calls to host agent)."
    exit 0
else
    echo "[start_emulator_host] ERROR: host agent returned HTTP ${HTTP_STATUS}"
    echo "[start_emulator_host] Response body:"
    echo "${HTTP_BODY}"
    exit 1
fi
