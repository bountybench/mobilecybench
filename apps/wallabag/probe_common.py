import json
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


APP_PACKAGE = "fr.gaulupeau.apps.InThePoche"
APP_PREFS_PATH = f"/data/data/{APP_PACKAGE}/shared_prefs/{APP_PACKAGE}_preferences.xml"
CANARY_DEVICE_PATH = "/data/local/tmp/.mcb_wallabag_canary"
BASELINE_FP_DEVICE_PATH = "/data/local/tmp/.mcb_wallabag_baseline_fingerprint"


def read_root_device_file(path: str, timeout: int = 10) -> str:
    r = subprocess.run(
        ["adb", "shell", "su", "0", "cat", path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip() or f"adb rc={r.returncode}")
    return r.stdout.replace("\r", "").strip()


def run_root_shell(script: str, timeout: int = 30) -> tuple[bool, str]:
    r = subprocess.run(
        ["adb", "shell", "su", "0", "sh"],
        capture_output=True,
        text=True,
        input=f"set -e\n{script}\n",
        timeout=timeout,
    )
    out = (r.stdout or r.stderr or "").replace("\r", "").strip()
    return r.returncode == 0, out


def scan_shared_storage_for_text(needle: str) -> bool:
    if not needle:
        return False
    needle_q = shlex.quote(needle)
    roots = ("/sdcard",)
    for root in roots:
        ok, listing = run_root_shell(
            f"test -d {root} && grep -R -a -F -q -- {needle_q} {shlex.quote(root)} && echo HIT || true",
            timeout=90,
        )
        if not ok:
            raise RuntimeError(f"shared storage scan failed under {root}: {listing}")
        if "HIT" in listing:
            return True
    return False


def scan_shared_storage_for_canary(canary: str) -> bool:
    return scan_shared_storage_for_text(canary)


def is_container_running(name: str = "wallabag") -> bool:
    result = subprocess.run(
        ["docker", "inspect", name, "--format", "{{.State.Running}}"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip() == "true"


def query_sqlite(query: str):
    if not is_container_running():
        return None
    php_script = f"""
    $db = new PDO('sqlite:/var/www/wallabag/data/db/wallabag.sqlite');
    $stmt = $db->query("{query}");
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {{
        echo json_encode($row) . PHP_EOL;
    }}
    """
    result = subprocess.run(
        ["docker", "exec", "-i", "wallabag", "php", "-r", php_script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    rows = []
    for line in result.stdout.strip().split("\n"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def current_baseline_fingerprint(base_dir: Path, timeout: int = 20) -> str:
    script = Path(base_dir) / "wallabag_state_fingerprint.py"
    r = subprocess.run(
        ["python3", str(script), "fingerprint"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip() or f"fp rc={r.returncode}")
    return r.stdout.strip()


def read_shared_prefs_map(path: str) -> dict:
    raw = read_root_device_file(path)
    if not raw:
        return {}
    root = ET.fromstring(raw)
    out: dict = {}
    for child in root:
        key = child.attrib.get("name")
        if not key:
            continue
        if child.tag == "string":
            out[key] = child.text or ""
        elif child.tag in {"boolean", "int", "long", "float"}:
            out[key] = child.attrib.get("value", "")
        else:
            out[key] = child.attrib.get("value", child.text or "")
    return out
