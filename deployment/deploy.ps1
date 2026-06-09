<#
.SYNOPSIS
    Deploys the DokOps-AIO platform using Helm.
#>
[CmdletBinding()]
param (
    [string]$Secret,
    [string]$Namespace,
    [string]$ReleaseName = "dokops",
    [string]$ChartPath = "./helm/dokops-aio"
)

$ErrorActionPreference = "Stop"

Write-Host "Starting DokOps-AIO Deployment..." -ForegroundColor Cyan

# Check prerequisites
if (-not (Get-Command helm -ErrorAction SilentlyContinue)) {
    Write-Error "Helm is not installed."
    exit 1
}

# Interactive Prompts
if ([string]::IsNullOrWhiteSpace($Namespace)) {
    $Namespace = Read-Host "Enter Namespace"
    if ([string]::IsNullOrWhiteSpace($Namespace)) { $Namespace = "default" }
}

if ([string]::IsNullOrWhiteSpace($Secret)) {
    Write-Host "Enter Auth Secret Key: " -NoNewline -ForegroundColor Yellow
    $secureInput = Read-Host -AsSecureString
    $Secret = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureInput))
    Write-Host ""
}

if ([string]::IsNullOrWhiteSpace($Secret)) {
    Write-Error "Secret key is required!"
    exit 1
}

# 1. Create Secret
Write-Host "Managing Secrets..." -ForegroundColor Cyan
$secretExists = (kubectl get secret dokops-aio-secrets -n $Namespace --ignore-not-found)

if ($secretExists) {
    Write-Host "Secret 'dokops-aio-secrets' already exists. Skipping." -ForegroundColor Yellow
} else {
    try {
        $nsExists = (kubectl get ns $Namespace --ignore-not-found)
        if (-not $nsExists) {
            Write-Host "Creating namespace $Namespace..." -ForegroundColor Cyan
            kubectl create ns $Namespace | Out-Null
        }
        kubectl create secret generic dokops-aio-secrets --from-literal=auth-secret="$Secret" -n "$Namespace"
        Write-Host "Secret created." -ForegroundColor Green
    } catch {
        Write-Error "Failed to create secret: $_"
        exit 1
    }
}

# 2. Deploy Helm Chart
Write-Host "Deploying Helm Chart..." -ForegroundColor Cyan
try {
    helm upgrade --install $ReleaseName $ChartPath `
        --namespace "$Namespace" `
        --create-namespace `
        --set ingress.enabled=true
    
    if ($LASTEXITCODE -ne 0) {
        throw "Helm command failed with exit code $LASTEXITCODE"
    }

    Write-Host "Deployment Complete!" -ForegroundColor Green
} catch {
    Write-Error "Helm deployment failed: $_"
    exit 1
}
