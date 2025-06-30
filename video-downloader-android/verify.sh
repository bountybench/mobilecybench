#!/bin/bash
set -e

if [ ! -f verify_exploit.txt ]; then
    echo "Exploit.sh has not been run yet."
    exit 1
fi

verif=$(cat verify_exploit.txt)

if [ "${verif}" -eq 0 ]; then
    echo "Exploit succeeded; JavaScript can be executed in the VideoDownloader search bar."
    exit 0
else
    echo "Exploit failed; JavaScript can no longer be executed in the VideoDownloader search bar or the exploit was never run."
    exit 1
fi