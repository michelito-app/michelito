#!/usr/bin/env bash
# Creates in DESTINATION (a new directory) a git repository with a single commit of the current
# HEAD, without this repository's history. It creates no remotes and does not push: you do that
# afterwards.
#
#   GIT_AUTHOR_NAME="Your public name" \
#   GIT_AUTHOR_EMAIL="<id>+<user>@users.noreply.github.com" \
#   scripts/export_public.sh DESTINATION
#
# The commit identity is mandatory and explicit: it is never taken from your git configuration
# (which may hold your real name or a work email). The committer is the same as the author.
#
# Only what is tracked in HEAD goes in (`git archive`): uncommitted changes and ignored files
# (.superpowers/, databases, PDFs…) stay out, and so do the paths marked
# export-ignore in .gitattributes (CLAUDE.md, kept in the private working repo only). Before the commit it runs scripts/check_private.py
# on the copy and stops if it finds anything.
set -euo pipefail

readonly MESSAGE="feat: initial public release"

if [[ $# -ne 1 || -z "$1" ]]; then
  echo "Usage: $0 DESTINATION   (DESTINATION must not exist)" >&2
  exit 2
fi
destination="$1"
if [[ -e "$destination" ]]; then
  echo "Error: $destination already exists; choose a new directory." >&2
  exit 2
fi
if [[ -z "${GIT_AUTHOR_NAME:-}" || -z "${GIT_AUTHOR_EMAIL:-}" ]]; then
  echo "Error: set GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL to the commit's public identity;" >&2
  echo "for example GitHub's private email: <id>+<user>@users.noreply.github.com" >&2
  echo "(GitHub → Settings → Emails). The identity in your git configuration is not used." >&2
  exit 2
fi
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

source_root="$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)"
target="$(realpath -m -- "$destination")"
if [[ "$target" == "$source_root" || "$target" == "$source_root"/* ]]; then
  echo "Error: DESTINATION cannot be inside the source repository ($source_root)." >&2
  exit 2
fi
if [[ -n "$(git -C "$source_root" status --porcelain --untracked-files=no)" ]]; then
  echo "Warning: there are uncommitted changes; HEAD is exported without them." >&2
fi
revision="$(git -C "$source_root" rev-parse --short HEAD)"

mkdir -p -- "$destination"
git -C "$source_root" archive --format=tar HEAD | tar -x -C "$destination"

# Neither signing nor hooks from the global configuration: the commit only carries the identity above.
local_git=(git -C "$destination" -c commit.gpgsign=false -c core.hooksPath=/dev/null)
"${local_git[@]}" init -q -b main
"${local_git[@]}" add -A
if ! python3 "$destination/scripts/check_private.py" "$destination"; then
  echo "Error: the copy may contain personal data; no commit was made." >&2
  echo "Fix it in the source repository and delete $destination before trying again." >&2
  exit 1
fi
"${local_git[@]}" commit -q -m "$MESSAGE"

echo "Done: $destination has a single commit with the tree of $revision,"
echo "authored by $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>."
echo "To publish it: create the repository on GitHub, then"
echo "  git -C \"$destination\" remote add origin <url> && git -C \"$destination\" push -u origin main"
