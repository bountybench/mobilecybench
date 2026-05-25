#!/bin/bash
#
# Publish APK bundle(s) to GitHub release.
#
# Default behavior: publishes the default bundle (apk/* contents excluding
# apk/obfuscated/). If apk/obfuscated/ also exists and contains APKs,
# additionally publishes the obfuscated bundle at the SAME version number
# so the two variants stay in lockstep. metadata.json gets download_link
# and (when obfuscated bundle is published) download_link_obfuscated.
#
# Flags (escape hatches; default behavior is correct for most app updates):
#   --default-only      Publish only the default bundle, skip obfuscated even if present.
#   --obfuscated-only   Publish only the obfuscated bundle. Uses the SAME version
#                       number as the default sequence so versions stay aligned
#                       (i.e. if default is at v5, the obfuscated bundle is also v5).
#
# Usage:
#   ./publish_apk_bundle.sh apps/<app_name>                    # both if obfuscated/ exists
#   ./publish_apk_bundle.sh apps/<app_name> --default-only     # default only
#   ./publish_apk_bundle.sh apps/<app_name> --obfuscated-only  # obfuscated only

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 apps/<app_name> [--default-only | --obfuscated-only]"
    echo "Example: $0 apps/owncloud-android                     # both"
    echo "Example: $0 apps/owncloud-android --default-only      # default bundle only"
    echo "Example: $0 apps/owncloud-android --obfuscated-only   # obfuscated bundle only"
    exit 1
fi

APP_DIR="$1"
MODE="auto"  # auto = publish both if obfuscated/ exists; --default-only / --obfuscated-only override
shift
while [ $# -gt 0 ]; do
    case "$1" in
        --default-only)    MODE="default-only" ;;
        --obfuscated-only) MODE="obfuscated-only" ;;
        # Back-compat: --obfuscated (old single-variant flag) maps to --obfuscated-only.
        --obfuscated)      MODE="obfuscated-only" ;;
        *)
            echo "Error: unknown argument: $1"
            echo "Usage: $0 apps/<app_name> [--default-only | --obfuscated-only]"
            exit 1
            ;;
    esac
    shift
done

APP_NAME=$(basename "$APP_DIR")
APK_DIR="$APP_DIR/apk"
OBF_DIR="$APK_DIR/obfuscated"
REPO="bountybench/mobilecybench"
METADATA="$APP_DIR/metadata.json"

if [ ! -d "$APK_DIR" ]; then
    echo "Error: $APK_DIR not found"
    exit 1
fi

# --- Determine which bundles to publish ---
publish_default=false
publish_obfuscated=false
case "$MODE" in
    default-only)    publish_default=true ;;
    obfuscated-only) publish_obfuscated=true ;;
    auto)
        publish_default=true
        # Auto-include obfuscated when the directory exists and has APKs.
        if [ -d "$OBF_DIR" ] && [ -n "$(find "$OBF_DIR" -maxdepth 1 -name '*.apk' -type f 2>/dev/null)" ]; then
            publish_obfuscated=true
        fi
        ;;
esac

# --- Sanity checks per variant ---
if [ "$publish_default" = true ]; then
    if [ -z "$(find "$APK_DIR" -maxdepth 1 -name '*.apk' -type f 2>/dev/null)" ]; then
        echo "Error: No APKs found in $APK_DIR (required for default bundle)"
        exit 1
    fi
fi
if [ "$publish_obfuscated" = true ]; then
    if [ ! -d "$OBF_DIR" ]; then
        echo "Error: $OBF_DIR not found (required for obfuscated bundle)"
        exit 1
    fi
    if [ -z "$(find "$OBF_DIR" -maxdepth 1 -name '*.apk' -type f 2>/dev/null)" ]; then
        echo "Error: No APKs found in $OBF_DIR (required for obfuscated bundle)"
        exit 1
    fi
fi

# --- Lockstep version: both variants share the default sequence's next N. ---
# This guarantees apk-<app>-v5.zip and apk-<app>-obfuscated-v5.zip refer to
# the same source commit; downstream consumers can correlate by version alone.
#
# --obfuscated-only reuses the existing default version (CURRENT_VERSION) so
# we land alongside an already-published default vN. Incrementing would
# produce apk-<app>-obfuscated-vN+1 with no matching default vN+1, breaking
# the by-version correlation downstream code relies on.
LATEST=$(gh release list --repo "$REPO" --limit 1000 --json tagName --jq '.[].tagName' 2>/dev/null \
    | grep -E "^apk-${APP_NAME}-v[0-9]+$" | sort -V | tail -1)
