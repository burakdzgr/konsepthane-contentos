# Canonical non-destructive local quality gate for ContentOS.
#
# Default: toolchain + backend + admin + repository checks, no Docker use.
# -Compose additionally validates, builds, starts, smoke-tests, and always
# tears down the ContentOS Compose stack (only this project's resources).

param(
    [switch]$Compose
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$stage = "startup"

function Invoke-Step {
    param([string]$Description, [scriptblock]$Action)
    Write-Host "-- $Description"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "'$Description' failed with exit code $LASTEXITCODE."
    }
}

function Assert-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required tool '$Name' was not found on PATH. $Hint"
    }
}

try {
    $stage = "toolchain"
    Write-Host "[toolchain]"
    Assert-Command -Name "git" -Hint "Git is required."
    Assert-Command -Name "uv" -Hint "uv is required for backend checks."
    Assert-Command -Name "node" -Hint "Node.js 24 is required for admin checks."
    Assert-Command -Name "corepack" -Hint "Corepack ships with Node.js 24."

    Invoke-Step -Description "Python 3.12 available (uv python find 3.12)" -Action {
        uv python find 3.12
    }

    $nodeVersion = node --version
    if ($nodeVersion -notmatch "^v24\.") {
        throw "Node 24.x is required, found $nodeVersion."
    }
    Write-Host "-- Node $nodeVersion"

    Push-Location $repoRoot
    try {
        $pnpmVersion = corepack pnpm --version
        if ($LASTEXITCODE -ne 0 -or $pnpmVersion -ne "11.15.1") {
            throw "pnpm 11.15.1 through corepack is required, found '$pnpmVersion'."
        }
        Write-Host "-- pnpm $pnpmVersion"
    } finally {
        Pop-Location
    }

    if ($Compose) {
        Assert-Command -Name "docker" -Hint "Docker is required for -Compose."
        Invoke-Step -Description "Docker daemon reachable" -Action {
            docker info --format "{{.ServerVersion}}"
        }
        Invoke-Step -Description "docker compose v2 available" -Action {
            docker compose version
        }
    }

    # Baseline so unintended modifications by the checks below are detected.
    $baselineStatus = git -C $repoRoot status --porcelain | Out-String

    $stage = "backend"
    Write-Host ""
    Write-Host "[backend]"
    Push-Location (Join-Path $repoRoot "apps\backend")
    try {
        Invoke-Step -Description "uv sync --all-groups --frozen" -Action {
            uv sync --all-groups --frozen
        }
        Invoke-Step -Description "ruff format --check" -Action { uv run ruff format --check . }
        Invoke-Step -Description "ruff check" -Action { uv run ruff check . }
        Invoke-Step -Description "mypy src" -Action { uv run mypy src }
        Invoke-Step -Description "pytest" -Action { uv run pytest }
    } finally {
        Pop-Location
    }

    $stage = "admin"
    Write-Host ""
    Write-Host "[admin]"
    Push-Location $repoRoot
    try {
        Invoke-Step -Description "pnpm install --frozen-lockfile" -Action {
            corepack pnpm install --frozen-lockfile
        }
        Invoke-Step -Description "admin format:check" -Action {
            corepack pnpm --filter admin format:check
        }
        Invoke-Step -Description "admin lint" -Action { corepack pnpm --filter admin lint }
        Invoke-Step -Description "admin typecheck" -Action { corepack pnpm --filter admin typecheck }
        Invoke-Step -Description "admin test" -Action { corepack pnpm --filter admin test }
        Invoke-Step -Description "admin build" -Action { corepack pnpm --filter admin build }
    } finally {
        Pop-Location
    }

    $stage = "repository"
    Write-Host ""
    Write-Host "[repository]"
    Invoke-Step -Description "git diff --check" -Action { git -C $repoRoot diff --check }

    $currentStatus = git -C $repoRoot status --porcelain | Out-String
    if ($currentStatus -ne $baselineStatus) {
        Write-Host "Tracked-file state before checks:"
        Write-Host $baselineStatus
        Write-Host "Tracked-file state after checks:"
        Write-Host $currentStatus
        throw "Validation modified the repository unexpectedly (see status difference above)."
    }
    Write-Host "-- no unintended repository modifications"

    if ($Compose) {
        $stage = "compose"
        Write-Host ""
        Write-Host "[compose]"
        Push-Location $repoRoot
        try {
            Invoke-Step -Description "docker compose config" -Action { docker compose config --quiet }
            Invoke-Step -Description "docker compose build" -Action { docker compose build }
            try {
                Invoke-Step -Description "docker compose up -d" -Action { docker compose up -d }

                Write-Host "-- waiting for service health"
                $services = @("postgres", "redis", "api", "admin")
                $healthy = $false
                foreach ($attempt in 1..60) {
                    $healthy = $true
                    foreach ($service in $services) {
                        $state = docker inspect --format "{{.State.Health.Status}}" "contentos-$service-1"
                        if ($state -ne "healthy") { $healthy = $false }
                    }
                    if ($healthy) { break }
                    Start-Sleep -Seconds 2
                }
                if (-not $healthy) {
                    throw "Compose services did not become healthy in time."
                }
                Write-Host "-- all health-checked services are healthy"

                Invoke-Step -Description "smoke checks (scripts/smoke.ps1)" -Action {
                    & (Join-Path $PSScriptRoot "smoke.ps1")
                }
            } finally {
                Write-Host "-- tearing down ContentOS Compose resources"
                docker compose down -v
            }
        } finally {
            Pop-Location
        }
    }

    Write-Host ""
    if ($Compose) {
        Write-Host "All quality checks passed (toolchain, backend, admin, repository, compose)."
    } else {
        Write-Host "All quality checks passed (toolchain, backend, admin, repository)."
    }
    exit 0
} catch {
    Write-Host ""
    Write-Host "FAILED in stage [$stage]: $($_.Exception.Message)"
    exit 1
}
