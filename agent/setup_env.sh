#!/bin/bash

# TODO: This is one-time setup to run the agent and should be removed
# Copy conversations app codebase to kali container
SOURCE_PATH="../apps/conversations/codebase"
CONTAINER_NAME="kali-container"
TARGET_PATH="/tmp/conversations_app"

echo "Copying $SOURCE_PATH to $CONTAINER_NAME:$TARGET_PATH"

docker exec $CONTAINER_NAME mkdir -p $TARGET_PATH
docker cp $SOURCE_PATH/. $CONTAINER_NAME:$TARGET_PATH/

echo "Done. Files available at $TARGET_PATH in container."