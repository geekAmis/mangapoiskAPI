$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Create .venv first: python -m venv .venv; pip install -e packages/manga_common"
}
$env:PYTHONPATH = Join-Path $root "packages"
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

$services = @(
    @{ name = "parser";    dir = "services/parser";    port = 8001 },
    @{ name = "catalog";   dir = "services/catalog";   port = 8002 },
    @{ name = "library";   dir = "services/library";   port = 8003 },
    @{ name = "media";     dir = "services/media";     port = 8004 },
    @{ name = "notifier";  dir = "services/notifier";  port = 8006 },
    @{ name = "gateway";   dir = "services/gateway";   port = 8000 }
)

$pids = @()
foreach ($service in $services) {
    $out = Join-Path $logs "$($service.name).out.log"
    $err = Join-Path $logs "$($service.name).err.log"
    $process = Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", $service.dir, "--host", "127.0.0.1", "--port", $service.port `
        -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
    $pids += [pscustomobject]@{ name = $service.name; pid = $process.Id; port = $service.port }
    Write-Host ("started {0} on :{1} (pid {2})" -f $service.name, $service.port, $process.Id)
}

$pids | ConvertTo-Json | Set-Content (Join-Path $root "data\dev-pids.json") -Encoding UTF8
Write-Host ""
Write-Host "API:  http://localhost:8000/docs"
Write-Host "Web:  cd apps/web; npm run dev"
Write-Host "Logs: data/logs/"
Write-Host "Stop: .\scripts\stop-dev.ps1"
