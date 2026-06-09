#!/usr/bin/env bash
# DokOps Minion Uninstaller
# Usage: curl http://your-dokops/minion/uninstall.sh | bash
set -euo pipefail

echo "[dokops-minion] Stopping and disabling service..."
systemctl stop dokops-minion 2>/dev/null || true
systemctl disable dokops-minion 2>/dev/null || true

echo "[dokops-minion] Removing service file..."
rm -f /etc/systemd/system/dokops-minion.service
systemctl daemon-reload

echo "[dokops-minion] Removing agent and config..."
rm -f /usr/local/bin/dokops-minion-agent.py
rm -rf /etc/dokops-minion

echo "[dokops-minion] Uninstalled successfully."
