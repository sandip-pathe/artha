param(
    [string]$Host = "127.0.0.1",
    [int]$Port = 8010
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonCmd = if (Test-Path $venvPython) { $venvPython } else { "python" }

Write-Host "Starting backend on http://$Host`:$Port" -ForegroundColor Cyan
Write-Host "Using Python: $pythonCmd" -ForegroundColor DarkGray

& $pythonCmd -m uvicorn app.main:app --host $Host --port $Port --env-file .env
