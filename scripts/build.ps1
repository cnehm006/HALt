param([string]$BuildDir = 'build', [string[]]$CMakeArgs = @())
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & cmake -S . -B $BuildDir -DCMAKE_BUILD_TYPE=Debug @CMakeArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & cmake --build $BuildDir --config Release --parallel 2
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
