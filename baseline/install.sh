#!/usr/bin/env bash
set -euo pipefail
pkg="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="${1:-$PWD}"
if [[ ! -f "$root/ns3" || ! -d "$root/scratch" ]]; then
  echo 'Usage: bash install.sh /absolute/path/to/ns-3.44' >&2; exit 1
fi
for name in rr-core.h rr-wifi-manager.h rr-rate-adaptation.cc; do
  if [[ -e "$root/scratch/$name" ]]; then
    echo "Already exists: $root/scratch/$name. Review/remove that file before installing." >&2; exit 1
  fi
done
for name in rr-core.h rr-wifi-manager.h rr-rate-adaptation.cc; do
  cp -- "$pkg/$name" "$root/scratch/$name"
done
testbin="$(mktemp)"
trap 'rm -f -- "$testbin"' EXIT
g++ -std=c++17 -Wall -Wextra -pedantic "$pkg/core-tests.cc" -o "$testbin"
"$testbin"
cd -- "$root"
./ns3 build rr-rate-adaptation
echo 'Installed and built. Run the smoke command from README.md.'
