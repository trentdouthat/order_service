#!/usr/bin/env bash
# ==============================================================================
# promote.sh - Enterprise Multi-Environment Atomic Promotion & Auto-Rollback
# Usage: ./promote.sh [version]  (Default: 0.1.0)
# ==============================================================================

set -euo pipefail

VERSION="${1:-0.1.0}"
STAGING_HOST="staging-samsung"
PROD_HOST="prod-rpi"
PORT="8080"

# Set to true to roll back the ENTIRE fleet if Prod fails.
# Set to false to leave Staging broken as a forensic crime scene.
FLEET_ROLLBACK=false

echo "======================================================================"
echo " [ENTERPRISE PROMOTION] Atomic Promotion Pipeline - Release v${VERSION}"
echo "======================================================================"

# ------------------------------------------------------------------------------
# Gate 1: Local Pre-flight Unit Tests
# ------------------------------------------------------------------------------
echo -e "\n[GATE 1/7] Running local pre-flight unit test suite..."
if ! uv run pytest -q tests/; then
  echo "[-] ABORT: Pre-flight unit test gate failed. Release candidate rejected." >&2
  exit 1
fi
echo "[+] Pre-flight unit tests PASSED."

# ------------------------------------------------------------------------------
# Gate 2: Build Deterministic Wheel Artifact
# ------------------------------------------------------------------------------
echo -e "\n[GATE 2/7] Compiling distribution wheel for v${VERSION}..."
rm -rf dist/
uv build --wheel > /dev/null
WHEEL_FILE="dist/order_service-${VERSION}-py3-none-any.whl"

if [[ ! -f "${WHEEL_FILE}" ]]; then
  WHEEL_FILE=$(ls dist/*.whl | head -n 1)
fi
echo "[+] Artifact ready: ${WHEEL_FILE}"

# ------------------------------------------------------------------------------
# Gate 3: Atomic Staging Deployment
# ------------------------------------------------------------------------------
echo -e "\n[GATE 3/7] Deploying v${VERSION} to STAGING (${STAGING_HOST}) via atomic symlink..."
ansible-playbook -i inventory.ini deploy_atomic.yml --limit staging -e "version=${VERSION}" > /dev/null
echo "[+] Staging symlink cutover complete."

# ------------------------------------------------------------------------------
# Gate 4: Staging Smoke & Boundary Verification Gate
# ------------------------------------------------------------------------------
echo -e "\n[GATE 4/7] Executing integration & boundary gate on Staging (${STAGING_HOST}:${PORT})..."
STAGING_HEALTH=$(curl -s "http://${STAGING_HOST}:${PORT}/healthz" || echo "")
echo "    -> Staging Health: ${STAGING_HEALTH}"

POS_TEST=$(curl -s -X POST "http://${STAGING_HOST}:${PORT}/validate" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "MSFT", "price": 425.50, "quantity": 100}' || echo "")

NEG_TEST=$(curl -s -X POST "http://${STAGING_HOST}:${PORT}/validate" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "bad_ticker", "price": 10.0, "quantity": 5}' || echo "")

if [[ "${POS_TEST}" =~ '"valid": true' ]] && [[ "${NEG_TEST}" =~ '"valid": false' ]]; then
  echo "[+] Staging boundary verification PASSED."
else
  echo -e "\n[-] CRITICAL: Staging smoke check FAILED! Triggering staging rollback..." >&2
  ansible-playbook -i inventory.ini rollback.yml --limit staging
  echo "[-] Staging rolled back. Promotion halted. Production was NOT touched." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Gate 5: Atomic Production Promotion
# ------------------------------------------------------------------------------
echo -e "\n[GATE 5/7] PROMOTING v${VERSION} to PRODUCTION (${PROD_HOST}) via atomic symlink..."
ansible-playbook -i inventory.ini deploy_atomic.yml --limit prod -e "version=${VERSION}" > /dev/null
echo "[+] Production symlink cutover complete."

# ------------------------------------------------------------------------------
# Gate 6: Production Live Verification & Auto-Rollback Gate
# ------------------------------------------------------------------------------
echo -e "\n[GATE 6/7] Verifying live Production service (${PROD_HOST}:${PORT})..."
PROD_HEALTH=$(curl -s "http://${PROD_HOST}:${PORT}/healthz" || echo "")
echo "    -> Production Health: ${PROD_HEALTH}"

PROD_CHECK=$(curl -s -X POST "http://${PROD_HOST}:${PORT}/validate" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "SPY", "price": 580.00, "quantity": 50}' || echo "")

if [[ "${PROD_CHECK}" =~ '"valid": true' ]]; then
  echo "[+] Production Verification Gate: PASSED"
else
  echo -e "\n[-] CRITICAL: Production check FAILED! Triggering IMMEDIATE ROLLBACK..." >&2
  if [[ "${FLEET_ROLLBACK}" == true ]]; then
    ansible-playbook -i inventory.ini rollback.yml
  else
    ansible-playbook -i inventory.ini rollback.yml --limit prod
  fi
  echo "[-] Target(s) reverted to previous stable release." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# Gate 7: Automated Release Retention & Disk Hygiene
# ------------------------------------------------------------------------------
echo -e "\n[GATE 7/7] Enforcing release retention policy (Purging stale versions)..."
ansible-playbook -i inventory.ini cleanup_old_releases.yml > /dev/null
echo "[+] Retention policy enforced across fleet."

echo -e "\n======================================================================"
echo " [SUCCESS] Release v${VERSION} is LIVE on Staging & Production!"
echo "======================================================================"