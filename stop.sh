#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"

stop_service() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"

  if [[ -f "$pid_file" ]]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      echo "[→] Stopping $name (PID $pid)..."
      kill "$pid"
      echo "[✓] $name stopped"
    else
      echo "[~] $name (PID $pid) was not running"
    fi
    rm -f "$pid_file"
  else
    echo "[~] No PID file for $name — skipping"
  fi
}

stop_service "frontend"
stop_service "backend"
stop_service "chroma"

echo ""
echo "DokOps stack stopped."
