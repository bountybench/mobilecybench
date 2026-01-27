#!/bin/bash

set -e

echo "Killing OpenHAB server"
docker kill openhab

echo "DoS attack completed - server should be unavailable"
