param([string]$Python = 'python', [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:PYTHONPATH = Join-Path $PWD 'python'
    & $Python -m halt.web --port $Port
    exit $LASTEXITCODE
} finally { Pop-Location }
