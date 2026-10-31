# Shared paths for the Facet Windows launchers. Dot-source it: . "$PSScriptRoot\Facet-Env.ps1"
# Layout (per user, no admin):
#   %LOCALAPPDATA%\Facet\app     code + built client, owned by the MSI (replaced on upgrade)
#   %LOCALAPPDATA%\Facet\venv    Python 3.12 + torch for this machine, built by Setup-Facet.ps1
#   %LOCALAPPDATA%\Facet\data    photo_scores_pro.db, logs
#   %LOCALAPPDATA%\Facet\config  scoring_config.json (the operator override)
$FacetRoot   = if ($env:FACET_HOME) { $env:FACET_HOME } else { Join-Path $env:LOCALAPPDATA 'Facet' }
$FacetApp    = Split-Path $PSScriptRoot -Parent
$FacetVenv   = Join-Path $FacetRoot 'venv'
$FacetData   = Join-Path $FacetRoot 'data'
$FacetConfig = Join-Path $FacetRoot 'config'
$FacetLogs   = Join-Path $FacetData 'logs'
$FacetPython = Join-Path $FacetVenv 'Scripts\python.exe'
$FacetUv     = Join-Path $PSScriptRoot 'bin\uv.exe'   # bundled by the MSI; a repo checkout uses PATH
if (-not (Test-Path $FacetUv)) { $FacetUv = (Get-Command uv -ErrorAction SilentlyContinue).Source }
$FacetReady  = Join-Path $FacetVenv '.facet-setup-ok'
$FacetExifTool = Join-Path $FacetRoot 'exiftool'

# What the environment was built from: the lock files (both pairs: setup picks one by GPU) and
# the setup script. The marker holds this key, so an upgrade that changes any of them makes the
# next start set up again.
function Get-FacetSetupKey {
    $files = @('requirements.lock.txt', 'requirements.restricted.lock.txt',
               'requirements.legacy.lock.txt', 'requirements.legacy.restricted.lock.txt') |
        ForEach-Object { Join-Path $FacetApp $_ }
    $files += Join-Path $PSScriptRoot 'Setup-Facet.ps1'
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($f in $files) { $b = [IO.File]::ReadAllBytes($f); [void]$sha.TransformBlock($b, 0, $b.Length, $null, 0) }
        [void]$sha.TransformFinalBlock([byte[]]@(), 0, 0)
        -join ($sha.Hash | ForEach-Object { $_.ToString('x2') })
    } finally { $sha.Dispose() }
}

function Test-FacetReady {
    (Test-Path $FacetReady) -and (Test-Path (Join-Path $FacetExifTool 'exiftool.exe')) -and
        ((Get-Content $FacetReady -TotalCount 1) -eq (Get-FacetSetupKey))
}

# Facet runs `exiftool` from PATH (EXIF batch read, XMP sidecars). Put this install's copy first.
if (Test-Path (Join-Path $FacetExifTool 'exiftool.exe')) { $env:PATH = "$FacetExifTool;$env:PATH" }

$env:FACET_CONFIG       = Join-Path $FacetConfig 'scoring_config.json'
$env:DB_PATH            = Join-Path $FacetData 'photo_scores_pro.db'
$env:PYTHONIOENCODING   = 'utf-8'

# Facet processes of THIS install. A uv venv's python.exe is a launcher that runs the base
# interpreter as a child, so match the launcher by path and take its children with it.
function Get-FacetProcesses {
    $all = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'")
    # The trailing separator keeps a sibling such as venv2 out.
    $prefix = $FacetVenv.TrimEnd('\') + '\'
    $launchers = @($all | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) })
    $ids = $launchers.ProcessId
    $launchers + @($all | Where-Object { $ids -contains $_.ParentProcessId })
}

function Test-PortOpen([int]$Port) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.ConnectAsync('127.0.0.1', $Port).Wait(500) -and $c.Connected } catch { $false } finally { $c.Dispose() }
}
