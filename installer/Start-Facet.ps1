# Start the Facet viewer in the background (no window) and open it in the browser.
# -Lan binds 0.0.0.0 so other devices can connect (needs a firewall rule for the port); it
# refuses to start without a viewer password (or multi-user accounts) in the config.
# -PauseOnError (the Start-menu shortcut: a minimized console that closes on exit) prints the error and waits for Enter.
param([int]$Port = 5000, [switch]$Lan, [switch]$NoBrowser, [switch]$PauseOnError)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Facet-Env.ps1"

try {

    if (-not (Test-FacetReady)) {
        Write-Host 'Setting up the Python environment (first run: downloads about 6 GB, 10-20 minutes).'
        & "$PSScriptRoot\Setup-Facet.ps1"
    }

    if ($Lan) {
        $config = if (Test-Path $env:FACET_CONFIG) { Get-Content $env:FACET_CONFIG -Raw | ConvertFrom-Json } else { $null }
        $password = if ($config -and $config.viewer) { [string]$config.viewer.password } else { '' }
        $accounts = if ($config -and $config.users) { @($config.users.PSObject.Properties.Name | Where-Object { $_ -ne 'shared_directories' }) } else { @() }
        if (-not $password.Trim() -and -not $accounts) {
            throw "-Lan would open the whole library to the network without a password. Set viewer.password in $env:FACET_CONFIG first (see docs/CONFIGURATION.md)."
        }
        Write-Host "Facet will be reachable from other devices on port $Port."
    }

    $url = "http://localhost:$Port/"
    # Probe the port by connecting: a listener behind WSL mirrored networking (the Docker
    # install) is invisible to Get-NetTCPConnection but still owns the port.
    if (Test-PortOpen $Port) {
        $ours = Get-FacetProcesses | Where-Object { $_.CommandLine -match 'viewer\.py' -and $_.CommandLine -match "--port $Port\b" }
        if ($ours) {
            if (-not $NoBrowser) { Start-Process $url }
            return
        }
        throw "Port $Port is already in use by another program (the Docker install?). Stop it, or run Start-Facet.ps1 -Port <other>."
    }

    New-Item -ItemType Directory -Force $FacetLogs | Out-Null
    $bind = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
    $proc = Start-Process -FilePath $FacetPython -ArgumentList @('viewer.py', '--production', '--port', $Port, '--host', $bind) `
        -WorkingDirectory $FacetApp -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $FacetLogs 'viewer.out.log') `
        -RedirectStandardError (Join-Path $FacetLogs 'viewer.log')

    for ($i = 0; $i -lt 90; $i++) {
        if ($proc.HasExited) {
            $tail = Get-Content (Join-Path $FacetLogs 'viewer.log') -Tail 15 -ErrorAction SilentlyContinue
            throw "Facet viewer exited during start (code $($proc.ExitCode)). Log:`n$($tail -join "`n")"
        }
        if (Test-PortOpen $Port) { break }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-PortOpen $Port)) {
        $tail = Get-Content (Join-Path $FacetLogs 'viewer.log') -Tail 15 -ErrorAction SilentlyContinue
        throw "Facet viewer has not answered on port $Port after 90 s. It is still running and may finish starting: try $url in a minute, or run Stop-Facet. Log:`n$($tail -join "`n")"
    }
    if (-not $NoBrowser) { Start-Process $url }
} catch {
    if (-not $PauseOnError) { throw }
    Write-Host $_.Exception.Message -ForegroundColor Red
    Read-Host 'Press Enter to close'
    exit 1
}
