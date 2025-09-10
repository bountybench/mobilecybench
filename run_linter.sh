#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Running linter from directory: $(pwd)"

# Install linting dependencies
echo "Installing linting dependencies..."
python -m pip install --upgrade pip
pip install "black==24.10.0" "isort==5.13.2"

# Get changed Python files (modified, staged, untracked), excluding deleted and "codebase" paths
echo "Finding changed Python files (excluding codebase paths)..."

# Collect candidates from three sources:
#  - modified in working tree
#  - staged changes (e.g., git mv/renames)
#  - untracked (new files)
CANDIDATES=()
while IFS= read -r f; do
  [ -n "$f" ] && CANDIDATES+=("$f")
done < <(
  {
    git ls-files -m -- '*.py'
    git diff --name-only --cached -- '*.py'
    git ls-files --others --exclude-standard -- '*.py'
  } 2>/dev/null | grep -v "codebase" | sort -u
)

# Filter to only paths that currently exist on disk
FILES_TO_LINT=()
for f in "${CANDIDATES[@]}"; do
  if [ -n "$f" ] && [ -e "$f" ]; then
    FILES_TO_LINT+=("$f")
  fi
done

if [ ${#FILES_TO_LINT[@]} -gt 0 ]; then
    echo "Python files to lint:"
    printf '%s\n' "${FILES_TO_LINT[@]}"
    echo ""

    echo "Running black to fix formatting..."
    black "${FILES_TO_LINT[@]}"

    echo "Running isort to fix imports..."
    isort --profile black "${FILES_TO_LINT[@]}"

    echo "Formatting completed!"
else
    echo "No changed Python files to lint (excluding codebase paths)"
fi
