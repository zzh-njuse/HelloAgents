param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceId,
    [Parameter(Mandatory = $true)]
    [string[]]$AlgorithmLesson,
    [Parameter(Mandatory = $true)]
    [string[]]$ScienceLesson,
    [Parameter(Mandatory = $true)]
    [string]$ConceptLesson,
    [string]$Judge0Url = 'https://ce.judge0.com',
    [string]$Output = '',
    [int]$Repetitions = 5,
    [int]$NegativeRepetitions = 3,
    [ValidateSet('python', 'java', 'cpp')]
    [string[]]$CodingLanguage = @(),
    [ValidateSet('code', 'coding', 'science', 'tutor', 'budget')]
    [string[]]$Section = @(),
    [switch]$Resume,
    [switch]$IncludeBudgetCurve,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
if ($Repetitions -lt 1 -or $NegativeRepetitions -lt 0) {
    throw 'required repetitions must be positive and negative repetitions non-negative'
}
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$driver = Join-Path $PSScriptRoot 'remote-gate.py'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'environment_failed: repository Python environment is missing'
}
if (-not (Test-Path -LiteralPath $driver)) {
    throw 'environment_failed: remote Gate driver is missing'
}
if ($AlgorithmLesson.Count -lt 2 -or $ScienceLesson.Count -lt 2) {
    throw 'environment_failed: two algorithm and two science lessons are required'
}
if (-not $Output) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $Output = Join-Path $repo (
        'docs\05-platform-stage-5-observability-system-validation-and-quality\' +
        "reviews\remote\slice2b-real-remote-$stamp.json"
    )
}

$hadBackend = Test-Path Env:EXECUTION_BACKEND_URL
$oldBackend = $env:EXECUTION_BACKEND_URL
$exitCode = 1

Push-Location $repo
try {
    $env:EXECUTION_BACKEND_URL = $Judge0Url
    docker compose up -d --no-deps --force-recreate mcp-execution capability-probe
    if ($LASTEXITCODE -ne 0) {
        throw 'environment_failed: could not activate the remote execution backend'
    }

    $deadline = (Get-Date).AddMinutes(3)
    do {
        try {
            $ready = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/ready' -TimeoutSec 5
            $codeReady = [bool]$ready.checks.code_execution.ok
            $scienceReady = [bool]$ready.checks.science_tool.ok
        }
        catch {
            $codeReady = $false
            $scienceReady = $false
        }
        if ($codeReady -and $scienceReady) {
            break
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    if (-not $codeReady) {
        throw 'environment_failed: Judge0 capability did not become ready'
    }
    if (-not $scienceReady) {
        throw 'environment_failed: Wolfram capability is not ready'
    }

    $arguments = @(
        $driver,
        '--workspace-id', $WorkspaceId,
        '--concept-lesson', $ConceptLesson,
        '--output', $Output,
        '--repetitions', $Repetitions,
        '--negative-repetitions', $NegativeRepetitions
    )
    foreach ($lesson in $AlgorithmLesson) {
        $arguments += @('--algorithm-lesson', $lesson)
    }
    foreach ($lesson in $ScienceLesson) {
        $arguments += @('--science-lesson', $lesson)
    }
    foreach ($name in $Section) {
        $arguments += @('--section', $name)
    }
    foreach ($language in $CodingLanguage) {
        $arguments += @('--coding-language', $language)
    }
    if ($Resume) {
        $arguments += '--resume'
    }
    if ($IncludeBudgetCurve) {
        $arguments += '--include-budget-curve'
    }
    if ($PreflightOnly) {
        $arguments += '--preflight-only'
    }

    & $python @arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "remote Gate failed with exit code $exitCode"
    }
}
finally {
    if ($hadBackend) {
        $env:EXECUTION_BACKEND_URL = $oldBackend
    }
    else {
        Remove-Item Env:EXECUTION_BACKEND_URL -ErrorAction SilentlyContinue
    }
    docker compose up -d --no-deps --force-recreate mcp-execution capability-probe
    $restoreExit = $LASTEXITCODE
    Pop-Location
    if ($restoreExit -ne 0 -and $exitCode -eq 0) {
        throw 'environment_failed: Gate passed but the prior execution backend could not be restored'
    }
}

if (-not $PreflightOnly) {
    Write-Host "REMOTE GATE REPORT: $Output"
}
