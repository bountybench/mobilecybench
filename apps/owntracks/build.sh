#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/codebase/project"
PROGUARD_FILE="$PROJECT_DIR/app/proguard-rules.pro"
PROGUARD_BACKUP=""

restore_owntracks_build_files() {
    if [[ -n "$PROGUARD_BACKUP" && -f "$PROGUARD_BACKUP" ]]; then
        mv "$PROGUARD_BACKUP" "$PROGUARD_FILE"
    fi
}
trap restore_owntracks_build_files EXIT

if [[ "${MCB_OBFUSCATE:-0}" = "1" ]]; then
    if [[ -f "$PROGUARD_FILE" ]]; then
        PROGUARD_BACKUP="$(mktemp "${PROGUARD_FILE}.mcb-obfuscate.XXXXXX")"
        cp "$PROGUARD_FILE" "$PROGUARD_BACKUP"

        # Upstream release builds already run R8, but this app's rules opt out of
        # name obfuscation and keep the entire app package. For benchmark
        # obfuscated APKs, remove those two app-level blockers while preserving
        # dependency/framework keep rules (Jackson, Paho, Conscrypt, etc.).
        python3 - "$PROGUARD_FILE" <<'PY'
from pathlib import Path
import re
import sys
p = Path(sys.argv[1])
s = p.read_text()
s = re.sub(r'(?m)^\s*-dontobfuscate\s*\n', '', s)
s = re.sub(
    r'(?ms)^\s*# Keep our package\s*\n\s*-keep public class org\.owntracks\.android\.\*\* \{\s*\n\s*public protected private \*;\s*\n\s*\}\s*\n+',
    '',
    s,
)
s += '''

# MobileCyBench obfuscated APK runtime keep rules:
# OwnTracks uses Kotlin delegated preferences and property references such as
# Preferences::setupCompleted. Kotlin reflection resolves these against the
# declaring class metadata, so this reflection-heavy class and its accessors
# must keep their JVM names. The reflected getter signatures also include the
# custom preference value/enum types, so keep those type names too. This is
# intentionally scoped to preferences reflection support; the rest of the app
# remains eligible for obfuscation.
-keep,allowoptimization class org.owntracks.android.preferences.Preferences {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.preferences.types.** {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.location.LocatorPriority {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.ui.map.MapLayerStyle {
  public protected private *;
}

# Room loads generated database implementations by appending "_Impl" to the
# database class name. Keep only the app's two Room database classes and their
# generated implementations so that lookup keeps working after R8 renames the
# rest of the codebase.
-keep,allowoptimization class org.owntracks.android.data.waypoints.RoomWaypointsRepo {
}
-keep,allowoptimization class org.owntracks.android.data.waypoints.RoomWaypointsRepo$WaypointDatabase {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.data.waypoints.RoomWaypointsRepo_WaypointDatabase_Impl {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.net.mqtt.RoomMqttClientPersistence {
}
-keep,allowoptimization class org.owntracks.android.net.mqtt.RoomMqttClientPersistence$MqttPersistableDatabase {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.net.mqtt.RoomMqttClientPersistence_MqttPersistableDatabase_Impl {
  public protected private *;
}

# BouncyCastle's provider code resolves several implementation classes by
# their published provider names. Upstream already kept org.bouncycastle.jce*
# but the obfuscated build also needs the rest of the third-party provider
# namespace (e.g. org.bouncycastle.crypto.CryptoServicesRegistrar). This does
# not keep OwnTracks application classes.
-keep class org.bouncycastle.** {
  public protected private *;
}

# OwnTracks serializes/deserializes its polymorphic wire/configuration DTOs
# with Jackson annotations on MessageBase/MessageConfiguration/etc. Without
# the old package-wide keep rule, R8 renames/optimizes these DTO members enough
# that configuration URI import falls back to MessageUnknown. Keep only the
# Jackson DTO package; service/network/business logic remains obfuscated.
-keep,allowoptimization class org.owntracks.android.model.messages.** {
  public protected private *;
}

# Jackson also deserializes these app model enums by @JsonValue strings.
# Keep the enum/member names for stable command/location parsing.
-keep,allowoptimization class org.owntracks.android.model.CommandAction {
  public protected private *;
}
-keep,allowoptimization class org.owntracks.android.model.BatteryStatus {
  public protected private *;
}
'''
p.write_text(s)
PY
        if grep -q -- '-dontobfuscate\|org\.owntracks\.android\.\*\*' "$PROGUARD_FILE"; then
            echo "ERROR: failed to remove OwnTracks obfuscation blockers from $PROGUARD_FILE" >&2
            exit 1
        fi
    else
        echo "ERROR: expected ProGuard rules at $PROGUARD_FILE" >&2
        exit 1
    fi
fi

cd "$PROJECT_DIR"

GRADLE_ARGS=()
if [[ "${MCB_OBFUSCATE:-0}" = "1" && -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

./gradlew "${GRADLE_ARGS[@]}" ${GRADLE_EXTRA_ARGS:-} :app:assembleOssRelease --no-daemon

cp app/build/outputs/apk/oss/release/*-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
