$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidDir = Join-Path $ScriptDir ".pids"
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

function Test-Port {
    param([int]$Port)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("localhost", $Port)
        $tcp.Close()
        return $true
    } catch {
        return $false
    }
}

# --- ChromaDB (port 8001) ---
if (Test-Port 8001) {
    Write-Host "[OK] ChromaDB already running on port 8001"
} else {
    Write-Host "[..] Starting ChromaDB on port 8001..."
    $chromaData = Join-Path $ScriptDir "backend\chroma_data"
    $chromaLog  = Join-Path $PidDir "chroma.log"
    $proc = Start-Process -FilePath "chroma" `
        -ArgumentList "run", "--host", "0.0.0.0", "--port", "8001", "--path", $chromaData `
        -RedirectStandardOutput $chromaLog `
        -NoNewWindow -PassThru
    $proc.Id | Out-File (Join-Path $PidDir "chroma.pid") -Encoding ascii
    Write-Host "[OK] ChromaDB started (PID $($proc.Id))"
}

# --- Backend (port 8000) ---
if (Test-Port 8000) {
    Write-Host "[OK] Backend already running on port 8000"
} else {
    Write-Host "[..] Starting backend..."
    $backendDir = Join-Path $ScriptDir "backend"
    $backendLog = Join-Path $PidDir "backend.log"
    $proc = Start-Process -FilePath "uvicorn" `
        -ArgumentList "app.main:app", "--reload", "--port", "8000" `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $backendLog `
        -NoNewWindow -PassThru
    $proc.Id | Out-File (Join-Path $PidDir "backend.pid") -Encoding ascii
    Write-Host "[OK] Backend started (PID $($proc.Id))"
}

# --- Frontend (port 5173) ---
if (Test-Port 5173) {
    Write-Host "[OK] Frontend already running on port 5173"
} else {
    Write-Host "[..] Starting frontend..."
    $frontendDir = Join-Path $ScriptDir "frontend"
    $frontendLog = Join-Path $PidDir "frontend.log"
    $proc = Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev" `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput $frontendLog `
        -NoNewWindow -PassThru
    $proc.Id | Out-File (Join-Path $PidDir "frontend.pid") -Encoding ascii
    Write-Host "[OK] Frontend started (PID $($proc.Id))"
}

Write-Host ""
Write-Host "DokOps stack is up:"
Write-Host "  Frontend : http://localhost:5173"
Write-Host "  Backend  : http://localhost:8000"
Write-Host "  ChromaDB : http://localhost:8001"
Write-Host ""
Write-Host "Logs: $PidDir\*.log"
