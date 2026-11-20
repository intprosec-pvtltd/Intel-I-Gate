$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
Set-Location (Join-Path $projectRoot 'backend')
& $python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
if($LASTEXITCODE -ne 0){throw 'Backend failed. Check PostgreSQL, migrations and configuration.'}
