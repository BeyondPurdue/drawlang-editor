#!/bin/bash
# ============================================================================
# deploy-drawlang.sh — auto-deploy script for editor.drawlang.com
#
# Runs every 2 minutes via drawlang-deploy.timer. Idempotent: if there's
# nothing new on origin/main, it exits without touching the running service.
#
# Reference source lives in-repo at deploy/deploy-drawlang.sh.
# The active copy on the server is at /usr/local/bin/deploy-drawlang.
# To update the server copy after editing this file:
#   sudo cp /var/www/drawlang-editor/deploy/deploy-drawlang.sh \
#           /usr/local/bin/deploy-drawlang
#   sudo chmod +x /usr/local/bin/deploy-drawlang
#
# Modeled on the SecureDCS bmg-kb-deploy pattern.
# ============================================================================

set -euo pipefail

APP_DIR="/var/www/drawlang-editor"
VENV="${APP_DIR}/venv"
BRANCH="main"
SERVICE="drawlang-editor.service"
LOG_TAG="deploy-drawlang"

log() { logger -t "${LOG_TAG}" -- "$*"; echo "[${LOG_TAG}] $*"; }

cd "${APP_DIR}"

# 1. Fetch and check for updates ---------------------------------------------
sudo -u www-data git fetch --quiet origin "${BRANCH}"

LOCAL="$(sudo -u www-data git rev-parse HEAD)"
REMOTE="$(sudo -u www-data git rev-parse "origin/${BRANCH}")"

if [ "${LOCAL}" = "${REMOTE}" ]; then
    # Nothing new — quiet exit (systemd journal stays clean).
    exit 0
fi

log "Update: ${LOCAL:0:8} → ${REMOTE:0:8}"

# 2. Detect changes that require special handling ----------------------------
CHANGED_FILES="$(sudo -u www-data git diff --name-only "${LOCAL}" "${REMOTE}")"

NEEDS_PIP_INSTALL=0
NEEDS_UNIT_RELOAD=0

if echo "${CHANGED_FILES}" | grep -qE '^(pyproject\.toml|requirements.*\.txt)$'; then
    NEEDS_PIP_INSTALL=1
    log "pyproject.toml changed — will reinstall Python deps"
fi

if echo "${CHANGED_FILES}" | grep -qE '^deploy/.*\.(service|timer)$'; then
    NEEDS_UNIT_RELOAD=1
    log "systemd unit changed — will reload daemon"
fi

# 3. Fast-forward pull -------------------------------------------------------
sudo -u www-data git pull --ff-only --quiet origin "${BRANCH}"

# 4. Reinstall Python dependencies if needed ---------------------------------
if [ "${NEEDS_PIP_INSTALL}" -eq 1 ]; then
    sudo -u www-data "${VENV}/bin/pip" install --quiet --upgrade pip
    sudo -u www-data "${VENV}/bin/pip" install --quiet -e ".[editor]"
    log "pip install completed"
fi

# 5. Reload systemd if unit files changed ------------------------------------
if [ "${NEEDS_UNIT_RELOAD}" -eq 1 ]; then
    # Copy updated unit files into /etc/systemd/system
    for unit in drawlang-editor.service drawlang-deploy.service drawlang-deploy.timer; do
        if [ -f "${APP_DIR}/deploy/${unit}" ]; then
            cp "${APP_DIR}/deploy/${unit}" "/etc/systemd/system/${unit}"
        fi
    done
    systemctl daemon-reload
    log "systemd daemon-reload completed"
fi

# 6. Restart the editor service ----------------------------------------------
systemctl restart "${SERVICE}"

# 7. Health check ------------------------------------------------------------
sleep 2
if systemctl is-active --quiet "${SERVICE}"; then
    log "Deployed ${REMOTE:0:8} — service active"
else
    log "ERROR: ${SERVICE} failed to start after deploy of ${REMOTE:0:8}"
    systemctl status "${SERVICE}" --no-pager | head -20 | logger -t "${LOG_TAG}"
    exit 1
fi
