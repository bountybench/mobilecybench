#!/usr/bin/env bash
set -euo pipefail

# Manage OwnCloud app preferences via adb.
# Usage:
#   PIN=4512 ./push_prefs.sh create-password
#   ./push_prefs.sh delete-password

APP_ID="com.owncloud.android"
PREF_XML="com.owncloud.android_preferences.xml"
DEVICE_TMP="/sdcard/oc_prefs.xml"
DEST_DIR="/data/data/${APP_ID}/shared_prefs"
DEST_XML="${DEST_DIR}/${PREF_XML}"

log() { echo "[owncloud_setup] INFO $*"; }
err() { echo "[owncloud_setup] ERROR $*" >&2; }

usage() {
	cat >&2 <<EOF
Usage: PIN=4512 $(basename "$0") create-password | $(basename "$0") delete-password
EOF
}

ACTION="${1:-}"
case "${ACTION}" in
	create-password|create)
		PIN_VAL="${PIN:-}"
		if [[ -z "${PIN_VAL}" ]]; then
			err "PIN environment variable is required for create-password"
			usage; exit 1
		fi
		;;
	delete-password|delete)
		;;
	*)
		usage; exit 1;
		;;
esac

log "Checking device"
adb get-state >/dev/null

TMP_XML="$(mktemp -t owncloud_prefs.XXXXXX.xml)"
trap 'rm -f "${TMP_XML}"' EXIT

if [[ "${ACTION}" == "create-password" || "${ACTION}" == "create" ]]; then
	# Generate preferences enabling PIN lock
	cat >"${TMP_XML}" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
		<int name="lastSeenVersionCode" value="22100100" />
		<long name="last_unlock_timestamp" value="34961287" />
		<string name="PrefPinCode">${PIN_VAL}</string>
		<string name="lock_timeout">IMMEDIATELY</string>
		<boolean name="set_pincode" value="true" />
</map>
EOF
	log "Prepared preferences with PIN"
else
	# Generate preferences without PIN entries
	cat >"${TMP_XML}" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
		<int name="lastSeenVersionCode" value="22100100" />
		<long name="last_unlock_timestamp" value="34961287" />
</map>
EOF
	log "Prepared preferences without PIN"
fi

log "Pushing ${PREF_XML} to ${DEVICE_TMP}"
adb push "${TMP_XML}" "${DEVICE_TMP}" >/dev/null

log "Installing prefs in OwnCloud private storage"
adb shell su 0 cp /sdcard/oc_prefs.xml /data/data/com.owncloud.android/shared_prefs/com.owncloud.android_preferences.xml

log "Forcing stop to ensure app reloads preferences"

# run this several times to make sure it actually stops
for i in {1..5}; do
	adb shell am force-stop "${APP_ID}" || true
	sleep 0.1
done

log "Done"
