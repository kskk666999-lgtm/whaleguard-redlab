param(
    [switch]$SkipInstall,
    [switch]$SkipE2E,
    [switch]$SkipSmoke,
    [string]$CredentialPath = "",
    [ValidateSet("Docker", "Local")][string]$RuntimeMode = "Docker"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$dockerStackAttempted = $false

function Invoke-WgChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ""
    )
    Write-WgMessage -Message "==> $Label" -Color "Cyan"
    $previous = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location -LiteralPath $WorkingDirectory }
        & $File @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
        Write-WgMessage -Message "[PASS] $Label" -Color "Green"
    }
    finally {
        Set-Location -LiteralPath $previous
    }
}

function Get-WgNpm {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npm) { throw "npm was not found. Install Node.js 20 or newer." }
    return $npm.Source
}

try {
    $root = Get-WgRoot
    $null = Start-WgOperationLog -Name "verify"
    Write-WgMessage -Message "Verification runtime mode: $RuntimeMode"
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $systemPython = Get-WgPython
        Invoke-WgChecked -Label "Create Python virtual environment" -File $systemPython.File -Arguments (@($systemPython.Args) + @("-m", "venv", ".venv")) -WorkingDirectory $root
    }
    $python = $venvPython
    $npm = Get-WgNpm
    $webRoot = Join-Path $root "apps\web"

    if (-not $SkipInstall) {
        Invoke-WgChecked -Label "Install Python build tools" -File $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-U", "pip") -WorkingDirectory $root
        Invoke-WgChecked -Label "Install policy engine" -File $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-e", ".\packages\policy-engine[test]") -WorkingDirectory $root
        Invoke-WgChecked -Label "Install worker" -File $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-e", ".\apps\worker[test]") -WorkingDirectory $root
        Invoke-WgChecked -Label "Install API and root validators" -File $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-e", ".\apps\api[dev]", "pyyaml", "jsonschema") -WorkingDirectory $root
        foreach ($lab in @("mock-llm", "mock-agent", "mock-mcp-server")) {
            Invoke-WgChecked -Label "Install $lab test dependencies" -File $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements-dev.txt") -WorkingDirectory (Join-Path $root "labs\$lab")
        }
        Invoke-WgChecked -Label "Install web dependencies" -File $npm -Arguments @("ci") -WorkingDirectory $webRoot
        if (-not $SkipE2E) {
            $npx = (Get-Command npx.cmd -ErrorAction Stop).Source
            Invoke-WgChecked -Label "Install Playwright Chromium" -File $npx -Arguments @("playwright", "install", "chromium") -WorkingDirectory $webRoot
        }
    }

    Invoke-WgChecked -Label "Validate 15 safe test cases" -File $python -Arguments @("scripts\validate_test_cases.py") -WorkingDirectory $root
    Invoke-WgChecked -Label "Validate Compose security invariants" -File $python -Arguments @("scripts\validate_compose.py") -WorkingDirectory $root
    Invoke-WgChecked -Label "Python formatting check" -File $python -Arguments @("-m", "ruff", "format", "--check", "apps", "packages", "labs", "scripts") -WorkingDirectory $root
    Invoke-WgChecked -Label "Python lint" -File $python -Arguments @("-m", "ruff", "check", "apps", "packages", "labs", "scripts") -WorkingDirectory $root

    Invoke-WgChecked -Label "Scope Guard tests" -File $python -Arguments @("-m", "pytest", "-q") -WorkingDirectory (Join-Path $root "packages\policy-engine")
    Invoke-WgChecked -Label "Worker tests" -File $python -Arguments @("-m", "pytest", "-q") -WorkingDirectory (Join-Path $root "apps\worker")
    Invoke-WgChecked -Label "API unit and integration tests" -File $python -Arguments @("-m", "pytest", "-q") -WorkingDirectory (Join-Path $root "apps\api")
    foreach ($lab in @("mock-llm", "mock-agent", "mock-mcp-server")) {
        Invoke-WgChecked -Label "$lab tests" -File $python -Arguments @("-m", "pytest", "-q") -WorkingDirectory (Join-Path $root "labs\$lab")
    }
    Invoke-WgChecked -Label "Alembic upgrade/downgrade/upgrade" -File $python -Arguments @("scripts\test_migrations.py") -WorkingDirectory $root
    Invoke-WgChecked -Label "Windows automation tests" -File $python -Arguments @("-m", "pytest", "-q", "scripts\tests") -WorkingDirectory $root

    Invoke-WgChecked -Label "Frontend component tests" -File $npm -Arguments @("test") -WorkingDirectory $webRoot
    Invoke-WgChecked -Label "Frontend lint" -File $npm -Arguments @("run", "lint") -WorkingDirectory $webRoot
    Invoke-WgChecked -Label "Frontend TypeScript check" -File $npm -Arguments @("run", "typecheck") -WorkingDirectory $webRoot
    Invoke-WgChecked -Label "Frontend production build" -File $npm -Arguments @("run", "build") -WorkingDirectory $webRoot
    if (-not $SkipE2E) {
        Invoke-WgChecked -Label "Playwright browser flow" -File $npm -Arguments @("run", "test:e2e") -WorkingDirectory $webRoot
    }

    $dockerPath = $null
    try { $dockerPath = Get-WgDocker } catch { }
    if ($dockerPath) {
        $target = Get-WgLocalDockerTarget -Docker $dockerPath
        Assert-WgComposeOwnership -Docker $dockerPath -Endpoint $target.Endpoint
        Write-WgMessage -Message "==> Docker Compose canonical config" -Color "Cyan"
        Invoke-WgCompose -Arguments @("config", "--quiet")
        Write-WgMessage -Message "[PASS] Docker Compose canonical config" -Color "Green"
    }
    else {
        Write-WgMessage -Message "==> Docker CLI unavailable; canonical YAML/security validation passed, engine validation skipped." -Level "WARN" -Color "Yellow"
    }

    if (-not $SkipSmoke) {
        $apiPort = Get-WgEnvValue -Name "API_PORT" -Default "8000"
        $webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
        $apiBase = "http://127.0.0.1:$apiPort"
        $webBase = "http://127.0.0.1:$webPort"
        $apiReady = Test-WgApiReady -Uri "$apiBase/ready"
        $webReady = Test-WgHttp -Uri $webBase
        if ($RuntimeMode -eq "Docker") {
            $dockerPath = Assert-WgDockerEngine
            $target = Get-WgLocalDockerTarget -Docker $dockerPath
            Assert-WgComposeOwnership -Docker $dockerPath -Endpoint $target.Endpoint
            $dockerStackAttempted = $true
            Write-WgMessage -Message "==> Build and start complete Docker stack" -Color "Cyan"
            Invoke-WgCompose -Arguments @("up", "-d", "--build")
            Write-WgMessage -Message "[PASS] Build and start complete Docker stack" -Color "Green"
            $null = Wait-WgStackHealthy -ApiPort ([int]$apiPort) -WebPort ([int]$webPort) -TimeoutSeconds 300
            if (-not $CredentialPath) {
                $CredentialPath = Join-Path $root ".local\first-run-credentials.txt"
            }
        }
        else {
            if (-not ($apiReady -and $webReady)) {
                throw "Local runtime mode requires an already-running API /ready endpoint and Web application."
            }
            if (-not $CredentialPath) {
                $CredentialPath = Join-Path $root ".local\local-first-run-credentials.txt"
            }
        }
        Invoke-WgChecked -Label "Authenticated product smoke test" -File (Get-Command powershell.exe -ErrorAction Stop).Source -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\smoke-test.ps1", "-ApiBase", "$apiBase/api/v1", "-WebBase", $webBase, "-CredentialPath", $CredentialPath, "-RuntimeMode", $RuntimeMode) -WorkingDirectory $root
    }

    Write-WgMessage -Message "VERIFY_ALL_OK" -Color "Green"
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)"
    exit 0
}
catch {
    Write-WgMessage -Message "VERIFY_ALL_FAILED: $($_.Exception.Message)" -Level "ERROR" -Color "Red"
    if ($dockerStackAttempted) { Write-WgComposeDiagnostics -Tail 80 }
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)" -Level "ERROR"
    exit 1
}
