# ContentOS local development bootstrap (idempotent, non-destructive).
# Verifies tooling, prepares .env, installs backend dependencies, builds the image.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "== ContentOS bootstrap =="

foreach ($tool in @("docker", "uv", "node", "corepack")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required tool '$tool' was not found on PATH."
    }
}
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker compose v2 is required." }

$envFile = Join-Path $repoRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repoRoot ".env.example") $envFile
    Write-Host "Created .env from .env.example (safe development defaults)."
} else {
    Write-Host ".env already exists - left untouched."
}

Push-Location (Join-Path $repoRoot "apps\backend")
try {
    uv sync --all-groups
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
} finally {
    Pop-Location
}

Push-Location $repoRoot
try {
    corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "pnpm install failed." }
} finally {
    Pop-Location
}

Push-Location $repoRoot
try {
    docker compose build
    if ($LASTEXITCODE -ne 0) { throw "docker compose build failed." }
} finally {
    Pop-Location
}

Write-Host "Bootstrap complete. Start the stack with: docker compose up -d"
