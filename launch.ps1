param(
    [int]$Port = 6211,
    [switch]$Detach
)

$ErrorActionPreference = "Stop"
$RequiredApiVersion = 3
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ((Split-Path -Leaf $ScriptDir) -eq "codex_governance" -and (Split-Path -Leaf (Split-Path -Parent $ScriptDir)) -eq "tools") {
    $RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
} else {
    $RepoRoot = (Resolve-Path $ScriptDir).Path
}
$Launcher = Join-Path $ScriptDir "codex_launcher.py"
$Dashboard = Join-Path $ScriptDir "dashboard.html"

Set-Location $RepoRoot

function Stop-OldGovernanceProcess {
    $launcherPattern = "tools[\\/]+codex_governance[\\/]+codex_launcher\.py"
    $launchScriptPattern = "tools[\\/]+codex_governance[\\/]+launch\.ps1"
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -and
        ($_.CommandLine -match $launcherPattern -or $_.CommandLine -match $launchScriptPattern)
    }

    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped old governance process: $($process.Name) pid=$($process.ProcessId)"
    }
}

function Test-Launcher {
    param([int]$ProbePort)
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:$ProbePort/api/status" -TimeoutSec 1
        return ([bool]$status.ok -and [int]$status.api_version -ge $RequiredApiVersion)
    } catch {
        return $false
    }
}

Stop-OldGovernanceProcess

$SelectedPort = $Port
while ((Test-NetConnection -ComputerName 127.0.0.1 -Port $SelectedPort -InformationLevel Quiet) -and -not (Test-Launcher $SelectedPort)) {
    Write-Host "Port $SelectedPort has an old or incompatible launcher. Trying $($SelectedPort + 1)."
    $SelectedPort++
}

$LauncherProcess = $null
if (-not (Test-Launcher $SelectedPort)) {
    $LauncherProcess = Start-Process -FilePath "python" `
        -ArgumentList @($Launcher, "--host", "127.0.0.1", "--port", "$SelectedPort") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Milliseconds 800
}

$Url = "file:///$($Dashboard.Replace('\','/'))?launcher=http://127.0.0.1:$SelectedPort"
Start-Process $Url
Write-Host "Codex governance dashboard: $Url"
Write-Host "Launcher API: http://127.0.0.1:$SelectedPort"

if ($Detach) {
    Write-Host "Detached mode: launcher keeps running in background."
    return
}

Write-Host "Launcher monitor is running. Press Ctrl+C to stop this script."
try {
    while ($true) {
        Start-Sleep -Seconds 5
        if ($LauncherProcess -and $LauncherProcess.HasExited) {
            throw "Launcher process exited unexpectedly."
        }
        if (-not (Test-Launcher $SelectedPort)) {
            throw "Launcher API is unavailable on port $SelectedPort."
        }
    }
} finally {
    if ($LauncherProcess -and -not $LauncherProcess.HasExited) {
        Stop-Process -Id $LauncherProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped launcher process $($LauncherProcess.Id)."
    }
}
