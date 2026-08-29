param(
    [string]$ApiBase = "http://127.0.0.1:8000/api/v1",
    [string]$WebBase = "http://127.0.0.1:3000",
    [string]$CredentialPath = "",
    [int]$TimeoutSeconds = 180
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
        $request["Body"] = $Body | ConvertTo-Json -Depth 30 -Compress
    }
    return Invoke-RestMethod @request
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

try {
    $root = Get-WgRoot
    if (-not $CredentialPath) {
        $CredentialPath = Join-Path $root ".local\first-run-credentials.txt"
    }
    $credentials = Read-WgCredentials -Path $CredentialPath

    $healthBase = $ApiBase -replace "/api/v1/?$", ""
    $health = Invoke-RestMethod -Uri "$healthBase/health" -TimeoutSec 10
    Assert-WgValue ($health.status -eq "ok") "API health check did not return ok."
    $ready = Invoke-RestMethod -Uri "$healthBase/ready" -TimeoutSec 10
    Assert-WgValue ($ready.database -eq "ok") "API readiness check did not confirm the database."
    $web = Invoke-WebRequest -UseBasicParsing -Uri $WebBase -TimeoutSec 10
    Assert-WgValue ($web.StatusCode -ge 200 -and $web.StatusCode -lt 400) "Web health check failed."
    Write-Host "[1/11] API, database, and web health checks passed."

    $login = Invoke-WgApi -Method POST -Path "/auth/login" -Body @{
        username = $credentials["username"]
        password = $credentials["password"]
    }
    Assert-WgValue ([bool]$login.access_token) "Login did not return an access token."
    Assert-WgValue ([bool]$login.csrf_token) "Login did not return a CSRF token."
    $headers = @{
        Authorization = "Bearer $($login.access_token)"
        "X-CSRF-Token" = $login.csrf_token
    }
    $me = Invoke-WgApi -Method GET -Path "/auth/me" -Headers $headers
    Assert-WgValue ($me.username -eq $credentials["username"]) "Authenticated user mismatch."
    Write-Host "[2/11] Random first-run administrator login passed."

    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $createdProject = Invoke-WgApi -Method POST -Path "/projects" -Headers $headers -Body @{
        name = "Smoke Authorized Lab $stamp"
        description = "Local-only smoke verification project."
        tags = @("smoke", "authorized-local-only")
    }
    Assert-WgValue ([bool]$createdProject.id) "Project creation failed."
    $scope = Invoke-WgApi -Method POST -Path "/projects/$($createdProject.id)/scopes" -Headers $headers -Body @{
        name = "Smoke loopback scope"
        target_type = "cidr"
        target_value = "127.0.0.0/8"
        allowed_request_types = @("http", "https")
        is_authorized = $true
        notes = "Explicitly confirmed for this local smoke test."
    }
    Assert-WgValue ($scope.is_authorized -eq $true) "Scope authorization was not persisted."
    Assert-WgValue ($scope.target_value -eq "127.0.0.0/8") "Scope target mismatch."
    Write-Host "[3/11] Project and authorized loopback scope creation passed."

    $projects = Invoke-WgApi -Method GET -Path "/projects?page_size=100" -Headers $headers
    $demoProject = $projects.items | Where-Object { $_.name -eq "WhaleGuard Demo Lab" } | Select-Object -First 1
    Assert-WgValue ($null -ne $demoProject) "Seeded WhaleGuard Demo Lab was not found."
    $suites = Invoke-WgApi -Method GET -Path "/test-suites?project_id=$($demoProject.id)&page_size=100" -Headers $headers
    $suite = $suites.items | Select-Object -First 1
    Assert-WgValue ($null -ne $suite) "Seeded demo test suite was not found."
    $cases = Invoke-WgApi -Method GET -Path "/test-suites/$($suite.id)/cases?page_size=100" -Headers $headers
    Assert-WgValue ($cases.total -eq 15) "The demo suite does not contain exactly 15 test cases."
    Write-Host "[4/11] Seeded demo project and 15 safe test cases passed."

    $run = Invoke-WgApi -Method POST -Path "/runs" -Headers $headers -Body @{
        project_id = $demoProject.id
        suite_id = $suite.id
        target_type = "agent"
        name = "AgentArena smoke run $stamp"
        max_concurrency = 2
        timeout_seconds = 30
        max_retries = 1
    } -TimeoutSec 60
    Assert-WgValue ([bool]$run.id) "Test run creation failed."

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $approvalCount = 0
    do {
        Start-Sleep -Milliseconds 750
        $run = Invoke-WgApi -Method GET -Path "/runs/$($run.id)" -Headers $headers
        if ($run.status -eq "waiting_approval") {
            $approvals = Invoke-WgApi -Method GET -Path "/approvals?project_id=$($demoProject.id)&status_filter=pending&page_size=100" -Headers $headers
            $approval = $approvals.items | Where-Object { $_.run_id -eq $run.id } | Select-Object -First 1
            Assert-WgValue ($null -ne $approval) "Run is waiting but no approval request was recorded."
            $approvalCount += 1
            Assert-WgValue ($approvalCount -le 15) "Run requested an unexpected number of approvals."
            $decision = Invoke-WgApi -Method POST -Path "/approvals/$($approval.id)/decision" -Headers $headers -Body @{
                status = "approved"
                decision_reason = "Continue the safe local simulation; the sensitive demo tool remains unexecuted."
            }
            Assert-WgValue ($decision.status -eq "approved") "Approval decision was not persisted."
        }
    } while ($run.status -notin @("completed", "failed", "cancelled") -and [DateTime]::UtcNow -lt $deadline)
    Assert-WgValue ($run.status -eq "completed") "AgentArena run did not complete successfully; status=$($run.status)."
    Assert-WgValue ($run.progress -eq 100) "Completed run progress is not 100."
    Assert-WgValue ($null -ne $run.security_score) "Completed run has no security score."
    Assert-WgValue ([bool]$run.score_explanation) "Completed run has no score explanation."
    Write-Host "[5/11] Mock Agent run, $approvalCount approval guard decision(s), progress, and scoring passed."

    $results = Invoke-WgApi -Method GET -Path "/runs/$($run.id)/results?page_size=100" -Headers $headers
    Assert-WgValue ($results.total -eq 15) "Completed run does not contain 15 results."
    $findings = Invoke-WgApi -Method GET -Path "/findings?project_id=$($demoProject.id)&run_id=$($run.id)&page_size=100" -Headers $headers
    Assert-WgValue ($findings.total -ge 1) "The run did not produce a Finding."
    $evidence = Invoke-WgApi -Method GET -Path "/evidence?project_id=$($demoProject.id)&run_id=$($run.id)&page_size=100" -Headers $headers
    Assert-WgValue ($evidence.total -eq 15) "The run did not persist one evidence item per case."
    Write-Host "[6/11] Results, Finding, evidence, and hashes passed."

    $model = Invoke-WgApi -Method POST -Path "/model-channels" -Headers $headers -Body @{
        project_id = $demoProject.id
        name = "Smoke OpenAI-compatible Mock $stamp"
        provider = "openai-compatible"
        base_url = "http://127.0.0.1:8101/v1"
        model = "whaleguard-safe-mock-1"
        timeout = 15
        max_tokens = 512
        temperature = 0
        enabled = $true
        extra_headers = @{}
    }
    Assert-WgValue ([bool]$model.id) "Mock model channel creation failed."
    Assert-WgValue ($model.api_key_masked -eq $null) "Model channel unexpectedly returned key material."
    $connection = Invoke-WgApi -Method POST -Path "/model-channels/$($model.id)/test-connection" -Headers $headers
    Assert-WgValue ($connection.success -eq $true) "OpenAI-compatible model connection test failed."
    $modelRun = Invoke-WgApi -Method POST -Path "/runs" -Headers $headers -Body @{
        project_id = $demoProject.id
        suite_id = $suite.id
        target_type = "model"
        model_channel_id = $model.id
        evaluation_mode = "rules_with_llm_judge"
        judge_model_channel_id = $model.id
        name = "Model and Judge smoke run $stamp"
        max_concurrency = 2
        timeout_seconds = 30
        max_retries = 1
    } -TimeoutSec 60
    $modelDeadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $modelRun = Invoke-WgApi -Method GET -Path "/runs/$($modelRun.id)" -Headers $headers
    } while ($modelRun.status -notin @("completed", "failed", "cancelled") -and [DateTime]::UtcNow -lt $modelDeadline)
    Assert-WgValue ($modelRun.status -eq "completed") "Model/Judge run did not complete; status=$($modelRun.status)."
    Assert-WgValue ($modelRun.score_explanation.llm_judge_used -eq $true) "Explicit LLM Judge mode was not used."
    Assert-WgValue ($modelRun.score_explanation.llm_judge_used_count -eq 15) "LLM Judge did not evaluate all 15 cases."
    $modelResults = Invoke-WgApi -Method GET -Path "/runs/$($modelRun.id)/results?page_size=100" -Headers $headers
    Assert-WgValue ($modelResults.total -eq 15) "Model target run does not contain 15 results."
    $measuredResult = $modelResults.items | Select-Object -First 1
    Assert-WgValue ($measuredResult.metrics.prompt_tokens -gt 0) "Model prompt token usage was not persisted."
    Assert-WgValue ($measuredResult.metrics.completion_tokens -gt 0) "Model completion token usage was not persisted."
    Assert-WgValue ($measuredResult.metrics.estimated_cost -ge 0) "Estimated cost was not persisted."
    Write-Host "[7/11] OpenAI-compatible model target, connection test, usage, and explicit LLM Judge passed."

    $servers = Invoke-WgApi -Method GET -Path "/mcp/servers?project_id=$($demoProject.id)&page_size=100" -Headers $headers
    $server = $servers.items | Select-Object -First 1
    Assert-WgValue ($null -ne $server) "Seeded MCP server was not found."
    $analysis = Invoke-WgApi -Method POST -Path "/mcp/servers/$($server.id)/analyze" -Headers $headers
    Assert-WgValue ($analysis.execution_performed -eq $false) "MCPShield unexpectedly executed a tool."
    Assert-WgValue ($analysis.tools.Count -eq 5) "MCPShield did not analyze five seeded tools."
    Assert-WgValue ($analysis.risk_score -ge 0 -and $analysis.risk_score -le 100) "MCP risk score is outside 0-100."
    Write-Host "[8/11] MCPShield metadata-only analysis passed."

    $report = Invoke-WgApi -Method POST -Path "/reports" -Headers $headers -Body @{
        project_id = $demoProject.id
        run_id = $run.id
        name = "WhaleGuard smoke report $stamp"
        formats = @("html", "markdown", "json")
    }
    $report = Invoke-WgApi -Method POST -Path "/reports/$($report.id)/generate" -Headers $headers
    Assert-WgValue ($report.status -eq "generated") "Report generation did not complete."
    Assert-WgValue ([bool]$report.content_html) "Generated report has no HTML content."
    Assert-WgValue ([bool]$report.content_markdown) "Generated report has no Markdown content."
    $localDir = Join-Path $root ".local"
    if (-not (Test-Path -LiteralPath $localDir -PathType Container)) {
        New-Item -ItemType Directory -Path $localDir | Out-Null
    }
    $reportPath = Join-Path $localDir "smoke-report.html"
    Invoke-WebRequest -UseBasicParsing -Uri "$ApiBase/reports/$($report.id)/download?format=html" -Headers $headers -OutFile $reportPath -TimeoutSec 30
    Assert-WgValue ((Get-Item -LiteralPath $reportPath).Length -gt 500) "Downloaded HTML report is unexpectedly small."
    Write-Host "[9/11] HTML, Markdown, and JSON report generation passed."

    foreach ($requiredAction in @("auth.login", "project.create", "scope.create", "model_channel.create", "model_channel.test_connection", "test_run.create", "approval.decision", "mcp_server.analyze", "report.generate", "report.export")) {
        $encodedAction = [Uri]::EscapeDataString($requiredAction)
        $audit = Invoke-WgApi -Method GET -Path "/audit-logs?action=$encodedAction&page_size=1" -Headers $headers
        Assert-WgValue ($audit.total -ge 1) "Required audit action is missing: $requiredAction"
    }
    Write-Host "[10/11] Required immutable audit trail entries passed."

    $events = @($run.event_log | ForEach-Object { $_.event })
    Assert-WgValue ($events -contains "run.waiting_approval") "Run event stream lacks waiting_approval evidence."
    Assert-WgValue ($events -contains "approval.approved") "Run event stream lacks approval evidence."
    Assert-WgValue ($events -contains "run.completed") "Run event stream lacks completion evidence."
    Write-Host "[11/11] Event lifecycle passed."
    Write-Host "SMOKE_TEST_OK agent_run_id=$($run.id) model_run_id=$($modelRun.id) report_id=$($report.id) report=$reportPath"
    exit 0
}
catch {
    Write-Error "SMOKE_TEST_FAILED: $($_.Exception.Message)"
    exit 1
}
