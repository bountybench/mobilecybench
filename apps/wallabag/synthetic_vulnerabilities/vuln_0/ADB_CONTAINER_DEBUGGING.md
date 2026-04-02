# ADB Container Connectivity Debugging

## Problem

The exploit container cannot reach the Android emulator via ADB on Windows. The symptom is:

```
WARNING: Container cannot see emulator via ADB.
adb: protocol fault (couldn't read status): Connection reset by peer
```

## The Connection Chain

```
exploit container (ADB client)
    ADB_SERVER_SOCKET=tcp:adb-proxy:5037
        ↓
    adb-proxy container (adb_filter_proxy.py, port 5037)
        ↓ connects to host.docker.internal:5037
    Windows host ADB server (adb.exe)
        ↓ TCP to emulator console port
    Android emulator (localhost:5554 / emulator-5554)
```

Every hop must work for `adb shell` commands to succeed from inside the exploit container.

## Known Failure Points

### 1. ADB server binds to 127.0.0.1 only (Windows-specific)

**Symptom:** Proxy container logs show it cannot connect to `host.docker.internal:5037`.

**Cause:** On Windows, `adb.exe` starts with `-L tcp:localhost:5037` by default, which binds to `127.0.0.1` only. Docker containers resolve `host.docker.internal` to the host's external IP on the Docker virtual adapter (e.g. `192.168.65.1`), which is a *different* interface. So even though the ADB server is running, containers can't reach it.

**Fix:** Kill the server and restart it bound to all interfaces:
```bash
adb kill-server
adb -a nodaemon server start &
```
The `-a` flag makes adb listen on `0.0.0.0:5037`.

**Verify:**
```bash
netstat -ano | grep ":5037"
# Should show: TCP  0.0.0.0:5037  0.0.0.0:0  LISTENING
# NOT:         TCP  127.0.0.1:5037 ...
```

### 2. host.docker.internal resolves to IPv6 on Windows Docker Desktop (ROOT CAUSE CONFIRMED)

**Symptom:**
```
[ADB-DIAG] PROXY: host.docker.internal resolves to:
fdc4:f303:9324::254 host.docker.internal   ← IPv6!
[ADB-DIAG] EXPLOIT: adb devices output:
adb: failed to check server version: protocol fault (couldn't read status): Connection reset by peer
```

**Cause:** On Windows Docker Desktop, `host.docker.internal` sometimes resolves to an IPv6 address. Python's `socket.create_connection()` picks IPv6 first. But the ADB server only binds to `0.0.0.0:5037` (IPv4). The IPv6 connection is refused, which causes the proxy to reset the client connection — producing "Connection reset by peer" in the exploit container.

**Fix (applied in `run_exploit_container.sh`):** Resolve the IPv4 address explicitly using `getent ahostsv4` and pass it as the upstream host argument to the proxy:
```bash
HOST_GW_IPV4=$(docker exec adb-proxy getent ahostsv4 host.docker.internal | awk 'NR==1{print $1}')
docker exec -d adb-proxy python3 /opt/adb_filter_proxy.py 5037 "$HOST_GW_IPV4" 5037
```

**Verify:** After this fix, `adb devices` from the exploit container should show the emulator.

### 3. Windows Firewall blocks shared_net gateway → host port 5037 (CONFIRMED ROOT CAUSE)

**Symptom:**
```
[ADB-DIAG] PROXY: TCP connect to 192.168.65.254:5037 FAILED: [Errno 111] Connection refused
```
(or a timeout)

**Cause:** `192.168.65.254` (Docker Desktop management subnet) is **not routable** from `shared_net` (`172.19.0.0/16`). The correct host IP from within `shared_net` is `172.19.0.1` (the bridge gateway). TCP connections to `172.19.0.1:5037` return "Connection refused" because Windows Firewall blocks inbound connections from the Docker bridge subnet to port 5037.

**Confirmed by:**
```
172.19.0.1:5037  FAILED: [Errno 111] Connection refused   ← path exists, firewall blocks
192.168.65.254:5037  FAILED: [Errno 101] Network is unreachable  ← wrong subnet entirely
```

**Fix (run once as Administrator in PowerShell):**
```powershell
New-NetFirewallRule -DisplayName "ADB for Docker (shared_net)" -Direction Inbound -Protocol TCP -LocalPort 5037 -Action Allow -RemoteAddress 172.19.0.0/16
```

Note: `172.19.0.0/16` is the `shared_net` subnet used by MobileCyBench. If `shared_net` is recreated with a different subnet, update this rule accordingly.

**Verify:**
```
[ADB-DIAG] PROXY: TCP connect to 192.168.65.254:5037 SUCCEEDED
```

### 4. Windows Firewall blocks Docker → host port 5037 (old heading)

**Symptom:** ADB server is on `0.0.0.0:5037`, proxy container can resolve `host.docker.internal`, but `nc -zv host.docker.internal 5037` from the proxy container fails.

