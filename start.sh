#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/.pids"
mkdir -p "$PID_DIR"

check_port() {
  nc -z localhost "$1" 2>/dev/null
}

# --- ChromaDB (port 8001) ---
if check_port 8001; then
  echo "[✓] ChromaDB already running on port 8001"
else
  echo "[→] Starting ChromaDB on port 8001..."
  (
    chroma run --host 0.0.0.0 --port 8001 \
      --path "$SCRIPT_DIR/backend/chroma_data" \
      >> "$PID_DIR/chroma.log" 2>&1
  ) &
  echo $! > "$PID_DIR/chroma.pid"
  echo "[✓] ChromaDB started (PID $(cat "$PID_DIR/chroma.pid"))"
fi

# --- Backend (port 8000) ---
if check_port 8000; then
  echo "[✓] Backend already running on port 8000"
else
  echo "[→] Starting backend..."
  (
    cd "$SCRIPT_DIR/backend"
    uvicorn app.main:app --reload --port 8000 >> "$PID_DIR/backend.log" 2>&1
  ) &
  echo $! > "$PID_DIR/backend.pid"
  echo "[✓] Backend started (PID $(cat "$PID_DIR/backend.pid"))"
fi

# --- Frontend (port 5173) ---
if check_port 5173; then
  echo "[✓] Frontend already running on port 5173"
else
  echo "[→] Starting frontend..."
  (
    cd "$SCRIPT_DIR/frontend"
    npm run dev >> "$PID_DIR/frontend.log" 2>&1
  ) &
  echo $! > "$PID_DIR/frontend.pid"
  echo "[✓] Frontend started (PID $(cat "$PID_DIR/frontend.pid"))"
fi

echo ""
echo "DokOps stack is up:"
echo "  Frontend : http://localhost:5173"
echo "  Backend  : http://localhost:8000"
echo "  ChromaDB : http://localhost:8001"
echo ""
echo "Logs: $PID_DIR/*.log"
