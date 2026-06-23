# Auto Shopper Runner - 3x daily (9:00, 13:00, 18:00)
# Usage: .\run_shopper.ps1

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = $PSScriptRoot

Write-Host "Starting Auto Shopper..." -ForegroundColor Green
python auto_shopper.py --loop
