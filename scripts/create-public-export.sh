#!/usr/bin/env bash
# Create a one-commit public repository without copying private Git history.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 OUTPUT_DIRECTORY" >&2
  exit 2
fi

for command_name in git tar python3 mktemp realpath; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Public export failed: required command is unavailable: $command_name" >&2
    exit 2
  fi
done

source_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "Public export failed: run this script from a Kalki Git checkout." >&2
  exit 2
}
source_root=$(realpath "$source_root")
source_commit=$(git -C "$source_root" rev-parse --verify HEAD^{commit})

if ! git -C "$source_root" diff --quiet || ! git -C "$source_root" diff --cached --quiet; then
  echo "Public export failed: tracked or staged changes are present." >&2
  exit 2
fi
if ! git -C "$source_root" ls-files --error-unmatch LICENSE \
  scripts/validate-public-tree.py docs/PUBLIC_RELEASE_CANDIDATE.md >/dev/null 2>&1; then
  echo "Public export failed: required release files are not tracked at HEAD." >&2
  exit 2
fi

output_requested=$1
output_parent=$(realpath -m "$(dirname "$output_requested")")
output_name=$(basename "$output_requested")
if [[ ! -d "$output_parent" || ! -w "$output_parent" ]]; then
  echo "Public export failed: output parent must already exist and be writable." >&2
  exit 2
fi
output_directory=$(realpath -m "$output_parent/$output_name")
if [[ -e "$output_directory" ]]; then
  echo "Public export failed: output path already exists." >&2
  exit 2
fi
case "$output_directory" in
  "$source_root"|"$source_root"/*)
    echo "Public export failed: output must be outside the private checkout." >&2
    exit 2
    ;;
esac

stage=$(mktemp -d "$output_parent/.kalki-public-export.XXXXXX")
cleanup() {
  if [[ -n "${stage:-}" && -d "$stage" ]]; then
    rm -rf -- "$stage"
  fi
}
trap cleanup EXIT

# git archive reads only HEAD's tracked snapshot, respects export-ignore, and cannot
# copy the source .git directory or any ignored/untracked local files.
git -C "$source_root" archive --format=tar HEAD | tar -xf - -C "$stage"
python3 "$stage/scripts/validate-public-tree.py" "$stage"

git -C "$stage" init --initial-branch=main --quiet
git -C "$stage" add --all
git -C "$stage" \
  -c user.name="Kalki Public Export" \
  -c user.email="noreply@example.invalid" \
  commit --quiet \
  -m "Initial public release: Observation Baseline V2" \
  -m "Private-source-commit: $source_commit"

public_commit=$(git -C "$stage" rev-parse HEAD)
if [[ $(git -C "$stage" rev-list --all --count) != "1" ]]; then
  echo "Public export failed: new repository contains more than one commit." >&2
  exit 2
fi
if git -C "$stage" cat-file -e "$source_commit^{commit}" 2>/dev/null; then
  echo "Public export failed: private source commit is reachable in the export." >&2
  exit 2
fi
if [[ -e "$stage/.git/objects/info/alternates" ]]; then
  echo "Public export failed: object alternates could reference private history." >&2
  exit 2
fi
if [[ -n $(git -C "$stage" remote) ]]; then
  echo "Public export failed: the new repository unexpectedly has a remote." >&2
  exit 2
fi
git -C "$stage" fsck --full --no-dangling >/dev/null
git -C "$stage" diff --quiet
git -C "$stage" diff --cached --quiet
python3 "$stage/scripts/validate-public-tree.py" --allow-git-metadata "$stage"

mv -- "$stage" "$output_directory"
stage=""
trap - EXIT

untracked_count=$(git -C "$source_root" status --porcelain --untracked-files=all | awk '$1 == "??" {count++} END {print count+0}')
echo "PUBLIC_EXPORT_CREATED=$output_directory"
echo "PUBLIC_EXPORT_SOURCE_COMMIT=$source_commit"
echo "PUBLIC_EXPORT_INITIAL_COMMIT=$public_commit"
echo "SOURCE_UNTRACKED_FILES_EXCLUDED=$untracked_count"
echo "NETWORK_OR_REMOTE_MUTATION=NONE"
