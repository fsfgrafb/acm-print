$ErrorActionPreference = 'Stop'
$program = Join-Path $PSScriptRoot 'print-platform.exe'
$manifestPath = Join-Path $PSScriptRoot 'var\processes.json'
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.root -ne $PSScriptRoot) { throw '进程记录不属于本发布目录。' }
    foreach ($entry in $manifest.processes) {
        $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($process -and $process.Path -eq $program) { Stop-Process -Id $entry.id }
    }
    Remove-Item -LiteralPath $manifestPath
}
Write-Host '打印平台已停止。'
