# Setup script to prepare environment, build images, run migrations and seed initial project
param(
    [string]$ProjectKey = "OLP",
    [int]$BoardId = 2
)

# Create secrets dir and ask for token if missing
if (-not (Test-Path -Path ./secrets)) { New-Item -ItemType Directory -Path ./secrets > $null }
if (-not (Test-Path -Path ./secrets/atlassian_token.txt)) {
    Write-Host "Please paste your Atlassian token (will be saved to ./secrets/atlassian_token.txt):"
    $token = Read-Host -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($token))
    Set-Content -Path ./secrets/atlassian_token.txt -Value $plain -Encoding UTF8
}

# Build and start containers
docker compose up --build -d

# Initialize database tables
docker compose run --rm web python -c "from api.db import init_db; init_db()"

# Seed initial project (fetch data)
docker compose run --rm web python -m api.seed --project-key $ProjectKey --board-id $BoardId

Write-Host "Setup complete. Open http://localhost:8000/dashboard/"
