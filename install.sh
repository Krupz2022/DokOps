#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
skip() { echo -e "${YELLOW}[SKIP]${NC} $1 already installed"; }

# Must run as root or with sudo
if [[ $EUID -ne 0 ]]; then
  echo "Re-running with sudo..."
  exec sudo bash "$0" "$@"
fi

apt-get update -qq

# ── Docker ────────────────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
  skip "Docker ($(docker --version | awk '{print $3}' | tr -d ','))"
else
  echo "Installing Docker..."
  apt-get install -y -qq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | tee /etc/apt/sources.list.d/docker.list >/dev/null
  apt-get update -qq
  apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  # Add the invoking user (before sudo) to docker group
  REAL_USER="${SUDO_USER:-$USER}"
  usermod -aG docker "$REAL_USER"
  systemctl enable --now docker
  ok "Docker installed — log out and back in for group to take effect"
fi

# ── Docker Compose (plugin check) ────────────────────────────────────────────
if docker compose version &>/dev/null; then
  skip "Docker Compose ($(docker compose version --short))"
else
  echo "Installing docker-compose-plugin..."
  apt-get install -y -qq docker-compose-plugin
  ok "Docker Compose installed"
fi

# ── PostgreSQL ────────────────────────────────────────────────────────────────
if command -v psql &>/dev/null; then
  skip "PostgreSQL ($(psql --version | awk '{print $3}'))"
else
  echo "Installing PostgreSQL..."
  apt-get install -y -qq postgresql postgresql-contrib
  systemctl enable --now postgresql
  ok "PostgreSQL installed"
fi

# ── Python3 / pip ─────────────────────────────────────────────────────────────
if ! command -v pip3 &>/dev/null; then
  echo "Installing python3-pip..."
  apt-get install -y -qq python3-pip
  ok "pip3 installed"
fi

# ── ChromaDB (Docker container — preferred over bare pip) ────────────────────
CHROMA_DATA="/var/chroma"
if docker ps -a --format '{{.Names}}' | grep -q '^chromadb$'; then
  skip "ChromaDB container"
  # Ensure it's running
  if ! docker ps --format '{{.Names}}' | grep -q '^chromadb$'; then
    docker start chromadb
    ok "ChromaDB container started"
  fi
else
  echo "Installing ChromaDB (Docker container)..."
  mkdir -p "$CHROMA_DATA"
  docker pull chromadb/chroma:latest -q
  docker run -d \
    --name chromadb \
    --restart unless-stopped \
    -p 8001:8000 \
    -v "$CHROMA_DATA":/chroma/chroma \
    chromadb/chroma:latest
  ok "ChromaDB running on port 8001 (data at $CHROMA_DATA)"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Versions"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
docker     --version
docker     compose version
psql       --version
python3    -c "import sys; print('Python', sys.version.split()[0])"
echo "ChromaDB: $(docker inspect chromadb --format '{{.Config.Image}}' 2>/dev/null || echo 'not running')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
