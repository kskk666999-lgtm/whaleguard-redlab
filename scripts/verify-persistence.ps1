param(
    [string]$ApiBase = "http://127.0.0.1:8000/api/v1",
    [string]$WebBase = "http://127.0.0.1:3000",
    [string]$CredentialPath = "",
    [string]$CheckpointPath = "",
    [ValidateSet("restart", "down-up")][string]$Phase = "restart",
    [ValidateRange(30, 600)][int]$TimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

function Assert-WgValue {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) { throw $Message }
}

function Read-WgCredentials {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "First-run credentials were not found at $Path"
    }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^([^=]+)=(.*)$") {
            $values[$Matches[1].Trim().ToLowerInvariant()] = $Matches[2]
        }
    }
    if (-not $values.ContainsKey("username") -or -not $values.ContainsKey("password")) {
        throw "The first-run credential file is incomplete."
    }
    return $values
}

function Invoke-WgApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body = $null,
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 30
    )
    $request = @{
        Uri = "$ApiBase$Path"
        Method = $Method
        Headers = $Headers
        TimeoutSec = $TimeoutSec
    }
    if ($null -ne $Body) {
        $request["ContentType"] = "application/json"
        $request["Body"] = $Body | ConvertTo-Json -Depth 10 -Compress
    }
    return Invoke-RestMethod @request
}

