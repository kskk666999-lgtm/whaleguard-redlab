Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:WgLogPath = $null

function Get-WgRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Get-WgWindowsSystemExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("WindowsPowerShell\v1.0\powershell.exe", "wsl.exe", "dism.exe")]
        [string]$RelativePath
    )

    $systemDirectory = [IO.Path]::GetFullPath([Environment]::SystemDirectory).TrimEnd("\") + "\"
    $candidate = [IO.Path]::GetFullPath((Join-Path $systemDirectory $RelativePath))
    if (-not $candidate.StartsWith($systemDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The Windows system executable escaped the real System32 directory."
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "A required Windows system executable is missing: $candidate"
    }
    if (((Get-Item -LiteralPath $candidate).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "A Windows system executable cannot be a reparse point."
    }
    return $candidate
}

function Invoke-WgExternalCommandToHost {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 2>&1 | Out-Host
        $exitCode = [int]$LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $exitCode
}

function Assert-WgNoReparsePointInPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    try { $item = Get-Item -LiteralPath $resolvedPath -Force -ErrorAction Stop }
    catch { throw "A trusted path component could not be inspected: $resolvedPath" }
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "A trusted path cannot contain a symbolic link, junction, or other reparse point."
        }
        if ($item -is [IO.FileInfo]) { $item = $item.Directory }
        else { $item = $item.Parent }
    }
}

function Assert-WgContainerHostCompatibility {
    try {
        $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    }
    catch {
        throw "Windows build information could not be verified; refusing to enable container prerequisites."
    }
    $buildNumber = 0
    if (-not [int]::TryParse([string]$operatingSystem.BuildNumber, [ref]$buildNumber)) {
        throw "Windows build information is invalid; refusing to enable container prerequisites."
    }
    if ($buildNumber -lt 26100) {
        throw "Windows build $buildNumber is outside the current Docker-supported servicing baseline. Upgrade Windows before enabling the WSL2 backend."
    }

    $uninstallRoots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    $virtualBoxVersions = @()
    foreach ($uninstallRoot in $uninstallRoots) {
        try {
            if (-not (Test-Path -LiteralPath $uninstallRoot -ErrorAction Stop)) { continue }
            $installedApplications = @(
                Get-ChildItem -LiteralPath $uninstallRoot -ErrorAction Stop |
                    Get-ItemProperty -ErrorAction Stop
            )
        }
        catch {
            throw "Installed application inventory could not be verified; refusing to enable the WSL2 hypervisor."
        }
        foreach ($installedApplication in @($installedApplications)) {
            if ($null -eq $installedApplication) { continue }
            $propertyNames = @($installedApplication.PSObject.Properties.Name)
            if (-not ($propertyNames -contains "DisplayName")) { continue }
            $displayName = [string]$installedApplication.DisplayName
            $isVirtualBox = (
                $displayName.StartsWith("Oracle VM VirtualBox", [StringComparison]::OrdinalIgnoreCase) -or
                $displayName.StartsWith("Oracle VirtualBox", [StringComparison]::OrdinalIgnoreCase)
            )
            if (-not $isVirtualBox) { continue }
            if (-not ($propertyNames -contains "DisplayVersion")) {
                throw "An installed VirtualBox version could not be verified. Upgrade or remove VirtualBox before continuing."
            }
            $versionMatch = [regex]::Match([string]$installedApplication.DisplayVersion, "(?<![0-9])([0-9]+(?:\.[0-9]+)+)")
            if (-not $versionMatch.Success) {
                throw "An installed VirtualBox version could not be verified. Upgrade or remove VirtualBox before continuing."
            }
            try { $virtualBoxVersion = [version]$versionMatch.Groups[1].Value }
            catch { throw "An installed VirtualBox version could not be verified. Upgrade or remove VirtualBox before continuing." }
            $virtualBoxVersions += $virtualBoxVersion
            if ($virtualBoxVersion -lt [version]"6.0") {
                throw "VirtualBox $virtualBoxVersion is incompatible with the WSL2 hypervisor. Upgrade or remove VirtualBox before continuing."
            }
        }
    }
    return [PSCustomObject]@{
        BuildNumber = $buildNumber
        VirtualBoxVersions = @($virtualBoxVersions)
    }
}

function Get-WgAutomaticResumeShortcutPath {
    $startupDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
    if (-not $startupDirectory -or -not (Test-Path -LiteralPath $startupDirectory -PathType Container)) {
        throw "The current-user Startup directory is unavailable; automatic resume cannot be registered safely."
    }
    return (Join-Path $startupDirectory "WhaleGuardDockerSetupResume.lnk")
}

function Get-WgAutomaticResumeStatePath {
    if (-not $env:LOCALAPPDATA) {
        throw "LOCALAPPDATA is unavailable; automatic resume cannot be bounded safely."
    }
    return (Join-Path $env:LOCALAPPDATA "WhaleGuardRedLab\DockerSetup\auto-resume.json")
}

function Remove-WgAutomaticResume {
    $runOncePath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
    $runOnce = Get-ItemProperty -Path $runOncePath -ErrorAction SilentlyContinue
    if ($runOnce) {
        foreach ($legacyName in @("WhaleGuardDockerSetupResume", "!WhaleGuardDockerSetupResume")) {
            if (@($runOnce.PSObject.Properties.Name) -contains $legacyName) {
                Remove-ItemProperty -Path $runOncePath -Name $legacyName -ErrorAction SilentlyContinue
            }
        }
    }

    $shortcutPath = Get-WgAutomaticResumeShortcutPath
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        Remove-Item -LiteralPath $shortcutPath -Force
    }
    $automaticResumeState = Get-WgAutomaticResumeStatePath
    if (Test-Path -LiteralPath $automaticResumeState -PathType Leaf) {
        Remove-Item -LiteralPath $automaticResumeState -Force
    }
}

