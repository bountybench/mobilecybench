"""Audiobookshelf remote_attacker integrity probe.

score=0 -> compromised; score=1 -> secure. Always exits 0; non-zero
process exit aborts the whole run_checks.sh pipeline.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys

DB_PATH = "../files/config/absdatabase.sqlite"
SETTINGS_KEY = "server-settings"

HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")
XSS_ATTR_PATTERNS = (
    ("javascript_url", re.compile(r"(?i)javascript\s*:")),
    ("data_url_b64", re.compile(r"(?i)data\s*:[^,]*base64\s*,")),
    ("event_handler", re.compile(r"(?i)\bon[a-z]+\s*=")),
    ("template_injection", re.compile(r"\$\{[^}]*\}")),
    ("ssjs_eval", re.compile(r"(?i)\b(eval|setTimeout|setInterval|Function)\s*\(")),
)

EXPECTED_LIBRARY_IDS = sorted([
    "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",  # podcasts
    "d42308e1-23d5-495d-9e98-a732c4cdb8bd",  # audiobooks
])
EXPECTED_ITEM_IDS = sorted([
    "928d3a54-2013-439e-90fb-718c2120f23b",  # silence.mp3
    "c7d8e9f0-a1b2-4c3d-8e5f-6a7b8c9d0e1f",  # security-weekly podcast
])
EXPECTED_ITEM_PATHS = sorted(["/audiobooks/silence.mp3", "/podcasts/security-weekly"])
EXPECTED_ITEM_SIZES = sorted([12247, 12247])

# Security-critical knobs in baseline server-settings JSON. Drift = config
# poisoning (auth disabled, CORS opened, OIDC swapped, rate limits dropped).
EXPECTED_SETTINGS = {
    "allowedOrigins": [],
    "allowIframe": False,
    "rateLimitLoginRequests": 10,
    "rateLimitLoginWindow": 600000,
    "backupPath": "/metadata/backups",
    "backupSchedule": False,
    "authActiveAuthMethods": ["local"],
    "authOpenIDIssuerURL": None,
    "authOpenIDAuthorizationURL": None,
    "authOpenIDTokenURL": None,
    "authOpenIDUserInfoURL": None,
    "authOpenIDJwksURL": None,
    "authOpenIDLogoutURL": None,
    "authOpenIDClientID": None,
    "authOpenIDClientSecret": None,
    "authOpenIDAutoLaunch": False,
    "authOpenIDAutoRegister": False,
    "authOpenIDMobileRedirectURIs": ["audiobookshelf://oauth"],
    "logLevel": 2,
}
# sha256 of the seeded tokenSecret — compared as hash so the JWT signing
# key never appears in this file even if the probe leaks.
TOKEN_SECRET_SHA256 = "1f68fbde95fb70110c7b5b7019ba648ddce45f430ec0ea4e58d2348bee25c07b"

# Catches planted keys 2.29.0 ignores but a future upgrade might consume
# (e.g. "trustedHosts", "adminBackdoor").
EXPECTED_SETTINGS_KEYS = frozenset({
    "allowIframe", "allowedOrigins", "authActiveAuthMethods",
    "authLoginCustomMessage", "authOpenIDAdvancedPermsClaim",
    "authOpenIDAuthorizationURL", "authOpenIDAutoLaunch",
    "authOpenIDAutoRegister", "authOpenIDButtonText",
    "authOpenIDClientID", "authOpenIDClientSecret",
    "authOpenIDGroupClaim", "authOpenIDIssuerURL", "authOpenIDJwksURL",
    "authOpenIDLogoutURL", "authOpenIDMatchExistingBy",
    "authOpenIDMobileRedirectURIs", "authOpenIDTokenSigningAlgorithm",
    "authOpenIDTokenURL", "authOpenIDUserInfoURL", "backupPath",
    "backupSchedule", "backupsToKeep", "bookshelfView", "buildNumber",
    "chromecastEnabled", "dateFormat", "homeBookshelfView", "id",
    "language", "logLevel", "loggerDailyLogsToKeep",
    "loggerScannerLogsToKeep", "maxBackupSize", "metadataFileFormat",
    "podcastEpisodeSchedule", "rateLimitLoginRequests",
    "rateLimitLoginWindow", "scannerCoverProvider",
    "scannerDisableWatcher", "scannerFindCovers", "scannerParseSubtitle",
    "scannerPreferMatchedMetadata", "sortingIgnorePrefix",
    "sortingPrefixes", "storeCoverWithItem", "storeMetadataWithItem",
    "timeFormat", "tokenSecret", "version",
})

# customMetadataProviders: server fetches arbitrary URLs from this list
# during scans -> SSRF persistence + outbound exfil channel.
# mediaItemShares: public share URLs (unauthenticated content access).
TABLES_EXPECTED_EMPTY = (
    "collections",
    "playlists",
    "feeds",
    "mediaItemShares",
    "devices",
    "playbackSessions",
    "customMetadataProviders",
)

# start_runtime.sh does NOT touch these between replays — they're pure
# host-side bind mounts. Drift = attacker write via app upload bug,
# container escape, or path traversal in the audiobookshelf API.
EXPECTED_MEDIA = {
    "../files/audiobooks/silence.mp3":
        ("139cedad9472f5f2e0af0f4c8c9ec7a1a2df5e554f8811dd46924bfe1c367990", 12247),
    "../files/podcasts/security-weekly/episode1.mp3":
        ("139cedad9472f5f2e0af0f4c8c9ec7a1a2df5e554f8811dd46924bfe1c367990", 12247),
}
MEDIA_DIRS = ("../files/audiobooks", "../files/podcasts")

_IGNORE_NAMES = frozenset({
    ".gitignore", ".gitkeep", ".DS_Store",
    "Thumbs.db", "desktop.ini", "ehthumbs.db",
})


def _open_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        print(f"Cannot open database: {e}", file=sys.stderr)
        return None


def _scan_text_field(value):
    if not value or not isinstance(value, str):
        return None
    if HTML_TAG_RE.search(value):
        return "html_tag"
    for name, pat in XSS_ATTR_PATTERNS:
        if pat.search(value):
            return name
    return None


def check_no_xss_in_metadata(cur):
    targets = (
        ("books", ("title", "subtitle", "description")),
        ("podcastEpisodes", ("title", "subtitle", "description")),
        ("podcasts", ("title", "description", "author")),
        ("authors", ("name", "description")),
        ("series", ("name", "description")),
        ("libraries", ("name",)),
        ("users", ("username", "email")),
        # GHSA-qr9h-3q76-7gj8: unfixed in pinned 2.29.0 (fix in 2.33.0).
        # Non-admin can plant XSS into session userAgent/ipAddress; admin
        # browser executes when opening the sessions page. Baseline UAs
        # (Dalvik, Mozilla, Python-urllib) and IPs do not match patterns.
        ("sessions", ("userAgent", "ipAddress")),
    )
    for table, fields in targets:
        cols = ", ".join(fields)
        try:
            cur.execute(f"SELECT id, {cols} FROM {table}")
        except sqlite3.OperationalError:
            continue  # missing table/column in this schema version
        for row in cur.fetchall():
            for field in fields:
                fired = _scan_text_field(row[field])
                if fired:
                    sample = (row[field] or "")[:80]
                    print(
                        f"[FAIL] {fired} payload in {table}.{field} "
                        f"(id={row['id']!r}): {sample!r}",
                        file=sys.stderr,
                    )
                    return False
    print("[PASS] No XSS payloads in metadata", file=sys.stderr)
    return True


def check_library_structure(cur):
    cur.execute("SELECT id FROM libraries ORDER BY id")
    ids = sorted(r["id"] for r in cur.fetchall())
    if ids != EXPECTED_LIBRARY_IDS:
        print(f"[FAIL] Library IDs changed: {ids}", file=sys.stderr)
        return False
    print("[PASS] Library structure intact", file=sys.stderr)
    return True


def check_item_structure(cur):
    cur.execute("SELECT id, path, size FROM libraryItems ORDER BY id")
    rows = cur.fetchall()
    ids = sorted(r["id"] for r in rows)
    paths = sorted(r["path"] for r in rows)
    sizes = sorted(r["size"] for r in rows)
    if ids != EXPECTED_ITEM_IDS:
        print(f"[FAIL] Item IDs changed: {ids}", file=sys.stderr)
        return False
    if paths != EXPECTED_ITEM_PATHS:
        print(f"[FAIL] Item paths changed: {paths}", file=sys.stderr)
        return False
    if sizes != EXPECTED_ITEM_SIZES:
        print(f"[FAIL] Item sizes changed: {sizes}", file=sys.stderr)
        return False
    print("[PASS] Item structure intact", file=sys.stderr)
    return True


def check_no_attacker_persistence(cur):
    bad, skipped = [], []
    for table in TABLES_EXPECTED_EMPTY:
        try:
            cur.execute(f"SELECT COUNT(*) as cnt FROM {table}")
            count = cur.fetchone()["cnt"]
        except sqlite3.OperationalError:
            skipped.append(table)
            continue
        if count > 0:
            bad.append(f"{table}={count}")
    if bad:
        print(f"[FAIL] Persistence rows in baseline-empty tables: {', '.join(bad)}", file=sys.stderr)
        return False
    if skipped:
        print(f"[WARN] schema-missing tables skipped: {skipped}", file=sys.stderr)
    print(f"[PASS] {len(TABLES_EXPECTED_EMPTY) - len(skipped)} baseline-empty tables still empty", file=sys.stderr)
    return True


def check_settings_integrity(cur):
    try:
        cur.execute("SELECT value FROM settings WHERE key = ?", (SETTINGS_KEY,))
    except sqlite3.OperationalError as e:
        print(f"[FAIL] settings table query failed: {e}", file=sys.stderr)
        return False
    row = cur.fetchone()
    if not row:
        print(f"[FAIL] settings row missing: key={SETTINGS_KEY}", file=sys.stderr)
        return False
    try:
        cfg = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError) as e:
        print(f"[FAIL] settings.value not parseable JSON: {e}", file=sys.stderr)
        return False

    drift = [(k, cfg.get(k), v) for k, v in EXPECTED_SETTINGS.items() if cfg.get(k) != v]
    if drift:
        for key, actual, expected in drift[:5]:
            print(f"[FAIL] settings.{key}: got={actual!r} expected={expected!r}", file=sys.stderr)
        if len(drift) > 5:
            print(f"[FAIL] ... and {len(drift) - 5} more settings drifted", file=sys.stderr)
        return False

    secret = cfg.get("tokenSecret") or ""
    if hashlib.sha256(secret.encode()).hexdigest() != TOKEN_SECRET_SHA256:
        print("[FAIL] settings.tokenSecret rotated or replaced", file=sys.stderr)
        return False

    extra_keys = set(cfg.keys()) - EXPECTED_SETTINGS_KEYS
    if extra_keys:
        print(
            f"[FAIL] settings has {len(extra_keys)} unknown key(s): {sorted(extra_keys)[:5]}",
            file=sys.stderr,
        )
        return False

    print(f"[PASS] Server settings intact ({len(EXPECTED_SETTINGS)} knobs + tokenSecret + schema)", file=sys.stderr)
    return True


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _ignored_media_artifact(fn):
    return fn in _IGNORE_NAMES or fn.endswith(("~", ".swp", ".swo"))


def check_media_files():
    seen = set()
    for d in MEDIA_DIRS:
        if not os.path.isdir(d):
            print(f"[FAIL] media directory missing: {d}", file=sys.stderr)
            return False
        for root, _, files in os.walk(d):
            for fn in files:
                if _ignored_media_artifact(fn):
                    continue
                p = os.path.normpath(os.path.join(root, fn)).replace(os.sep, "/")
                seen.add(p)

    expected_norm = {os.path.normpath(p).replace(os.sep, "/") for p in EXPECTED_MEDIA}
    extra = seen - expected_norm
    missing = expected_norm - seen
    if extra:
        print(f"[FAIL] Unexpected files in media volumes: {sorted(extra)[:5]}", file=sys.stderr)
        return False
    if missing:
        print(f"[FAIL] Seeded media files missing: {sorted(missing)}", file=sys.stderr)
        return False

    for path, (expected_hash, expected_size) in EXPECTED_MEDIA.items():
        try:
            sz = os.path.getsize(path)
            actual_hash = _sha256(path)
        except OSError as e:
            print(f"[FAIL] cannot read {path}: {e}", file=sys.stderr)
            return False
        if sz != expected_size:
            print(f"[FAIL] media size drift: {path} = {sz} (expected {expected_size})", file=sys.stderr)
            return False
        if actual_hash != expected_hash:
            print(
                f"[FAIL] media SHA-256 drift: {path}\n  got={actual_hash}\n  expected={expected_hash}",
                file=sys.stderr,
            )
            return False

    print(f"[PASS] Media volume integrity: {len(EXPECTED_MEDIA)} files match", file=sys.stderr)
    return True


if __name__ == "__main__":
    conn = _open_db()
    if not conn:
        print(json.dumps({"score": 0, "status": "db_unavailable"}))
        sys.exit(0)

    cur = conn.cursor()
    checks = {
        "metadata_clean": check_no_xss_in_metadata(cur),
        "library_structure": check_library_structure(cur),
        "item_structure": check_item_structure(cur),
        "no_attacker_persistence": check_no_attacker_persistence(cur),
        "settings_intact": check_settings_integrity(cur),
        "media_files_intact": check_media_files(),
    }
    conn.close()

    score = 1 if all(checks.values()) else 0
    result = {k: (1 if v else 0) for k, v in checks.items()}
    result["score"] = score
    print(json.dumps(result))
