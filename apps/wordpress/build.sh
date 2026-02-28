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

# Tune for constrained environments: cap heap (default 6GB OOMs on 7GB CI runners),
# limit Kotlin daemon memory, and disable Automattic's build scan / remote cache.
sed -i 's/-Xmx6g/-Xmx4g/' gradle.properties
echo "kotlin.daemon.jvmargs=-Xmx2g" >> gradle.properties
echo "develocity.scan.uploadInBackground=false" >> gradle.properties
sed -i 's/publishing.onlyIf { true }/publishing.onlyIf { false }/' config/gradle/gradle_build_scan.gradle

./gradlew assembleWordpressVanillaRelease --no-daemon --parallel --no-build-cache \
    -x lint -x lintWordpressVanillaRelease -x test

cp wordpress/build/outputs/apk/wordpressVanilla/release/*-wordpress-vanilla-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
