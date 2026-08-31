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

function Invoke-WgExternalCommandCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 can promote native stderr to a terminating
        # error when the caller uses Stop. Capture the command result first so
        # callers can make an explicit, bounded decision from its exit code.
        $ErrorActionPreference = "Continue"
        $output = @(& $FilePath @Arguments 2>$null)
        $exitCode = [int]$LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [PSCustomObject]@{
        ExitCode = $exitCode
        Output = @($output)
    }
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
        "Desktop" { @("Docker Desktop", "Docker Desktop Launcher") }
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

function Invoke-WgDockerComposeVersionProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateRange(1, 60)][int]$TimeoutSeconds = 15
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Path
    $startInfo.Arguments = "version --short"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $startInfo.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw "Unable to start the Docker Compose version probe." }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill()
            $process.WaitForExit()
            throw "Docker Compose version probe timed out."
        }
        $output = ($process.StandardOutput.ReadToEnd() + [Environment]::NewLine + $process.StandardError.ReadToEnd()).Trim()
        if ($process.ExitCode -ne 0) { throw "Docker Compose version probe failed." }
        $match = [regex]::Match($output, "(?m)^\s*v?([0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?)\s*$")
        if (-not $match.Success) { throw "Docker Compose version output is invalid." }
        try { return [version]$match.Groups[1].Value }
        catch { throw "Docker Compose version output is invalid." }
    }
    finally {
        $process.Dispose()
    }
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
    $authenticodeCommand = Get-WgTrustedAuthenticodeCommand
    $signature = & $authenticodeCommand -LiteralPath $resolvedPath
    $signerSubject = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { "" }
    $productName = [string]$item.VersionInfo.ProductName
    $productVersion = [string]$item.VersionInfo.ProductVersion
    if (-not $productVersion) { $productVersion = [string]$item.VersionInfo.FileVersion }
    if ($Kind -eq "Compose" -and -not $productName -and -not $productVersion) {
        if (
            [string]$signature.Status -ne "Valid" -or
            $signerSubject -notmatch "(?i)(^|,\s*)CN=Docker Inc\.?(,|$)"
        ) {
            throw "Docker Compose binary failed publisher validation."
        }
        $composeVersion = Invoke-WgDockerComposeVersionProbe -Path $resolvedPath
        $productName = "Docker Compose"
        $productVersion = $composeVersion.ToString()
    }
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

