#!/bin/bash
set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Running linter from directory: $(pwd)"

# Install linting dependencies
echo "Installing linting dependencies..."
python -m pip install --upgrade pip
pip install "black==24.10.0" "ruff==0.13.0"

# Get changed Python files (modified, staged, untracked), excluding deleted and "codebase" paths
echo "Finding changed Python files (excluding codebase paths)..."

# Fetch latest main branch to ensure accurate comparison
echo "Fetching latest origin/main..."
if ! git fetch origin main; then
    echo "❌ Failed to fetch origin/main - please check your git setup"
    exit 1
fi

# Collect candidates from modified files compared to main (like GitHub CI)
CANDIDATES=()
while IFS= read -r f; do
  [ -n "$f" ] && CANDIDATES+=("$f")
done < <(
  {
    # Command 1: Find committed changes against main
    git diff --name-only --diff-filter=d origin/main HEAD -- '*.py'

    # Command 2: Find local uncommitted changes
    git ls-files -m -- '*.py'
    git diff --name-only --cached -- '*.py'
    git ls-files --others --exclude-standard -- '*.py'

} 2>/dev/null | grep -v "codebase" | sort -u
)

# Filter to only paths that currently exist on disk
FILES_TO_LINT=()
if [ ${#CANDIDATES[@]} -gt 0 ]; then
  for f in "${CANDIDATES[@]}"; do
    if [ -n "$f" ] && [ -e "$f" ]; then
      FILES_TO_LINT+=("$f")
    fi
  done
fi

if [ ${#FILES_TO_LINT[@]} -gt 0 ]; then
    echo "Python files to lint:"
    printf '%s\n' "${FILES_TO_LINT[@]}"
    echo ""

    echo "Linting with ruff (style, errors, imports) and applying fixes..."
    if ! ruff check --select E,F,I --line-length 120 --fix "${FILES_TO_LINT[@]}"; then
        echo "❌ Ruff found unfixable issues - please review and fix manually"
        exit 1
    fi

    echo "Running black to format after ruff fixes..."
    if ! black "${FILES_TO_LINT[@]}"; then
        echo "❌ Black formatting failed"
        exit 1
    fi

    echo "✅ All linting and formatting completed successfully!"
else
    echo "No changed Python files to lint (excluding codebase paths)"
fi
