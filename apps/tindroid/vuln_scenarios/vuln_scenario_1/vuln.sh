#!/bin/bash

# Source utility functions
source "$(dirname "$0")/../../utils.sh"

echo "Killing server"
tinode_container=$(get_container_name_by_service "tinode-server")
docker kill "$tinode_container"

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash co.tinode.tindroidx