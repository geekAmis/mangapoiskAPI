$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "data\dev-pids.json"
if (Test-Path $pidFile) {
    $entries = Get-Content $pidFile -Raw | ConvertFrom-Json
    foreach ($entry in $entries) {
        Stop-Process -Id $entry.pid -Force
        Write-Host ("stopped {0} (pid {1})" -f $entry.name, $entry.pid)
    }
    Remove-Item $pidFile -Force
} else {
    Write-Host "no dev-pids.json; nothing to stop"
}
