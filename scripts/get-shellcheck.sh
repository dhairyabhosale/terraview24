#!/usr/bin/env bash
# Download a pinned shellcheck into tools/ (gitignored).
#
# WHY THIS EXISTS, and it is not optional tidiness.
#
# actionlint runs shellcheck over every `run:` block, but ONLY if a shellcheck
# binary is on PATH. If one is absent it silently skips those checks and still
# exits 0. The GitHub runner image ships shellcheck; a Windows development
# machine does not.
#
# So on 2026-11-06 actionlint passed locally, the workflow was pushed, and CI
# failed on SC2028 in a `run:` block. The local check was a strictly weaker
# check that reported success in the same words as the strong one. That is
# worse than having no local check at all, because it manufactures confidence.
#
# Usage:
#   scripts/get-shellcheck.sh            # download if missing
#   scripts/get-shellcheck.sh --force    # re download

set -euo pipefail

SHELLCHECK_VERSION="0.11.0"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="${REPO_ROOT}/tools"

case "$(uname -s)" in
  Linux*)               OS="linux" ;  BIN="shellcheck"     ;;
  Darwin*)              OS="darwin" ; BIN="shellcheck"     ;;
  MINGW*|MSYS*|CYGWIN*) OS="windows" ; BIN="shellcheck.exe" ;;
  *) echo "unsupported platform: $(uname -s)" >&2 ; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ARCH="x86_64" ;;
  arm64|aarch64) ARCH="aarch64" ;;
  *) echo "unsupported architecture: $(uname -m)" >&2 ; exit 1 ;;
esac

TARGET="${TOOLS_DIR}/${BIN}"

if [[ "${1:-}" != "--force" && -x "${TARGET}" ]]; then
  echo "shellcheck already present: ${TARGET}"
  "${TARGET}" --version | head -2
  exit 0
fi

# The Windows release is a single zip with no architecture in the name.
if [[ "${OS}" == "windows" ]]; then
  ASSET="shellcheck-v${SHELLCHECK_VERSION}.zip"
else
  ASSET="shellcheck-v${SHELLCHECK_VERSION}.${OS}.${ARCH}.tar.xz"
fi

URL="https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/${ASSET}"

mkdir -p "${TOOLS_DIR}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "downloading ${URL}"
curl -fsSL "${URL}" -o "${WORK}/${ASSET}"

if [[ "${ASSET}" == *.zip ]]; then
  unzip -q -o "${WORK}/${ASSET}" -d "${WORK}"
else
  tar -xJf "${WORK}/${ASSET}" -C "${WORK}"
fi

# The archive layout differs between platforms, so find the binary rather than
# assuming a path.
FOUND="$(find "${WORK}" -type f -name "${BIN}" -print -quit)"
if [[ -z "${FOUND}" ]]; then
  echo "could not find ${BIN} inside ${ASSET}" >&2
  exit 1
fi

mv "${FOUND}" "${TARGET}"
chmod +x "${TARGET}"

echo "installed ${TARGET}"
"${TARGET}" --version | head -2
