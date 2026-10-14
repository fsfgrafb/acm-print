$ErrorActionPreference = 'Stop'
$program = Join-Path $PSScriptRoot 'print-platform.exe'
$manifestPath = Join-Path $PSScriptRoot 'var\processes.json'
$pathHash = [System.Security.Cryptography.SHA256]::Create()
try { $startupId = ([BitConverter]::ToString($pathHash.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($PSScriptRoot.ToLowerInvariant())))).Replace('-', '').Substring(0, 16) }
finally { $pathHash.Dispose() }
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) "acm-print-$startupId.lnk"
if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.root -ne $PSScriptRoot) { throw '进程记录不属于本发布目录。' }
    foreach ($entry in $manifest.processes) {
        $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($process -and $process.Path -eq $program) { Stop-Process -Id $entry.id }
    }
    Remove-Item -LiteralPath $manifestPath
}
Write-Host '打印平台已停止，自启已关闭。数据库连接保留供下次启动使用。'
