param([string]$Video='')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
if($Video){& $python scripts\test_models.py --video $Video}else{& $python scripts\test_models.py}
if($LASTEXITCODE -ne 0){throw 'Model verification failed; inspect the error above'}