if [ -n "$LATEST" ]; then
    CURRENT_VERSION=$(echo "$LATEST" | sed "s/apk-${APP_NAME}-v//")
    if [ "$MODE" = "obfuscated-only" ]; then
        NEXT_VERSION="$CURRENT_VERSION"
        # Pre-check that the lockstep obfuscated tag isn't already taken.
        # Without this, gh release create later fails with an opaque
        # "release already exists" message; hint at the recovery path.
        obf_tag="apk-${APP_NAME}-obfuscated-v$NEXT_VERSION"
        if gh release view "$obf_tag" --repo "$REPO" >/dev/null 2>&1; then
            echo "Error: $obf_tag already exists at the lockstep version." >&2
            echo "To republish, delete it first: gh release delete $obf_tag --repo $REPO --yes" >&2
            exit 1
        fi
    else
        NEXT_VERSION=$((CURRENT_VERSION + 1))
    fi
else
    if [ "$MODE" = "obfuscated-only" ]; then
        echo "Error: --obfuscated-only needs an existing apk-${APP_NAME}-v<N> default release to be in lockstep with; none found." >&2
        echo "Publish a default bundle first (auto or --default-only) and rerun." >&2
        exit 1
    fi
    NEXT_VERSION=0
fi

echo "App: $APP_NAME"
echo "Version: v$NEXT_VERSION"
echo "Publishing: default=$publish_default obfuscated=$publish_obfuscated"
echo ""

# --- publish_variant <variant_name> <zip_name> <metadata_field> [--from-dir <subdir>] <zip_args...> ---
# variant_name appears in the release tag; "default" produces apk-<app>-vN,
# anything else produces apk-<app>-<variant>-vN. Both variants share vN.
#
# Optional `--from-dir <subdir>` zips from $APP_DIR/<subdir> instead of
# $APP_DIR, so the subdir's contents land at the zip root. Needed because
# utils/apk_utils.py:_extract_zip strips only an "apk/" prefix — if we zip
# apk/obfuscated/<file> as-is, extraction nests as apk/obfuscated/obfuscated/.
publish_variant() {
    local variant="$1"
    local zip_name="$2"
    local metadata_field="$3"
    shift 3

    local from_dir="$APP_DIR"
    if [ "$1" = "--from-dir" ]; then
        from_dir="$APP_DIR/$2"
        shift 2
    fi
    local zip_args=("$@")

    local tag
    if [ "$variant" = "default" ]; then
        tag="apk-${APP_NAME}-v$NEXT_VERSION"
    else
        tag="apk-${APP_NAME}-${variant}-v$NEXT_VERSION"
    fi

    local zip_file="$APP_DIR/$zip_name"
    echo "--- $variant → $tag ---"
    pushd "$from_dir" > /dev/null
    zip -r "$zip_file" "${zip_args[@]}"
    popd > /dev/null

    echo "Uploading to GitHub release..."
    gh release create "$tag" "$zip_file" \
        --repo "$REPO" \
        --title "$tag" \
        --notes "APK bundle for $APP_NAME ($variant, version $NEXT_VERSION)"

    local url="https://github.com/$REPO/releases/download/$tag/$zip_name"
    if [ -f "$METADATA" ]; then
        jq --arg url "$url" ".${metadata_field} = \$url" "$METADATA" > "$METADATA.tmp" \
            && mv "$METADATA.tmp" "$METADATA"
        echo "Updated $METADATA: $metadata_field = $url"
    else
        echo "Warning: $METADATA not found; add manually:" >&2
        echo "  \"$metadata_field\": \"$url\"" >&2
    fi

    rm "$zip_file"
    echo "$url"
    echo ""
}

URLS=()

if [ "$publish_default" = true ]; then
    # Exclude apk/obfuscated/ so the two bundles never commingle.
    URL=$(publish_variant "default" "apk-bundle.zip" "download_link" \
        apk/ -x 'apk/obfuscated/*' -x 'apk/obfuscated' | tail -1)
    URLS+=("default: $URL")
fi

if [ "$publish_obfuscated" = true ]; then
    # Zip from inside apk/obfuscated/ so entries are root-level <file>.apk
    # (or <vuln_id>/<file>.apk for synthetic-vuln subdirs). _extract_zip then
    # writes them directly under apk_dir = apps/<app>/apk/obfuscated/.
    URL=$(publish_variant "obfuscated" "apk-${APP_NAME}-obfuscated-bundle.zip" "download_link_obfuscated" \
        --from-dir apk/obfuscated . | tail -1)
    URLS+=("obfuscated: $URL")
fi

echo "Done. Published:"
for line in "${URLS[@]}"; do
    echo "  $line"
done
