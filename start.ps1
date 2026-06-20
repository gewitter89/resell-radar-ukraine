# Resell Radar Ukraine — One-command launch
param(
    [switch]$Docker,
    [switch]$Celery,
    [switch]$Help
)

if ($Help) {
    Write-Host "Usage: .\start.ps1 [flags]"
    Write-Host "  -Docker    Start with Docker (PG, Redis, MinIO)"
    Write-Host "  -Celery    Start Celery worker + beat alongside"
    Write-Host "  No flags   Quick dev mode (SQLite fallback)"
    exit
}

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Check Python
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host "ERROR: Python not found. Install Python 3.11+" -ForegroundColor Red
    exit 1
}

# Check deps
Write-Host "Checking dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt -q 2>$null

# Docker mode
if ($Docker) {
    Write-Host "Starting Docker services..." -ForegroundColor Cyan
    docker compose up -d
    Write-Host "Waiting for PostgreSQL..." -ForegroundColor Cyan
    Start-Sleep -Seconds 5
    python -m alembic upgrade head 2>$null
}

# Start everything
Write-Host "Starting Resell Radar Ukraine..." -ForegroundColor Green

if ($Celery) {
    # Start all three processes
    $jobs = @()
    $jobs += Start-Job -ScriptBlock { param($d) Set-Location $d; uvicorn app.web.web_server:app --host 0.0.0.0 --port 8000 --log-level info } -ArgumentList $root
    Start-Sleep -Seconds 2
    $jobs += Start-Job -ScriptBlock { param($d) Set-Location $d; celery -A app.celery_app worker -l info -P gevent -c 10 } -ArgumentList $root
    $jobs += Start-Job -ScriptBlock { param($d) Set-Location $d; celery -A app.celery_app beat -l info } -ArgumentList $root

    Write-Host "All services started:" -ForegroundColor Green
    Write-Host "  Dashboard: http://localhost:8000" -ForegroundColor Yellow
    Write-Host "  API docs:  http://localhost:8000/docs" -ForegroundColor Yellow
    Write-Host "  Celery:    worker + beat running" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Press Ctrl+C to stop all services" -ForegroundColor Cyan

    try {
        $jobs | Wait-Job
    } finally {
        $jobs | Stop-Job | Remove-Job
    }
} else {
    # Simple mode
    Write-Host "  Dashboard: http://localhost:8000" -ForegroundColor Yellow
    Write-Host "  API docs:  http://localhost:8000/docs" -ForegroundColor Yellow
    Write-Host "  Press Ctrl+C to stop" -ForegroundColor Cyan
    uvicorn app.web.web_server:app --host 0.0.0.0 --port 8000 --log-level info
}