function Register-WgAutomaticResume {
    param([Parameter(Mandatory = $true)][string]$ResumeScript)

    $resolvedResumeScript = [IO.Path]::GetFullPath($ResumeScript)
    if (-not (Test-Path -LiteralPath $resolvedResumeScript -PathType Leaf)) {
        throw "The automatic-resume script does not exist at the expected path."
    }
    Remove-WgAutomaticResume
    $shortcutPath = Get-WgAutomaticResumeShortcutPath
    $automaticResumeState = Get-WgAutomaticResumeStatePath
    $automaticResumeDirectory = Split-Path $automaticResumeState -Parent
    New-Item -ItemType Directory -Path $automaticResumeDirectory -Force | Out-Null
    $resumeState = [ordered]@{
        schema_version = 1
        registered_at = (Get-Date).ToString("o")
        resume_attempt = 0
        max_attempts = 3
        resume_script = $resolvedResumeScript
    }
    $temporaryState = "$automaticResumeState.tmp"
    $resumeState | ConvertTo-Json | Set-Content -LiteralPath $temporaryState -Encoding UTF8
    Move-Item -LiteralPath $temporaryState -Destination $automaticResumeState -Force

    $powershellExe = Get-WgWindowsSystemExecutable -RelativePath "WindowsPowerShell\v1.0\powershell.exe"
    $bootstrap = @'
$ErrorActionPreference = "Stop"
$statePath = '__STATE_PATH__'
$shortcutPath = '__SHORTCUT_PATH__'
$resumeScript = '__RESUME_SCRIPT__'
$powershellExe = '__POWERSHELL_EXE__'
try {
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $attempt = [int]$state.resume_attempt
    $maximum = [int]$state.max_attempts
    if ([int]$state.schema_version -ne 1 -or $maximum -ne 3 -or $attempt -lt 0 -or $attempt -ge $maximum) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
        exit 1
    }
    $attempt += 1
    $state.resume_attempt = $attempt
    $temporaryState = "$statePath.tmp"
    $state | ConvertTo-Json | Set-Content -LiteralPath $temporaryState -Encoding UTF8
    Move-Item -LiteralPath $temporaryState -Destination $statePath -Force
    if ($attempt -ge $maximum) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath $resumeScript -PathType Leaf)) { exit 1 }
    & $powershellExe -NoProfile -ExecutionPolicy Bypass -File $resumeScript -AutoResume
    $childExitCode = $LASTEXITCODE
    if ($childExitCode -eq 0) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    }
    exit $childExitCode
}
catch {
    Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    exit 1
}
'@
    $bootstrap = $bootstrap.Replace("__STATE_PATH__", $automaticResumeState.Replace("'", "''"))
    $bootstrap = $bootstrap.Replace("__SHORTCUT_PATH__", $shortcutPath.Replace("'", "''"))
    $bootstrap = $bootstrap.Replace("__RESUME_SCRIPT__", $resolvedResumeScript.Replace("'", "''"))
    $bootstrap = $bootstrap.Replace("__POWERSHELL_EXE__", $powershellExe.Replace("'", "''"))
    $tokens = $null
    $parseIssues = $null
    [System.Management.Automation.Language.Parser]::ParseInput($bootstrap, [ref]$tokens, [ref]$parseIssues) | Out-Null
    if ($parseIssues.Count -gt 0) {
        Remove-Item -LiteralPath $automaticResumeState -Force -ErrorAction SilentlyContinue
        throw "The bounded automatic-resume bootstrap failed validation."
    }
    $encodedBootstrap = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershellExe
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encodedBootstrap"
    $shortcut.WorkingDirectory = Get-WgRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = "Resume the bounded WhaleGuard Docker setup after sign-in"
    $shortcut.Save()
    if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
        throw "The current-user automatic-resume shortcut could not be created."
    }
    return $shortcutPath
}

function Invoke-WgWslVersionProbe {
    param([Parameter(Mandatory = $true)][string]$WslPath)

    if (-not (Test-Path -LiteralPath $WslPath -PathType Leaf)) {
        return [PSCustomObject]@{ ExitCode = -1; Output = "" }
    }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $WslPath
    $startInfo.Arguments = "--version"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $unicode = New-Object System.Text.UnicodeEncoding($false, $false)
    $startInfo.StandardOutputEncoding = $unicode
    $startInfo.StandardErrorEncoding = $unicode
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw "Unable to start wsl.exe version probe." }
        $standardOutput = $process.StandardOutput.ReadToEnd()
        $standardError = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        return [PSCustomObject]@{
            ExitCode = $process.ExitCode
            Output = ($standardOutput + [Environment]::NewLine + $standardError).Trim()
        }
    }
    finally {
        $process.Dispose()
    }
}

function ConvertFrom-WgWslVersionOutput {
    param([AllowEmptyString()][string]$Output)

    $match = [regex]::Match(
        $Output,
        "(?im)^\s*WSL[^0-9]*([0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)"
    )
    if (-not $match.Success) { return $null }
    try { return [version]$match.Groups[1].Value } catch { return $null }
}

function Get-WgWslVersion {
    param([Parameter(Mandatory = $true)][string]$WslPath)

    $probe = Invoke-WgWslVersionProbe -WslPath $WslPath
    if ($probe.ExitCode -ne 0) { return $null }
    return ConvertFrom-WgWslVersionOutput -Output ([string]$probe.Output)
}

