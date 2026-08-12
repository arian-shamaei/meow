<#
  hid_measure.ps1 -- runs ON `meow`. Measures HID typing throughput by asking
  the board (serial command 'm') to type one frame and report the elapsed time.

  No GUI: a script launched over SSH is not on the physical desktop, so it
  cannot place a window to catch the keystrokes. It does not need to -- the
  timing is intrinsic to the USB HID transfer and comes back over serial
  regardless of where the characters land. (The 288 characters do get typed
  into whatever window has focus on meow's console; harmless on an idle box.)

      powershell -ExecutionPolicy Bypass -File hid_measure.ps1
#>
param([int]$Baud = 115200)
$ErrorActionPreference = "Stop"

$j = arduino-cli board list --format json | ConvertFrom-Json
$port = ($j.detected_ports | Where-Object { $_.port.properties.vid -eq "0x2341" } |
         Select-Object -First 1).port.address
if (-not $port) { throw "board not found" }
Write-Host "port: $port"

$sp = New-Object System.IO.Ports.SerialPort($port, $Baud, "None", 8, "One")
$sp.ReadTimeout = 3000
$sp.DtrEnable = $true
try {
    $sp.Open()
    Start-Sleep -Milliseconds 1500      # let the composite CDC settle
    $sp.Write("m")
    Start-Sleep -Seconds 5              # frame types + telemetry comes back
    $out = $sp.ReadExisting()
} finally {
    if ($sp.IsOpen) { $sp.Close() }
}

if ([string]::IsNullOrWhiteSpace($out)) {
    Write-Host "NO TELEMETRY (board did not answer 'm')"
    exit 1
}
Write-Host "TELEMETRY: $($out.Trim())"
