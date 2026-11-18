# Start the NLI result viewer on Windows: http://127.0.0.1:8000
#   .\start_viewer.ps1                       # uses viewer_config.json next to this script
#   .\start_viewer.ps1 -Config my.json -Port 8080 -Public   # -Public: reachable from other machines
#   .\start_viewer.ps1 -Wheels ..\pkgs\windows-py312   # first run without internet: install from a wheel folder
#   .\start_viewer.ps1 -Python C:\Python312\python.exe   # first run: create backend\.venv with this Python (default: py -3)
# First run: creates backend\.venv, installs the Python packages, builds the frontend if npm is available.
# -Python only matters while backend\.venv does not exist; to switch Python, delete backend\.venv first.
param([string]$Config = "$PSScriptRoot\viewer_config.json", [int]$Port = 8000, [switch]$Public, [switch]$Rebuild,
      [string]$Wheels = "", [string]$Python = "")
$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "backend"
$frontend = Join-Path $PSScriptRoot "frontend"
$venv = Join-Path $backend ".venv"
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating Python environment in $venv ..."
    if ($Python) {
        if (-not (Test-Path $Python)) { Write-Host "Python not found: $Python"; exit 1 }
        Write-Host "Using $Python"
        & $Python -m venv $venv
    } else {
        py -3 -m venv $venv
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) {
        Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue
        Write-Host "Creating the Python environment failed (see above)."
        exit 1
    }
    $source = @()
    if ($Wheels) {
        $Wheels = (Resolve-Path $Wheels).Path
        Write-Host "Installing offline from $Wheels ..."
        $source = @("--no-index", "--find-links", $Wheels)
    }
    & $py -m pip install --disable-pip-version-check -q @source -r (Join-Path $backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        # a half-installed environment would be taken as ready on the next start: remove it
        Remove-Item -Recurse -Force $venv -ErrorAction SilentlyContinue
        Write-Host "Installing the Python packages failed (see above); $venv was removed, fix the cause and start again."
        Write-Host "'No such file or directory' under cfnlint = Windows path limit: move the project to a shorter path"
        Write-Host "(e.g. D:\nli) or enable long paths (https://pip.pypa.io/warnings/enable-long-paths)."
        exit 1
    }
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
