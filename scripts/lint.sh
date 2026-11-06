#!/usr/bin/env bash
# Run every check CI runs, at the versions CI uses.
#
# WHY THIS EXISTS: on 2026-11-06 the local checks passed and CI failed twice in
# the same run, for two different reasons, both of which were version or
# environment drift rather than genuine disagreement:
#
#   1. ruff. Locally 0.17.4, in CI 0.8.4 (pinned in requirements-ci.txt). UP038
#      exists in 0.8.4 and not in later versions, so the local run was a
#      DIFFERENT linter that happened to share a name.
#   2. actionlint. It runs shellcheck over `run:` blocks only when a shellcheck
#      binary is on PATH, and silently skips those checks when there is none.
#      The runner has shellcheck; a Windows dev machine does not. So the local
#      run reported success in the same words as a strictly stronger check.
#
# Both failures said "green" locally. A local check that is weaker than CI while
# claiming the same result is worse than no local check, because it manufactures
# confidence. This script closes that gap by pinning versions and refusing to
# report success when a checker is missing.
#
# Usage:  bash scripts/lint.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# Keep these in step with requirements-ci.txt and lint-workflows.yml.
RUFF_VERSION="$(sed -n 's/^ruff==\(.*\)$/\1/p' requirements-ci.txt)"
PYTHON_VERSION="3.11"

FAILED=()
SKIPPED=()

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m    ok\033[0m\n'; }
bad()  { printf '\033[31m    FAILED\033[0m\n'; FAILED+=("$1"); }

# --- workflow linting -------------------------------------------------------

step "actionlint (with shellcheck, as CI has it)"
bash scripts/get-actionlint.sh >/dev/null 2>&1 || true
bash scripts/get-shellcheck.sh >/dev/null 2>&1 || true

ACTIONLINT="$(ls tools/actionlint tools/actionlint.exe 2>/dev/null | head -1)"
if [[ -z "${ACTIONLINT}" ]]; then
  echo "    actionlint is missing. Run: bash scripts/get-actionlint.sh"
  bad "actionlint (not installed)"
else
  # Put tools/ on PATH so actionlint finds the pinned shellcheck.
  export PATH="${REPO_ROOT}/tools:${PATH}"
  if ! command -v shellcheck >/dev/null 2>&1; then
    # Do NOT report success in this state. actionlint would exit 0 having
    # skipped the shellcheck rules, which is how SC2028 reached CI.
    echo "    shellcheck is missing, so actionlint would skip its shell checks."
    echo "    Run: bash scripts/get-shellcheck.sh"
    SKIPPED+=("actionlint shellcheck rules")
  fi
  if "${ACTIONLINT}" -color .github/workflows/*.yml; then ok; else bad "actionlint"; fi
fi

# --- python -----------------------------------------------------------------

if command -v uv >/dev/null 2>&1; then
  UV="uv"
elif python -m uv --version >/dev/null 2>&1; then
  UV="python -m uv"
else
  UV=""
fi

step "pytest on Python ${PYTHON_VERSION} (the version CI pins)"
if [[ -n "${UV}" ]]; then
  if ${UV} run --python "${PYTHON_VERSION}" --with pytest --with httpx --with pyyaml \
      --isolated python -m pytest tests/ -q; then ok; else bad "pytest"; fi
else
  echo "    uv not found, falling back to the local interpreter ($(python --version 2>&1))."
  echo "    This is NOT what CI runs. Install uv to match it."
  SKIPPED+=("pytest on ${PYTHON_VERSION}")
  if python -m pytest tests/ -q; then ok; else bad "pytest"; fi
fi

step "ruff ${RUFF_VERSION} (the version CI pins)"
if [[ -n "${UV}" ]]; then
  if ${UV} tool run "ruff@${RUFF_VERSION}" check pipeline/ scripts/ tests/; then ok; else bad "ruff"; fi
else
  echo "    uv not found. The local ruff is probably a different version to CI,"
  echo "    which is exactly how UP038 reached CI green locally."
  SKIPPED+=("ruff ${RUFF_VERSION}")
  if python -m ruff check pipeline/ scripts/ tests/; then ok; else bad "ruff"; fi
fi

step "no en or em dashes (ground rule 8)"
if python scripts/check_no_dashes.py; then ok; else bad "check_no_dashes"; fi

# --- javascript and typescript ---------------------------------------------

step "trigger Worker tests"
if (cd infra/trigger-worker && node --test "test/*.test.ts" >/dev/null 2>&1); then
  ok
else
  (cd infra/trigger-worker && node --test "test/*.test.ts")
  bad "trigger-worker tests"
fi

step "web tests and build (tsc AND vite build, both)"
if [[ -d web/node_modules ]]; then
  if (cd web && node --test "test/*.test.ts" >/dev/null 2>&1); then ok; else
    (cd web && node --test "test/*.test.ts"); bad "web tests"
  fi
  # tsc catches config errors that vite build passes over, so run both.
  if (cd web && npm run build >/dev/null 2>&1); then ok; else
    (cd web && npm run build); bad "web build"
  fi
else
  echo "    web/node_modules is absent. Run: npm --prefix web install"
  SKIPPED+=("web tests and build")
fi

# --- verdict ----------------------------------------------------------------

printf '\n\033[1m==> summary\033[0m\n'

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  printf '\033[33m    skipped or weakened:\033[0m\n'
  for s in "${SKIPPED[@]}"; do printf '      %s\n' "${s}"; done
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
  printf '\033[31m    failed:\033[0m\n'
  for f in "${FAILED[@]}"; do printf '      %s\n' "${f}"; done
  exit 1
fi

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  # Deliberately not a pass. A partial run must not read like a full one.
  printf '\033[33m    all checks that ran passed, but some were skipped or weakened.\033[0m\n'
  printf '\033[33m    This is NOT equivalent to CI green.\033[0m\n'
  exit 2
fi

printf '\033[32m    everything CI runs passed locally, at the versions CI uses.\033[0m\n'
