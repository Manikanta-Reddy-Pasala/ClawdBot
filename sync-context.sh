#!/bin/bash
set -euo pipefail

SERVER="77.42.68.16"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_CLAWDBOT="/opt/clawdbot"

echo "=== Syncing context files to ClawdBot VM ==="

# Sync CLAUDE.md to repos directory on server
if [ -f "${REPO_ROOT}/CLAUDE.md" ]; then
    echo "[1/2] Syncing CLAUDE.md..."
    ssh root@${SERVER} "mkdir -p ${REMOTE_CLAWDBOT}/repos/codeRepo"
    scp "${REPO_ROOT}/CLAUDE.md" root@${SERVER}:${REMOTE_CLAWDBOT}/repos/codeRepo/CLAUDE.md
    echo "  -> Copied to ${REMOTE_CLAWDBOT}/repos/codeRepo/CLAUDE.md"
else
    echo "[1/2] CLAUDE.md not found at ${REPO_ROOT}/CLAUDE.md, skipping"
fi

# Sync memory files
MEMORY_DIR="${REPO_ROOT}/.claude/projects/-Users-manip-Documents-codeRepo/memory"
if [ -d "${MEMORY_DIR}" ]; then
    echo "[2/2] Syncing memory files..."
    ssh root@${SERVER} "mkdir -p ${REMOTE_CLAWDBOT}/.claude/memory"
    scp -r "${MEMORY_DIR}"/* root@${SERVER}:${REMOTE_CLAWDBOT}/.claude/memory/ 2>/dev/null || true
    echo "  -> Copied memory files to ${REMOTE_CLAWDBOT}/.claude/memory/"
else
    echo "[2/2] Memory directory not found at ${MEMORY_DIR}, skipping"
fi

echo "=== Context sync complete ==="