try {
    $root = Get-WgRoot
    $null = Start-WgOperationLog -Name "persistence-$Phase"
    if (-not $CredentialPath) {
        $CredentialPath = Join-Path $root ".local\first-run-credentials.txt"
    }
    if (-not $CheckpointPath) {
        $CheckpointPath = Join-Path $root ".local\docker-persistence-checkpoint.json"
    }
    if (-not (Test-Path -LiteralPath $CheckpointPath -PathType Leaf)) {
        throw "Persistence checkpoint was not found at $CheckpointPath"
    }
    $checkpoint = Get-Content -Raw -LiteralPath $CheckpointPath | ConvertFrom-Json
    Assert-WgValue ($checkpoint.schema_version -eq 2) "Unsupported persistence checkpoint schema; run the current smoke test again."
    Assert-WgValue (-not [string]::IsNullOrWhiteSpace([string]$checkpoint.run_project_id)) "Persistence checkpoint has no TestRun project identity."
    Assert-WgValue ($checkpoint.expected_evidence_count -gt 0 -and $checkpoint.expected_evidence_count -le 100) "Persistence checkpoint has an invalid Evidence count."
    $expectedEvidenceEntries = @($checkpoint.evidence_entries)
    Assert-WgValue ($expectedEvidenceEntries.Count -eq $checkpoint.expected_evidence_count) "Persistence checkpoint has an incomplete Evidence identity set."

    $expectedEvidenceById = @{}
    foreach ($expectedEvidence in $expectedEvidenceEntries) {
        $expectedEvidenceId = [string]$expectedEvidence.id
        Assert-WgValue (-not [string]::IsNullOrWhiteSpace($expectedEvidenceId)) "Persistence checkpoint contains Evidence without an identity."
        Assert-WgValue (-not $expectedEvidenceById.ContainsKey($expectedEvidenceId)) "Persistence checkpoint contains a duplicate Evidence identity."
        Assert-WgValue ([string]$expectedEvidence.project_id -eq [string]$checkpoint.run_project_id) "Persistence checkpoint contains an Evidence project mismatch."
        Assert-WgValue ([string]$expectedEvidence.run_id -eq [string]$checkpoint.run_id) "Persistence checkpoint contains an Evidence TestRun mismatch."
        Assert-WgValue (-not [string]::IsNullOrWhiteSpace([string]$expectedEvidence.evidence_type)) "Persistence checkpoint contains Evidence without a type."
        Assert-WgValue ([string]$expectedEvidence.sha256 -cmatch "^[0-9a-f]{64}$") "Persistence checkpoint contains an invalid Evidence SHA-256 digest."
        $expectedEvidenceById[$expectedEvidenceId] = $expectedEvidence
    }

    $apiPort = ([Uri]($ApiBase -replace "/api/v1/?$", "")).Port
    $webPort = ([Uri]$WebBase).Port
    $null = Wait-WgStackHealthy -ApiPort $apiPort -WebPort $webPort -TimeoutSeconds $TimeoutSeconds

    $credentials = Read-WgCredentials -Path $CredentialPath
    $login = Invoke-WgApi -Method POST -Path "/auth/login" -Body @{
        username = $credentials["username"]
        password = $credentials["password"]
    }
    Assert-WgValue ([bool]$login.access_token) "Login failed after $Phase."
    $headers = @{
        Authorization = "Bearer $($login.access_token)"
        "X-CSRF-Token" = $login.csrf_token
    }

    $project = Invoke-WgApi -Method GET -Path "/projects/$($checkpoint.project_id)" -Headers $headers
    Assert-WgValue ([string]$project.id -eq [string]$checkpoint.project_id) "Project was not retained after $Phase."

    $run = Invoke-WgApi -Method GET -Path "/runs/$($checkpoint.run_id)" -Headers $headers
    Assert-WgValue ([string]$run.id -eq [string]$checkpoint.run_id) "TestRun was not retained after $Phase."
    Assert-WgValue ([string]$run.project_id -eq [string]$checkpoint.run_project_id) "TestRun project association changed after $Phase."
    Assert-WgValue ($run.status -eq "completed") "Persisted TestRun is no longer completed after $Phase."
    $results = Invoke-WgApi -Method GET -Path "/runs/$($checkpoint.run_id)/results?page_size=100" -Headers $headers
    Assert-WgValue ($results.total -eq $checkpoint.expected_result_count) "TestResult count changed after $Phase."

    $persistedEvidence = Invoke-WgApi -Method GET -Path "/evidence?project_id=$($checkpoint.run_project_id)&run_id=$($checkpoint.run_id)&page_size=100" -Headers $headers
    $persistedEvidenceItems = @($persistedEvidence.items)
    Assert-WgValue ($persistedEvidence.total -eq $checkpoint.expected_evidence_count) "Evidence count changed after $Phase."
    Assert-WgValue ($persistedEvidenceItems.Count -eq $checkpoint.expected_evidence_count) "Evidence page is incomplete after $Phase."
    $persistedEvidenceById = @{}
    foreach ($evidenceItem in $persistedEvidenceItems) {
        $evidenceId = [string]$evidenceItem.id
        Assert-WgValue (-not [string]::IsNullOrWhiteSpace($evidenceId)) "Persisted Evidence has no identity after $Phase."
        Assert-WgValue (-not $persistedEvidenceById.ContainsKey($evidenceId)) "Persisted Evidence contains a duplicate identity after $Phase."
        Assert-WgValue ($expectedEvidenceById.ContainsKey($evidenceId)) "Unexpected Evidence identity appeared after $Phase."
        $persistedEvidenceById[$evidenceId] = $evidenceItem
    }
    foreach ($expectedEvidence in $expectedEvidenceEntries) {
        $evidenceId = [string]$expectedEvidence.id
        Assert-WgValue ($persistedEvidenceById.ContainsKey($evidenceId)) "Expected Evidence identity was not retained after $Phase."
        $evidenceItem = $persistedEvidenceById[$evidenceId]
        Assert-WgValue ([string]$evidenceItem.project_id -eq [string]$expectedEvidence.project_id) "Evidence project association changed after $Phase."
        Assert-WgValue ([string]$evidenceItem.run_id -eq [string]$expectedEvidence.run_id) "Evidence TestRun association changed after $Phase."
        Assert-WgValue ([string]$evidenceItem.finding_id -eq [string]$expectedEvidence.finding_id) "Evidence Finding association changed after $Phase."
        Assert-WgValue ([string]$evidenceItem.evidence_type -ceq [string]$expectedEvidence.evidence_type) "Evidence type changed after $Phase."
        Assert-WgValue ([string]$evidenceItem.sha256 -ceq [string]$expectedEvidence.sha256) "Evidence SHA-256 digest changed after $Phase."
    }

    $finding = Invoke-WgApi -Method GET -Path "/findings/$($checkpoint.finding_id)" -Headers $headers
    Assert-WgValue ([string]$finding.run_id -eq [string]$checkpoint.run_id) "Finding was not retained after $Phase."

    $report = Invoke-WgApi -Method GET -Path "/reports/$($checkpoint.report_id)" -Headers $headers
    Assert-WgValue ($report.status -eq "generated") "Report metadata was not retained after $Phase."
    $downloadPath = Join-Path $root ".local\persistence-report-$Phase.html"
    Invoke-WebRequest -UseBasicParsing -Uri "$ApiBase/reports/$($checkpoint.report_id)/download?format=html" -Headers $headers -OutFile $downloadPath -TimeoutSec 30
    $downloadHash = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-WgValue ($downloadHash -eq [string]$checkpoint.report_sha256) "Report content hash changed after $Phase."

    foreach ($auditEntry in @($checkpoint.audit_entries)) {
        $action = [string]$auditEntry.action
        $encodedAction = [Uri]::EscapeDataString($action)
        $audit = Invoke-WgApi -Method GET -Path "/audit-logs?action=$encodedAction&page_size=100" -Headers $headers
        $retained = @($audit.items | Where-Object { [string]$_.id -eq [string]$auditEntry.id })
        Assert-WgValue ($retained.Count -eq 1) "Exact audit entry was not retained after $Phase`: $action"
    }

    Write-WgMessage -Message "PERSISTENCE_OK phase=$Phase project_id=$($checkpoint.project_id) run_id=$($checkpoint.run_id) finding_id=$($checkpoint.finding_id) report_id=$($checkpoint.report_id)" -Color "Green"
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)"
    exit 0
}
catch {
    Write-WgMessage -Message "PERSISTENCE_FAILED phase=$Phase`: $($_.Exception.Message)" -Level "ERROR" -Color "Red"
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)" -Level "ERROR"
    exit 1
}
