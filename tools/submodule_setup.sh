#!/usr/bin/env bash
set -euo pipefail

USE_AGENT=0
KEY_PATH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --use-key) USE_AGENT=0; KEY_PATH="$2"; shift 2;;
    --use-ssh-agent) USE_AGENT=1; shift;;
    *) shift;;
  esac
done

if [ "$USE_AGENT" -eq 1 ]; then
  export GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes'
else
  if [ -z "$KEY_PATH" ]; then
    export GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes'
  else
    chmod 600 "$KEY_PATH"
    export GIT_SSH_COMMAND="ssh -i $KEY_PATH -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
  fi
fi

git submodule sync --recursive
git submodule update --init --recursive --timeout=30 || {
  sleep 2
  git submodule update --init --recursive --timeout=30
}