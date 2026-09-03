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

# Phase 5 G2: every admin page except /login requires a session, so "/"
# lands on the login page (Invoke-WebRequest follows the redirect). The
# login page carries the truthful foundation status.
$adminPage = Get-CheckedBody -Url "$adminBase/" -ExpectedStatus 200

if ($null -ne $adminPage) {
    # The UI is Turkish; anchor on ASCII-safe markup (the login title id
    # and the status badge tone) so the check is encoding-independent.
    if ($adminPage -match 'id="login-title"') {
        Write-Host "OK   admin gate redirects to the login page"
    } else {
        Write-Host "FAIL admin did not present the login page"
        $script:failed = $true
    }
    if ($adminPage -match "Sistem Durumu" -and $adminPage -match 'data-tone="ok"') {
        Write-Host "OK   login page reflects backend readiness"
    } else {
        Write-Host "FAIL login page does not show an operational backend"
        $script:failed = $true
    }
    if ($adminPage -match 'data-tone="bad"') {
        Write-Host "FAIL login page reports the backend as unavailable"
        $script:failed = $true
    }
    if ($adminPage -match "api:8000" -or $adminPage -match "CONTENTOS_INTERNAL_API_URL") {
        Write-Host "FAIL admin page leaks the internal API URL"
        $script:failed = $true
    }
}

# Unauthenticated internal API access must be refused.
$unauthorized = $null
try {
    $unauthorized = Invoke-WebRequest -Uri "$apiBase/internal/editorial/work-items" `
        -UseBasicParsing -TimeoutSec 20
} catch {
    if ($_.Exception.Response) {
        $status = [int]$_.Exception.Response.StatusCode
        if ($status -eq 401) {
            Write-Host "OK   $apiBase/internal/editorial/work-items -> 401 (auth enforced)"
        } else {
            Write-Host "FAIL unauthenticated internal request -> $status (expected 401)"
            $script:failed = $true
        }
    } else {
        Write-Host "FAIL unauthenticated internal request -> no response"
        $script:failed = $true
    }
}
if ($null -ne $unauthorized) {
    Write-Host "FAIL unauthenticated internal request succeeded (expected 401)"
    $script:failed = $true
}

# Real end-to-end login: provision a smoke user inside the api container,
# then authenticate and read the identity back.
$smokePassword = "smoke-operator-password-1"
$env:CONTENTOS_NEW_PASSWORD = $smokePassword
docker compose exec -T -e CONTENTOS_NEW_PASSWORD=$smokePassword api `
    python -m contentos.auth.cli create-user smoke.operator `
    --display-name "Smoke Operator" --roles operator --reason "compose smoke" | Out-Null
if ($LASTEXITCODE -ne 0) {
    # Re-runnable on a persistent dev database: an already-provisioned
    # smoke user gets its known password rotated instead of failing.
    docker compose exec -T -e CONTENTOS_NEW_PASSWORD=$smokePassword api `
        python -m contentos.auth.cli set-password smoke.operator `
        --reason "compose smoke re-run" | Out-Null
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL could not provision the smoke user"
    $script:failed = $true
} else {
    try {
        $login = Invoke-RestMethod -Method Post -Uri "$apiBase/internal/auth/login" `
            -ContentType "application/json" `
            -Body (@{ username = "smoke.operator"; password = $smokePassword } | ConvertTo-Json) `
            -TimeoutSec 20
        $me = Invoke-RestMethod -Uri "$apiBase/internal/auth/me" `
            -Headers @{ Authorization = "Bearer $($login.token)" } -TimeoutSec 20
        if ($me.username -eq "smoke.operator") {
            Write-Host "OK   real login flow: provision -> login -> me"
        } else {
            Write-Host "FAIL login flow returned an unexpected identity"
            $script:failed = $true
        }
    } catch {
        Write-Host "FAIL login flow failed ($($_.Exception.Message))"
        $script:failed = $true
    }
}
Remove-Item Env:CONTENTOS_NEW_PASSWORD -ErrorAction SilentlyContinue

if ($script:failed) {
    Write-Host "Smoke check FAILED."
    exit 1
}
Write-Host "Smoke check passed."
exit 0
