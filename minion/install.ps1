# DokOps Minion Windows Installer
# Usage:  powershell -ExecutionPolicy Bypass -Command "irm http://your-dokops:8000/minion/install.ps1 | iex"
# Params: & ([scriptblock]::Create((irm 'http://your-dokops:8000/minion/install.ps1'))) -Url 'http://...' -Token '...'
param(
    [string]$Url   = "http://localhost:8000",
    [string]$Token = "",
    [string]$Key   = "",
    [string]$Org   = "",
    [string]$Env   = ""
)

$ErrorActionPreference = "Stop"
$InstallDir = "C:\ProgramData\DokOps\minion"
$AgentScript = "$InstallDir\agent.py"
$ConfigFile  = "$InstallDir\config.env"
$TaskName    = "DokOps Minion Agent"

Write-Host "[dokops-minion] Installing from $Url"

# Find Python 3.8+
$Python = $null
foreach ($candidate in @("python3.13","python3.12","python3.11","python3.10","python3.9","python3.8","python3","python")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        $ver = & $found.Source -c "import sys; print(sys.version_info[:2] >= (3,8))" 2>$null
        if ($ver -eq "True") { $Python = $found.Source; break }
    }
}
if (-not $Python) {
    Write-Error "[dokops-minion] Python 3.8+ not found. Install from https://python.org and retry."
    exit 1
}
Write-Host "[dokops-minion] Using Python: $Python"

# Install Python deps — download wheels via Invoke-WebRequest (uses Windows HTTP, bypasses pip network issues)
$baseUrl  = $Url.TrimEnd('/')
$wheelDir = "$env:TEMP\dokops-wheels"
New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
$pyTag = & $Python -c "import sys; print('cp{}{}'.format(*sys.version_info[:2]))"
$arch  = if ([System.Environment]::Is64BitOperatingSystem) { "win_amd64" } else { "win32" }

foreach ($pkg in @("websockets", "psutil")) {
    try {
        Write-Host "[dokops-minion] Fetching wheel index for $pkg..."
        $html = (Invoke-WebRequest "$baseUrl/minion/simple/$pkg/" -UseBasicParsing).Content
        # Try platform wheel first, fall back to universal
        $wheelUrl = $null
        $pyMinor  = [int]($pyTag -replace 'cp3','')
        $wheelUrl = $null

        # 1. Version-specific wheel: -cp313-cp313-win_amd64 (then cp312 fallback)
        foreach ($tag in @($pyTag, "cp3$($pyMinor - 1)")) {
            $hits = [regex]::Matches($html, "href=""([^""]+-${tag}-${tag}-${arch}[^""]*\.whl[^""]*)")
            if ($hits.Count -gt 0) { $wheelUrl = ($hits[$hits.Count - 1].Groups[1].Value -split '#')[0]; break }
        }

        # 2. Stable ABI wheel: -cp3XX-abi3-win_amd64 where XX <= pyMinor (e.g. cp36-abi3)
        if (-not $wheelUrl) {
            $hits = [regex]::Matches($html, "href=""([^""]*-cp3([0-9]+)-abi3-${arch}[^""]*\.whl[^""]*)")
            $compat = $hits | Where-Object { [int]$_.Groups[2].Value -le $pyMinor }
            if ($compat.Count -gt 0) { $wheelUrl = ($compat[$compat.Count - 1].Groups[1].Value -split '#')[0] }
        }

        # 3. Pure Python fallback
        if (-not $wheelUrl) {
            $hits = [regex]::Matches($html, "href=""([^""]*-py3-none-any[^""]*\.whl[^""]*)")
            if ($hits.Count -gt 0) { $wheelUrl = ($hits[$hits.Count - 1].Groups[1].Value -split '#')[0] }
        }
        if (-not $wheelUrl) { Write-Warning "[dokops-minion] No compatible wheel found for $pkg"; continue }
        # Decode the proxied URL to recover the real wheel filename
        $encodedPypiUrl = ($wheelUrl -split 'url=')[1]
        $realFileName   = [System.Uri]::UnescapeDataString($encodedPypiUrl).Split('/')[-1]
        $outFile = "$wheelDir\$realFileName"
        Write-Host "[dokops-minion] Downloading $pkg ($realFileName)..."
        Invoke-WebRequest $wheelUrl -OutFile $outFile -UseBasicParsing
        # Install into InstallDir\lib so SYSTEM can find it regardless of Python install type
        $libDir = "$InstallDir\lib"
        New-Item -ItemType Directory -Force -Path $libDir | Out-Null
        & $Python -m pip install --quiet --target $libDir $outFile
        Write-Host "[dokops-minion] Installed $pkg"
    } catch {
        Write-Warning "[dokops-minion] Failed to install ${pkg}: $_"
    }
}
Remove-Item $wheelDir -Recurse -Force -ErrorAction SilentlyContinue

# Create install dir and download agent
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Invoke-WebRequest -Uri "$Url/minion/agent.py" -OutFile $AgentScript -UseBasicParsing
# Blueprint engine — must sit next to the agent so `import blueprint` resolves
Invoke-WebRequest -Uri "$Url/minion/blueprint.py" -OutFile "$InstallDir\blueprint.py" -UseBasicParsing
Write-Host "[dokops-minion] Agent downloaded to $AgentScript"

# Write config (preserve existing MINION_ID if present)
$existingId = ""
if (Test-Path $ConfigFile) {
    $existingId = (Get-Content $ConfigFile | Where-Object { $_ -match "^MINION_ID=" }) -replace "^MINION_ID=",""
}
$config = "DOKOPS_URL=$Url`nMINION_TOKEN=$Token`nORG=$Org`nENV=$Env"
if ($Key)        { $config += "`nKEY=$Key" }
if ($existingId) { $config += "`nMINION_ID=$existingId" }
[System.IO.File]::WriteAllText($ConfigFile, $config, [System.Text.UTF8Encoding]::new($false))

# Register as Scheduled Task (SYSTEM account, restarts on failure, no time limit)
$action   = New-ScheduledTaskAction -Execute $Python -Argument $AgentScript
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "[dokops-minion] Installed and started."
Write-Host "[dokops-minion] Check status: Get-ScheduledTask -TaskName '$TaskName'"
