param(
    [Parameter(Mandatory)][string]$Package,
    [string]$InstallPath = $PSScriptRoot,
    [string]$PgBin,
    [ValidateRange(10, 300)][int]$HealthTimeoutSeconds = 60
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Copy-DirectoryContents([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Remove-ProgramFiles {
    # Resolve and verify every deletion stays directly inside the explicit installation.
    foreach ($entry in Get-ChildItem -LiteralPath $installRoot -Force) {
        if ($entry.Name -in @('config', 'var')) { continue }
        $resolved = [IO.Path]::GetFullPath($entry.FullName)
        if ([IO.Path]::GetDirectoryName($resolved) -ne $installRoot) { throw '程序文件路径越界。' }
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '程序目录含链接，停止更新。' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

function Invoke-ReleaseScript([string]$ScriptPath) {
    # Separate process: replacing update.ps1 cannot change this running updater.
    $shellPath = (Get-Process -Id $PID).Path
    & $shellPath -NoProfile -ExecutionPolicy Bypass -File $ScriptPath
    if ($LASTEXITCODE -ne 0) { throw "发布脚本执行失败：$ScriptPath" }
}

$installRoot = (Resolve-Path -LiteralPath $InstallPath).Path.TrimEnd('\')
$archive = (Resolve-Path -LiteralPath $Package).Path
if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or [IO.Path]::GetExtension($archive) -ne '.zip') { throw 'Package 必须是发布包 ZIP 文件。' }
foreach ($required in @('print-platform.exe', 'start.ps1', 'stop.ps1', 'config\platform.toml')) {
    if (-not (Test-Path -LiteralPath (Join-Path $installRoot $required) -PathType Leaf)) { throw "安装目录缺少 $required" }
}
$runtime = Join-Path $installRoot 'var'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$lock = $null
$savedDatabase = $env:PLATFORM_DATABASE_URL
$savedConfig = $env:PLATFORM_CONFIG_FILE
$stopped = $false
$replacementStarted = $false
$startupAttempted = $false
$programBackupComplete = $false
$backup = $null
try {
    $lock = [IO.File]::Open((Join-Path $runtime 'update.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    if (-not $env:PLATFORM_DATABASE_URL) {
        $connectionPath = Join-Path $runtime 'database.dpapi'
        $secret = Get-Content -LiteralPath $connectionPath -Raw | ConvertTo-SecureString
        $env:PLATFORM_DATABASE_URL = [Net.NetworkCredential]::new('', $secret).Password
    }
    $env:PLATFORM_CONFIG_FILE = Join-Path $installRoot 'config\platform.toml'
    if ($PgBin) { $dumpProgram = Join-Path $PgBin 'pg_dump.exe' } else {
        $dumpCommand = Get-Command pg_dump -ErrorAction SilentlyContinue
        if (-not $dumpCommand) { throw '找不到 pg_dump，请通过 -PgBin 指定 PostgreSQL 的 bin 目录。' }
        $dumpProgram = $dumpCommand.Source
        $PgBin = Split-Path -Parent $dumpProgram
    }
    if (-not (Test-Path -LiteralPath $dumpProgram -PathType Leaf)) { throw '找不到 pg_dump.exe。' }
    $checksumPath = $archive + '.sha256'
    if (-not (Test-Path -LiteralPath $checksumPath)) { throw '缺少发布包同目录的 .zip.sha256 校验文件。' }
    $checksum = ((Get-Content -LiteralPath $checksumPath -Raw).Trim() -split '\s+')[0]
    if ($checksum -notmatch '^[0-9a-fA-F]{64}$' -or (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $checksum) { throw '发布包 SHA-256 校验失败。' }
    $backup = Join-Path $runtime ('updates\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $stage = Join-Path $backup 'package'
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    # Inspect ZIP paths before extraction, including Windows path aliases.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        foreach ($entry in $zip.Entries) {
            $parts = $entry.FullName -split '[/\\]'
            if ($entry.FullName -match '[:\x00]' -or $parts -contains '..' -or $parts -match '[. ]$') { throw '发布包含非法路径。' }
            $target = [IO.Path]::GetFullPath((Join-Path $stage $entry.FullName))
            if (-not $target.StartsWith($stage + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '发布包路径越界。' }
        }
    } finally { $zip.Dispose() }
    Expand-Archive -LiteralPath $archive -DestinationPath $stage
    foreach ($required in @('print-platform.exe', '_internal', 'frontend\dist\index.html', 'backend\migrations\001_initial.sql', 'start.ps1', 'stop.ps1', 'VERSION')) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $required))) { throw "发布包缺少 $required" }
    }
    if (Test-Path -LiteralPath (Join-Path $stage 'var')) { throw '发布包不应携带运行数据。' }
    # Never remove or rewrite a migration already shipped with this installation.
    foreach ($migration in Get-ChildItem -LiteralPath (Join-Path $installRoot 'backend\migrations') -Filter '*.sql') {
        $nextMigration = Join-Path $stage ('backend\migrations\' + $migration.Name)
        if (-not (Test-Path -LiteralPath $nextMigration) -or (Get-FileHash -LiteralPath $migration.FullName).Hash -ne (Get-FileHash -LiteralPath $nextMigration).Hash) {
            throw "新包缺少或修改了已有迁移 $($migration.Name)，请勿降级或改写历史迁移。"
        }
    }
    $newProgram = Join-Path $stage 'print-platform.exe'
    & $newProgram check-runtime
    if ($LASTEXITCODE -ne 0) { throw '新版本运行依赖或配置检查失败。' }
    $info = & $newProgram update-check --install-root $installRoot
    if ($LASTEXITCODE -ne 0) { throw '更新检查失败，请等待在途打印任务结束。' }
    $storage = ($info | ConvertFrom-Json).storage_path
    if ($storage.StartsWith($installRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and -not $storage.StartsWith($runtime + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw '安装目录内的存储必须位于 var 子目录，其他存储请使用安装目录外的绝对路径。'
    }
    # A backup inside storage would recurse forever; ancestor storage layouts are unsupported.
    if ($backup.StartsWith($storage.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '存储目录包含更新备份目录，请调整存储位置。' }
    $links = Get-ChildItem -LiteralPath $installRoot -Force -Recurse -Attributes ReparsePoint
    if ($links) { throw '安装目录包含目录链接，请移除链接后更新。' }
    Write-Host '校验通过，正在停止平台并备份。'
    $stopped = $true
    Invoke-ReleaseScript (Join-Path $installRoot 'stop.ps1')
    # Wait for handles to close before copying executables or data.
    $processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $installRoot 'print-platform.exe') })
    foreach ($process in $processes) {
        if (-not $process.WaitForExit(15000)) { throw '平台进程尚未退出，停止更新。' }
    }
    $info = & $newProgram update-check --install-root $installRoot --dump-to (Join-Path $backup 'database.dump') --pg-bin $PgBin
    if ($LASTEXITCODE -ne 0) { throw '停止后的任务检查或数据库备份失败，尚未替换程序。' }
    $oldProgram = Join-Path $backup 'program'
    New-Item -ItemType Directory -Path $oldProgram -Force | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $installRoot -Force) {
        if ($entry.Name -eq 'var') { continue }
        Copy-Item -LiteralPath $entry.FullName -Destination $oldProgram -Recurse -Force
    }
    $programBackupComplete = $true
    # Copy runtime data without nesting the updates directory into its own backup.
    $varBackup = Join-Path $backup 'var'
    New-Item -ItemType Directory -Path $varBackup -Force | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $runtime -Force) {
        if ($entry.Name -in @('updates', 'update.lock')) { continue }
        Copy-Item -LiteralPath $entry.FullName -Destination $varBackup -Recurse -Force
    }
    $storageInsideVar = $storage.StartsWith($runtime + '\', [StringComparison]::OrdinalIgnoreCase)
    if (-not $storageInsideVar -and (Test-Path -LiteralPath $storage)) {
        if (Get-ChildItem -LiteralPath $storage -Recurse -Force -Attributes ReparsePoint) { throw '存储目录含链接，停止更新。' }
        Copy-DirectoryContents $storage (Join-Path $backup 'storage')
    }
    @{ install_path = $installRoot; storage_path = $storage; storage_in_var = $storageInsideVar; created_at = (Get-Date).ToString('o'); new_version = (Get-Content -LiteralPath (Join-Path $stage 'VERSION') -Raw).Trim() } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'backup.json') -Encoding UTF8
    '备份完整；程序替换尚未开始。' | Set-Content -LiteralPath (Join-Path $backup 'status.txt') -Encoding UTF8
    $replacementStarted = $true
    Remove-ProgramFiles
    foreach ($entry in Get-ChildItem -LiteralPath $stage -Force) {
        if ($entry.Name -eq 'config') { continue }
        Copy-Item -LiteralPath $entry.FullName -Destination $installRoot -Recurse -Force
    }
    # Keep all local configuration, including additional local config files.
    Copy-Item -LiteralPath (Join-Path $stage 'config\platform.example.toml') -Destination (Join-Path $installRoot 'config\platform.example.toml') -Force
    $startupAttempted = $true
    '已尝试迁移及启动；失败时请结合数据库备份人工恢复。' | Set-Content -LiteralPath (Join-Path $backup 'status.txt') -Encoding UTF8
    Invoke-ReleaseScript (Join-Path $installRoot 'start.ps1')
    $port = [int](Get-Content -LiteralPath (Join-Path $runtime 'startup.json') -Raw | ConvertFrom-Json).port
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    $healthy = $false
    $healthyChecks = 0
    do {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health/ready" -TimeoutSec 3
            $manifest = Get-Content -LiteralPath (Join-Path $runtime 'processes.json') -Raw | ConvertFrom-Json
            $running = @($manifest.processes | Where-Object {
                $process = Get-Process -Id $_.id -ErrorAction SilentlyContinue
                $process -and $process.Path -eq (Join-Path $installRoot 'print-platform.exe')
            })
            $healthy = $response.status -eq 'ready' -and $running.Count -eq 4
        } catch { $healthy = $false }
        if ($healthy) { $healthyChecks++ } else { $healthyChecks = 0 }
        if ($healthyChecks -lt 2) { Start-Sleep -Seconds 2 }
    } while ($healthyChecks -lt 2 -and (Get-Date) -lt $deadline)
    if ($healthyChecks -lt 2) { throw '更新后健康检查失败。' }
    '更新成功。' | Set-Content -LiteralPath (Join-Path $backup 'status.txt') -Encoding UTF8
    Write-Host "更新成功，备份保留在：$backup"
} catch {
    $failure = $_
    if ($stopped) {
        if ($startupAttempted) {
            try { Invoke-ReleaseScript (Join-Path $installRoot 'stop.ps1') } catch { Write-Warning '停止新版本失败，请检查进程。' }
            Write-Warning "已进入数据库迁移/启动阶段，平台保持停止。请根据备份恢复，勿直接启动旧版。备份：$backup"
        } else {
            try {
                if ($replacementStarted -and $programBackupComplete) {
                    Remove-ProgramFiles
                    foreach ($entry in Get-ChildItem -LiteralPath (Join-Path $backup 'program') -Force) {
                        if ($entry.Name -eq 'config') { continue }
                        Copy-Item -LiteralPath $entry.FullName -Destination $installRoot -Recurse -Force
                    }
                }
                Invoke-ReleaseScript (Join-Path $installRoot 'start.ps1')
                Write-Warning '更新未完成，已重新启动原版本。'
            } catch { Write-Warning "原版本恢复失败，请检查备份和日志：$backup" }
        }
    }
    throw $failure
} finally {
    $env:PLATFORM_DATABASE_URL = $savedDatabase
    $env:PLATFORM_CONFIG_FILE = $savedConfig
    if ($lock) { $lock.Dispose() }
}
