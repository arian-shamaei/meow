<#
  wsl_linux_test.ps1 -- validate the Linux DEVICE_QUALIFIER premise on meow.

  Run this ELEVATED (Run as Administrator) with the Arduino (flashed with the
  MEOW_PROBE build) plugged into THIS Windows PC.

  It reads the board's detection flag over the Windows COM port, then hands the
  device to WSL2's Linux kernel (usbipd bind + attach --wsl) so LINUX itself
  enumerates it, detaches, and reads the flag again. The board never resets, so
  the flags are sticky: if LINUX flips 0 -> 1 across the WSL round-trip, real
  Linux requested the device_qualifier descriptor -> premise CONFIRMED.
#>
$ErrorActionPreference = 'Stop'
$usbipd = "C:\Program Files\usbipd-win\usbipd.exe"

function Get-ArduinoCom {
    $e = Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'COM\d+' -and $_.Name -match 'Arduino' } | Select-Object -First 1
    if ($e -and $e.Name -match '(COM\d+)') { return $Matches[1] }
    return $null
}
function Read-Flag {
    $port = Get-ArduinoCom
    if (-not $port) { return "NO-COM (device not on Windows right now)" }
    $sp = New-Object System.IO.Ports.SerialPort($port, 115200, 'None', 8, 'One')
    $sp.ReadTimeout = 2000; $sp.DtrEnable = $true
    try { $sp.Open(); Start-Sleep -Milliseconds 900; $out = $sp.ReadExisting() }
    finally { if ($sp.IsOpen) { $sp.Close() } }
    $line = ($out -split "`n" | Select-String 'WIN=' | Select-Object -Last 1)
    if ($line) { return "$line".Trim() } else { return "(no flag line read)" }
}

# find the board's usbip busid (VID:PID 2341:8037)
$list = & $usbipd list
Write-Host "--- usbipd list ---"; Write-Host $list
$busid = ($list | Select-String '2341:8037' | ForEach-Object { ($_.ToString().Trim() -split '\s+')[0] } | Select-Object -First 1)
if (-not $busid) { throw "Arduino 2341:8037 not found by usbipd. Plug it into this PC." }
Write-Host "busid: $busid`n"

Write-Host "BEFORE (Windows enumeration): $(Read-Flag)"

Write-Host "`n--- handing device to WSL2 Linux ---"
& $usbipd bind --busid $busid
& $usbipd attach --wsl --busid $busid
Start-Sleep -Seconds 6                      # WSL Linux kernel enumerates it here
# make Linux actually touch it (optional, harmless): list usb in WSL
wsl -d Ubuntu -u root -e bash -lc "ls -l /dev/bus/usb 2>/dev/null; lsusb 2>/dev/null | grep -i 2341 || true"
& $usbipd detach --busid $busid
Start-Sleep -Seconds 4                       # Windows re-enumerates the (unchanged) board

Write-Host "`nAFTER  (WSL Linux round-trip): $(Read-Flag)"
Write-Host "`nIf LINUX went 0 -> 1, real Linux requested device_qualifier: premise CONFIRMED."
