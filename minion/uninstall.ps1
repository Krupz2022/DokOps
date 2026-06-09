# DokOps Minion Windows Uninstaller
# Usage: powershell -ExecutionPolicy Bypass -Command "irm http://your-dokops:8000/minion/uninstall.ps1 | iex"
$TaskName   = "DokOps Minion Agent"
$InstallDir = "C:\ProgramData\DokOps\minion"

Write-Host "[dokops-minion] Stopping and removing Windows minion agent..."
Stop-ScheduledTask   -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
Write-Host "[dokops-minion] Uninstalled successfully."
