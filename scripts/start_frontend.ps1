$ErrorActionPreference='Stop'
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend')
& npm run dev
if($LASTEXITCODE -ne 0){throw 'Frontend failed'}