**Cause:** Windows Defender Firewall has an inbound rule blocking connections to port 5037 from Docker's virtual network adapter (`vEthernet (DockerDesktop)` or similar).

**Fix:** Add a Windows Firewall inbound rule allowing TCP 5037 from the Docker subnet:
```powershell
# Run as Administrator in PowerShell
New-NetFirewallRule -DisplayName "ADB for Docker" -Direction Inbound -Protocol TCP -LocalPort 5037 -Action Allow
```
Or temporarily disable the firewall for testing:
```powershell
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
```

**Verify from proxy container:**
```bash
docker exec adb-proxy nc -zv host.docker.internal 5037
# Should show: Connection to host.docker.internal 5037 port [tcp/*] succeeded!
```

### 3. Proxy process dies before exploit container connects

**Symptom:** `adb-proxy` container is running but `nc -zv adb-proxy 5037` from exploit container fails.

**Cause:** `adb_filter_proxy.py` crashes on startup (e.g. import error, bind failure).

**Verify:**
```bash
docker logs adb-proxy
# Should show: [PROXY] ADB filter proxy on :5037 -> host.docker.internal:5037
```

### 4. ADB server drops emulator connection after restart

**Symptom:** `adb devices` from host shows no devices after restarting the ADB server.

**Cause:** `adb kill-server` terminates the connection to the emulator. The emulator reconnects automatically, but it may take a few seconds.

**Fix:** After restarting, wait and reconnect:
```bash
adb kill-server
adb -a nodaemon server start &
sleep 3
adb devices   # emulator should reconnect on its own
```

## Diagnostic Logs Added to run_exploit_container.sh

The following `[ADB-DIAG]` log blocks were added to `utils/run_exploit_container.sh`:

### Block 1: Before proxy start (host-side)
```
=== [ADB-DIAG] HOST: ADB server binding check ===
[ADB-DIAG] HOST: adb devices output: ...
[ADB-DIAG] HOST: ADB only on 127.0.0.1 — restarting on 0.0.0.0...   (if needed)
[ADB-DIAG] HOST: ADB binding after restart: ...
```
**What to look for:** `TCP  0.0.0.0:5037` in the netstat output.

### Block 2: After proxy start (proxy-side)
```
=== [ADB-DIAG] PROXY CONTAINER: network connectivity ===
[ADB-DIAG] PROXY: Can proxy reach host.docker.internal:5037?
[ADB-DIAG] PROXY: host.docker.internal resolves to: ...
```
**What to look for:** `succeeded!` on the nc check. If it fails, the issue is firewall or ADB binding.

### Block 3: After exploit container starts (exploit-side)
```
=== [ADB-DIAG] EXPLOIT CONTAINER: ADB chain ===
[ADB-DIAG] EXPLOIT: ADB_SERVER_SOCKET=tcp:adb-proxy:5037
[ADB-DIAG] EXPLOIT: Can exploit container reach proxy port 5037?
[ADB-DIAG] EXPLOIT: adb devices output: ...
```
**What to look for:**
- `nc` to proxy succeeds → proxy is reachable
- `adb devices` shows the emulator → full chain works
- `adb devices` shows empty → proxy can't reach host ADB (firewall)
- `Connection reset by peer` → proxy is reached but drops the connection (host ADB unreachable)

## Decision Tree

```
Connection reset by peer on adb commands?
    ↓
Is adb-proxy:5037 reachable from exploit container?
    NO → proxy died → check `docker logs adb-proxy`
    YES ↓
Is host.docker.internal:5037 reachable from proxy?
    NO → Windows Firewall blocking → add firewall rule
    YES ↓
Is ADB server on 0.0.0.0 (not 127.0.0.1)?
    NO → restart with `adb -a nodaemon server start`
    YES ↓
Does `adb devices` show the emulator from the host?
    NO → emulator not running or ADB not connected
    YES → unknown issue, check adb_filter_proxy.py logs
```

## Changes Attempted on `utils/run_exploit_container.sh`

These are all the changes we tried in the debugging session. They have been reverted via `git restore utils/` — documented here for reference.

### Attempt 1: Rebind ADB server to 0.0.0.0

**What:** Added a block that checks if ADB is bound to `127.0.0.1:5037` and, if so, kills it and restarts with `adb -a nodaemon server start &` to bind to `0.0.0.0:5037`.

**Result:** ADB correctly rebinds to `0.0.0.0:5037` on the Windows host (verified with `netstat`). However, containers on `shared_net` still cannot reach it. The port is open on the *Windows* host, but containers route through the Docker Desktop Linux VM.

### Attempt 2: Resolve IPv4 for host.docker.internal

**What:** Inside the proxy container, used `getent ahostsv4 host.docker.internal` to resolve the IPv4 address explicitly, avoiding the IPv6 preference issue. Got `192.168.65.254`.

**Result:** `192.168.65.254` is on the Docker Desktop management subnet, which is **not routable** from `shared_net` (`172.19.0.0/16`). Error: "Network is unreachable".

### Attempt 3: Use shared_net bridge gateway IP

