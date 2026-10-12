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

foreach ($directory in @("app", "web", "migrations", "prompts", "schemas", "tools")) {
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

$exeStage = Join-Path $buildRoot "exe-stage"
New-Item -ItemType Directory -Path $exeStage | Out-Null
$portableArchiveName = [System.IO.Path]::GetFileName($archive)
Copy-Item -LiteralPath $archive -Destination (Join-Path $exeStage $portableArchiveName)

$launcher = @'
@echo off
setlocal
set "CLAWCV_ARCHIVE=%~dp0__PORTABLE_ARCHIVE__"
set "CLAWCV_RUNTIME=%TEMP%\ClawCV-runtime-%RANDOM%%RANDOM%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:CLAWCV_ARCHIVE -DestinationPath $env:CLAWCV_RUNTIME -Force"
if errorlevel 1 (
    echo ClawCV could not extract its runtime package.
    pause
    exit /b 1
)
pushd "%CLAWCV_RUNTIME%\ClawCV"
if errorlevel 1 (
    echo ClawCV runtime directory was not created.
    pause
    exit /b 1
)
call start.bat
set "CLAWCV_EXIT=%ERRORLEVEL%"
popd
rmdir /s /q "%CLAWCV_RUNTIME%" >nul 2>&1
exit /b %CLAWCV_EXIT%
'@
$launcher = $launcher.Replace("__PORTABLE_ARCHIVE__", $portableArchiveName)
Set-Content -LiteralPath (Join-Path $exeStage "run-clawv.cmd") -Value $launcher -Encoding ASCII

$sedPath = Join-Path $buildRoot "ClawCV-package.sed"
$exeArchive = Join-Path $releaseRoot "ClawCV-0.1.0-win64.exe"
$stageShortPath = (& cmd.exe /d /c ('for %I in ("{0}") do @echo %~sI' -f $exeStage) | Select-Object -Last 1).Trim()
$releaseShortPath = (& cmd.exe /d /c ('for %I in ("{0}") do @echo %~sI' -f $releaseRoot) | Select-Object -Last 1).Trim()
if ([string]::IsNullOrWhiteSpace($stageShortPath)) {
    throw "Could not resolve a short path for the IExpress staging directory"
}
if ([string]::IsNullOrWhiteSpace($releaseShortPath)) {
    throw "Could not resolve a short path for the release directory"
}
$exeTargetShortPath = Join-Path $releaseShortPath "ClawCV-0.1.0-win64.exe"
$sedContent = @"
[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=1
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=$exeTargetShortPath
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles

[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
FriendlyName=ClawCV Phase 2 Supervised Interview
AppLaunched=cmd.exe /c run-clawv.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="$portableArchiveName"
FILE1="run-clawv.cmd"

[SourceFiles]
SourceFiles0=$stageShortPath\

[SourceFiles0]
%FILE0%=
%FILE1%=
"@
Set-Content -LiteralPath $sedPath -Value $sedContent -Encoding ASCII
$sedShortPath = (& cmd.exe /d /c ('for %I in ("{0}") do @echo %~sI' -f $sedPath) | Select-Object -Last 1).Trim()
if ([string]::IsNullOrWhiteSpace($sedShortPath)) {
    throw "Could not resolve a short path for the IExpress directive"
}
$iexpress = Join-Path $env:SystemRoot "System32\iexpress.exe"
if (-not (Test-Path -LiteralPath $iexpress -PathType Leaf)) {
    throw "IExpress was not found at $iexpress"
}
$staleExecutable = @($exeArchive, "$exeArchive.sha256")
foreach ($path in $staleExecutable) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}
Get-ChildItem -LiteralPath $releaseRoot -Filter "~ClawCV-0.1.0-win64*" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force
$iexpressProcess = Start-Process -FilePath $iexpress -ArgumentList @("/N", $sedShortPath) -Wait -PassThru
if ($iexpressProcess.ExitCode -ne 0) { throw "IExpress failed to build the executable" }

# IExpress can return after starting makecab.exe. Wait for the output to exist
# and become stable before hashing it or cleaning up the temporary CAB files.
$buildDeadline = [DateTime]::UtcNow.AddSeconds(180)
$lastExecutableLength = -1L
$stableChecks = 0
while ($stableChecks -lt 2) {
    if ([DateTime]::UtcNow -ge $buildDeadline) {
        throw "IExpress did not create a stable executable within 180 seconds: $exeArchive"
    }
    if (Test-Path -LiteralPath $exeArchive -PathType Leaf) {
        $currentExecutableLength = (Get-Item -LiteralPath $exeArchive).Length
        if ($currentExecutableLength -gt 0 -and $currentExecutableLength -eq $lastExecutableLength) {
            $stableChecks++
        }
        else {
            $stableChecks = 0
            $lastExecutableLength = $currentExecutableLength
        }
    }
    Start-Sleep -Milliseconds 500
}
$exeHash = (Get-FileHash -LiteralPath $exeArchive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$exeArchive.sha256" -Value "$exeHash  $([System.IO.Path]::GetFileName($exeArchive))" -Encoding ASCII
Remove-Item -LiteralPath $sedPath -Force
Get-ChildItem -LiteralPath $releaseRoot -Filter "~ClawCV-0.1.0-win64*" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Force

Write-Host "Portable package: $archive"
Write-Host "SHA-256: $archiveHash"
Write-Host "Self-extracting executable: $exeArchive"
Write-Host "SHA-256: $exeHash"
if ($downloadedRuntime) { Write-Host "Python runtime downloaded from python.org and checksum verified." }
