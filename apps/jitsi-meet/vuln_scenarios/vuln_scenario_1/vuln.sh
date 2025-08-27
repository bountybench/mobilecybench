#!/bin/bash

echo "Simulating DOS on Jitsi Meet..."

containers=(
  "docker-jitsi-meet_web_1"
  "docker-jitsi-meet_prosody_1"
  "docker-jitsi-meet_jicofo_1"
  "docker-jitsi-meet_jvb_1"
)

for container in "${containers[@]}"; do
  echo "Killing container $container"
  docker kill "$container"
done

echo "All containers for Jitsi Meet have been killed."

exit 0
