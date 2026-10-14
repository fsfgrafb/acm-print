param([switch]$NoFrontend)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot 'var'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$manifestPath = Join-Path $runtimeRoot 'dev-processes.json'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '先按 README 安装 Python 依赖。' }
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (Test-Path -LiteralPath $manifestPath) {
    $previous = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $previous.processes) {
        $process = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($process -and $process.Path -eq $entry.executable) { throw '开发进程仍在运行，请先执行 scripts/stop-dev.ps1。' }
    }
}
if (-not $env:PLATFORM_DATABASE_URL) {
    $pgCtl = Join-Path $runtimeRoot 'dev-postgres\pgsql\bin\pg_ctl.exe'
    $pgData = Join-Path $runtimeRoot 'dev-postgres\data'
    if (-not (Test-Path -LiteralPath $pgCtl)) { throw '请先设置 PLATFORM_DATABASE_URL，连接本机 PostgreSQL。' }
    $pgStatus = Start-Process -FilePath $pgCtl -ArgumentList @('-D', ('"' + $pgData + '"'), 'status') -WindowStyle Hidden -PassThru
    $pgStatus.WaitForExit()
    if ($pgStatus.ExitCode -ne 0) {
        $pgStart = Start-Process -FilePath $pgCtl -ArgumentList @('-D', ('"' + $pgData + '"'), '-l', ('"' + (Join-Path $runtimeRoot 'dev-postgres\server.log') + '"'), '-o', '"-h 127.0.0.1 -p 55432"', '-w', 'start') -WindowStyle Hidden -PassThru
        $pgStart.WaitForExit()
        if ($pgStart.ExitCode -ne 0) { throw '开发 PostgreSQL 启动失败，请检查 server.log。' }
    }
    $env:PLATFORM_DATABASE_URL = 'postgresql+psycopg://platform_dev@127.0.0.1:55432/platform_dev'
}
$configPath = Join-Path $projectRoot 'config\platform.toml'
if (-not (Test-Path -LiteralPath $configPath)) { Copy-Item -LiteralPath (Join-Path $projectRoot 'config\platform.example.toml') -Destination $configPath }
if (-not $env:PLATFORM_CONFIG_FILE) { $env:PLATFORM_CONFIG_FILE = $configPath }
Push-Location $projectRoot
try {
    & $pythonPath -m print_platform.cli check-config
    if ($LASTEXITCODE -ne 0) { throw '配置校验失败。' }
    & $pythonPath -m print_platform.cli migrate
    if ($LASTEXITCODE -ne 0) { throw '迁移失败。' }
    $entries = [System.Collections.Generic.List[object]]::new()
    $jobs = @(
        @{ role = 'api'; args = @('-m', 'uvicorn', 'print_platform.main:app', '--host', '127.0.0.1', '--port', '8000') },
        @{ role = 'conversion'; args = @('-m', 'print_platform.workers.conversion') },
        @{ role = 'printing'; args = @('-m', 'print_platform.workers.printing') },
        @{ role = 'maintenance'; args = @('-m', 'print_platform.workers.maintenance') }
    )
    foreach ($job in $jobs) {
        $process = Start-Process -FilePath $pythonPath -ArgumentList $job.args -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot ($job.role + '.out.log')) -RedirectStandardError (Join-Path $runtimeRoot ($job.role + '.error.log'))
        $entries.Add(@{ id = $process.Id; role = $job.role; executable = $pythonPath })
    }
    if (-not $NoFrontend) {
        $vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
        if (-not (Test-Path -LiteralPath $vitePath)) { throw '请先在 frontend 执行 npm ci。' }
        $nodePath = (Get-Command node.exe).Source
        $process = Start-Process -FilePath $nodePath -ArgumentList @(('"' + $vitePath + '"'), '--host', '127.0.0.1', '--port', '5173', '--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'frontend.out.log') -RedirectStandardError (Join-Path $runtimeRoot 'frontend.error.log')
        $entries.Add(@{ id = $process.Id; role = 'frontend'; executable = $nodePath })
    }
    @{ root = $projectRoot; processes = $entries.ToArray() } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    Write-Host '开发环境：http://localhost:5173；API：http://127.0.0.1:8000/api/docs'
    Write-Host '默认禁用物理打印。'
} finally { Pop-Location }