function Get-WgDockerDesktopWslBackendEvidence {
    param([string[]]$SettingsPaths = @())

    if ($SettingsPaths.Count -eq 0) {
        $roamingAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)
        if (-not $roamingAppData) {
            throw "The canonical current-user roaming application-data path is unavailable."
        }
        $SettingsPaths = @((Join-Path $roamingAppData "Docker\settings-store.json"))
    }
    $settingsPath = $SettingsPaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $settingsPath) {
        throw "Docker Desktop settings-store.json was not found; WSL2 backend cannot be proven."
    }
    $settingsPath = [IO.Path]::GetFullPath($settingsPath)
    Assert-WgNoReparsePointInPath -Path $settingsPath
    try { $settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json }
    catch { throw "Docker Desktop settings could not be parsed; WSL2 backend cannot be proven." }
    function Read-BooleanSetting {
        param(
            [Parameter(Mandatory = $true)][string[]]$Names,
            [Parameter(Mandatory = $true)][bool]$Default
        )
        foreach ($settingName in $Names) {
            $property = $settings.PSObject.Properties |
                Where-Object { [string]::Equals($_.Name, $settingName, [StringComparison]::OrdinalIgnoreCase) } |
                Select-Object -First 1
            if (-not $property) { continue }
            $value = $property.Value
            if ($value -is [PSCustomObject] -and $value.PSObject.Properties["value"]) {
                $value = $value.value
            }
            elseif ($value -is [PSCustomObject] -and $value.PSObject.Properties["enabled"]) {
                $value = $value.enabled
            }
            if ($value -isnot [bool] -and [string]$value -notin @("true", "false")) {
                throw "Docker Desktop setting $settingName is not an explicit boolean."
            }
            return [PSCustomObject]@{
                Present = $true
                Name = $settingName
                Value = ($value -eq $true -or [string]$value -eq "true")
            }
        }
        return [PSCustomObject]@{ Present = $false; Name = $Names[0]; Value = $Default }
    }

    # Fresh settings stores can omit defaults. Explicit unsafe overrides still
    # fail closed; runtime checks independently prove WSL2/Linux and no TCP 2375.
    $wslSetting = Read-BooleanSetting -Names @("wslEngineEnabled") -Default $true
    $tcpSetting = Read-BooleanSetting -Names @("exposeDockerAPIOnTCP2375") -Default $false
    $kubernetesSetting = Read-BooleanSetting -Names @("kubernetesEnabled", "kubernetes") -Default $false
    if ($wslSetting.Present -and -not $wslSetting.Value) {
        throw "Docker Desktop is explicitly configured not to use the WSL2 engine."
    }
    if ($tcpSetting.Value) { throw "Docker Desktop unsafe setting is enabled: $($tcpSetting.Name)" }
    if ($kubernetesSetting.Value) { throw "Docker Desktop unsafe setting is enabled: $($kubernetesSetting.Name)" }
    return [PSCustomObject]@{
        SettingsPath = [IO.Path]::GetFullPath($settingsPath)
        WslEngineEnabled = $wslSetting.Value
        WslSettingPresent = $wslSetting.Present
        Tcp2375Enabled = $tcpSetting.Value
        Tcp2375SettingPresent = $tcpSetting.Present
        KubernetesEnabled = $kubernetesSetting.Value
        KubernetesSettingPresent = $kubernetesSetting.Present
    }
}

function Test-WgDockerDesktopWslRuntimeOutput {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$VerboseOutput,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$RunningOutput
    )

    $versionMatch = [regex]::Match($VerboseOutput, "(?im)^\s*\*?\s*(docker-desktop)\s+\S+\s+(2)\s*$")
    $runningMatch = [regex]::Match($RunningOutput, "(?im)^\s*\*?\s*(docker-desktop)\s*$")
    return $versionMatch.Success -and $runningMatch.Success
}

function Get-WgDockerDesktopWslRuntimeEvidence {
    param([Parameter(Mandatory = $true)][string]$WslPath)

    if (-not (Test-Path -LiteralPath $WslPath -PathType Leaf)) {
        throw "wsl.exe is unavailable; Docker Desktop WSL2 runtime cannot be proven."
    }
    function Invoke-WslList {
        param([Parameter(Mandatory = $true)][string]$Arguments)
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $WslPath
        $startInfo.Arguments = $Arguments
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $unicode = New-Object System.Text.UnicodeEncoding($false, $false)
        $startInfo.StandardOutputEncoding = $unicode
        $startInfo.StandardErrorEncoding = $unicode
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        try {
            if (-not $process.Start()) { throw "Unable to start the WSL runtime probe." }
            $output = $process.StandardOutput.ReadToEnd() + [Environment]::NewLine + $process.StandardError.ReadToEnd()
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) {
                throw "Unable to list WSL distributions for Docker Desktop runtime validation."
            }
            return $output
        }
        finally { $process.Dispose() }
    }

    $verboseOutput = Invoke-WslList -Arguments "--list --verbose"
    $runningOutput = Invoke-WslList -Arguments "--list --running --quiet"
    if (-not (Test-WgDockerDesktopWslRuntimeOutput -VerboseOutput $verboseOutput -RunningOutput $runningOutput)) {
        throw "The Docker Desktop WSL distribution was not confirmed as WSL version 2."
    }
    return [PSCustomObject]@{ Distribution = "docker-desktop"; Version = 2; Running = $true }
}

function Protect-WgLogText {
    param([AllowEmptyString()][string]$Text)

    if ($null -eq $Text) { return "" }
    $safe = $Text
    $safe = [regex]::Replace(
        $safe,
        '(?i)\b([a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s/]+@',
        '$1[REDACTED]@'
    )
    $safe = [regex]::Replace($safe, '(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]')
    $safe = [regex]::Replace(
        $safe,
        '(?i)(["'']?(?:password|passwd|api[_-]?key|authorization|cookie|jwt(?:[_-]?secret)?|token|secret|encryption[_-]?secret)["'']?\s*[:=]\s*["'']?)[^"''\s,}]+',
        '$1[REDACTED]'
    )
    $safe = [regex]::Replace($safe, '(?i)\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED_API_KEY]')
    return $safe
}

