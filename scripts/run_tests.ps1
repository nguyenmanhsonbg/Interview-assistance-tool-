[CmdletBinding()]
param(
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

if (-not $PythonExe) {
    $embedded = Join-Path $repoRoot "python\python.exe"
    if (Test-Path -LiteralPath $embedded) {
        $PythonExe = $embedded
    } else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if (-not $command) {
            throw "Python 3.10+ was not found. Pass -PythonExe with an explicit path."
        }
        $PythonExe = $command.Source
    }
}

$testCode = @"
import sys, unittest
sys.path.insert(0, r'$repoRoot')
suite = unittest.defaultTestLoader.discover(r'$(Join-Path $repoRoot "tests")')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
"@

& $PythonExe -c $testCode
exit $LASTEXITCODE
