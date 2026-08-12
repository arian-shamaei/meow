<#
  meow_deploy.ps1 -- runs ON the Windows machine (`meow`). Compiles the sketch,
  finds the board, uploads, and reads the port back as proof it is alive.

  deploy.sh on the Mac copies this over and invokes it; it is not meant to be
  run by hand, though it works standalone:

      powershell -ExecutionPolicy Bypass -File meow_deploy.ps1

  The port is DETECTED every time rather than hard-coded: a 32U4 board enters
  its bootloader via a 1200-baud touch and re-enumerates, so the COM number can
  differ between the compile step and the read-back step.
#>
param(
    [string]$SketchDir   = "$PSScriptRoot\meow_micro",
    [string]$Fqbn        = "arduino:avr:micro",
    [int]   $Baud        = 115200,
    [int]   $ReadSeconds = 6,
    [switch]$NoUpload,
    [switch]$NoRead
)

$ErrorActionPreference = "Stop"

function Find-BoardPort {
    param([string]$Fqbn)
    $json = arduino-cli board list --format json | ConvertFrom-Json
    foreach ($p in $json.detected_ports) {
        if ($p.matching_boards.fqbn -contains $Fqbn) { return $p.port.address }
    }
    # Bootloader mode reports a different PID and no matching board: fall back
    # to any Arduino-VID serial device so an upload can still find it.
    foreach ($p in $json.detected_ports) {
        if ($p.port.properties.vid -eq "0x2341") { return $p.port.address }
    }
    return $null
}

Write-Host "== compile ==" -ForegroundColor Cyan
$compile = arduino-cli compile --fqbn $Fqbn $SketchDir 2>&1
$compile | ForEach-Object { Write-Host "   $_" }
if ($LASTEXITCODE -ne 0) { throw "compile failed" }

# Surface the numbers that decide whether this fits the chip at all.
$ram = $compile | Select-String -Pattern "dynamic memory"
if ($ram) { Write-Host "SRAM: $($ram.Line.Trim())" -ForegroundColor Yellow }

if ($NoUpload) { Write-Host "(--NoUpload: stopping after compile)"; exit 0 }

$port = Find-BoardPort -Fqbn $Fqbn
if (-not $port) { throw "no Arduino board found on any serial port" }
Write-Host "== upload -> $port ==" -ForegroundColor Cyan
arduino-cli upload -p $port --fqbn $Fqbn $SketchDir 2>&1 |
    ForEach-Object { Write-Host "   $_" }
if ($LASTEXITCODE -ne 0) { throw "upload failed" }

if ($NoRead) { Write-Host "(--NoRead: skipping read-back)"; exit 0 }

# The board re-enumerates after upload; wait, then find it again.
Start-Sleep -Seconds 3
$port = Find-BoardPort -Fqbn $Fqbn
if (-not $port) { Write-Host "uploaded, but the board did not re-appear to read back"; exit 0 }

Write-Host "== read back $port @ $Baud ==" -ForegroundColor Cyan
$sp = New-Object System.IO.Ports.SerialPort($port, $Baud, "None", 8, "One")
$sp.ReadTimeout  = 2000
$sp.DtrEnable    = $true
try {
    $sp.Open()
    Start-Sleep -Seconds $ReadSeconds
    $data = $sp.ReadExisting()
} finally {
    if ($sp.IsOpen) { $sp.Close() }
}

if ([string]::IsNullOrWhiteSpace($data)) {
    Write-Host "NO SERIAL OUTPUT -- board flashed but is not talking" -ForegroundColor Red
    exit 1
}
Write-Host $data
$frames = ([regex]::Matches($data, "meow frame \d+")).Count
Write-Host "frames seen in $ReadSeconds s: $frames" -ForegroundColor Green
