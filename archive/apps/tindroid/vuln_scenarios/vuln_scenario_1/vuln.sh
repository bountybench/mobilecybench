#!/bin/bash

echo "Killing server"
tinode_container="tinode-server"
docker kill "$tinode_container"

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash co.tinode.tindroidx