# Start the NLI result viewer on Windows: http://127.0.0.1:8000
#   .\start_viewer.ps1                       # uses viewer_config.json next to this script
#   .\start_viewer.ps1 -Config my.json -Port 8080 -Public   # -Public: reachable from other machines
# First run: creates backend\.venv, installs the Python packages, builds the frontend if npm is available.
param([string]$Config = "$PSScriptRoot\viewer_config.json", [int]$Port = 8000, [switch]$Public, [switch]$Rebuild)
$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "backend"
$frontend = Join-Path $PSScriptRoot "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating Python environment in $backend\.venv ..."
    py -3 -m venv (Join-Path $backend ".venv")
    & $py -m pip install --disable-pip-version-check -q -r (Join-Path $backend "requirements.txt")
}
if ($Rebuild -or -not (Test-Path (Join-Path $frontend "out\index.html"))) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "Building the frontend ..."
        Push-Location $frontend
        try {
            if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
            $env:NEXT_TELEMETRY_DISABLED = "1"
            npm run build
        } finally { Pop-Location }
    } else {
        Write-Warning "npm not found: the API runs, but the web pages need frontend\out (build it on a machine with Node.js and copy it)"
    }
}
$hostAddr = if ($Public) { "0.0.0.0" } else { "127.0.0.1" }
Push-Location $backend
try { & $py -m nli_viewer serve --config $Config --host $hostAddr --port $Port } finally { Pop-Location }
