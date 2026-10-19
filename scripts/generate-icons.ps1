# Requires ImageMagick 7 (magick on PATH). Run after updating frontend/public/logo.svg.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Get-Command magick -ErrorAction Stop | Out-Null

$publicDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend/public'
$logo = Join-Path $publicDir 'logo.svg'

function Invoke-Magick
{
    param([string[]]$Arguments)
    & magick @Arguments
    if ($LASTEXITCODE -ne 0)
    {
        throw "ImageMagick failed with exit code $LASTEXITCODE"
    }
}

Copy-Item -LiteralPath $logo -Destination (Join-Path $publicDir 'favicon.svg')
foreach ($size in @(192, 512))
{
    Invoke-Magick @('-background', 'none', '-density', '192', $logo,
        '-resize', "${size}x${size}", (Join-Path $publicDir "icon-$size.png"))
}
Invoke-Magick @('-background', 'white', '-density', '192', $logo,
    '-resize', '180x180', '-alpha', 'remove', '-alpha', 'off',
    (Join-Path $publicDir 'apple-touch-icon.png'))
Invoke-Magick @((Join-Path $publicDir 'icon-512.png'),
    '-define', 'icon:auto-resize=48,32,16', (Join-Path $publicDir 'favicon.ico'))
Invoke-Magick @((Join-Path $publicDir 'icon-512.png'),
    '-define', 'icon:auto-resize=256,128,64,48,32,16', (Join-Path $publicDir 'app.ico'))
