#!/bin/bash

echo "Killing server"
docker kill tinode-server

echo "Crashing app"
ADB_PATH=$(which adb)
$ADB_PATH shell am crash co.tinode.tindroidx