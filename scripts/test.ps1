param([string]$BuildDir = 'build', [string]$Python = 'python', [string[]]$PytestArgs = @())
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & $PSScriptRoot/build.ps1 -BuildDir $BuildDir
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    New-Item -ItemType Directory -Force reports | Out-Null
    & ctest --test-dir $BuildDir -C Release --output-on-failure --output-junit "$PWD/reports/cpp-junit.xml"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python scripts/generate_proto.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $server = Join-Path $PWD "$BuildDir/Release/halt_server.exe"
    if (-not (Test-Path -LiteralPath $server)) { $server = Join-Path $PWD "$BuildDir/halt_server.exe" }
    $env:HALT_SERVER = $server
    & $Python -m pytest -v @PytestArgs
    exit $LASTEXITCODE
} finally { Pop-Location }