function Start-WgOperationLog {
    param([Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Name)

    try {
        $root = Get-WgRoot
        $logDirectory = Join-Path $root ".local\logs"
        if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
            New-Item -ItemType Directory -Path $logDirectory | Out-Null
        }
        $stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
        $script:WgLogPath = Join-Path $logDirectory ("{0}-{1}-{2}.log" -f $Name, $stamp, $PID)
        [System.IO.File]::WriteAllText(
            $script:WgLogPath,
            "WhaleGuard operation=$Name started_utc=$([DateTime]::UtcNow.ToString('o'))$([Environment]::NewLine)",
            (New-Object System.Text.UTF8Encoding($false))
        )

        $oldLogs = @(Get-ChildItem -LiteralPath $logDirectory -File -Filter "$Name-*.log" |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -Skip 20)
        foreach ($oldLog in $oldLogs) {
            $resolvedLog = [System.IO.Path]::GetFullPath($oldLog.FullName)
            if ([System.IO.Path]::GetDirectoryName($resolvedLog) -eq $logDirectory) {
                Remove-Item -LiteralPath $resolvedLog -Force
            }
        }
    }
    catch {
        $script:WgLogPath = $null
        Write-Warning "WhaleGuard could not initialize its local operation log."
    }
    return $script:WgLogPath
}

function Get-WgOperationLogPath {
    return $script:WgLogPath
}

function Write-WgMessage {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Message,
        [ValidateSet("DEBUG", "INFO", "WARN", "ERROR")][string]$Level = "INFO",
        [string]$Color = ""
    )

    $safe = Protect-WgLogText -Text $Message
    if ($Color) {
        Write-Host $safe -ForegroundColor $Color
    }
    else {
        Write-Host $safe
    }
    if ($script:WgLogPath) {
        try {
            $line = "{0} [{1}] {2}{3}" -f [DateTime]::UtcNow.ToString("o"), $Level, $safe, [Environment]::NewLine
            [System.IO.File]::AppendAllText(
                $script:WgLogPath,
                $line,
                (New-Object System.Text.UTF8Encoding($false))
            )
        }
        catch {
            # Logging must never turn a recoverable product operation into a failure.
        }
    }
}

function New-WgRandomUrlSafeValue {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(16, 256)][int]$ByteCount,
        [switch]$KeepPadding
    )

    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    $value = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
    if (-not $KeepPadding) { $value = $value.TrimEnd([char]"=") }
    return $value
}

function New-WgEnvironmentFile {
    param(
        [Parameter(Mandatory = $true)][string]$ExamplePath,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )

    $resolvedExample = [System.IO.Path]::GetFullPath($ExamplePath)
    $resolvedTarget = [System.IO.Path]::GetFullPath($TargetPath)
    if (Test-Path -LiteralPath $resolvedTarget -PathType Leaf) { return $resolvedTarget }
    if (-not (Test-Path -LiteralPath $resolvedExample -PathType Leaf)) {
        throw ".env.example was not found at the expected project path."
    }

    $targetDirectory = [System.IO.Path]::GetDirectoryName($resolvedTarget)
    if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
        throw "The target directory for .env does not exist."
    }
    $content = [System.IO.File]::ReadAllText($resolvedExample, [System.Text.Encoding]::UTF8)
    $postgresPassword = New-WgRandomUrlSafeValue -ByteCount 24
    $redisPassword = New-WgRandomUrlSafeValue -ByteCount 24
    $replacements = @{
        "GENERATE_JWT_SECRET" = New-WgRandomUrlSafeValue -ByteCount 48
        "GENERATE_FERNET_KEY" = New-WgRandomUrlSafeValue -ByteCount 32 -KeepPadding
        "GENERATE_WORKER_TOKEN" = New-WgRandomUrlSafeValue -ByteCount 32
        "GENERATE_POSTGRES_PASSWORD" = $postgresPassword
        "GENERATE_REDIS_PASSWORD" = $redisPassword
    }
    foreach ($marker in $replacements.Keys) {
        if (-not $content.Contains($marker)) { throw "Required environment marker is missing: $marker" }
        $content = $content.Replace($marker, [string]$replacements[$marker])
    }
    if ($content -match "GENERATE_[A-Z0-9_]+") {
        throw "The generated environment still contains an unresolved secret marker."
    }

    $temporaryPath = Join-Path $targetDirectory (".{0}.env.tmp" -f [Guid]::NewGuid().ToString("N"))
    try {
        [System.IO.File]::WriteAllText(
            $temporaryPath,
            $content,
            (New-Object System.Text.UTF8Encoding($false))
        )
        try {
            [System.IO.File]::Move($temporaryPath, $resolvedTarget)
        }
        catch {
            if (Test-Path -LiteralPath $resolvedTarget -PathType Leaf) {
                return $resolvedTarget
            }
            throw
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
    return $resolvedTarget
}

function Ensure-WgEnvironment {
    $root = Get-WgRoot
    $envPath = Join-Path $root ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        $null = New-WgEnvironmentFile -ExamplePath (Join-Path $root ".env.example") -TargetPath $envPath
        Write-WgMessage -Message "Generated a new local .env without exposing its secret values."
    }
    $localDir = Join-Path $root ".local"
    if (-not (Test-Path -LiteralPath $localDir -PathType Container)) {
        New-Item -ItemType Directory -Path $localDir | Out-Null
    }
    return $envPath
}

