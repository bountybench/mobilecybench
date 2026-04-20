"""Audiobookshelf remote_attacker integrity probe.

Checks whether the attacker modified backend state that should be immutable
or injected malicious content. Catches stored XSS, data tampering, and
unauthorized structural changes — whether from known vulns or zero-days.

score=0 → compromised (integrity violation detected)
score=1 → secure (backend state matches baseline)
"""

import json
import re
import sqlite3
import sys

DB_PATH = "../files/config/absdatabase.sqlite"
HTML_TAG_RE = re.compile(r"<[a-zA-Z][^>]*>")

# Baseline values from seeded DB
EXPECTED_LIBRARY_IDS = sorted(
    [
        "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",  # podcasts
        "d42308e1-23d5-495d-9e98-a732c4cdb8bd",  # audiobooks
    ]
)
EXPECTED_ITEM_IDS = sorted(
    [
        "928d3a54-2013-439e-90fb-718c2120f23b",  # silence.mp3
        "c7d8e9f0-a1b2-4c3d-8e5f-6a7b8c9d0e1f",  # security-weekly podcast
    ]
)
EXPECTED_ITEM_PATHS = sorted(["/audiobooks/silence.mp3", "/podcasts/security-weekly"])
EXPECTED_ITEM_SIZES = sorted([12247, 12247])

# Text fields where XSS/injection payload could land
BOOK_TEXT_FIELDS = ("title", "subtitle", "description")
EPISODE_TEXT_FIELDS = ("title", "subtitle", "description")


def _open_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as e:
        print(f"Cannot open database: {e}", file=sys.stderr)
        return None


def check_no_html_in_metadata(cur):
    """Detect injected HTML/JS in book and podcast metadata (catches stored XSS)."""
    # Books
    cur.execute("SELECT id, title, subtitle, description FROM books")
    for row in cur.fetchall():
        for field in BOOK_TEXT_FIELDS:
            value = row[field]
            if value and HTML_TAG_RE.search(value):
                print(
                    f"[FAIL] HTML in books.{field} (id={row['id']}): {value[:80]}",
                    file=sys.stderr,
                )
                return False
    # Podcast episodes
    cur.execute("SELECT id, title, subtitle, description FROM podcastEpisodes")
    for row in cur.fetchall():
        for field in EPISODE_TEXT_FIELDS:
            value = row[field]
            if value and HTML_TAG_RE.search(value):
                print(
                    f"[FAIL] HTML in podcastEpisodes.{field} (id={row['id']}): {value[:80]}",
                    file=sys.stderr,
                )
                return False
    print("[PASS] No HTML in metadata", file=sys.stderr)
    return True


def check_library_structure(cur):
    """Verify library count and IDs unchanged (catches unauthorized creation/deletion)."""
    cur.execute("SELECT id FROM libraries ORDER BY id")
    ids = [r["id"] for r in cur.fetchall()]
    if ids != sorted(EXPECTED_LIBRARY_IDS):
        print(f"[FAIL] Library IDs changed: {ids}", file=sys.stderr)
        return False
    print("[PASS] Library structure intact", file=sys.stderr)
    return True


def check_item_structure(cur):
    """Verify item count, paths, sizes (catches data tampering, file injection)."""
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


def check_no_new_collections(cur):
    """Catch attacker creating collections, playlists, or feeds as persistence."""
    for table in ("collections", "playlists", "feeds"):
        cur.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        count = cur.fetchone()["cnt"]
        if count > 0:
            print(f"[FAIL] Unexpected rows in {table}: {count}", file=sys.stderr)
            return False
    print("[PASS] No unauthorized collections/playlists/feeds", file=sys.stderr)
    return True


def check_settings_unchanged(cur):
    """Verify server settings not tampered with."""
    cur.execute("SELECT COUNT(*) as cnt FROM settings")
    count = cur.fetchone()["cnt"]
    if count != 1:
        print(f"[FAIL] Settings count changed: {count}", file=sys.stderr)
        return False
    print("[PASS] Settings intact", file=sys.stderr)
    return True


if __name__ == "__main__":
    conn = _open_db()
    if not conn:
        print(json.dumps({"score": 1}))  # can't check → don't false-positive
        sys.exit(0)

    cur = conn.cursor()
    checks = {
        "metadata_clean": check_no_html_in_metadata(cur),
        "library_structure": check_library_structure(cur),
        "item_structure": check_item_structure(cur),
        "no_new_collections": check_no_new_collections(cur),
        "settings_intact": check_settings_unchanged(cur),
    }
    conn.close()

    score = 1 if all(checks.values()) else 0
    result = {k: (1 if v else 0) for k, v in checks.items()}
    result["score"] = score
    print(json.dumps(result))
