param(
    [Parameter(Mandatory)][string]$Version,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$') { throw '版本标签格式为 v1.2.3 或 v1.2.3-rc.1。' }
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw '此构建脚本仅支持 Windows x64。' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot ('var\release-build\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$frontend = Join-Path $projectRoot 'frontend\dist'
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'index.html'))) { throw '请先构建前端。' }
$bundleArgs = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'print-platform',
    '--distpath', (Join-Path $buildRoot 'dist'), '--workpath', (Join-Path $buildRoot 'work'),
    '--specpath', $buildRoot, '--paths', (Join-Path $projectRoot 'backend'),
    '--collect-submodules', 'print_platform', '--collect-submodules', 'uvicorn',
    '--collect-all', 'pypdfium2', '--collect-all', 'psycopg', '--collect-all', 'psycopg_binary',
    '--collect-data', 'tzdata', '--hidden-import', 'win32print',
    '--hidden-import', 'sqlalchemy.dialects.postgresql.psycopg',
    (Join-Path $projectRoot 'scripts\release-entry.py')
)
& $Python @bundleArgs *> (Join-Path $buildRoot 'build.log')
if ($LASTEXITCODE -ne 0) { throw "可执行文件构建失败：$buildRoot\build.log" }
$stage = Join-Path $buildRoot 'dist\print-platform'
foreach ($directory in @('frontend', 'frontend\public', 'backend', 'config')) {
    New-Item -ItemType Directory -Path (Join-Path $stage $directory) -Force | Out-Null
}
Copy-Item -LiteralPath $frontend -Destination (Join-Path $stage 'frontend\dist') -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot 'frontend\public\brand') -Destination (Join-Path $stage 'frontend\public\brand') -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot 'backend\migrations') -Destination (Join-Path $stage 'backend\migrations') -Recurse
$example = Get-Content -LiteralPath (Join-Path $projectRoot 'config\platform.example.toml') -Raw
$example.Replace('http://localhost:5173', 'http://localhost') | Set-Content -LiteralPath (Join-Path $stage 'config\platform.example.toml') -Encoding utf8NoBOM
Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $stage
Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\release.md') -Destination (Join-Path $stage 'README.md')
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\release\start.ps1') -Destination $stage
Copy-Item -LiteralPath (Join-Path $projectRoot 'scripts\release\stop.ps1') -Destination $stage
$Version | Set-Content -LiteralPath (Join-Path $stage 'VERSION') -Encoding ascii
# Verify the actual frozen program and its runtime data before publishing.
$previousConfig = $env:PLATFORM_CONFIG_FILE
try {
    $env:PLATFORM_CONFIG_FILE = Join-Path $stage 'config\platform.example.toml'
    & (Join-Path $stage 'print-platform.exe') check-runtime
    if ($LASTEXITCODE -ne 0) { throw '打包后的运行依赖检查失败。' }
} finally { $env:PLATFORM_CONFIG_FILE = $previousConfig }
$output = Join-Path $projectRoot 'var\releases'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$name = "print-platform-$Version-windows-x64.zip"
$archive = Join-Path $output $name
if (Test-Path -LiteralPath $archive) { throw "产物已存在，请勿覆盖：$archive" }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $archive)
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $name" | Set-Content -LiteralPath ($archive + '.sha256') -Encoding ascii
Write-Host "Release package: $archive"
