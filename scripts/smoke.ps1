# Smoke-check a running ContentOS backend stack: API liveness and readiness.

$ErrorActionPreference = "Stop"
$apiPort = if ($env:CONTENTOS_API_HOST_PORT) { $env:CONTENTOS_API_HOST_PORT } else { "8000" }
$baseUrl = "http://127.0.0.1:$apiPort"

function Test-Endpoint {
    param([string]$Path, [int]$ExpectedStatus)
    try {
        $response = Invoke-WebRequest -Uri "$baseUrl$Path" -UseBasicParsing -TimeoutSec 10
        $status = [int]$response.StatusCode
        $body = $response.Content
    } catch {
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            $body = ""
        } else {
            Write-Host "FAIL $Path -> no response ($($_.Exception.Message))"
            return $false
        }
    }
    if ($status -eq $ExpectedStatus) {
        Write-Host "OK   $Path -> $status $body"
        return $true
    }
    Write-Host "FAIL $Path -> $status (expected $ExpectedStatus) $body"
    return $false
}

$allPassed = $true
if (-not (Test-Endpoint -Path "/health/live" -ExpectedStatus 200)) { $allPassed = $false }
if (-not (Test-Endpoint -Path "/health/ready" -ExpectedStatus 200)) { $allPassed = $false }

if (-not $allPassed) {
    Write-Host "Smoke check FAILED."
    exit 1
}
Write-Host "Smoke check passed."
exit 0