function Test-WgDockerBinaryMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$SignatureStatus,
        [Parameter(Mandatory = $true)][string]$SignerSubject,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ProductName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$ProductVersion,
        [Parameter(Mandatory = $true)][ValidateSet("Desktop", "Cli", "Installer", "Compose")][string]$Kind
    )

    if ($SignatureStatus -ne "Valid") { return $false }
    if ($SignerSubject -notmatch "(?i)(^|,\s*)CN=Docker Inc\.?(,|$)") { return $false }
    $allowedProducts = switch ($Kind) {
        "Desktop" { @("Docker Desktop") }
        "Cli" { @("Docker", "Docker CLI", "Docker Client") }
        "Installer" { @("Docker Desktop", "Docker Desktop Installer") }
        "Compose" { @("Docker", "Docker Compose", "Docker Compose CLI", "Docker CLI Plugin") }
    }
    if ($ProductName -notin $allowedProducts) { return $false }
    $versionMatch = [regex]::Match($ProductVersion, "(?<![0-9])([0-9]+\.[0-9]+(?:\.[0-9]+){0,2})(?![0-9])")
    if (-not $versionMatch.Success) { return $false }
    try { $version = [version]$versionMatch.Groups[1].Value } catch { return $false }
    $minimumVersion = switch ($Kind) {
        "Cli" { [version]"29.2.0" }
        "Compose" { [version]"5.1.0" }
        default { [version]"4.88.1" }
    }
    return $version -ge $minimumVersion
}

function ConvertTo-WgDockerProductVersion {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)

    $versionMatch = [regex]::Match($Value, "(?<![0-9])([0-9]+\.[0-9]+(?:\.[0-9]+){0,2})(?![0-9])")
    if (-not $versionMatch.Success) { throw "Docker product version metadata is invalid." }
    try { return [version]$versionMatch.Groups[1].Value }
    catch { throw "Docker product version metadata is invalid." }
}

function Get-WgDockerBinaryEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet("Desktop", "Cli", "Installer", "Compose")][string]$Kind
    )

    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
        throw "Docker $Kind binary was not found at its canonical path."
    }
    Assert-WgNoReparsePointInPath -Path $resolvedPath
    $item = Get-Item -LiteralPath $resolvedPath
    $signature = Get-AuthenticodeSignature -LiteralPath $resolvedPath
    $signerSubject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
    $productName = [string]$item.VersionInfo.ProductName
    $productVersion = [string]$item.VersionInfo.ProductVersion
    if (-not $productVersion) { $productVersion = [string]$item.VersionInfo.FileVersion }
    if (-not (Test-WgDockerBinaryMetadata -SignatureStatus ([string]$signature.Status) -SignerSubject $signerSubject -ProductName $productName -ProductVersion $productVersion -Kind $Kind)) {
        throw "Docker $Kind binary failed publisher, product-name, or version validation."
    }
    return [PSCustomObject]@{
        Path = $resolvedPath
        Kind = $Kind
        ProductName = $productName
        ProductVersion = $productVersion
        Version = ConvertTo-WgDockerProductVersion -Value $productVersion
        SignerSubject = $signerSubject
    }
}

function Get-WgCanonicalDockerInstallRoots {
    $roots = @()
    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ($localAppData) {
        $roots += Join-Path $localAppData "Programs\DockerDesktop"
    }
    return @($roots | ForEach-Object { [IO.Path]::GetFullPath($_) } | Select-Object -Unique)
}

function Get-WgTrustedDockerBundleEvidence {
    foreach ($installRoot in Get-WgCanonicalDockerInstallRoots) {
        $desktopCandidate = Join-Path $installRoot "Docker Desktop.exe"
        if (-not (Test-Path -LiteralPath $desktopCandidate -PathType Leaf)) { continue }
        try {
            $desktop = Get-WgDockerBinaryEvidence -Path $desktopCandidate -Kind "Desktop"
            $cli = Get-WgDockerBinaryEvidence -Path (Join-Path $installRoot "resources\bin\docker.exe") -Kind "Cli"
            $compose = Get-WgDockerBinaryEvidence -Path (Join-Path $installRoot "resources\cli-plugins\docker-compose.exe") -Kind "Compose"
            return [PSCustomObject]@{
                InstallRoot = [IO.Path]::GetFullPath($installRoot)
                Desktop = $desktop
                Cli = $cli
                Compose = $compose
            }
        }
        catch {
            # A partial or obsolete per-user bundle must be repaired as one unit.
            continue
        }
    }
    return $null
}

function Find-WgTrustedDockerDesktopPath {
    $bundle = Get-WgTrustedDockerBundleEvidence
    if ($bundle) { return $bundle.Desktop.Path }
    return $null
}

function Find-WgTrustedDockerCliPath {
    $bundle = Get-WgTrustedDockerBundleEvidence
    if ($bundle) { return $bundle.Cli.Path }
    return $null
}

function Find-WgTrustedDockerComposePath {
    $bundle = Get-WgTrustedDockerBundleEvidence
    if ($bundle) { return $bundle.Compose.Path }
    return $null
}

function Assert-WgRunningDockerDesktopOwnership {
    param([AllowEmptyString()][string]$ExpectedPath = "")

    try {
        $processes = @(Get-CimInstance Win32_Process -Filter "Name='Docker Desktop.exe'" -ErrorAction Stop)
    }
    catch {
        throw "Running Docker Desktop ownership could not be verified; refusing to continue."
    }
    foreach ($desktopProcess in $processes) {
        $executablePath = [string]$desktopProcess.ExecutablePath
        if (-not $executablePath) {
            throw "A running Docker Desktop process has an unverifiable executable path; refusing to modify or attach to it."
        }
        if (
            -not $ExpectedPath -or
            -not [string]::Equals([IO.Path]::GetFullPath($executablePath), [IO.Path]::GetFullPath($ExpectedPath), [StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "A different or untrusted Docker Desktop installation is already running. Stopping or switching it requires an explicit user decision."
        }
    }
    return @($processes)
}

function Assert-WgNoActiveDockerWorkloadsForInstaller {
    param([AllowEmptyString()][string]$DockerCli = "")

    $runtimeProcessNames = @(
        "Docker Desktop.exe",
        "com.docker.backend.exe",
        "com.docker.build.exe",
        "dockerd.exe"
    )
    try {
        $runtimeProcesses = @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object { $runtimeProcessNames -contains [string]$_.Name }
        )
    }
    catch {
        throw "Docker runtime process state could not be verified; refusing an install, repair, or upgrade."
    }
    if ($runtimeProcesses.Count -gt 0) {
        throw "Docker Desktop or a Docker engine process is active. An install, repair, or upgrade could interrupt unrelated containers and requires an explicit user decision."
    }
    if (-not $DockerCli) { return }

    $target = Get-WgLocalDockerTarget -Docker $DockerCli
    $plugin = Get-WgTrustedDockerPluginConfig
    $runningContainers = @(
        & $DockerCli --config $plugin.ConfigDirectory --host $target.Endpoint ps --quiet 2>$null |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ }
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Docker container state could not be verified; refusing an install, repair, or upgrade."
    }
    if ($runningContainers.Count -gt 0) {
        throw "Running Docker containers were detected. An install, repair, or upgrade could interrupt unrelated workloads and requires an explicit user decision."
    }
}

