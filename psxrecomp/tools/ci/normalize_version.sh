#!/usr/bin/env bash
# Normalize a release version string to X.Y.Z (strip leading v / whitespace).
#
# Usage:
#   normalize_version.sh <raw>                 # prints VERSION=… TAG=…
#   normalize_version.sh --write VERSION <raw> # also writes VERSION file
#
# When GITHUB_OUTPUT is set, appends version= and tag=.
set -euo pipefail

WRITE=""
RAW=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --write) WRITE="${2:?}"; shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      RAW="$1"
      shift
      ;;
  esac
done

if [[ -z "${RAW}" ]]; then
  echo "usage: $0 [--write VERSION] <raw-version>" >&2
  exit 2
fi

RAW="$(printf '%s' "${RAW}" | tr -d '[:space:]')"
VER="${RAW#v}"
if [[ ! "${VER}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.+-][A-Za-z0-9.+-]*)?$ ]]; then
  echo "error: invalid version '${RAW}' (want X.Y.Z or vX.Y.Z)" >&2
  exit 1
fi
TAG="v${VER}"

echo "VERSION=${VER}"
echo "TAG=${TAG}"

if [[ -n "${WRITE}" ]]; then
  printf '%s\n' "${VER}" >"${WRITE}"
fi
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "version=${VER}" >>"${GITHUB_OUTPUT}"
  echo "tag=${TAG}" >>"${GITHUB_OUTPUT}"
fi
