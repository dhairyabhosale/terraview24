#!/usr/bin/env bash
# Download a pinned actionlint into tools/ (gitignored).
#
# Why actionlint and not a YAML parser: on attempt 1 a workflow file parsed
# cleanly under PyYAML and was rejected by GitHub Actions on every single push,
# reporting only "workflow file issue". The cause was a YAML key with nothing
# but a comment under it, which parses as null. `env:` followed by a comment is
# `env: null`. actionlint catches exactly that. See ARCHITECTURE.md section 9.
#
# Pinned on purpose: a linter that updates itself turns an unrelated push into
# a surprise failure.
#
# Usage:
#   scripts/get-actionlint.sh            # download if missing
#   scripts/get-actionlint.sh --force    # re download
#
# Used by developers locally and by .github/workflows/lint-workflows.yml, so
# both run the same version.

set -euo pipefail

ACTIONLINT_VERSION="1.7.12"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="${REPO_ROOT}/tools"

case "$(uname -s)" in
  Linux*)             OS="linux" ;  EXT="tar.gz" ; BIN="actionlint"     ;;
  Darwin*)            OS="darwin" ; EXT="tar.gz" ; BIN="actionlint"     ;;
  MINGW*|MSYS*|CYGWIN*) OS="windows" ; EXT="zip" ; BIN="actionlint.exe" ;;
  *) echo "unsupported platform: $(uname -s)" >&2 ; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) echo "unsupported architecture: $(uname -m)" >&2 ; exit 1 ;;
esac

TARGET="${TOOLS_DIR}/${BIN}"

if [[ "${1:-}" != "--force" && -x "${TARGET}" ]]; then
  echo "actionlint already present: ${TARGET}"
  "${TARGET}" --version
  exit 0
fi

ASSET="actionlint_${ACTIONLINT_VERSION}_${OS}_${ARCH}.${EXT}"
URL="https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${ASSET}"

mkdir -p "${TOOLS_DIR}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "downloading ${URL}"
curl -fsSL "${URL}" -o "${WORK}/${ASSET}"

if [[ "${EXT}" == "zip" ]]; then
  unzip -q -o "${WORK}/${ASSET}" -d "${WORK}"
else
  tar -xzf "${WORK}/${ASSET}" -C "${WORK}"
fi

mv "${WORK}/${BIN}" "${TARGET}"
chmod +x "${TARGET}"

echo "installed ${TARGET}"
"${TARGET}" --version
