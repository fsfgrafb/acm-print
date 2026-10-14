param([ValidateRange(1, 65535)][int]$Port = 80)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$program = Join-Path $bundleRoot 'print-platform.exe'
$runtime = Join-Path $bundleRoot 'var'
$manifestPath = Join-Path $runtime 'processes.json'
if (-not $env:PLATFORM_DATABASE_URL) { throw '请先设置 PLATFORM_DATABASE_URL。' }
if (-not (Test-Path -LiteralPath (Join-Path $bundleRoot 'config\platform.toml'))) {
    Copy-Item -LiteralPath (Join-Path $bundleRoot 'config\platform.example.toml') -Destination (Join-Path $bundleRoot 'config\platform.toml')
}
$env:PLATFORM_CONFIG_FILE = Join-Path $bundleRoot 'config\platform.toml'
if (Test-Path -LiteralPath $manifestPath) {
    $previous = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $previous.processes) {
        $running = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($running -and $running.Path -eq $program) { throw '程序已运行，请先执行 stop.ps1。' }
    }
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Push-Location $bundleRoot
try {
    & $program check-config
    if ($LASTEXITCODE -ne 0) { throw '配置校验失败。' }
    & $program migrate
    if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败。' }
    $entries = @()
    foreach ($role in @('serve', 'conversion', 'printing', 'maintenance')) {
        $roleArgs = @($role)
        if ($role -eq 'serve') { $roleArgs += @('--host', '0.0.0.0', '--port', $Port) }
        $process = Start-Process -FilePath $program -ArgumentList $roleArgs -WorkingDirectory $bundleRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$role.out.log") -RedirectStandardError (Join-Path $runtime "$role.error.log")
        $entries += @{ id = $process.Id; role = $role }
        @{ root = $bundleRoot; processes = $entries } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    }
    Write-Host "打印平台：http://localhost:$Port"
} finally { Pop-Location }
