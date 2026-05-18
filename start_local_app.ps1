$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Url = "http://127.0.0.1:8765/"

try {
  $response = Invoke-WebRequest -Uri "$($Url)api/status" -UseBasicParsing -TimeoutSec 2
  if ($response.StatusCode -eq 200) {
    Start-Process $Url
    exit 0
  }
} catch {
  # Server is not running yet.
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  py -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$InstallMarker = Join-Path $Root ".venv\.requirements_installed"
$needsInstall = -not (Test-Path $InstallMarker)

if (-not $needsInstall) {
  $needsInstall = (Get-Item $Requirements).LastWriteTime -gt (Get-Item $InstallMarker).LastWriteTime
}

if ($needsInstall) {
  & $Python -m pip install -r $Requirements
  Set-Content -Path $InstallMarker -Value (Get-Date).ToString("s")
}

& $Python .\local_app.py