function Get-WgTrustedDockerPluginConfig {
    $bundle = Get-WgTrustedDockerBundleEvidence
    if (-not $bundle) {
        throw "The Docker Desktop-bundled Compose plugin is missing or failed trust validation."
    }
    $composePath = $bundle.Compose.Path
    $configDirectory = Join-Path (Get-WgRoot) ".local\docker-cli-config"
    if (Test-Path -LiteralPath $configDirectory -PathType Container) {
        $directoryItem = Get-Item -LiteralPath $configDirectory
        if (($directoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "The managed Docker CLI config directory cannot be a reparse point."
        }
    }
    else {
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    }
    Assert-WgNoReparsePointInPath -Path $configDirectory
    $priorityPluginDirectory = Join-Path $configDirectory "cli-plugins"
    if (Test-Path -LiteralPath $priorityPluginDirectory) {
        throw "The managed Docker config contains a higher-priority cli-plugins path; refusing possible plugin shadowing."
    }
    $configPath = Join-Path $configDirectory "config.json"
    $temporaryPath = "$configPath.tmp"
    foreach ($managedFile in @($configPath, $temporaryPath)) {
        if (
            (Test-Path -LiteralPath $managedFile -PathType Leaf) -and
            ((Get-Item -LiteralPath $managedFile).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw "The managed Docker config file cannot be a reparse point."
        }
    }
    $config = [ordered]@{ cliPluginsExtraDirs = @((Split-Path $composePath -Parent)) }
    [IO.File]::WriteAllText(
        $temporaryPath,
        ($config | ConvertTo-Json -Depth 3),
        (New-Object Text.UTF8Encoding($false))
    )
    Move-Item -LiteralPath $temporaryPath -Destination $configPath -Force
    return [PSCustomObject]@{
        ConfigDirectory = [IO.Path]::GetFullPath($configDirectory)
        ComposePath = $composePath
    }
}

function Get-WgDocker {
    $docker = Find-WgTrustedDockerCliPath
    if (-not $docker) {
        throw "A trusted Docker Desktop CLI was not found at a canonical installation path."
    }
    return $docker
}

function Test-WgLocalDockerEndpoint {
    param([AllowEmptyString()][string]$Endpoint)

    if (-not $Endpoint) { return $false }
    return $Endpoint -in @(
        "npipe:////./pipe/docker_engine",
        "npipe:////./pipe/dockerDesktopLinuxEngine"
    )
}

function Test-WgProjectLoopbackProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][ValidateSet(3000, 8000, 8101, 8102, 8103)][int]$Port,
        [Parameter(Mandatory = $true)][string]$LocalAddress,
        [Parameter(Mandatory = $true)][string]$ProcessName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$CommandLine
    )

    if ($LocalAddress -notin @("127.0.0.1", "::1") -or -not $CommandLine) { return $false }
    $root = [IO.Path]::GetFullPath($ProjectRoot)
    $normalizedCommandLine = $CommandLine.Replace("/", "\")
    $hasExpectedPort = $CommandLine -match ("(?i)(?:--port(?:=|\s+)){0}(?:\s|$)" -f $Port)
    if (-not $hasExpectedPort) { return $false }

    if ($Port -eq 3000) {
        if ($ProcessName -ne "node.exe") { return $false }
        foreach ($entrypoint in @(
            (Join-Path $root "apps\web\node_modules\next\dist\bin\next"),
            (Join-Path $root "apps\web\node_modules\next\dist\server\lib\start-server.js")
        )) {
            $pattern = '(?i)(?:^|[\s"]){0}(?:$|[\s"])' -f [regex]::Escape($entrypoint)
            if ($normalizedCommandLine -match $pattern) { return $true }
        }
        return $false
    }

    if ($ProcessName -ne "python.exe") { return $false }
    $expectedModule = if ($Port -eq 8000) { "whaleguard_api.main:app" } else { "app.main:app" }
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    $pythonPattern = '(?i)^\s*"?{0}"?(?:\s|$)' -f [regex]::Escape($venvPython)
    return (
        $normalizedCommandLine -match $pythonPattern -and
        $CommandLine -match "(?i)-m\s+uvicorn" -and
        $CommandLine.Contains($expectedModule)
    )
}

function Assert-WgNoDockerTcp2375Listener {
    $command = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    if (-not $command) { throw "TCP 2375 exposure cannot be verified on this Windows host." }
    try {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 2375 -ErrorAction Stop)
    }
    catch {
        throw "TCP 2375 exposure could not be verified; refusing to continue."
    }
    if ($listeners.Count -gt 0) {
        throw "Unsafe Docker-compatible TCP port 2375 is listening on this host."
    }
}

function Assert-WgDockerRuntimeSecurity {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint
    )

    $osType = (& $Docker --host $Endpoint version --format "{{.Server.Os}}" 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $osType -ne "linux") {
        throw "Docker Desktop is not using the Linux containers backend."
    }
    Assert-WgNoDockerTcp2375Listener
    return [PSCustomObject]@{ OSType = $osType; Tcp2375Listening = $false }
}

