#!/usr/bin/env bash
# Step-1 check: from INSIDE the isolated Validator container, every allowed
# read returns data and every state-changing request is refused.
# Usage: check_gateway.sh <package> <db-path-on-device>
# Requires: emulator running, gateway.py serving on 127.0.0.1:8765, sandbox up.
set -u
PKG=$1; DB=$2
V="docker run --rm --network a2v_internal -e http_proxy=http://a2v-egress:3128 -e MCBV_GATEWAY=http://host.docker.internal:8765/ mcb/a2-validator:0.1"
run() { echo; echo "\$ mcbv $*"; $V mcbv "$@" 2>&1 | head -c 600; echo; }

echo "=== isolation: no adb, no direct host/internet route ==="
$V sh -c 'which adb || echo "adb: not installed"; curl -s -m5 --noproxy "*" http://host.docker.internal:5037 >/dev/null && echo "HOST ADB REACHABLE (BAD)" || echo "direct host:5037 unreachable"; curl -s -m5 -x http://a2v-egress:3128 http://host.docker.internal:5037 -o /dev/null -w "via proxy to host:5037 -> HTTP %{http_code}\n"; curl -s -m8 -x http://a2v-egress:3128 https://example.com -o /dev/null -w "via proxy to example.com -> %{http_code}\n" || echo "example.com blocked"'

echo "=== allowed reads ==="
run shell "dumpsys activity activities"
run shell "getprop ro.build.version.sdk"
run ls /data/data/$PKG
run exists /data/data/$PKG/databases
run grep "CREATE TABLE" /data/data/$PKG/databases
run sqlite $DB "select name from sqlite_master where type='table' limit 3"
run ui-find Phone
run logcat ActivityManager
$V sh -c "mcbv ui-dump | head -c 300; echo"

echo "=== state-changing requests (must be REFUSED) ==="
run shell "am start -a android.intent.action.VIEW -d https://example.com"
run shell "input tap 500 500"
run shell "pm clear $PKG"
run shell "touch /data/data/$PKG/pwned"
run shell "cat /dev/null > /data/data/$PKG/pwned"
run shell "ls; rm -rf /sdcard"
run shell "sqlite3 $DB \"insert into x values(1)\""
run sqlite $DB "insert into _sync_state(account_name) values('pwned')"
run sqlite $DB "select 1; delete from _sync_state"
run shell "content insert --uri content://settings/system --bind name:s:x --bind value:s:y"
run shell "settings put global airplane_mode_on 1"
run shell "dumpsys battery set level 5"
