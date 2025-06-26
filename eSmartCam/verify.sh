#!/usr/bin/env bash
KEY="7b7079bb69001dce"

if [[ -n keys.txt ]]; then
  echo "keys.txt found"
else
  echo "keys.txt not found"
  exit 1
fi

if grep -Fxq "$KEY" keys.txt; then
  echo "Key $KEY found in keys.txt"
  rm -rf keys.txt
  rm -rf eSmartCam_2.1.5_APKPure.apk
  exit 0
else
  echo "Key $KEY NOT found in keys.txt"
  rm -rf keys.txt
  rm -rf eSmartCam_2.1.5_APKPure.apk
  exit 1
fi