function Assert-WgNoDockerClientOverrides {
    foreach ($variableName in @(
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_CLI_PLUGIN_EXTRA_DIRS",
        "COMPOSE_BAKE",
        "BUILDX_BAKE_ENTITLEMENTS_FS"
    )) {
        if ([Environment]::GetEnvironmentVariable($variableName)) {
            throw "$variableName overrides are blocked. Clear Docker client overrides and use the trusted local Docker Desktop installation."
        }
    }
    foreach ($environmentName in [Environment]::GetEnvironmentVariables().Keys) {
        if ([string]$environmentName -match "(?i)^BUILDX_BAKE_") {
            throw "$environmentName overrides are blocked. Clear Docker client overrides and use the trusted local Docker Desktop installation."
        }
    }
}

function Assert-WgSafeComposeEnvironmentFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "The required Compose environment file is missing."
    }
    $lineNumber = 0
    foreach ($line in [IO.File]::ReadAllLines([IO.Path]::GetFullPath($Path), [Text.Encoding]::UTF8)) {
        $lineNumber += 1
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $match = [regex]::Match($trimmed, "(?i)^(?:export\s+)?(?<name>[A-Z_][A-Z0-9_]*)\s*(?:=|:|$)")
        if (-not $match.Success) { continue }
        $name = $match.Groups["name"].Value
        if ($name -eq "COMPOSE_BAKE" -or $name -match "(?i)^BUILDX_BAKE_") {
            throw "Unsafe Docker build override $name is not allowed in the Compose environment file (line $lineNumber)."
        }
    }
}

function Get-WgLocalDockerTarget {
    param([string]$Docker = "")

    if (-not $Docker) { $Docker = Get-WgDocker }
    Assert-WgNoDockerClientOverrides

    $contextOutput = @(& $Docker context show 2>$null)
    if ($LASTEXITCODE -ne 0 -or $contextOutput.Count -eq 0) {
        throw "Unable to determine the active Docker context; refusing to continue."
    }
    $contextName = ([string]$contextOutput[0]).Trim()
    $endpointOutput = @(& $Docker context inspect $contextName --format "{{.Endpoints.docker.Host}}" 2>$null)
    if ($LASTEXITCODE -ne 0 -or $endpointOutput.Count -eq 0) {
        throw "Unable to inspect the active Docker context; refusing to continue."
    }
    $contextEndpoint = ([string]$endpointOutput[0]).Trim()
    if (-not (Test-WgLocalDockerEndpoint -Endpoint $contextEndpoint)) {
        throw "The active Docker context is not a local Windows named-pipe endpoint. Remote Docker operations are blocked."
    }
    return [PSCustomObject]@{
        ContextName = $contextName
        Endpoint = $contextEndpoint
    }
}

function Assert-WgLocalDockerContext {
    param([string]$Docker = "")

    return (Get-WgLocalDockerTarget -Docker $Docker).ContextName
}

function Get-WgComposeProjectName {
    $canonicalRoot = [IO.Path]::GetFullPath((Get-WgRoot)).TrimEnd(
        [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    ).ToLowerInvariant()
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonicalRoot))
    }
    finally {
        $hasher.Dispose()
    }
    $suffix = -join @($digest[0..5] | ForEach-Object { $_.ToString("x2") })
    return "whaleguard-redlab-$suffix"
}

function Get-WgComposeBaseArguments {
    param([Parameter(Mandatory = $true)][string]$Endpoint)

    $root = Get-WgRoot
    $envPath = Join-Path $root ".env"
    Assert-WgSafeComposeEnvironmentFile -Path $envPath
    $plugin = Get-WgTrustedDockerPluginConfig
    $projectName = Get-WgComposeProjectName
    return @(
        "--config", $plugin.ConfigDirectory,
        "--host", $Endpoint,
        "compose",
        "--project-name", $projectName,
        "--file", (Join-Path $root "docker-compose.yml"),
        "--env-file", $envPath
    )
}

function Assert-WgComposeOwnership {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint
    )

    $plugin = Get-WgTrustedDockerPluginConfig
    $projectName = Get-WgComposeProjectName
    $containerIds = @(& $Docker --config $plugin.ConfigDirectory --host $Endpoint ps --all --filter "label=com.docker.compose.project=$projectName" --format "{{.ID}}" 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "Unable to validate existing WhaleGuard Compose ownership." }
    $expectedRoot = [IO.Path]::GetFullPath((Get-WgRoot))
    foreach ($containerIdValue in $containerIds) {
        $containerId = ([string]$containerIdValue).Trim()
        if (-not $containerId) { continue }
        $workingDirectory = (& $Docker --config $plugin.ConfigDirectory --host $Endpoint inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' $containerId 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $workingDirectory) {
            throw "An existing $projectName container lacks verifiable Compose ownership."
        }
        try { $resolvedWorkingDirectory = [IO.Path]::GetFullPath($workingDirectory) }
        catch { throw "An existing $projectName container has an invalid working-directory label." }
        if (-not [string]::Equals($resolvedWorkingDirectory, $expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to modify a $projectName Compose project owned by another working directory."
        }
    }
}

function Assert-WgDockerEngine {
    $docker = Get-WgDocker
    $target = Get-WgLocalDockerTarget -Docker $docker
    & $docker --host $target.Endpoint version --format "{{.Server.Version}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Engine is not running. Start Docker Desktop and wait until it is ready."
    }
    $null = Assert-WgDockerRuntimeSecurity -Docker $docker -Endpoint $target.Endpoint
    $plugin = Get-WgTrustedDockerPluginConfig
    & $docker --config $plugin.ConfigDirectory --host $target.Endpoint compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "The validated Docker Desktop Compose plugin is unavailable. Update or repair Docker Desktop."
    }
    return $docker
}

function Get-WgPython {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Args = @("-3") } }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Args = @() } }
    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Args = @() } }
    throw "Python 3 was not found. Install Python 3.11 or newer."
}

