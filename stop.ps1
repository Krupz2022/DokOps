$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidDir = Join-Path $ScriptDir ".pids"

function Stop-ServiceByPid {
    param([string]$Name)
    $pidFile = Join-Path $PidDir "$Name.pid"

    if (Test-Path $pidFile) {
        $id = [int](Get-Content $pidFile -Raw).Trim()
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[..] Stopping $Name (PID $id)..."
            Stop-Process -Id $id -Force
            Write-Host "[OK] $Name stopped"
        } else {
            Write-Host "[~]  $Name (PID $id) was not running"
        }
        Remove-Item $pidFile -Force
    } else {
        Write-Host "[~]  No PID file for $Name - skipping"
    }
}

Stop-ServiceByPid "frontend"
Stop-ServiceByPid "backend"
Stop-ServiceByPid "chroma"

Write-Host ""
Write-Host "DokOps stack stopped."
