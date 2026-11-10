#!/usr/bin/env bash
# Fetch each in-scope app's source at its pinned commit (apps/<app>/metadata.json
# commit_version, the commit the agent codebase and published APKs use) and
# export it without .git into $SRC_ROOT/<app>/.
# Usage: prepare_sources.sh <src_root> [app ...]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_ROOT="$1"; shift
APPS=("$@")
[ ${#APPS[@]} -eq 0 ] && APPS=($(jq -r '.sets.in_scope[]' "$REPO_ROOT/apps/app_catalog.json"))
mkdir -p "$SRC_ROOT/.git_cache"

for app in "${APPS[@]}"; do
  meta="$REPO_ROOT/apps/$app/metadata.json"
  ref=$(jq -r .commit_version "$meta")
  repo=$(jq -r .gh_link "$meta" | sed -E 's#https://github.com/##; s#\.git$##')
  # termux: metadata gh_link (cy-suite/termux-app) 404s; the submodule URL
  # cy-suite/termux holds the same pinned SHA.
  [ "$app" = termux ] && repo=cy-suite/termux
  sha=$(gh api "repos/$repo/commits/$ref" --jq .sha)
  dest="$SRC_ROOT/$app"
  if [ -f "$SRC_ROOT/.git_cache/$app.sha" ] && [ "$(cat "$SRC_ROOT/.git_cache/$app.sha")" = "$sha" ]; then
    echo "$app: cached $sha"; continue
  fi
  gd="$SRC_ROOT/.git_cache/$app.git"
  [ -d "$gd" ] || git init -q --bare "$gd"
  git --git-dir="$gd" fetch -q --depth 1 "https://github.com/$repo.git" "$sha"
  rm -rf "$dest"; mkdir -p "$dest"
  git --git-dir="$gd" --work-tree="$dest" checkout -q -f "$sha" -- .
  echo "$sha" > "$SRC_ROOT/.git_cache/$app.sha"
  echo "$app: $repo@$sha ($(find "$dest" -type f | wc -l | tr -d ' ') files)"
done
