<#
.SYNOPSIS
    One-click setup for music-hub on Windows.
    Downloads mpv portable + yt-dlp, installs Python deps, registers global 'm' command.
.EXAMPLE
    .\install.ps1
#>
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsDir  = Join-Path $env:USERPROFILE "tools\mpv-portable"
$MpvExe    = Join-Path $ToolsDir "mpv.exe"
$YtdlpExe  = Join-Path $ToolsDir "yt-dlp.exe"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }

# --- 1. Check Python ---------------------------------------------------------
Write-Step "Checking Python 3.11+"
$pyver = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    Write-Host "Install from https://www.python.org/downloads/ then re-run this script."
    exit 1
}
$ver = [version]($pyver -replace 'Python ', '')
if ($ver -lt [version]"3.11") {
    Write-Host "ERROR: Python 3.11+ required (found $ver)" -ForegroundColor Red
    exit 1
}
Write-OK $pyver

# --- 2. Download mpv portable ------------------------------------------------
Write-Step "Setting up mpv portable -> $ToolsDir"
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

if (Test-Path $MpvExe) {
    Write-OK "mpv.exe already present, skipping download"
} else {
    Write-Host "    Fetching latest mpv release info from GitHub..."
    $apiUrl  = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
    $headers = @{ "User-Agent" = "music-hub-installer" }
    try {
        $release = Invoke-RestMethod -Uri $apiUrl -Headers $headers
        $asset   = $release.assets | Where-Object { $_.name -match "mpv-x86_64-.*\.7z$" } | Select-Object -First 1
        if (-not $asset) { throw "No x86_64 .7z asset found in release" }
        $zipPath = Join-Path $env:TEMP "mpv-portable.7z"
        Write-Host "    Downloading $($asset.name) ..."
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -Headers $headers
        Write-Host "    Extracting..."
        $7z = "7z"
        if (-not (Get-Command $7z -ErrorAction SilentlyContinue)) {
            Write-Warn "7z not found. Install 7-Zip and re-run, OR manually extract $zipPath to $ToolsDir"
            Write-Warn "Skipping mpv extraction. Install 7-Zip from https://www.7-zip.org/"
        } else {
            & $7z x $zipPath -o"$ToolsDir" -y | Out-Null
            Remove-Item $zipPath -Force
            Write-OK "mpv extracted to $ToolsDir"
        }
    } catch {
        Write-Warn "Could not auto-download mpv: $_"
        Write-Warn "Manual option: download portable build from https://mpv.io/installation/"
        Write-Warn "Extract mpv.exe to: $ToolsDir"
    }
}

# --- 3. Download yt-dlp.exe --------------------------------------------------
Write-Step "Setting up yt-dlp.exe -> $ToolsDir"
if (Test-Path $YtdlpExe) {
    Write-OK "yt-dlp.exe already present, skipping download"
} else {
    $ytUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
    Write-Host "    Downloading yt-dlp.exe ..."
    try {
        Invoke-WebRequest -Uri $ytUrl -OutFile $YtdlpExe
        Write-OK "yt-dlp.exe saved to $ToolsDir"
    } catch {
        Write-Warn "Could not download yt-dlp.exe: $_"
        Write-Warn "Manual option: https://github.com/yt-dlp/yt-dlp/releases/latest"
    }
}

# --- 4. Install Python dependencies ------------------------------------------
Write-Step "Installing Python dependencies (pip install -e .)"
Push-Location $RepoRoot
try {
    python -m pip install -e . --quiet
    Write-OK "Python deps installed"
} finally {
    Pop-Location
}

# --- 5. Register global 'm' command ------------------------------------------
Write-Step "Registering global 'm' command"
Push-Location $RepoRoot
try {
    & ".\install-m-cli.ps1"
    Write-OK "'m' command registered"
} finally {
    Pop-Location
}

# --- 6. Verify ---------------------------------------------------------------
Write-Step "Running 'm doctor' to verify setup"
Push-Location $RepoRoot
try {
    & ".\m.ps1" doctor
} finally {
    Pop-Location
}

Write-Host "`n==> Setup complete! Try:" -ForegroundColor Green
Write-Host "    m `"play meditation music`""
Write-Host "    m `"播放 周杰伦 稻香`""