function Get-WgTrustedAuthenticodeCommand {
    # The launcher deliberately uses Windows PowerShell 5.1. A parent process
    # can nevertheless prepend PowerShell 7 module directories to PSModulePath,
    # causing command auto-loading to select an incompatible or shadow module.
    # Import the security module from this exact PowerShell runtime and invoke
    # the verified CmdletInfo object instead of resolving an unqualified name.
    $manifestPath = [IO.Path]::GetFullPath(
        (Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1")
    )
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "The trusted PowerShell security module is unavailable."
    }
    Assert-WgNoReparsePointInPath -Path $manifestPath
    try {
        Import-Module -Name $manifestPath -Force -ErrorAction Stop
    }
    catch {
        throw "The trusted PowerShell security module could not be loaded."
    }

    $commands = @(
        Get-Command -Name "Get-AuthenticodeSignature" -CommandType Cmdlet -All -ErrorAction Stop |
            Where-Object {
                $_.Module -and
                [string]::Equals(
                    [IO.Path]::GetFullPath($_.Module.Path),
                    $manifestPath,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
    )
    if ($commands.Count -ne 1) {
        throw "The trusted Authenticode command could not be resolved uniquely."
    }
    return $commands[0]
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
    if ($processes.Count -eq 0) { return @() }
    if (-not $ExpectedPath) {
        throw "A different or untrusted Docker Desktop installation is already running. Stopping or switching it requires an explicit user decision."
    }

    try {
        $resolvedExpectedPath = [IO.Path]::GetFullPath($ExpectedPath)
        $expectedInstallRoot = [IO.Path]::GetDirectoryName($resolvedExpectedPath)
    }
    catch {
        throw "The expected Docker Desktop installation path is invalid; refusing to attach to running processes."
    }
    $canonicalLauncherPaths = @(Get-WgCanonicalDockerInstallRoots | ForEach-Object {
        [IO.Path]::GetFullPath((Join-Path $_ "Docker Desktop.exe"))
    })
    if (-not ($canonicalLauncherPaths | Where-Object {
        [string]::Equals(
            $_,
            $resolvedExpectedPath,
            [StringComparison]::OrdinalIgnoreCase
        )
    })) {
        throw "The running Docker Desktop installation is outside the canonical current-user location."
    }

    try {
        $expectedEvidence = Get-WgDockerBinaryEvidence -Path $resolvedExpectedPath -Kind "Desktop"
    }
    catch {
        throw "The expected Docker Desktop launcher could not be validated; refusing to attach to running processes."
    }
    $trustedProcessPaths = @{}
    foreach ($candidatePath in @(
        $resolvedExpectedPath,
        (Join-Path $expectedInstallRoot "frontend\Docker Desktop.exe")
    )) {
        if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) { continue }
        try {
            $candidateEvidence = Get-WgDockerBinaryEvidence -Path $candidatePath -Kind "Desktop"
        }
        catch {
            throw "A Docker Desktop process binary in the expected installation failed publisher validation."
        }
        if ($candidateEvidence.Version -ne $expectedEvidence.Version) {
            throw "Docker Desktop process binaries in the expected installation have mismatched versions."
        }
        $trustedProcessPaths[[IO.Path]::GetFullPath($candidatePath)] = $true
    }
    foreach ($desktopProcess in $processes) {
        $executablePath = [string]$desktopProcess.ExecutablePath
        if (-not $executablePath) {
            throw "A running Docker Desktop process has an unverifiable executable path; refusing to modify or attach to it."
        }
        try { $resolvedExecutablePath = [IO.Path]::GetFullPath($executablePath) }
        catch {
            throw "A running Docker Desktop process has an invalid executable path; refusing to modify or attach to it."
        }
        if (-not $trustedProcessPaths.ContainsKey($resolvedExecutablePath)) {
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
        $listeners = @(
            Get-NetTCPConnection -State Listen -ErrorAction Stop |
                Where-Object { $_.LocalPort -eq 2375 }
        )
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

    # Do not trust or depend on the user's mutable Docker context store. Probe
    # only Docker Desktop's two allowlisted local named pipes with the signed
    # CLI. Prefer the product-specific pipe when both aliases are available.
    $candidates = @(
        [PSCustomObject]@{
            ContextName = "local-docker-desktop-linux"
            Endpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"
        },
        [PSCustomObject]@{
            ContextName = "local-docker-engine"
            Endpoint = "npipe:////./pipe/docker_engine"
        }
    )
    foreach ($candidate in $candidates) {
        if (Test-WgDockerEngineReady -Docker $Docker -Endpoint $candidate.Endpoint) {
            return $candidate
        }
    }
    throw "No trusted local Docker Desktop engine endpoint is ready."
}

function Test-WgDockerEngineReady {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [ValidateRange(100, 30000)][int]$TimeoutMilliseconds = 5000
    )

    if (-not (Test-WgLocalDockerEndpoint -Endpoint $Endpoint)) {
        throw "Docker Engine readiness probes are restricted to trusted local Windows named pipes."
    }
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $Docker
    $startInfo.Arguments = "--host `"$Endpoint`" version --format `"{{.Server.Version}}`""
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $outputTask = $null
    $errorTask = $null
    try {
        if (-not $process.Start()) { throw "Unable to start the Docker Engine readiness probe." }
        $process.StandardInput.Close()
        $outputTask = $process.StandardOutput.ReadToEndAsync()
        $errorTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            try { $process.Kill() } catch { }
            $null = $process.WaitForExit(1000)
            return $false
        }
        if (-not $outputTask.Wait(1000) -or -not $errorTask.Wait(1000)) {
            return $false
        }
        $output = $outputTask.Result.Trim()
        return (
            $process.ExitCode -eq 0 -and
            $output -match "^[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?$"
        )
    }
    finally {
        $process.Dispose()
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

function Get-WgLegacyComposeProjectName {
    return "whaleguard-redlab"
}

function Assert-WgManagedComposeProjectName {
    param([Parameter(Mandatory = $true)][string]$ProjectName)

    if ($ProjectName -notin @((Get-WgComposeProjectName), (Get-WgLegacyComposeProjectName))) {
        throw "Compose project selection is outside the two WhaleGuard identities managed by this checkout."
    }
}

function Get-WgComposeSelectionDirectory {
    $localAppData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
    if (-not $localAppData) {
        throw "LOCALAPPDATA could not be resolved for Compose project selection."
    }
    $resolvedLocalAppData = [IO.Path]::GetFullPath($localAppData)
    Assert-WgNoReparsePointInPath -Path $resolvedLocalAppData
    return [IO.Path]::GetFullPath(
        (Join-Path $resolvedLocalAppData "WhaleGuardRedLab\ComposeProjects")
    )
}

function Get-WgComposeSelectionPath {
    $canonicalName = Get-WgComposeProjectName
    Assert-WgManagedComposeProjectName -ProjectName $canonicalName
    return [IO.Path]::GetFullPath(
        (Join-Path (Get-WgComposeSelectionDirectory) "selection-$canonicalName.json")
    )
}

function Read-WgComposeProjectSelection {
    $selectionPath = Get-WgComposeSelectionPath
    if (-not (Test-Path -LiteralPath $selectionPath)) { return "" }
    if (-not (Test-Path -LiteralPath $selectionPath -PathType Leaf)) {
        throw "The Compose project selection marker is not a regular file."
    }
    Assert-WgNoReparsePointInPath -Path $selectionPath
    $selectionItem = Get-Item -LiteralPath $selectionPath -Force -ErrorAction Stop
    if ($selectionItem.Length -lt 2 -or $selectionItem.Length -gt 16384) {
        throw "The Compose project selection marker has an invalid size."
    }
    try {
        $selection = Get-Content -LiteralPath $selectionPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The Compose project selection marker is not valid JSON."
    }
    $expectedRoot = [IO.Path]::GetFullPath((Get-WgRoot)).TrimEnd(
        [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    )
    $storedRoot = [string]$selection.root_path
    $canonicalName = Get-WgComposeProjectName
    $selectedProject = [string]$selection.selected_project
    $savedAt = [DateTimeOffset]::MinValue
    $savedAtValid = [DateTimeOffset]::TryParse(
        [string]$selection.saved_at,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind,
        [ref]$savedAt
    )
    if (
        [int]$selection.schema_version -ne 1 -or
        -not [string]::Equals(
            $storedRoot, $expectedRoot, [StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$selection.canonical_project -cne $canonicalName -or
        -not $savedAtValid
    ) {
        throw "The Compose project selection marker does not belong to this checkout."
    }
    Assert-WgManagedComposeProjectName -ProjectName $selectedProject
    return $selectedProject
}

function Save-WgComposeProjectSelection {
    param([Parameter(Mandatory = $true)][string]$ProjectName)

    Assert-WgManagedComposeProjectName -ProjectName $ProjectName
    $selectionDirectory = Get-WgComposeSelectionDirectory
    if (Test-Path -LiteralPath $selectionDirectory) {
        if (-not (Test-Path -LiteralPath $selectionDirectory -PathType Container)) {
            throw "The Compose project selection path is not a directory."
        }
    }
    else {
        $null = New-Item -ItemType Directory -Path $selectionDirectory -Force -ErrorAction Stop
    }
    Assert-WgNoReparsePointInPath -Path $selectionDirectory
    $selectionPath = Get-WgComposeSelectionPath
    if (Test-Path -LiteralPath $selectionPath) {
        if (-not (Test-Path -LiteralPath $selectionPath -PathType Leaf)) {
            throw "The Compose project selection marker is not a regular file."
        }
        Assert-WgNoReparsePointInPath -Path $selectionPath
    }
    $normalizedRoot = [IO.Path]::GetFullPath((Get-WgRoot)).TrimEnd(
        [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    )
    $payload = [ordered]@{
        schema_version = 1
        root_path = $normalizedRoot
        canonical_project = Get-WgComposeProjectName
        selected_project = $ProjectName
        saved_at = [DateTime]::UtcNow.ToString("o")
    }
    $json = $payload | ConvertTo-Json -Depth 4 -Compress
    if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 16384) {
        throw "The Compose project selection marker exceeds its size limit."
    }
    $temporaryPath = Join-Path $selectionDirectory (
        ".selection-$([Guid]::NewGuid().ToString('N')).tmp"
    )
    try {
        [IO.File]::WriteAllText(
            $temporaryPath,
            $json,
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temporaryPath -Destination $selectionPath -Force -ErrorAction Stop
    }
    catch {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
        throw "The Compose project selection marker could not be saved atomically."
    }
    $verifiedSelection = Read-WgComposeProjectSelection
    if ($verifiedSelection -cne $ProjectName) {
        throw "The Compose project selection marker could not be verified after writing."
    }
    return $selectionPath
}

function Get-WgComposeProjectInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$ProjectName
    )

    Assert-WgManagedComposeProjectName -ProjectName $ProjectName
    if (-not (Test-WgLocalDockerEndpoint -Endpoint $Endpoint)) {
        throw "Compose inventory is restricted to a trusted local Docker Desktop endpoint."
    }
    $plugin = Get-WgTrustedDockerPluginConfig
    $dockerBase = @("--config", $plugin.ConfigDirectory, "--host", $Endpoint)
    $allResult = Invoke-WgExternalCommandCapture `
        -FilePath $Docker `
        -Arguments ($dockerBase + @(
            "ps", "--all", "--quiet", "--no-trunc",
            "--filter", "label=com.docker.compose.project=$ProjectName"
        ))
    if ($allResult.ExitCode -ne 0) {
        throw "Unable to inventory the existing $ProjectName Compose project."
    }
    $containerIds = @(
        $allResult.Output |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ }
    )
    if ($containerIds.Count -eq 0) {
        return [PSCustomObject]@{
            ProjectName = $ProjectName
            Exists = $false
            OwnedByCurrentRoot = $false
            Complete = $false
            FullyRunning = $false
            ContainerCount = 0
            RunningCount = 0
            Services = @()
        }
    }
    $uniqueIds = @($containerIds | Select-Object -Unique)
    if (
        $uniqueIds.Count -ne $containerIds.Count -or
        @($containerIds | Where-Object { $_ -notmatch "^[0-9a-f]{64}$" }).Count -gt 0
    ) {
        throw "The existing $ProjectName project returned invalid or duplicate container identities."
    }

    $expectedRoot = [IO.Path]::GetFullPath((Get-WgRoot))
    $expectedComposePath = [IO.Path]::GetFullPath((Join-Path $expectedRoot "docker-compose.yml"))
    $expectedEnvironmentPath = [IO.Path]::GetFullPath((Join-Path $expectedRoot ".env"))
    $ownershipMatches = @()
    $labelsById = @{}
    foreach ($containerId in $containerIds) {
        $inspectResult = Invoke-WgExternalCommandCapture `
            -FilePath $Docker `
            -Arguments ($dockerBase + @(
                "inspect", "--format", "{{json .Config.Labels}}", $containerId
            ))
        $labelsText = (@($inspectResult.Output) -join [Environment]::NewLine).Trim()
        if ($inspectResult.ExitCode -ne 0 -or -not $labelsText) {
            throw "An existing $ProjectName container lacks verifiable Compose ownership."
        }
        try { $labels = ConvertFrom-Json -InputObject $labelsText -ErrorAction Stop }
        catch { throw "An existing $ProjectName container has invalid ownership labels." }
        if ($null -eq $labels) {
            throw "An existing $ProjectName container has empty ownership labels."
        }
        $actualProject = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.project")
        $workingDirectory = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.project.working_dir")
        if ($actualProject -cne $ProjectName -or -not $workingDirectory) {
            throw "An existing $ProjectName container has inconsistent ownership labels."
        }
        try { $resolvedWorkingDirectory = [IO.Path]::GetFullPath($workingDirectory) }
        catch { throw "An existing $ProjectName container has an invalid working-directory label." }
        $ownershipMatches += [string]::Equals(
            $resolvedWorkingDirectory,
            $expectedRoot,
            [StringComparison]::OrdinalIgnoreCase
        )
        $labelsById[$containerId] = $labels
    }
    $ownedCount = @($ownershipMatches | Where-Object { $_ }).Count
    if ($ownedCount -notin @(0, $containerIds.Count)) {
        throw "The existing $ProjectName project mixes containers from different working directories."
    }
    if ($ownedCount -eq 0) {
        return [PSCustomObject]@{
            ProjectName = $ProjectName
            Exists = $true
            OwnedByCurrentRoot = $false
            Complete = $false
            FullyRunning = $false
            ContainerCount = $containerIds.Count
            RunningCount = 0
            Services = @()
        }
    }

    $services = @()
    foreach ($containerId in $containerIds) {
        $labels = $labelsById[$containerId]
        $configFiles = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.project.config_files")
        $environmentFile = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.project.environment_file")
        $service = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.service")
        $containerNumber = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.container-number")
        $oneOff = [string](Get-WgObjectPropertyValue `
            -InputObject $labels -Name "com.docker.compose.oneoff")
        try { $resolvedConfigFiles = [IO.Path]::GetFullPath($configFiles) }
        catch { throw "An existing $ProjectName container has an invalid Compose config-file label." }
        $environmentMatches = $true
        if ($environmentFile) {
            try { $resolvedEnvironmentFile = [IO.Path]::GetFullPath($environmentFile) }
            catch {
                throw "An existing $ProjectName container has an invalid Compose environment-file label."
            }
            $environmentMatches = [string]::Equals(
                $resolvedEnvironmentFile,
                $expectedEnvironmentPath,
                [StringComparison]::OrdinalIgnoreCase
            )
        }
        if (
            -not [string]::Equals(
                $resolvedConfigFiles, $expectedComposePath, [StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $environmentMatches -or
            $service -notin @(Get-WgExpectedServices) -or
            $containerNumber -cne "1" -or
            $oneOff -cne "False"
        ) {
            throw "An existing $ProjectName container does not match this checkout's exact Compose topology."
        }
        $services += $service
    }
    if (@($services | Select-Object -Unique).Count -ne $services.Count) {
        throw "The existing $ProjectName project has duplicate Compose service identities."
    }

    $runningResult = Invoke-WgExternalCommandCapture `
        -FilePath $Docker `
        -Arguments ($dockerBase + @(
            "ps", "--quiet", "--no-trunc",
            "--filter", "label=com.docker.compose.project=$ProjectName"
        ))
    if ($runningResult.ExitCode -ne 0) {
        throw "Unable to inspect the running state of $ProjectName."
    }
    $runningIds = @(
        $runningResult.Output |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ }
    )
    if (
        @($runningIds | Select-Object -Unique).Count -ne $runningIds.Count -or
        @($runningIds | Where-Object { $_ -notin $containerIds }).Count -gt 0
    ) {
        throw "The running state of $ProjectName is inconsistent with its container inventory."
    }
    $expectedServices = @(Get-WgExpectedServices)
    $complete = (
        $services.Count -eq $expectedServices.Count -and
        @($expectedServices | Where-Object { $_ -notin $services }).Count -eq 0
    )
    return [PSCustomObject]@{
        ProjectName = $ProjectName
        Exists = $true
        OwnedByCurrentRoot = $true
        Complete = $complete
        FullyRunning = ($complete -and $runningIds.Count -eq $expectedServices.Count)
        ContainerCount = $containerIds.Count
        RunningCount = $runningIds.Count
        Services = @($services | Sort-Object)
    }
}

function Resolve-WgComposeProjectName {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint
    )

    $canonicalName = Get-WgComposeProjectName
    $legacyName = Get-WgLegacyComposeProjectName
    $canonical = Get-WgComposeProjectInventory `
        -Docker $Docker -Endpoint $Endpoint -ProjectName $canonicalName
    $legacy = Get-WgComposeProjectInventory `
        -Docker $Docker -Endpoint $Endpoint -ProjectName $legacyName
    if ($canonical.Exists -and -not $canonical.OwnedByCurrentRoot) {
        throw "The checkout-scoped Compose project name is already owned by another working directory."
    }
    if (-not $canonical.Exists -and -not $legacy.Exists) {
        $persistedSelection = Read-WgComposeProjectSelection
        if ($persistedSelection) { return $persistedSelection }
        return $canonicalName
    }
    $ownedLegacyExists = $legacy.Exists -and $legacy.OwnedByCurrentRoot
    if (-not $canonical.Exists) {
        if ($ownedLegacyExists) { return $legacyName }
        return $canonicalName
    }
    if (-not $ownedLegacyExists) { return $canonicalName }

    if ($legacy.FullyRunning -and -not $canonical.FullyRunning) { return $legacyName }
    if ($canonical.FullyRunning -and -not $legacy.FullyRunning) { return $canonicalName }
    if ($legacy.Complete -and -not $canonical.Complete) { return $legacyName }
    if ($canonical.Complete -and -not $legacy.Complete) { return $canonicalName }
    if ($legacy.RunningCount -gt 0 -and $canonical.RunningCount -eq 0) { return $legacyName }
    if ($canonical.RunningCount -gt 0 -and $legacy.RunningCount -eq 0) { return $canonicalName }
    throw "Both the legacy and checkout-scoped WhaleGuard Compose projects exist, but neither is the unique recoverable active stack. No project was modified."
}

function Get-WgComposeBaseArguments {
    param(
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [AllowEmptyString()][string]$ProjectName = ""
    )

    $root = Get-WgRoot
    $envPath = Join-Path $root ".env"
    Assert-WgSafeComposeEnvironmentFile -Path $envPath
    $plugin = Get-WgTrustedDockerPluginConfig
    if (-not $ProjectName) { $ProjectName = Get-WgComposeProjectName }
    Assert-WgManagedComposeProjectName -ProjectName $ProjectName
    return @(
        "--config", $plugin.ConfigDirectory,
        "--host", $Endpoint,
        "compose",
        "--project-name", $ProjectName,
        "--file", (Join-Path $root "docker-compose.yml"),
        "--env-file", $envPath
    )
}

function Get-WgObjectPropertyValue {
    param(
        [AllowNull()][object]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $InputObject) { return $null }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Test-WgEmptyJsonObject {
    param([AllowNull()][AllowEmptyCollection()][object]$Value)

    if ($null -eq $Value) { return $true }
    if ($Value -isnot [PSCustomObject]) { return $false }
    return @($Value.PSObject.Properties).Count -eq 0
}

function Test-WgEmptyCollection {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) { return $true }
    return @($Value).Count -eq 0
}

function Test-WgExactStringList {
    param(
        [AllowNull()][object[]]$Actual,
        [AllowNull()][object[]]$Expected
    )

    $actualValues = @($Actual | ForEach-Object { [string]$_ })
    $expectedValues = @($Expected | ForEach-Object { [string]$_ })
    if ($actualValues.Count -ne $expectedValues.Count) { return $false }
    for ($index = 0; $index -lt $actualValues.Count; $index += 1) {
        if ($actualValues[$index] -cne $expectedValues[$index]) { return $false }
    }
    return $true
}

function Test-WgExactCapabilitySet {
    param(
        [AllowNull()][object[]]$Actual,
        [AllowNull()][string[]]$Expected
    )

    $actualValues = @($Actual | Where-Object { $null -ne $_ } | ForEach-Object {
        $value = ([string]$_).ToUpperInvariant()
        if ($value.StartsWith("CAP_", [StringComparison]::Ordinal)) {
            $value = $value.Substring(4)
        }
        $value
    } | Sort-Object)
    $expectedValues = @(
        $Expected |
            Where-Object { $null -ne $_ } |
            ForEach-Object { $_.ToUpperInvariant() } |
            Sort-Object
    )
    return Test-WgExactStringList -Actual $actualValues -Expected $expectedValues
}

function ConvertTo-WgRedisMigrationRunner {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateLength(1, 8192)]
        [string]$Command
    )

    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Command))
    if ($encoded -notmatch "^[A-Za-z0-9+/]+={0,2}$") {
        throw "The Redis migration command could not be encoded safely."
    }
    return "echo $encoded|base64 -d|sh -e"
}

function ConvertFrom-WgDockerJsonOutput {
    param(
        [Parameter(Mandatory = $true)][object]$Result,
        [Parameter(Mandatory = $true)][string]$Context
    )

    if ([int]$Result.ExitCode -ne 0) {
        throw "$Context failed; refusing to continue the Redis volume migration."
    }
    $text = (@($Result.Output) -join "`n").Trim()
    if (-not $text) {
        throw "$Context returned no JSON; refusing to continue the Redis volume migration."
    }
    try { return ($text | ConvertFrom-Json -ErrorAction Stop) }
    catch { throw "$Context returned invalid JSON; refusing to continue the Redis volume migration." }
}

function Invoke-WgDockerCaptureRequired {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $result = Invoke-WgExternalCommandCapture -FilePath $Docker -Arguments $Arguments
    if ($result.ExitCode -ne 0) {
        throw "$Context failed; refusing to continue the Redis volume migration."
    }
    return $result
}

function Assert-WgRedisVolumeInspection {
    param(
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][string]$ExpectedName,
        [Parameter(Mandatory = $true)][string]$ExpectedProject
    )

    $labels = Get-WgObjectPropertyValue -InputObject $Inspection -Name "Labels"
    $options = $null
    $optionsProperty = $Inspection.PSObject.Properties["Options"]
    if ($null -ne $optionsProperty) { $options = $optionsProperty.Value }
    $projectLabel = Get-WgObjectPropertyValue -InputObject $labels -Name "com.docker.compose.project"
    $volumeLabel = Get-WgObjectPropertyValue -InputObject $labels -Name "com.docker.compose.volume"
    if (
        (Get-WgObjectPropertyValue -InputObject $Inspection -Name "Name") -cne $ExpectedName -or
        (Get-WgObjectPropertyValue -InputObject $Inspection -Name "Driver") -cne "local" -or
        (Get-WgObjectPropertyValue -InputObject $Inspection -Name "Scope") -cne "local" -or
        -not (Test-WgEmptyJsonObject -Value $options) -or
        $projectLabel -cne $ExpectedProject -or
        $volumeLabel -cne "redis_data"
    ) {
        throw "Refusing to modify a Redis volume outside this exact local Compose project."
    }
}

function Assert-WgRedisAttachedContainers {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string[]]$DockerBaseArguments,
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [switch]$RequireStopped
    )

    $result = Invoke-WgDockerCaptureRequired `
        -Docker $Docker `
        -Arguments ($DockerBaseArguments + @(
            "ps", "-aq", "--no-trunc", "--filter", "volume=$VolumeName"
        )) `
        -Context "Redis attached-container listing"
    foreach ($rawContainerId in @($result.Output)) {
        $containerId = ([string]$rawContainerId).Trim()
        if (-not $containerId) { continue }
        if ($containerId -notmatch "^[0-9a-f]{64}$") {
            throw "Redis attached-container listing returned an invalid full container ID."
        }
        $inspectionResult = Invoke-WgDockerCaptureRequired `
            -Docker $Docker `
            -Arguments ($DockerBaseArguments + @("container", "inspect", $containerId)) `
            -Context "Redis attached-container inspection"
        $inspectionItems = @(
            ConvertFrom-WgDockerJsonOutput `
                -Result $inspectionResult `
                -Context "Redis attached-container inspection"
        )
        if ($inspectionItems.Count -ne 1) {
            throw "Redis attached-container inspection was not unique."
        }
        $inspection = $inspectionItems[0]
        if ((Get-WgObjectPropertyValue -InputObject $inspection -Name "Id") -cne $containerId) {
            throw "Redis attached-container inspection returned the wrong container."
        }
        $config = Get-WgObjectPropertyValue -InputObject $inspection -Name "Config"
        $labels = Get-WgObjectPropertyValue -InputObject $config -Name "Labels"
        if (
            (Get-WgObjectPropertyValue -InputObject $labels -Name "com.docker.compose.project") -cne $ProjectName -or
            (Get-WgObjectPropertyValue -InputObject $labels -Name "com.docker.compose.service") -cne "redis"
        ) {
            throw "The Redis volume is attached outside this exact Compose project."
        }
        if ($RequireStopped) {
            $state = Get-WgObjectPropertyValue -InputObject $inspection -Name "State"
            $running = [bool](Get-WgObjectPropertyValue -InputObject $state -Name "Running")
            $paused = [bool](Get-WgObjectPropertyValue -InputObject $state -Name "Paused")
            if ($running -or $paused) {
                throw "Redis is still active after the required safe stop."
            }
        }
    }
}

function Assert-WgRedisMigrationHelperInspection {
    param(
        [Parameter(Mandatory = $true)][object]$Inspection,
        [Parameter(Mandatory = $true)][string]$ContainerId,
        [Parameter(Mandatory = $true)][string]$ContainerName,
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [Parameter(Mandatory = $true)][ValidateSet("inspection", "mutation", "postcheck")][string]$Role,
        [Parameter(Mandatory = $true)][string]$User,
        [AllowEmptyCollection()][string[]]$Capabilities = @(),
        [Parameter(Mandatory = $true)][bool]$ReadOnlyVolume,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$Image
    )

    $config = Get-WgObjectPropertyValue -InputObject $Inspection -Name "Config"
    $labels = Get-WgObjectPropertyValue -InputObject $config -Name "Labels"
    $hostConfig = Get-WgObjectPropertyValue -InputObject $Inspection -Name "HostConfig"
    $mounts = @(Get-WgObjectPropertyValue -InputObject $Inspection -Name "Mounts")
    $expectedBind = "$VolumeName`:/data" + $(if ($ReadOnlyVolume) { ":ro" } else { "" })
    $expectedReadWrite = -not $ReadOnlyVolume
    $entrypoint = @(Get-WgObjectPropertyValue -InputObject $config -Name "Entrypoint")
    $configuredCommand = @(Get-WgObjectPropertyValue -InputObject $config -Name "Cmd")
    $restartPolicy = Get-WgObjectPropertyValue -InputObject $hostConfig -Name "RestartPolicy"
    $restartName = Get-WgObjectPropertyValue -InputObject $restartPolicy -Name "Name"
    $ipcMode = [string](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "IpcMode")
    $cgroupMode = [string](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "CgroupnsMode")
    $expectedCommandRunner = ConvertTo-WgRedisMigrationRunner -Command $Command
    if (
        (Get-WgObjectPropertyValue -InputObject $Inspection -Name "Id") -cne $ContainerId -or
        (Get-WgObjectPropertyValue -InputObject $Inspection -Name "Name") -cne "/$ContainerName" -or
        (Get-WgObjectPropertyValue -InputObject $config -Name "Image") -cne $Image -or
        (Get-WgObjectPropertyValue -InputObject $config -Name "User") -cne $User -or
        -not (Test-WgExactStringList -Actual $entrypoint -Expected @("sh")) -or
        -not (Test-WgExactStringList `
            -Actual $configuredCommand `
            -Expected @("-ec", $expectedCommandRunner)) -or
        (Get-WgObjectPropertyValue -InputObject $labels -Name "com.whaleguard.redis-volume-migration") -cne "true" -or
        (Get-WgObjectPropertyValue -InputObject $labels -Name "com.whaleguard.parent-compose-project") -cne $ProjectName -or
        (Get-WgObjectPropertyValue -InputObject $labels -Name "com.whaleguard.redis-volume-migration-role") -cne $Role -or
        -not (Test-WgExactCapabilitySet `
            -Actual @(Get-WgObjectPropertyValue -InputObject $hostConfig -Name "CapAdd") `
            -Expected $Capabilities) -or
        -not (Test-WgExactCapabilitySet `
            -Actual @(Get-WgObjectPropertyValue -InputObject $hostConfig -Name "CapDrop") `
            -Expected @("ALL")) -or
        (Get-WgObjectPropertyValue -InputObject $hostConfig -Name "NetworkMode") -cne "none" -or
        -not [bool](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "ReadonlyRootfs") -or
        -not (Test-WgExactStringList `
            -Actual @(Get-WgObjectPropertyValue -InputObject $hostConfig -Name "SecurityOpt") `
            -Expected @("no-new-privileges:true")) -or
        [bool](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "Privileged") -or
        [bool](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "PublishAllPorts") -or
        -not (Test-WgEmptyJsonObject `
            -Value (Get-WgObjectPropertyValue -InputObject $hostConfig -Name "PortBindings")) -or
        -not (Test-WgEmptyCollection `
            -Value (Get-WgObjectPropertyValue -InputObject $hostConfig -Name "Devices")) -or
        -not (Test-WgEmptyCollection `
            -Value (Get-WgObjectPropertyValue -InputObject $hostConfig -Name "DeviceRequests")) -or
        [string](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "PidMode") -notin @("", "private") -or
        $ipcMode -notin @("", "private") -or
        $cgroupMode -notin @("", "private") -or
        [string](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "UTSMode") -ne "" -or
        [string](Get-WgObjectPropertyValue -InputObject $hostConfig -Name "UsernsMode") -ne "" -or
        $restartName -notin @($null, "", "no") -or
        -not (Test-WgExactStringList `
            -Actual @(Get-WgObjectPropertyValue -InputObject $hostConfig -Name "Binds") `
            -Expected @($expectedBind)) -or
        $mounts.Count -ne 1 -or
        (Get-WgObjectPropertyValue -InputObject $mounts[0] -Name "Type") -cne "volume" -or
        (Get-WgObjectPropertyValue -InputObject $mounts[0] -Name "Name") -cne $VolumeName -or
        (Get-WgObjectPropertyValue -InputObject $mounts[0] -Name "Driver") -cne "local" -or
        (Get-WgObjectPropertyValue -InputObject $mounts[0] -Name "Destination") -cne "/data" -or
        [bool](Get-WgObjectPropertyValue -InputObject $mounts[0] -Name "RW") -ne $expectedReadWrite
    ) {
        throw "Redis migration helper sandbox is not exact."
    }
}

function Invoke-WgRedisScopedMigrationHelper {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string[]]$DockerBaseArguments,
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [Parameter(Mandatory = $true)][ValidateSet("inspection", "mutation", "postcheck")][string]$Role,
        [Parameter(Mandatory = $true)][string]$User,
        [AllowEmptyCollection()][string[]]$Capabilities = @(),
        [Parameter(Mandatory = $true)][bool]$ReadOnlyVolume,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$Image
    )

    $containerName = "wg-redis-migrate-$Role-$([Guid]::NewGuid().ToString('N'))"
    $mount = "$VolumeName`:/data" + $(if ($ReadOnlyVolume) { ":ro" } else { "" })
    $commandRunner = ConvertTo-WgRedisMigrationRunner -Command $Command
    $arguments = $DockerBaseArguments + @(
        "create",
        "--name", $containerName,
        "--label", "com.whaleguard.redis-volume-migration=true",
        "--label", "com.whaleguard.parent-compose-project=$ProjectName",
        "--label", "com.whaleguard.redis-volume-migration-role=$Role",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL"
    )
    foreach ($capability in $Capabilities) {
        $arguments += @("--cap-add", $capability)
    }
    $arguments += @(
        "--security-opt", "no-new-privileges:true",
        "--user", $User,
        "--entrypoint", "sh",
        "-v", $mount,
        $Image,
        "-ec", $commandRunner
    )
    $createResult = Invoke-WgDockerCaptureRequired `
        -Docker $Docker `
        -Arguments $arguments `
        -Context "Redis $Role helper creation"
    $ids = @($createResult.Output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
    if ($ids.Count -ne 1 -or $ids[0] -notmatch "^[0-9a-f]{64}$") {
        throw "Docker did not create one uniquely identifiable Redis migration helper."
    }
    $containerId = $ids[0]
    $primaryFailure = $null
    $output = ""
    try {
        $inspectionResult = Invoke-WgDockerCaptureRequired `
            -Docker $Docker `
            -Arguments ($DockerBaseArguments + @("container", "inspect", $containerId)) `
            -Context "Redis $Role helper inspection"
        $inspectionItems = @(
            ConvertFrom-WgDockerJsonOutput `
                -Result $inspectionResult `
                -Context "Redis $Role helper inspection"
        )
        if ($inspectionItems.Count -ne 1) {
            throw "Redis migration helper inspection was not unique."
        }
        Assert-WgRedisMigrationHelperInspection `
            -Inspection $inspectionItems[0] `
            -ContainerId $containerId `
            -ContainerName $containerName `
            -VolumeName $VolumeName `
            -ProjectName $ProjectName `
            -Role $Role `
            -User $User `
            -Capabilities $Capabilities `
            -ReadOnlyVolume $ReadOnlyVolume `
            -Command $Command `
            -Image $Image
        $startResult = Invoke-WgDockerCaptureRequired `
            -Docker $Docker `
            -Arguments ($DockerBaseArguments + @("start", "--attach", $containerId)) `
            -Context "Redis $Role helper execution"
        $output = (@($startResult.Output) -join "`n").Trim()
    }
    catch { $primaryFailure = $_ }
    $removeResult = Invoke-WgExternalCommandCapture `
        -FilePath $Docker `
        -Arguments ($DockerBaseArguments + @("container", "rm", "--force", $containerId))
    if ($removeResult.ExitCode -ne 0) {
        throw "Docker could not remove the exact scoped Redis migration helper."
    }
    if ($null -ne $primaryFailure) { throw $primaryFailure }
    return $output
}

function Invoke-WgRedisVolumeMigration {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$DockerConfig,
        [Parameter(Mandatory = $true)][string]$ProjectName
    )

    $root = [IO.Path]::GetFullPath((Get-WgRoot))
    $dockerPath = [IO.Path]::GetFullPath($Docker)
    $configPath = [IO.Path]::GetFullPath($DockerConfig)
    $expectedConfig = [IO.Path]::GetFullPath((Join-Path $root ".local\docker-cli-config"))
    $trustedDockerPath = [IO.Path]::GetFullPath((Get-WgDocker))
    $trustedTarget = Get-WgLocalDockerTarget -Docker $trustedDockerPath
    $trustedPlugin = Get-WgTrustedDockerPluginConfig
    $trustedConfig = [IO.Path]::GetFullPath($trustedPlugin.ConfigDirectory)
    if (
        -not (Test-Path -LiteralPath $dockerPath -PathType Leaf) -or
        -not [string]::Equals(
            $dockerPath, $trustedDockerPath, [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-WgLocalDockerEndpoint -Endpoint $Endpoint) -or
        $Endpoint -cne $trustedTarget.Endpoint -or
        -not (Test-Path -LiteralPath $configPath -PathType Container) -or
        -not [string]::Equals($configPath, $expectedConfig, [StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($configPath, $trustedConfig, [StringComparison]::OrdinalIgnoreCase) -or
        $ProjectName -cne (Resolve-WgComposeProjectName `
            -Docker $trustedDockerPath -Endpoint $trustedTarget.Endpoint)
    ) {
        throw "Redis volume migration requires the trusted local Docker path, config, endpoint, and project."
    }
    Assert-WgNoReparsePointInPath -Path $dockerPath
    Assert-WgNoReparsePointInPath -Path $configPath
    $composePath = Join-Path $root "docker-compose.yml"
    $environmentPath = Join-Path $root ".env"
    Assert-WgNoReparsePointInPath -Path $composePath
    Assert-WgNoReparsePointInPath -Path $environmentPath
    Assert-WgSafeComposeEnvironmentFile -Path $environmentPath
    Assert-WgComposeOwnership `
        -Docker $dockerPath -Endpoint $Endpoint -ProjectName $ProjectName

    $dockerBase = @("--config", $configPath, "--host", $Endpoint)
    $composeBase = @(
        "compose",
        "--project-name", $ProjectName,
        "--file", $composePath,
        "--env-file", $environmentPath
    )
    $configResult = Invoke-WgDockerCaptureRequired `
        -Docker $dockerPath `
        -Arguments ($dockerBase + $composeBase + @("config", "--format", "json")) `
        -Context "Redis Compose identity inspection"
    $composeConfig = ConvertFrom-WgDockerJsonOutput `
        -Result $configResult `
        -Context "Redis Compose identity inspection"
    $volumes = Get-WgObjectPropertyValue -InputObject $composeConfig -Name "volumes"
    $redisVolume = Get-WgObjectPropertyValue -InputObject $volumes -Name "redis_data"
    $volumeName = [string](Get-WgObjectPropertyValue -InputObject $redisVolume -Name "name")
    $expectedVolumeName = "${ProjectName}_redis_data"
    if (
        (Get-WgObjectPropertyValue -InputObject $composeConfig -Name "name") -cne $ProjectName -or
        $volumeName -cne $expectedVolumeName
    ) {
        throw "Compose did not expose the exact Redis volume for this project."
    }

    $volumeResult = Invoke-WgExternalCommandCapture `
        -FilePath $dockerPath `
        -Arguments ($dockerBase + @("volume", "inspect", $volumeName))
    if ($volumeResult.ExitCode -ne 0) {
        $listResult = Invoke-WgDockerCaptureRequired `
            -Docker $dockerPath `
            -Arguments ($dockerBase + @(
                "volume", "ls", "--quiet", "--filter", "name=^$volumeName$"
            )) `
            -Context "Redis volume fallback listing"
        $listed = @($listResult.Output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
        if ($listed.Count -ne 0) {
            throw "Docker returned an inconsistent Redis volume listing after inspect failed."
        }
        return [PSCustomObject]@{
            Status = "not_needed"
            VolumePresent = $false
            Project = $ProjectName
        }
    }
    $volumeItems = @(
        ConvertFrom-WgDockerJsonOutput `
            -Result $volumeResult `
            -Context "Redis volume inspection"
    )
    if ($volumeItems.Count -ne 1) { throw "Redis volume inspection was not unique." }
    Assert-WgRedisVolumeInspection `
        -Inspection $volumeItems[0] `
        -ExpectedName $volumeName `
        -ExpectedProject $ProjectName
    Assert-WgRedisAttachedContainers `
        -Docker $dockerPath `
        -DockerBaseArguments $dockerBase `
        -VolumeName $volumeName `
        -ProjectName $ProjectName

    $null = Invoke-WgDockerCaptureRequired `
        -Docker $dockerPath `
        -Arguments ($dockerBase + $composeBase + @("stop", "redis")) `
        -Context "Redis safe stop"
    Assert-WgRedisAttachedContainers `
        -Docker $dockerPath `
        -DockerBaseArguments $dockerBase `
        -VolumeName $volumeName `
        -ProjectName $ProjectName `
        -RequireStopped

    $migrationImage = (
        "redis:7.4.11-alpine3.21@" +
        "sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf"
    )
    $countCommand = @'
set -o pipefail; cap_eff="$(awk '$1 == "CapEff:" { print $2 }' /proc/1/status)"; cap_prm="$(awk '$1 == "CapPrm:" { print $2 }' /proc/1/status)"; cap_bnd="$(awk '$1 == "CapBnd:" { print $2 }' /proc/1/status)"; nnp="$(awk '$1 == "NoNewPrivs:" { print $2 }' /proc/1/status)"; [ "$(id -u)" = 0 ] && [ "$cap_eff" = 0000000000000004 ] && [ "$cap_prm" = 0000000000000004 ] && [ "$cap_bnd" = 0000000000000004 ] && [ "$nnp" = 1 ] || exit 73; count="$(find /data -xdev -user 0 -exec echo x \; | wc -l)" || exit 71; printf "%s %s %s %s\n" "$count" "$cap_eff" "$cap_prm" "$cap_bnd"
'@.Trim()
    $before = Invoke-WgRedisScopedMigrationHelper `
        -Docker $dockerPath `
        -DockerBaseArguments $dockerBase `
        -VolumeName $volumeName `
        -ProjectName $ProjectName `
        -Role "inspection" `
        -User "0:0" `
        -Capabilities @("DAC_READ_SEARCH") `
        -ReadOnlyVolume $true `
        -Command $countCommand `
        -Image $migrationImage
    $beforeFields = @($before -split "\s+" | Where-Object { $_ })
    $rootOwnedBefore = [long]0
    if (
        $beforeFields.Count -ne 4 -or
        -not [long]::TryParse($beforeFields[0], [ref]$rootOwnedBefore) -or
        $rootOwnedBefore -lt 0 -or
        -not (Test-WgExactStringList `
            -Actual $beforeFields[1..3] `
            -Expected @(
                "0000000000000004", "0000000000000004", "0000000000000004"
            ))
    ) {
        throw "Could not prove legacy Redis ownership with the scoped inspection helper."
    }

    $mutationCapability = $null
    if ($rootOwnedBefore -gt 0) {
        $mutationCommand = @'
cap_eff="$(awk '$1 == "CapEff:" { print $2 }' /proc/1/status)"; cap_prm="$(awk '$1 == "CapPrm:" { print $2 }' /proc/1/status)"; cap_bnd="$(awk '$1 == "CapBnd:" { print $2 }' /proc/1/status)"; nnp="$(awk '$1 == "NoNewPrivs:" { print $2 }' /proc/1/status)"; [ "$(id -u)" = 0 ] && [ "$cap_eff" = 0000000000000005 ] && [ "$cap_prm" = 0000000000000005 ] && [ "$cap_bnd" = 0000000000000005 ] && [ "$nnp" = 1 ] || exit 73; find /data -xdev -depth -user 0 -exec chown -h redis:redis {} +; printf "%s %s %s\n" "$cap_eff" "$cap_prm" "$cap_bnd"
'@.Trim()
        $mutationOutput = Invoke-WgRedisScopedMigrationHelper `
            -Docker $dockerPath `
            -DockerBaseArguments $dockerBase `
            -VolumeName $volumeName `
            -ProjectName $ProjectName `
            -Role "mutation" `
            -User "0:0" `
            -Capabilities @("CHOWN", "DAC_READ_SEARCH") `
            -ReadOnlyVolume $false `
            -Command $mutationCommand `
            -Image $migrationImage
        $mutationFields = @($mutationOutput -split "\s+" | Where-Object { $_ })
        if (-not (Test-WgExactStringList `
            -Actual $mutationFields `
            -Expected @(
                "0000000000000005", "0000000000000005", "0000000000000005"
            ))) {
            throw "Redis migration helper capability proof is invalid."
        }
        $mutationCapability = $mutationFields[0]
    }

    $postcheckCommand = @'
set -o pipefail; cap_eff="$(awk '$1 == "CapEff:" { print $2 }' /proc/1/status)"; cap_prm="$(awk '$1 == "CapPrm:" { print $2 }' /proc/1/status)"; cap_bnd="$(awk '$1 == "CapBnd:" { print $2 }' /proc/1/status)"; nnp="$(awk '$1 == "NoNewPrivs:" { print $2 }' /proc/1/status)"; [ "$(id -u)" != 0 ] && [ "$cap_eff" = 0000000000000000 ] && [ "$cap_prm" = 0000000000000000 ] && [ "$cap_bnd" = 0000000000000000 ] && [ "$nnp" = 1 ] || exit 73; count="$(find /data -xdev -user 0 -exec echo x \; | wc -l)" || exit 71; [ "$count" = 0 ] || exit 72; printf "%s %s %s %s\n" "$count" "$cap_eff" "$cap_prm" "$cap_bnd"
'@.Trim()
    $after = Invoke-WgRedisScopedMigrationHelper `
        -Docker $dockerPath `
        -DockerBaseArguments $dockerBase `
        -VolumeName $volumeName `
        -ProjectName $ProjectName `
        -Role "postcheck" `
        -User "redis" `
        -Capabilities @() `
        -ReadOnlyVolume $true `
        -Command $postcheckCommand `
        -Image $migrationImage
    $afterFields = @($after -split "\s+" | Where-Object { $_ })
    if (-not (Test-WgExactStringList `
        -Actual $afterFields `
        -Expected @(
            "0", "0000000000000000", "0000000000000000", "0000000000000000"
        ))) {
        throw "Root-owned entries remain in the Redis volume."
    }
    return [PSCustomObject]@{
        Status = $(if ($rootOwnedBefore -gt 0) { "migrated" } else { "already_compatible" })
        VolumePresent = $true
        RootOwnedEntriesBefore = $rootOwnedBefore
        RootOwnedEntriesAfter = 0
        MutationHelperCapEff = $mutationCapability
        Project = $ProjectName
    }
}

function Assert-WgComposeOwnership {
    param(
        [Parameter(Mandatory = $true)][string]$Docker,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [AllowEmptyString()][string]$ProjectName = ""
    )

    $plugin = Get-WgTrustedDockerPluginConfig
    if (-not $ProjectName) { $ProjectName = Get-WgComposeProjectName }
    Assert-WgManagedComposeProjectName -ProjectName $ProjectName
    $containerIds = @(& $Docker --config $plugin.ConfigDirectory --host $Endpoint ps --all --quiet --no-trunc --filter "label=com.docker.compose.project=$projectName" 2>$null)
    if ($LASTEXITCODE -ne 0) { throw "Unable to validate existing WhaleGuard Compose ownership." }
    $expectedRoot = [IO.Path]::GetFullPath((Get-WgRoot))
    foreach ($containerIdValue in $containerIds) {
        $containerId = ([string]$containerIdValue).Trim()
        if (-not $containerId) { continue }
        if ($containerId -notmatch "^[0-9a-f]{64}$") {
            throw "An existing $projectName container returned an invalid full container ID."
        }
        # Ask Docker for labels only, then select the ownership label in
        # PowerShell. Embedding the dotted label key inside a Go template loses
        # its nested quotes under Windows PowerShell 5.1 native argument
        # marshalling and turns the key into an unintended template function.
        $labelsText = (& $Docker --config $plugin.ConfigDirectory --host $Endpoint inspect --format "{{json .Config.Labels}}" $containerId 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $labelsText) {
            throw "An existing $projectName container lacks verifiable Compose ownership."
        }
        $workingDirectory = ""
        try {
            $labels = ConvertFrom-Json -InputObject $labelsText -ErrorAction Stop
            if ($null -ne $labels) {
                $workingDirectoryProperty = $labels.PSObject.Properties["com.docker.compose.project.working_dir"]
                if ($workingDirectoryProperty) {
                    $workingDirectory = ([string]$workingDirectoryProperty.Value).Trim()
                }
            }
        }
        catch {
            throw "An existing $projectName container has invalid ownership labels."
        }
        if (-not $workingDirectory) {
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
    $desktop = Find-WgTrustedDockerDesktopPath
    if (-not $desktop) {
        throw "A trusted Docker Desktop launcher was not found."
    }
    $desktopProcesses = @(Assert-WgRunningDockerDesktopOwnership -ExpectedPath $desktop)
    if ($desktopProcesses.Count -eq 0) {
        throw "Docker Desktop is not running."
    }
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

function Get-WgDockerRuntimeProcesses {
    $runtimeNames = @(
        "Docker Desktop.exe",
        "com.docker.backend.exe",
        "com.docker.build.exe",
        "dockerd.exe",
        "vpnkit.exe"
    )
    try {
        return @(
            Get-CimInstance Win32_Process -ErrorAction Stop |
                Where-Object { [string]$_.Name -in $runtimeNames }
        )
    }
    catch {
        throw "Docker runtime process state could not be verified; stale socket recovery is disabled."
    }
}

function Get-WgDockerRuntimeDirectory {
    $localAppData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
    if (-not $localAppData) {
        throw "LOCALAPPDATA could not be resolved for stale Docker socket recovery."
    }
    return [IO.Path]::GetFullPath((Join-Path $localAppData "Docker\run"))
}

function Get-WgDockerSecretsRuntimeDirectory {
    $localAppData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::LocalApplicationData
    )
    if (-not $localAppData) {
        throw "LOCALAPPDATA could not be resolved for stale Docker socket recovery."
    }
    return [IO.Path]::GetFullPath((Join-Path $localAppData "docker-secrets-engine"))
}

function Get-WgDockerRuntimeEntryEvidence {
    param([Parameter(Mandatory = $true)][string]$RuntimeDirectory)

    try {
        $children = @(Get-ChildItem -LiteralPath $RuntimeDirectory -Force -ErrorAction Stop)
    }
    catch {
        throw "Docker runtime directory contents could not be verified; refusing automatic recovery."
    }
    return @($children | ForEach-Object {
        [PSCustomObject]@{
            Name = [string]$_.Name
            IsFile = ($_ -is [IO.FileInfo])
            Length = $(if ($_ -is [IO.FileInfo]) { [long]$_.Length } else { [long]-1 })
            IsReparsePoint = (
                ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
            )
        }
    })
}

function Get-WgDockerRuntimeRecoveryPlan {
    param(
        [Parameter(Mandatory = $true)][string]$DockerDesktopPath,
        [ValidateSet("desktop", "secrets")][string]$RuntimeKind = "desktop"
    )

    $desktopPath = [IO.Path]::GetFullPath($DockerDesktopPath)
    $canonicalDesktopPaths = @(Get-WgCanonicalDockerInstallRoots | ForEach-Object {
        [IO.Path]::GetFullPath((Join-Path $_ "Docker Desktop.exe"))
    })
    if (-not ($canonicalDesktopPaths | Where-Object {
        [string]::Equals($_, $desktopPath, [StringComparison]::OrdinalIgnoreCase)
    })) {
        throw "Stale socket recovery requires the canonical current-user Docker Desktop path."
    }
    $desktopEvidence = Get-WgDockerBinaryEvidence -Path $desktopPath -Kind "Desktop"
    if (
        $desktopEvidence.Version.Major -ne 4 -or
        $desktopEvidence.Version.Minor -ne 88 -or
        $desktopEvidence.Version.Build -ne 1
    ) {
        return [PSCustomObject]@{
            Status = "not_affected_version"
            Recoverable = $false
            RuntimeDirectory = ""
            RuntimeKind = $RuntimeKind
            BackupDirectory = ""
            RuntimeProcessCount = 0
        }
    }

    if ($RuntimeKind -eq "desktop") {
        $runtimeDirectory = [IO.Path]::GetFullPath((Get-WgDockerRuntimeDirectory))
        $requiredSocketName = "sailor-ingest.sock"
        $allowedSocketNames = @(
            "dockerEthernetVfkit",
            "dockerInference",
            "sailor-ingest.sock",
            "userAnalyticsOtlpHttp.sock"
        )
    }
    else {
        $runtimeDirectory = [IO.Path]::GetFullPath((Get-WgDockerSecretsRuntimeDirectory))
        $requiredSocketName = "engine.sock"
        $allowedSocketNames = @("engine.sock")
    }
    if (-not (Test-Path -LiteralPath $runtimeDirectory)) {
        return [PSCustomObject]@{
            Status = "runtime_directory_absent"
            Recoverable = $false
            RuntimeDirectory = $runtimeDirectory
            RuntimeKind = $RuntimeKind
            BackupDirectory = ""
            RuntimeProcessCount = 0
        }
    }
    if (-not (Test-Path -LiteralPath $runtimeDirectory -PathType Container)) {
        throw "The Docker runtime path is not a directory; refusing automatic recovery."
    }
    Assert-WgNoReparsePointInPath -Path $runtimeDirectory

    try {
        $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $directorySecurity = [IO.Directory]::GetAccessControl(
            $runtimeDirectory,
            [Security.AccessControl.AccessControlSections]::Owner
        )
        $ownerSid = $directorySecurity.GetOwner(
            [Security.Principal.SecurityIdentifier]
        )
    }
    catch {
        throw "Docker runtime directory ownership could not be verified; refusing automatic recovery: $($_.Exception.Message)"
    }
    if ($null -eq $currentSid -or $ownerSid -ne $currentSid) {
        throw "Docker runtime directory is not owned by the current Windows user."
    }

    $runtimeProcesses = @(Get-WgDockerRuntimeProcesses)
    if ($runtimeProcesses.Count -gt 0) {
        return [PSCustomObject]@{
            Status = "runtime_active"
            Recoverable = $false
            RuntimeDirectory = $runtimeDirectory
            RuntimeKind = $RuntimeKind
            BackupDirectory = ""
            RuntimeProcessCount = $runtimeProcesses.Count
        }
    }

    $entries = @(Get-WgDockerRuntimeEntryEvidence -RuntimeDirectory $runtimeDirectory)
    if (-not ($entries | Where-Object { $_.Name -ceq $requiredSocketName })) {
        return [PSCustomObject]@{
            Status = "affected_socket_absent"
            Recoverable = $false
            RuntimeDirectory = $runtimeDirectory
            RuntimeKind = $RuntimeKind
            BackupDirectory = ""
            RuntimeProcessCount = 0
        }
    }
    $runtimeItem = Get-Item -LiteralPath $runtimeDirectory -Force -ErrorAction Stop
    if ($runtimeItem.LastWriteTimeUtc -gt [DateTime]::UtcNow.AddSeconds(-30)) {
        return [PSCustomObject]@{
            Status = "runtime_directory_too_recent"
            Recoverable = $false
            RuntimeDirectory = $runtimeDirectory
            RuntimeKind = $RuntimeKind
            BackupDirectory = ""
            RuntimeProcessCount = 0
        }
    }

    foreach ($entry in $entries) {
        if (
            $entry.Name -notin $allowedSocketNames -or
            -not $entry.IsFile -or
            $entry.Length -ne 0 -or
            -not $entry.IsReparsePoint
        ) {
            throw "Docker's stale runtime directory contains unexpected data; it was not renamed."
        }
    }
    return [PSCustomObject]@{
        Status = "recoverable_stale_socket_directory"
        Recoverable = $true
        RuntimeDirectory = $runtimeDirectory
        RuntimeKind = $RuntimeKind
        BackupDirectory = ""
        RuntimeProcessCount = 0
    }
}

function Move-WgDockerRuntimeRecoveryPlan {
    param([Parameter(Mandatory = $true)][object]$Plan)

    if (-not $Plan.Recoverable) { return $Plan }
    if (@(Get-WgDockerRuntimeProcesses).Count -gt 0) {
        throw "Docker runtime processes appeared during stale socket recovery; no directory was renamed."
    }
    $runtimeKind = [string]$Plan.RuntimeKind
    if ($runtimeKind -notin @("desktop", "secrets")) {
        throw "The stale Docker runtime recovery kind is invalid."
    }
    $runtimeDirectory = [IO.Path]::GetFullPath([string]$Plan.RuntimeDirectory)
    $expectedRuntimeDirectory = if ($runtimeKind -eq "desktop") {
        [IO.Path]::GetFullPath((Get-WgDockerRuntimeDirectory))
    }
    else {
        [IO.Path]::GetFullPath((Get-WgDockerSecretsRuntimeDirectory))
    }
    if (-not [string]::Equals(
        $runtimeDirectory,
        $expectedRuntimeDirectory,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "The stale Docker runtime directory is outside the exact recovery boundary."
    }
    $recoveryRoot = [IO.Path]::GetFullPath((Split-Path $runtimeDirectory -Parent))
    $leafName = Split-Path $runtimeDirectory -Leaf
    $timestamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
    $backupDirectory = Join-Path $recoveryRoot (
        "{0}.stale-{1}-{2}" -f `
            $leafName,
            $timestamp,
            [Guid]::NewGuid().ToString("N").Substring(0, 8)
    )
    if (Test-Path -LiteralPath $backupDirectory) {
        throw "The stale Docker runtime backup path already exists."
    }
    try {
        Move-Item -LiteralPath $runtimeDirectory -Destination $backupDirectory -ErrorAction Stop
    }
    catch {
        throw "The verified stale Docker runtime directory could not be isolated safely."
    }
    if (
        (Test-Path -LiteralPath $runtimeDirectory) -or
        -not (Test-Path -LiteralPath $backupDirectory -PathType Container)
    ) {
        throw "The stale Docker runtime directory move could not be verified."
    }
    Assert-WgNoReparsePointInPath -Path $backupDirectory
    return [PSCustomObject]@{
        Status = "stale_socket_directory_isolated"
        Recoverable = $false
        RuntimeDirectory = $runtimeDirectory
        RuntimeKind = $runtimeKind
        BackupDirectory = [IO.Path]::GetFullPath($backupDirectory)
        RuntimeProcessCount = 0
    }
}

function Invoke-WgDockerRuntimeSocketRecovery {
    param(
        [Parameter(Mandatory = $true)][string]$DockerDesktopPath,
        [ValidateSet("desktop", "secrets")][string]$RuntimeKind = "desktop"
    )

    $plan = Get-WgDockerRuntimeRecoveryPlan `
        -DockerDesktopPath $DockerDesktopPath -RuntimeKind $RuntimeKind
    return (Move-WgDockerRuntimeRecoveryPlan -Plan $plan)
}

function Invoke-WgDockerRuntimeSocketRecoveries {
    param([Parameter(Mandatory = $true)][string]$DockerDesktopPath)

    # Validate every known 4.88.1 socket directory before moving either one.
    # This prevents a partially recognized directory from being touched.
    $plans = @(
        Get-WgDockerRuntimeRecoveryPlan `
            -DockerDesktopPath $DockerDesktopPath -RuntimeKind "desktop"
        Get-WgDockerRuntimeRecoveryPlan `
            -DockerDesktopPath $DockerDesktopPath -RuntimeKind "secrets"
    )
    if (@($plans | Where-Object { $_.Status -eq "runtime_active" }).Count -gt 0) {
        return [PSCustomObject]@{
            Status = "runtime_active"
            BackupDirectories = @()
            Results = $plans
        }
    }
    $results = @($plans | ForEach-Object { Move-WgDockerRuntimeRecoveryPlan -Plan $_ })
    $backups = @(
        $results |
            Where-Object { $_.Status -eq "stale_socket_directory_isolated" } |
            ForEach-Object { $_.BackupDirectory }
    )
    return [PSCustomObject]@{
        Status = $(
            if ($backups.Count -gt 0) { "stale_socket_directories_isolated" }
            else { "not_needed" }
        )
        BackupDirectories = $backups
        Results = $results
    }
}

function Start-WgDockerDesktopEngine {
    param([ValidateRange(30, 600)][int]$TimeoutSeconds = 180)

    $desktop = Find-WgTrustedDockerDesktopPath
    if (-not $desktop) {
        throw "A trusted Docker Desktop launcher was not found."
    }
    $docker = Get-WgDocker
    $desktopProcesses = @(Assert-WgRunningDockerDesktopOwnership -ExpectedPath $desktop)
    if ($desktopProcesses.Count -eq 0) {
        $recovery = Invoke-WgDockerRuntimeSocketRecoveries -DockerDesktopPath $desktop
        if ($recovery.Status -eq "runtime_active") {
            throw "Docker runtime processes exist without a verified Docker Desktop launcher; refusing to start a second runtime."
        }
        if ($recovery.Status -eq "stale_socket_directories_isolated") {
            Write-WgMessage -Message (
                "Recovered Docker Desktop 4.88.1 from stale local sockets. " +
                "The original runtime directories were retained at " +
                "$($recovery.BackupDirectories -join '; ')."
            ) -Level "WARN" -Color "Yellow"
        }
        Start-Process -FilePath $desktop -WindowStyle Hidden
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $target = Get-WgLocalDockerTarget -Docker $docker
            $confirmedProcesses = @(
                Assert-WgRunningDockerDesktopOwnership -ExpectedPath $desktop
            )
            if ($confirmedProcesses.Count -eq 0) {
                throw "The trusted Docker Desktop process exited before its engine became ready."
            }
            return $target
        }
        catch {
            if (
                $_.Exception.Message -notmatch "^No trusted local Docker Desktop engine endpoint is ready" -and
                $_.Exception.Message -notmatch "^The trusted Docker Desktop process exited"
            ) {
                throw
            }
        }
        if ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    } while ((Get-Date) -lt $deadline)
    throw "Docker Desktop did not expose a trusted local Linux engine within $TimeoutSeconds seconds."
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
    param(
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments,
        [AllowEmptyString()][string]$ProjectName = ""
    )
    $docker = Get-WgDocker
    $target = Get-WgLocalDockerTarget -Docker $docker
    if (-not $ProjectName) {
        $ProjectName = Resolve-WgComposeProjectName `
            -Docker $docker -Endpoint $target.Endpoint
    }
    Assert-WgComposeOwnership `
        -Docker $docker -Endpoint $target.Endpoint -ProjectName $ProjectName
    $plugin = Get-WgTrustedDockerPluginConfig
    $baseArguments = @(
        Get-WgComposeBaseArguments -Endpoint $target.Endpoint -ProjectName $ProjectName
    )
    $previousDockerConfig = [Environment]::GetEnvironmentVariable("DOCKER_CONFIG", "Process")
    try {
        # Docker Compose can launch Buildx as a second-level CLI plugin. The
        # global --config flag is not reliably inherited by that child, so set
        # the already validated managed config only for this process tree.
        [Environment]::SetEnvironmentVariable("DOCKER_CONFIG", $plugin.ConfigDirectory, "Process")
        & $docker @baseArguments @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        [Environment]::SetEnvironmentVariable("DOCKER_CONFIG", $previousDockerConfig, "Process")
    }
    if ($exitCode -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}

function Get-WgExpectedServices {
    return @("db", "redis", "api", "worker", "web", "mock-llm", "mock-agent", "mock-mcp-server")
}

function Get-WgComposeServiceStatus {
    param([AllowEmptyString()][string]$ProjectName = "")

    $docker = Get-WgDocker
    $target = Get-WgLocalDockerTarget -Docker $docker
    if (-not $ProjectName) {
        $ProjectName = Resolve-WgComposeProjectName `
            -Docker $docker -Endpoint $target.Endpoint
    }
    Assert-WgComposeOwnership `
        -Docker $docker -Endpoint $target.Endpoint -ProjectName $ProjectName
    $baseArguments = @(
        Get-WgComposeBaseArguments -Endpoint $target.Endpoint -ProjectName $ProjectName
    )
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
        [AllowEmptyString()][string]$ProjectName = "",
        [ValidateRange(30, 900)][int]$TimeoutSeconds = 300
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastDescription = ""
    do {
        try {
            $status = @(Get-WgComposeServiceStatus -ProjectName $ProjectName)
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
    param(
        [ValidateRange(1, 500)][int]$Tail = 80,
        [AllowEmptyString()][string]$ProjectName = ""
    )

    try {
        $docker = Get-WgDocker
        $target = Get-WgLocalDockerTarget -Docker $docker
        if (-not $ProjectName) {
            $ProjectName = Resolve-WgComposeProjectName `
                -Docker $docker -Endpoint $target.Endpoint
        }
        Assert-WgComposeOwnership `
            -Docker $docker -Endpoint $target.Endpoint -ProjectName $ProjectName
        $baseArguments = @(
            Get-WgComposeBaseArguments -Endpoint $target.Endpoint -ProjectName $ProjectName
        )
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
