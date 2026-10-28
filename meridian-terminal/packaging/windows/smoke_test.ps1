# Start the built console binary headless, check the dashboard and API answer, stop it.
param([Parameter(Mandatory = $true)][string]$Exe, [int]$Port = 8791)
$ErrorActionPreference = "Stop"
$env:MERIDIAN_HOME = Join-Path ([IO.Path]::GetTempPath()) ("meridian-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $env:MERIDIAN_HOME | Out-Null

& $Exe version
if ($LASTEXITCODE -ne 0) { throw "version command failed" }
$token = (& $Exe token).Trim()
$log = Join-Path $env:MERIDIAN_HOME "smoke.log"
$proc = Start-Process -FilePath $Exe -ArgumentList @("headless", "--port", "$Port") -PassThru `
    -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError "$log.err"
try {
    $up = $false
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/" | Out-Null; $up = $true; break }
        catch {
            if ($proc.HasExited) { Get-Content $log, "$log.err" -ErrorAction SilentlyContinue; throw "binary exited early (is Meridian already running?)" }
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $up) { throw "dashboard did not come up" }
    $index = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/"
    if ($index.Content -notmatch "Meridian Terminal") { throw "unexpected index page" }
    $js = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/static/js/app.js"
    if ($js.Headers["Content-Type"] -notmatch "javascript") { throw "app.js served as $($js.Headers['Content-Type'])" }
    $state = Invoke-WebRequest -UseBasicParsing -Headers @{ "X-Token" = $token } "http://127.0.0.1:$Port/api/state"
    if ($state.Content -notmatch '"demo": true') { throw "unexpected /api/state" }
    $noToken = 0
    try { $noToken = [int](Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/state").StatusCode }
    catch { $noToken = [int]$_.Exception.Response.StatusCode }
    if ($noToken -ne 401) { throw "API answered $noToken without a token (expected 401)" }
    Write-Host "smoke test passed ($Exe)"
}
finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
}
