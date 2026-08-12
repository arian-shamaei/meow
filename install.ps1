<#
  install.ps1 -- native Windows installer for meow.

  Downloads the prebuilt meow.exe from the latest GitHub release, installs it,
  and adds it to the user's PATH permanently. No compiler, no git, no admin
  rights required -- the PowerShell counterpart to install.sh.

      # from a release:
      iwr -useb https://github.com/<owner>/<repo>/releases/latest/download/install.ps1 | iex

      # or with an explicit source:
      .\install.ps1 -Repo owner/repo

  This is what the USB stick's typed command runs on a Windows target.
#>
[CmdletBinding()]
param(
    [string]$Repo   = "arian-shamaei/meow",
    [string]$Asset  = "meow-windows-x86_64.exe",
    [switch]$NoPath
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "install: $m" }

# --- destination: a per-user dir that needs no admin rights ---------------
$Dest   = Join-Path $env:LOCALAPPDATA "Programs\meow"
$ExePath = Join-Path $Dest "meow.exe"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# --- download the prebuilt binary from the latest release -----------------
$Url = "https://github.com/$Repo/releases/latest/download/$Asset"
Info "downloading $Url"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $ExePath
} catch {
    throw "download failed ($Url): $($_.Exception.Message)"
}
if ((Get-Item $ExePath).Length -lt 1000) { throw "downloaded file looks too small; aborting" }
Info "installed $ExePath"

# --- add to the USER PATH permanently (idempotent) ------------------------
if (-not $NoPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($null -eq $userPath) { $userPath = "" }
    $parts = $userPath -split ';' | Where-Object { $_ -ne "" }
    if ($parts -notcontains $Dest) {
        $newPath = (@($parts) + $Dest) -join ';'
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        # reflect it into the current session too, so `meow` works right away
        $env:Path = "$env:Path;$Dest"
        Info "added $Dest to your PATH (new terminals will find 'meow')"
    } else {
        Info "PATH already contains $Dest"
    }
}

Info "done. run:  meow        (Ctrl-C to quit)"
