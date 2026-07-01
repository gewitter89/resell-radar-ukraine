# Shopping Bot 24/7 Launch Script
# Run this once to start everything.
# Watchdog will restart bot if it crashes.

Set-Location $PSScriptRoot

Write-Output "🛒 Starting Shopping Bot..."

# Kill any stale shopping_bot processes
Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*shopping_bot*'
} | Stop-Process -Force -ErrorAction SilentlyContinue

# Start watchdog (which will start bot)
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
Start-Process python -ArgumentList "watchdog.py" `
    -NoNewWindow `
    -RedirectStandardOutput "watchdog.log" `
    -RedirectStandardError "watchdog.err.log"

Start-Sleep 3

# Verify
$log = Get-Content "watchdog.log" -Encoding utf8 -Tail 5 -ErrorAction SilentlyContinue
if ($log) {
    Write-Output "✅ Watchdog output:"
    Write-Output $log
}

Write-Output ""
Write-Output "🛡️ Watchdog: watchdog.log"
Write-Output "🤖 Bot: shopping_bot_run.log"
Write-Output "📊 Status:"
Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*shopping*' -or $_.CommandLine -like '*watchdog*'
} | Select-Object Id, ProcessName
