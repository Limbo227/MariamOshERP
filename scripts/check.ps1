$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    $pythonExe = Join-Path $root '.venv/Scripts/python.exe'
    & $pythonExe -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Ruff failed' }
    & $pythonExe manage.py check
    if ($LASTEXITCODE -ne 0) { throw 'Django checks failed' }
    & $pythonExe manage.py makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Migrations are missing' }
    & $pythonExe -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
} finally { Pop-Location }

