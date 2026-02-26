# Upgrading an App from HTTP to HTTPS

This guide walks you through upgrading a MobileCybench app from plain HTTP to HTTPS using the shared TLS proxy infrastructure.

## Background

Our benchmark used plain HTTP, making exploits unrealistically easy — an agent could set up a MITM proxy between the emulator and backend to intercept all traffic. With HTTPS, intercepting traffic requires installing a custom CA into the emulator's system trust store, which requires root access the agent doesn't have.

The infrastructure is already in place:
- A shared CA certificate and server cert live in `tls/`
- The CA is automatically injected into the emulator's system trust store before app setup
- A reusable nginx TLS proxy template handles termination

**You only need to modify your app's files.** No changes to shared infra are needed.

## Architecture

```
Android App (in emulator)
    |
    | HTTPS request to https://10.0.2.2:<PORT>
    v
Host port <PORT> --> nginx container (TLS termination, port 443)
    |
    | HTTP (plain) via Docker internal network
    v
Backend container (unchanged, still serves HTTP)
```

The nginx proxy terminates TLS and forwards plain HTTP to your backend. Your backend code doesn't change at all.

## Step-by-Step

### 1. Add the `tls_proxy` service to `docker-compose.yml`

Add this service **before** your backend service:

```yaml
tls_proxy:
  image: nginx:alpine
  container_name: <appname>_tls_proxy
  restart: always
  ports:
    - <HOST_PORT>:443          # same port the app was using before
  volumes:
    - ../../tls/server.crt:/etc/nginx/certs/server.crt:ro
    - ../../tls/server.key:/etc/nginx/certs/server.key:ro
    - ../../tls/nginx-tls-proxy.conf.template:/etc/nginx/templates/default.conf.template:ro
  environment:
    - UPSTREAM=<backend_container>:<backend_internal_port>
    - NGINX_ENVSUBST_FILTER=UPSTREAM
  depends_on:
    <backend_service>:
      condition: service_healthy
  networks:
    - shared_net
    - private_net
  healthcheck:
    test: ["CMD", "curl", "-fsk", "https://localhost"]
    interval: 10s
    timeout: 5s
    retries: 5
```

