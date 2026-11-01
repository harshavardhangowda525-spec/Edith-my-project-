<#
.SYNOPSIS
  One-time local setup for EDITH AI on Windows.

.DESCRIPTION
  - Checks for Python 3.11+ and Node.js 18+
  - Creates backend/.venv and installs Python dependencies
  - Creates backend/.env from .env.example (mock mode, random dev token) if missing
  - Installs frontend npm packages and creates frontend/.env if missing
  - Runs the backend test-suite
  Never overwrites an existing .env file.

.EXAMPLE
  cd edith-ai
  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -SkipTests
  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Start
#>
[CmdletBinding()]
param(
  [switch]$SkipTests,
  [switch]$Start
)

$ErrorActionPreference = 'Stop'
$Root     = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPy   = Join-Path $Backend '.venv\Scripts\python.exe'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

# ---------- prerequisites ----------
Step 'Checking prerequisites'
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw 'Python 3.11+ not found. Install from https://www.python.org/downloads/ (tick "Add to PATH").' }
$pyVersion = & $py.Source -c "import sys;print('%d.%d' % sys.version_info[:2])"
if ([version]$pyVersion -lt [version]'3.11') { throw "Python $pyVersion found; 3.11+ is required." }
Ok "Python $pyVersion"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw 'Node.js 18+ not found. Install the LTS from https://nodejs.org/' }
$nodeVersion = (& node --version).TrimStart('v')
if ([version]$nodeVersion -lt [version]'18.0') { throw "Node $nodeVersion found; 18+ is required." }
Ok "Node $nodeVersion"

# ---------- backend ----------
Step 'Setting up backend virtual environment'
Push-Location $Backend
try {
  if (-not (Test-Path $VenvPy)) {
    & $py.Source -m venv .venv
    Ok 'Created backend\.venv'
  } else { Ok 'backend\.venv already exists' }

  & $VenvPy -m pip install --upgrade pip --quiet
  & $VenvPy -m pip install -r requirements.txt --quiet
  if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
  Ok 'Python dependencies installed'

  if (-not (Test-Path '.env')) {
    $token = & $VenvPy -c "import secrets;print(secrets.token_urlsafe(32))"
    $userId = [guid]::NewGuid().ToString()
    (Get-Content '.env.example') `
      -replace '^LOCAL_ACCESS_TOKENS=.*', "LOCAL_ACCESS_TOKENS=${token}:${userId}" `
      -replace '^AI_API_KEY=.*', 'AI_API_KEY=' `
      -replace '^SUPABASE_URL=.*', 'SUPABASE_URL=' `
      -replace '^SUPABASE_JWT_SECRET=.*', 'SUPABASE_JWT_SECRET=' `
      -replace '^SUPABASE_SERVICE_ROLE_KEY=.*', 'SUPABASE_SERVICE_ROLE_KEY=' |
      Set-Content '.env' -Encoding UTF8
    Ok 'Created backend\.env (mock AI mode)'
    Write-Host ''
    Write-Host '    Your local access token (paste into EDITH Settings -> General):' -ForegroundColor Yellow
    Write-Host "    $token" -ForegroundColor White
  } else {
    Warn 'backend\.env already exists - left unchanged'
  }

  if (-not $SkipTests) {
    Step 'Running backend tests'
    & $VenvPy -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
    Ok 'All backend tests passed'
  }
} finally { Pop-Location }

# ---------- frontend ----------
Step 'Installing frontend packages'
Push-Location $Frontend
try {
  npm install
  if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
  if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Ok 'Created frontend\.env'
  }
} finally { Pop-Location }

Step 'Done'
Write-Host @"
    Start the backend:
      cd $Backend
      .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

    Start the frontend (new terminal):
      cd $Frontend
      npm run dev

    Then open http://localhost:5173 in Chrome or Edge.
    To use real AI, edit backend\.env: AI_PROVIDER, AI_API_KEY, AI_MODEL.
"@

if ($Start) {
  Step 'Launching backend and frontend in new windows'
  Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$Backend'; & '$VenvPy' -m uvicorn app.main:app --reload"
  Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$Frontend'; npm run dev"
  Start-Sleep -Seconds 4
  Start-Process 'http://localhost:5173'
}
