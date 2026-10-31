# Stop every Facet process (viewer and scans) started from this install's venv.
. "$PSScriptRoot\Facet-Env.ps1"
$procs = @(Get-FacetProcesses)
if (-not $procs) { Write-Host 'Facet is not running.'; return }
foreach ($p in $procs) {
    # Killing a launcher's tree also ends its child, which is listed too: skip what is gone.
    if (-not (Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue)) { continue }
    # Through cmd, so taskkill's stderr never becomes a PowerShell error under -ErrorAction Stop.
    cmd /c "taskkill /T /F /PID $($p.ProcessId) >nul 2>&1"
    Write-Host "Stopped $($p.ProcessId): $($p.CommandLine)"
}
# A child can end between the check above and taskkill, which then exits non-zero; the
# script would pass that on as its own exit code (a failed scheduled task).
exit 0
