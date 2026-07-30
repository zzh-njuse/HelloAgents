$ErrorActionPreference = 'Stop'

# Run from the repository root regardless of the caller's working directory.
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

$project = if ($env:SYSTEM_TEST_PROJECT) { $env:SYSTEM_TEST_PROJECT } else { 'ha_stage5_2b' }
$files = @('-f', 'docker-compose.yml', '-f', 'compose.system-test.yml')

try {
    # One controlled-system command: build, readiness (healthchecks, no fixed
    # sleep), run the Practice+Tutor double-MCP vertical tests, then clean up.
    docker compose -p $project @files up --build --abort-on-container-exit --exit-code-from system-test-runner system-test-runner
    if ($LASTEXITCODE -ne 0) {
        throw "Controlled system test failed with exit code $LASTEXITCODE."
    }
}
finally {
    docker compose -p $project @files down --volumes --remove-orphans
}