**What:** Used `docker network inspect shared_net` to get the bridge gateway IP (`172.19.0.1`), then pointed the proxy at `172.19.0.1:5037` instead of `host.docker.internal:5037`.

**Result:** "Connection refused". `172.19.0.1` is the gateway **inside the Docker Desktop Linux VM**, not the Windows host. Nothing listens on port 5037 at that address.

### Attempt 4: Host-side proxy on port 15037

**What:** Moved the ADB filter proxy out of a container and ran it directly on the Windows host as `python3 adb_filter_proxy.py 15037 127.0.0.1 5037`, binding to `0.0.0.0:15037`. Then pointed exploit container at `${SHARED_NET_GW}:15037` (i.e., `172.19.0.1:15037`).

**Result:** Still "Connection refused". Same root cause — `172.19.0.1` is inside the Linux VM, so the host-side proxy on Windows `0.0.0.0:15037` is unreachable from there.

### Attempt 5: Added `--add-host=host.docker.internal:host-gateway` to exploit container

**What:** Added the `--add-host` flag to the `docker run` command for the exploit container, hoping `host.docker.internal` would resolve to a routable Windows host IP.

**Result:** On custom bridge networks, `host-gateway` resolves to the Linux VM's gateway, not the Windows host. Same dead end.

### Attempt 6: Extensive `[ADB-DIAG]` diagnostics

**What:** Added diagnostic blocks throughout the script:
- `[ADB-DIAG] HOST:` — checks ADB server binding, runs `adb devices`, checks port 5037 with `netstat`
- `[ADB-DIAG] CONNECTIVITY TEST:` — runs a temp container to test TCP connectivity to host proxy
- `[ADB-DIAG] EXPLOIT:` — tests proxy reachability and `adb devices` from inside the exploit container
- Also added `su` disable via bind mount (`mount --bind /data/local/tmp/.fake_su /system/xbin/su`)

**Result:** The diagnostics confirmed the root cause (see below) but did not fix anything.

## Root Cause (Final)

**On Windows Docker Desktop, containers on custom bridge networks (`shared_net`) fundamentally cannot reach ANY port on the Windows host.**

The networking topology is:

```
Windows host (adb.exe on 0.0.0.0:5037)
    ↑ cannot be reached from shared_net
    |
Docker Desktop Linux VM
    ├── 172.19.0.1  (shared_net gateway — inside the VM, not Windows)
    ├── 172.19.0.x  (containers on shared_net)
    └── 192.168.65.254  (management subnet — not routable from shared_net)
```

- `172.19.0.1` is the bridge gateway **inside the Linux VM**. Nothing from Windows binds there.
- `192.168.65.254` (`host.docker.internal`) is on the management subnet, which is **not routable** from custom bridge networks.
- `--add-host=host.docker.internal:host-gateway` maps to the VM's gateway, not the Windows host.
- Docker Desktop's port publishing (`-p`) only works for **inbound** traffic (host → container), not for container → host.

The only reliable way for a container on a custom bridge network to reach the Windows host is Docker Desktop's built-in `host.docker.internal` resolution — but that only works on the **default bridge** network, not custom ones like `shared_net`.

## Possible Solutions (Not Yet Tried)

1. **Run exploit container on default bridge + shared_net**: Use `--network bridge --network shared_net` so `host.docker.internal` is routable while still being able to reach other containers on `shared_net`.

2. **Run ADB proxy container with `--network host`**: A container in host network mode can reach `127.0.0.1:5037` directly. Other containers on `shared_net` can reach it via the container's name if it's also connected to `shared_net` (dual-network).

3. **Docker Desktop port forwarding trick**: Publish the host ADB port into a sidecar container using `-p 5037:5037`, then have the proxy container connect to the sidecar. This uses Docker's built-in NAT which does work cross-network.

4. **Move ADB commands out of exploit container**: Have `prepare_app.sh` (which runs on the host) handle all ADB operations (start app, clear cache), and have `exploit.sh` only run the token capture server. This avoids the ADB-from-container problem entirely but changes the exploit architecture.

5. **Use `extra_hosts` in docker-compose**: For containers launched via docker-compose, the `extra_hosts` directive with `host-gateway` may work differently than the CLI `--add-host` flag.

6. **Windows Firewall rule + correct IP**: If we can find the correct IP that containers see for the Windows host (not the VM gateway), add a firewall rule for that IP on port 5037.

## Linux vs Windows

On **Linux**, this is a non-issue: ADB binds to `0.0.0.0` by default, and Docker's host network mode or `--add-host=host.docker.internal:host-gateway` works without firewall complications. `host.docker.internal` resolves to a real host IP that containers can reach.

On **Windows with Docker Desktop**, the virtual network adapter creates a NAT boundary through a Linux VM. Inbound connections to host ports from containers require either:
- The host process binding to `0.0.0.0` (not `127.0.0.1`)
- Windows Firewall allowing the inbound connection from the Docker subnet
- **AND** a routable path from the container's network to the Windows host — which does not exist for custom bridge networks
