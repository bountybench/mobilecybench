#!/bin/bash

# Script to add a new app from cy-suite organization to mobilecybench
# Usage: ./add_app.sh <APP_NAME> <GITHUB_URL>

set -e

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <APP_NAME> <GITHUB_URL>"
    echo "Example: $0 myapp https://github.com/cy-suite/myapp"
    exit 1
fi

APP_NAME="$1"
GITHUB_URL="$2"

# Validate GitHub URL is from cy-suite organization
if [[ ! "$GITHUB_URL" =~ ^https://github\.com/cy-suite/ ]]; then
    echo "Error: GitHub URL must be from cy-suite organization (https://github.com/cy-suite/...)"
    exit 1
fi

# Check if app directory already exists
if [ -d "apps/$APP_NAME" ]; then
    echo "Error: App directory 'apps/$APP_NAME' already exists"
    exit 1
fi

echo "Creating app directory structure for: $APP_NAME"

# Create app directory
mkdir -p "apps/$APP_NAME"

# Add git submodule for codebase
echo "Adding git submodule from: $GITHUB_URL"
git submodule add "$GITHUB_URL" "apps/$APP_NAME/codebase"

echo ""
echo "✓ Successfully created app structure:"
echo "  - Directory: apps/$APP_NAME/"
echo "  - Submodule: apps/$APP_NAME/codebase"
echo ""
echo "Next, pass agent_prompt.txt into an agentic terminal/window with access to the filesystem to complete app setup."
