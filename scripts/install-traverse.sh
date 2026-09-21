#!/bin/sh
set -eu

repository=abrakjamson/Traverse
version=${1:-}
install_directory=${TRAVERSE_INSTALL_DIR:-"$HOME/.local/bin"}
platform=$(uname -s)
architecture=$(uname -m)

case "$platform-$architecture" in
  Linux-x86_64)
    asset=traverse-linux-x64
    ;;
  Darwin-x86_64)
    asset=traverse-macos-x64
    ;;
  Darwin-arm64)
    asset=traverse-macos-arm64
    ;;
  *)
    echo "The current Traverse release does not support $platform/$architecture." >&2
    exit 1
    ;;
esac

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required to download this private repository's release assets." >&2
  exit 1
fi

temporary_directory=$(mktemp -d "${TMPDIR:-/tmp}/traverse-install.XXXXXX")
trap 'rm -rf "$temporary_directory"' EXIT HUP INT TERM

if [ -n "$version" ]; then
  gh release download "$version" \
    --repo "$repository" \
    --pattern "$asset" \
    --pattern SHA256SUMS \
    --dir "$temporary_directory" \
    --clobber
else
  gh release download \
    --repo "$repository" \
    --pattern "$asset" \
    --pattern SHA256SUMS \
    --dir "$temporary_directory" \
    --clobber
fi

expected=$(
  awk -v asset="$asset" '$2 == asset { print $1 }' \
    "$temporary_directory/SHA256SUMS"
)
if [ -z "$expected" ]; then
  echo "The release checksum for $asset is missing." >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$temporary_directory/$asset" | awk '{ print $1 }')
elif command -v shasum >/dev/null 2>&1; then
  actual=$(shasum -a 256 "$temporary_directory/$asset" | awk '{ print $1 }')
else
  echo "No SHA-256 utility is available." >&2
  exit 1
fi
if [ "$actual" != "$expected" ]; then
  echo "Checksum verification failed for $asset." >&2
  exit 1
fi

mkdir -p "$install_directory"
install -m 755 "$temporary_directory/$asset" "$install_directory/traverse"
echo "Installed Traverse to $install_directory/traverse"

case ":$PATH:" in
  *":$install_directory:"*) ;;
  *)
    echo "Add $install_directory to PATH before installing or running the Copilot plugin."
    ;;
esac
