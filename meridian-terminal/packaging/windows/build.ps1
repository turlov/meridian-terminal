# Build Meridian Terminal for Windows and wrap it in an installer. Run in PowerShell:
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
# Needs Python 3.11+ (python.org or `winget install Python.Python.3.12`) and Inno Setup 6
# (`winget install JRSoftware.InnoSetup`).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

function Run($exe, [string[]]$argList) {
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { throw "$exe $($argList -join ' ') failed with exit code $LASTEXITCODE" }
}

$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
if (-not (Test-Path ".venv-build\Scripts\python.exe")) { Run $py @("-m", "venv", ".venv-build") }
$vpy = (Resolve-Path ".venv-build\Scripts\python.exe").Path

Run $vpy @("-m", "pip", "install", "--upgrade", "pip")
Run $vpy @("-m", "pip", "install", "-r", "requirements-desktop.txt", "-r", "requirements-build.txt")
$version = (& $vpy -c "import meridian; print(meridian.__version__)").Trim()

Write-Host "== tests"
Run $vpy @("-m", "pytest", "-q", "tests")

Write-Host "== icons"
Run $vpy @("packaging\icons\make_icons.py")

Write-Host "== pyinstaller"
Remove-Item -Recurse -Force "build", "dist\Meridian Terminal" -ErrorAction SilentlyContinue
Run $vpy @("-m", "PyInstaller", "--noconfirm", "--clean", "packaging\meridian.spec")

Write-Host "== smoke test"
& (Join-Path $PSScriptRoot "smoke_test.ps1") -Exe (Resolve-Path "dist\Meridian Terminal\meridian.exe").Path

Write-Host "== installer"
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    Write-Warning "Inno Setup 6 not found, so no installer was made. Install it with: winget install JRSoftware.InnoSetup"
    Write-Host "The app itself is ready in 'dist\Meridian Terminal\' (run 'Meridian Terminal.exe')."
    exit 0
}
Run $iscc @("/Qp", "/DMyAppVersion=$version", "packaging\windows\meridian.iss")
Write-Host ""
Write-Host "Built dist\MeridianTerminal-Setup-$version.exe"
