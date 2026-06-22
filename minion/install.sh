#!/usr/bin/env bash
# DokOps Minion Installer
# Usage: curl http://your-dokops/minion/install.sh | bash -s -- --token=<key>
set -euo pipefail

DOKOPS_URL="${DOKOPS_URL:-}"
TOKEN=""
ORG=""
ENV=""

for arg in "$@"; do
  case "$arg" in
    --token=*) TOKEN="${arg#--token=}" ;;
    --url=*)   DOKOPS_URL="${arg#--url=}" ;;
    --org=*)   ORG="${arg#--org=}" ;;
    --env=*)   ENV="${arg#--env=}" ;;
  esac
done

if [ -z "$DOKOPS_URL" ]; then
  DOKOPS_URL="${DOKOPS_INSTALL_URL:-http://localhost:8000}"
fi

echo "[dokops-minion] Installing from $DOKOPS_URL"

# Pick the best available Python (3.8+)
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
  if command -v "$candidate" &>/dev/null; then
    ver=$("$candidate" -c "import sys; print(sys.version_info[:2] >= (3,8))" 2>/dev/null)
    if [ "$ver" = "True" ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "[dokops-minion] ERROR: Python 3.8+ not found. Install it and retry."
  exit 1
fi

echo "[dokops-minion] Using $PYTHON ($(${PYTHON} --version))"

# Install Python deps
$PYTHON -m pip install --quiet websockets psutil

# Download agent
mkdir -p /etc/dokops-minion
curl -fsSL "$DOKOPS_URL/minion/agent.py" -o /usr/local/bin/dokops-minion-agent.py
chmod +x /usr/local/bin/dokops-minion-agent.py
# Blueprint engine — must sit next to the agent so `import blueprint` resolves
curl -fsSL "$DOKOPS_URL/minion/blueprint.py" -o /usr/local/bin/blueprint.py

# Write config
cat > /etc/dokops-minion/config.env <<EOF
DOKOPS_URL=$DOKOPS_URL
MINION_TOKEN=$TOKEN
ORG=$ORG
ENV=$ENV
EOF

# Resolve full path for use in heredoc
PYTHON_BIN=$(command -v $PYTHON)

# Create systemd service
cat > /etc/systemd/system/dokops-minion.service <<EOF
[Unit]
Description=DokOps Minion Agent
After=network.target

[Service]
ExecStart=$PYTHON_BIN /usr/local/bin/dokops-minion-agent.py
Restart=always
RestartSec=5
EnvironmentFile=/etc/dokops-minion/config.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now dokops-minion
echo "[dokops-minion] Installed and started. Check status: systemctl status dokops-minion"
