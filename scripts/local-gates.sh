#!/usr/bin/env bash
#
# The gate set, locally, in the same order as .github/workflows/ci.yml.
# Run from the repo root:   ./scripts/local-gates.sh
#
# Tool versions are NOT hardcoded here (dev rule 19). They are parsed out of
# ci.yml, so bumping a pin in one file moves local and CI together. If this
# script installs a different version than CI runs, that is a bug in the
# parsing below, not something to work around by pinning twice.
#
# NOT COVERED by this script, and why:
#   hassfest  - a containerized Home Assistant action; there is no supported
#               standalone invocation. It only ever fails on manifest edits.
#   hacs      - likewise a container action. Fails only on repo-structure or
#               hacs.json changes, or on repository metadata such as topics,
#               which live in GitHub settings rather than in the repo.
# Both are cheap and run on every push. If you touched manifest.json, hacs.json
# or moved files around, push to a branch and read those two jobs rather than
# assuming this script covered you.
#
# Everything else here is byte-for-byte the same check CI runs.

set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
CI_FILE=".github/workflows/ci.yml"
VENV=".venv-gates"

if [[ ! -f "$CI_FILE" ]]; then
  echo "FATAL: $CI_FILE not found. Run this as ./scripts/local-gates.sh from the repo root." >&2
  exit 1
fi

pin() {
  # Read `  NAME: "value"` out of the ci.yml env block.
  local name="$1" value
  value="$(grep -E "^[[:space:]]+${name}:" "$CI_FILE" | head -1 | sed -E 's/.*:[[:space:]]*"?([^"]+)"?[[:space:]]*$/\1/')"
  if [[ -z "$value" ]]; then
    echo "FATAL: could not read ${name} from ${CI_FILE} (rule 19)" >&2
    exit 1
  fi
  printf '%s' "$value"
}

PYTHON_VERSION="$(pin PYTHON_VERSION)"
RUFF_VERSION="$(pin RUFF_VERSION)"
MYPY_VERSION="$(pin MYPY_VERSION)"
GITLEAKS_VERSION="$(pin GITLEAKS_VERSION)"
PHCC_VERSION="$(pin PHCC_VERSION)"

echo "pins from ${CI_FILE}: python=${PYTHON_VERSION} ruff=${RUFF_VERSION} mypy=${MYPY_VERSION} phcc=${PHCC_VERSION} gitleaks=${GITLEAKS_VERSION}"

PY="python${PYTHON_VERSION}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "FATAL: ${PY} not on PATH." >&2
  echo "Home Assistant ${PHCC_VERSION} requires Python ${PYTHON_VERSION}; an older" >&2
  echo "interpreter will fail to resolve the dependency and give you a confusing error." >&2
  exit 1
fi

STAMP="${VENV}/.pins"
WANT="${RUFF_VERSION} ${MYPY_VERSION} ${PHCC_VERSION}"
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$WANT" ]]; then
  echo "==> creating ${VENV} at the pinned versions (first run takes a few minutes)"
  rm -rf "$VENV"
  "$PY" -m venv "$VENV"
  "${VENV}/bin/pip" install -q --upgrade pip
  "${VENV}/bin/pip" install -q \
    "ruff==${RUFF_VERSION}" \
    "mypy==${MYPY_VERSION}" \
    "pytest-homeassistant-custom-component==${PHCC_VERSION}"
  printf '%s' "$WANT" > "$STAMP"
fi
BIN="${REPO_ROOT}/${VENV}/bin"

FAILED=()
gate() {
  local name="$1"; shift
  echo
  echo "==> ${name}"
  if "$@"; then
    echo "    ${name}: PASS"
  else
    echo "    ${name}: FAIL"
    FAILED+=("$name")
  fi
}

gate "lint (ruff check)"  "${BIN}/ruff" check custom_components scripts tests
gate "lint (ruff format)" "${BIN}/ruff" format --check --diff custom_components scripts tests
gate "consistency"        "${BIN}/python" scripts/check-consistency.py
gate "typecheck"          "${BIN}/mypy" custom_components/pelican
gate "tests"              "${BIN}/pytest" --cov=custom_components.pelican --cov-report=term-missing

# gitleaks last: it is the slowest and the one most likely to be a false
# positive, and a finding here needs a human decision rather than a quick fix.
#
# NOTE: this is STRICTER than CI on a fresh clone only if your local history
# differs. Both scan full history via `detect --source .`.
GITLEAKS_BIN="${VENV}/gitleaks"
if [[ ! -x "$GITLEAKS_BIN" ]]; then
  echo
  echo "==> fetching gitleaks ${GITLEAKS_VERSION}"
  curl -sSfL \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    | tar -xz -C "$VENV" gitleaks
fi
gate "gitleaks" "$GITLEAKS_BIN" detect --source . --redact --verbose

echo
if (( ${#FAILED[@]} )); then
  echo "GATES FAILED: ${FAILED[*]}"
  echo "hassfest and hacs were not run here \u2014 see the header if you touched manifest.json or hacs.json."
  exit 1
fi

echo "ALL LOCAL GATES PASSED"
echo "Still unverified locally: hassfest, hacs. Read those two jobs after pushing."
