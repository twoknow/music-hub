$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetDir = Join-Path $env:APPDATA "npm"

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

$cmdPath = Join-Path $targetDir "m.cmd"
$ps1Path = Join-Path $targetDir "m.ps1"

$cmdContent = @"
@echo off
setlocal
set ROOT=$repoRoot
set PYTHONPATH=%ROOT%;%PYTHONPATH%
pushd "%ROOT%"
python -m musichub.cli %*
set ERR=%ERRORLEVEL%
popd
exit /b %ERR%
"@

$ps1Content = @"
`$ErrorActionPreference = 'Stop'
`$root = '$repoRoot'
`$env:PYTHONPATH = if (`$env:PYTHONPATH) { "`$root;`$env:PYTHONPATH" } else { `$root }
Push-Location `$root
try {
    python -m musichub.cli @Args
} finally {
    Pop-Location
}
"@

Set-Content -Path $cmdPath -Value $cmdContent -Encoding ASCII
Set-Content -Path $ps1Path -Value $ps1Content -Encoding ASCII

Write-Host "Installed:"
Write-Host "  $cmdPath"
Write-Host "  $ps1Path"
Write-Host ""
Write-Host "Try:"
Write-Host "  m doctor"
Write-Host "  m `"播放 周杰伦 稻香`""
