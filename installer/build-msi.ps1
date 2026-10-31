# Build installer\out\Facet-<version>.msi from the committed tree (HEAD) plus the built client.
# Needs: WiX 3.14 binaries (-WixDir), a built client (client\dist\client\browser), uv.exe.
param(
    [Parameter(Mandatory = $true)][string]$WixDir,
    [string]$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
)
$ErrorActionPreference = 'Stop'
$repo  = Split-Path $PSScriptRoot -Parent
$out   = Join-Path $PSScriptRoot 'out'
# Stage outside the repo: a dev viewer (`python viewer.py`, auto-reload) watches the repo
# for .py changes and dies when a staged copy appears and is deleted under it.
$work  = Join-Path $env:TEMP 'facet-msi-build'
$stage = Join-Path $work 'stage'
$obj   = Join-Path $work 'obj'
$dist  = Join-Path $repo 'client\dist\client\browser'

if (-not (Test-Path (Join-Path $WixDir 'candle.exe'))) {
    throw "WiX 3.14 not found in $WixDir. Download wix314-binaries.zip from https://github.com/wixtoolset/wix3/releases/tag/wix3141rtm (SHA-256 6AC824E1642D6F7277D0ED7EA09411A508F6116BA6FAE0AA5F2C7DAA2FF43D31), unzip it and pass that folder as -WixDir."
}
if (-not (Test-Path (Join-Path $dist 'index.html'))) { throw "Build the client first (cd client; npm run build): $dist" }
if (-not $Uv -or -not (Test-Path $Uv)) { throw 'uv.exe not found: pass -Uv <path>' }
$dirty = git -C $repo status --porcelain -- . ':!dev-notes' ':!installer/out'
if ($dirty) { Write-Warning "Uncommitted changes are NOT in the MSI (it packages HEAD):`n$dirty" }

$version = (Select-String -Path (Join-Path $repo 'pyproject.toml') -Pattern '^version = "([^"]+)"').Matches[0].Groups[1].Value
$commit  = git -C $repo rev-parse --short HEAD

foreach ($d in $out, $work) { if (Test-Path $d) { Remove-Item -Recurse -Force $d } }
New-Item -ItemType Directory -Force $out, $stage, $obj | Out-Null

# App files: the committed tree, minus what a running install never reads.
$tar = Join-Path $work 'src.tar'
git -C $repo archive --format=tar -o $tar HEAD
tar -xf $tar -C $stage
Remove-Item $tar
foreach ($p in 'client', 'tests', '.claude', '.github', 'bench', 'build-tools', 'docs\de', 'docs\es', 'docs\fr', 'docs\it', 'docs\pt', 'docs\zh') {
    $t = Join-Path $stage $p
    if (Test-Path $t) { Remove-Item -Recurse -Force $t }
}
$distStage = Join-Path $stage 'client\dist\client\browser'
New-Item -ItemType Directory -Force $distStage | Out-Null
Copy-Item -Recurse (Join-Path $dist '*') $distStage
New-Item -ItemType Directory -Force (Join-Path $stage 'installer\bin') | Out-Null
Copy-Item $Uv (Join-Path $stage 'installer\bin\uv.exe')
Set-Content (Join-Path $stage 'BUILD.txt') "Facet $version, commit $commit, built $(Get-Date -Format s)" -Encoding ascii

# Harvest, compile, link. A per-user install with file key paths trips ICE38/ICE64/ICE91 by
# design, and the app folder is replaced wholesale on upgrade: those three are suppressed, every
# other ICE still validates.
& "$WixDir\heat.exe" dir $stage -nologo -cg AppFiles -dr INSTALLDIR -srd -gg -sfrag -sreg -var var.StageDir -out (Join-Path $obj 'AppFiles.wxs')
if ($LASTEXITCODE) { throw 'heat failed' }
& "$WixDir\candle.exe" -nologo -arch x64 "-dStageDir=$stage" "-dVersion=$version" -out "$obj\" `
    (Join-Path $PSScriptRoot 'Facet.wxs') (Join-Path $obj 'AppFiles.wxs')
if ($LASTEXITCODE) { throw 'candle failed' }
$msi = Join-Path $out "Facet-$version-$commit.msi"
& "$WixDir\light.exe" -nologo -sice:ICE38 -sice:ICE64 -sice:ICE91 -out $msi (Join-Path $obj 'Facet.wixobj') (Join-Path $obj 'AppFiles.wixobj')
if ($LASTEXITCODE) { throw 'light failed' }
Remove-Item -Recurse -Force $work
Get-Item $msi | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }
