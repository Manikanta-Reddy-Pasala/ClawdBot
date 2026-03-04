#!/bin/bash
set -euo pipefail

SERVER="77.42.68.16"
REMOTE_DIR="/opt/clawdbot"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== ClawdBot v2 Deployment ==="

# Step 1: Install Python & deps on server
echo "[1/8] Setting up server packages..."
ssh root@${SERVER} 'apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip > /dev/null 2>&1 && echo "Packages installed"'

# Step 2: Create directory and venv
echo "[2/8] Creating directory and virtual environment..."
ssh root@${SERVER} "mkdir -p ${REMOTE_DIR}/repos && python3 -m venv ${REMOTE_DIR}/venv"

# Step 3: Copy bot files
echo "[3/8] Copying bot files..."
scp "${LOCAL_DIR}/requirements.txt" \
    "${LOCAL_DIR}/config.py" \
    "${LOCAL_DIR}/task_queue.py" \
    "${LOCAL_DIR}/context_manager.py" \
    "${LOCAL_DIR}/executor.py" \
    "${LOCAL_DIR}/agents.py" \
    "${LOCAL_DIR}/bot.py" \
    "${LOCAL_DIR}/tools.py" \
    "${LOCAL_DIR}/shell_executor.py" \
    "${LOCAL_DIR}/api_server.py" \
    "${LOCAL_DIR}/progress_broadcaster.py" \
    root@${SERVER}:${REMOTE_DIR}/

scp "${LOCAL_DIR}/clawdbot.service" root@${SERVER}:/etc/systemd/system/

# Step 4: Copy devops module
echo "[4/8] Copying devops module..."
ssh root@${SERVER} "mkdir -p ${REMOTE_DIR}/devops"
scp "${LOCAL_DIR}"/devops/*.py root@${SERVER}:${REMOTE_DIR}/devops/

# Step 5: Copy static dashboard files
echo "[5/8] Copying dashboard files..."
if [ -d "${LOCAL_DIR}/static" ]; then
    ssh root@${SERVER} "mkdir -p ${REMOTE_DIR}/static/js ${REMOTE_DIR}/static/css"
    scp -r "${LOCAL_DIR}"/static/* root@${SERVER}:${REMOTE_DIR}/static/ 2>/dev/null || true
fi

# Copy .env only if it doesn't exist on server (don't overwrite secrets)
ssh root@${SERVER} "test -f ${REMOTE_DIR}/.env || echo 'NO_ENV'" | grep -q "NO_ENV" && {
    echo "No .env file on server. Copying template..."
    scp "${LOCAL_DIR}/.env.template" root@${SERVER}:${REMOTE_DIR}/.env
    echo "*** IMPORTANT: Edit /opt/clawdbot/.env on the server with your API keys! ***"
}

# Step 6: Remove old files that are no longer needed
echo "[6/8] Cleaning up old files..."
ssh root@${SERVER} "rm -f ${REMOTE_DIR}/ai_router.py ${REMOTE_DIR}/claude_client.py ${REMOTE_DIR}/conversation_store.py ${REMOTE_DIR}/gemini_client.py ${REMOTE_DIR}/gmail_tools.py ${REMOTE_DIR}/job_tools.py ${REMOTE_DIR}/job_profile.json"

# Step 7: Install Python dependencies
echo "[7/8] Installing Python dependencies..."
ssh root@${SERVER} "${REMOTE_DIR}/venv/bin/pip install -q -r ${REMOTE_DIR}/requirements.txt"

# Step 8: Sync context files (CLAUDE.md + memory)
echo "[8/8] Syncing context files..."
bash "${LOCAL_DIR}/sync-context.sh" 2>/dev/null || echo "Context sync skipped (sync-context.sh not found or failed)"

# Enable and start service
echo "Configuring systemd service..."
ssh root@${SERVER} "systemctl daemon-reload && systemctl enable clawdbot && systemctl restart clawdbot"

echo ""
echo "=== Deployment complete ==="
echo "Check status:    ssh root@${SERVER} 'systemctl status clawdbot'"
echo "View logs:       ssh root@${SERVER} 'journalctl -u clawdbot -f'"
echo "Dashboard:       http://${SERVER}:8000/"
echo "API health:      http://${SERVER}:8000/api/v1/health"
