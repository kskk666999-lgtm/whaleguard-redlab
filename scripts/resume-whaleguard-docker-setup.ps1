[CmdletBinding()]
param(
    [switch]$AutoResume,
    [ValidateRange(120, 1200)][int]$EngineTimeoutSeconds = 600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$composeFile = Join-Path $projectRoot "docker-compose.yml"
$logDir = Join-Path $projectRoot ".local\setup-logs"
$installerDir = Join-Path $projectRoot ".local\installers"
$statePath = Join-Path $projectRoot ".local\docker-setup-state.json"
$installerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
$installerPath = Join-Path $installerDir "Docker Desktop Installer.exe"
$transcriptStarted = $false
$resumeAttempt = 0
if ($AutoResume -and (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    try {
        $previousState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        if ($previousState.PSObject.Properties["resume_attempt"]) {
            $resumeAttempt = [int]$previousState.resume_attempt
        }
    }
    catch { $resumeAttempt = 0 }
}
if ($AutoResume) { $resumeAttempt += 1 }

function Write-State {
    param(
        [Parameter(Mandatory = $true)][string]$Phase,
        [string]$Detail = ""
    )
    $stateDirectory = Split-Path $statePath -Parent
    if (-not (Test-Path -LiteralPath $stateDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    }
    $state = [ordered]@{
        schema_version = 1
        updated_at = (Get-Date).ToString("o")
        project_root = $projectRoot
        phase = $Phase
        detail = $Detail
        automatic_resume = [bool]$AutoResume
        resume_attempt = $resumeAttempt
    }
    $tempPath = "$statePath.tmp"
    $state | ConvertTo-Json | Set-Content -LiteralPath $tempPath -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $statePath -Force
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ""
    )
    Write-Host "==> $Label"
    $previous = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location -LiteralPath $WorkingDirectory }
        $exitCode = Invoke-WgExternalCommandToHost -FilePath $FilePath -Arguments $Arguments
        if ($exitCode -ne 0) {
            throw "$Label failed with exit code $exitCode."
        }
    }
    finally {
        Set-Location -LiteralPath $previous
    }
}

function Get-DockerDesktopPath {
    return Find-WgTrustedDockerDesktopPath
}

function Get-DockerCliPath {
    return Find-WgTrustedDockerCliPath
}

function Test-DockerInstallerSignature {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $null = Get-WgDockerBinaryEvidence -Path $Path -Kind "Installer"
        return $true
    }
    catch { return $false }
}

function Write-DockerInstallerEvidence {
    param([Parameter(Mandatory = $true)][string]$Path)
    $evidence = Get-WgDockerBinaryEvidence -Path $Path -Kind "Installer"
    $hash = Get-FileHash -LiteralPath $Path -Algorithm SHA256
    Write-Host "Docker installer publisher: $($evidence.SignerSubject)"
    Write-Host "Docker installer product: $($evidence.ProductName)"
    Write-Host "Docker installer version: $($evidence.ProductVersion)"
    Write-Host "Docker installer SHA256: $($hash.Hash)"
}

