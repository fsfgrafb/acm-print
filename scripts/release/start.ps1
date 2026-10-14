param([ValidateRange(1, 65535)][int]$Port = 80, [switch]$AutoStart)
$ErrorActionPreference = 'Stop'
$bundleRoot = $PSScriptRoot
$program = Join-Path $bundleRoot 'print-platform.exe'
$runtime = Join-Path $bundleRoot 'var'
$manifestPath = Join-Path $runtime 'processes.json'
$connectionPath = Join-Path $runtime 'database.dpapi'
$startupSettingsPath = Join-Path $runtime 'startup.json'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
if (($AutoStart -or -not $env:PLATFORM_DATABASE_URL) -and (Test-Path -LiteralPath $connectionPath)) {
    $savedConnection = Get-Content -LiteralPath $connectionPath -Raw | ConvertTo-SecureString
    $env:PLATFORM_DATABASE_URL = [System.Net.NetworkCredential]::new('', $savedConnection).Password
}
if (-not $env:PLATFORM_DATABASE_URL) { throw '首次启动请先设置 PLATFORM_DATABASE_URL，成功后会加密保存。' }
if (-not $PSBoundParameters.ContainsKey('Port') -and (Test-Path -LiteralPath $startupSettingsPath)) {
    $Port = [int](Get-Content -LiteralPath $startupSettingsPath -Raw | ConvertFrom-Json).port
    if ($Port -lt 1 -or $Port -gt 65535) { throw '保存的端口无效。' }
}
if (-not (Test-Path -LiteralPath (Join-Path $bundleRoot 'config\platform.toml'))) {
    Copy-Item -LiteralPath (Join-Path $bundleRoot 'config\platform.example.toml') -Destination (Join-Path $bundleRoot 'config\platform.toml')
}
$env:PLATFORM_CONFIG_FILE = Join-Path $bundleRoot 'config\platform.toml'
if (Test-Path -LiteralPath $manifestPath) {
    $previous = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($entry in $previous.processes) {
        $running = Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($running -and $running.Path -eq $program) {
            if ($AutoStart) { return }
            throw '程序已运行，请先执行 stop.ps1。'
        }
    }
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Push-Location $bundleRoot
try {
    & $program check-config
    if ($LASTEXITCODE -ne 0) { throw '配置校验失败。' }
    $attempts = if ($AutoStart) { 12 } else { 1 }
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        & $program migrate
        if ($LASTEXITCODE -eq 0) { break }
        if ($attempt -eq $attempts) { throw '数据库迁移失败。' }
        Start-Sleep -Seconds 5
    }
    $entries = @()
    foreach ($role in @('serve', 'conversion', 'printing', 'maintenance')) {
        $roleArgs = @($role)
        if ($role -eq 'serve') { $roleArgs += @('--host', '0.0.0.0', '--port', $Port) }
        $process = Start-Process -FilePath $program -ArgumentList $roleArgs -WorkingDirectory $bundleRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$role.out.log") -RedirectStandardError (Join-Path $runtime "$role.error.log")
        $entries += @{ id = $process.Id; role = $role }
        @{ root = $bundleRoot; processes = $entries } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    }
    $env:PLATFORM_DATABASE_URL | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $connectionPath -Encoding ascii
    @{ port = $Port } | ConvertTo-Json | Set-Content -LiteralPath $startupSettingsPath -Encoding utf8
    $pathHash = [System.Security.Cryptography.SHA256]::Create()
    try { $startupId = ([BitConverter]::ToString($pathHash.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($bundleRoot.ToLowerInvariant())))).Replace('-', '').Substring(0, 16) }
    finally { $pathHash.Dispose() }
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) "acm-print-$startupId.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $bundleRoot 'start.ps1') + '" -AutoStart'
    $shortcut.WorkingDirectory = $bundleRoot
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    Write-Host "打印平台：http://localhost:$Port；已启用当前用户登录后自启，数据库连接已加密保存。"
} finally { Pop-Location }
