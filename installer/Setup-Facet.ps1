# Build (or repair) the Facet Python environment. Runs once after install, and again after an
# upgrade that changes the lock files or this script; safe to re-run.
# Picks the PyTorch build the way install.sh does: by the lowest GPU compute capability and the
# CUDA version the NVIDIA driver supports, else CPU. Then the matching pair of lock files from
# PyPI with that torch held, then, on a CUDA 12 build, the CPU onnxruntime swapped for
# onnxruntime-gpu.
#   -Cpu    install the CPU build even when an NVIDIA GPU is present
param([switch]$Force, [switch]$Cpu)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

if ((Test-FacetReady) -and -not $Force) {
    Write-Host "Facet environment already set up ($FacetVenv). Use -Force to rebuild."
    return
}
New-Item -ItemType Directory -Force $FacetData, $FacetConfig, $FacetLogs | Out-Null

Step 'Python 3.12 virtual environment'
& $FacetUv venv $FacetVenv --python 3.12 --allow-existing
if ($LASTEXITCODE) { throw 'uv venv failed' }

# The PyTorch build. cu128 wheels ship sm_75 upwards only, so a Maxwell, Pascal or Volta card
# (compute capability below 7.5) takes cu126 whatever the driver (issue #119). Every build is
# pinned to what a Docker image ships: torch 2.11.0 with requirements.lock.txt (the cpu and cuda
# images), or, for the older CUDA indexes, torch 2.6.0 with requirements.legacy.lock.txt (the
# cuda-legacy image). The two cannot share a lock: torch 2.6.0 pins sympy==1.13.1 and torch
# 2.11.0 needs sympy>=1.13.3, and the cu124 and cu118 indexes stop at 2.6.0 on Python 3.12.
$variant, $legacy, $ortGpu = 'cpu', $false, $true
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi -and -not $Cpu) {
    $cudaText = (& $smi.Source) -join "`n"
    $cuda = if ($cudaText -match 'CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)') { [version]"$($Matches[1]).$($Matches[2])" }
    $arch = @(& $smi.Source --query-gpu=compute_cap --format=csv,noheader 2>$null |
        Where-Object { $_ -match '^\s*\d+\.\d+\s*$' } | ForEach-Object { [version]$_.Trim() } | Sort-Object)[0]
    if (-not $cuda) {
        Write-Warning 'nvidia-smi found, but it reports no CUDA version: installing the CPU build'
    } elseif ($arch -and $arch -lt [version]'7.5') {
        $variant, $legacy = 'cu126', $true
        Write-Host "GPU compute capability $arch (pre-Turing): cu126, which still ships its kernels"
    } elseif ($cuda -ge [version]'12.8') {
        $variant = 'cu128'
    } elseif ($cuda -ge [version]'12.6') {
        $variant, $legacy = 'cu126', $true
    } elseif ($cuda -ge [version]'12.4') {
        $variant, $legacy = 'cu124', $true
    } elseif ($cuda -ge [version]'11.8') {
        # The only onnxruntime-gpu for CUDA 11 links cuDNN 8 and the cu118 wheels ship cuDNN 9,
        # so its CUDA provider would never load: keep the CPU onnxruntime.
        $variant, $legacy, $ortGpu = 'cu118', $true, $false
        Write-Warning 'Driver supports CUDA 11.8 only: face detection runs on the CPU. Update the NVIDIA driver for GPU face detection.'
    } else {
        Write-Warning "Driver supports CUDA $cuda only, too old for PyTorch: installing the CPU build. Update the NVIDIA driver to use the GPU."
    }
}
$torchSpec = if ($legacy) { @('torch==2.6.0', 'torchvision==0.21.0') } else { @('torch==2.11.0', 'torchvision==0.26.0') }
$locks = if ($legacy) { @('requirements.legacy.lock.txt', 'requirements.legacy.restricted.lock.txt') } `
    else { @('requirements.lock.txt', 'requirements.restricted.lock.txt') }
Step "PyTorch ($variant, $($torchSpec[0]))"
& $FacetUv pip install --python $FacetPython @torchSpec --index-url "https://download.pytorch.org/whl/$variant"
if ($LASTEXITCODE) { throw 'torch install failed' }

# The lock files omit torch. Hold the version just installed (a local "+cu128" build satisfies
# "==2.11.0"), so the locks come from PyPI alone and cannot replace it.
$held = & $FacetPython -c "import torch, torchvision; print('torch==' + torch.__version__.split('+')[0]); print('torchvision==' + torchvision.__version__.split('+')[0])"
if ($LASTEXITCODE) { throw 'torch import failed' }
$constraint = Join-Path $env:TEMP 'facet-torch-constraint.txt'
Set-Content $constraint $held -Encoding ascii

Step "Facet dependencies ($($locks -join ' + '))"
& $FacetUv pip install --python $FacetPython -c $constraint `
    -r (Join-Path $FacetApp $locks[0]) -r (Join-Path $FacetApp $locks[1])
