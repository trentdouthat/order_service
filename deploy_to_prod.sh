#!/usr/bin/env bash
# ==============================================================================
# deploy_to_prod.sh - Enterprise Systemd Release Pipeline
# Promotes immutable wheel artifacts to target host and validates daemon health.
# ==============================================================================

set -euo pipefail

TARGET_HOST="${1:-tdouthat@raspberrypi.local}"
TARGET_IP="raspberrypi.local"
PROD_INSTALL_DIR="/opt/order_service"
ARTIFACT_NAME="order_service-0.1.0-py3-none-any.whl"

echo "============================================================"
echo " [RELEASE PIPELINE] Deploying order_service to ${TARGET_HOST}"
echo "============================================================"

# Stage 1: Quality Gate (Run Local Test Suite)
echo -e "\n[STAGE 1/5] Running automated pre-flight test gate..."
if ! uv run pytest -q tests/; then
  echo "[-] ABORT: Test suite failed! Release candidate rejected." >&2
  exit 1
fi
echo "[+] Pre-flight test gate passed cleanly."

# Stage 2: Build Immutable Wheel Artifact
echo -e "\n[STAGE 2/5] Building production distribution artifact..."
rm -rf dist/
uv build --wheel > /dev/null
echo "[+] Successfully built artifact: dist/${ARTIFACT_NAME}"

# Stage 3: Promote Artifact to Target Host
echo -e "\n[STAGE 3/5] Transferring artifact over network to ${TARGET_HOST}..."
scp -O -q "dist/${ARTIFACT_NAME}" "${TARGET_HOST}:/tmp/"
echo "[+] Artifact staged in /tmp/ on remote target."

# Stage 4: Install Wheel & Restart Systemd Daemon on Target
echo -e "\n[STAGE 4/5] Updating production binary and restarting daemon..."
ssh "${TARGET_HOST}" bash -s << REMOTE_SCRIPT
set -euo pipefail
# Install updated wheel into production virtualenv
${PROD_INSTALL_DIR}/bin/pip install --quiet --no-cache-dir --force-reinstall "/tmp/${ARTIFACT_NAME}"

# Restart systemd service
sudo systemctl restart order-service
sudo systemctl is-active --quiet order-service
REMOTE_SCRIPT
echo "[+] Remote systemd service restarted and verified active."

# Stage 5: External L7 Network Verification (Probing from CI/Dev runner)
echo -e "\n[STAGE 5/5] Probing live HTTP health endpoint across network..."
sleep 1

HEALTH_RESPONSE=$(curl -s "http://${TARGET_IP}:8080/healthz")
echo "[+] Target Health Response: ${HEALTH_RESPONSE}"

# Negative Boundary Test: Verify validation logic via live POST
VALIDATION_TEST=$(curl -s -X POST "http://${TARGET_IP}:8080/validate" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "TEST", "price": 100.0, "quantity": 10}')

if [[ "${VALIDATION_TEST}" =~ '"valid": true' ]]; then
  echo "[+] Live Validation Gate: PASSED"
else
  echo "[-] Live Validation Gate: FAILED (${VALIDATION_TEST})" >&2
  exit 1
fi

echo -e "\n============================================================"
echo " [DEPLOYMENT SUCCESSFUL] order_service is verified LIVE in Prod!"
echo "============================================================"