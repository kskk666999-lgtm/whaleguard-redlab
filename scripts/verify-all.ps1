param(
    [switch]$SkipInstall,
    [switch]$SkipE2E,
    [switch]$SkipSmoke,
    [string]$CredentialPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

function Invoke-WgChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = ""
    )
    Write-Host "==> $Label"
    $previous = Get-Location
    try {
        if ($WorkingDirectory) { Set-Location -LiteralPath $WorkingDirectory }
        & $File @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Label failed with exit code $LASTEXITCODE"
        }
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

    Invoke-WgChecked -Label "Frontend component tests" -File $npm -Arguments @("test") -WorkingDirectory $webRoot
    Invoke-WgChecked -Label "Frontend lint" -File $npm -Arguments @("run", "lint") -WorkingDirectory $webRoot
    Invoke-WgChecked -Label "Frontend TypeScript check" -File $npm -Arguments @("run", "typecheck") -WorkingDirectory $webRoot
    Invoke-WgChecked -Label "Frontend production build" -File $npm -Arguments @("run", "build") -WorkingDirectory $webRoot
    if (-not $SkipE2E) {
        Invoke-WgChecked -Label "Playwright browser flow" -File $npm -Arguments @("run", "test:e2e") -WorkingDirectory $webRoot
    }

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        Invoke-WgChecked -Label "Docker Compose canonical config" -File $docker.Source -Arguments @("compose", "-f", "docker-compose.yml", "config", "--quiet") -WorkingDirectory $root
    }
    else {
        Write-Host "==> Docker CLI unavailable; canonical YAML/security validation passed, engine validation skipped."
    }

    if (-not $SkipSmoke) {
        $apiPort = Get-WgEnvValue -Name "API_PORT" -Default "8000"
        $webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
        $apiBase = "http://127.0.0.1:$apiPort"
        $webBase = "http://127.0.0.1:$webPort"
        $apiReady = Test-WgHttp -Uri "$apiBase/ready"
        $webReady = Test-WgHttp -Uri $webBase
        if (-not ($apiReady -and $webReady)) {
            Assert-WgDockerEngine | Out-Null
            Invoke-WgChecked -Label "Build and start complete Docker stack" -File $docker.Source -Arguments @("compose", "-f", "docker-compose.yml", "up", "-d", "--build") -WorkingDirectory $root
        }
        if (-not $CredentialPath) {
            $dockerCredentials = Join-Path $root ".local\first-run-credentials.txt"
            $localCredentials = Join-Path $root ".local\local-first-run-credentials.txt"
            $CredentialPath = if ($apiReady -and $webReady -and (Test-Path -LiteralPath $localCredentials -PathType Leaf)) {
                $localCredentials
            }
            else {
                $dockerCredentials
            }
        }
        Invoke-WgChecked -Label "Authenticated product smoke test" -File (Get-Command powershell.exe -ErrorAction Stop).Source -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\smoke-test.ps1", "-ApiBase", "$apiBase/api/v1", "-WebBase", $webBase, "-CredentialPath", $credentialPath) -WorkingDirectory $root
    }

    Write-Host "VERIFY_ALL_OK"
    exit 0
}
catch {
    Write-Error "VERIFY_ALL_FAILED: $($_.Exception.Message)"
    exit 1
}
