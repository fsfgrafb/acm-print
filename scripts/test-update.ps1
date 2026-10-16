# Exercises real archive/file operations in disposable directories; services and PostgreSQL are mocked.
$ErrorActionPreference = 'Stop'
$source = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release\update.ps1') -Raw -Encoding UTF8
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw $parseErrors[0] }
$invoke = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-ReleaseScript' }, $true)
$mockInvoke = @'
function Invoke-ReleaseScript([string]$ScriptPath) {
    if ([IO.Path]::GetFileName($ScriptPath) -eq 'stop.ps1') { $script:mockRunning = $false; return }
    if ($env:UPDATE_TEST_MODE -eq 'startup') { throw 'simulated startup failure' }
    $script:mockRunning = $true
    @{ port = 18080 } | ConvertTo-Json | Set-Content (Join-Path $runtime 'startup.json')
    @{ processes = @(1..4 | ForEach-Object { @{ id = 2000 + $_; role = "test$_" } }) } |
        ConvertTo-Json -Depth 4 | Set-Content (Join-Path $runtime 'processes.json')
}
'@
$source = $source.Remove($invoke.Extent.StartOffset, $invoke.Extent.EndOffset - $invoke.Extent.StartOffset).Insert($invoke.Extent.StartOffset, $mockInvoke)
$source = $source.Replace('& $newProgram', 'Invoke-MockProgram')
$mockTools = @'
function Invoke-MockProgram {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'check-runtime') { return }
    if ($env:UPDATE_TEST_MODE -eq 'busy') { $global:LASTEXITCODE = 1; return }
    $dumpIndex = [array]::IndexOf($args, '--dump-to')
    if ($dumpIndex -ge 0) {
        if ($env:UPDATE_TEST_MODE -eq 'backup') { $global:LASTEXITCODE = 1; return }
        Set-Content -LiteralPath $args[$dumpIndex + 1] -Value 'mock database'
    }
    @{ storage_path = (Join-Path $InstallPath 'var\storage') } | ConvertTo-Json -Compress
}
function Get-Process {
    param($Id, $ErrorAction)
    if ($Id -and $script:mockRunning) { [pscustomobject]@{ Path = (Join-Path $installRoot 'print-platform.exe') } }
}
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    if ($env:UPDATE_TEST_MODE -eq 'health') { throw 'simulated health failure' }
    @{ status = 'ready' }
}
function Copy-Item {
    param($LiteralPath, $Destination, [switch]$Recurse, [switch]$Force)
    if ($env:UPDATE_TEST_MODE -eq 'replacement' -and $LiteralPath -eq (Join-Path $stage 'VERSION')) {
        throw 'simulated replacement failure'
    }
    Microsoft.PowerShell.Management\Copy-Item @PSBoundParameters
}
'@
# Insert mocks after the parameter block, so the public invocation stays identical.
$source = $source.Insert($ast.ParamBlock.Extent.EndOffset, "`n$mockTools`n")
$workspace = Join-Path ([IO.Path]::GetTempPath()) ('print-update-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $workspace | Out-Null
$savedDatabase = $env:PLATFORM_DATABASE_URL
$savedMode = $env:UPDATE_TEST_MODE
try {
    $env:PLATFORM_DATABASE_URL = 'postgresql+psycopg://test:test@localhost/test'
    foreach ($mode in @('success', 'migration', 'busy', 'backup', 'replacement', 'startup', 'health')) {
        $case = Join-Path $workspace $mode
        $install = Join-Path $case 'installed'
        $package = Join-Path $case 'new'
        foreach ($root in @($install, $package)) {
            foreach ($dir in @('_internal', 'frontend\dist', 'backend\migrations', 'config')) {
                New-Item -ItemType Directory -Path (Join-Path $root $dir) -Force | Out-Null
            }
            foreach ($file in @('print-platform.exe', '_internal\fixture.dll', 'start.ps1', 'stop.ps1', 'frontend\dist\index.html', 'config\platform.example.toml', 'backend\migrations\001_initial.sql')) {
                Set-Content -LiteralPath (Join-Path $root $file) -Value 'fixture'
            }
        }
        Set-Content -LiteralPath (Join-Path $install 'VERSION') -Value 'v1.0.0'
        Set-Content -LiteralPath (Join-Path $package 'VERSION') -Value 'v1.1.0'
        if ($mode -eq 'migration') { Set-Content -LiteralPath (Join-Path $package 'backend\migrations\001_initial.sql') -Value 'rewritten migration' }
        Set-Content -LiteralPath (Join-Path $install 'obsolete.txt') -Value 'old'
        Set-Content -LiteralPath (Join-Path $install 'config\platform.toml') -Value 'local-config'
        New-Item -ItemType Directory -Path (Join-Path $install 'var\storage') -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $install 'var\storage\document.pdf') -Value 'user-data'
        $zipPath = Join-Path $case 'release.zip'
        Compress-Archive -Path (Join-Path $package '*') -DestinationPath $zipPath
        $pgBin = Join-Path $case 'pg'
        New-Item -ItemType Directory -Path $pgBin | Out-Null
        Set-Content -LiteralPath (Join-Path $pgBin 'pg_dump.exe') -Value 'fixture'
        $env:UPDATE_TEST_MODE = $mode
        $script:mockRunning = $false
        $failed = $false
        try { & ([scriptblock]::Create($source)) -Package $zipPath -InstallPath $install -PgBin $pgBin -HealthTimeoutSeconds 10 } catch { $failed = $true; Write-Host "[$mode] $($_.Exception.Message)" }
        if ($failed -ne ($mode -ne 'success')) { throw "Unexpected result: $mode" }
        if ((Get-Content -LiteralPath (Join-Path $install 'config\platform.toml')).Trim() -ne 'local-config') { throw 'Configuration lost' }
        if ((Get-Content -LiteralPath (Join-Path $install 'var\storage\document.pdf')).Trim() -ne 'user-data') { throw 'Storage lost' }
        $expectedVersion = if ($mode -in @('success', 'startup', 'health')) { 'v1.1.0' } else { 'v1.0.0' }
        if ((Get-Content -LiteralPath (Join-Path $install 'VERSION')).Trim() -ne $expectedVersion) { throw "Wrong installed version: $mode" }
        if ($mode -in @('success', 'startup', 'health')) {
            if (Test-Path -LiteralPath (Join-Path $install 'obsolete.txt')) { throw 'Obsolete program file retained' }
            if (-not (Get-ChildItem -LiteralPath (Join-Path $install 'var\updates') -Recurse -Filter database.dump)) { throw 'Backup missing' }
        }
        if ($mode -in @('startup', 'health') -and $script:mockRunning) { throw 'Failed service left running' }
        Write-Host "PASS: $mode"
    }
} finally {
    $env:PLATFORM_DATABASE_URL = $savedDatabase
    $env:UPDATE_TEST_MODE = $savedMode
    $resolved = [IO.Path]::GetFullPath($workspace)
    if ((Split-Path -Parent $resolved) -ne [IO.Path]::GetTempPath().TrimEnd('\') -or (Split-Path -Leaf $resolved) -notlike 'print-update-test-*') { throw 'Unsafe test cleanup path' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
