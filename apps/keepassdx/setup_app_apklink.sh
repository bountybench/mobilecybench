#!/bin/bash
set -e

wget "$(jq -r '.download_link' metadata.json)" -O apk/keepassdx.apk
