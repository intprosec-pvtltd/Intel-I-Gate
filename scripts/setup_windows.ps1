param([ValidateSet('cpu','cu124')][string]$TorchBuild='cpu',[switch]$SkipModels)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
function Check-Exit([string]$Step){if($LASTEXITCODE -ne 0){throw "$Step failed (exit $LASTEXITCODE)"}}
foreach($commandName in @('py','node','npm','psql','ffmpeg','ffprobe','git')){if(-not(Get-Command $commandName -ErrorAction SilentlyContinue)){throw "Install $commandName and add it to PATH; see README.md"}}
& py -3.11 -c "import sys;print(sys.version)"
Check-Exit 'Python 3.11 check'
& node -e "const [a,b]=process.versions.node.split('.').map(Number);if(a<22||(a===22&&b<12))process.exit(1);console.log(process.version)"
Check-Exit 'Node check'
if($TorchBuild -eq 'cu124'){
    if(-not(Get-Command nvidia-smi -ErrorAction SilentlyContinue)){throw 'nvidia-smi missing; verify driver before CUDA installation'}
    & nvidia-smi
    Check-Exit 'NVIDIA driver check'
}
if(-not(Test-Path '.venv\Scripts\python.exe')){& py -3.11 -m venv .venv;Check-Exit 'Virtual environment'}
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip
Check-Exit 'pip upgrade'
& $python -m pip install torch==2.6.0 torchvision==0.21.0 --index-url "https://download.pytorch.org/whl/$TorchBuild"
Check-Exit 'PyTorch installation'
& $python -m pip install -r backend\requirements-ai.txt
Check-Exit 'Backend dependencies'
& $python -m pip check
Check-Exit 'Dependency check'
if($TorchBuild -eq 'cu124'){& $python -c "import torch;assert torch.cuda.is_available(),'CUDA unavailable';print(torch.cuda.get_device_name(0))";Check-Exit 'CUDA verification'}
if(-not(Test-Path 'backend\.env')){& $python scripts\configure.py;Check-Exit 'Configuration'}
Push-Location frontend
try{& npm ci;Check-Exit 'Frontend dependencies';& npm run build;Check-Exit 'Frontend build'}finally{Pop-Location}
if(-not $SkipModels){& $python scripts\download_models.py;Check-Exit 'Model downloads'}
Write-Host 'Setup finished. Edit backend/.env DATABASE_URL and CAMERA_ALLOW_CIDRS, then run the migration and create_admin.py.'
Write-Host 'DEVICE remains cpu until you explicitly choose cuda:0 after verifying hardware. DINO_DEVICE=cpu is the initial 4 GB configuration.'
