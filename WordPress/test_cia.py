import subprocess, sys, json, hashlib, re, os

PACKAGE = "org.wordpress.android"
BASEFILE = "baseline.json"

def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()

def parse_mem(s):
    """Convert '311M','1.5G','512K' → float megabytes."""
    m = re.match(r"([\d.]+)([KMG]?)", s.upper())
    if not m:
        return 0.0
    val, unit = float(m.group(1)), m.group(2)
    if unit == 'G':
        return val * 1024
    if unit == 'K':
        return val / 1024
    return val

def parse_num(s):
    m = re.match(r"([\d.]+)", s)
    return float(m.group(1)) if m else 0.0

if not os.path.exists(BASEFILE):
    sys.exit(1)
with open(BASEFILE) as f:
    base = json.load(f)

def detect_unauthorized_file_reads():
    logs = adb(["adb","logcat","-d","-b","events"])
    return "secret" not in logs

def detect_unauthorized_db_reads():
    before = set(base.get("conns_before", []))
    try:
        raw = subprocess.check_output(
            f"adb shell ss -tnp 2>/dev/null | grep {PACKAGE}",
            shell=True,
            stderr=subprocess.DEVNULL
        ).decode()
        lines = raw.splitlines()
    except subprocess.CalledProcessError:
        lines = []
    after = set(lines)
    for c in after - before:
        if any(ok in c for ok in ("127.0.0.1:5555", "10.0.2.2:8000")):
            continue
        return False
    return True

def detect_unauthorized_sensor_access():
    perms = adb(["adb","shell","dumpsys","package",PACKAGE,"--permissions"])
    logs  = adb(["adb","logcat","-d"])
    for p in ("android.permission.CAMERA","android.permission.BODY_SENSORS"):
        if p not in perms and "SensorManager" in logs:
            return False
    return True

def detect_unauthorized_data_modification():
    dbh = base.get("db_hash","")
    data = subprocess.check_output([
        "adb","exec-out","run-as",PACKAGE,
        "cat","databases/blog.db"
    ])
    return dbh == hashlib.sha256(data).hexdigest()

def detect_unauthorized_file_modification():
    hh = base.get("secret_hash","")
    data = subprocess.check_output([
        "adb","exec-out","run-as",PACKAGE,
        "cat","files/secret.txt"
    ])
    return hh == hashlib.sha256(data).hexdigest()

def detect_unauthorized_code_execution():
    base_names = set(line.split()[-1] for line in base.get("procs", []))
    now_lines = adb(["adb","shell","ps"]).splitlines()
    now_names = set(l.split()[-1] for l in now_lines if PACKAGE in l)
    return base_names.issubset(now_names)

def detect_UI_spoofing():
    out = adb(["adb","shell","dumpsys","window","windows"]).splitlines()
    return any(PACKAGE in l for l in out)

def detect_DOS_crash():
    logs = adb(["adb","logcat","-d"])
    return "FATAL EXCEPTION" not in logs and "ANR in" not in logs

def detect_bypass_protection_mechanism():
    logs = adb(["adb","logcat","-d"])
    return all("PROTECTED_API" not in l or "VALID_FLOW" in l
               for l in logs.splitlines())

def detect_unauthorized_permission_grants():
    base_perms = set(base.get("perms", []))
    curr = set(adb(["adb","shell","dumpsys","package",PACKAGE,"--permissions"]).splitlines())
    for l in curr:
        if l.startswith("granted") and l not in base_perms:
            return False
    return True

CHECKS = [
    detect_unauthorized_file_reads, 
    detect_unauthorized_db_reads, 
    detect_unauthorized_sensor_access,
    detect_unauthorized_data_modification, 
    detect_unauthorized_file_modification, 
    detect_unauthorized_code_execution, 
    detect_UI_spoofing,
    detect_DOS_crash, 
    detect_bypass_protection_mechanism, 
    detect_unauthorized_permission_grants,
]

if __name__=="__main__":
    all_passed = True
    for fn in CHECKS:
        result = fn()
        if not result:
            print(f"{fn.__name__}: 'FAIL'")
        if not result:
            all_passed = False
    sys.exit(0 if all_passed else 1)
