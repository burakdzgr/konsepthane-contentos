# Smoke-check a running ContentOS stack: backend health and the admin panel.

$ErrorActionPreference = "Stop"
$apiPort = if ($env:CONTENTOS_API_HOST_PORT) { $env:CONTENTOS_API_HOST_PORT } else { "8000" }
$adminPort = if ($env:CONTENTOS_ADMIN_PORT) { $env:CONTENTOS_ADMIN_PORT } else { "3000" }
$apiBase = "http://127.0.0.1:$apiPort"
$adminBase = "http://127.0.0.1:$adminPort"

$script:failed = $false

function Get-CheckedBody {
    param([string]$Url, [int]$ExpectedStatus)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20
        $status = [int]$response.StatusCode
        $body = [string]$response.Content
    } catch {
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            $body = ""
        } else {
            Write-Host "FAIL $Url -> no response ($($_.Exception.Message))"
            $script:failed = $true
            return $null
        }
    }
    if ($status -ne $ExpectedStatus) {
        Write-Host "FAIL $Url -> $status (expected $ExpectedStatus)"
        $script:failed = $true
        return $null
    }
    Write-Host "OK   $Url -> $status"
    return $body
}

$null = Get-CheckedBody -Url "$apiBase/health/live" -ExpectedStatus 200
$null = Get-CheckedBody -Url "$apiBase/health/ready" -ExpectedStatus 200
$null = Get-CheckedBody -Url "$adminBase/api/health" -ExpectedStatus 200
$adminPage = Get-CheckedBody -Url "$adminBase/" -ExpectedStatus 200

if ($null -ne $adminPage) {
    if ($adminPage -match "Foundation Status" -and $adminPage -match "Operational") {
        Write-Host "OK   admin page reflects backend readiness"
    } else {
        Write-Host "FAIL admin page does not show an operational backend"
        $script:failed = $true
    }
    if ($adminPage -match "Unavailable") {
        Write-Host "FAIL admin page reports the backend as unavailable"
        $script:failed = $true
    }
    if ($adminPage -match "api:8000" -or $adminPage -match "CONTENTOS_INTERNAL_API_URL") {
        Write-Host "FAIL admin page leaks the internal API URL"
        $script:failed = $true
    }
}

if ($script:failed) {
    Write-Host "Smoke check FAILED."
    exit 1
}
Write-Host "Smoke check passed."
exit 0
