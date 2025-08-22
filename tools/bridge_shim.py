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
                new_args.append(a)
                i += 1
                continue
        call_adb(new_args)
        return
    call_adb(args)

if __name__ == "__main__":
    main()