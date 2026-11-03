param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$valueName = 'InputShareFixed'
if ($Disable) {
    Remove-ItemProperty -LiteralPath $runKey -Name $valueName -ErrorAction SilentlyContinue
    Write-Output 'InputShare automatic startup disabled.'
    exit 0
}
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$main = Join-Path $root 'main.py'
if (-not (Test-Path -LiteralPath $pythonw) -or -not (Test-Path -LiteralPath $main)) {
    throw 'InputShare .venv and main.py are required.'
}
$command = '"' + $pythonw + '" "' + $main + '"'
if (-not (Test-Path -LiteralPath $runKey)) { New-Item -Path $runKey -Force | Out-Null }
New-ItemProperty -LiteralPath $runKey -Name $valueName -Value $command -PropertyType String -Force | Out-Null
Write-Output ('LOGIN_STARTUP_ENABLED: ' + $command)
