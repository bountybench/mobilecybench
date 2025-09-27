#!/bin/bash
set -e
mkdir apk
wget "$(jq -r '.download_link' metadata.json)" -O apk/keepassdx.apk
