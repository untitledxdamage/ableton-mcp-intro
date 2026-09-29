# Copies the AbletonMCP_Intro Remote Script into Live's User Library.
# Usage:  powershell -ExecutionPolicy Bypass -File install_remote_script.ps1 [-Reload]
#   -Reload  hot-reloads the script in a running Live (needs an AbletonMCP_Intro
#            version that already has the `reload` command loaded).
param([switch]$Reload)
$src = Join-Path $PSScriptRoot "remote_script\AbletonMCP_Intro\__init__.py"
$dst = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Ableton\User Library\Remote Scripts\AbletonMCP_Intro"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item $src $dst -Force
Write-Output "Installed to $dst"
if ($Reload) {
    Push-Location $PSScriptRoot
    uv run python -c "from ableton_mcp import live; print(live.send('reload'))"
    Pop-Location
}
