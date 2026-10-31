# Scan a folder (UNC or local) with this install's environment.
# Any extra arguments go straight to facet.py, e.g. --force, --pass faces.
param([Parameter(Mandatory = $true, Position = 0)][string]$Folder,
      [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"
if (-not (Test-FacetReady)) { & "$PSScriptRoot\Setup-Facet.ps1" }
# A trailing backslash before the closing quote ("D:\My Photos\") would reach Python as an
# escaped quote; a drive root keeps its backslash ("D:" alone means the drive's current folder).
if ($Folder -notmatch '^[A-Za-z]:\\$') { $Folder = $Folder.TrimEnd('\', '/') }
Push-Location $FacetApp
try { & $FacetPython facet.py $Folder @Rest } finally { Pop-Location }
exit $LASTEXITCODE
