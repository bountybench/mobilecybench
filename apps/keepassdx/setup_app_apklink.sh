#!/bin/bash
set -e
mkdir -p apk
wget "$(jq -r '.download_link' metadata.json)" -O apk/keepassdx.apk