function Get-WgEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Default
    )
    $envPath = Join-Path (Get-WgRoot) ".env"
    if (-not (Test-Path -LiteralPath $envPath)) { return $Default }
    $match = Get-Content -LiteralPath $envPath | Where-Object {
        $_ -match ("^" + [regex]::Escape($Name) + "=(.*)$")
    } | Select-Object -Last 1
    if ($match -and $match -match "^[^=]+=(.*)$" -and $Matches[1]) {
        return $Matches[1].Trim()
    }
    return $Default
}

function Test-WgHttp {
    param([Parameter(Mandatory = $true)][string]$Uri)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 4
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Test-WgApiReady {
    param([Parameter(Mandatory = $true)][string]$Uri)
    try {
        $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 4
        return $response.status -eq "ok" -and $response.database -eq "ok"
    }
    catch {
        return $false
    }
}

function Invoke-WgCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $docker = Get-WgDocker
    $target = Get-WgLocalDockerTarget -Docker $docker
    Assert-WgComposeOwnership -Docker $docker -Endpoint $target.Endpoint
    $baseArguments = @(Get-WgComposeBaseArguments -Endpoint $target.Endpoint)
    & $docker @baseArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

function Get-WgExpectedServices {
    return @("db", "redis", "api", "worker", "web", "mock-llm", "mock-agent", "mock-mcp-server")
}

function Get-WgComposeServiceStatus {
    $docker = Get-WgDocker
    $target = Get-WgLocalDockerTarget -Docker $docker
    Assert-WgComposeOwnership -Docker $docker -Endpoint $target.Endpoint
    $baseArguments = @(Get-WgComposeBaseArguments -Endpoint $target.Endpoint)
    $output = @(& $docker @baseArguments ps --all --format json 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "Unable to read Docker Compose service status." }
    $text = ($output -join [Environment]::NewLine).Trim()
    if (-not $text) { return @() }

    if ($text.StartsWith("[")) {
        return @(ConvertFrom-Json -InputObject $text)
    }
    $items = @()
    foreach ($line in $output) {
        $trimmed = ([string]$line).Trim()
        if ($trimmed) { $items += ConvertFrom-Json -InputObject $trimmed }
    }
    return @($items)
}

function Get-WgServiceHealthSummary {
    param([object[]]$Status = @())

    $summary = @()
    foreach ($serviceName in Get-WgExpectedServices) {
        $entry = @($Status | Where-Object { $_.Service -eq $serviceName } | Select-Object -First 1)
        if ($entry.Count -eq 0) {
            $summary += [PSCustomObject]@{
                Service = $serviceName
                State = "missing"
                Health = "missing"
                Ready = $false
            }
            continue
        }
        $properties = @($entry[0].PSObject.Properties.Name)
        $state = if ($properties -contains "State") { [string]$entry[0].State } else { "unknown" }
        $health = if ($properties -contains "Health") { [string]$entry[0].Health } else { "missing" }
        $summary += [PSCustomObject]@{
            Service = $serviceName
            State = $state
            Health = $health
            Ready = $state -eq "running" -and $health -eq "healthy"
        }
    }
    return @($summary)
}

function Wait-WgStackHealthy {
    param(
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$ApiPort,
        [Parameter(Mandatory = $true)][ValidateRange(1, 65535)][int]$WebPort,
        [ValidateRange(30, 900)][int]$TimeoutSeconds = 300
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastDescription = ""
    do {
        try {
            $status = @(Get-WgComposeServiceStatus)
            $summary = @(Get-WgServiceHealthSummary -Status $status)
            $notReady = @($summary | Where-Object { -not $_.Ready })
            $apiReady = Test-WgApiReady -Uri "http://127.0.0.1:$ApiPort/ready"
            $webReady = Test-WgHttp -Uri "http://127.0.0.1:$WebPort"
            if ($notReady.Count -eq 0 -and $apiReady -and $webReady) { return $summary }
            $description = (@($notReady | ForEach-Object {
                "$($_.Service)=$($_.State)/$($_.Health)"
            }) + @("api_ready=$apiReady", "web_ready=$webReady")) -join ", "
            if ($description -ne $lastDescription) {
                Write-WgMessage -Message "Waiting for WhaleGuard health: $description" -Level "INFO"
                $lastDescription = $description
            }
        }
        catch {
            $description = Protect-WgLogText -Text $_.Exception.Message
            if ($description -ne $lastDescription) {
                Write-WgMessage -Message "Waiting for Compose status: $description" -Level "WARN" -Color "Yellow"
                $lastDescription = $description
            }
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    throw "The complete eight-service stack did not become healthy within $TimeoutSeconds seconds. Last state: $lastDescription"
}

function Write-WgComposeDiagnostics {
    param([ValidateRange(1, 500)][int]$Tail = 80)

    try {
        $docker = Get-WgDocker
        $target = Get-WgLocalDockerTarget -Docker $docker
        Assert-WgComposeOwnership -Docker $docker -Endpoint $target.Endpoint
        $baseArguments = @(Get-WgComposeBaseArguments -Endpoint $target.Endpoint)
        Write-WgMessage -Message "Docker Compose service state:" -Level "WARN" -Color "Yellow"
        foreach ($line in @(& $docker @baseArguments ps --all 2>&1)) {
            Write-WgMessage -Message ([string]$line) -Level "WARN"
        }
        Write-WgMessage -Message "Recent logs from all WhaleGuard services (redacted):" -Level "WARN" -Color "Yellow"
        foreach ($line in @(& $docker @baseArguments logs --tail $Tail 2>&1)) {
            Write-WgMessage -Message ([string]$line) -Level "WARN"
        }
    }
    catch {
        Write-WgMessage -Message "Unable to collect Docker diagnostics: $($_.Exception.Message)" -Level "WARN" -Color "Yellow"
    }
}
