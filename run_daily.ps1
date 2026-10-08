# Daily job, run by Windows Task Scheduler ("NBA Fantasy Daily Update", 09:00):
# pull the 2026-27 game logs, rebuild the website and push it to GitHub Pages.
# Every step is appended to logs\daily_update.log.

Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$log = Join-Path $PSScriptRoot "logs\daily_update.log"

function Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $log -Append -Encoding utf8
}
function Run($label, $exe, [string[]]$arguments) {
    $output = & $exe @arguments 2>&1 | Out-String
    if ($output.Trim()) { $output.TrimEnd() | Out-File -FilePath $log -Append -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { Log "$label failed (exit $LASTEXITCODE)"; exit 1 }
}

Log "start"
Run "pull" "python" @("daily_update.py")
Run "build" "python" @("build_dashboard.py")

& git add -A -- nba_2026_27 docs draft_dashboard.html
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Log "no new data"
} else {
    Run "commit" "git" @("commit", "-q", "-m", "Daily data update $(Get-Date -Format 'yyyy-MM-dd')")
    Run "push" "git" @("push", "-q")
    Log "pushed"
}
Log "done"
