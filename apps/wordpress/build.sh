#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Patch login discovery: the app validates site URLs by calling WordPress.com's
# connect/site-info API, which cannot reach local addresses like 10.0.2.2.
# This makes self-hosted login on local/private networks impossible.
# Fix: on site-info failure, fall back to direct XML-RPC discovery.
LOGIN_FRAGMENT="libs/login/src/main/java/org/wordpress/android/login/LoginSiteAddressFragment.kt"
sed -i.bak '/onFetchedConnectSiteInfo has error/,/endProgressIfNeeded()/{
    /onFetchedConnectSiteInfo has error/!{
        /endProgressIfNeeded/!d
        s/endProgressIfNeeded()/initiateDiscovery()/
    }
}' "$LOGIN_FRAGMENT"
rm -f "${LOGIN_FRAGMENT}.bak"

chmod +x gradlew
./gradlew assembleWordpressVanillaRelease --no-daemon --parallel --build-cache \
    -x lint -x lintWordpressVanillaRelease -x test

cp wordpress/build/outputs/apk/wordpressVanilla/release/*-wordpress-vanilla-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
