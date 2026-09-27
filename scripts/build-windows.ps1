[CmdletBinding()]
param(
    [string]$PythonVersion = '3.14',
    [switch]$SkipFrontend
)
$env:PreferredToolArchitecture = "x64"
$ErrorActionPreference = 'Stop'

Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT')
{ throw 'This build supports Windows only.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $repoRoot 'build/windows'

function Invoke-Checked
{
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0)
    { throw "$Command failed with exit code $LASTEXITCODE"
    }
}

Push-Location $repoRoot
try
{
    Get-Command uv -ErrorAction Stop | Out-Null
    if (-not $SkipFrontend)
    {
        Get-Command pnpm -ErrorAction Stop | Out-Null
        Invoke-Checked pnpm @('--dir', 'frontend', 'install', '--frozen-lockfile')
        Invoke-Checked pnpm @('--dir', 'frontend', 'build')
    }
    if (-not (Test-Path 'frontend/dist/index.html'))
    {
        throw 'frontend/dist/index.html is missing. Build the frontend first.'
    }

    # Keep build dependencies and Python separate from the developer environment.
    $previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $buildRoot '.venv'
    try
    {
        Invoke-Checked uv @('sync', '--locked', '--no-dev', '--python', $PythonVersion)
        $arguments = @(
            'run', '--no-sync', '--python', $PythonVersion, '--with', 'Nuitka==4.2.2',
            'python', '-m', 'nuitka',
            '--mode=standalone', '--msvc=latest', '--assume-yes-for-downloads',
            '--output-dir=build/windows', '--output-filename=Ounce-bt.exe',
            '--windows-console-mode=attach',
            '--include-package=uvicorn', '--include-package=bumble',
            '--include-data-dir=frontend/dist=frontend/dist',
            '--include-data-files=presets/xbox.json=presets/xbox.json',
            '--include-data-files=presets/playstation.json=presets/playstation.json',
            '--include-data-files=presets/switch_pro.json=presets/switch_pro.json',
            '--report=build/windows/nuitka-report.xml',
            'main.py'
        )
        Invoke-Checked uv $arguments
    } finally
    {
        $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    }

    $distribution = Join-Path $buildRoot 'main.dist'
    foreach ($excluded in @('config', 'config.json', 'pro_controller.json', 'macros', 'rtl8761bu_fw.bin', 'rtl8761bu_config.bin'))
    {
        if (Test-Path (Join-Path $distribution $excluded))
        {
            throw "Unexpected private/runtime data in distribution: $excluded"
        }
    }
    if (-not (Test-Path (Join-Path $distribution 'Ounce-bt.exe')))
    {
        throw 'Nuitka did not produce Ounce-bt.exe.'
    }
    Write-Host "Windows application: $distribution"
} finally
{
    Pop-Location
}
