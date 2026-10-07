#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'usage: %s <project-root> <worktree-path>\n' "$0" >&2
  exit 2
fi

project_root_input=$1
worktree_path_input=$2

if [[ ! -d "$project_root_input" || ! -d "$worktree_path_input" ]]; then
  printf 'project root and worktree path must both exist\n' >&2
  exit 2
fi

project_root=$(cd "$project_root_input" && pwd -P)
worktree_path=$(cd "$worktree_path_input" && pwd -P)

if [[ "$project_root" == "$worktree_path" ]]; then
  exit 0
fi

# Link only package-local ignored configuration, never replace a caller path.
for package in service-bursawatch-control lib-sectors lib-chart-img; do
  package_dir="$worktree_path/$package"
  source_env="$project_root/$package/.env"
  target_env="$package_dir/.env"

  if [[ ! -d "$package_dir" || ! -f "$source_env" ]]; then
    continue
  fi
  if [[ -L "$target_env" ]] && [[ "$(readlink "$target_env")" == "$source_env" ]]; then
    continue
  fi
  if [[ -e "$target_env" || -L "$target_env" ]]; then
    printf 'refusing to replace existing %s/.env\n' "$package" >&2
    exit 1
  fi
  ln -s "$source_env" "$target_env"
done
