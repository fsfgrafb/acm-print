param([switch]$StopDatabase)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $projectRoot 'var\dev-processes.json'
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.root -ne $projectRoot) { throw '开发进程记录不属于本工作目录。' }
    foreach ($entry in $manifest.processes) {
        $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($process -and $process.Path -eq $entry.executable) {
            $command = (Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.id)").CommandLine
            if ($command.Contains($projectRoot)) { Stop-Process -Id $entry.id }
        }
    }
    Remove-Item -LiteralPath $manifestPath
}
if ($StopDatabase) {
    $pgCtl = Join-Path $projectRoot 'var\dev-postgres\pgsql\bin\pg_ctl.exe'
    $pgData = Join-Path $projectRoot 'var\dev-postgres\data'
    if (Test-Path -LiteralPath $pgCtl) {
        Start-Process -FilePath $pgCtl -ArgumentList @('-D', ('"' + $pgData + '"'), '-m', 'fast', '-w', 'stop') -WindowStyle Hidden -Wait | Out-Null
    }
}
Write-Host '本项目开发进程已停止。'
