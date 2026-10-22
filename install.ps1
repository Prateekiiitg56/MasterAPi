# MasterAPI installer for Windows:
#
#   irm https://raw.githubusercontent.com/Prateekiiitg56/MasterAPi/main/install.ps1 | iex
#
# Installs uv (if missing), MasterAPI as a uv tool, and Deno (the Code Mode sandbox),
# then runs `masterapi setup` to add keys and connect your coding agents.
# Skip parts with $env:MASTERAPI_NO_DENO = 1 or $env:MASTERAPI_NO_SETUP = 1.

$ErrorActionPreference = "Stop"
$Repo = "git+https://github.com/Prateekiiitg56/MasterAPi"

function Test-Command($Name) { [bool](Get-Command $Name -ErrorAction SilentlyContinue) }
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "Machine")
}

Write-Host "Installing MasterAPI" -ForegroundColor Yellow

if (-not (Test-Command uv)) {
    Write-Host "-> installing uv (Python tool manager)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Update-SessionPath
}

Write-Host "-> installing masterapi"
uv tool install --force --python 3.12 $Repo
uv tool update-shell | Out-Null
Update-SessionPath

if (-not $env:MASTERAPI_NO_DENO -and -not (Test-Command deno)) {
    Write-Host "-> installing Deno (sandbox for Code Mode)"
    Invoke-RestMethod https://deno.land/install.ps1 | Invoke-Expression
    Update-SessionPath
}

$MasterApi = (Get-Command masterapi -ErrorAction SilentlyContinue).Source
if (-not $MasterApi) { $MasterApi = Join-Path $HOME ".local\bin\masterapi.exe" }

if ($env:MASTERAPI_NO_SETUP) {
    Write-Host "Installed. Run 'masterapi setup' to add keys and connect your coding agents." -ForegroundColor Green
} else {
    & $MasterApi setup
}
