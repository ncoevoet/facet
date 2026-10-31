# Delete what Setup-Facet.ps1 built: the Python environment and ExifTool. The MSI runs it on a
# real uninstall (not an upgrade), before the program files go. The database, settings and logs
# stay. Anything that cannot be removed is listed in data\logs\uninstall.log; exit 1 then.
. "$PSScriptRoot\Facet-Env.ps1"
New-Item -ItemType Directory -Force $FacetLogs | Out-Null
$log = Join-Path $FacetLogs 'uninstall.log'
function Log($msg) { Add-Content $log "$(Get-Date -Format s) $msg" -Encoding utf8 }

# A running viewer or scan holds files in the environment open.
& "$PSScriptRoot\Stop-Facet.ps1" | Out-Null
$left = @()
foreach ($dir in $FacetVenv, $FacetExifTool) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    try { Remove-Item -Recurse -Force -LiteralPath $dir -ErrorAction Stop; Log "removed $dir" }
    catch { Log "could not remove ${dir}: $($_.Exception.Message)" }
    if (Test-Path -LiteralPath $dir) { $left += $dir }
}
foreach ($dir in $left) { Log "LEFT BEHIND, delete it by hand: $dir" }
exit [int][bool]$left
