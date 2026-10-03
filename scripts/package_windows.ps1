[CmdletBinding()]
param(
    [string]$PythonVersion = "3.13.16",
    [string]$PythonEmbedSha256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297",
    [string]$RuntimeZip = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "build\portable"))
$releaseRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "release"))
$bundleRoot = [System.IO.Path]::GetFullPath((Join-Path $buildRoot "ClawCV"))

foreach ($target in @($buildRoot, $releaseRoot, $bundleRoot)) {
    if (-not $target.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Packaging target escaped the repository root: $target"
    }
}

if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $bundleRoot | Out-Null
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null

$downloadedRuntime = $false
if (-not $RuntimeZip) {
    $RuntimeZip = Join-Path $buildRoot "python-embed-amd64.zip"
    $runtimeUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Invoke-WebRequest -Uri $runtimeUrl -OutFile $RuntimeZip -UseBasicParsing
    $downloadedRuntime = $true
}
$RuntimeZip = [System.IO.Path]::GetFullPath($RuntimeZip)
if (-not (Test-Path -LiteralPath $RuntimeZip -PathType Leaf)) {
    throw "Python embeddable ZIP was not found: $RuntimeZip"
}
$actualRuntimeHash = (Get-FileHash -LiteralPath $RuntimeZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualRuntimeHash -ne $PythonEmbedSha256.ToLowerInvariant()) {
    throw "Python runtime checksum mismatch. Expected $PythonEmbedSha256, got $actualRuntimeHash"
}

$pythonRoot = Join-Path $bundleRoot "python"
Expand-Archive -LiteralPath $RuntimeZip -DestinationPath $pythonRoot
$pth = Get-ChildItem -LiteralPath $pythonRoot -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "Embedded Python _pth file was not found" }
$pthLines = Get-Content -LiteralPath $pth.FullName
if ($pthLines -notcontains "..") {
    Add-Content -LiteralPath $pth.FullName -Value ".."
}

foreach ($directory in @("app", "web", "migrations", "prompts", "schemas")) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $directory) -Destination (Join-Path $bundleRoot $directory) -Recurse
}
foreach ($file in @("main.py", "start.bat", "README.txt")) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $file) -Destination (Join-Path $bundleRoot $file)
}
Get-ChildItem -LiteralPath $bundleRoot -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $bundleRoot -Recurse -File |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
    Remove-Item -Force

$buildInfo = [ordered]@{
    application = "ClawCV Phase 2 Supervised Interview"
    applicationVersion = "0.1.0"
    pythonVersion = $PythonVersion
    pythonEmbedSha256 = $actualRuntimeHash
    builtAtUtc = [DateTime]::UtcNow.ToString("o")
    runtimeDependencies = @("Python Standard Library", "SQLite bundled with CPython")
}
$buildInfo | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $bundleRoot "BUILD-INFO.json") -Encoding UTF8

$smokeCode = @"
import pathlib, sys, tempfile
root = pathlib.Path(r'$bundleRoot')
sys.path.insert(0, str(root))
from app.application import create_application
from app.config import AppConfig
with tempfile.TemporaryDirectory() as temporary:
    app = create_application(AppConfig(port=0, data_directory=pathlib.Path(temporary), web_directory=root / 'web'), initial_pin='246810')
    assert app.database.path.exists()
print('portable smoke: OK')
"@
& (Join-Path $pythonRoot "python.exe") -B -c $smokeCode
if ($LASTEXITCODE -ne 0) { throw "Portable runtime smoke test failed" }

$archive = Join-Path $releaseRoot "ClawCV-0.1.0-win64-portable.zip"
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
Compress-Archive -Path $bundleRoot -DestinationPath $archive -CompressionLevel Optimal
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$archive.sha256" -Value "$archiveHash  $([System.IO.Path]::GetFileName($archive))" -Encoding ASCII

Write-Host "Portable package: $archive"
Write-Host "SHA-256: $archiveHash"
if ($downloadedRuntime) { Write-Host "Python runtime downloaded from python.org and checksum verified." }
