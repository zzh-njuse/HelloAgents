$ErrorActionPreference = 'Stop'

$project = if ($env:BROWSER_TEST_PROJECT) { $env:BROWSER_TEST_PROJECT } else { 'ha_stage5_2b_browser' }
$files = @('-f', 'docker-compose.yml', '-f', 'compose.system-test.yml')
$url = if ($env:PLAYWRIGHT_TEST_BASE_URL) { $env:PLAYWRIGHT_TEST_BASE_URL } else { 'http://127.0.0.1:18080' }
$stubUrl = if ($env:SYSTEM_TEST_STUB_URL) { $env:SYSTEM_TEST_STUB_URL } else { 'http://127.0.0.1:18091' }
$fakeExecUrl = if ($env:SYSTEM_TEST_FAKE_EXEC_URL) { $env:SYSTEM_TEST_FAKE_EXEC_URL } else { 'http://127.0.0.1:18092' }
$fakeWolframUrl = if ($env:SYSTEM_TEST_FAKE_WOLFRAM_URL) { $env:SYSTEM_TEST_FAKE_WOLFRAM_URL } else { 'http://127.0.0.1:18093' }

try {
    # Full tool stack: web + both workers + capability probe (+deps: api, fakes,
    # mcp-execution, postgres, redis, qdrant, stub). Practice grading needs the
    # practice-worker; capability readiness needs the probe.
    docker compose -p $project @files up --build --detach web practice-worker tutor-system-worker capability-probe
    if ($LASTEXITCODE -ne 0) {
        throw "Browser test environment failed to start."
    }

    # Readiness poll (no fixed sleep): wait for the web root. Capability
    # readiness (written by the real probe) is enforced by the seed scripts'
    # own wait_for_environment, which runs inside the runner against the API.
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt += 1) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) {
        throw "environment_failed:web_not_ready"
    }

    docker compose -p $project @files run --build --rm --no-deps system-test-runner `
        python tests/system/seed_browser_tutor.py
    if ($LASTEXITCODE -ne 0) { throw "Browser Tutor fixture failed to seed." }
    docker compose -p $project @files run --build --rm --no-deps system-test-runner `
        python tests/system/seed_browser_tools.py
    if ($LASTEXITCODE -ne 0) { throw "Browser tools fixture failed to seed." }

    Push-Location apps/web
    try {
        $env:PLAYWRIGHT_TEST_BASE_URL = $url
        $env:SYSTEM_TEST_STUB_URL = $stubUrl
        $env:SYSTEM_TEST_FAKE_EXEC_URL = $fakeExecUrl
        $env:SYSTEM_TEST_FAKE_WOLFRAM_URL = $fakeWolframUrl
        if (-not $env:PLAYWRIGHT_CHANNEL) {
            $env:PLAYWRIGHT_CHANNEL = 'chrome'
        }
        npm.cmd run test:e2e
        if ($LASTEXITCODE -ne 0) {
            throw "Playwright failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    docker compose -p $project @files down --volumes --remove-orphans
}