function Get-OfficialDockerInstaller {
    New-Item -ItemType Directory -Path $installerDir -Force | Out-Null
    if (Test-Path -LiteralPath $installerPath) {
        $cachedInstaller = Get-Item -LiteralPath $installerPath -ErrorAction Stop
        $cacheAge = [DateTime]::UtcNow - $cachedInstaller.LastWriteTimeUtc
        if (
            $cacheAge -ge [TimeSpan]::Zero -and
            $cacheAge -le [TimeSpan]::FromHours(1) -and
            (Test-DockerInstallerSignature -Path $installerPath)
        ) {
            Write-Host "Reusing a recently downloaded Docker-signed installer after local setup recovery."
            Write-DockerInstallerEvidence -Path $installerPath
            return $installerPath
        }
        Remove-Item -LiteralPath $installerPath -Force
        Write-Host "Discarded the previous installer cache; a fresh official package is required."
    }

    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    $winget = if ($localAppData) { Join-Path $localAppData "Microsoft\WindowsApps\winget.exe" } else { "" }
    if (Test-Path -LiteralPath $winget -PathType Leaf) {
        $wingetDir = Join-Path $installerDir ("winget-{0}" -f [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $wingetDir -Force | Out-Null
        try {
            Write-Host "Downloading a fresh exact Docker.DockerDesktop package from the official winget source."
            $showExitCode = Invoke-WgExternalCommandToHost -FilePath $winget -Arguments @(
                "show", "--id", "Docker.DockerDesktop", "--exact", "--source", "winget",
                "--accept-source-agreements", "--disable-interactivity"
            )
            if ($showExitCode -eq 0) {
                $downloadExitCode = Invoke-WgExternalCommandToHost -FilePath $winget -Arguments @(
                    "download", "--id", "Docker.DockerDesktop", "--exact", "--source", "winget",
                    "--architecture", "x64", "--download-directory", $wingetDir,
                    "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"
                )
                if ($downloadExitCode -eq 0) {
                    $trustedInstallers = @()
                    foreach ($candidate in Get-ChildItem -LiteralPath $wingetDir -Filter "*.exe" -File -Recurse -ErrorAction SilentlyContinue) {
                        if (Test-DockerInstallerSignature -Path $candidate.FullName) {
                            $trustedInstallers += $candidate
                        }
                    }
                    if ($trustedInstallers.Count -gt 1) {
                        throw "The exact winget package contained multiple trusted Docker installers; refusing an ambiguous selection."
                    }
                    if ($trustedInstallers.Count -eq 1) {
                        Move-Item -LiteralPath $trustedInstallers[0].FullName -Destination $installerPath
                    }
                }
            }
        }
        finally {
            if (Test-Path -LiteralPath $wingetDir -PathType Container) {
                Remove-Item -LiteralPath $wingetDir -Recurse -Force
            }
        }
    }

    if (Test-DockerInstallerSignature -Path $installerPath) {
        Write-Host "The winget manifest hash and Docker Authenticode signature were both accepted."
        Write-DockerInstallerEvidence -Path $installerPath
        return $installerPath
    }

    $downloadPath = Join-Path $installerDir ("Docker Desktop Installer.download-{0}.exe" -f [Guid]::NewGuid().ToString("N"))
    try {
        Write-Host "Downloading a fresh Docker Desktop installer from the official desktop.docker.com endpoint."
        $bits = Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue
        if ($bits) {
            Start-BitsTransfer -Source $installerUrl -Destination $downloadPath -DisplayName "WhaleGuard Docker Desktop setup" | Out-Null
        }
        else {
            Add-Type -AssemblyName System.Net.Http -ErrorAction Stop
            $client = New-Object Net.Http.HttpClient
            try {
                $response = $client.GetAsync($installerUrl, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
                $response.EnsureSuccessStatusCode() | Out-Null
                $inputStream = $response.Content.ReadAsStreamAsync().Result
                $outputStream = [IO.File]::Create($downloadPath)
                try { $inputStream.CopyTo($outputStream) }
                finally { $outputStream.Dispose(); $inputStream.Dispose() }
            }
            finally { $client.Dispose() }
        }
        if (-not (Test-DockerInstallerSignature -Path $downloadPath)) {
            throw "The downloaded Docker Desktop installer failed Docker publisher, product-name, or version validation."
        }
        Move-Item -LiteralPath $downloadPath -Destination $installerPath
    }
    finally {
        if (Test-Path -LiteralPath $downloadPath -PathType Leaf) {
            Remove-Item -LiteralPath $downloadPath -Force
        }
    }
    Write-DockerInstallerEvidence -Path $installerPath
    return $installerPath
}

function Get-LocalDockerTarget {
    param([Parameter(Mandatory = $true)][string]$DockerCli)
    $target = Get-WgLocalDockerTarget -Docker $DockerCli
    Write-Host "Docker context: $($target.ContextName) ($($target.Endpoint))"
    return $target
}

function Stop-ProjectLoopbackProcesses {
    $ports = 3000, 8000, 8101, 8102, 8103
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $ports -contains $_.LocalPort }
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        $commandLine = [string]$process.CommandLine
        $isWhaleGuard = Test-WgProjectLoopbackProcess `
            -ProjectRoot $projectRoot `
            -Port ([int]$listener.LocalPort) `
            -LocalAddress ([string]$listener.LocalAddress) `
            -ProcessName ([string]$process.Name) `
            -CommandLine $commandLine
        if (-not $isWhaleGuard) {
            throw "Port $($listener.LocalPort) is occupied by an unrelated process (PID $($listener.OwningProcess), $($process.Name))."
        }
        $confirmedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        $confirmedListener = Get-NetTCPConnection -State Listen -LocalPort $listener.LocalPort -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $listener.OwningProcess }
        if (-not $confirmedProcess -or -not $confirmedListener) { continue }
        if ([string]$confirmedProcess.CommandLine -ne $commandLine) {
            throw "Process ownership changed while validating port $($listener.LocalPort); refusing to stop it."
        }
        Write-Host "Stopping prior WhaleGuard local process PID $($listener.OwningProcess) on port $($listener.LocalPort)."
        Stop-Process -Id $listener.OwningProcess
        try { Wait-Process -Id $listener.OwningProcess -Timeout 10 -ErrorAction Stop }
        catch {
            $currentProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
            $stillOwnsPort = Get-NetTCPConnection -State Listen -LocalPort $listener.LocalPort -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -eq $listener.OwningProcess }
            if ($currentProcess -and $stillOwnsPort -and [string]$currentProcess.CommandLine -eq $commandLine) {
                Stop-Process -Id $listener.OwningProcess -Force
            }
            elseif ($currentProcess) {
                throw "Process ownership changed while releasing port $($listener.LocalPort); refusing a forced stop."
            }
        }
    }
}

$setupMutex = New-Object System.Threading.Mutex($false, "Local\WhaleGuardDockerSetup")
$mutexAcquired = $false
try {
    try { $mutexAcquired = $setupMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $mutexAcquired = $true }
    if (-not $mutexAcquired) {
        Write-Error "Another WhaleGuard Docker setup process is already running."
        exit 2
    }
    if ($AutoResume -and $resumeAttempt -gt 3) {
        Remove-WgAutomaticResume
        Write-State -Phase "automatic-resume-exhausted" -Detail "The bounded three-attempt automatic resume limit was reached."
        throw "Automatic resume reached its bounded three-attempt limit."
    }
    if ($AutoResume) {
        Write-State -Phase "automatic-resume-starting" -Detail "Automatic resume attempt $resumeAttempt of 3 started."
    }
    if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
        throw "Refusing to continue because docker-compose.yml was not found at $projectRoot."
    }
    $null = Assert-WgContainerHostCompatibility
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $logPath = Join-Path $logDir ("docker-setup-resume-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    Start-Transcript -Path $logPath | Out-Null
    $transcriptStarted = $true
    Write-State -Phase "checking-wsl"

    $systemDirectory = [IO.Path]::GetFullPath([Environment]::SystemDirectory)
    $wsl = Get-WgWindowsSystemExecutable -RelativePath "wsl.exe"
    $wslVersion = Get-WgWslVersion -WslPath $wsl
    if ($null -eq $wslVersion -or $wslVersion -lt [version]"2.1.5") {
        Write-Host "Updating the inbox WSL installation."
        & $wsl --update
        if ($LASTEXITCODE -ne 0) {
            & $wsl --update --web-download
            if ($LASTEXITCODE -ne 0) {
                throw "WSL update failed from both Microsoft package sources. Review the prerequisite log."
            }
        }
        $wslVersion = Get-WgWslVersion -WslPath $wsl
    }
    if ($null -eq $wslVersion -or $wslVersion -lt [version]"2.1.5") {
        throw "Docker Desktop requires WSL 2.1.5 or newer; detected version: $wslVersion"
    }
    Write-Host "WSL version: $wslVersion"
    & $wsl --set-default-version 2
    if ($LASTEXITCODE -ne 0) { throw "Unable to set WSL 2 as the default." }
    Write-State -Phase "installing-docker"

    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    $programFiles = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles)
    if (-not $localAppData) { throw "The current-user LocalAppData path is unavailable." }
    $allUserDesktop = if ($programFiles) { Join-Path $programFiles "Docker\Docker\Docker Desktop.exe" } else { "" }
    $perUserDesktopCandidates = @((Join-Path $localAppData "Programs\DockerDesktop\Docker Desktop.exe"))
    if (
        $allUserDesktop -and
        (Test-Path -LiteralPath $allUserDesktop -PathType Leaf) -and
        -not ($perUserDesktopCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    ) {
        throw "An all-user Docker Desktop installation already exists. Switching it to per-user mode can affect existing Docker data and requires an explicit user decision."
    }

    $dockerDesktop = $null
    $dockerCli = $null
    $desktopEvidence = $null
    try {
        $dockerDesktop = Get-DockerDesktopPath
        if ($dockerDesktop) { $desktopEvidence = Get-WgDockerBinaryEvidence -Path $dockerDesktop -Kind "Desktop" }
    }
    catch { Write-Warning "The existing Docker Desktop binary is untrusted, obsolete, or damaged; a signed repair/upgrade is required." }
    try { $dockerCli = Get-DockerCliPath }
    catch { Write-Warning "The existing Docker CLI is untrusted, obsolete, or damaged; a signed repair/upgrade is required." }
    $null = Assert-WgRunningDockerDesktopOwnership -ExpectedPath ([string]$dockerDesktop)

    $installer = $null
    try {
        $installer = Get-OfficialDockerInstaller
        $installerEvidence = Get-WgDockerBinaryEvidence -Path $installer -Kind "Installer"
        $needsInstall = -not $dockerDesktop -or -not $dockerCli -or $desktopEvidence.Version -lt $installerEvidence.Version
        if ($needsInstall) {
            $null = Assert-WgRunningDockerDesktopOwnership -ExpectedPath ([string]$dockerDesktop)
            Assert-WgNoActiveDockerWorkloadsForInstaller -DockerCli ([string]$dockerCli)
            $installerLog = Join-Path $logDir "docker-desktop-install.log"
            "Started at $((Get-Date).ToString('o'))" | Set-Content -LiteralPath $installerLog -Encoding UTF8
            "Reason: missing, damaged, incomplete, or older than official version $($installerEvidence.Version)" | Add-Content -LiteralPath $installerLog -Encoding UTF8
            $installArguments = @("install", "--user", "--accept-license", "--backend=wsl-2", "--no-windows-containers")
            $installProcess = Start-Process -FilePath $installer -ArgumentList $installArguments -Wait -PassThru -WindowStyle Hidden
            "Exit code: $($installProcess.ExitCode)" | Add-Content -LiteralPath $installerLog -Encoding UTF8
            if ($installProcess.ExitCode -ne 0) { throw "Docker Desktop installer failed with exit code $($installProcess.ExitCode)." }
        }
        else {
            Write-Host "Installed Docker Desktop $($desktopEvidence.Version) is at least as new as official installer $($installerEvidence.Version)."
        }
    }
    finally {
        if ($installer) {
            if (
                (Test-Path -LiteralPath $installer -PathType Leaf) -and
                [string]::Equals([IO.Path]::GetFullPath($installer), [IO.Path]::GetFullPath($installerPath), [StringComparison]::OrdinalIgnoreCase)
            ) {
                Write-Host "Retaining the recently verified Docker installer for bounded local recovery."
            }
        }
    }
    $dockerDesktop = Get-DockerDesktopPath
    $dockerCli = Get-DockerCliPath
    if (-not $dockerDesktop -or -not $dockerCli) {
        throw "Docker Desktop or its trusted bundled CLI was not found after the official install/repair completed."
    }
    $desktopEvidence = Get-WgDockerBinaryEvidence -Path $dockerDesktop -Kind "Desktop"
    if ($desktopEvidence.Version -lt $installerEvidence.Version) {
        throw "Docker Desktop remained older than the freshly verified official installer after upgrade/repair."
    }
    $expectedPerUserPrefix = [IO.Path]::GetFullPath((Join-Path $localAppData "Programs\DockerDesktop")).TrimEnd("\") + "\"
    if (-not $dockerDesktop.StartsWith($expectedPerUserPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Docker Desktop was not installed in the required current-user location."
    }
    Write-Host "Docker Desktop path: $dockerDesktop (version $($desktopEvidence.Version))"

    Assert-WgNoDockerClientOverrides
    Write-State -Phase "starting-docker"
    $desktopProcesses = @(Assert-WgRunningDockerDesktopOwnership -ExpectedPath $dockerDesktop)
    if ($desktopProcesses.Count -eq 0) {
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    }
    $deadline = (Get-Date).AddSeconds($EngineTimeoutSeconds)
    $dockerCli = $null
    $dockerTarget = $null
    $serverReady = $false
    do {
        $dockerCli = Get-DockerCliPath
        if ($dockerCli) {
            try {
                $dockerTarget = Get-LocalDockerTarget -DockerCli $dockerCli
                $serverReady = Test-WgDockerEngineReady `
                    -Docker $dockerCli -Endpoint $dockerTarget.Endpoint
            }
            catch {
                if ($_.Exception.Message -notmatch "^Unable to (determine|inspect)") { throw }
                $serverReady = $false
            }
        }
        if (-not $serverReady) { Start-Sleep -Seconds 5 }
    } while (-not $serverReady -and (Get-Date) -lt $deadline)
    if (-not $serverReady) { throw "Docker Engine did not become ready within $EngineTimeoutSeconds seconds." }

    $dockerTarget = Get-LocalDockerTarget -DockerCli $dockerCli
    $backendEvidence = Get-WgDockerDesktopWslBackendEvidence
    $confirmedWslVersion = Get-WgWslVersion -WslPath $wsl
    if ($null -eq $confirmedWslVersion -or $confirmedWslVersion -lt [version]"2.1.5") {
        throw "WSL 2.1.5 or newer was not available while validating the Docker Desktop WSL2 backend."
    }
    Assert-WgNoDockerTcp2375Listener
    $plugin = Get-WgTrustedDockerPluginConfig
    Invoke-Checked -Label "Docker Compose plugin" -FilePath $dockerCli -Arguments @("--config", $plugin.ConfigDirectory, "--host", $dockerTarget.Endpoint, "compose", "version")
    Write-State -Phase "hello-world"
    Invoke-Checked -Label "Docker hello-world" -FilePath $dockerCli -Arguments @("--config", $plugin.ConfigDirectory, "--host", $dockerTarget.Endpoint, "run", "--rm", "hello-world")
    $runtimeSecurity = Assert-WgDockerRuntimeSecurity -Docker $dockerCli -Endpoint $dockerTarget.Endpoint
    $wslRuntimeEvidence = Get-WgDockerDesktopWslRuntimeEvidence -WslPath $wsl
    Write-Host "Docker Desktop security: OSType=$($runtimeSecurity.OSType), WSL2=$($wslRuntimeEvidence.Distribution)/v$($wslRuntimeEvidence.Version)/running, TCP2375=false, Kubernetes=false (settings: $($backendEvidence.SettingsPath); WSL: $confirmedWslVersion)"

    $envPath = Ensure-WgEnvironment
    $composeBaseArguments = @(Get-WgComposeBaseArguments -Endpoint $dockerTarget.Endpoint)
    Assert-WgComposeOwnership -Docker $dockerCli -Endpoint $dockerTarget.Endpoint
    Invoke-Checked -Label "Stop prior WhaleGuard containers" -FilePath $dockerCli -Arguments ($composeBaseArguments + @("down", "--remove-orphans")) -WorkingDirectory $projectRoot
    Stop-ProjectLoopbackProcesses
    Write-State -Phase "building-whaleguard"
    $powershellExe = Get-WgWindowsSystemExecutable -RelativePath "WindowsPowerShell\v1.0\powershell.exe"
    Invoke-Checked -Label "Start WhaleGuard Docker stack" -FilePath $powershellExe -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "start-whaleguard.ps1"), "-NoBrowser", "-TimeoutSeconds", "600") -WorkingDirectory $projectRoot

    Write-State -Phase "verifying-whaleguard"
    $verifyArguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "verify-all.ps1"), "-SkipInstall")
    Invoke-Checked -Label "Complete WhaleGuard verification" -FilePath $powershellExe -Arguments $verifyArguments -WorkingDirectory $projectRoot

    $persistenceScript = Join-Path $PSScriptRoot "verify-persistence.ps1"
    Write-State -Phase "verifying-restart-persistence"
    Assert-WgComposeOwnership -Docker $dockerCli -Endpoint $dockerTarget.Endpoint
    Invoke-Checked -Label "Restart WhaleGuard containers" -FilePath $dockerCli -Arguments ($composeBaseArguments + @("restart")) -WorkingDirectory $projectRoot
    Invoke-Checked -Label "Verify persistence after restart" -FilePath $powershellExe -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $persistenceScript, "-Phase", "restart") -WorkingDirectory $projectRoot

    Write-State -Phase "verifying-down-up-persistence"
    Assert-WgComposeOwnership -Docker $dockerCli -Endpoint $dockerTarget.Endpoint
    Invoke-Checked -Label "Stop WhaleGuard without deleting volumes" -FilePath $dockerCli -Arguments ($composeBaseArguments + @("down")) -WorkingDirectory $projectRoot
    Invoke-Checked -Label "Start WhaleGuard from retained volumes" -FilePath $dockerCli -Arguments ($composeBaseArguments + @("up", "-d")) -WorkingDirectory $projectRoot
    Invoke-Checked -Label "Verify persistence after down/up" -FilePath $powershellExe -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $persistenceScript, "-Phase", "down-up") -WorkingDirectory $projectRoot

    Remove-WgAutomaticResume
    Write-State -Phase "completed" -Detail "Docker Desktop, hello-world, eight-service startup, full product verification, RQ consumption, and restart/down-up persistence completed."
    Write-Host "WHALEGUARD_DOCKER_SETUP_COMPLETE"
}
catch {
    Write-State -Phase "failed" -Detail $_.Exception.Message
    if ($AutoResume -and $resumeAttempt -lt 3) {
        Write-Warning "The crash-safe current-user startup entry remains registered (attempt $resumeAttempt of 3)."
    }
    elseif ($AutoResume) {
        Remove-WgAutomaticResume
        Write-Warning "Automatic resume reached its three-attempt limit and was removed."
    }
    Write-Error "WHALEGUARD_DOCKER_SETUP_FAILED: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($mutexAcquired) { $setupMutex.ReleaseMutex() }
    $setupMutex.Dispose()
}

exit 0