if ($LASTEXITCODE) { throw 'dependency install failed' }

if ($variant -ne 'cpu' -and $ortGpu) {
    Step 'onnxruntime-gpu 1.26.0 (GPU face detection)'
    & $FacetUv pip uninstall --python $FacetPython onnxruntime onnxruntime-gpu
    if ($LASTEXITCODE) { throw 'onnxruntime uninstall failed' }
    & $FacetUv pip install --python $FacetPython 'onnxruntime-gpu==1.26.0'
    if ($LASTEXITCODE) { throw 'onnxruntime-gpu install failed' }
}

# ExifTool for Windows, the version the Docker image pins (must stay >= 13.28: 13.23-13.27
# corrupt darktable XMP sidecars). exiftool.org keeps only the latest release, so take the
# SourceForge archive and pin its hash (MD5 matches SourceForge's published 1ebe3c5b...).
$exifVersion = '13.55'
$exifSha256  = '9FADAF5221DCB07A5D018E21C8529E257917D2FAD1FDFC8E64855C4FB73293DF'
$exifExe = Join-Path $FacetExifTool 'exiftool.exe'
if (-not (Test-Path $exifExe) -or ((& $exifExe -ver) -ne $exifVersion)) {
    Step "ExifTool $exifVersion"
    $zip = Join-Path $env:TEMP "exiftool-${exifVersion}_64.zip"
    Invoke-WebRequest "https://sourceforge.net/projects/exiftool/files/exiftool-${exifVersion}_64.zip/download" `
        -OutFile $zip -UseBasicParsing -UserAgent 'Wget'
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $exifSha256) { Remove-Item $zip; throw 'ExifTool download failed its checksum' }
    $unpack = Join-Path $env:TEMP "exiftool-$exifVersion"
    if (Test-Path $unpack) { Remove-Item -Recurse -Force $unpack }
    Expand-Archive $zip $unpack
    if (Test-Path $FacetExifTool) { Remove-Item -Recurse -Force $FacetExifTool }
    Move-Item (Get-ChildItem $unpack -Directory | Select-Object -First 1).FullName $FacetExifTool
    Rename-Item (Join-Path $FacetExifTool 'exiftool(-k).exe') 'exiftool.exe'
    Remove-Item -Recurse -Force $zip, $unpack
    Write-Host "exiftool $(& $exifExe -ver)"
}

if (-not (Test-Path $env:FACET_CONFIG)) {
    Step "New config: $env:FACET_CONFIG"
    Set-Content $env:FACET_CONFIG '{}' -Encoding ascii
    Write-Host 'Set viewer.edition_password in it before editing in the viewer (see docs/CONFIGURATION.md).'
}

Step 'Check'
& $FacetPython -c "import torch, onnxruntime as o; print('torch', torch.__version__, 'CUDA' if torch.cuda.is_available() else 'CPU'); print('onnxruntime', o.__version__, o.get_available_providers())"
if ($LASTEXITCODE) { throw 'import check failed' }
if ($variant -ne 'cpu') {
    # A GPU build that cannot reach the GPU would scan on the CPU without saying so.
    & $FacetPython -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 3)"
    if ($LASTEXITCODE) {
        throw "PyTorch $variant is installed but cannot use the GPU (driver too old or not loaded?). Update the NVIDIA driver and run setup again, or run Setup-Facet.ps1 -Force -Cpu to use the CPU."
    }
}
Push-Location $FacetApp
try { & $FacetPython database.py; if ($LASTEXITCODE) { throw 'database init failed' } } finally { Pop-Location }

Set-Content $FacetReady (Get-FacetSetupKey) -Encoding ascii
Write-Host "`nFacet is ready. Start it from the Start menu: Facet." -ForegroundColor Green
