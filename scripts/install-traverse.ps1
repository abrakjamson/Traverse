[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$InstallDirectory = "",
    [switch]$SkipPathUpdate
)

$ErrorActionPreference = "Stop"
$Repository = "abrakjamson/Traverse"
$Asset = "traverse-windows-x64.exe"

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
)) {
    throw "This installer supports Windows only."
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "The current Traverse release supports only Windows x64."
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI is required to download this private repository's release assets."
}
if (-not $InstallDirectory) {
    $InstallDirectory = Join-Path $env:LOCALAPPDATA "Programs\Traverse"
}

$TemporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
    "traverse-install-{0}-{1}" -f $PID, [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $TemporaryDirectory | Out-Null

try {
    $Arguments = @(
        "release", "download",
        "--repo", $Repository,
        "--pattern", $Asset,
        "--pattern", "SHA256SUMS",
        "--dir", $TemporaryDirectory,
        "--clobber"
    )
    if ($Version) {
        $Arguments = @("release", "download", $Version) + $Arguments[2..($Arguments.Length - 1)]
    }

    & gh @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI could not download the Traverse release."
    }

    $ChecksumLine = Get-Content (Join-Path $TemporaryDirectory "SHA256SUMS") |
        Where-Object { $_ -match "\s+$([regex]::Escape($Asset))$" } |
        Select-Object -First 1
    if (-not $ChecksumLine) {
        throw "The release checksum for $Asset is missing."
    }

    $Expected = ($ChecksumLine -split "\s+")[0].ToLowerInvariant()
    $Download = Join-Path $TemporaryDirectory $Asset
    $Actual = (Get-FileHash -LiteralPath $Download -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected) {
        throw "Checksum verification failed for $Asset."
    }

    New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
    Copy-Item -LiteralPath $Download -Destination (
        Join-Path $InstallDirectory "traverse.exe"
    ) -Force
    Copy-Item -LiteralPath $Download -Destination (
        Join-Path $InstallDirectory "purepath.exe"
    ) -Force

    if (-not $SkipPathUpdate) {
        $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
        $PathEntries = @($UserPath -split ";" | Where-Object { $_ })
        if ($InstallDirectory -notin $PathEntries) {
            $UpdatedPath = (@($PathEntries) + $InstallDirectory) -join ";"
            [Environment]::SetEnvironmentVariable("Path", $UpdatedPath, "User")
        }
        if ($InstallDirectory -notin ($env:Path -split ";")) {
            $env:Path = "$InstallDirectory;$env:Path"
        }
    }

    Write-Output "Installed Traverse to $InstallDirectory\traverse.exe"
    Write-Output "Installed compatibility alias at $InstallDirectory\purepath.exe"
    Write-Output "Open a new terminal before installing or running the Copilot plugin."
}
finally {
    Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