**Key variables to fill in:**
- `<appname>`: your app name (e.g., `simplelogin`)
- `<HOST_PORT>`: the port the emulator currently connects to (keep it the same so the app config doesn't break)
- `<backend_container>:<backend_internal_port>`: where nginx forwards to internally (e.g., `simplelogin-api:7777`)
- `<backend_service>`: the docker-compose service name of your backend

### 2. Remove `ports` and `shared_net` from the backend service

Your backend no longer needs to be directly reachable from the host. The TLS proxy handles that.

**Before:**
```yaml
my-backend:
  ports:
    - "7777:7777"
  networks:
    - private_net
    - shared_net
```

**After:**
```yaml
my-backend:
  networks:
    - private_net
```

This is important: the backend should only be on `private_net`. If it stays on `shared_net` with published ports, the emulator could bypass TLS entirely.

### 3. Update `metadata.json`

Change the protocol from `http` to `https` in `emulator_server`, and point `app_server` to the TLS proxy container:

**Before:**
```json
{
  "emulator_server": "http://10.0.2.2:7777",
  "app_server": "simplelogin-api:7777"
}
```

**After:**
```json
{
  "emulator_server": "https://10.0.2.2:7777",
  "app_server": "simplelogin_tls_proxy:443"
}
```

- `emulator_server`: what the Android app uses — change `http://` to `https://`, keep the same port
- `app_server`: what CI connectivity checks use via `shared_net` — point to the nginx container on port 443

### 4. Update `start_runtime.sh`

Change the `wait_healthy` target from the backend container to the TLS proxy:

**Before:**
```bash
wait_healthy "simplelogin-api" 180 || fatal "simplelogin-api did not become healthy"
```

**After:**
```bash
wait_healthy "simplelogin_tls_proxy" 180 || fatal "simplelogin_tls_proxy did not become healthy"
```

If your `start_runtime.sh` or setup scripts make HTTP calls to the backend (e.g., seeding data via `curl` or Python `requests`), you have two options:
1. **Talk to the backend directly** via `docker exec` (no TLS needed)
2. **Talk through the proxy** by trusting the CA:
   ```bash
   export REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem"
   ```

### 5. Update all hardcoded `http://` URLs

Search your app directory for any remaining `http://` references to the backend. Common places:
- **Test files** (`test_*.py`): change default URLs from `http://` to `https://`
- **`.env` files**: update server URLs
- **Vuln files** (`vulnerability.patch`, `vuln.sh`): update `target_server` and default URLs
- **Setup scripts** (`*_setup.py`, `seed_data.py`): update default URLs

For Python scripts using `requests`, set `REQUESTS_CA_BUNDLE` to trust the local CA:
```bash
# In .env
REQUESTS_CA_BUNDLE=../../tls/rootCA.pem
```

## FAQ

**Q: Do I need to modify the backend application code?**
No. The nginx proxy handles TLS termination. Your backend still serves plain HTTP internally — only the path from the emulator to nginx is encrypted.

**Q: Do I need to generate new certificates?**
No. The shared certs in `tls/` cover all the SANs we need (`10.0.2.2`, `localhost`, `127.0.0.1`, `host.docker.internal`). They're valid for 100 years.

**Q: Do I need to inject the CA certificate into the emulator?**
No. This happens automatically. The orchestrator calls `utils/inject_system_ca.sh` after emulator boot, before your `start_runtime.sh` runs. CI workflows also inject it.

**Q: What if my backend listens on a non-standard port?**
Set `UPSTREAM` to `<container_name>:<internal_port>`. The TLS proxy always listens on 443 internally, but you map whatever host port you want (e.g., `7777:443` for simplelogin).

**Q: What about `REQUESTS_CA_BUNDLE` — when do I need it?**
Only if your host-side Python scripts (setup, tests, seeding) make HTTPS requests to the backend through the proxy. Set it in `.env` or `start_runtime.sh`:
```bash
export REQUESTS_CA_BUNDLE="$SCRIPT_DIR/../../tls/rootCA.pem"
```
If your scripts talk to the backend via `docker exec` (SQL, CLI commands), you don't need it.

**Q: How do I test locally?**
```bash
# Start your backend
cd apps/<yourapp>
docker compose up -d

# Verify all containers are healthy
docker compose ps

# Test TLS from host
curl -v --cacert ../../tls/rootCA.pem https://localhost:<PORT>/

# Or skip cert verification
curl -vk https://localhost:<PORT>/
```

## App Upgrade Status

### Simple drop-in (use the template as-is)

These apps have a single HTTP backend port and no existing reverse proxy — follow the steps above directly.

| App | Current `emulator_server` |
|-----|--------------------------|
| grocy | `http://10.0.2.2:8080` |
| audiobookshelf | `http://10.0.2.2:13378` |
| joplin | `http://10.0.2.2:22300` |
| moememos | `http://10.0.2.2:5230` |
| miniflutt | `http://10.0.2.2:8080` |
| jerboa | `http://10.0.2.2:8536` |
| ntfy-android | `http://10.0.2.2:8080` |
| gotify | `http://10.0.2.2:8080` |
| davx5 | `http://10.0.2.2:5232/` |
| wordpress | `http://10.0.2.2:8000` |
| tindroid | `http://10.0.2.2:6060` |
| bitwarden | `http://10.0.2.2:8000` |
| nextcloud-talk | `10.0.2.2:8080` |
| wallabag | `10.0.2.2:8080` |

### Needs custom work

| App | Why |
|-----|-----|
| jellyfin | Multiple ports including UDP (DLNA discovery) |
| home-assistant-android | Complex multi-network setup (SSRF listener on separate network) |
| openhab | Multiple ports + Mosquitto MQTT sidecar |
| conversations | XMPP protocol (port 5222), not HTTP |
| owntracks | MQTT protocol (`tcp://10.0.2.2:1883`), not HTTP |
| openvpn | VPN binary protocol (port 1194), not HTTP |
| linphone | SIP/RTP protocol (port 5060), not HTTP |
| thunderbird | IMAP/SMTP protocols (ports 993, 465), not HTTP |
| deltachat-android | SMTP protocol (port 1025), not HTTP |

### Already upgraded

| App | Notes |
|-----|-------|
| owncloud-android | PR #723, uses shared TLS proxy template |
| simplelogin | PR #730, uses shared TLS proxy template |
| ankidroid | No containerized backend (`app_server` is empty) |
| termux | No backend |
| funkwhale | Has its own nginx, but we should standardize |
| moodle | Has its own nginx, but we should standardize |
